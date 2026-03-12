# -*- coding: utf-8 -*-
"""
test_credito.py — Suite de pruebas para el control de crédito de clientes.

Cubre (regla 2.15 del contrato de negocio):
  - BLOQUEO: cliente con facturas vencidas y saldo no puede emitir nuevas facturas.
  - ADVERTENCIA: cliente con facturas vencidas y saldo emite con warning (no bloquea).
  - Cliente sin deuda vencida pasa sin problema.
  - Factura ya cobrada no cuenta como vencida (saldo_pendiente == 0).
  - fecha_vencimiento se calcula correctamente en emitir().

NOTA: emitir() requiere stock previo en los productos. Usamos registrar_entrada()
para preparar el stock antes de llamar a emitir().
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from apps.almacen.services import registrar_entrada
from apps.core.exceptions import EstadoInvalidoError
from apps.ventas.models import (
    Cliente, FacturaVenta, DetalleFacturaVenta, Cobro,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures locales
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cliente_bloqueo(db):
    """Cliente con control de crédito BLOQUEO, plazo 30 días."""
    return Cliente.objects.create(
        nombre='Cliente Bloqueado S.A.',
        rif='J-10000001-0',
        limite_credito=Decimal('5000.00'),
        dias_credito=30,
        tipo_control_credito='BLOQUEO',
    )


@pytest.fixture
def cliente_advertencia(db):
    """Cliente con control de crédito ADVERTENCIA, plazo 30 días."""
    return Cliente.objects.create(
        nombre='Cliente Advertencia C.A.',
        rif='J-10000002-0',
        limite_credito=Decimal('5000.00'),
        dias_credito=30,
        tipo_control_credito='ADVERTENCIA',
    )


@pytest.fixture
def cliente_limpio(db):
    """Cliente sin historial de deuda vencida."""
    return Cliente.objects.create(
        nombre='Cliente Limpio S.R.L.',
        rif='J-10000003-0',
        limite_credito=Decimal('5000.00'),
        dias_credito=30,
        tipo_control_credito='BLOQUEO',
    )


def _dar_stock(producto, cantidad='100', costo='10.00'):
    """Inyecta stock al producto vía Kardex."""
    registrar_entrada(
        producto=producto,
        cantidad=Decimal(str(cantidad)),
        costo_unitario=Decimal(str(costo)),
        referencia='STOCK-INICIAL',
    )
    producto.refresh_from_db()


def _crear_factura_emitida(cliente, producto, numero, fecha=None):
    """
    Crea FacturaVenta en EMITIDA con un detalle de 1 unidad a 100 USD.
    El stock debe haberse preparado con _dar_stock() antes de llamar.
    """
    if fecha is None:
        fecha = date.today()
    factura = FacturaVenta.objects.create(
        numero=numero,
        cliente=cliente,
        fecha=fecha,
        estado='EMITIDA',
    )
    DetalleFacturaVenta.objects.create(
        factura=factura,
        producto=producto,
        cantidad=Decimal('1.0000'),
        precio_unitario=Decimal('100.000000'),
    )
    factura.refresh_from_db()
    return factura


def _forzar_vencimiento(factura, dias_atras=31):
    """
    Simula que la factura está vencida: establece fecha_vencimiento
    en el pasado usando update directo (bypass de lógica de negocio,
    solo para setup de prueba).
    """
    FacturaVenta.objects.filter(pk=factura.pk).update(
        fecha_vencimiento=date.today() - timedelta(days=dias_atras)
    )
    factura.refresh_from_db()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — BLOQUEO: cliente con deuda vencida no puede emitir
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_bloqueo_cliente_con_deuda_vencida(cliente_bloqueo, producto_pt):
    """
    Un cliente con tipo_control_credito=BLOQUEO que tiene una factura EMITIDA
    con fecha_vencimiento en el pasado y saldo_pendiente > 0 debe bloquear
    la emisión de cualquier nueva factura.
    """
    _dar_stock(producto_pt, cantidad='200', costo='5.00')

    # Crear factura anterior ya vencida (sin cobrar)
    fv_vieja = _crear_factura_emitida(
        cliente_bloqueo, producto_pt, numero='VTA-VIEJA-01',
        fecha=date.today() - timedelta(days=60),
    )
    _forzar_vencimiento(fv_vieja, dias_atras=31)

    # Intentar emitir una nueva factura para el mismo cliente
    fv_nueva = _crear_factura_emitida(
        cliente_bloqueo, producto_pt, numero='VTA-NUEVA-01',
    )

    with pytest.raises(EstadoInvalidoError) as exc_info:
        fv_nueva.emitir()

    assert 'bloqueado' in str(exc_info.value).lower() or 'vencidas' in str(exc_info.value).lower()

    # Stock debe permanecer intacto (no se descontó)
    producto_pt.refresh_from_db()
    # Stock inicial 200, fv_vieja NO llegó a emitir salida en este test
    # (se creó con estado EMITIDA pero no se llamó a emitir())
    # → solo la factura nueva no debe haber descontado
    from apps.almacen.models import MovimientoInventario
    salidas_nueva = MovimientoInventario.objects.filter(
        referencia='VTA-NUEVA-01', tipo='SALIDA'
    ).count()
    assert salidas_nueva == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — ADVERTENCIA: emite con warning pero no bloquea
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_advertencia_no_bloquea_emision(cliente_advertencia, producto_pt):
    """
    Un cliente con tipo_control_credito=ADVERTENCIA que tiene una factura vencida
    permite emitir la nueva factura, solo genera un logger.warning().
    """
    _dar_stock(producto_pt, cantidad='200', costo='5.00')

    # Factura vencida previa para el mismo cliente
    fv_vieja = _crear_factura_emitida(
        cliente_advertencia, producto_pt, numero='VTA-ADV-VIEJA',
        fecha=date.today() - timedelta(days=60),
    )
    _forzar_vencimiento(fv_vieja, dias_atras=31)

    # Nueva factura: debe emitirse aunque haya deuda vencida
    fv_nueva = _crear_factura_emitida(
        cliente_advertencia, producto_pt, numero='VTA-ADV-NUEVA',
    )

    # NO debe lanzar excepción
    fv_nueva.emitir()

    from apps.almacen.models import MovimientoInventario
    salidas = MovimientoInventario.objects.filter(
        referencia='VTA-ADV-NUEVA', tipo='SALIDA'
    ).count()
    assert salidas == 1, "La factura debe haberse procesado a pesar de la advertencia"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Cliente sin deuda vencida pasa sin restricciones
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cliente_sin_deuda_vencida_pasa(cliente_limpio, producto_pt):
    """
    Un cliente con tipo_control_credito=BLOQUEO pero sin facturas vencidas
    puede emitir normalmente.
    """
    _dar_stock(producto_pt, cantidad='100', costo='5.00')

    fv = _crear_factura_emitida(cliente_limpio, producto_pt, numero='VTA-LIMPIO-01')

    # No debe lanzar ninguna excepción
    fv.emitir()

    from apps.almacen.models import MovimientoInventario
    assert MovimientoInventario.objects.filter(
        referencia='VTA-LIMPIO-01', tipo='SALIDA'
    ).count() == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Factura completamente cobrada no bloquea nuevas emisiones
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_factura_pagada_no_bloquea(cliente_bloqueo, producto_pt):
    """
    Una factura EMITIDA con fecha_vencimiento en el pasado pero con
    saldo_pendiente == 0 (cobrada en su totalidad) NO debe activar el bloqueo.
    """
    _dar_stock(producto_pt, cantidad='200', costo='5.00')

    # Factura vencida PERO con cobro completo
    fv_vieja = _crear_factura_emitida(
        cliente_bloqueo, producto_pt, numero='VTA-PAGADA-01',
        fecha=date.today() - timedelta(days=60),
    )
    _forzar_vencimiento(fv_vieja, dias_atras=31)
    # Registrar cobro completo
    Cobro.objects.create(
        factura=fv_vieja,
        fecha=date.today(),
        monto=Decimal('100.00'),  # igual al total de la factura
        medio_pago='EFECTIVO_USD',
    )

    # Nueva factura para el mismo cliente → no debe bloquearse
    fv_nueva = _crear_factura_emitida(
        cliente_bloqueo, producto_pt, numero='VTA-NUEVA-LIMPIO',
    )

    # No debe lanzar EstadoInvalidoError
    fv_nueva.emitir()

    from apps.almacen.models import MovimientoInventario
    assert MovimientoInventario.objects.filter(
        referencia='VTA-NUEVA-LIMPIO', tipo='SALIDA'
    ).count() == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — fecha_vencimiento se calcula correctamente en emitir()
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_fecha_vencimiento_calculada_correctamente(cliente_limpio, producto_pt):
    """
    Al llamar a emitir(), fecha_vencimiento debe asignarse como:
      fecha_emision + timedelta(days=cliente.dias_credito)

    Con dias_credito=30 y fecha=hoy → fecha_vencimiento = hoy + 30 días.
    """
    _dar_stock(producto_pt, cantidad='100', costo='5.00')

    hoy = date.today()
    fv = _crear_factura_emitida(cliente_limpio, producto_pt, numero='VTA-VENCE-01',
                                 fecha=hoy)
    fv.emitir()

    fv.refresh_from_db()

    fecha_esperada = hoy + timedelta(days=cliente_limpio.dias_credito)
    assert fv.fecha_vencimiento == fecha_esperada, (
        f"Se esperaba {fecha_esperada} pero se obtuvo {fv.fecha_vencimiento}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — dias_credito personalizado por cliente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_dias_credito_personalizado(db, producto_pt):
    """
    Un cliente con dias_credito=15 debe tener fecha_vencimiento = hoy + 15.
    """
    _dar_stock(producto_pt, cantidad='50', costo='5.00')

    cliente_15 = Cliente.objects.create(
        nombre='Cliente 15 Días',
        rif='J-15150015-0',
        limite_credito=Decimal('1000.00'),
        dias_credito=15,
        tipo_control_credito='ADVERTENCIA',
    )

    hoy = date.today()
    fv = _crear_factura_emitida(cliente_15, producto_pt, numero='VTA-15D-01', fecha=hoy)
    fv.emitir()
    fv.refresh_from_db()

    assert fv.fecha_vencimiento == hoy + timedelta(days=15)
