import datetime
from decimal import Decimal, ROUND_HALF_UP
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum, F, Value, DecimalField
from django.db.models.functions import Coalesce

from apps.core.models import ConfiguracionEmpresa
from apps.ventas.models import FacturaVenta, Cliente, DetalleFacturaVenta
from apps.compras.models import FacturaCompra, Proveedor, DetalleFacturaCompra, GastoServicio
from apps.produccion.models import OrdenProduccion, ConsumoOP, SalidaOrden
from apps.bancos.models import CuentaBancaria
from apps.almacen.models import Producto
from apps.compras.models import GastoServicio as Gs


def _check_reporte_perm(request):
    """B9 — Verifica que el usuario tiene permiso de ver reportes."""
    if request.user.is_superuser:
        return
    if not request.user.has_perm('reportes.view_reportelink'):
        raise PermissionDenied('No tiene permiso para acceder a los reportes.')


@login_required
def reporte_ventas(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_desde = request.GET.get('fecha_desde')
    fecha_hasta = request.GET.get('fecha_hasta')
    clientes_ids = request.GET.getlist('cliente')
    productos_ids = request.GET.getlist('articulo')
    estados = request.GET.getlist('estado')
    agrupar_por_cliente = request.GET.get('agrupar_por_cliente') == '1'

    qs = DetalleFacturaVenta.objects.select_related('factura', 'factura__cliente', 'producto').all()

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

    detalles = list(qs.order_by('factura__fecha', 'factura__numero'))

    context = {
        'empresa': empresa,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'agrupar_por_cliente': agrupar_por_cliente,
        'detalles': detalles,
        'clientes': Cliente.objects.all(),
        'productos': Producto.objects.filter(activo=True),
    }
    return render(request, 'reportes/ventas.html', context)


@login_required
def reporte_cxc(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_corte = request.GET.get('fecha_corte')
    hasta = datetime.datetime.strptime(fecha_corte, "%Y-%m-%d").date() if fecha_corte else datetime.date.today()

    facturas = FacturaVenta.objects.filter(
        estado='EMITIDA',
        fecha__lte=hasta
    ).select_related('cliente')

    resultados = []
    totales = {
        'total': Decimal('0.00'), 'pendiente': Decimal('0.00'),
        's_0_30': Decimal('0.00'), 's_31_60': Decimal('0.00'),
        's_61_90': Decimal('0.00'), 's_90_plus': Decimal('0.00'),
    }

    for fv in facturas:
        cobrado_hasta = sum(c.monto for c in fv.cobros.filter(fecha__lte=hasta)) if hasattr(fv, 'cobros') else Decimal('0.00')
        saldo = fv.total - cobrado_hasta
        if saldo > 0:
            dias_vencida = (hasta - fv.fecha_vencimiento).days if fv.fecha_vencimiento else 0
            if dias_vencida < 0:
                dias_vencida = 0

            saldo_0_30 = saldo if 0 <= dias_vencida <= 30 else Decimal('0.00')
            saldo_31_60 = saldo if 31 <= dias_vencida <= 60 else Decimal('0.00')
            saldo_61_90 = saldo if 61 <= dias_vencida <= 90 else Decimal('0.00')
            saldo_90_plus = saldo if dias_vencida > 90 else Decimal('0.00')

            resultados.append({
                'factura': fv,
                'saldo': saldo,
                'dias_vencida': dias_vencida,
                's_0_30': saldo_0_30,
                's_31_60': saldo_31_60,
                's_61_90': saldo_61_90,
                's_90_plus': saldo_90_plus,
            })
            totales['total'] += fv.total
            totales['pendiente'] += saldo
            totales['s_0_30'] += saldo_0_30
            totales['s_31_60'] += saldo_31_60
            totales['s_61_90'] += saldo_61_90
            totales['s_90_plus'] += saldo_90_plus

    context = {
        'empresa': empresa,
        'fecha_corte': hasta,
        'resultados': resultados,
        'totales': totales,
    }
    return render(request, 'reportes/cxc.html', context)


@login_required
def reporte_compras(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_desde = request.GET.get('fecha_desde')
    fecha_hasta = request.GET.get('fecha_hasta')
    proveedor_ids = request.GET.getlist('proveedor')
    productos_ids = request.GET.getlist('articulo')
    estados = request.GET.getlist('estado')
    agrupar_por_proveedor = request.GET.get('agrupar_por_proveedor') == '1'

    qs = DetalleFacturaCompra.objects.select_related('factura', 'factura__proveedor', 'producto').all()

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

    detalles = list(qs.order_by('factura__fecha', 'factura__numero'))

    context = {
        'empresa': empresa,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'agrupar_por_proveedor': agrupar_por_proveedor,
        'detalles': detalles,
        'proveedores': Proveedor.objects.all(),
        'productos': Producto.objects.filter(activo=True),
    }
    return render(request, 'reportes/compras.html', context)


@login_required
def reporte_cxp(request):
    """
    B3 — CxP con pagos parciales: usa annotate + Coalesce para calcular saldo.
    Filtra facturas APROBADA (no RECIBIDA) porque los pagos van contra APROBADAS.
    """
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_corte = request.GET.get('fecha_corte')
    tipo_reporte = request.GET.get('tipo', 'TODOS')
    hasta = datetime.datetime.strptime(fecha_corte, "%Y-%m-%d").date() if fecha_corte else datetime.date.today()

    resultados = []
    totales = {
        'total': Decimal('0.00'), 'pendiente': Decimal('0.00'),
        's_0_30': Decimal('0.00'), 's_31_60': Decimal('0.00'),
        's_61_90': Decimal('0.00'), 's_90_plus': Decimal('0.00'),
    }

    if tipo_reporte in ['TODOS', 'COMPRAS']:
        # B3 fix: estado APROBADA + Coalesce para pagos parciales
        facturas = (
            FacturaCompra.objects
            .filter(estado='APROBADA', fecha__lte=hasta)
            .select_related('proveedor')
            .annotate(
                total_pagado=Coalesce(
                    Sum('pagos__monto_usd'),
                    Value(Decimal('0.00')),
                    output_field=DecimalField(),
                )
            )
            .annotate(saldo=F('total') - F('total_pagado'))
            .filter(saldo__gt=0)
        )

        for fv in facturas:
            saldo = Decimal(str(fv.saldo))
            dias_vencida = (hasta - fv.fecha_vencimiento).days if fv.fecha_vencimiento else 0
            if dias_vencida < 0:
                dias_vencida = 0

            s_0 = saldo if 0 <= dias_vencida <= 30 else Decimal('0.00')
            s_31 = saldo if 31 <= dias_vencida <= 60 else Decimal('0.00')
            s_61 = saldo if 61 <= dias_vencida <= 90 else Decimal('0.00')
            s_90 = saldo if dias_vencida > 90 else Decimal('0.00')

            resultados.append({
                'es_gasto': False,
                'documento': fv,
                'saldo': saldo,
                'dias': dias_vencida,
                's_0': s_0, 's_31': s_31, 's_61': s_61, 's_90': s_90,
            })
            totales['pendiente'] += saldo
            totales['s_0_30'] += s_0
            totales['s_31_60'] += s_31
            totales['s_61_90'] += s_61
            totales['s_90_plus'] += s_90

    if tipo_reporte in ['TODOS', 'GASTOS_SERVICIOS']:
        gastos = GastoServicio.objects.filter(
            estado='PENDIENTE',
            fecha_emision__lte=hasta
        ).select_related('proveedor')
        for gs in gastos:
            saldo = Decimal(str(gs.monto_usd))
            dias_vencida = (hasta - gs.fecha_vencimiento).days if gs.fecha_vencimiento else 0
            if dias_vencida < 0:
                dias_vencida = 0

            s_0 = saldo if 0 <= dias_vencida <= 30 else Decimal('0.00')
            s_31 = saldo if 31 <= dias_vencida <= 60 else Decimal('0.00')
            s_61 = saldo if 61 <= dias_vencida <= 90 else Decimal('0.00')
            s_90 = saldo if dias_vencida > 90 else Decimal('0.00')

            resultados.append({
                'es_gasto': True,
                'documento': gs,
                'saldo': saldo,
                'dias': dias_vencida,
                's_0': s_0, 's_31': s_31, 's_61': s_61, 's_90': s_90,
            })
            totales['pendiente'] += saldo
            totales['s_0_30'] += s_0
            totales['s_31_60'] += s_31
            totales['s_61_90'] += s_61
            totales['s_90_plus'] += s_90

    context = {
        'empresa': empresa,
        'fecha_corte': hasta,
        'tipo': tipo_reporte,
        'resultados': resultados,
        'totales': totales,
    }
    return render(request, 'reportes/cxp.html', context)


@login_required
def reporte_produccion(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_desde = request.GET.get('fecha_desde')
    fecha_hasta = request.GET.get('fecha_hasta')

    qs = OrdenProduccion.objects.all()
    if fecha_desde:
        qs = qs.filter(fecha_apertura__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha_apertura__lte=fecha_hasta)

    ordenes = list(qs.prefetch_related('salidas__producto__unidad_medida').order_by('-fecha_apertura'))

    for orden in ordenes:
        orden.mp_total = sum(c.subtotal for c in orden.consumos.all())
        for s in orden.salidas.all():
            if s.producto.unidad_medida.simbolo.lower() == 'kg':
                s.kg_totales = s.cantidad
            else:
                if s.producto.peso_unitario_kg:
                    s.kg_totales = s.cantidad * s.producto.peso_unitario_kg
                else:
                    s.kg_totales = None

            if s.cantidad > 0:
                s.cu = s.costo_asignado / s.cantidad
            else:
                s.cu = Decimal('0.00')

    context = {
        'empresa': empresa,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'ordenes': ordenes,
    }
    return render(request, 'reportes/produccion.html', context)


@login_required
def reporte_gastos(request):
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_desde = request.GET.get('fecha_desde')
    fecha_hasta = request.GET.get('fecha_hasta')
    categorias = request.GET.getlist('categoria')
    estado = request.GET.get('estado')

    qs = GastoServicio.objects.select_related('proveedor').all()
    if fecha_desde:
        qs = qs.filter(fecha_emision__gte=fecha_desde)
    if fecha_hasta:
        qs = qs.filter(fecha_emision__lte=fecha_hasta)
    if categorias:
        qs = qs.filter(categoria_gasto__in=categorias)
    if estado:
        qs = qs.filter(estado=estado)

    gastos = list(qs.order_by('fecha_emision'))
    total_usd = sum(g.monto_usd for g in gastos)

    all_categorias = set(g.categoria_gasto for g in Gs.objects.all())

    context = {
        'empresa': empresa,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'gastos': gastos,
        'total_usd': total_usd,
        'todas_categorias': all_categorias,
    }
    return render(request, 'reportes/gastos.html', context)


@login_required
def reporte_capital_trabajo(request):
    """
    B4 — Aplica quantize(0.01) a TODOS los totales y subtotales.
    """
    _check_reporte_perm(request)  # B9
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_corte = request.GET.get('fecha_corte')
    hasta = datetime.datetime.strptime(fecha_corte, "%Y-%m-%d").date() if fecha_corte else datetime.date.today()
    valorar = request.GET.get('valorar_inventario', 'COSTO')

    def q(valor):
        """Cuantiza a 2 decimales con ROUND_HALF_UP."""
        return Decimal(str(valor)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # Obtener tasa de cambio para cuentas VES: usar última reexpresión o fallback
    tasa_ves = Decimal('1.00')
    try:
        from apps.bancos.models import PeriodoReexpresado
        ultimo_periodo = PeriodoReexpresado.objects.order_by('-anio', '-mes').first()
        if ultimo_periodo:
            tasa_ves = Decimal(str(ultimo_periodo.tasa_cierre))
    except Exception:
        pass

    # Activo Corriente: Efectivo
    efectivo = Decimal('0.00')
    for cta in CuentaBancaria.objects.filter(activa=True):
        if cta.moneda == 'USD':
            efectivo += Decimal(str(cta.saldo_actual))
        else:
            if tasa_ves > 0:
                efectivo += Decimal(str(cta.saldo_actual)) / tasa_ves
    efectivo = q(efectivo)

    # Activo Corriente: CxC
    cxc = Decimal('0.00')
    facturas_emitidas = FacturaVenta.objects.filter(estado='EMITIDA', fecha__lte=hasta)
    for f in facturas_emitidas:
        cobros = sum(c.monto for c in f.cobros.filter(fecha__lte=hasta))
        saldo = Decimal(str(f.total)) - Decimal(str(cobros))
        if saldo > 0 and (not f.fecha_vencimiento or f.fecha_vencimiento >= hasta):
            cxc += saldo
    cxc = q(cxc)

    # Activo Corriente: Inventario
    inventario = Decimal('0.00')
    for prod in Producto.objects.filter(activo=True, stock_actual__gt=0):
        if valorar == 'VENTA':
            precio = prod.precio_venta if prod.precio_venta else prod.costo_promedio
        else:
            precio = prod.costo_promedio
        inventario += Decimal(str(prod.stock_actual)) * Decimal(str(precio))
    inventario = q(inventario)

    activo_corriente = q(efectivo + cxc + inventario)

    # Pasivo Corriente: CxP Compras (APROBADAS con saldo pendiente)
    cxp_compras = Decimal('0.00')
    facturas_aprobadas = (
        FacturaCompra.objects
        .filter(estado='APROBADA', fecha__lte=hasta)
        .annotate(
            total_pagado=Coalesce(
                Sum('pagos__monto_usd'),
                Value(Decimal('0.00')),
                output_field=DecimalField(),
            )
        )
        .annotate(saldo=F('total') - F('total_pagado'))
        .filter(saldo__gt=0)
    )
    for f in facturas_aprobadas:
        cxp_compras += Decimal(str(f.saldo))
    cxp_compras = q(cxp_compras)

    # Pasivo Corriente: CxP Gastos
    cxp_gastos = Decimal('0.00')
    for g in GastoServicio.objects.filter(estado='PENDIENTE', fecha_emision__lte=hasta):
        cxp_gastos += Decimal(str(g.monto_usd))
    cxp_gastos = q(cxp_gastos)

    # Pasivo de socios: préstamos activos
    from datetime import timedelta
    from apps.socios.models import PrestamoPorSocio

    hoy = datetime.date.today()
    limite_corriente = hoy + timedelta(days=365)

    prestamos_activos = list(PrestamoPorSocio.objects.filter(estado='ACTIVO'))

    prestamos_corriente = q(sum(
        Decimal(str(p.monto_usd))
        for p in prestamos_activos
        if p.fecha_vencimiento and p.fecha_vencimiento <= limite_corriente
    ) or Decimal('0.00'))

    prestamos_no_corriente = q(sum(
        Decimal(str(p.monto_usd))
        for p in prestamos_activos
        if not p.fecha_vencimiento or p.fecha_vencimiento > limite_corriente
    ) or Decimal('0.00'))

    pasivo_corriente = q(cxp_compras + cxp_gastos + prestamos_corriente)
    capital_neto = q(activo_corriente - pasivo_corriente)
    capital_trabajo = capital_neto  # alias para compatibilidad con la plantilla

    context = {
        'empresa': empresa,
        'fecha_corte': hasta,
        'valorar': valorar,
        'efectivo': efectivo,
        'cxc': cxc,
        'inventario': inventario,
        'activo_corriente': activo_corriente,
        'cxp_compras': cxp_compras,
        'cxp_gastos': cxp_gastos,
        'prestamos_corriente': prestamos_corriente,
        'prestamos_no_corriente': prestamos_no_corriente,
        'prestamos_activos': prestamos_activos,
        'pasivo_corriente': pasivo_corriente,
        'capital_neto': capital_neto,
        'capital_trabajo': capital_trabajo,
    }
    return render(request, 'reportes/capital_trabajo.html', context)
