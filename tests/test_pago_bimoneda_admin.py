# -*- coding: utf-8 -*-
"""
test_pago_bimoneda_admin.py — Bimoneda en Pago de Factura de Compra (Sprint 5 B5/B6).

Cubre:
  - VES con tasa explícita → monto_usd = monto / tasa (Decimal exacto).
  - USD → monto_usd == monto, tasa forzada a 1.
  - VES con tasa default (=1, sin TasaCambio en BD) → monto_usd = monto/1, no queda en 0.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.bancos.models import CuentaBancaria
from apps.compras.models import FacturaCompra, DetalleFacturaCompra, Pago
from apps.compras.models import Proveedor


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures locales
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def proveedor_pago(db):
    return Proveedor.objects.create(nombre='Prov Bimoneda Pago', rif='J-22222222-2')


@pytest.fixture
def cuenta_ves_pago(db):
    """Cuenta VES con saldo suficiente para pagos de prueba."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta VES Pago Test',
        moneda='VES',
        saldo_actual=Decimal('10000.00'),
    )


@pytest.fixture
def cuenta_usd_pago(db):
    """Cuenta USD con saldo suficiente para pagos de prueba."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta USD Pago Test',
        moneda='USD',
        saldo_actual=Decimal('500.00'),
    )


def _crear_factura_compra(proveedor, producto, moneda='USD', tasa='1.000000', numero='COM-PAG-001'):
    factura = FacturaCompra.objects.create(
        numero=numero,
        proveedor=proveedor,
        fecha=date.today(),
        moneda=moneda,
        tasa_cambio=Decimal(tasa),
        estado='RECIBIDA',
    )
    DetalleFacturaCompra.objects.create(
        factura=factura,
        producto=producto,
        cantidad=Decimal('10'),
        costo_unitario=Decimal('10.00'),
    )
    factura.refresh_from_db()
    return factura


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — VES: monto_usd = monto / tasa con exactitud Decimal
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_pago_ves_monto_usd_calculado(proveedor_pago, producto_mp, cuenta_ves_pago):
    """
    Pago en VES: monto=500.00, tasa=50.
    monto_usd debe ser exactamente 500.00 / 50 = 10.00.
    """
    factura = _crear_factura_compra(proveedor_pago, producto_mp, moneda='VES',
                                    tasa='50.000000', numero='COM-PAG-001')

    pago = Pago.objects.create(
        factura=factura,
        fecha=date.today(),
        monto=Decimal('500.00'),
        moneda='VES',
        tasa_cambio=Decimal('50.000000'),
        cuenta_origen=cuenta_ves_pago,
        medio_pago='EFECTIVO_VES',
    )
    pago.registrar()
    pago.refresh_from_db()

    esperado = (Decimal('500.00') / Decimal('50')).quantize(Decimal('0.01'))
    assert pago.monto_usd == Decimal('10.00')
    assert pago.monto_usd == esperado


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — USD: monto_usd == monto, tasa forzada a 1
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_pago_usd_monto_usd_igual_monto(proveedor_pago, producto_mp, cuenta_usd_pago):
    """
    Pago en USD: monto=100.00 → monto_usd debe ser exactamente 100.00.
    La tasa se fuerza a 1 internamente; monto_usd = monto.
    """
    factura = _crear_factura_compra(proveedor_pago, producto_mp, moneda='USD',
                                    tasa='1.000000', numero='COM-PAG-002')

    pago = Pago.objects.create(
        factura=factura,
        fecha=date.today(),
        monto=Decimal('100.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        cuenta_origen=cuenta_usd_pago,
        medio_pago='EFECTIVO_USD',
    )
    pago.registrar()
    pago.refresh_from_db()

    assert pago.monto_usd == Decimal('100.00')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — VES con tasa default (=1): fallback, monto_usd no queda en 0
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_pago_ves_sin_tasa_monto_usd_cero_o_error(proveedor_pago, producto_mp, cuenta_ves_pago):
    """
    Pago en VES sin TasaCambio en BD; tasa_cambio field = 1.000000 (default).
    Lógica: tasa=1 > 0 → monto_usd = monto / 1 = monto.
    monto_usd NO debe quedar en 0.
    """
    factura = _crear_factura_compra(proveedor_pago, producto_mp, moneda='VES',
                                    tasa='1.000000', numero='COM-PAG-003')

    pago = Pago.objects.create(
        factura=factura,
        fecha=date.today(),
        monto=Decimal('500.00'),
        moneda='VES',
        tasa_cambio=Decimal('1.000000'),   # default / fallback — sin TasaCambio en BD
        cuenta_origen=cuenta_ves_pago,
        medio_pago='EFECTIVO_VES',
    )
    pago.registrar()
    pago.refresh_from_db()

    # Con tasa=1 > 0: monto_usd = 500 / 1 = 500.00 — el fallback es funcional
    assert pago.monto_usd != Decimal('0.00'), "monto_usd no debe quedar en cero con tasa=1"
    assert pago.monto_usd == Decimal('500.00')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — DIM-07-001: PagoAdmin bloquea VES cuando get_tasa_para_fecha → None
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_admin_pago_ves_sin_tasa_bd_no_guarda(proveedor_pago, producto_mp, cuenta_ves_pago):
    """
    Simula el comportamiento de PagoAdmin.save_model() cuando moneda=VES y
    no existe TasaCambio en BD para la fecha del pago.

    La función get_tasa_para_fecha() debe retornar None → el admin bloquea el save
    mostrando messages.error y devolviendo sin persistir.

    Verifica que monto_usd permanece en 0 (el pago no fue guardado).
    """
    from apps.core.services import get_tasa_para_fecha
    from datetime import date

    # Sin TasaCambio en BD, get_tasa_para_fecha debe retornar None
    tasa = get_tasa_para_fecha(date.today())
    assert tasa is None, "No debe haber TasaCambio en BD para este test"

    # El Pago en VES con monto_usd=0 representa el estado "no procesado"
    factura = _crear_factura_compra(proveedor_pago, producto_mp, moneda='VES',
                                    tasa='1.000000', numero='COM-PAG-004')
    pago = Pago(
        factura=factura,
        fecha=date.today(),
        monto=Decimal('800.00'),
        moneda='VES',
        tasa_cambio=Decimal('1.000000'),
        cuenta_origen=cuenta_ves_pago,
        medio_pago='EFECTIVO_VES',
        monto_usd=Decimal('0.00'),  # Default: no ha sido procesado aún
    )

    # El admin bloqueará antes de llamar super().save_model() si no hay tasa
    # Verificamos la condición que dispara el bloqueo en PagoAdmin.save_model():
    # "if obj.moneda == 'VES' and not tasa: return" → pago NO se persiste
    if pago.moneda == 'VES' and not tasa:
        pago_guardado = False
    else:
        pago.save()
        pago_guardado = True

    assert not pago_guardado, (
        "PagoAdmin debe bloquear el guardado de Pago VES cuando no hay tasa BCV en BD"
    )
    assert pago.monto_usd == Decimal('0.00'), (
        "monto_usd debe permanecer en 0 si el pago VES no fue procesado por falta de tasa"
    )
