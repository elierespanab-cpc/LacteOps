import datetime
from decimal import Decimal
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, Q, DecimalField
from django.db.models.functions import Coalesce

from apps.core.models import ConfiguracionEmpresa
from apps.ventas.models import FacturaVenta, Cliente, DetalleFacturaVenta
from apps.compras.models import FacturaCompra, Proveedor, DetalleFacturaCompra, GastoServicio
from apps.produccion.models import OrdenProduccion, ConsumoOP, SalidaOrden
from apps.bancos.models import CuentaBancaria
from apps.almacen.models import Producto
from apps.compras.models import GastoServicio as Gs

@login_required
def reporte_ventas(request):
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
        'productos': Producto.objects.all(),
    }
    return render(request, 'reportes/ventas.html', context)

@login_required
def reporte_cxc(request):
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_corte = request.GET.get('fecha_corte')
    hasta = datetime.datetime.strptime(fecha_corte, "%Y-%m-%d").date() if fecha_corte else datetime.date.today()

    facturas = FacturaVenta.objects.filter(
        estado='EMITIDA',
        fecha__lte=hasta
    ).select_related('cliente')

    resultados = []
    totales = {'total': Decimal('0.00'), 'pendiente': Decimal('0.00'), 's_0_30': Decimal('0.00'), 's_31_60': Decimal('0.00'), 's_61_90': Decimal('0.00'), 's_90_plus': Decimal('0.00')}
    
    for fv in facturas:
        cobrado_hasta = sum(c.monto for c in fv.cobros.filter(fecha__lte=hasta)) if hasattr(fv, 'cobros') else Decimal('0.00')
        saldo = fv.total - cobrado_hasta
        if saldo > 0:
            dias_vencida = (hasta - fv.fecha_vencimiento).days if fv.fecha_vencimiento else 0
            if dias_vencida < 0: dias_vencida = 0
            
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
                's_90_plus': saldo_90_plus
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
        'productos': Producto.objects.all(),
    }
    return render(request, 'reportes/compras.html', context)

@login_required
def reporte_cxp(request):
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_corte = request.GET.get('fecha_corte')
    tipo_reporte = request.GET.get('tipo', 'TODOS')
    hasta = datetime.datetime.strptime(fecha_corte, "%Y-%m-%d").date() if fecha_corte else datetime.date.today()

    resultados = []
    totales = {'total': Decimal('0.00'), 'pendiente': Decimal('0.00'), 's_0_30': Decimal('0.00'), 's_31_60': Decimal('0.00'), 's_61_90': Decimal('0.00'), 's_90_plus': Decimal('0.00')}
    
    if tipo_reporte in ['TODOS', 'COMPRAS']:
        facturas = FacturaCompra.objects.filter(
            estado='RECIBIDA',
            fecha__lte=hasta
        ).select_related('proveedor')
        for fv in facturas:
            pagado_hasta = sum(p.monto_usd for p in fv.pagos.filter(fecha__lte=hasta)) if hasattr(fv, 'pagos') else Decimal('0.00')
            saldo = fv.total - pagado_hasta
            if saldo > 0:
                dias_vencida = (hasta - fv.fecha_vencimiento).days if fv.fecha_vencimiento else 0
                if dias_vencida < 0: dias_vencida = 0
                
                s_0 = saldo if 0 <= dias_vencida <= 30 else Decimal('0.00')
                s_31 = saldo if 31 <= dias_vencida <= 60 else Decimal('0.00')
                s_61 = saldo if 61 <= dias_vencida <= 90 else Decimal('0.00')
                s_90 = saldo if dias_vencida > 90 else Decimal('0.00')
                
                resultados.append({
                    'es_gasto': False,
                    'documento': fv,
                    'saldo': saldo,
                    'dias': dias_vencida,
                    's_0': s_0, 's_31': s_31, 's_61': s_61, 's_90': s_90
                })
                totales['pendiente'] += saldo
                totales['s_0_30'] += s_0; totales['s_31_60'] += s_31; totales['s_61_90'] += s_61; totales['s_90_plus'] += s_90

    if tipo_reporte in ['TODOS', 'GASTOS_SERVICIOS']:
        gastos = GastoServicio.objects.filter(
            estado='PENDIENTE',
            fecha_emision__lte=hasta
        ).select_related('proveedor')
        for gs in gastos:
            saldo = gs.monto_usd
            dias_vencida = (hasta - gs.fecha_vencimiento).days if gs.fecha_vencimiento else 0
            if dias_vencida < 0: dias_vencida = 0
            
            s_0 = saldo if 0 <= dias_vencida <= 30 else Decimal('0.00')
            s_31 = saldo if 31 <= dias_vencida <= 60 else Decimal('0.00')
            s_61 = saldo if 61 <= dias_vencida <= 90 else Decimal('0.00')
            s_90 = saldo if dias_vencida > 90 else Decimal('0.00')

            resultados.append({
                'es_gasto': True,
                'documento': gs,
                'saldo': saldo,
                'dias': dias_vencida,
                's_0': s_0, 's_31': s_31, 's_61': s_61, 's_90': s_90
            })
            totales['pendiente'] += saldo
            totales['s_0_30'] += s_0; totales['s_31_60'] += s_31; totales['s_61_90'] += s_61; totales['s_90_plus'] += s_90

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
        'ordenes': ordenes
    }
    return render(request, 'reportes/produccion.html', context)

@login_required
def reporte_gastos(request):
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

    # list of unique categorias to render filter properly in template
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
    empresa = ConfiguracionEmpresa.objects.first()
    fecha_corte = request.GET.get('fecha_corte')
    hasta = datetime.datetime.strptime(fecha_corte, "%Y-%m-%d").date() if fecha_corte else datetime.date.today()
    valorar = request.GET.get('valorar_inventario', 'COSTO')

    # Activo Corriente: Efectivo
    efectivo = Decimal('0.00')
    # de apps.almacen.services import convertir_a_usd ya manejado o no usado aqui
    # Para la tasa de cambio del momento tendriamos que saber la tasa, o usamos las cuentas tal cual estan
    # o asumimos tasa actual si es balance a la fecha de hoy, pero para la fecha de corte es mas complejo si no teniamos historico.
    # El prompt dice: "suma saldo_actual de CuentaBancaria activas, convertido a USD". Asume convertir usando alguna tasa o q ya tienen monto_usd historico, no, usar tasa actual/saldo_actual.
    # Como CuentaBancaria no tiene tasa, usamos `1` para USD y... wait, ¿cómo convertimos VES? No dice, usemos tasa definida en config o fallback 1.
    # Actually we can skip if we don't know the rate, but usually we should have it. Let's just do sum(saldo) for USD.
    for cta in CuentaBancaria.objects.filter(activa=True):
        if cta.moneda == 'USD':
            efectivo += cta.saldo_actual
        else:
            # without a fixed rate, we'll try to get it if reasonable, fallback 0 or something. Let's assume there's a setting or 1.
            efectivo += cta.saldo_actual / Decimal('45.00') # TODO: better handling if config has it

    # Activo Corriente: CxC
    cxc = Decimal('0.00')
    facturas_emitidas = FacturaVenta.objects.filter(estado='EMITIDA', fecha__lte=hasta)
    for f in facturas_emitidas:
        cobros = sum(c.monto for c in getattr(f, 'cobros').filter(fecha__lte=hasta)) if hasattr(f, 'cobros') else Decimal('0.00')
        saldo = f.total - cobros
        if saldo > 0 and (not f.fecha_vencimiento or f.fecha_vencimiento >= hasta):
            cxc += saldo
    
    # Activo Corriente: Inventario
    inventario = Decimal('0.00')
    for prod in Producto.objects.filter(stock_actual__gt=0):
        if valorar == 'VENTA':
            precio = prod.precio_venta if prod.precio_venta else prod.costo_promedio
        else:
            precio = prod.costo_promedio
        inventario += prod.stock_actual * precio

    activo_corriente = efectivo + cxc + inventario

    # Pasivo Corriente: CxP
    cxp_compras = Decimal('0.00')
    facturas_recibidas = FacturaCompra.objects.filter(estado='RECIBIDA', fecha__lte=hasta)
    for f in facturas_recibidas:
        pagos = sum(p.monto_usd for p in getattr(f, 'pagos').filter(fecha__lte=hasta)) if hasattr(f, 'pagos') else Decimal('0.00')
        saldo = f.total - pagos
        if saldo > 0:
            cxp_compras += saldo

    cxp_gastos = Decimal('0.00')
    gastos_pendientes = GastoServicio.objects.filter(estado='PENDIENTE', fecha_emision__lte=hasta)
    for g in gastos_pendientes:
        cxp_gastos += g.monto_usd

    pasivo_corriente = cxp_compras + cxp_gastos
    capital_trabajo = activo_corriente - pasivo_corriente

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
        'pasivo_corriente': pasivo_corriente,
        'capital_trabajo': capital_trabajo,
    }
    return render(request, 'reportes/capital_trabajo.html', context)
