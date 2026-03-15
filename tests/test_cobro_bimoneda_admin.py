# -*- coding: utf-8 -*-
"""
test_cobro_bimoneda_admin.py — Bimoneda en Cobro de Factura de Venta (Sprint 5 B5/B6).

Cubre:
  - VES con tasa explícita → monto_usd = monto / tasa (Decimal exacto).
  - USD → monto_usd == monto.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.bancos.models import CuentaBancaria
from apps.ventas.models import FacturaVenta, Cobro, ListaPrecio, DetalleLista


# ─────────────────────────────────────────────────────────────────────────────
# Helpers y fixtures locales
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cuenta_ves_cobro(db):
    """Cuenta VES destino para cobros (ENTRADA no requiere saldo previo)."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta VES Cobro Test',
        moneda='VES',
        saldo_actual=Decimal('0.00'),
    )


@pytest.fixture
def cuenta_usd_cobro(db):
    """Cuenta USD destino para cobros."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta USD Cobro Test',
        moneda='USD',
        saldo_actual=Decimal('0.00'),
    )


def _crear_factura_venta_minima(cliente, numero='VTA-COB-001'):
    """
    Crea FacturaVenta mínima en estado EMITIDA.
    No llama a emitir() — solo necesitamos el FK para el Cobro.
    """
    return FacturaVenta.objects.create(
        numero=numero,
        cliente=cliente,
        fecha=date.today(),
        estado='EMITIDA',
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — VES: monto_usd = monto / tasa con exactitud Decimal
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cobro_ves_monto_usd_calculado(cliente, cuenta_ves_cobro):
    """
    Cobro en VES: monto=500.00, tasa=50.
    monto_usd debe ser exactamente 500.00 / 50 = 10.00.
    """
    factura = _crear_factura_venta_minima(cliente, numero='VTA-COB-001')

    cobro = Cobro.objects.create(
        factura=factura,
        fecha=date.today(),
        monto=Decimal('500.00'),
        moneda='VES',
        tasa_cambio=Decimal('50.000000'),
        cuenta_destino=cuenta_ves_cobro,
        medio_pago='EFECTIVO_VES',
    )
    cobro.registrar()
    cobro.refresh_from_db()

    esperado = (Decimal('500.00') / Decimal('50')).quantize(Decimal('0.01'))
    assert cobro.monto_usd == Decimal('10.00')
    assert cobro.monto_usd == esperado


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — USD: monto_usd == monto
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cobro_usd_monto_usd_igual_monto(cliente, cuenta_usd_cobro):
    """
    Cobro en USD: monto=100.00 → monto_usd debe ser exactamente 100.00.
    """
    factura = _crear_factura_venta_minima(cliente, numero='VTA-COB-002')

    cobro = Cobro.objects.create(
        factura=factura,
        fecha=date.today(),
        monto=Decimal('100.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        cuenta_destino=cuenta_usd_cobro,
        medio_pago='EFECTIVO_USD',
    )
    cobro.registrar()
    cobro.refresh_from_db()

    assert cobro.monto_usd == Decimal('100.00')
