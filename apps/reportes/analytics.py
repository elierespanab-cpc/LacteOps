# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging
from types import SimpleNamespace

from django.db.models import Sum

logger = logging.getLogger(__name__)


def _q(value, digits="0.01"):
    return Decimal(str(value or 0)).quantize(Decimal(digits), rounding=ROUND_HALF_UP)


def _month_start(ref_date):
    return ref_date.replace(day=1)


def _next_month(ref_date):
    if ref_date.month == 12:
        return ref_date.replace(year=ref_date.year + 1, month=1, day=1)
    return ref_date.replace(month=ref_date.month + 1, day=1)


def _month_windows(months=6):
    today = date.today()
    current = _month_start(today)
    windows = []
    for offset in range(months - 1, -1, -1):
        cursor = current - timedelta(days=offset * 31)
        start = _month_start(cursor)
        end = _next_month(start)
        windows.append(
            {
                "label": start.strftime("%b %Y"),
                "start": start,
                "end": end,
            }
        )
    deduped = []
    seen = set()
    for item in windows:
        key = item["start"]
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


def _gasto_monto_usd(gasto):
    monto_usd = Decimal(str(gasto.monto_usd or 0))
    if monto_usd > 0:
        return _q(monto_usd)
    monto = Decimal(str(gasto.monto or 0))
    tasa = Decimal(str(gasto.tasa_cambio or 0))
    if gasto.moneda == "USD":
        return _q(monto)
    if tasa > 0:
        return _q(monto / tasa)
    return Decimal("0.00")


def _saldo_factura_venta(factura):
    return _q(factura.get_saldo_pendiente())


def _saldo_factura_compra(factura):
    pagado_individual = sum(
        (Decimal(str(p.monto_usd or 0)) for p in factura.pagos.all()),
        Decimal("0.00"),
    )
    pagado_consolidado = sum(
        (Decimal(str(det.monto_aplicado or 0)) for det in factura.detalle_pagos.select_related("pago").all()),
        Decimal("0.00"),
    )
    return _q(max(Decimal("0.00"), Decimal(str(factura.total or 0)) - pagado_individual - pagado_consolidado))


def calcular_add_mes(cliente, anio, mes):
    from apps.ventas.models import Cobro

    cobros = Cobro.objects.filter(
        factura__cliente=cliente, fecha__year=anio, fecha__month=mes
    ).select_related("factura")
    if not cobros.exists():
        return Decimal("0")
    retrasos = [
        max(0, (c.fecha - c.factura.fecha_vencimiento).days)
        for c in cobros
        if c.factura.fecha_vencimiento
    ]
    if not retrasos:
        return Decimal("0")
    return Decimal(str(sum(retrasos) / len(retrasos)))


def calcular_slope_add(cliente):
    hoy = date.today()
    adds = []
    for offset in range(3):
        ref = hoy.replace(day=1) - timedelta(days=offset * 30)
        adds.append(calcular_add_mes(cliente, ref.year, ref.month))
    x_mean = Decimal("1")
    y_mean = sum(adds) / Decimal("3")
    num = sum((Decimal(str(i)) - x_mean) * (adds[i] - y_mean) for i in range(3))
    den = sum((Decimal(str(i)) - x_mean) ** 2 for i in range(3))
    return num / den if den != Decimal("0") else Decimal("0")


def calcular_score_riesgo(cliente):
    from apps.ventas.models import FacturaVenta

    hoy = date.today()
    add = calcular_add_mes(cliente, hoy.year, hoy.month)
    punt = max(Decimal("0"), min(Decimal("100"), Decimal("100") - (add * Decimal("100") / Decimal("15"))))

    facturas = FacturaVenta.objects.filter(cliente=cliente, estado__in=["EMITIDA", "COBRADA"]).prefetch_related("cobros", "notas_credito")
    saldo = sum((_saldo_factura_venta(f) for f in facturas), Decimal("0.00"))
    d60 = sum(
        (
            _saldo_factura_venta(f)
            for f in facturas
            if f.fecha_vencimiento and _saldo_factura_venta(f) > 0 and (hoy - f.fecha_vencimiento).days > 60
        ),
        Decimal("0.00"),
    )
    lim = Decimal(str(cliente.limite_credito or 0))
    ru = min(Decimal("1"), saldo / lim if lim > 0 else Decimal("1"))
    pm = d60 / saldo if saldo > 0 else Decimal("0")
    solv = max(Decimal("0"), min(Decimal("100"), Decimal("100") * (Decimal("1") - ru) * (Decimal("1") - pm)))

    slope = Decimal(str(calcular_slope_add(cliente)))
    tend_raw = max(Decimal("-1"), min(Decimal("1"), -slope / Decimal("5")))
    tend = max(Decimal("0"), min(Decimal("100"), tend_raw * Decimal("100") + Decimal("50")))
    score = (Decimal("0.40") * punt + Decimal("0.30") * solv + Decimal("0.30") * tend).quantize(Decimal("0.1"))
    return {
        "score": score,
        "puntualidad": punt.quantize(Decimal("0.1")),
        "solvencia": solv.quantize(Decimal("0.1")),
        "tendencia": tend.quantize(Decimal("0.1")),
        "add_actual": add.quantize(Decimal("0.1")),
        "saldo_total": _q(saldo),
        "deuda_60d": _q(d60),
        "ratio_utilizacion": ru.quantize(Decimal("0.001")),
    }


def calcular_score_riesgo_activos(limit=12):
    from apps.ventas.models import Cliente, FacturaVenta

    clientes = Cliente.objects.filter(activo=True).order_by("nombre")
    scores = []
    for cliente in clientes:
        facturas = FacturaVenta.objects.filter(
            cliente=cliente, estado__in=["EMITIDA", "COBRADA"]
        ).prefetch_related("cobros", "notas_credito")
        saldo_total = sum((_saldo_factura_venta(f) for f in facturas), Decimal("0.00"))
        if saldo_total <= 0:
            continue
        score = calcular_score_riesgo(cliente)
        score["cliente"] = cliente
        scores.append(score)
    scores.sort(key=lambda item: (item["score"], -item["saldo_total"], item["cliente"].nombre.lower()))
    return scores[:limit]


def calcular_precio_ponderado_leche():
    from apps.almacen.models import MovimientoInventario, Producto

    hoy = date.today()
    entradas = MovimientoInventario.objects.filter(
        tipo="ENTRADA",
        fecha__date__gte=hoy - timedelta(days=7),
        producto__es_materia_prima_base=True,
    )
    total_q = sum((e.cantidad for e in entradas), Decimal("0.00"))
    if not total_q:
        prods = Producto.objects.filter(es_materia_prima_base=True, activo=True)
        if not prods.exists():
            return {"precio": None, "sin_datos_recientes": True}
        tq = sum((p.stock_actual for p in prods), Decimal("0.00")) or Decimal("1")
        pp = sum((p.costo_promedio * p.stock_actual for p in prods), Decimal("0.00")) / tq
        return {"precio": pp.quantize(Decimal("0.000001")), "sin_datos_recientes": True}
    total_v = sum((e.cantidad * e.costo_unitario for e in entradas), Decimal("0.00"))
    return {"precio": (total_v / total_q).quantize(Decimal("0.000001")), "sin_datos_recientes": False}


def construir_serie_rendimiento_leche_diario(days=14):
    from apps.produccion.models import OrdenProduccion

    hoy = date.today()
    data = []
    for offset in range(days - 1, -1, -1):
        cursor = hoy - timedelta(days=offset)
        ordenes = (
            OrdenProduccion.objects.filter(
                estado="CERRADA",
                fecha_apertura=cursor,
            )
            .select_related("receta")
        )
        rendimientos = []
        for orden in ordenes:
            rendimiento = Decimal(str(orden.rendimiento_real or 0))
            if rendimiento <= 0:
                continue
            if (orden.receta.unidad_rendimiento or "L/Kg") == "Kg/L":
                rendimiento = (Decimal("1.00") / rendimiento).quantize(Decimal("0.0001"))
            else:
                rendimiento = rendimiento.quantize(Decimal("0.0001"))
            rendimientos.append(rendimiento)
        promedio = (
            _q(sum(rendimientos, Decimal("0.00")) / Decimal(str(len(rendimientos))), "0.0001")
            if rendimientos
            else Decimal("0.0000")
        )
        data.append(
            {
                "label": cursor.strftime("%d/%m"),
                "value": float(promedio),
            }
        )
    return {
        "labels": [item["label"] for item in data],
        "values": [item["value"] for item in data],
    }


def calcular_cce():
    from apps.ventas.models import Cobro, FacturaVenta
    from apps.compras.models import Pago, DetallePagoFactura
    from apps.almacen.models import Producto

    hoy = date.today()
    hace90 = hoy - timedelta(days=90)

    cobros = Cobro.objects.filter(fecha__gte=hace90).select_related("factura")
    dso_v = [(c.fecha - c.factura.fecha).days for c in cobros if c.factura and c.factura.fecha]
    dso = Decimal(str(sum(dso_v) / len(dso_v))).quantize(Decimal("0.1")) if dso_v else Decimal("0.0")

    inv = sum(
        (Decimal(str(p.stock_actual)) * Decimal(str(p.costo_promedio)) for p in Producto.objects.filter(activo=True, es_producto_terminado=True)),
        Decimal("0.00"),
    )
    cv = sum(
        (Decimal(str(f.total or 0)) for f in FacturaVenta.objects.filter(fecha__gte=hace90, estado__in=["EMITIDA", "COBRADA"])),
        Decimal("0.00"),
    ) or Decimal("1.00")
    dio = (inv / cv * Decimal("90")).quantize(Decimal("0.1"))

    pagos_individuales = Pago.objects.filter(fecha__gte=hace90, factura__isnull=False).select_related("factura")
    pagos_consolidados = DetallePagoFactura.objects.filter(
        pago__fecha__gte=hace90
    ).select_related("pago", "factura")
    dpo_v = [(p.fecha - p.factura.fecha).days for p in pagos_individuales if p.factura and p.factura.fecha]
    dpo_v.extend(
        [
            (detalle.pago.fecha - detalle.factura.fecha).days
            for detalle in pagos_consolidados
            if detalle.factura and detalle.factura.fecha and detalle.pago
        ]
    )
    dpo = Decimal(str(sum(dpo_v) / len(dpo_v))).quantize(Decimal("0.1")) if dpo_v else Decimal("0.0")

    return {
        "cce": (dso + dio - dpo).quantize(Decimal("0.1")),
        "dso": dso,
        "dio": dio,
        "dpo": dpo,
    }


def calcular_proyeccion_caja_7d():
    from apps.bancos.models import CuentaBancaria
    from apps.ventas.models import FacturaVenta
    from apps.compras.models import FacturaCompra, GastoServicio
    from apps.socios.models import PrestamoPorSocio
    from apps.core.models import TasaCambio

    hoy = date.today()
    limite = hoy + timedelta(days=7)
    ultima_tasa = TasaCambio.objects.filter(fecha__lte=hoy).order_by("-fecha").first()
    tasa_ref = Decimal(str(ultima_tasa.tasa if ultima_tasa else 1))

    saldo_usd = Decimal("0.00")
    for cuenta in CuentaBancaria.objects.filter(activa=True):
        saldo = Decimal(str(cuenta.saldo_actual or 0))
        saldo_usd += saldo if cuenta.moneda == "USD" else (saldo / tasa_ref if tasa_ref > 0 else Decimal("0.00"))
    saldo_usd = _q(saldo_usd)

    cobros_por_fecha = defaultdict(Decimal)
    facturas_venta = FacturaVenta.objects.filter(
        estado__in=["EMITIDA", "COBRADA"], fecha_vencimiento__range=[hoy, limite]
    ).prefetch_related("cobros", "notas_credito")
    for factura in facturas_venta:
        saldo = _saldo_factura_venta(factura)
        if saldo > 0 and factura.fecha_vencimiento:
            cobros_por_fecha[factura.fecha_vencimiento] += saldo

    pagos_por_fecha = defaultdict(Decimal)
    facturas_compra = FacturaCompra.objects.filter(
        estado__in=["RECIBIDA", "APROBADA"], fecha__lte=limite
    ).prefetch_related("pagos", "detalle_pagos__pago")
    for factura in facturas_compra:
        fecha_objetivo = factura.fecha_vencimiento or factura.fecha
        if fecha_objetivo and hoy <= fecha_objetivo <= limite:
            pagos_por_fecha[fecha_objetivo] += _saldo_factura_compra(factura)

    gastos = GastoServicio.objects.filter(
        estado="PENDIENTE", fecha_emision__lte=limite
    ).select_related("proveedor")
    for gasto in gastos:
        fecha_objetivo = gasto.fecha_vencimiento or gasto.fecha_emision
        if fecha_objetivo and hoy <= fecha_objetivo <= limite:
            pagos_por_fecha[fecha_objetivo] += _gasto_monto_usd(gasto)

    prestamos_por_fecha = defaultdict(Decimal)
    prestamos = PrestamoPorSocio.objects.filter(
        estado="ACTIVO", fecha_vencimiento__range=[hoy, limite]
    )
    for prestamo in prestamos:
        prestamos_por_fecha[prestamo.fecha_vencimiento] += Decimal(str(prestamo.monto_usd or 0))

    serie = []
    saldo_cursor = saldo_usd
    for offset in range(0, 8):
        cursor = hoy + timedelta(days=offset)
        cobros = _q(cobros_por_fecha.get(cursor, Decimal("0.00")))
        pagos = _q(pagos_por_fecha.get(cursor, Decimal("0.00")))
        prestamos_dia = _q(prestamos_por_fecha.get(cursor, Decimal("0.00")))
        saldo_cursor = _q(saldo_cursor + cobros - pagos - prestamos_dia)
        serie.append(
            {
                "fecha": cursor.strftime("%d/%m"),
                "saldo": saldo_cursor,
                "cobros": cobros,
                "pagos": pagos,
                "prestamos": prestamos_dia,
            }
        )

    cobros_total = sum((item["cobros"] for item in serie), Decimal("0.00"))
    pagos_total = sum((item["pagos"] for item in serie), Decimal("0.00"))
    prestamos_total = sum((item["prestamos"] for item in serie), Decimal("0.00"))
    return {
        "saldo_usd": saldo_usd,
        "cobros_esperados": _q(cobros_total),
        "pagos_a_vencer": _q(pagos_total),
        "prestamos_venciendo": _q(prestamos_total),
        "proyeccion_neta": _q(serie[-1]["saldo"] if serie else saldo_usd),
        "serie": serie,
    }


def obtener_notificaciones_dashboard(limit=20):
    from apps.ventas.models import FacturaVenta
    from apps.almacen.models import Producto
    from apps.core.models import Notificacion, TasaCambio
    from apps.socios.models import PrestamoPorSocio

    hoy = date.today()
    limite_fecha = hoy + timedelta(days=7)
    notifs = {}

    for notif in Notificacion.objects.filter(activa=True).order_by("fecha_referencia", "id"):
        key = (notif.tipo, notif.entidad, notif.entidad_id)
        notifs[key] = SimpleNamespace(
            id=notif.id,
            persistida=True,
            tipo=notif.tipo,
            tipo_label=notif.get_tipo_display(),
            titulo=notif.titulo,
            mensaje=notif.mensaje,
            entidad=notif.entidad,
            entidad_id=notif.entidad_id,
            fecha_referencia=notif.fecha_referencia,
        )

    for factura in FacturaVenta.objects.filter(
        estado__in=["EMITIDA", "COBRADA"], fecha_vencimiento__range=[hoy, limite_fecha]
    ).select_related("cliente").prefetch_related("cobros", "notas_credito"):
        saldo = _saldo_factura_venta(factura)
        if saldo <= 0:
            continue
        key = ("CXC_VENCIENDO", "FacturaVenta", factura.pk)
        notifs.setdefault(
            key,
            SimpleNamespace(
                id=f"dyn-cxc-{factura.pk}",
                persistida=False,
                tipo="CXC_VENCIENDO",
                tipo_label="CxC Venciendo",
                titulo=f"Factura {factura.numero} con saldo activo",
                mensaje=f"Cliente: {factura.cliente}. Pendiente: {saldo} USD",
                entidad="FacturaVenta",
                entidad_id=factura.pk,
                fecha_referencia=factura.fecha_vencimiento,
            ),
        )

    for producto in Producto.objects.filter(activo=True).exclude(stock_minimo=None):
        if Decimal(str(producto.stock_actual or 0)) < Decimal(str(producto.stock_minimo or 0)):
            key = ("STOCK_MINIMO", "Producto", producto.pk)
            notifs.setdefault(
                key,
                SimpleNamespace(
                    id=f"dyn-stock-{producto.pk}",
                    persistida=False,
                    tipo="STOCK_MINIMO",
                    tipo_label="Stock Mínimo",
                    titulo=f"Stock bajo: {producto.nombre}",
                    mensaje=f"Actual: {producto.stock_actual} | Mínimo: {producto.stock_minimo}",
                    entidad="Producto",
                    entidad_id=producto.pk,
                    fecha_referencia=hoy,
                ),
            )

    if not TasaCambio.objects.filter(fecha=hoy).exists():
        key = ("TASA_NO_CARGADA", "TasaCambio", 0)
        notifs.setdefault(
            key,
            SimpleNamespace(
                id="dyn-tasa-hoy",
                persistida=False,
                tipo="TASA_NO_CARGADA",
                tipo_label="Tasa BCV No Cargada",
                titulo="Tasa BCV no cargada para hoy",
                mensaje="No hay tasa registrada para la fecha actual.",
                entidad="TasaCambio",
                entidad_id=0,
                fecha_referencia=hoy,
            ),
        )

    for prestamo in PrestamoPorSocio.objects.filter(
        estado="ACTIVO", fecha_vencimiento__range=[hoy, limite_fecha]
    ).select_related("socio"):
        key = ("PRESTAMO_VENCIENDO", "PrestamoPorSocio", prestamo.pk)
        notifs.setdefault(
            key,
            SimpleNamespace(
                id=f"dyn-prest-{prestamo.pk}",
                persistida=False,
                tipo="PRESTAMO_VENCIENDO",
                tipo_label="Préstamo Venciendo",
                titulo=f"Préstamo {prestamo.numero} vence pronto",
                mensaje=f"Socio: {prestamo.socio} | Saldo base: {prestamo.monto_usd} USD",
                entidad="PrestamoPorSocio",
                entidad_id=prestamo.pk,
                fecha_referencia=prestamo.fecha_vencimiento,
            ),
        )

    return sorted(notifs.values(), key=lambda item: (item.fecha_referencia, str(item.id)))[:limit]


def _inventario_variacion_mes(start, end):
    from apps.almacen.models import MovimientoInventario

    movimientos = MovimientoInventario.objects.filter(
        fecha__date__gte=start, fecha__date__lt=end
    )
    variacion = Decimal("0.00")
    for mov in movimientos:
        valor = Decimal(str(mov.cantidad or 0)) * Decimal(str(mov.costo_unitario or 0))
        variacion += valor if mov.tipo == "ENTRADA" else -valor
    return _q(variacion)


def construir_graficos_dashboard(months=6, top_n=8):
    from apps.ventas.models import FacturaVenta
    from apps.compras.models import FacturaCompra, GastoServicio
    from apps.produccion.models import OrdenProduccion

    charts = {}

    ventas_cliente = defaultdict(Decimal)
    for factura in FacturaVenta.objects.exclude(estado="ANULADA").select_related("cliente"):
        ventas_cliente[factura.cliente.nombre if factura.cliente else "Sin cliente"] += Decimal(str(factura.total or 0))
    top_clientes = sorted(ventas_cliente.items(), key=lambda item: item[1], reverse=True)[:top_n]
    charts["ventas_por_cliente"] = {
        "labels": [item[0] for item in top_clientes],
        "values": [float(_q(item[1])) for item in top_clientes],
    }

    windows = _month_windows(months=months)
    ventas_mes = []
    rentabilidad_mes = []
    for window in windows:
        ventas_total = sum(
            (
                Decimal(str(f.total or 0))
                for f in FacturaVenta.objects.exclude(estado="ANULADA").filter(
                    fecha__gte=window["start"], fecha__lt=window["end"]
                )
            ),
            Decimal("0.00"),
        )
        compras_total = sum(
            (
                Decimal(str(f.total or 0))
                for f in FacturaCompra.objects.exclude(estado="ANULADA").filter(
                    fecha__gte=window["start"], fecha__lt=window["end"]
                )
            ),
            Decimal("0.00"),
        )
        gastos_total = sum(
            (
                _gasto_monto_usd(g)
                for g in GastoServicio.objects.exclude(estado="ANULADO").filter(
                    fecha_emision__gte=window["start"], fecha_emision__lt=window["end"]
                )
            ),
            Decimal("0.00"),
        )
        variacion_inventario = _inventario_variacion_mes(window["start"], window["end"])
        rentabilidad = _q(ventas_total - variacion_inventario - compras_total - gastos_total)

        ventas_mes.append(float(_q(ventas_total)))
        rentabilidad_mes.append(float(rentabilidad))

    labels_meses = [item["label"] for item in windows]
    charts["ventas_mensual"] = {"labels": labels_meses, "values": ventas_mes}
    charts["rentabilidad_mensual"] = {"labels": labels_meses, "values": rentabilidad_mes}

    cxc_cliente = defaultdict(Decimal)
    for factura in FacturaVenta.objects.filter(estado__in=["EMITIDA", "COBRADA"]).select_related("cliente").prefetch_related("cobros", "notas_credito"):
        saldo = _saldo_factura_venta(factura)
        if saldo > 0:
            cxc_cliente[factura.cliente.nombre if factura.cliente else "Sin cliente"] += saldo
    top_cxc = sorted(cxc_cliente.items(), key=lambda item: item[1], reverse=True)[:top_n]
    charts["concentracion_cxc"] = {
        "labels": [item[0] for item in top_cxc],
        "values": [float(_q(item[1])) for item in top_cxc],
    }

    cxp_proveedor = defaultdict(Decimal)
    for factura in FacturaCompra.objects.filter(estado__in=["RECIBIDA", "APROBADA"]).select_related("proveedor").prefetch_related("pagos", "detalle_pagos__pago"):
        saldo = _saldo_factura_compra(factura)
        if saldo > 0:
            cxp_proveedor[factura.proveedor.nombre if factura.proveedor else "Sin proveedor"] += saldo
    for gasto in GastoServicio.objects.filter(estado="PENDIENTE").select_related("proveedor"):
        cxp_proveedor[gasto.proveedor.nombre if gasto.proveedor else "Sin proveedor"] += _gasto_monto_usd(gasto)
    top_cxp = sorted(cxp_proveedor.items(), key=lambda item: item[1], reverse=True)[:top_n]
    charts["concentracion_cxp"] = {
        "labels": [item[0] for item in top_cxp],
        "values": [float(_q(item[1])) for item in top_cxp],
    }

    charts["rendimiento_leche_diario"] = construir_serie_rendimiento_leche_diario()

    return charts
