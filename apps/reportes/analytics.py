# -*- coding: utf-8 -*-
from decimal import Decimal
from datetime import date, timedelta
import logging

logger = logging.getLogger(__name__)


# ── Score de Riesgo ───────────────────────────────────────────────────

def calcular_add_mes(cliente, anio, mes):
    from apps.ventas.models import Cobro
    cobros = Cobro.objects.filter(
        factura__cliente=cliente, fecha__year=anio, fecha__month=mes
    ).select_related('factura')
    if not cobros.exists():
        return Decimal('0')
    retrasos = [max(0, (c.fecha - c.factura.fecha_vencimiento).days)
                for c in cobros if c.factura.fecha_vencimiento]
    if not retrasos:
        return Decimal('0')
    return Decimal(str(sum(retrasos) / len(retrasos)))


def calcular_slope_add(cliente):
    """Regresión lineal simple x=[0,1,2] y=[ADD_m0,ADD_m1,ADD_m2].
    Retorna pendiente. Positivo=deterioro, Negativo=mejora.
    Usa Decimal en todos los cálculos para mantener precisión financiera.
    """
    hoy = date.today()
    adds = []
    for offset in range(3):
        ref = (hoy.replace(day=1) - timedelta(days=offset * 30))
        adds.append(calcular_add_mes(cliente, ref.year, ref.month))
    x_mean = Decimal('1')
    y_mean = sum(adds) / Decimal('3')
    num = sum((Decimal(str(i)) - x_mean) * (adds[i] - y_mean) for i in range(3))
    den = sum((Decimal(str(i)) - x_mean) ** 2 for i in range(3))
    return num / den if den != Decimal('0') else Decimal('0')


def calcular_score_riesgo(cliente):
    from apps.ventas.models import FacturaVenta
    hoy = date.today()
    # Puntualidad
    add = calcular_add_mes(cliente, hoy.year, hoy.month)
    punt = max(Decimal('0'), min(Decimal('100'), 100 - (add * 100 / 15)))
    # Solvencia
    facturas = FacturaVenta.objects.filter(cliente=cliente, estado='EMITIDA')
    saldo = sum(f.get_saldo_pendiente() for f in facturas) or Decimal('0')
    d60 = sum(f.get_saldo_pendiente() for f in facturas
              if f.fecha_vencimiento and (hoy - f.fecha_vencimiento).days > 60) or Decimal('0')
    lim = cliente.limite_credito or Decimal('0')
    ru = min(Decimal('1'), saldo / lim if lim > 0 else Decimal('1'))
    pm = d60 / saldo if saldo > 0 else Decimal('0')
    solv = max(Decimal('0'), min(Decimal('100'), 100 * (1 - ru) * (1 - pm)))
    # Tendencia — normalizar slope a Decimal por si viene de mock o float externo
    slope = Decimal(str(calcular_slope_add(cliente)))
    tend_raw = max(Decimal('-1'), min(Decimal('1'), -slope / Decimal('5')))
    tend = max(Decimal('0'), min(Decimal('100'), tend_raw * Decimal('100') + Decimal('50')))
    score = (Decimal('0.40') * punt + Decimal('0.30') * solv + Decimal('0.30') * tend).quantize(Decimal('0.1'))
    return {
        'score': score,
        'puntualidad': punt.quantize(Decimal('0.1')),
        'solvencia': solv.quantize(Decimal('0.1')),
        'tendencia': tend.quantize(Decimal('0.1')),
        'add_actual': add.quantize(Decimal('0.1')),
        'saldo_total': saldo,
        'deuda_60d': d60,
        'ratio_utilizacion': ru.quantize(Decimal('0.001')),
    }


# ── Precio Ponderado Leche ────────────────────────────────────────────

def calcular_precio_ponderado_leche():
    from apps.almacen.models import MovimientoInventario, Producto
    hoy = date.today()
    entradas = MovimientoInventario.objects.filter(
        tipo='ENTRADA', fecha__date__gte=hoy - timedelta(days=7),
        producto__es_materia_prima_base=True)
    total_q = sum(e.cantidad for e in entradas)
    if not total_q:
        prods = Producto.objects.filter(es_materia_prima_base=True, activo=True)
        if not prods.exists():
            return {'precio': None, 'sin_datos': True}
        tq = sum(p.stock_actual for p in prods) or Decimal('1')
        pp = sum(p.costo_promedio * p.stock_actual for p in prods) / tq
        return {'precio': pp.quantize(Decimal('0.000001')), 'sin_datos': True}
    total_v = sum(e.cantidad * e.costo_unitario for e in entradas)
    return {'precio': (total_v / total_q).quantize(Decimal('0.000001')), 'sin_datos': False}


# ── CCE ──────────────────────────────────────────────────────────────

def calcular_cce():
    from apps.ventas.models import Cobro, FacturaVenta
    from apps.compras.models import Pago
    from apps.almacen.models import Producto
    hoy = date.today()
    hace90 = hoy - timedelta(days=90)
    # DSO
    cobros = Cobro.objects.filter(fecha__gte=hace90).select_related('factura')
    dso_v = [(c.fecha - c.factura.fecha).days for c in cobros if c.factura and c.factura.fecha]
    dso = Decimal(str(sum(dso_v) / len(dso_v))).quantize(Decimal('0.1')) if dso_v else Decimal('0')
    # DIO
    inv = sum(p.stock_actual * p.costo_promedio for p in
              Producto.objects.filter(activo=True, es_producto_terminado=True)) or Decimal('0')
    cv = sum(d.cantidad * d.precio_unitario
             for f in FacturaVenta.objects.filter(fecha__gte=hace90, estado__in=['EMITIDA', 'COBRADA'])
             for d in f.detalles.all()) or Decimal('1')
    dio = (inv / cv * 90).quantize(Decimal('0.1'))
    # DPO
    pagos = Pago.objects.filter(fecha__gte=hace90).select_related('factura')
    dpo_v = [(p.fecha - p.factura.fecha).days for p in pagos if p.factura and p.factura.fecha]
    dpo = Decimal(str(sum(dpo_v) / len(dpo_v))).quantize(Decimal('0.1')) if dpo_v else Decimal('0')
    return {
        'cce': (dso + dio - dpo).quantize(Decimal('0.1')),
        'dso': dso,
        'dio': dio,
        'dpo': dpo,
    }


# ── Proyección Caja 7d ────────────────────────────────────────────────

def calcular_proyeccion_caja_7d():
    from apps.bancos.models import CuentaBancaria
    from apps.ventas.models import FacturaVenta
    from apps.compras.models import FacturaCompra
    from apps.socios.models import PrestamoPorSocio
    from apps.core.models import TasaCambio
    hoy = date.today()
    limite = hoy + timedelta(days=7)
    ultima_tasa = TasaCambio.objects.order_by('-fecha').first()
    tasa_ref = ultima_tasa.tasa if ultima_tasa else Decimal('1')
    saldo_usd = Decimal('0')
    for c in CuentaBancaria.objects.filter(activa=True):
        saldo_usd += c.saldo_actual if c.moneda == 'USD' else c.saldo_actual / tasa_ref
    cobros = sum(f.get_saldo_pendiente() for f in FacturaVenta.objects.filter(
        estado='EMITIDA', fecha_vencimiento__range=[hoy, limite])) or Decimal('0')
    pagos = sum(f.get_saldo_pendiente() for f in FacturaCompra.objects.filter(
        estado='APROBADA', fecha__range=[hoy, limite])) or Decimal('0')
    prestamos = sum(p.monto_usd for p in PrestamoPorSocio.objects.filter(
        estado='ACTIVO', fecha_vencimiento__range=[hoy, limite])) or Decimal('0')
    proy = saldo_usd + cobros - pagos - prestamos
    return {
        'saldo_usd': saldo_usd.quantize(Decimal('0.01')),
        'cobros_esperados': cobros.quantize(Decimal('0.01')),
        'pagos_a_vencer': pagos.quantize(Decimal('0.01')),
        'prestamos_venciendo': prestamos.quantize(Decimal('0.01')),
        'proyeccion_neta': proy.quantize(Decimal('0.01')),
    }
