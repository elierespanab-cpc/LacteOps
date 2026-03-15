# -*- coding: utf-8 -*-
"""
test_score_riesgo.py — Suite para calcular_score_riesgo y helpers (Sprint 4).
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User

from apps.almacen.models import UnidadMedida, Categoria, Producto
from apps.ventas.models import Cliente, FacturaVenta, Cobro
from apps.core.models import Secuencia
from apps.reportes.analytics import (
    calcular_add_mes,
    calcular_slope_add,
    calcular_score_riesgo,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def unidad_score(db):
    unidad, _ = UnidadMedida.objects.get_or_create(simbolo='un', defaults={'nombre': 'Unidad'})
    return unidad


@pytest.fixture
def categoria_score(db):
    cat, _ = Categoria.objects.get_or_create(nombre='Score')
    return cat


@pytest.fixture
def cliente_score(db):
    return Cliente.objects.create(
        nombre='Cliente Score Test',
        rif='J-10000001-1',
        limite_credito=Decimal('1000.00'),
        dias_credito=30,
    )


@pytest.fixture
def secuencia_vta_score(db):
    seq, _ = Secuencia.objects.get_or_create(
        tipo_documento='VTA',
        defaults={'prefijo': 'VTA-', 'digitos': 4, 'ultimo_numero': 0},
    )
    return seq


@pytest.fixture
def factura_sin_saldo(db, cliente_score, secuencia_vta_score):
    """Factura totalmente cobrada → no agrega saldo pendiente."""
    hoy = date.today()
    f = FacturaVenta.objects.create(
        numero='VTA-SC-001',
        cliente=cliente_score,
        fecha=hoy - timedelta(days=5),
        fecha_vencimiento=hoy + timedelta(days=25),
        estado='COBRADA',
        total=Decimal('100.00'),
    )
    return f


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_score_cliente_sin_deuda(cliente_score):
    """
    Cliente sin facturas pendientes ni cobros retrasados:
    ADD=0, saldo=0, ratio=0, slope=0 (neutral sin historial).
    Puntualidad=100, Solvencia=100, Tendencia=50 (neutral).
    score = 0.4*100 + 0.3*100 + 0.3*50 = 85.0 (máximo práctico sin tendencia positiva).
    """
    resultado = calcular_score_riesgo(cliente_score)
    assert resultado['score'] == Decimal('85.0'), (
        f"Score esperado 85.0 (neutral sin historial), obtenido {resultado['score']}"
    )
    assert resultado['puntualidad'] == Decimal('100.0')
    assert resultado['solvencia'] == Decimal('100.0')


@pytest.mark.django_db
def test_score_cliente_deuda_60d(db, cliente_score):
    """
    Cliente con factura vencida > 60 días:
    deuda_60d > 0 → solvencia < 50.
    """
    hoy = date.today()
    vencida_hace70 = hoy - timedelta(days=70)
    FacturaVenta.objects.create(
        numero='VTA-SC-010',
        cliente=cliente_score,
        fecha=hoy - timedelta(days=100),
        fecha_vencimiento=vencida_hace70,
        estado='EMITIDA',
        total=Decimal('500.00'),
    )
    resultado = calcular_score_riesgo(cliente_score)
    assert resultado['solvencia'] < Decimal('50'), (
        f"Solvencia esperada < 50 con deuda_60d, obtenida {resultado['solvencia']}"
    )


@pytest.mark.django_db
def test_slope_positivo_penaliza(cliente_score):
    """
    slope > 0 (ADD creciente = deterioro) → Tendencia < 50.
    """
    with patch('apps.reportes.analytics.calcular_slope_add', return_value=3.0):
        resultado = calcular_score_riesgo(cliente_score)
    assert resultado['tendencia'] < Decimal('50'), (
        f"Tendencia esperada < 50 con slope positivo, obtenida {resultado['tendencia']}"
    )


@pytest.mark.django_db
def test_slope_negativo_bonifica(cliente_score):
    """
    slope < 0 (ADD decreciente = mejora) → Tendencia > 50.
    """
    with patch('apps.reportes.analytics.calcular_slope_add', return_value=-3.0):
        resultado = calcular_score_riesgo(cliente_score)
    assert resultado['tendencia'] > Decimal('50'), (
        f"Tendencia esperada > 50 con slope negativo, obtenida {resultado['tendencia']}"
    )


@pytest.mark.django_db
def test_add_mayor_15_puntualidad_cero(cliente_score):
    """
    ADD = 20 días → puntualidad = max(0, 100 - 20*100/15) = max(0, -33) = 0.
    """
    hoy = date.today()
    with patch('apps.reportes.analytics.calcular_add_mes', return_value=Decimal('20')):
        resultado = calcular_score_riesgo(cliente_score)
    assert resultado['puntualidad'] == Decimal('0'), (
        f"Puntualidad esperada 0 con ADD=20, obtenida {resultado['puntualidad']}"
    )


@pytest.mark.django_db
def test_formula_ponderada_correcta(cliente_score):
    """
    score = 0.40*Puntualidad + 0.30*Solvencia + 0.30*Tendencia (Decimal exacto).
    """
    resultado = calcular_score_riesgo(cliente_score)
    P = resultado['puntualidad']
    S = resultado['solvencia']
    T = resultado['tendencia']
    expected = (Decimal('0.40') * P + Decimal('0.30') * S + Decimal('0.30') * T).quantize(Decimal('0.1'))
    assert resultado['score'] == expected, (
        f"Score calculado {resultado['score']} ≠ fórmula {expected}"
    )
