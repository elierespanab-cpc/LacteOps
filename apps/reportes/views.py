import datetime
from decimal import Decimal, ROUND_HALF_UP
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.db.models import Q, Sum, F, Value, DecimalField
from django.db.models.functions import Coalesce

from apps.core.models import ConfiguracionEmpresa
from apps.ventas.models import FacturaVenta, Cliente, DetalleFacturaVenta
from apps.compras.models import (
    FacturaCompra,
    Proveedor,
    DetalleFacturaCompra,
    GastoServicio,
)
from apps.produccion.models import OrdenProduccion, ConsumoOP, SalidaOrden
from apps.bancos.models import CuentaBancaria
from apps.almacen.models import Producto
from apps.compras.models import GastoServicio as Gs
from apps.reportes.excel import exportar_excel
from apps.core.rbac import usuario_en_grupo


def _check_reporte_perm(request):
    """B9 — Verifica que el usuario tiene permiso de ver reportes."""
    if request.user.is_superuser:
        return
    if not request.user.has_perm("reportes.view_reportelink"):
        raise PermissionDenied("No tiene permiso para acceder a los reportes.")


def _monto_usd_linea(subtotal, moneda, tasa_cambio):
    subtotal = Decimal(str(subtotal or 0))
    if moneda == "USD":
        return subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    tasa = Decimal(str(tasa_cambio or 0))
    if tasa > 0:
        return (subtotal / tasa).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Decimal("0.00")


def _estatus_por_saldo(saldo, total, etiqueta_cero, etiqueta_parcial, etiqueta_pendiente):
    saldo = Decimal(str(saldo or 0))
    total = Decimal(str(total or 0))
    if saldo <= 0:
        return etiqueta_cero
    if saldo < total:
        return etiqueta_parcial
    return etiqueta_pendiente


@login_required
def reporte_ventas(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_desde = request.GET.get("fecha_desde")
    fecha_hasta = request.GET.get("fecha_hasta")
    clientes_ids = request.GET.getlist("cliente")
    productos_ids = request.GET.getlist("articulo")
    estados = request.GET.getlist("estado")
    agrupar_por_cliente = request.GET.get("agrupar_por_cliente") == "1"

    qs = DetalleFacturaVenta.objects.select_related(
        "factura", "factura__cliente", "producto"
    ).all()

    if fecha_desde:
        qs = qs.filter(factura__fecha__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(factura__fecha__lte=fecha_hasta)
    if clientes_ids:
        qs = qs.filter(factura__cliente_id__in=clientes_ids)
    if productos_ids:
        qs = qs.filter(producto_id__in=productos_ids)
    if estados:
        qs = qs.filter(factura__estado__in=estados)

    if agrupar_por_cliente:
        detalles = list(
            qs.order_by("factura__cliente__nombre", "factura__fecha", "factura__numero")
        )
    else:
        detalles = list(qs.order_by("factura__fecha", "factura__numero"))

    filas = []
    total_general = Decimal("0.00")
    subtotal_cliente = Decimal("0.00")
    cliente_actual = None
    cliente_actual_nombre = ""
    cliente_actual_rif = ""

    for detalle in detalles:
        detalle.monto_usd = _monto_usd_linea(
            detalle.subtotal, detalle.factura.moneda, detalle.factura.tasa_cambio
        )
        detalle.estatus_cobro = _estatus_por_saldo(
            detalle.factura.get_saldo_pendiente(),
            detalle.factura.total,
            "Cobrada",
            "Parcialmente Pendiente",
            "Pendiente",
        )

        if agrupar_por_cliente:
            cliente = detalle.factura.cliente
            cliente_id = cliente.pk if cliente else None
            nombre_cliente = cliente.nombre if cliente else "Sin cliente"
            rif_cliente = cliente.rif if cliente else ""

            if cliente_actual is None:
                cliente_actual = cliente_id
                cliente_actual_nombre = nombre_cliente
                cliente_actual_rif = rif_cliente
            elif cliente_actual != cliente_id:
                filas.append(
                    {
                        "tipo": "subtotal",
                        "cliente": cliente_actual_nombre,
                        "rif": cliente_actual_rif,
                        "monto_total": subtotal_cliente,
                    }
                )
                subtotal_cliente = Decimal("0.00")
                cliente_actual = cliente_id
                cliente_actual_nombre = nombre_cliente
                cliente_actual_rif = rif_cliente

            subtotal_cliente += detalle.monto_usd

        total_general += detalle.monto_usd
        filas.append({"tipo": "detalle", "detalle": detalle})

    if agrupar_por_cliente and cliente_actual is not None:
        filas.append(
            {
                "tipo": "subtotal",
                "cliente": cliente_actual_nombre,
                "rif": cliente_actual_rif,
                "monto_total": subtotal_cliente,
            }
        )

    parametros = {}
    if fecha_desde:
        parametros["Desde"] = fecha_desde
    if fecha_hasta:
        parametros["Hasta"] = fecha_hasta
    if clientes_ids:
        parametros["Clientes"] = ", ".join(clientes_ids)
    if productos_ids:
        parametros["Productos"] = ", ".join(productos_ids)
    if estados:
        parametros["Estados"] = ", ".join(estados)
    if agrupar_por_cliente:
        parametros["Agrupar por cliente"] = "Sí"

    if "exportar" in request.GET:
        columnas = [
            "Numero",
            "Fecha",
            "Cliente",
            "Articulo",
            "Cantidad",
            "Precio Unitario",
            "Subtotal",
            "Moneda",
            "Monto USD",
            "Estatus",
            "Estado",
        ]
        filas_export = []
        for d in detalles:
            monto_usd = _monto_usd_linea(
                d.subtotal, d.factura.moneda, d.factura.tasa_cambio
            )
            filas_export.append(
                [
                    d.factura.numero,
                    d.factura.fecha,
                    d.factura.cliente.nombre if d.factura.cliente else "",
                    f"{d.producto.codigo} - {d.producto.nombre}",
                    d.cantidad,
                    d.precio_unitario,
                    d.subtotal,
                    d.factura.moneda,
                    monto_usd,
                    d.estatus_cobro,
                    d.factura.estado,
                ]
            )
        return exportar_excel(
            "reporte_ventas",
            columnas,
            [[str(v) for v in fila] for fila in filas_export],
            empresa=empresa,
            parametros=parametros,
        )

    context = {
        "empresa": empresa,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "agrupar_por_cliente": agrupar_por_cliente,
        "filas": filas,
        "total_general": total_general,
        "clientes_ids": clientes_ids,
        "productos_ids": productos_ids,
        "clientes": Cliente.objects.all(),
        "productos": Producto.objects.all(),
    }
    return render(request, "reportes/ventas.html", context)


@login_required
def reporte_cxc(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_corte = request.GET.get("fecha_corte")
    hasta = (
        datetime.datetime.strptime(fecha_corte, "%Y-%m-%d").date()
        if fecha_corte
        else datetime.date.today()
    )

    # DIM-06-001: incluye EMITIDA y COBRADA (puede haber cobro parcial en COBRADA)
    facturas = (
        FacturaVenta.objects.filter(estado__in=["EMITIDA", "COBRADA"], fecha__lte=hasta)
        .select_related("cliente")
        .prefetch_related("cobros", "notas_credito")
    )

    resultados = []
    totales = {
        "total": Decimal("0.00"),
        "cobrado": Decimal("0.00"),
        "nc": Decimal("0.00"),
        "neto_pendiente": Decimal("0.00"),
        "pendiente": Decimal("0.00"),
        "s_0_30": Decimal("0.00"),
        "s_31_60": Decimal("0.00"),
        "s_61_90": Decimal("0.00"),
        "s_90_plus": Decimal("0.00"),
    }

    for fv in facturas:
        monto_cobrado = sum(
            Decimal(str(c.monto_usd))
            for c in fv.cobros.all()
            if c.fecha <= hasta and c.monto_usd
        )
        nc_emitidas = sum(
            Decimal(str(nc.total))
            for nc in fv.notas_credito.all()
            if nc.estado == "EMITIDA" and nc.fecha <= hasta and nc.total
        )
        neto_pendiente = max(
            Decimal("0.00"), Decimal(str(fv.total)) - monto_cobrado - nc_emitidas
        )
        if neto_pendiente > 0:
            dias_vencida = (
                (hasta - fv.fecha_vencimiento).days if fv.fecha_vencimiento else 0
            )
            if dias_vencida < 0:
                dias_vencida = 0

            saldo_0_30 = neto_pendiente if 0 <= dias_vencida <= 30 else Decimal("0.00")
            saldo_31_60 = neto_pendiente if 31 <= dias_vencida <= 60 else Decimal("0.00")
            saldo_61_90 = neto_pendiente if 61 <= dias_vencida <= 90 else Decimal("0.00")
            saldo_90_plus = neto_pendiente if dias_vencida > 90 else Decimal("0.00")

            resultados.append(
                {
                    "factura": fv,
                    "total": Decimal(str(fv.total)),
                    "monto_cobrado": monto_cobrado,
                    "nc_emitidas": nc_emitidas,
                    "neto_pendiente": neto_pendiente,
                    "dias_vencida": dias_vencida,
                    "s_0_30": saldo_0_30,
                    "s_31_60": saldo_31_60,
                    "s_61_90": saldo_61_90,
                    "s_90_plus": saldo_90_plus,
                }
            )
            totales["total"] += Decimal(str(fv.total))
            totales["cobrado"] += monto_cobrado
            totales["nc"] += nc_emitidas
            totales["neto_pendiente"] += neto_pendiente
            totales["pendiente"] += neto_pendiente
            totales["s_0_30"] += saldo_0_30
            totales["s_31_60"] += saldo_31_60
            totales["s_61_90"] += saldo_61_90
            totales["s_90_plus"] += saldo_90_plus

    resultados.sort(
        key=lambda item: (
            item["factura"].cliente.nombre if item["factura"].cliente else "",
            item["factura"].fecha,
            item["factura"].numero,
        )
    )

    parametros = {}
    parametros["Fecha corte"] = fecha_corte or str(hasta)

    if "exportar" in request.GET:
        columnas = [
            "Cliente",
            "No. Factura",
            "Emision",
            "Vencimiento",
            "Monto Total",
            "Cobrado",
            "NC",
            "Neto Pendiente",
            "Dias Vencida",
            "0-30 Dias",
            "31-60 Dias",
            "61-90 Dias",
            "+90 Dias",
        ]
        filas = []
        for item in resultados:
            fv = item["factura"]
            filas.append(
                [
                    fv.cliente.nombre if fv.cliente else "",
                    fv.numero,
                    fv.fecha,
                    fv.fecha_vencimiento,
                    item["total"],
                    item["monto_cobrado"],
                    item["nc_emitidas"],
                    item["neto_pendiente"],
                    item["dias_vencida"],
                    item["s_0_30"],
                    item["s_31_60"],
                    item["s_61_90"],
                    item["s_90_plus"],
                ]
            )
        return exportar_excel(
            "reporte_cxc",
            columnas,
            [[str(v) for v in fila] for fila in filas],
            empresa=empresa,
            parametros=parametros,
        )

    context = {
        "empresa": empresa,
        "fecha_corte": hasta,
        "resultados": resultados,
        "totales": totales,
    }
    return render(request, "reportes/cxc.html", context)


@login_required
def reporte_compras(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_desde = request.GET.get("fecha_desde")
    fecha_hasta = request.GET.get("fecha_hasta")
    proveedor_ids = request.GET.getlist("proveedor")
    productos_ids = request.GET.getlist("articulo")
    estados = request.GET.getlist("estado")
    agrupar_por_proveedor = request.GET.get("agrupar_por_proveedor") == "1"

    qs = DetalleFacturaCompra.objects.select_related(
        "factura", "factura__proveedor", "producto"
    ).all()

    if fecha_desde:
        qs = qs.filter(factura__fecha__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(factura__fecha__lte=fecha_hasta)
    if proveedor_ids:
        qs = qs.filter(factura__proveedor_id__in=proveedor_ids)
    if productos_ids:
        qs = qs.filter(producto_id__in=productos_ids)
    if estados:
        qs = qs.filter(factura__estado__in=estados)

    if agrupar_por_proveedor:
        detalles = list(
            qs.order_by("factura__proveedor__nombre", "factura__fecha", "factura__numero")
        )
    else:
        detalles = list(qs.order_by("factura__fecha", "factura__numero"))

    filas = []
    total_general = Decimal("0.00")
    subtotal_proveedor = Decimal("0.00")
    proveedor_actual = None
    proveedor_actual_nombre = ""
    proveedor_actual_rif = ""

    for detalle in detalles:
        detalle.monto_usd = _monto_usd_linea(
            detalle.subtotal, detalle.factura.moneda, detalle.factura.tasa_cambio
        )
        detalle.estatus_pago = _estatus_por_saldo(
            detalle.factura.get_saldo_pendiente(),
            detalle.factura.total,
            "Pagada",
            "Parcialmente Pendiente",
            "Pendiente",
        )

        if agrupar_por_proveedor:
            proveedor = detalle.factura.proveedor
            proveedor_id = proveedor.pk if proveedor else None
            nombre_proveedor = proveedor.nombre if proveedor else "Sin proveedor"
            rif_proveedor = proveedor.rif if proveedor else ""

            if proveedor_actual is None:
                proveedor_actual = proveedor_id
                proveedor_actual_nombre = nombre_proveedor
                proveedor_actual_rif = rif_proveedor
            elif proveedor_actual != proveedor_id:
                filas.append(
                    {
                        "tipo": "subtotal",
                        "proveedor": proveedor_actual_nombre,
                        "rif": proveedor_actual_rif,
                        "monto_total": subtotal_proveedor,
                    }
                )
                subtotal_proveedor = Decimal("0.00")
                proveedor_actual = proveedor_id
                proveedor_actual_nombre = nombre_proveedor
                proveedor_actual_rif = rif_proveedor

            subtotal_proveedor += detalle.monto_usd

        total_general += detalle.monto_usd
        filas.append({"tipo": "detalle", "detalle": detalle})

    if agrupar_por_proveedor and proveedor_actual is not None:
        filas.append(
            {
                "tipo": "subtotal",
                "proveedor": proveedor_actual_nombre,
                "rif": proveedor_actual_rif,
                "monto_total": subtotal_proveedor,
            }
        )

    parametros = {}
    if fecha_desde:
        parametros["Desde"] = fecha_desde
    if fecha_hasta:
        parametros["Hasta"] = fecha_hasta
    if proveedor_ids:
        parametros["Proveedores"] = ", ".join(proveedor_ids)
    if estados:
        parametros["Estados"] = ", ".join(estados)
    if agrupar_por_proveedor:
        parametros["Agrupar por proveedor"] = "Sí"

    if "exportar" in request.GET:
        columnas = [
            "Numero",
            "Fecha",
            "Proveedor",
            "Articulo",
            "Cantidad",
            "Costo Unitario",
            "Subtotal",
            "Moneda",
            "Monto USD",
            "Estatus",
            "Estado",
        ]
        filas_export = []
        for d in detalles:
            monto_usd = _monto_usd_linea(
                d.subtotal, d.factura.moneda, d.factura.tasa_cambio
            )
            filas_export.append(
                [
                    d.factura.numero,
                    d.factura.fecha,
                    d.factura.proveedor.nombre if d.factura.proveedor else "",
                    f"{d.producto.codigo} - {d.producto.nombre}",
                    d.cantidad,
                    d.costo_unitario,
                    d.subtotal,
                    d.factura.moneda,
                    monto_usd,
                    d.estatus_pago,
                    d.factura.estado,
                ]
            )
        return exportar_excel(
            "reporte_compras",
            columnas,
            [[str(v) for v in fila] for fila in filas_export],
            empresa=empresa,
            parametros=parametros,
        )

    context = {
        "empresa": empresa,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "agrupar_por_proveedor": agrupar_por_proveedor,
        "filas": filas,
        "total_general": total_general,
        "proveedor_ids": proveedor_ids,
        "productos_ids": productos_ids,
        "proveedores": Proveedor.objects.all(),
        "productos": Producto.objects.all(),
    }
    return render(request, "reportes/compras.html", context)


@login_required
def reporte_cxp(request):
    """
    B3 — CxP con pagos parciales: usa annotate + Coalesce para calcular saldo.
    Filtra facturas APROBADA (no RECIBIDA) porque los pagos van contra APROBADAS.
    """
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_corte = request.GET.get("fecha_corte")
    tipo_reporte = request.GET.get("tipo", "TODOS")
    hasta = (
        datetime.datetime.strptime(fecha_corte, "%Y-%m-%d").date()
        if fecha_corte
        else datetime.date.today()
    )

    resultados = []
    totales = {
        "total": Decimal("0.00"),
        "pendiente": Decimal("0.00"),
        "s_0_30": Decimal("0.00"),
        "s_31_60": Decimal("0.00"),
        "s_61_90": Decimal("0.00"),
        "s_90_plus": Decimal("0.00"),
    }

    if tipo_reporte in ["TODOS", "COMPRAS"]:
        # B3 fix: estado APROBADA + Coalesce para pagos parciales
        facturas = (
            FacturaCompra.objects.filter(estado="APROBADA", fecha__lte=hasta)
            .select_related("proveedor")
            .annotate(
                total_pagado=Coalesce(
                    Sum("pagos__monto_usd"),
                    Value(Decimal("0.00")),
                    output_field=DecimalField(),
                )
            )
            .annotate(saldo=F("total") - F("total_pagado"))
            .filter(saldo__gt=0)
        )

        for fv in facturas:
            saldo = Decimal(str(fv.saldo))
            dias_vencida = (
                (hasta - fv.fecha_vencimiento).days if fv.fecha_vencimiento else 0
            )
            if dias_vencida < 0:
                dias_vencida = 0

            s_0 = saldo if 0 <= dias_vencida <= 30 else Decimal("0.00")
            s_31 = saldo if 31 <= dias_vencida <= 60 else Decimal("0.00")
            s_61 = saldo if 61 <= dias_vencida <= 90 else Decimal("0.00")
            s_90 = saldo if dias_vencida > 90 else Decimal("0.00")

            resultados.append(
                {
                    "es_gasto": False,
                    "documento": fv,
                    "saldo": saldo,
                    "dias": dias_vencida,
                    "s_0": s_0,
                    "s_31": s_31,
                    "s_61": s_61,
                    "s_90": s_90,
                }
            )
            totales["pendiente"] += saldo
            totales["s_0_30"] += s_0
            totales["s_31_60"] += s_31
            totales["s_61_90"] += s_61
            totales["s_90_plus"] += s_90

    if tipo_reporte in ["TODOS", "GASTOS_SERVICIOS"]:
        gastos = GastoServicio.objects.filter(
            estado="PENDIENTE", fecha_emision__lte=hasta
        ).select_related("proveedor")
        for gs in gastos:
            saldo = Decimal(str(gs.monto_usd))
            dias_vencida = (
                (hasta - gs.fecha_vencimiento).days if gs.fecha_vencimiento else 0
            )
            if dias_vencida < 0:
                dias_vencida = 0

            s_0 = saldo if 0 <= dias_vencida <= 30 else Decimal("0.00")
            s_31 = saldo if 31 <= dias_vencida <= 60 else Decimal("0.00")
            s_61 = saldo if 61 <= dias_vencida <= 90 else Decimal("0.00")
            s_90 = saldo if dias_vencida > 90 else Decimal("0.00")

            resultados.append(
                {
                    "es_gasto": True,
                    "documento": gs,
                    "saldo": saldo,
                    "dias": dias_vencida,
                    "s_0": s_0,
                    "s_31": s_31,
                    "s_61": s_61,
                    "s_90": s_90,
                }
            )
            totales["pendiente"] += saldo
            totales["s_0_30"] += s_0
            totales["s_31_60"] += s_31
            totales["s_61_90"] += s_61
            totales["s_90_plus"] += s_90

    parametros = {
        "Fecha corte": fecha_corte or str(hasta),
        "Tipo": tipo_reporte,
    }

    if "exportar" in request.GET:
        columnas = [
            "Proveedor",
            "Tipo Doc.",
            "No. Documento",
            "Vencimiento",
            "Dias Vencida",
            "Monto USD Original",
            "Saldo Pendiente USD",
            "0-30 Dias",
            "31-60 Dias",
            "61-90 Dias",
            "+90 Dias",
        ]
        filas = []
        for item in resultados:
            doc = item["documento"]
            monto_original = (
                doc.monto_usd
                if item["es_gasto"]
                else (
                    doc.total_usd
                    if hasattr(doc, "total_usd") and doc.total_usd
                    else doc.total
                )
            )
            filas.append(
                [
                    doc.proveedor.nombre if doc.proveedor else "",
                    "Gasto/Servicio" if item["es_gasto"] else "Factura Compra",
                    doc.numero,
                    doc.fecha_vencimiento,
                    item["dias"],
                    monto_original,
                    item["saldo"],
                    item["s_0"],
                    item["s_31"],
                    item["s_61"],
                    item["s_90"],
                ]
            )
        return exportar_excel(
            "reporte_cxp",
            columnas,
            [[str(v) for v in fila] for fila in filas],
            empresa=empresa,
            parametros=parametros,
        )

    context = {
        "empresa": empresa,
        "fecha_corte": hasta,
        "tipo": tipo_reporte,
        "resultados": resultados,
        "totales": totales,
    }
    return render(request, "reportes/cxp.html", context)


@login_required
def reporte_produccion(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_desde = request.GET.get("fecha_desde")
    fecha_hasta = request.GET.get("fecha_hasta")
    producto_ids = request.GET.getlist("producto")

    qs = OrdenProduccion.objects.all()
    if fecha_desde:
        qs = qs.filter(fecha_apertura__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha_apertura__lte=fecha_hasta)
    if producto_ids:
        qs = qs.filter(salidas__producto_id__in=producto_ids).distinct()

    ordenes = list(
        qs.prefetch_related("salidas__producto__unidad_medida", "consumos").order_by(
            "-fecha_apertura"
        )
    )

    for orden in ordenes:
        orden.mp_total = sum(c.subtotal for c in orden.consumos.all())
        for s in orden.salidas.all():
            if s.producto.unidad_medida.simbolo.lower() == "kg":
                s.kg_totales = s.cantidad
            else:
                if s.producto.peso_unitario_kg:
                    s.kg_totales = s.cantidad * s.producto.peso_unitario_kg
                else:
                    s.kg_totales = None

            if s.cantidad > 0:
                s.cu = s.costo_asignado / s.cantidad
            else:
                s.cu = Decimal("0.00")

    parametros = {}
    if fecha_desde:
        parametros["Desde"] = fecha_desde
    if fecha_hasta:
        parametros["Hasta"] = fecha_hasta
    if producto_ids:
        parametros["Producto"] = ", ".join(producto_ids)

    if "exportar" in request.GET:
        columnas = [
            "No. Orden",
            "Fecha",
            "Estado",
            "Costo Total MP (USD)",
            "Producto Obtenido",
            "Cant. Fisica",
            "Unidad",
            "Kg Totales",
            "Costo Asignado",
            "Costo Unitario USD",
        ]
        filas = []
        for orden in ordenes:
            if orden.salidas.all():
                for sal in orden.salidas.all():
                    filas.append(
                        [
                            orden.numero,
                            orden.fecha_apertura,
                            orden.estado,
                            orden.mp_total,
                            f"{sal.producto.nombre}{' (Subprod)' if sal.es_subproducto else ''}",
                            sal.cantidad,
                            sal.producto.unidad_medida.simbolo,
                            sal.kg_totales if sal.kg_totales is not None else "-",
                            sal.costo_asignado or Decimal("0.00"),
                            sal.cu or Decimal("0.00"),
                        ]
                    )
            else:
                filas.append(
                    [
                        orden.numero,
                        orden.fecha_apertura,
                        orden.estado,
                        orden.mp_total,
                        "Sin salidas",
                        "",
                        "",
                        "",
                        "",
                        "",
                    ]
                )
        return exportar_excel(
            "reporte_produccion",
            columnas,
            [[str(v) for v in fila] for fila in filas],
            empresa=empresa,
            parametros=parametros,
        )

    total_general_mp = sum((o.mp_total for o in ordenes), Decimal("0.00"))
    total_general_costo = sum((o.costo_total for o in ordenes), Decimal("0.00"))

    context = {
        "empresa": empresa,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "producto_ids": producto_ids,
        "productos": Producto.objects.filter(activo=True).order_by("codigo"),
        "ordenes": ordenes,
        "total_general_mp": total_general_mp,
        "total_general_costo": total_general_costo,
    }
    return render(request, "reportes/produccion.html", context)


@login_required
def reporte_gastos(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_desde = request.GET.get("fecha_desde")
    fecha_hasta = request.GET.get("fecha_hasta")
    categorias = request.GET.getlist("categoria")
    estado = request.GET.get("estado")

    qs = GastoServicio.objects.select_related("proveedor").all()
    if fecha_desde:
        qs = qs.filter(fecha_emision__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha_emision__lte=fecha_hasta)
    if categorias:
        qs = qs.filter(categoria_gasto__in=categorias)
    if estado:
        qs = qs.filter(estado=estado)

    gastos = list(qs.select_related("categoria_gasto", "categoria_gasto__padre").order_by("fecha_emision"))
    total_usd = sum((Decimal(str(g.monto_usd)) for g in gastos), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    try:
        nivel_detalle = int(request.GET.get("nivel_detalle", 2))
    except ValueError:
        nivel_detalle = 2

    # Construir estructura agrupada para ambos niveles
    # nivel_detalle=1: agrupar todo por categoría padre → lista de {padre, subtotal}
    # nivel_detalle=2: agrupar por padre → subcategorías → filas individuales
    grupos_nivel1 = {}   # {padre: subtotal}
    grupos_nivel2 = {}   # {padre: {subcat: [gastos]}}
    sin_categoria = []
    for g in gastos:
        monto = Decimal(str(g.monto_usd))
        cat = g.categoria_gasto
        if cat:
            padre = cat.padre if cat.padre else cat
            subcat = cat if cat.padre else None
            # nivel 1
            grupos_nivel1.setdefault(padre, Decimal("0.00"))
            grupos_nivel1[padre] += monto
            # nivel 2
            grupos_nivel2.setdefault(padre, {})
            key = subcat if subcat else cat
            grupos_nivel2[padre].setdefault(key, [])
            grupos_nivel2[padre][key].append(g)
        else:
            sin_categoria.append(g)

    gastos_display_n1 = [
        {"categoria": k, "total": v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)}
        for k, v in sorted(grupos_nivel1.items(), key=lambda x: x[0].nombre)
    ]
    gastos_display_n2 = [
        {
            "padre": padre,
            "subcategorias": [
                {
                    "subcat": subcat,
                    "gastos": items,
                    "subtotal": sum(Decimal(str(g.monto_usd)) for g in items).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                }
                for subcat, items in sorted(subcats.items(), key=lambda x: x[0].nombre)
            ],
            "subtotal": sum(Decimal(str(g.monto_usd)) for subcats_items in grupos_nivel2.get(padre, {}).values() for g in subcats_items).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        }
        for padre, subcats in sorted(grupos_nivel2.items(), key=lambda x: x[0].nombre)
    ]

    all_categorias = set(g.categoria_gasto for g in Gs.objects.all())

    parametros = {}
    if fecha_desde:
        parametros["Desde"] = fecha_desde
    if fecha_hasta:
        parametros["Hasta"] = fecha_hasta
    if estado:
        parametros["Estado"] = estado
    if categorias:
        parametros["Categorías"] = ", ".join(categorias)
    parametros["Nivel detalle"] = str(nivel_detalle)

    if "exportar" in request.GET:
        if nivel_detalle == 1:
            columnas = ["Categoria", "Total USD"]
            filas = [[gd["categoria"], gd["total"]] for gd in gastos_display_n1]
        else:
            columnas = [
                "Numero",
                "Proveedor",
                "Categoria",
                "Descripcion",
                "Monto Original",
                "Moneda",
                "Monto USD",
                "Estado",
            ]
            filas = []
            for g in gastos:
                filas.append(
                    [
                        g.numero,
                        g.proveedor.nombre if g.proveedor else "",
                        g.categoria_gasto,
                        g.descripcion,
                        g.monto,
                        g.moneda,
                        g.monto_usd,
                        g.estado,
                    ]
                )
        return exportar_excel(
            "reporte_gastos",
            columnas,
            [[str(v) for v in fila] for fila in filas],
            empresa=empresa,
            parametros=parametros,
        )

    context = {
        "empresa": empresa,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "gastos": gastos,
        "gastos_display_n1": gastos_display_n1,
        "gastos_display_n2": gastos_display_n2,
        "sin_categoria": sin_categoria,
        "nivel_detalle": nivel_detalle,
        "total_usd": total_usd,
        "todas_categorias": all_categorias,
    }
    return render(request, "reportes/gastos.html", context)


@login_required
def reporte_capital_trabajo(request):
    """
    B4 — Aplica quantize(0.01) a TODOS los totales y subtotales.
    """
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_corte = request.GET.get("fecha_corte")
    hasta = (
        datetime.datetime.strptime(fecha_corte, "%Y-%m-%d").date()
        if fecha_corte
        else datetime.date.today()
    )
    valorar = request.GET.get("valorar_inventario", "COSTO")

    def q(valor):
        """Cuantiza a 2 decimales con ROUND_HALF_UP."""
        return Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Obtener tasa de cambio para cuentas VES: usar última reexpresión o fallback
    tasa_ves = Decimal("1.00")
    try:
        from apps.bancos.models import PeriodoReexpresado

        ultimo_periodo = PeriodoReexpresado.objects.order_by("-anio", "-mes").first()
        if ultimo_periodo:
            tasa_ves = Decimal(str(ultimo_periodo.tasa_cierre))
    except Exception:
        pass

    # Activo Corriente: Efectivo (con desglose por cuenta)
    efectivo = Decimal("0.00")
    cuentas_efectivo = []
    for cta in CuentaBancaria.objects.filter(activa=True).order_by("nombre"):
        saldo_original = Decimal(str(cta.saldo_actual))
        if cta.moneda == "USD":
            saldo_usd = saldo_original
        else:
            saldo_usd = (saldo_original / tasa_ves) if tasa_ves > 0 else Decimal("0.00")
        saldo_usd = q(saldo_usd)
        cuentas_efectivo.append({
            "nombre": cta.nombre,
            "moneda": cta.moneda,
            "saldo_original": saldo_original,
            "saldo_usd": saldo_usd,
        })
        efectivo += saldo_usd
    efectivo = q(efectivo)

    # Activo Corriente: CxC — usa get_saldo_pendiente() que ya descuenta NCs emitidas (A-2)
    cxc = Decimal("0.00")
    facturas_emitidas = FacturaVenta.objects.filter(
        estado="EMITIDA", fecha__lte=hasta
    ).prefetch_related("cobros", "notas_credito")
    for f in facturas_emitidas:
        saldo = f.get_saldo_pendiente()
        if saldo > 0 and (not f.fecha_vencimiento or f.fecha_vencimiento >= hasta):
            cxc += saldo
    cxc = q(cxc)

    # Activo Corriente: Inventario
    inventario = Decimal("0.00")
    for prod in Producto.objects.filter(activo=True, stock_actual__gt=0):
        if valorar == "VENTA":
            precio = prod.precio_venta if prod.precio_venta else prod.costo_promedio
        else:
            precio = prod.costo_promedio
        inventario += Decimal(str(prod.stock_actual)) * Decimal(str(precio))
    inventario = q(inventario)

    activo_corriente = q(efectivo + cxc + inventario)

    # Pasivo Corriente: CxP Compras (APROBADAS con saldo pendiente)
    cxp_compras = Decimal("0.00")
    facturas_aprobadas = (
        FacturaCompra.objects.filter(estado="APROBADA", fecha__lte=hasta)
        .annotate(
            total_pagado=Coalesce(
                Sum("pagos__monto_usd"),
                Value(Decimal("0.00")),
                output_field=DecimalField(),
            )
        )
        .annotate(saldo=F("total") - F("total_pagado"))
        .filter(saldo__gt=0)
    )
    for f in facturas_aprobadas:
        cxp_compras += Decimal(str(f.saldo))
    cxp_compras = q(cxp_compras)

    # Pasivo Corriente: CxP Gastos
    cxp_gastos = Decimal("0.00")
    gastos_base = list(
        GastoServicio.objects.filter(
            estado="PENDIENTE", fecha_emision__lte=hasta
        ).select_related("categoria_gasto", "categoria_gasto__padre")
    )
    for g in gastos_base:
        cxp_gastos += Decimal(str(g.monto_usd))
    cxp_gastos = q(cxp_gastos)

    # Pasivo de socios: préstamos activos
    from datetime import timedelta
    from apps.socios.models import PrestamoPorSocio

    hoy = datetime.date.today()
    limite_corriente = hoy + timedelta(days=365)

    from django.db.models import Sum as _Sum
    prestamos_activos = list(
        PrestamoPorSocio.objects.filter(estado="ACTIVO").annotate(
            total_pagado=Coalesce(
                _Sum("pagos__monto_usd"),
                Value(Decimal("0.00")),
                output_field=DecimalField(),
            )
        )
    )

    def _saldo_prestamo(p):
        """Saldo neto de un préstamo: monto_usd menos lo ya pagado."""
        return max(Decimal("0.00"), Decimal(str(p.monto_usd)) - Decimal(str(p.total_pagado)))

    prestamos_corriente = q(
        sum(
            (_saldo_prestamo(p) for p in prestamos_activos
             if p.fecha_vencimiento and p.fecha_vencimiento <= limite_corriente),
            Decimal("0.00"),
        )
    )

    prestamos_no_corriente = q(
        sum(
            (_saldo_prestamo(p) for p in prestamos_activos
             if not p.fecha_vencimiento or p.fecha_vencimiento > limite_corriente),
            Decimal("0.00"),
        )
    )

    pasivo_corriente = q(cxp_compras + cxp_gastos + prestamos_corriente)
    capital_neto = q(activo_corriente - pasivo_corriente)
    capital_trabajo = capital_neto  # alias para compatibilidad con la plantilla

    try:
        nivel_detalle = int(request.GET.get("nivel_detalle", 2))
    except ValueError:
        nivel_detalle = 2

    # Reutilizar la misma lógica de agrupación que reporte_gastos
    _grupos_n1 = {}
    _grupos_n2 = {}
    for g in gastos_base:
        monto = Decimal(str(g.monto_usd))
        cat = g.categoria_gasto
        if cat:
            padre = cat.padre if cat.padre else cat
            subcat = cat if cat.padre else None
            _grupos_n1.setdefault(padre, Decimal("0.00"))
            _grupos_n1[padre] += monto
            _grupos_n2.setdefault(padre, {})
            key = subcat if subcat else cat
            _grupos_n2[padre].setdefault(key, [])
            _grupos_n2[padre][key].append(g)
    gastos_display_n1_ct = [
        {"categoria": k, "total": v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)}
        for k, v in sorted(_grupos_n1.items(), key=lambda x: x[0].nombre)
    ]
    gastos_display_n2_ct = [
        {
            "padre": padre,
            "subcategorias": [
                {
                    "subcat": subcat,
                    "gastos": items,
                    "subtotal": sum(Decimal(str(g.monto_usd)) for g in items).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                }
                for subcat, items in sorted(subcats.items(), key=lambda x: x[0].nombre)
            ],
            "subtotal": sum(Decimal(str(g.monto_usd)) for subcats_items in _grupos_n2.get(padre, {}).values() for g in subcats_items).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        }
        for padre, subcats in sorted(_grupos_n2.items(), key=lambda x: x[0].nombre)
    ]

    parametros = {
        "Fecha corte": fecha_corte or str(hasta),
        "Valorar inventario": valorar,
        "Nivel detalle": str(nivel_detalle),
    }

    if "exportar" in request.GET:
        columnas = [
            "Concepto",
            "Monto USD",
        ]
        filas = [
            ["Efectivo y Equivalentes", efectivo],
            ["Cuentas por Cobrar", cxc],
            [f"Inventario ({valorar})", inventario],
            ["Total Activo Corriente", activo_corriente],
            ["CxP Compras", cxp_compras],
            ["CxP Gastos", cxp_gastos],
            ["Prestamos Corriente", prestamos_corriente],
            ["Prestamos No Corriente", prestamos_no_corriente],
            ["Total Pasivo Corriente", pasivo_corriente],
            ["Capital de Trabajo Neto", capital_trabajo],
        ]
        return exportar_excel(
            "capital_trabajo",
            columnas,
            [[str(v) for v in fila] for fila in filas],
            empresa=empresa,
            parametros=parametros,
        )

    context = {
        "empresa": empresa,
        "fecha_corte": hasta,
        "valorar": valorar,
        "efectivo": efectivo,
        "cuentas_efectivo": cuentas_efectivo,
        "tasa_ves": tasa_ves,
        "cxc": cxc,
        "inventario": inventario,
        "activo_corriente": activo_corriente,
        "cxp_compras": cxp_compras,
        "cxp_gastos": cxp_gastos,
        "prestamos_corriente": prestamos_corriente,
        "prestamos_no_corriente": prestamos_no_corriente,
        "prestamos_activos": prestamos_activos,
        "pasivo_corriente": pasivo_corriente,
        "capital_neto": capital_neto,
        "capital_trabajo": capital_trabajo,
        "gastos_display_n1": gastos_display_n1_ct,
        "gastos_display_n2": gastos_display_n2_ct,
        "nivel_detalle": nivel_detalle,
    }
    return render(request, "reportes/capital_trabajo.html", context)


@login_required
def reporte_stock(request):
    from datetime import date as date_module
    from datetime import datetime
    from apps.core.models import ConfiguracionEmpresa
    from apps.core.rbac import usuario_en_grupo
    from apps.almacen.models import MovimientoInventario

    if not (
        request.user.is_superuser
        or usuario_en_grupo(request.user, "Master", "Administrador")
    ):
        raise PermissionDenied

    empresa = ConfiguracionEmpresa.objects.first()
    solo_activos = request.GET.get("activos", "1") == "1"

    fecha_str = request.GET.get("fecha", "")
    if fecha_str:
        try:
            fecha_corte = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except ValueError:
            fecha_corte = date_module.today()
    else:
        fecha_corte = date_module.today()

    solo_con_stock = request.GET.get("con_stock", "0") == "1"

    def stock_a_fecha(producto, fecha):
        # DIM-06-002: values_list devuelve tuplas ligeras, sin instanciar el modelo
        movs = (
            MovimientoInventario.objects.filter(
                producto=producto, fecha__date__lte=fecha
            )
            .order_by("fecha", "id")
            .values_list("tipo", "cantidad", "costo_unitario")
        )
        stock = Decimal("0")
        costo = Decimal("0")
        for tipo, cantidad, costo_unitario in movs:
            if tipo == "ENTRADA":
                ve = stock * costo
                vn = cantidad * costo_unitario
                nq = stock + cantidad
                costo = (ve + vn) / nq if nq > 0 else costo
                stock = nq
            elif tipo == "SALIDA":
                stock = max(Decimal("0"), stock - cantidad)
        return stock, costo

    qs = Producto.objects.select_related("unidad_medida", "categoria")
    if solo_activos:
        qs = qs.filter(activo=True)
    qs = qs.order_by("categoria__nombre", "codigo")

    es_hoy = fecha_corte == date_module.today()

    productos = []
    total_costo = Decimal("0")
    total_venta = Decimal("0")
    for p in qs:
        if es_hoy:
            # Usar valores cacheados del producto para que coincida con la pantalla Productos
            stock_calc = Decimal(str(p.stock_actual))
            costo_prom = Decimal(str(p.costo_promedio))
        else:
            stock_calc, costo_prom = stock_a_fecha(p, fecha_corte)
        if solo_con_stock and stock_calc == 0:
            continue
        valor_costo = (stock_calc * costo_prom).quantize(Decimal("0.01"))
        precio_v = p.precio_venta if p.precio_venta else costo_prom
        valor_venta = (stock_calc * precio_v).quantize(Decimal("0.01"))
        total_costo += valor_costo
        total_venta += valor_venta
        productos.append(
            {
                "codigo": p.codigo,
                "nombre": p.nombre,
                "categoria": p.categoria.nombre if p.categoria else "Sin categoría",
                "stock_actual": stock_calc,
                "unidad": p.unidad_medida.simbolo if p.unidad_medida else "",
                "costo_promedio": costo_prom,
                "precio_venta": p.precio_venta,
                "valor_costo": valor_costo,
                "valor_venta": valor_venta,
            }
        )

    # Agrupar por categoría para el template
    from itertools import groupby
    from operator import itemgetter
    categorias_data = []
    for cat_nombre, prods_iter in groupby(productos, key=itemgetter("categoria")):
        prods_list = list(prods_iter)
        sub_costo = sum(p["valor_costo"] for p in prods_list).quantize(Decimal("0.01"))
        sub_venta = sum(p["valor_venta"] for p in prods_list).quantize(Decimal("0.01"))
        categorias_data.append({
            "categoria": cat_nombre,
            "productos": prods_list,
            "subtotal_costo": sub_costo,
            "subtotal_venta": sub_venta,
        })

    if "exportar" in request.GET:
        columnas = [
            "Código",
            "Producto",
            "Stock",
            "U/M",
            "Costo Unit.",
            "Precio Unit.",
            "Valor Costo",
            "Valor Venta",
        ]
        filas = [
            [
                p["codigo"],
                p["nombre"],
                p["stock_actual"],
                p["unidad"],
                p["costo_promedio"],
                p["precio_venta"] or "",
                p["valor_costo"],
                p["valor_venta"],
            ]
            for p in productos
        ]
        parametros = {
            "Fecha corte": fecha_corte.strftime("%d/%m/%Y"),
            "Productos": "Solo activos" if solo_activos else "Todos",
        }
        if solo_con_stock:
            parametros["Filtro"] = "Solo con stock"
        return exportar_excel(
            "Stock",
            columnas,
            filas,
            empresa=empresa,
            parametros=parametros,
        )

    context = {
        "empresa": empresa,
        "productos": productos,
        "categorias_data": categorias_data,
        "total_costo": total_costo,
        "total_venta": total_venta,
        "solo_activos": solo_activos,
        "solo_con_stock": solo_con_stock,
        "fecha_corte": fecha_corte.strftime("%Y-%m-%d"),
        "today": fecha_corte.strftime("%Y-%m-%d"),
        "titulo": "Reporte de Stock",
    }
    return render(request, "reportes/stock.html", context)


@login_required
def dashboard(request):
    _check_reporte_perm(request)  # B9
    from apps.reportes.analytics import (
        calcular_cce,
        calcular_precio_ponderado_leche,
        calcular_proyeccion_caja_7d,
        calcular_score_riesgo,
    )
    from apps.ventas.models import Cliente
    from apps.core.models import Notificacion

    ctx = {"empresa": ConfiguracionEmpresa.objects.first()}
    es_admin = request.user.is_superuser or usuario_en_grupo(
        request.user, "Master", "Administrador"
    )
    if es_admin:
        ctx["cce"] = calcular_cce()
        ctx["proyeccion"] = calcular_proyeccion_caja_7d()
        ctx["precio_leche"] = calcular_precio_ponderado_leche()
        ctx["scores"] = [
            {"cliente": c, **calcular_score_riesgo(c)}
            for c in Cliente.objects.filter(activo=True)
        ]

    notifs = Notificacion.objects.filter(activa=True)
    leidas = request.session.get("notif_leidas", [])
    ctx.update({"notificaciones": notifs, "notif_leidas": leidas, "es_admin": es_admin})

    parametros = {"Tipo": "Admin" if es_admin else "Usuario"}

    if "exportar" in request.GET:
        if es_admin:
            columnas = ["Cliente", "Score", "Puntualidad", "Solvencia", "Tendencia"]
            filas = []
            for item in ctx.get("scores", []):
                filas.append(
                    [
                        item["cliente"],
                        item.get("score"),
                        item.get("puntualidad"),
                        item.get("solvencia"),
                        item.get("tendencia"),
                    ]
                )
        else:
            columnas = ["Tipo", "Titulo", "Mensaje", "Entidad", "Fecha"]
            filas = []
            for n in notifs:
                filas.append(
                    [
                        n.get_tipo_display(),
                        n.titulo,
                        n.mensaje,
                        f"{n.entidad} {n.entidad_id}",
                        n.fecha_referencia,
                    ]
                )
        return exportar_excel(
            "dashboard",
            columnas,
            [[str(v) for v in fila] for fila in filas],
            empresa=ctx.get("empresa"),
            parametros=parametros,
        )

    from django.contrib import admin as django_admin
    ctx.update(django_admin.site.each_context(request))
    return render(request, "reportes/dashboard.html", ctx)


@login_required
def kardex_view(request):
    _check_reporte_perm(request)
    from apps.almacen.models import Categoria, MovimientoInventario

    empresa = ConfiguracionEmpresa.objects.first()
    productos_qs = Producto.objects.select_related("categoria", "unidad_medida").filter(activo=True).order_by("codigo")
    categorias_qs = Categoria.objects.filter(activo=True).order_by("nombre")

    producto_id = request.GET.get("producto")
    categoria_id = request.GET.get("categoria")
    fecha_desde = request.GET.get("fecha_desde")
    fecha_hasta = request.GET.get("fecha_hasta")

    # Modo detalle: un producto seleccionado → Kardex línea a línea con PPM
    lineas_kardex = []
    # Modo grupo: categoría seleccionada → resumen por producto con subtotales
    grupos = []
    total_valorizado = Decimal("0")
    # Modo totales: sin filtros → una línea por producto con columnas agregadas
    productos_data = []
    modo = None
    producto_sel = None
    categoria_sel = None

    if producto_id:
        modo = "producto"
        try:
            producto_sel = Producto.objects.select_related("unidad_medida", "categoria").get(pk=producto_id)
        except Producto.DoesNotExist:
            producto_sel = None

        if producto_sel:
            movs_qs = MovimientoInventario.objects.filter(producto=producto_sel).order_by("fecha", "id")
            if fecha_desde:
                movs_qs = movs_qs.filter(fecha__date__gte=fecha_desde)
            if fecha_hasta:
                movs_qs = movs_qs.filter(fecha__date__lte=fecha_hasta)

            stock = Decimal("0")
            costo = Decimal("0")
            for mov in movs_qs:
                cantidad = Decimal(str(mov.cantidad))
                costo_u = Decimal(str(mov.costo_unitario))
                if mov.tipo == "ENTRADA":
                    ve = stock * costo
                    vn = cantidad * costo_u
                    nq = stock + cantidad
                    costo = (ve + vn) / nq if nq > 0 else costo
                    stock = nq
                elif mov.tipo == "SALIDA":
                    stock = max(Decimal("0"), stock - cantidad)
                lineas_kardex.append({
                    "fecha": mov.fecha,
                    "tipo": mov.tipo,
                    "cantidad": cantidad,
                    "costo_unitario": costo_u,
                    "referencia": mov.referencia,
                    "stock_acumulado": stock.quantize(Decimal("0.0001")),
                    "costo_promedio": costo.quantize(Decimal("0.000001")),
                    "valor_stock": (stock * costo).quantize(Decimal("0.01")),
                })

    elif categoria_id:
        modo = "categoria"
        try:
            categoria_sel = Categoria.objects.get(pk=categoria_id)
        except Categoria.DoesNotExist:
            categoria_sel = None

        if categoria_sel:
            prods_cat = Producto.objects.filter(categoria=categoria_sel, activo=True).order_by("codigo")
            subtotal_cat = Decimal("0")
            items = []
            for p in prods_cat:
                stock = Decimal(str(p.stock_actual))
                costo = Decimal(str(p.costo_promedio))
                valorizado = (stock * costo).quantize(Decimal("0.01"))
                subtotal_cat += valorizado
                items.append({
                    "producto": p,
                    "stock": stock,
                    "costo_promedio": costo,
                    "valorizado": valorizado,
                })
            total_valorizado += subtotal_cat
            grupos.append({
                "categoria": categoria_sel,
                "items": items,
                "subtotal": subtotal_cat,
            })

    else:
        # Modo totales: sin filtros → una fila por producto con columnas agregadas
        modo = "totales"
        import datetime as _dt

        fecha_desde_dt = None
        fecha_hasta_dt = None
        if fecha_desde:
            try:
                fecha_desde_dt = _dt.datetime.strptime(fecha_desde, "%Y-%m-%d").date()
            except ValueError:
                pass
        if fecha_hasta:
            try:
                fecha_hasta_dt = _dt.datetime.strptime(fecha_hasta, "%Y-%m-%d").date()
            except ValueError:
                pass

        for producto in productos_qs:
            movs_all = MovimientoInventario.objects.filter(producto=producto)
            if fecha_desde_dt:
                movs_antes = movs_all.filter(fecha__lt=fecha_desde_dt)
                movs_rango = movs_all.filter(fecha__gte=fecha_desde_dt)
            else:
                movs_antes = MovimientoInventario.objects.none()
                movs_rango = movs_all

            if fecha_hasta_dt:
                movs_rango = movs_rango.filter(fecha__lte=fecha_hasta_dt)

            # Saldo inicial (movimientos antes del rango)
            cant_inicial = Decimal("0")
            monto_inicial = Decimal("0.00")
            for mov in movs_antes:
                q_mov = Decimal(str(mov.cantidad))
                v_mov = q_mov * Decimal(str(mov.costo_unitario))
                if mov.tipo == "ENTRADA":
                    cant_inicial += q_mov
                    monto_inicial += v_mov
                elif mov.tipo == "SALIDA":
                    cant_inicial -= q_mov
                    monto_inicial -= v_mov

            # Movimientos dentro del rango
            cant_entradas = Decimal("0")
            monto_entradas = Decimal("0.00")
            cant_salidas = Decimal("0")
            monto_salidas = Decimal("0.00")
            cant_ajustes = Decimal("0")
            monto_ajustes = Decimal("0.00")
            for mov in movs_rango:
                q_mov = Decimal(str(mov.cantidad))
                v_mov = q_mov * Decimal(str(mov.costo_unitario))
                if mov.tipo == "ENTRADA":
                    if q_mov == Decimal("0"):
                        monto_ajustes += v_mov
                    else:
                        cant_entradas += q_mov
                        monto_entradas += v_mov
                elif mov.tipo == "SALIDA":
                    cant_salidas += q_mov
                    monto_salidas += v_mov

            cant_final = cant_inicial + cant_entradas - cant_salidas + cant_ajustes
            monto_final = monto_inicial + monto_entradas - monto_salidas + monto_ajustes
            total_valorizado += monto_final.quantize(Decimal("0.01"))
            productos_data.append({
                "codigo": producto.codigo,
                "descripcion": producto.nombre,
                "categoria": producto.categoria.nombre if producto.categoria else "Sin categoría",
                "cant_inicial": cant_inicial.quantize(Decimal("0.01")),
                "cant_entradas": cant_entradas.quantize(Decimal("0.01")),
                "cant_salidas": cant_salidas.quantize(Decimal("0.01")),
                "cant_ajustes": cant_ajustes.quantize(Decimal("0.01")),
                "cant_final": cant_final.quantize(Decimal("0.01")),
                "monto_inicial": monto_inicial.quantize(Decimal("0.01")),
                "monto_entradas": monto_entradas.quantize(Decimal("0.01")),
                "monto_salidas": monto_salidas.quantize(Decimal("0.01")),
                "monto_ajustes": monto_ajustes.quantize(Decimal("0.01")),
                "monto_final": monto_final.quantize(Decimal("0.01")),
            })

    context = {
        "empresa": empresa,
        "productos": productos_qs,
        "categorias": categorias_qs,
        "producto_id": producto_id or "",
        "categoria_id": categoria_id or "",
        "fecha_desde": fecha_desde or "",
        "fecha_hasta": fecha_hasta or "",
        "modo": modo,
        "producto_sel": producto_sel,
        "categoria_sel": categoria_sel,
        "lineas_kardex": lineas_kardex,
        "grupos": grupos,
        "total_valorizado": total_valorizado,
        "productos_data": productos_data,
        "titulo": "Kardex de Inventario",
    }
    return render(request, "reportes/kardex.html", context)


@login_required
def tesoreria_view(request):
    _check_reporte_perm(request)
    from apps.bancos.models import MovimientoCaja, MovimientoTesoreria

    empresa = ConfiguracionEmpresa.objects.first()
    cuentas_qs = CuentaBancaria.objects.filter(activa=True).order_by("nombre")

    fecha_desde = request.GET.get("fecha_desde")
    fecha_hasta = request.GET.get("fecha_hasta")
    cuentas_ids = request.GET.getlist("cuenta")
    tipos_sel = request.GET.getlist("tipo_movimiento")

    # --- MovimientoCaja ---
    mc_qs = MovimientoCaja.objects.select_related("cuenta").all()
    if fecha_desde:
        mc_qs = mc_qs.filter(fecha__gte=fecha_desde)
    if fecha_hasta:
        mc_qs = mc_qs.filter(fecha__lte=fecha_hasta)
    if cuentas_ids:
        mc_qs = mc_qs.filter(cuenta_id__in=cuentas_ids)

    # --- MovimientoTesoreria ---
    mt_qs = MovimientoTesoreria.objects.select_related("cuenta", "categoria").all()
    if fecha_desde:
        mt_qs = mt_qs.filter(fecha__gte=fecha_desde)
    if fecha_hasta:
        mt_qs = mt_qs.filter(fecha__lte=fecha_hasta)
    if cuentas_ids:
        mt_qs = mt_qs.filter(cuenta_id__in=cuentas_ids)

    # Consolidar en lista uniforme
    movimientos = []
    for m in mc_qs:
        movimientos.append({
            "fecha": m.fecha,
            "cuenta": m.cuenta,
            "origen": "Caja",
            "tipo": m.tipo,
            "referencia": m.referencia,
            "descripcion": m.notas or "",
            "monto": Decimal(str(m.monto)),
            "moneda": m.moneda,
            "tasa": Decimal(str(m.tasa_cambio)),
            "monto_usd": Decimal(str(m.monto_usd)),
        })
    for m in mt_qs:
        movimientos.append({
            "fecha": m.fecha,
            "cuenta": m.cuenta,
            "origen": "Tesorería",
            "tipo": m.tipo,
            "referencia": m.numero,
            "descripcion": m.descripcion,
            "monto": Decimal(str(m.monto)),
            "moneda": m.moneda,
            "tasa": Decimal(str(m.tasa_cambio)),
            "monto_usd": Decimal(str(m.monto_usd)),
        })

    # Filtrar por tipo_movimiento si aplica
    if tipos_sel:
        movimientos = [m for m in movimientos if m["tipo"] in tipos_sel]

    # Ordenar por fecha, luego cuenta
    movimientos.sort(key=lambda m: (m["fecha"], m["cuenta"].nombre))

    # Resumen por cuenta
    resumen = {}
    for m in movimientos:
        cid = m["cuenta"].pk
        if cid not in resumen:
            resumen[cid] = {
                "cuenta": m["cuenta"],
                "entradas_usd": Decimal("0"),
                "salidas_usd": Decimal("0"),
            }
        tipo = m["tipo"]
        monto_usd = m["monto_usd"]
        # Tipos que suman saldo
        if tipo in ("ENTRADA", "TRANSFERENCIA_ENTRADA", "ABONO"):
            resumen[cid]["entradas_usd"] += monto_usd
        elif tipo in ("SALIDA", "TRANSFERENCIA_SALIDA", "CARGO", "REEXPRESION"):
            resumen[cid]["salidas_usd"] += monto_usd

    resumen_list = []
    total_entradas = Decimal("0")
    total_salidas = Decimal("0")
    for v in resumen.values():
        neto = v["entradas_usd"] - v["salidas_usd"]
        v["neto"] = neto
        total_entradas += v["entradas_usd"]
        total_salidas += v["salidas_usd"]
        resumen_list.append(v)
    resumen_list.sort(key=lambda r: r["cuenta"].nombre)
    total_neto = total_entradas - total_salidas

    # Tipos disponibles para filtro
    TIPOS_MC = [t[0] for t in MovimientoCaja.TIPO_CHOICES]
    TIPOS_MT = [t[0] for t in MovimientoTesoreria.TIPOS]
    todos_tipos = sorted(set(TIPOS_MC + TIPOS_MT))

    context = {
        "empresa": empresa,
        "cuentas": cuentas_qs,
        "fecha_desde": fecha_desde or "",
        "fecha_hasta": fecha_hasta or "",
        "cuentas_ids": cuentas_ids,
        "tipos_sel": tipos_sel,
        "todos_tipos": todos_tipos,
        "movimientos": movimientos,
        "resumen": resumen_list,
        "total_entradas": total_entradas,
        "total_salidas": total_salidas,
        "total_neto": total_neto,
        "titulo": "Reporte de Tesorería",
    }
    return render(request, "reportes/tesoreria.html", context)


@login_required
def marcar_notificacion_leida(request, notif_id):
    leidas = request.session.get("notif_leidas", [])
    if notif_id not in leidas:
        leidas.append(notif_id)
    request.session["notif_leidas"] = leidas
    return JsonResponse({"ok": True})
