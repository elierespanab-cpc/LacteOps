# -*- coding: utf-8 -*-
"""
test_compras.py — Suite de pruebas para el módulo de Compras.

Cubre:
  - Flujo completo: RECIBIDA → APROBADA con movimiento kardex.
  - Bloqueo de re-aprobación (EstadoInvalidoError).
  - Conversión VES → USD al aprobar.
  - Anulación de factura RECIBIDA.
  - Bloqueo de anulación de factura APROBADA.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.almacen.models import MovimientoInventario
from apps.compras.models import FacturaCompra, DetalleFacturaCompra
from apps.core.exceptions import EstadoInvalidoError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _crear_factura_recibida(proveedor, producto, cantidad, costo_unitario,
                             moneda='USD', tasa_cambio='1.000000',
                             numero='COM-0001'):
    """Crea FacturaCompra en RECIBIDA con un solo detalle."""
    factura = FacturaCompra.objects.create(
        numero=numero,
        proveedor=proveedor,
        fecha=date.today(),
        moneda=moneda,
        tasa_cambio=Decimal(str(tasa_cambio)),
        estado='RECIBIDA',
    )
    DetalleFacturaCompra.objects.create(
        factura=factura,
        producto=producto,
        cantidad=Decimal(str(cantidad)),
        costo_unitario=Decimal(str(costo_unitario)),
    )
    factura.refresh_from_db()
    return factura


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Flujo completo de aprobación
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_factura_compra_flujo_completo(proveedor, producto_mp):
    """
    RECIBIDA → aprobar() → APROBADA.
    Verifica: estado, stock, costo_promedio y movimiento kardex.
    """
    factura = _crear_factura_recibida(
        proveedor, producto_mp,
        cantidad='100', costo_unitario='10.00',
    )

    factura.aprobar()

    factura.refresh_from_db()
    producto_mp.refresh_from_db()

    assert factura.estado == 'APROBADA'
    assert producto_mp.stock_actual == Decimal('100')
    assert producto_mp.costo_promedio == Decimal('10.000000')

    movimientos = MovimientoInventario.objects.filter(
        producto=producto_mp, tipo='ENTRADA', referencia='COM-0001'
    )
    assert movimientos.count() == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Bloqueo de re-aprobación
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_aprobar_factura_ya_aprobada(proveedor, producto_mp):
    """
    Intentar aprobar una factura que ya está APROBADA debe lanzar
    EstadoInvalidoError sin crear movimientos adicionales.
    """
    factura = _crear_factura_recibida(
        proveedor, producto_mp,
        cantidad='100', costo_unitario='10.00',
    )
    factura.aprobar()

    with pytest.raises(EstadoInvalidoError):
        factura.aprobar()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Conversión VES → USD al entrar al Kardex
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_conversion_ves_a_usd(proveedor, producto_mp):
    """
    Factura en VES con tasa=50.
    costo_unitario=500 VES → 500/50 = 10.000000 USD en el Kardex.
    """
    factura = _crear_factura_recibida(
        proveedor, producto_mp,
        cantidad='100', costo_unitario='500.00',
        moneda='VES', tasa_cambio='50.000000',
        numero='COM-0002',
    )

    factura.aprobar()

    producto_mp.refresh_from_db()
    assert producto_mp.costo_promedio == Decimal('10.000000')

    # El movimiento en el Kardex también debe reflejar el costo en USD
    mov = MovimientoInventario.objects.get(
        producto=producto_mp, tipo='ENTRADA', referencia='COM-0002'
    )
    assert mov.costo_unitario == Decimal('10.000000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Anular factura en estado RECIBIDA
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_anular_factura_recibida(proveedor, producto_mp):
    """
    Una factura RECIBIDA puede anularse. El stock no debe verse afectado.
    """
    factura = _crear_factura_recibida(
        proveedor, producto_mp,
        cantidad='100', costo_unitario='10.00',
    )

    factura.anular()

    factura.refresh_from_db()
    producto_mp.refresh_from_db()

    assert factura.estado == 'ANULADA'
    assert producto_mp.stock_actual == Decimal('0')

    # No debe existir ningún movimiento de inventario
    assert MovimientoInventario.objects.filter(
        producto=producto_mp, referencia='COM-0001'
    ).count() == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Bloqueo de anulación de factura APROBADA
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_anular_factura_aprobada_bloqueado(proveedor, producto_mp):
    """
    Una factura APROBADA no puede anularse directamente.
    Debe lanzar EstadoInvalidoError.
    """
    factura = _crear_factura_recibida(
        proveedor, producto_mp,
        cantidad='100', costo_unitario='10.00',
    )
    factura.aprobar()

    with pytest.raises(EstadoInvalidoError):
        factura.anular()
