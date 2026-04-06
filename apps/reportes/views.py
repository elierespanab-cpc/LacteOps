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
from apps.socios.models import PrestamoPorSocio


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


def _decimal(value, default="0.00"):
    return Decimal(str(value if value is not None else default))


def _quantize_money(value):
    return _decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _monto_usd_gasto(gasto):
    monto_usd = _decimal(getattr(gasto, "monto_usd", Decimal("0.00")))
    if monto_usd > 0:
        return _quantize_money(monto_usd)
    return _monto_usd_linea(gasto.monto, gasto.moneda, gasto.tasa_cambio)


def _resumen_factura_venta(factura, hasta=None):
    total = _quantize_money(factura.total)
    cobrado = sum(
        (_decimal(cobro.monto) for cobro in factura.cobros.all() if not hasta or cobro.fecha <= hasta),
        Decimal("0.00"),
    )
    nc_emitidas = sum(
        (
            _decimal(nc.total)
            for nc in factura.notas_credito.all()
            if nc.estado == "EMITIDA" and (not hasta or nc.fecha <= hasta) and nc.total is not None
        ),
        Decimal("0.00"),
    )
    saldo = max(Decimal("0.00"), total - cobrado - nc_emitidas)
    return {
        "total": _quantize_money(total),
        "cobrado": _quantize_money(cobrado),
        "nc_emitidas": _quantize_money(nc_emitidas),
        "saldo": _quantize_money(saldo),
    }


def _resumen_factura_compra(factura, hasta=None):
    total = _quantize_money(factura.total)
    pagado_individual = sum(
        (
            _decimal(pago.monto_usd)
            for pago in factura.pagos.all()
            if (not hasta or pago.fecha <= hasta) and pago.monto_usd is not None
        ),
        Decimal("0.00"),
    )
    pagado_consolidado = sum(
        (
            _decimal(detalle.monto_aplicado)
            for detalle in factura.detalle_pagos.select_related("pago").all()
            if not hasta or detalle.pago.fecha <= hasta
        ),
        Decimal("0.00"),
    )
    pagado = pagado_individual + pagado_consolidado
    saldo = max(Decimal("0.00"), total - pagado)
    return {
        "total": _quantize_money(total),
        "pagado": _quantize_money(pagado),
        "saldo": _quantize_money(saldo),
    }


@login_required
def reporte_ventas(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_desde = request.GET.get("fecha_desde")
    fecha_hasta = request.GET.get("fecha_hasta")
    cliente_q = request.GET.get("cliente_q", "").strip()
    articulo_q = request.GET.get("articulo_q", "").strip()
    estado_pago = request.GET.get("estado_pago", "").strip()
    estado_factura = request.GET.get("estado_factura", "").strip()
    agrupar_por_cliente = request.GET.get("agrupar_por_cliente") == "1"
    mostrar_detalles = request.GET.get("mostrar_detalles") == "1"
    sort_by = request.GET.get("sort_by", "fecha")
    sort_dir = request.GET.get("sort_dir", "desc")

    qs = (
        FacturaVenta.objects.exclude(estado="ANULADA")
        .select_related("cliente")
        .prefetch_related("cobros", "notas_credito", "detalles__producto")
    )

    if fecha_desde:
        qs = qs.filter(fecha__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha__lte=fecha_hasta)
    if cliente_q:
        qs = qs.filter(
            Q(cliente__nombre__icontains=cliente_q) | Q(cliente__rif__icontains=cliente_q)
        )
    if articulo_q:
        qs = qs.filter(
            Q(detallefacturaventa__producto__nombre__icontains=articulo_q)
            | Q(detallefacturaventa__producto__codigo__icontains=articulo_q)
        ).distinct()
    if estado_factura:
        qs = qs.filter(estado=estado_factura)

    facturas = []
    total_general = Decimal("0.00")
    total_pagado = Decimal("0.00")
    total_pendiente = Decimal("0.00")
    for factura in qs:
        resumen = _resumen_factura_venta(factura)
        factura.estado_pago = _estatus_por_saldo(
            resumen["saldo"],
            resumen["total"],
            "Cobrada",
            "Parcialmente Pendiente",
            "Pendiente",
        )
        if estado_pago and factura.estado_pago != estado_pago:
            continue
        factura.total_pagado = resumen["cobrado"]
        factura.nc_emitidas_total = resumen["nc_emitidas"]
        factura.saldo_pendiente_total = resumen["saldo"]
        factura.detalles_reporte = list(factura.detalles.all())
        for detalle in factura.detalles_reporte:
            detalle.monto_usd = _monto_usd_linea(
                detalle.subtotal, factura.moneda, factura.tasa_cambio
            )
            detalle.estatus_cobro = factura.estado_pago
        total_general += resumen["total"]
        total_pagado += resumen["cobrado"]
        total_pendiente += resumen["saldo"]
        facturas.append(factura)

    sort_map = {
        "fecha": lambda f: (f.fecha, f.numero),
        "numero": lambda f: (f.numero,),
        "cliente": lambda f: ((f.cliente.nombre if f.cliente else "").lower(), f.fecha, f.numero),
    }
    facturas.sort(key=sort_map.get(sort_by, sort_map["fecha"]), reverse=(sort_dir == "desc"))

    filas = []
    if agrupar_por_cliente:
        cliente_nombre = ""
        cliente_rif = ""
        cliente_actual = None
        subtotal_total = Decimal("0.00")
        subtotal_pagado = Decimal("0.00")
        subtotal_pendiente = Decimal("0.00")
        for factura in facturas:
            if cliente_actual is None:
                cliente_actual = factura.cliente_id
            elif cliente_actual != factura.cliente_id:
                filas.append(
                    {
                        "tipo": "subtotal",
                        "cliente": cliente_nombre,
                        "rif": cliente_rif,
                        "total": subtotal_total,
                        "pagado": subtotal_pagado,
                        "pendiente": subtotal_pendiente,
                    }
                )
                subtotal_total = Decimal("0.00")
                subtotal_pagado = Decimal("0.00")
                subtotal_pendiente = Decimal("0.00")
                cliente_actual = factura.cliente_id
            cliente_nombre = factura.cliente.nombre if factura.cliente else "Sin cliente"
            cliente_rif = factura.cliente.rif if factura.cliente else ""
            subtotal_total += factura.total
            subtotal_pagado += factura.total_pagado
            subtotal_pendiente += factura.saldo_pendiente_total
            filas.append({"tipo": "factura", "factura": factura})
            for detalle in factura.detalles_reporte:
                filas.append({"tipo": "detalle", "detalle": detalle, "factura": factura})
        if facturas:
            filas.append(
                {
                    "tipo": "subtotal",
                    "cliente": cliente_nombre,
                    "rif": cliente_rif,
                    "total": subtotal_total,
                    "pagado": subtotal_pagado,
                    "pendiente": subtotal_pendiente,
                }
            )
    else:
        filas = []
        for factura in facturas:
            filas.append({"tipo": "factura", "factura": factura})
            for detalle in factura.detalles_reporte:
                filas.append({"tipo": "detalle", "detalle": detalle, "factura": factura})

    parametros = {}
    if fecha_desde:
        parametros["Desde"] = fecha_desde
    if fecha_hasta:
        parametros["Hasta"] = fecha_hasta
    if cliente_q:
        parametros["Cliente"] = cliente_q
    if articulo_q:
        parametros["Articulo"] = articulo_q
    if estado_pago:
        parametros["Estado pago"] = estado_pago
    if estado_factura:
        parametros["Estado factura"] = estado_factura
    if agrupar_por_cliente:
        parametros["Agrupar por cliente"] = "Si"

    if "exportar" in request.GET:
        columnas = [
            "Numero",
            "Fecha",
            "Cliente",
            "Total",
            "Cobrado",
            "NC",
            "Pendiente",
            "Estado de Pago",
            "Estado Factura",
        ]
        filas_export = []
        for factura in facturas:
            filas_export.append(
                [
                    factura.numero,
                    factura.fecha,
                    factura.cliente.nombre if factura.cliente else "",
                    factura.total,
                    factura.total_pagado,
                    factura.nc_emitidas_total,
                    factura.saldo_pendiente_total,
                    factura.estado_pago,
                    factura.estado,
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
        "total_pagado": total_pagado,
        "total_pendiente": total_pendiente,
        "cliente_q": cliente_q,
        "articulo_q": articulo_q,
        "estado_pago": estado_pago,
        "estado_factura": estado_factura,
        "mostrar_detalles": mostrar_detalles,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }
    return render(request, "reportes/ventas.html", context)


@login_required
def reporte_cxc(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_corte = request.GET.get("fecha_corte")
    agrupar_por_cliente = request.GET.get("agrupar_por_cliente") == "1"
    mostrar_aging = request.GET.get("mostrar_aging") == "1"
    sort_by = request.GET.get("sort_by", "cliente")
    sort_dir = request.GET.get("sort_dir", "asc")
    hasta = (
        datetime.datetime.strptime(fecha_corte, "%Y-%m-%d").date()
        if fecha_corte
        else datetime.date.today()
    )

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
        resumen = _resumen_factura_venta(fv, hasta=hasta)
        neto_pendiente = resumen["saldo"]
        if neto_pendiente <= 0:
            continue
        dias_vencida = (hasta - fv.fecha_vencimiento).days if fv.fecha_vencimiento else 0
        if dias_vencida < 0:
            dias_vencida = 0
        saldo_0_30 = neto_pendiente if 0 <= dias_vencida <= 30 else Decimal("0.00")
        saldo_31_60 = neto_pendiente if 31 <= dias_vencida <= 60 else Decimal("0.00")
        saldo_61_90 = neto_pendiente if 61 <= dias_vencida <= 90 else Decimal("0.00")
        saldo_90_plus = neto_pendiente if dias_vencida > 90 else Decimal("0.00")
        resultados.append(
            {
                "factura": fv,
                "total": resumen["total"],
                "monto_cobrado": resumen["cobrado"],
                "nc_emitidas": resumen["nc_emitidas"],
                "neto_pendiente": neto_pendiente,
                "dias_vencida": dias_vencida,
                "s_0_30": saldo_0_30,
                "s_31_60": saldo_31_60,
                "s_61_90": saldo_61_90,
                "s_90_plus": saldo_90_plus,
            }
        )
        totales["total"] += resumen["total"]
        totales["cobrado"] += resumen["cobrado"]
        totales["nc"] += resumen["nc_emitidas"]
        totales["neto_pendiente"] += neto_pendiente
        totales["pendiente"] += neto_pendiente
        totales["s_0_30"] += saldo_0_30
        totales["s_31_60"] += saldo_31_60
        totales["s_61_90"] += saldo_61_90
        totales["s_90_plus"] += saldo_90_plus

    sort_map = {
        "cliente": lambda item: ((item["factura"].cliente.nombre if item["factura"].cliente else "").lower(), item["factura"].fecha, item["factura"].numero),
        "fecha": lambda item: (item["factura"].fecha, item["factura"].numero),
        "numero": lambda item: (item["factura"].numero,),
        "saldo": lambda item: (item["neto_pendiente"], item["factura"].numero),
    }
    resultados.sort(key=sort_map.get(sort_by, sort_map["cliente"]), reverse=(sort_dir == "desc"))

    grupos_cliente = []
    if agrupar_por_cliente:
        grupos = {}
        for item in resultados:
            cliente = item["factura"].cliente
            key = cliente.pk if cliente else None
            grupos.setdefault(key, {"cliente": cliente, "items": [], "subtotal": Decimal("0.00")})
            grupos[key]["items"].append(item)
            grupos[key]["subtotal"] += item["neto_pendiente"]
        grupos_cliente = list(grupos.values())
        grupos_cliente.sort(key=lambda grupo: (grupo["cliente"].nombre if grupo["cliente"] else ""))

    parametros = {"Fecha corte": fecha_corte or str(hasta)}
    if agrupar_por_cliente:
        parametros["Agrupar por cliente"] = "Si"

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
        "agrupar_por_cliente": agrupar_por_cliente,
        "grupos_cliente": grupos_cliente,
        "mostrar_aging": mostrar_aging,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }
    return render(request, "reportes/cxc.html", context)


@login_required
def reporte_compras(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_desde = request.GET.get("fecha_desde")
    fecha_hasta = request.GET.get("fecha_hasta")
    proveedor_q = request.GET.get("proveedor_q", "").strip()
    articulo_q = request.GET.get("articulo_q", "").strip()
    estado_pago = request.GET.get("estado_pago", "").strip()
    estado_factura = request.GET.get("estado_factura", "").strip()
    agrupar_por_proveedor = request.GET.get("agrupar_por_proveedor") == "1"
    mostrar_detalles = request.GET.get("mostrar_detalles") == "1"
    sort_by = request.GET.get("sort_by", "fecha")
    sort_dir = request.GET.get("sort_dir", "desc")

    qs = (
        FacturaCompra.objects.exclude(estado="ANULADA")
        .select_related("proveedor")
        .prefetch_related("pagos", "detalle_pagos__pago", "detalles__producto")
    )

    if fecha_desde:
        qs = qs.filter(fecha__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha__lte=fecha_hasta)
    if proveedor_q:
        qs = qs.filter(
            Q(proveedor__nombre__icontains=proveedor_q) | Q(proveedor__rif__icontains=proveedor_q)
        )
    if articulo_q:
        qs = qs.filter(
            Q(detalles__producto__nombre__icontains=articulo_q)
            | Q(detalles__producto__codigo__icontains=articulo_q)
        ).distinct()
    if estado_factura:
        qs = qs.filter(estado=estado_factura)

    facturas = []
    total_general = Decimal("0.00")
    total_pagado = Decimal("0.00")
    total_pendiente = Decimal("0.00")
    for factura in qs:
        resumen = _resumen_factura_compra(factura)
        factura.estado_pago = _estatus_por_saldo(
            resumen["saldo"],
            resumen["total"],
            "Pagada",
            "Parcialmente Pendiente",
            "Pendiente",
        )
        if estado_pago and factura.estado_pago != estado_pago:
            continue
        factura.total_pagado = resumen["pagado"]
        factura.saldo_pendiente_total = resumen["saldo"]
        factura.detalles_reporte = list(factura.detalles.all())
        for detalle in factura.detalles_reporte:
            detalle.monto_usd = _monto_usd_linea(
                detalle.subtotal, factura.moneda, factura.tasa_cambio
            )
            detalle.estatus_cobro = factura.estado_pago
        total_general += resumen["total"]
        total_pagado += resumen["pagado"]
        total_pendiente += resumen["saldo"]
        facturas.append(factura)

    sort_map = {
        "fecha": lambda f: (f.fecha, f.numero),
        "numero": lambda f: (f.numero,),
        "proveedor": lambda f: ((f.proveedor.nombre if f.proveedor else "").lower(), f.fecha, f.numero),
    }
    facturas.sort(key=sort_map.get(sort_by, sort_map["fecha"]), reverse=(sort_dir == "desc"))

    filas = []
    if agrupar_por_proveedor:
        proveedor_nombre = ""
        proveedor_rif = ""
        proveedor_actual = None
        subtotal_total = Decimal("0.00")
        subtotal_pagado = Decimal("0.00")
        subtotal_pendiente = Decimal("0.00")
        for factura in facturas:
            if proveedor_actual is None:
                proveedor_actual = factura.proveedor_id
            elif proveedor_actual != factura.proveedor_id:
                filas.append(
                    {
                        "tipo": "subtotal",
                        "proveedor": proveedor_nombre,
                        "rif": proveedor_rif,
                        "total": subtotal_total,
                        "pagado": subtotal_pagado,
                        "pendiente": subtotal_pendiente,
                    }
                )
                subtotal_total = Decimal("0.00")
                subtotal_pagado = Decimal("0.00")
                subtotal_pendiente = Decimal("0.00")
                proveedor_actual = factura.proveedor_id
            proveedor_nombre = factura.proveedor.nombre if factura.proveedor else "Sin proveedor"
            proveedor_rif = factura.proveedor.rif if factura.proveedor else ""
            subtotal_total += factura.total
            subtotal_pagado += factura.total_pagado
            subtotal_pendiente += factura.saldo_pendiente_total
            filas.append({"tipo": "factura", "factura": factura})
            for detalle in factura.detalles_reporte:
                filas.append({"tipo": "detalle", "detalle": detalle, "factura": factura})
        if facturas:
            filas.append(
                {
                    "tipo": "subtotal",
                    "proveedor": proveedor_nombre,
                    "rif": proveedor_rif,
                    "total": subtotal_total,
                    "pagado": subtotal_pagado,
                    "pendiente": subtotal_pendiente,
                }
            )
    else:
        filas = []
        for factura in facturas:
            filas.append({"tipo": "factura", "factura": factura})
            for detalle in factura.detalles_reporte:
                filas.append({"tipo": "detalle", "detalle": detalle, "factura": factura})

    parametros = {}
    if fecha_desde:
        parametros["Desde"] = fecha_desde
    if fecha_hasta:
        parametros["Hasta"] = fecha_hasta
    if proveedor_q:
        parametros["Proveedor"] = proveedor_q
    if articulo_q:
        parametros["Articulo"] = articulo_q
    if estado_pago:
        parametros["Estado pago"] = estado_pago
    if estado_factura:
        parametros["Estado factura"] = estado_factura
    if agrupar_por_proveedor:
        parametros["Agrupar por proveedor"] = "Si"

    if "exportar" in request.GET:
        columnas = [
            "Numero",
            "Fecha",
            "Proveedor",
            "Total",
            "Pagado",
            "Pendiente",
            "Estado de Pago",
            "Estado Factura",
        ]
        filas_export = []
        for factura in facturas:
            filas_export.append(
                [
                    factura.numero,
                    factura.fecha,
                    factura.proveedor.nombre if factura.proveedor else "",
                    factura.total,
                    factura.total_pagado,
                    factura.saldo_pendiente_total,
                    factura.estado_pago,
                    factura.estado,
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
        "total_pagado": total_pagado,
        "total_pendiente": total_pendiente,
        "proveedor_q": proveedor_q,
        "articulo_q": articulo_q,
        "estado_pago": estado_pago,
        "estado_factura": estado_factura,
        "mostrar_detalles": mostrar_detalles,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }
    return render(request, "reportes/compras.html", context)


@login_required
def reporte_cxp(request):
    """
    CxP sincronizado con FacturaCompra.get_saldo_pendiente() y pagos consolidados.
    """
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_corte = request.GET.get("fecha_corte")
    tipo_reporte = request.GET.get("tipo", "TODOS")
    agrupar_por_proveedor = request.GET.get("agrupar_por_proveedor") == "1"
    mostrar_aging = request.GET.get("mostrar_aging") == "1"
    sort_by = request.GET.get("sort_by", "proveedor")
    sort_dir = request.GET.get("sort_dir", "asc")
    hasta = (
        datetime.datetime.strptime(fecha_corte, "%Y-%m-%d").date()
        if fecha_corte
        else datetime.date.today()
    )

    resultados = []
    totales = {
        "total": Decimal("0.00"),
        "pagado": Decimal("0.00"),
        "pendiente": Decimal("0.00"),
        "s_0_30": Decimal("0.00"),
        "s_31_60": Decimal("0.00"),
        "s_61_90": Decimal("0.00"),
        "s_90_plus": Decimal("0.00"),
    }

    if tipo_reporte in ["TODOS", "COMPRAS"]:
        facturas = (
            FacturaCompra.objects.filter(estado="APROBADA", fecha__lte=hasta)
            .select_related("proveedor")
            .prefetch_related("pagos", "detalle_pagos__pago")
        )
        for fv in facturas:
            resumen = _resumen_factura_compra(fv, hasta=hasta)
            saldo = resumen["saldo"]
            if saldo <= 0:
                continue
            dias_vencida = (hasta - fv.fecha_vencimiento).days if fv.fecha_vencimiento else 0
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
                    "monto_original": resumen["total"],
                    "monto_pagado": resumen["pagado"],
                    "saldo": saldo,
                    "dias": dias_vencida,
                    "s_0": s_0,
                    "s_31": s_31,
                    "s_61": s_61,
                    "s_90": s_90,
                }
            )
            totales["total"] += resumen["total"]
            totales["pagado"] += resumen["pagado"]
            totales["pendiente"] += saldo
            totales["s_0_30"] += s_0
            totales["s_31_60"] += s_31
            totales["s_61_90"] += s_61
            totales["s_90_plus"] += s_90

    if tipo_reporte in ["TODOS", "GASTOS_SERVICIOS"]:
        gastos = GastoServicio.objects.filter(estado="PENDIENTE", fecha_emision__lte=hasta).select_related("proveedor")
        for gs in gastos:
            saldo = _monto_usd_gasto(gs)
            dias_vencida = (hasta - gs.fecha_vencimiento).days if gs.fecha_vencimiento else 0
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
                    "monto_original": saldo,
                    "monto_pagado": Decimal("0.00"),
                    "saldo": saldo,
                    "dias": dias_vencida,
                    "s_0": s_0,
                    "s_31": s_31,
                    "s_61": s_61,
                    "s_90": s_90,
                }
            )
            totales["total"] += saldo
            totales["pendiente"] += saldo
            totales["s_0_30"] += s_0
            totales["s_31_60"] += s_31
            totales["s_61_90"] += s_61
            totales["s_90_plus"] += s_90

    resultados_proveedores = resultados
    totales_proveedores = dict(totales)

    from django.db.models import Sum as _Sum
    prestamos = PrestamoPorSocio.objects.filter(
        estado='ACTIVO'
    ).select_related('socio').annotate(
        total_pagado_p=Coalesce(
            _Sum('pagos__monto_usd'),
            Value(Decimal('0.00')),
            output_field=DecimalField(),
        )
    )

    resultados_socios = []
    total_socios = Decimal('0.00')
    for p in prestamos:
        pagado = Decimal(str(p.total_pagado_p))
        monto_original = Decimal(str(p.monto_usd))
        saldo = max(Decimal('0.00'), monto_original - pagado)
        if saldo <= 0:
            continue
        resultados_socios.append({
            'prestamo': p,
            'socio': p.socio.nombre,
            'numero': p.numero,
            'fecha': p.fecha_prestamo,
            'monto_original': monto_original,
            'pagado': pagado,
            'saldo': saldo,
        })
        total_socios += saldo

    def _fecha_documento_cxp(item):
        doc = item["documento"]
        return (
            getattr(doc, "fecha_vencimiento", None)
            or getattr(doc, "fecha_emision", None)
            or getattr(doc, "fecha", None)
        )

    sort_map = {
        "proveedor": lambda item: (
            (item["documento"].proveedor.nombre if item["documento"].proveedor else "").lower(),
            _fecha_documento_cxp(item),
            item["documento"].numero,
        ),
        "fecha": lambda item: (_fecha_documento_cxp(item), item["documento"].numero),
        "numero": lambda item: (item["documento"].numero,),
        "saldo": lambda item: (item["saldo"], item["documento"].numero),
    }
    resultados.sort(key=sort_map.get(sort_by, sort_map["proveedor"]), reverse=(sort_dir == "desc"))

    grupos_proveedor = []
    if agrupar_por_proveedor:
        grupos = {}
        for item in resultados:
            proveedor = item["documento"].proveedor
            key = proveedor.pk if proveedor else None
            grupos.setdefault(key, {"proveedor": proveedor, "items": [], "subtotal": Decimal("0.00")})
            grupos[key]["items"].append(item)
            grupos[key]["subtotal"] += item["saldo"]
        grupos_proveedor = list(grupos.values())
        grupos_proveedor.sort(key=lambda grupo: (grupo["proveedor"].nombre if grupo["proveedor"] else ""))

    total_general_cxp = totales_proveedores['pendiente'] + total_socios

    parametros = {
        "Fecha corte": fecha_corte or str(hasta),
        "Tipo": tipo_reporte,
    }

    if "exportar" in request.GET:
        columnas = [
            "Proveedor / Socio",
            "Tipo Doc.",
            "No. Documento",
            "Vencimiento",
            "Dias Vencida",
            "Monto USD Original",
            "Monto Pagado USD",
            "Saldo Pendiente USD",
            "0-30 Dias",
            "31-60 Dias",
            "61-90 Dias",
            "+90 Dias",
        ]
        filas = []
        for item in resultados:
            doc = item["documento"]
            filas.append(
                [
                    doc.proveedor.nombre if doc.proveedor else "",
                    "Gasto/Servicio" if item["es_gasto"] else "Factura Compra",
                    doc.numero,
                    doc.fecha_vencimiento,
                    item["dias"],
                    item["monto_original"],
                    item["monto_pagado"],
                    item["saldo"],
                    item["s_0"],
                    item["s_31"],
                    item["s_61"],
                    item["s_90"],
                ]
            )
        filas.append(["--- PRESTAMOS DE SOCIOS ---", "", "", "", "", "", "", "", "", "", "", ""])
        for item in resultados_socios:
            filas.append(
                [
                    item["socio"],
                    "Prestamo Socio",
                    item["numero"],
                    item["prestamo"].fecha_vencimiento or "",
                    "",
                    item["monto_original"],
                    item["pagado"],
                    item["saldo"],
                    "",
                    "",
                    "",
                    "",
                ]
            )
        filas.append(["TOTAL GENERAL CXP", "", "", "", "", "", "", total_general_cxp, "", "", "", ""])
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
        "resultados_proveedores": resultados_proveedores,
        "totales_proveedores": totales_proveedores,
        "resultados_socios": resultados_socios,
        "total_socios": total_socios,
        "total_general_cxp": total_general_cxp,
        "agrupar_por_proveedor": agrupar_por_proveedor,
        "grupos_proveedor": grupos_proveedor,
        "mostrar_aging": mostrar_aging,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
    }
    return render(request, "reportes/cxp.html", context)


@login_required
def reporte_produccion(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_desde = request.GET.get("fecha_desde")
    fecha_hasta = request.GET.get("fecha_hasta")
    producto_q = request.GET.get("producto_q", "").strip()
    producto_ids = request.GET.getlist("producto")
    modo = request.GET.get("modo", "detallado")
    incluir_consumos = request.GET.get("incluir_consumos", "1") == "1"
    incluir_productos = request.GET.get("incluir_productos", "1") == "1"

    qs = OrdenProduccion.objects.all()
    if fecha_desde:
        qs = qs.filter(fecha_apertura__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha_apertura__lte=fecha_hasta)
    if producto_ids:
        qs = qs.filter(salidas__producto_id__in=producto_ids).distinct()
    elif producto_q:
        qs = qs.filter(
            Q(salidas__producto__nombre__icontains=producto_q)
            | Q(salidas__producto__codigo__icontains=producto_q)
        ).distinct()

    parametros = {
        "Modo": modo,
        "Mostrar consumos": "Si" if incluir_consumos else "No",
        "Mostrar productos": "Si" if incluir_productos else "No",
    }
    if fecha_desde:
        parametros["Desde"] = fecha_desde
    if fecha_hasta:
        parametros["Hasta"] = fecha_hasta
    if producto_ids:
        parametros["Producto"] = ", ".join(producto_ids)
    elif producto_q:
        parametros["Producto"] = producto_q

    context = {
        "empresa": empresa,
        "fecha_desde": fecha_desde,
        "fecha_hasta": fecha_hasta,
        "producto_q": producto_q,
        "modo": modo,
        "incluir_consumos": incluir_consumos,
        "incluir_productos": incluir_productos,
    }

    ordenes = list(
        qs.prefetch_related(
            "salidas__producto__unidad_medida",
            "consumos__producto__unidad_medida",
        ).order_by("-fecha_apertura", "-id")
    )
    for orden in ordenes:
        orden.consumos_reporte = list(orden.consumos.all())
        orden.salidas_reporte = list(orden.salidas.all())
        orden.mp_total = sum((c.subtotal for c in orden.consumos_reporte), Decimal("0.00"))
        orden.total_productos = sum((s.costo_asignado or Decimal("0.00") for s in orden.salidas_reporte), Decimal("0.00"))
        orden.yield_display = orden.rendimiento_real or Decimal("0.00")
        for salida in orden.salidas_reporte:
            if salida.cantidad > 0:
                salida.cu = (salida.costo_asignado or Decimal("0.00")) / salida.cantidad
            else:
                salida.cu = Decimal("0.00")
        for consumo in orden.consumos_reporte:
            consumo.costo_unitario_display = consumo.costo_unitario or Decimal("0.00")

    total_general_mp = sum((o.mp_total for o in ordenes), Decimal("0.00"))
    total_general_productos = sum((o.total_productos for o in ordenes), Decimal("0.00"))

    context.update({
        "ordenes": ordenes,
        "total_general_mp": total_general_mp,
        "total_general_productos": total_general_productos,
    })

    if modo == "consolidado":
        context["total_ordenes"] = len(ordenes)
        if incluir_consumos:
            consumos_consolidados = list(
                ConsumoOP.objects.filter(orden__in=qs)
                .values("producto__codigo", "producto__nombre", "producto__unidad_medida__simbolo")
                .annotate(total_cantidad=Sum("cantidad_consumida"), total_costo=Sum("subtotal"))
                .order_by("producto__nombre")
            )
            context["consumos_consolidados"] = consumos_consolidados
            context["total_consumos_costo"] = sum((c["total_costo"] or Decimal("0.00") for c in consumos_consolidados), Decimal("0.00"))
        if incluir_productos:
            productos_consolidados = list(
                SalidaOrden.objects.filter(orden__in=qs)
                .values("producto__codigo", "producto__nombre", "producto__unidad_medida__simbolo")
                .annotate(total_cantidad=Sum("cantidad"), total_costo=Sum("costo_asignado"))
                .order_by("producto__nombre")
            )
            context["productos_consolidados"] = productos_consolidados
            context["total_kg_producidos"] = sum((p["total_cantidad"] or Decimal("0.00") for p in productos_consolidados), Decimal("0.00"))

    if "exportar" in request.GET:
        columnas = [
            "No. Orden",
            "Fecha",
            "Estado",
            "Rendimiento",
            "Tipo",
            "Producto",
            "Cantidad",
            "Unidad",
            "Costo USD",
        ]
        filas = []
        for orden in ordenes:
            if incluir_consumos:
                for consumo in orden.consumos_reporte:
                    filas.append([orden.numero, orden.fecha_apertura, orden.estado, orden.yield_display, "Consumo", consumo.producto.nombre, consumo.cantidad_consumida, consumo.producto.unidad_medida.simbolo if consumo.producto.unidad_medida else "", consumo.subtotal])
            if incluir_productos:
                for salida in orden.salidas_reporte:
                    filas.append([orden.numero, orden.fecha_apertura, orden.estado, orden.yield_display, "Producto", salida.producto.nombre, salida.cantidad, salida.producto.unidad_medida.simbolo if salida.producto.unidad_medida else "", salida.costo_asignado or Decimal("0.00")])
        return exportar_excel(
            "reporte_produccion",
            columnas,
            [[str(v) for v in fila] for fila in filas],
            empresa=empresa,
            parametros=parametros,
        )

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
    for gasto in gastos:
        gasto.monto_usd_calculado = _monto_usd_gasto(gasto)
    total_usd = sum((g.monto_usd_calculado for g in gastos), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

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
        monto = g.monto_usd_calculado
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
                    "subtotal": sum((g.monto_usd_calculado for g in items), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                }
                for subcat, items in sorted(subcats.items(), key=lambda x: x[0].nombre)
            ],
            "subtotal": sum((g.monto_usd_calculado for subcats_items in grupos_nivel2.get(padre, {}).values() for g in subcats_items), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
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
                        g.monto_usd_calculado,
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
    facturas_aprobadas = FacturaCompra.objects.filter(
        estado="APROBADA", fecha__lte=hasta
    ).prefetch_related("pagos", "detalle_pagos__pago")
    for f in facturas_aprobadas:
        cxp_compras += _resumen_factura_compra(f, hasta=hasta)["saldo"]
    cxp_compras = q(cxp_compras)

    # Pasivo Corriente: CxP Gastos
    cxp_gastos = Decimal("0.00")
    gastos_base = list(
        GastoServicio.objects.filter(
            estado="PENDIENTE", fecha_emision__lte=hasta
        ).select_related("categoria_gasto", "categoria_gasto__padre")
    )
    for g in gastos_base:
        cxp_gastos += _monto_usd_gasto(g)
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
        g.monto_usd_calculado = _monto_usd_gasto(g)
        monto = g.monto_usd_calculado
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
                    "subtotal": sum((g.monto_usd_calculado for g in items), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                }
                for subcat, items in sorted(subcats.items(), key=lambda x: x[0].nombre)
            ],
            "subtotal": sum((g.monto_usd_calculado for subcats_items in _grupos_n2.get(padre, {}).values() for g in subcats_items), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
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
        "sources_info": {
            "efectivo": "CuentaBancaria.saldo_actual reexpresado a USD en views.reporte_capital_trabajo()",
            "cxc": "FacturaVenta + cobros + notas_credito via _resumen_factura_venta() con fecha de corte",
            "inventario": "Producto.stock_actual * costo_promedio/precio_venta en views.reporte_capital_trabajo()",
            "cxp_compras": "FacturaCompra + pagos + detalle_pagos via _resumen_factura_compra() con fecha de corte",
            "cxp_gastos": "GastoServicio pendiente usando monto_usd o recalculo monto/tasa cuando monto_usd historico es 0",
            "prestamos_corriente": "PrestamoPorSocio activo con annotate(Sum pagos__monto_usd)",
            "prestamos_no_corriente": "PrestamoPorSocio activo con annotate(Sum pagos__monto_usd)",
            "capital_neto": "Activo corriente - pasivo corriente calculado en views.reporte_capital_trabajo()",
        },
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

    def _parse_fecha(valor):
        if not valor:
            return None
        try:
            return datetime.datetime.strptime(valor, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _signo(tipo):
        if tipo in ("ENTRADA", "TRANSFERENCIA_ENTRADA", "ABONO"):
            return Decimal("1")
        return Decimal("-1")

    fecha_desde_date = _parse_fecha(fecha_desde)
    fecha_hasta_date = _parse_fecha(fecha_hasta)

    mc_qs = MovimientoCaja.objects.select_related("cuenta").all()
    mt_qs = MovimientoTesoreria.objects.select_related("cuenta", "categoria").all()
    if cuentas_ids:
        mc_qs = mc_qs.filter(cuenta_id__in=cuentas_ids)
        mt_qs = mt_qs.filter(cuenta_id__in=cuentas_ids)

    movimientos_todos = []
    for m in mc_qs:
        monto_ves = _quantize_money(m.monto if m.moneda == "VES" else _decimal(m.monto_usd) * _decimal(m.tasa_cambio or 1))
        movimientos_todos.append({
            "fecha": m.fecha,
            "cuenta": m.cuenta,
            "origen": "Caja",
            "tipo": m.tipo,
            "referencia": m.referencia,
            "descripcion": m.notas or "",
            "monto": _quantize_money(m.monto),
            "monto_ves": monto_ves,
            "moneda": m.moneda,
            "tasa": _decimal(m.tasa_cambio),
            "monto_usd": _quantize_money(m.monto_usd),
        })
    for m in mt_qs:
        monto_ves = _quantize_money(m.monto if m.moneda == "VES" else _decimal(m.monto_usd) * _decimal(m.tasa_cambio or 1))
        movimientos_todos.append({
            "fecha": m.fecha,
            "cuenta": m.cuenta,
            "origen": "Tesorer?a",
            "tipo": m.tipo,
            "referencia": m.numero,
            "descripcion": m.descripcion,
            "monto": _quantize_money(m.monto),
            "monto_ves": monto_ves,
            "moneda": m.moneda,
            "tasa": _decimal(m.tasa_cambio),
            "monto_usd": _quantize_money(m.monto_usd),
        })

    if tipos_sel:
        movimientos_todos = [m for m in movimientos_todos if m["tipo"] in tipos_sel]

    movimientos_todos.sort(key=lambda m: (m["fecha"], m["cuenta"].nombre, m["referencia"]))

    saldo_inicial = {}
    saldo_inicial_usd = {}
    movimientos = []
    running_native = {}
    running_usd = {}
    for mov in movimientos_todos:
        cid = mov["cuenta"].pk
        running_native.setdefault(cid, Decimal("0.00"))
        running_usd.setdefault(cid, Decimal("0.00"))
        signo = _signo(mov["tipo"])
        monto_nativo = mov["monto"] if mov["cuenta"].moneda == mov["moneda"] else mov["monto_usd"]
        running_native[cid] += signo * _decimal(monto_nativo)
        running_usd[cid] += signo * _decimal(mov["monto_usd"])

        if fecha_desde_date and mov["fecha"] < fecha_desde_date:
            saldo_inicial[cid] = running_native[cid]
            saldo_inicial_usd[cid] = running_usd[cid]
            continue
        if fecha_hasta_date and mov["fecha"] > fecha_hasta_date:
            continue
        mov["saldo_cuenta"] = _quantize_money(running_native[cid])
        mov["saldo_usd"] = _quantize_money(running_usd[cid])
        mov["saldo_ves"] = _quantize_money(running_native[cid] if mov["cuenta"].moneda == "VES" else running_usd[cid] * (mov["tasa"] or Decimal("1.00")))
        movimientos.append(mov)

    resumen = {}
    for cuenta in cuentas_qs:
        cid = cuenta.pk
        resumen[cid] = {
            "cuenta": cuenta,
            "saldo_inicial": _quantize_money(saldo_inicial.get(cid, Decimal("0.00"))),
            "saldo_inicial_usd": _quantize_money(saldo_inicial_usd.get(cid, Decimal("0.00"))),
            "entradas_usd": Decimal("0.00"),
            "salidas_usd": Decimal("0.00"),
        }
    for m in movimientos:
        cid = m["cuenta"].pk
        monto_usd = m["monto_usd"]
        if _signo(m["tipo"]) > 0:
            resumen[cid]["entradas_usd"] += monto_usd
        else:
            resumen[cid]["salidas_usd"] += monto_usd

    resumen_list = []
    total_entradas = Decimal("0.00")
    total_salidas = Decimal("0.00")
    total_saldo_inicial = Decimal("0.00")
    total_saldo_inicial_usd = Decimal("0.00")
    for v in resumen.values():
        v["neto"] = v["entradas_usd"] - v["salidas_usd"]
        total_entradas += v["entradas_usd"]
        total_salidas += v["salidas_usd"]
        total_saldo_inicial += v["saldo_inicial"]
        total_saldo_inicial_usd += v["saldo_inicial_usd"]
        resumen_list.append(v)
    resumen_list.sort(key=lambda r: r["cuenta"].nombre)
    total_neto = total_entradas - total_salidas

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
        "total_saldo_inicial": total_saldo_inicial,
        "total_saldo_inicial_usd": total_saldo_inicial_usd,
        "titulo": "Reporte de Tesorer?a",
    }
    return render(request, "reportes/tesoreria.html", context)


@login_required
def marcar_notificacion_leida(request, notif_id):
    leidas = request.session.get("notif_leidas", [])
    if notif_id not in leidas:
        leidas.append(notif_id)
    request.session["notif_leidas"] = leidas
    return JsonResponse({"ok": True})
