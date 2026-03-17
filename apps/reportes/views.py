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

    detalles = list(qs.order_by("factura__fecha", "factura__numero"))

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
            "Estado",
        ]
        filas = []
        for d in detalles:
            if d.factura.moneda == "USD":
                monto_usd = d.subtotal
            else:
                monto_usd = (
                    d.subtotal / d.factura.tasa_cambio
                    if d.factura.tasa_cambio and d.factura.tasa_cambio > 0
                    else Decimal("0.00")
                )
            filas.append(
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
                    d.factura.estado,
                ]
            )
        return exportar_excel(
            "reporte_ventas",
            columnas,
            [[str(v) for v in fila] for fila in filas],
            empresa=empresa,
            parametros=parametros,
        )

    context = {
        "empresa": empresa,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "agrupar_por_cliente": agrupar_por_cliente,
        "detalles": detalles,
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

    # DIM-06-001: un solo SELECT con SUM condicional — elimina N+1 por cobros
    facturas = (
        FacturaVenta.objects.filter(estado="EMITIDA", fecha__lte=hasta)
        .select_related("cliente")
        .annotate(
            cobrado_hasta=Coalesce(
                Sum("cobros__monto", filter=Q(cobros__fecha__lte=hasta)),
                Value(Decimal("0.00")),
                output_field=DecimalField(),
            )
        )
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

    for fv in facturas:
        saldo = fv.total - fv.cobrado_hasta
        if saldo > 0:
            dias_vencida = (
                (hasta - fv.fecha_vencimiento).days if fv.fecha_vencimiento else 0
            )
            if dias_vencida < 0:
                dias_vencida = 0

            saldo_0_30 = saldo if 0 <= dias_vencida <= 30 else Decimal("0.00")
            saldo_31_60 = saldo if 31 <= dias_vencida <= 60 else Decimal("0.00")
            saldo_61_90 = saldo if 61 <= dias_vencida <= 90 else Decimal("0.00")
            saldo_90_plus = saldo if dias_vencida > 90 else Decimal("0.00")

            resultados.append(
                {
                    "factura": fv,
                    "saldo": saldo,
                    "dias_vencida": dias_vencida,
                    "s_0_30": saldo_0_30,
                    "s_31_60": saldo_31_60,
                    "s_61_90": saldo_61_90,
                    "s_90_plus": saldo_90_plus,
                }
            )
            totales["total"] += fv.total
            totales["pendiente"] += saldo
            totales["s_0_30"] += saldo_0_30
            totales["s_31_60"] += saldo_31_60
            totales["s_61_90"] += saldo_61_90
            totales["s_90_plus"] += saldo_90_plus

    parametros = {}
    parametros["Fecha corte"] = fecha_corte or str(hasta)

    if "exportar" in request.GET:
        columnas = [
            "Cliente",
            "No. Factura",
            "Emision",
            "Vencimiento",
            "Dias Vencida",
            "Monto Total",
            "Saldo Pendiente",
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
                    item["dias_vencida"],
                    fv.total_usd
                    if hasattr(fv, "total_usd") and fv.total_usd
                    else fv.total,
                    item["saldo"],
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

    detalles = list(qs.order_by("factura__fecha", "factura__numero"))

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
            "Estado",
        ]
        filas = []
        for d in detalles:
            if d.factura.moneda == "USD":
                monto_usd = d.subtotal
            else:
                monto_usd = (
                    d.subtotal / d.factura.tasa_cambio
                    if d.factura.tasa_cambio and d.factura.tasa_cambio > 0
                    else Decimal("0.00")
                )
            filas.append(
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
                    d.factura.estado,
                ]
            )
        return exportar_excel(
            "reporte_compras",
            columnas,
            [[str(v) for v in fila] for fila in filas],
            empresa=empresa,
            parametros=parametros,
        )

    context = {
        "empresa": empresa,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "agrupar_por_proveedor": agrupar_por_proveedor,
        "detalles": detalles,
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

    qs = OrdenProduccion.objects.all()
    if fecha_desde:
        qs = qs.filter(fecha_apertura__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha_apertura__lte=fecha_hasta)

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

    context = {
        "empresa": empresa,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "ordenes": ordenes,
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

    gastos = list(qs.order_by("fecha_emision"))
    total_usd = sum(g.monto_usd for g in gastos)

    try:
        nivel_detalle = int(request.GET.get("nivel_detalle", 2))
    except ValueError:
        nivel_detalle = 2

    gastos_display = gastos
    if nivel_detalle == 1:
        agrupado = {}
        for g in gastos:
            cat = (
                g.categoria_gasto.padre
                if g.categoria_gasto and g.categoria_gasto.padre
                else g.categoria_gasto
            )
            if not cat:
                continue
            agrupado.setdefault(cat, Decimal("0.00"))
            agrupado[cat] += Decimal(str(g.monto_usd))
        gastos_display = [{"categoria": k, "total": v} for k, v in agrupado.items()]

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
            filas = [[gd["categoria"], gd["total"]] for gd in gastos_display]
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
        "gastos_display": gastos_display,
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

    # Activo Corriente: Efectivo
    efectivo = Decimal("0.00")
    for cta in CuentaBancaria.objects.filter(activa=True):
        if cta.moneda == "USD":
            efectivo += Decimal(str(cta.saldo_actual))
        else:
            if tasa_ves > 0:
                efectivo += Decimal(str(cta.saldo_actual)) / tasa_ves
    efectivo = q(efectivo)

    # Activo Corriente: CxC — DIM-06-001: un solo SELECT con SUM condicional
    cxc = Decimal("0.00")
    facturas_emitidas = (
        FacturaVenta.objects.filter(estado="EMITIDA", fecha__lte=hasta)
        .annotate(
            cobrado_hasta=Coalesce(
                Sum("cobros__monto", filter=Q(cobros__fecha__lte=hasta)),
                Value(Decimal("0.00")),
                output_field=DecimalField(),
            )
        )
    )
    for f in facturas_emitidas:
        saldo = Decimal(str(f.total)) - Decimal(str(f.cobrado_hasta))
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

    prestamos_activos = list(PrestamoPorSocio.objects.filter(estado="ACTIVO"))

    prestamos_corriente = q(
        sum(
            Decimal(str(p.monto_usd))
            for p in prestamos_activos
            if p.fecha_vencimiento and p.fecha_vencimiento <= limite_corriente
        )
        or Decimal("0.00")
    )

    prestamos_no_corriente = q(
        sum(
            Decimal(str(p.monto_usd))
            for p in prestamos_activos
            if not p.fecha_vencimiento or p.fecha_vencimiento > limite_corriente
        )
        or Decimal("0.00")
    )

    pasivo_corriente = q(cxp_compras + cxp_gastos + prestamos_corriente)
    capital_neto = q(activo_corriente - pasivo_corriente)
    capital_trabajo = capital_neto  # alias para compatibilidad con la plantilla

    try:
        nivel_detalle = int(request.GET.get("nivel_detalle", 2))
    except ValueError:
        nivel_detalle = 2

    gastos_display = gastos_base
    if nivel_detalle == 1:
        agrupado = {}
        for g in gastos_base:
            cat = (
                g.categoria_gasto.padre
                if g.categoria_gasto and g.categoria_gasto.padre
                else g.categoria_gasto
            )
            if not cat:
                continue
            agrupado.setdefault(cat, Decimal("0.00"))
            agrupado[cat] += Decimal(str(g.monto_usd))
        gastos_display = [{"categoria": k, "total": v} for k, v in agrupado.items()]

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
        "gastos_display": gastos_display,
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

    qs = Producto.objects.select_related("unidad_medida")
    if solo_activos:
        qs = qs.filter(activo=True)
    qs = qs.order_by("codigo")

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
                "stock_actual": stock_calc,
                "unidad": p.unidad_medida.simbolo if p.unidad_medida else "",
                "costo_promedio": costo_prom,
                "precio_venta": p.precio_venta,
                "valor_costo": valor_costo,
                "valor_venta": valor_venta,
            }
        )

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
def marcar_notificacion_leida(request, notif_id):
    leidas = request.session.get("notif_leidas", [])
    if notif_id not in leidas:
        leidas.append(notif_id)
    request.session["notif_leidas"] = leidas
    return JsonResponse({"ok": True})
