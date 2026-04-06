# -*- coding: utf-8 -*-
"""
test_sprint6_socio.py — Cobertura QA Sprint 6 para Socio (saldos calculados).

Cubre:
  - get_saldo_bruto(): suma monto_usd de préstamos ACTIVOS
  - get_saldo_neto(): bruto menos pagos realizados

REGLA: todas las aserciones numéricas usan Decimal exacto, NUNCA float.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.core.models import Secuencia
from apps.socios.models import Socio, PrestamoPorSocio, PagoPrestamo


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures locales
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def socio(db):
    return Socio.objects.create(nombre='Ana Martínez', rif='V-87654321')


@pytest.fixture(autouse=True)
def secuencia_soc(db):
    seq, _ = Secuencia.objects.get_or_create(
        tipo_documento='SOC',
        defaults={'ultimo_numero': 0, 'prefijo': 'SOC-', 'digitos': 4},
    )
    seq.ultimo_numero = 0
    seq.prefijo = 'SOC-'
    seq.digitos = 4
    seq.save()
    return seq


def _crear_prestamo(socio, monto, moneda='USD', tasa=Decimal('1.000000')):
    return PrestamoPorSocio.objects.create(
        socio=socio,
        monto_principal=Decimal(str(monto)),
        moneda=moneda,
        tasa_cambio=tasa,
        fecha_prestamo=date.today(),
        estado='ACTIVO',
    )


# ═══════════════════════════════════════════════════════════════════════════════
# test_socio_saldo_bruto_correcto
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_socio_saldo_bruto_correcto(socio):
    """
    Socio con 2 préstamos activos (1000 + 500 USD).
    get_saldo_bruto() debe retornar exactamente 1500.00.
    """
    _crear_prestamo(socio, '1000.00')
    _crear_prestamo(socio, '500.00')

    saldo = socio.get_saldo_bruto()
    assert saldo == Decimal('1500.00'), f"Saldo bruto esperado 1500.00, obtenido {saldo}"


@pytest.mark.django_db
def test_socio_saldo_bruto_sin_prestamos(socio):
    """Socio sin préstamos → saldo bruto debe ser 0.00."""
    assert socio.get_saldo_bruto() == Decimal('0.00')


@pytest.mark.django_db
def test_socio_saldo_bruto_ignora_cancelados(socio):
    """Préstamos CANCELADOS no deben sumarse al saldo bruto."""
    _crear_prestamo(socio, '800.00')
    prestamo_cancelado = _crear_prestamo(socio, '200.00')
    prestamo_cancelado.estado = 'CANCELADO'
    prestamo_cancelado.save(update_fields=['estado'])

    saldo = socio.get_saldo_bruto()
    assert saldo == Decimal('800.00'), f"Saldo bruto esperado 800.00, obtenido {saldo}"


# ═══════════════════════════════════════════════════════════════════════════════
# test_socio_saldo_neto_descuenta_pagos
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_socio_saldo_neto_descuenta_pagos(socio):
    """
    Préstamo 1000 USD. Pago de 300.
    get_saldo_neto() debe retornar exactamente 700.00.
    """
    prestamo = _crear_prestamo(socio, '1000.00')

    PagoPrestamo.objects.create(
        prestamo=prestamo,
        monto=Decimal('300.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        monto_usd=Decimal('300.00'),
        fecha=date.today(),
    )

    saldo_neto = socio.get_saldo_neto()
    assert saldo_neto == Decimal('700.00'), f"Saldo neto esperado 700.00, obtenido {saldo_neto}"


@pytest.mark.django_db
def test_socio_saldo_neto_sin_pagos(socio):
    """Sin pagos, el saldo neto debe ser igual al bruto."""
    _crear_prestamo(socio, '500.00')
    assert socio.get_saldo_neto() == Decimal('500.00')


@pytest.mark.django_db
def test_socio_saldo_neto_no_negativo(socio):
    """El saldo neto nunca debe ser negativo (pagos > principal)."""
    prestamo = _crear_prestamo(socio, '100.00')
    PagoPrestamo.objects.create(
        prestamo=prestamo,
        monto=Decimal('150.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        monto_usd=Decimal('150.00'),
        fecha=date.today(),
    )
    assert socio.get_saldo_neto() == Decimal('0.00')
