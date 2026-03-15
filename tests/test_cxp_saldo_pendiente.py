# -*- coding: utf-8 -*-
"""
test_cxp_saldo_pendiente.py — get_saldo_pendiente() de FacturaCompra (Sprint 5).

Cubre:
  - Factura sin pagos → saldo_pendiente == total.
  - Factura con pago parcial → saldo_pendiente == total - monto_usd_pago.
  - Factura con pagos que cubren el total → saldo_pendiente == 0.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.compras.models import FacturaCompra, DetalleFacturaCompra, Pago
from apps.compras.models import Proveedor


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures locales
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def proveedor_cxp(db):
    return Proveedor.objects.create(nombre='Prov CXP Saldo', rif='J-33333333-3')


def _crear_factura_usd(proveedor, producto, cantidad='10', costo_unitario='10.00',
                        numero='COM-CXP-001'):
    """
    Crea FacturaCompra USD con total = cantidad * costo_unitario.
    Con cantidad=10 y costo_unitario=10.00 → total = 100.00 USD.
    """
    factura = FacturaCompra.objects.create(
        numero=numero,
        proveedor=proveedor,
        fecha=date.today(),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        estado='RECIBIDA',
    )
    DetalleFacturaCompra.objects.create(
        factura=factura,
        producto=producto,
        cantidad=Decimal(cantidad),
        costo_unitario=Decimal(costo_unitario),
    )
    factura.refresh_from_db()
    return factura


def _crear_pago_con_monto_usd(factura, monto_usd):
    """
    Crea un Pago en USD y fuerza monto_usd vía queryset.update()
    para simular que ya fue registrado (registrar() requiere cuenta bancaria).
    """
    pago = Pago.objects.create(
        factura=factura,
        fecha=date.today(),
        monto=monto_usd,
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        medio_pago='EFECTIVO_USD',
    )
    Pago.objects.filter(pk=pago.pk).update(monto_usd=monto_usd)
    return pago


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Sin pagos: saldo_pendiente == total
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cxp_factura_sin_pagos_saldo_igual_total(proveedor_cxp, producto_mp):
    """
    FacturaCompra USD (total=100.00) sin ningún Pago.
    get_saldo_pendiente() debe retornar exactamente 100.00.
    """
    factura = _crear_factura_usd(proveedor_cxp, producto_mp,
                                  cantidad='10', costo_unitario='10.00',
                                  numero='COM-CXP-001')

    assert factura.total == Decimal('100.00')
    assert factura.get_saldo_pendiente() == Decimal('100.00')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Pago parcial: saldo_pendiente == total - monto_usd_pago
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cxp_factura_con_pago_parcial(proveedor_cxp, producto_mp):
    """
    FacturaCompra USD total=100.00. Pago de 30.00 USD.
    get_saldo_pendiente() debe retornar 70.00.
    """
    factura = _crear_factura_usd(proveedor_cxp, producto_mp,
                                  cantidad='10', costo_unitario='10.00',
                                  numero='COM-CXP-002')
    _crear_pago_con_monto_usd(factura, Decimal('30.00'))

    assert factura.total == Decimal('100.00')
    assert factura.get_saldo_pendiente() == Decimal('70.00')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Pagos cubren el total: saldo_pendiente == 0
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cxp_factura_pagada_saldo_cero(proveedor_cxp, producto_mp):
    """
    FacturaCompra USD total=100.00. Pagos que suman >= 100.00 (60 + 40 = 100).
    get_saldo_pendiente() debe retornar 0.
    """
    factura = _crear_factura_usd(proveedor_cxp, producto_mp,
                                  cantidad='10', costo_unitario='10.00',
                                  numero='COM-CXP-003')
    _crear_pago_con_monto_usd(factura, Decimal('60.00'))
    _crear_pago_con_monto_usd(factura, Decimal('40.00'))

    assert factura.total == Decimal('100.00')
    assert factura.get_saldo_pendiente() == Decimal('0')
