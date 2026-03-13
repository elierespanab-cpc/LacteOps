# -*- coding: utf-8 -*-
"""
test_ventas.py — Suite de pruebas para el módulo de Ventas.

Actualizado para Sprint 2: emitir() ahora requiere una Lista de Precios
con el producto aprobado.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.almacen.models import MovimientoInventario
from apps.almacen.services import registrar_entrada
from apps.ventas.models import FacturaVenta, DetalleFacturaVenta, Cobro, ListaPrecio, DetalleLista
from apps.core.exceptions import EstadoInvalidoError, StockInsuficienteError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _dar_stock(producto, cantidad, costo_unitario, referencia='INICIAL'):
    """Genera stock real vía el Kardex (no fuerza UPDATE directo)."""
    registrar_entrada(
        producto=producto,
        cantidad=Decimal(str(cantidad)),
        costo_unitario=Decimal(str(costo_unitario)),
        referencia=referencia,
    )
    producto.refresh_from_db()


def _crear_lista_con_precio(producto, precio='10.00'):
    """Crea una lista de precios aprobada para el producto."""
    lista = ListaPrecio.objects.create(nombre='Lista Test', activa=True)
    DetalleLista.objects.create(
        lista=lista, producto=producto, precio=Decimal(precio),
        vigente_desde=date.today(), aprobado=True
    )
    return lista


def _crear_factura_venta(cliente, producto, cantidad, precio_unitario,
                          numero='VTA-0001', lista_precio=None):
    """
    Crea FacturaVenta en estado EMITIDA con un solo detalle.
    """
    factura = FacturaVenta.objects.create(
        numero=numero,
        cliente=cliente,
        fecha=date.today(),
        estado='EMITIDA',
        lista_precio=lista_precio,
    )
    # Se inicializa con precio_unitario=0 para dejar que emitir() lo asigne desde la lista
    DetalleFacturaVenta.objects.create(
        factura=factura,
        producto=producto,
        cantidad=Decimal(str(cantidad)),
        precio_unitario=Decimal('0'),
    )
    factura.refresh_from_db()
    return factura


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Emisión descuenta stock
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_emitir_factura_descuenta_stock(cliente, producto_pt):
    """
    Stock inicial=50, factura de 20 unidades.
    emitir() debe dejar stock=30 y crear 1 MovimientoInventario SALIDA.
    """
    _dar_stock(producto_pt, cantidad=50, costo_unitario='5.00')
    lista = _crear_lista_con_precio(producto_pt, precio='10.00')

    factura = _crear_factura_venta(cliente, producto_pt,
                                   cantidad=20, precio_unitario='10.00',
                                   lista_precio=lista)
    factura.emitir()

    producto_pt.refresh_from_db()
    assert producto_pt.stock_actual == Decimal('30')

    movimientos = MovimientoInventario.objects.filter(
        producto=producto_pt, tipo='SALIDA', referencia='VTA-0001'
    )
    assert movimientos.count() == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Bloqueo de emisión sin stock suficiente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_emitir_sin_stock_bloqueado(cliente, producto_pt):
    """
    Stock=5, factura de 10 unidades.
    emitir() debe lanzar StockInsuficienteError y stock debe permanecer en 5.
    """
    _dar_stock(producto_pt, cantidad=5, costo_unitario='5.00')
    lista = _crear_lista_con_precio(producto_pt)

    factura = _crear_factura_venta(cliente, producto_pt,
                                   cantidad=10, precio_unitario='10.00',
                                   lista_precio=lista)

    with pytest.raises(StockInsuficienteError):
        factura.emitir()

    producto_pt.refresh_from_db()
    assert producto_pt.stock_actual == Decimal('5')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — emitir() es idempotente (segunda llamada rechazada)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_emitir_idempotente(cliente, producto_pt):
    """
    Llamar a emitir() dos veces sobre la misma factura debe:
      - Segunda llamada: lanzar EstadoInvalidoError.
      - Stock descontado solo una vez (stock_actual == 30, no 10).
      - Exactamente 1 MovimientoInventario SALIDA.
    """
    _dar_stock(producto_pt, cantidad=50, costo_unitario='5.00')
    lista = _crear_lista_con_precio(producto_pt)

    factura = _crear_factura_venta(cliente, producto_pt,
                                   cantidad=20, precio_unitario='10.00',
                                   lista_precio=lista)
    factura.emitir()

    with pytest.raises(EstadoInvalidoError):
        factura.emitir()

    producto_pt.refresh_from_db()
    assert producto_pt.stock_actual == Decimal('30')

    movimientos = MovimientoInventario.objects.filter(
        producto=producto_pt, tipo='SALIDA', referencia='VTA-0001'
    )
    assert movimientos.count() == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — marcar_cobrada flujo completo
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_marcar_cobrada_flujo_completo(cliente, producto_pt):
    """
    Factura emitida con total=100.00.
    Registrar cobro de 100.00 → marcar_cobrada() debe cambiar estado a COBRADA.
    """
    _dar_stock(producto_pt, cantidad=50, costo_unitario='5.00')
    lista = _crear_lista_con_precio(producto_pt, precio='10.00')

    factura = _crear_factura_venta(cliente, producto_pt,
                                   cantidad=10, precio_unitario='10.00',
                                   lista_precio=lista)
    factura.emitir()
    factura.refresh_from_db()

    assert factura.total == Decimal('100.00')

    Cobro.objects.create(
        factura=factura,
        fecha=date.today(),
        monto=Decimal('100.00'),
        medio_pago='EFECTIVO_USD',
    )

    factura.marcar_cobrada()
    factura.refresh_from_db()

    assert factura.estado == 'COBRADA'


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — marcar_cobrada bloqueado por saldo pendiente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_marcar_cobrada_saldo_pendiente(cliente, producto_pt):
    """
    Factura con total=100.00, solo cobrado 50.00.
    marcar_cobrada() debe lanzar EstadoInvalidoError (saldo pendiente: 50).
    """
    _dar_stock(producto_pt, cantidad=50, costo_unitario='5.00')
    lista = _crear_lista_con_precio(producto_pt, precio='10.00')

    factura = _crear_factura_venta(cliente, producto_pt,
                                   cantidad=10, precio_unitario='10.00',
                                   lista_precio=lista)
    factura.emitir()
    factura.refresh_from_db()

    Cobro.objects.create(
        factura=factura,
        fecha=date.today(),
        monto=Decimal('50.00'),
        medio_pago='TRANSFERENCIA_USD',
    )

    with pytest.raises(EstadoInvalidoError):
        factura.marcar_cobrada()

    factura.refresh_from_db()
    assert factura.estado == 'EMITIDA'
