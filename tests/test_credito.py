# -*- coding: utf-8 -*-
"""
test_credito.py — Suite de pruebas para el control de crédito de clientes.

Actualizado para Sprint 2: soporte para Listas de Precios obligatorias.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from apps.almacen.services import registrar_entrada
from apps.core.exceptions import EstadoInvalidoError
from apps.ventas.models import (
    Cliente, FacturaVenta, DetalleFacturaVenta, Cobro, ListaPrecio, DetalleLista
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


@pytest.fixture
def lista_precios(db, producto_pt):
    """Lista de precios aprobada para los productos de los tests."""
    lp = ListaPrecio.objects.create(nombre='Lista Crédito', activa=True)
    DetalleLista.objects.create(
        lista=lp, producto=producto_pt, precio=Decimal('100.000000'),
        vigente_desde=date.today(), aprobado=True
    )
    return lp


def _dar_stock(producto, cantidad='100', costo='10.00'):
    """Inyecta stock al producto vía Kardex."""
    registrar_entrada(
        producto=producto,
        cantidad=Decimal(str(cantidad)),
        costo_unitario=Decimal(str(costo)),
        referencia='STOCK-INICIAL',
    )
    producto.refresh_from_db()


def _crear_factura_emitida(cliente, producto, numero, lista_precio, fecha=None):
    """
    Crea FacturaVenta en EMITIDA con una lista de precios asociada.
    """
    if fecha is None:
        fecha = date.today()
    factura = FacturaVenta.objects.create(
        numero=numero,
        cliente=cliente,
        fecha=fecha,
        estado='EMITIDA',
        lista_precio=lista_precio,
    )
    DetalleFacturaVenta.objects.create(
        factura=factura,
        producto=producto,
        cantidad=Decimal('1.0000'),
        precio_unitario=Decimal('0'),
    )
    factura.refresh_from_db()
    return factura


def _forzar_vencimiento(factura, dias_atras=31):
    """
    Simula que la factura está vencida.
    """
    FacturaVenta.objects.filter(pk=factura.pk).update(
        fecha_vencimiento=date.today() - timedelta(days=dias_atras)
    )
    factura.refresh_from_db()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — BLOQUEO: cliente con deuda vencida no puede emitir
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_bloqueo_cliente_con_deuda_vencida(cliente_bloqueo, producto_pt, lista_precios):
    """
    Un cliente con facturas vencidas bloquea la emisión.
    """
    _dar_stock(producto_pt, cantidad='200', costo='5.00')

    # Crear factura anterior ya vencida (sin cobrar)
    fv_vieja = _crear_factura_emitida(
        cliente_bloqueo, producto_pt, numero='VTA-VIEJA-01',
        lista_precio=lista_precios,
        fecha=date.today() - timedelta(days=60),
    )
    fv_vieja.emitir()
    _forzar_vencimiento(fv_vieja, dias_atras=31)

    # Intentar emitir una nueva factura para el mismo cliente
    fv_nueva = _crear_factura_emitida(
        cliente_bloqueo, producto_pt, numero='VTA-NUEVA-01',
        lista_precio=lista_precios,
    )

    with pytest.raises(EstadoInvalidoError) as exc_info:
        fv_nueva.emitir()

    assert 'bloqueado' in str(exc_info.value).lower() or 'vencidas' in str(exc_info.value).lower()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — ADVERTENCIA: emite con warning pero no bloquea
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_advertencia_no_bloquea_emision(cliente_advertencia, producto_pt, lista_precios):
    """
    Un cliente con advertencia emite normalmente.
    """
    _dar_stock(producto_pt, cantidad='200', costo='5.00')

    # Factura vencida previa
    fv_vieja = _crear_factura_emitida(
        cliente_advertencia, producto_pt, numero='VTA-ADV-VIEJA',
        lista_precio=lista_precios,
        fecha=date.today() - timedelta(days=60),
    )
    _forzar_vencimiento(fv_vieja, dias_atras=31)

    # Nueva factura
    fv_nueva = _crear_factura_emitida(
        cliente_advertencia, producto_pt, numero='VTA-ADV-NUEVA',
        lista_precio=lista_precios,
    )

    fv_nueva.emitir()

    from apps.almacen.models import MovimientoInventario
    salidas = MovimientoInventario.objects.filter(
        referencia='VTA-ADV-NUEVA', tipo='SALIDA'
    ).count()
    assert salidas == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Cliente sin deuda vencida pasa sin restricciones
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cliente_sin_deuda_vencida_pasa(cliente_limpio, producto_pt, lista_precios):
    """
    Cliente limpio puede emitir.
    """
    _dar_stock(producto_pt, cantidad='100', costo='5.00')

    fv = _crear_factura_emitida(cliente_limpio, producto_pt, numero='VTA-LIMPIO-01',
                                 lista_precio=lista_precios)

    fv.emitir()

    from apps.almacen.models import MovimientoInventario
    assert MovimientoInventario.objects.filter(
        referencia='VTA-LIMPIO-01', tipo='SALIDA'
    ).count() == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Factura completamente cobrada no bloquea nuevas emisiones
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_factura_pagada_no_bloquea(cliente_bloqueo, producto_pt, lista_precios):
    """
    Factura pagada no bloquea el crédito.
    """
    _dar_stock(producto_pt, cantidad='200', costo='5.00')

    # Factura vencida PERO con cobro completo
    fv_vieja = _crear_factura_emitida(
        cliente_bloqueo, producto_pt, numero='VTA-PAGADA-01',
        lista_precio=lista_precios,
        fecha=date.today() - timedelta(days=60),
    )
    _forzar_vencimiento(fv_vieja, dias_atras=31)
    
    # Obtener total real (1 un * 100 USD)
    fv_vieja.refresh_from_db()

    Cobro.objects.create(
        factura=fv_vieja,
        fecha=date.today(),
        monto=Decimal('100.00'),
        medio_pago='EFECTIVO_USD',
    )

    # Nueva factura
    fv_nueva = _crear_factura_emitida(
        cliente_bloqueo, producto_pt, numero='VTA-NUEVA-LIMPIO',
        lista_precio=lista_precios,
    )

    fv_nueva.emitir()

    from apps.almacen.models import MovimientoInventario
    assert MovimientoInventario.objects.filter(
        referencia='VTA-NUEVA-LIMPIO', tipo='SALIDA'
    ).count() == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — fecha_vencimiento se calcula correctamente en emitir()
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_fecha_vencimiento_calculada_correctamente(cliente_limpio, producto_pt, lista_precios):
    """
    La fecha de vencimiento es fecha + días crédito cliente.
    """
    _dar_stock(producto_pt, cantidad='100', costo='5.00')

    hoy = date.today()
    fv = _crear_factura_emitida(cliente_limpio, producto_pt, numero='VTA-VENCE-01',
                                 lista_precio=lista_precios, fecha=hoy)
    fv.emitir()
    fv.refresh_from_db()

    fecha_esperada = hoy + timedelta(days=cliente_limpio.dias_credito)
    assert fv.fecha_vencimiento == fecha_esperada


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — dias_credito personalizado por cliente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_dias_credito_personalizado(db, producto_pt, lista_precios):
    """
    Verifica que se usen los días de crédito del cliente.
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
    fv = _crear_factura_emitida(cliente_15, producto_pt, numero='VTA-15D-01', 
                                 lista_precio=lista_precios, fecha=hoy)
    fv.emitir()
    fv.refresh_from_db()

    assert fv.fecha_vencimiento == hoy + timedelta(days=15)
