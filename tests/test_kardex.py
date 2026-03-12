# -*- coding: utf-8 -*-
"""
test_kardex.py — Suite de pruebas para el Kardex (Promedio Ponderado Móvil).

Cubre:
  - Cálculo correcto del PPM en primera y segunda entrada.
  - Salidas: descuento de stock sin modificar costo promedio.
  - Bloqueo de stock negativo (StockInsuficienteError).
  - Creación de MovimientoInventario en entradas y salidas.
  - Atomicidad: rollback completo ante fallo parcial.
"""
import pytest
from decimal import Decimal
from unittest.mock import patch

from apps.almacen.models import MovimientoInventario
from apps.almacen.services import registrar_entrada, registrar_salida
from apps.core.exceptions import StockInsuficienteError


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers internos del módulo de test
# ═══════════════════════════════════════════════════════════════════════════════

def _set_stock(producto, stock, costo_promedio):
    """Fuerza stock y costo_promedio directamente en BD (bypass de services)."""
    producto.stock_actual = Decimal(str(stock))
    producto.costo_promedio = Decimal(str(costo_promedio))
    producto.save(update_fields=['stock_actual', 'costo_promedio'])
    producto.refresh_from_db()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Primera entrada con stock en cero
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_entrada_stock_cero(producto_mp):
    """
    Con stock=0 la primera entrada define el costo_promedio igual al costo_unitario.
    """
    registrar_entrada(producto_mp, cantidad=100, costo_unitario='10.00',
                      referencia='COM-0001')

    producto_mp.refresh_from_db()
    assert producto_mp.stock_actual == Decimal('100')
    assert producto_mp.costo_promedio == Decimal('10.000000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Segunda entrada: recálculo de Promedio Ponderado Móvil
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_promedio_ponderado_segunda_entrada(producto_mp):
    """
    Segunda entrada con precios distintos:
      (100 * 10 + 50 * 16) / 150 = 1800 / 150 = 12.000000
    """
    _set_stock(producto_mp, stock='100', costo_promedio='10.000000')

    registrar_entrada(producto_mp, cantidad=50, costo_unitario='16.00',
                      referencia='COM-0002')

    producto_mp.refresh_from_db()
    assert producto_mp.stock_actual == Decimal('150')
    assert producto_mp.costo_promedio == Decimal('12.000000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Salida: descuenta stock correctamente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_salida_descuenta_stock(producto_mp):
    """
    Una salida de 30 unidades sobre stock=150 deja stock_actual=120.
    """
    _set_stock(producto_mp, stock='150', costo_promedio='12.000000')

    registrar_salida(producto_mp, cantidad=30, referencia='VTA-0001')

    producto_mp.refresh_from_db()
    assert producto_mp.stock_actual == Decimal('120')
    assert producto_mp.costo_promedio == Decimal('12.000000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Salida NO modifica el costo promedio
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_salida_no_modifica_costo_promedio(producto_mp):
    """
    registrar_salida NUNCA debe modificar el campo costo_promedio del producto.
    Se verifica antes y después de la salida.
    """
    _set_stock(producto_mp, stock='200', costo_promedio='15.500000')
    costo_antes = producto_mp.costo_promedio

    registrar_salida(producto_mp, cantidad=50, referencia='VTA-0002')

    producto_mp.refresh_from_db()
    assert producto_mp.costo_promedio == costo_antes
    assert producto_mp.costo_promedio == Decimal('15.500000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Stock negativo bloqueado
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_stock_negativo_bloqueado(producto_mp):
    """
    Una salida mayor al stock disponible debe:
      1. Lanzar StockInsuficienteError.
      2. Dejar el stock intacto.
      3. No crear ningún MovimientoInventario.
    """
    _set_stock(producto_mp, stock='10', costo_promedio='10.000000')
    movimientos_antes = MovimientoInventario.objects.filter(producto=producto_mp).count()

    with pytest.raises(StockInsuficienteError):
        registrar_salida(producto_mp, cantidad=11, referencia='VTA-9999')

    producto_mp.refresh_from_db()
    assert producto_mp.stock_actual == Decimal('10')
    movimientos_despues = MovimientoInventario.objects.filter(producto=producto_mp).count()
    assert movimientos_despues == movimientos_antes


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — Entrada crea exactamente 1 MovimientoInventario ENTRADA
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_entrada_crea_movimiento(producto_mp):
    """
    registrar_entrada crea 1 MovimientoInventario de tipo ENTRADA
    con cantidad y costo_unitario correctos.
    """
    registrar_entrada(producto_mp, cantidad=100, costo_unitario='10.00',
                      referencia='COM-0001')

    movimientos = MovimientoInventario.objects.filter(
        producto=producto_mp, tipo='ENTRADA'
    )
    assert movimientos.count() == 1

    mov = movimientos.first()
    assert mov.cantidad == Decimal('100')
    assert mov.costo_unitario == Decimal('10.000000')
    assert mov.referencia == 'COM-0001'


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — Salida crea exactamente 1 MovimientoInventario SALIDA
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_salida_crea_movimiento(producto_mp):
    """
    registrar_salida crea 1 MovimientoInventario de tipo SALIDA cuyo
    costo_unitario iguala el costo_promedio vigente al momento de la salida.
    """
    _set_stock(producto_mp, stock='150', costo_promedio='12.000000')

    registrar_salida(producto_mp, cantidad=30, referencia='VTA-0001')

    movimientos = MovimientoInventario.objects.filter(
        producto=producto_mp, tipo='SALIDA'
    )
    assert movimientos.count() == 1

    mov = movimientos.first()
    assert mov.cantidad == Decimal('30')
    assert mov.costo_unitario == Decimal('12.000000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8 — Atomicidad de entrada: rollback si falla creación del movimiento
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_atomicidad_entrada(producto_mp):
    """
    Si MovimientoInventario.objects.create lanza una excepción después de
    actualizar el producto, el rollback debe dejar el stock intacto.
    """
    _set_stock(producto_mp, stock='0', costo_promedio='0')

    target = 'apps.almacen.models.MovimientoInventario.objects.create'
    with patch(target, side_effect=Exception('Error simulado de BD')):
        with pytest.raises(Exception, match='Error simulado de BD'):
            registrar_entrada(producto_mp, cantidad=100, costo_unitario='10.00',
                              referencia='COM-FAIL')

    producto_mp.refresh_from_db()
    # El stock NO debe haber cambiado debido al rollback atómico
    assert producto_mp.stock_actual == Decimal('0')
    assert producto_mp.costo_promedio == Decimal('0')
