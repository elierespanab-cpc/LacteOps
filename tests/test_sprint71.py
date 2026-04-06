# -*- coding: utf-8 -*-
"""
Tests Sprint 7.1 — Correcciones Profundas Post-Sprint 7
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import Client as TestClient

from apps.ventas.models import FacturaVenta, Cliente, Cobro
from apps.compras.models import Proveedor, GastoServicio
from apps.core.models import CategoriaGasto


def _capturar_ctx(url, username='_admin71', password='_pass71'):
    """Helper: llama a una URL y captura el contexto que la vista pasa a render."""
    try:
        User.objects.get(username=username)
    except User.DoesNotExist:
        User.objects.create_superuser(username, f'{username}@x.com', password)

    client = TestClient()
    client.login(username=username, password=password)

    ctx_capturado = {}

    def fake_render(req, template, context, **kwargs):
        ctx_capturado.update(context)
        return HttpResponse('OK')

    with patch('apps.reportes.views.render', side_effect=fake_render):
        client.get(url)

    return ctx_capturado


# ─────────────────────────────────────────────────────────────────────────────
# B7.1-CxC: Corrección inconsistencia — cobros con monto_usd=0 no se omiten
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_factura_venta_get_saldo_pendiente_sin_cobros():
    """get_saldo_pendiente() retorna total cuando no hay cobros."""
    cliente = Cliente.objects.create(nombre='Saldo Test 71', rif='J-71000002-0')
    factura = FacturaVenta.objects.create(
        numero='VTA-71-SALDO-001',
        cliente=cliente,
        fecha=date.today(),
        moneda='USD',
        tasa_cambio=Decimal('1.0'),
        estado='EMITIDA',
        total=Decimal('200.00'),
    )
    assert factura.get_saldo_pendiente() == Decimal('200.00')


# ─────────────────────────────────────────────────────────────────────────────
# B7.1-Gastos: GastoServicio monto_usd calculado correctamente
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_gasto_servicio_usd_no_es_cero():
    """GastoServicio guardado debe tener monto_usd > 0 si monto > 0."""
    proveedor = Proveedor.objects.create(nombre='Prov 71', rif='J-71100001-0')
    cat = CategoriaGasto.objects.create(nombre='Servicios 71', contexto='GASTO')
    subcat = CategoriaGasto.objects.create(nombre='Agua 71', padre=cat, contexto='GASTO')

    gasto = GastoServicio.objects.create(
        proveedor=proveedor,
        fecha_emision=date.today(),
        fecha_vencimiento=date.today() + timedelta(days=30),
        descripcion='Gasto test Sprint 7.1',
        monto=Decimal('500.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        categoria_gasto=subcat,
    )
    assert gasto.monto_usd > Decimal('0.00'), f"monto_usd={gasto.monto_usd} debe ser > 0"
    assert gasto.monto_usd == Decimal('500.00')


@pytest.mark.django_db
def test_gasto_servicio_ves_convierte_a_usd():
    """GastoServicio VES convierte monto a USD usando tasa_cambio."""
    proveedor = Proveedor.objects.create(nombre='Prov VES 71', rif='J-71100002-0')
    cat = CategoriaGasto.objects.create(nombre='Electricidad 71', contexto='GASTO')
    subcat = CategoriaGasto.objects.create(nombre='CORPOELEC 71', padre=cat, contexto='GASTO')

    tasa = Decimal('100.000000')
    gasto = GastoServicio.objects.create(
        proveedor=proveedor,
        fecha_emision=date.today(),
        fecha_vencimiento=date.today() + timedelta(days=30),
        descripcion='Electricidad VES',
        monto=Decimal('50000.00'),
        moneda='VES',
        tasa_cambio=tasa,
        categoria_gasto=subcat,
    )
    esperado = (Decimal('50000.00') / tasa).quantize(Decimal('0.01'))
    assert gasto.monto_usd == esperado, f"Esperado {esperado}, obtenido {gasto.monto_usd}"


# ─────────────────────────────────────────────────────────────────────────────
# B7.1-Ventas/Compras: contexto correcto con 'filas' + filtros
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_reporte_ventas_context_tiene_filas():
    """reporte_ventas debe enviar 'filas' y 'estados' al contexto."""
    ctx = _capturar_ctx('/reportes/ventas/', '_adm71v', '_p71v')
    assert 'filas' in ctx, "El contexto debe tener 'filas'"
    assert 'estados' in ctx, "El contexto debe tener 'estados'"


@pytest.mark.django_db
def test_reporte_compras_context_tiene_filas():
    """reporte_compras debe enviar 'filas' y 'estados' al contexto."""
    ctx = _capturar_ctx('/reportes/compras/', '_adm71c', '_p71c')
    assert 'filas' in ctx
    assert 'estados' in ctx


@pytest.mark.django_db
def test_reporte_ventas_filtro_estatus_cobro():
    """reporte_ventas con ?estatus_cobro=Pendiente pasa estatus_cobro_filtro al contexto."""
    ctx = _capturar_ctx(
        '/reportes/ventas/?estatus_cobro=Pendiente', '_adm71ef', '_p71ef'
    )
    assert ctx.get('estatus_cobro_filtro') == 'Pendiente'


@pytest.mark.django_db
def test_reporte_compras_filtro_estatus_pago():
    """reporte_compras con ?estatus_pago=Pendiente pasa estatus_pago_filtro al contexto."""
    ctx = _capturar_ctx(
        '/reportes/compras/?estatus_pago=Pendiente', '_adm71ep', '_p71ep'
    )
    assert ctx.get('estatus_pago_filtro') == 'Pendiente'


# ─────────────────────────────────────────────────────────────────────────────
# B7.1-Capital de Trabajo: Préstamos socios en contexto
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_capital_trabajo_incluye_prestamos_corriente():
    """reporte_capital_trabajo incluye prestamos_corriente, prestamos_no_corriente y cuentas_efectivo."""
    ctx = _capturar_ctx('/reportes/capital_trabajo/', '_adm71ct', '_p71ct')
    assert 'prestamos_corriente' in ctx
    assert 'prestamos_no_corriente' in ctx
    assert 'cuentas_efectivo' in ctx


# ─────────────────────────────────────────────────────────────────────────────
# B7.1-Producción: modo consolidado en contexto
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_reporte_produccion_acepta_modo_consolidado():
    """reporte_produccion con ?modo=consolidado retorna modo='consolidado' en contexto."""
    ctx = _capturar_ctx(
        '/reportes/produccion/?modo=consolidado&mostrar=solo_consumos', '_adm71p', '_p71p'
    )
    assert ctx.get('modo') == 'consolidado'
    assert ctx.get('mostrar') == 'solo_consumos'


@pytest.mark.django_db
def test_reporte_produccion_modo_detallado_default():
    """reporte_produccion sin parámetros usa modo='detallado' y mostrar='ambos' por defecto."""
    ctx = _capturar_ctx('/reportes/produccion/', '_adm71pd', '_p71pd')
    assert ctx.get('modo') == 'detallado'
    assert ctx.get('mostrar') == 'ambos'
