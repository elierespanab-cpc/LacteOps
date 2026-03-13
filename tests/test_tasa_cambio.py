# -*- coding: utf-8 -*-
"""
test_tasa_cambio.py — Suite para el modelo TasaCambio (Sprint 3).

Cubre:
  - Creación y recuperación por fecha exacta.
  - Consulta de la tasa más reciente cuando no hay fecha exacta.
  - ignore_conflicts=True en bulk_create no sobreescribe registros existentes.

REGLA: todas las aserciones numéricas usan Decimal exacto, NUNCA float.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from apps.core.models import TasaCambio


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Creación y recuperación del día de hoy
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_tasa_hoy():
    """Crea una tasa para hoy y la recupera por fecha exacta."""
    hoy = date.today()
    TasaCambio.objects.create(
        fecha=hoy,
        tasa=Decimal('50.123456'),
        fuente='BCV_AUTO',
    )
    tasa = TasaCambio.objects.get(fecha=hoy)
    assert tasa.tasa == Decimal('50.123456')
    assert tasa.fuente == 'BCV_AUTO'


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Recuperación por fecha anterior exacta
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_tasa_fecha_anterior():
    """Recupera correctamente una tasa registrada en una fecha del pasado."""
    ayer = date.today() - timedelta(days=1)
    TasaCambio.objects.create(
        fecha=ayer,
        tasa=Decimal('48.500000'),
        fuente='BCV_MANUAL',
    )
    tasa = TasaCambio.objects.get(fecha=ayer)
    assert tasa.tasa == Decimal('48.500000')
    assert tasa.fuente == 'BCV_MANUAL'


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — Sin tasa exacta: retorna la más reciente anterior a la fecha
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_sin_tasa_exacta_retorna_mas_reciente():
    """
    Si no hay tasa para la fecha exacta, filter(fecha__lte=...).order_by('-fecha').first()
    debe retornar la entrada más cercana anterior a esa fecha.
    """
    hoy = date.today()
    d1 = hoy - timedelta(days=5)  # más antigua
    d2 = hoy - timedelta(days=3)  # más reciente

    TasaCambio.objects.create(fecha=d1, tasa=Decimal('45.000000'), fuente='BCV_AUTO')
    TasaCambio.objects.create(fecha=d2, tasa=Decimal('47.000000'), fuente='BCV_AUTO')

    # Consultar para ayer (no existe registro exacto; d2 es la más reciente <= ayer)
    consulta = hoy - timedelta(days=1)
    tasa = TasaCambio.objects.filter(fecha__lte=consulta).order_by('-fecha').first()

    assert tasa is not None
    assert tasa.tasa == Decimal('47.000000'), (
        f"Esperado 47.000000, obtenido {tasa.tasa}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — bulk_create con ignore_conflicts=True no sobreescribe existentes
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_bulk_create_no_sobreescribe():
    """
    Un bulk_create con ignore_conflicts=True sobre una fecha ya registrada
    debe dejar intacto el registro original (no actualiza ni lanza error).
    """
    hoy = date.today()
    TasaCambio.objects.create(
        fecha=hoy,
        tasa=Decimal('50.000000'),
        fuente='BCV_MANUAL',
    )

    # Intento de bulk_create con la misma fecha — debe ser silenciado
    TasaCambio.objects.bulk_create(
        [TasaCambio(fecha=hoy, tasa=Decimal('99.000000'), fuente='BCV_AUTO')],
        ignore_conflicts=True,
    )

    # La tasa original no debe haber cambiado
    tasa = TasaCambio.objects.get(fecha=hoy)
    assert tasa.tasa == Decimal('50.000000'), (
        f"El registro original fue sobreescrito: tasa={tasa.tasa}"
    )
    assert tasa.fuente == 'BCV_MANUAL'
