# -*- coding: utf-8 -*-
"""
test_ajustes.py — Suite de pruebas para ajustes de inventario.

En el Sprint 1, el mecanismo de ajuste de inventario se ejecuta mediante
la combinación de registrar_entrada() / registrar_salida() con referencias
de tipo 'INV-XXXX'. No existe un modelo AjusteInventario autónomo aún;
este archivo valida las reglas de negocio que deben cumplirse cuando se
realiza un ajuste manual al Kardex, incluyendo:

  - Ajuste positivo (entrada): incrementa stock y recalcula PPM.
  - Ajuste negativo (salida): decrementa stock al costo promedio vigente.
  - Ajuste negativo bloqueado si stock insuficiente.
  - Ajuste con cantidad cero rechazado (ValueError).
  - Ajuste de inventario crea exactamente 1 MovimientoInventario.
  - Varios ajustes sucesivos mantienen el PPM correcto.
  - Atomicidad: ajuste parcialmente fallido no modifica el stock.
"""
import pytest
from decimal import Decimal
from unittest.mock import patch

from apps.almacen.models import MovimientoInventario
from apps.almacen.services import registrar_entrada, registrar_salida
from apps.core.exceptions import StockInsuficienteError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _set_stock(producto, stock, costo_promedio):
    """Fuerza stock y costo_promedio sin pasar por la lógica de negocio (setup)."""
    producto.stock_actual = Decimal(str(stock))
    producto.costo_promedio = Decimal(str(costo_promedio))
    producto.save(update_fields=['stock_actual', 'costo_promedio'])
    producto.refresh_from_db()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Ajuste positivo aumenta stock y recalcula PPM
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_ajuste_positivo_aumenta_stock_y_precio(producto_mp):
    """
    Ajuste de inventario POSITIVO (ENTRADA):
      Situación inicial: stock=100, costo_promedio=20.00
      Entrada ajuste:    50 unidades a 14.00 USD
      PPM esperado:      (100*20 + 50*14) / 150 = 2700/150 = 18.000000
    """
    _set_stock(producto_mp, stock='100', costo_promedio='20.000000')

    registrar_entrada(
        producto=producto_mp,
        cantidad=Decimal('50'),
        costo_unitario=Decimal('14.00'),
        referencia='INV-0001',
        notas='Ajuste positivo conteo físico',
    )

    producto_mp.refresh_from_db()
    assert producto_mp.stock_actual == Decimal('150')
    assert producto_mp.costo_promedio == Decimal('18.000000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Ajuste negativo descuenta stock al costo promedio vigente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_ajuste_negativo_descuenta_stock(producto_mp):
    """
    Ajuste de inventario NEGATIVO (SALIDA) por merma:
      stock=200, costo_promedio=15.00
      Salida: 30 unidades → stock=170, costo_promedio no cambia.
    """
    _set_stock(producto_mp, stock='200', costo_promedio='15.000000')

    registrar_salida(
        producto=producto_mp,
        cantidad=Decimal('30'),
        referencia='INV-0002',
        notas='Ajuste negativo merma',
    )

    producto_mp.refresh_from_db()
    assert producto_mp.stock_actual == Decimal('170')
    assert producto_mp.costo_promedio == Decimal('15.000000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Ajuste negativo bloqueado si stock insuficiente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_ajuste_negativo_bloqueado_sin_stock(producto_mp):
    """
    Intentar registrar un ajuste negativo mayor al stock disponible debe
    lanzar StockInsuficienteError y no modificar el stock.
    """
    _set_stock(producto_mp, stock='10', costo_promedio='10.000000')

    with pytest.raises(StockInsuficienteError):
        registrar_salida(
            producto=producto_mp,
            cantidad=Decimal('15'),
            referencia='INV-0003',
        )

    producto_mp.refresh_from_db()
    assert producto_mp.stock_actual == Decimal('10')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Ajuste con cantidad cero rechazado
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_ajuste_cantidad_cero_rechazado(producto_mp):
    """
    Pasar cantidad=0 a registrar_entrada o registrar_salida debe lanzar ValueError.
    """
    with pytest.raises(ValueError):
        registrar_entrada(
            producto=producto_mp,
            cantidad=Decimal('0'),
            costo_unitario=Decimal('10.00'),
            referencia='INV-CERO',
        )

    with pytest.raises(ValueError):
        registrar_salida(
            producto=producto_mp,
            cantidad=Decimal('0'),
            referencia='INV-CERO',
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Ajuste crea exactamente 1 MovimientoInventario
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_ajuste_crea_un_movimiento(producto_mp):
    """
    Cada llamada a registrar_entrada / registrar_salida debe crear
    exactamente 1 MovimientoInventario con la referencia correcta.
    """
    registrar_entrada(
        producto=producto_mp,
        cantidad=Decimal('50'),
        costo_unitario=Decimal('10.00'),
        referencia='INV-0010',
    )

    movimientos = MovimientoInventario.objects.filter(
        producto=producto_mp, referencia='INV-0010'
    )
    assert movimientos.count() == 1
    assert movimientos.first().tipo == 'ENTRADA'


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — Múltiples ajustes sucesivos mantienen PPM correcto
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_multiples_ajustes_mantienen_ppm(producto_mp):
    """
    Tres ajustes de entrada con precios distintos deben producir el PPM
    acumulado correcto al final.

    Paso 1: stock=0  → 100 ud a 10 → PPM = 10.000000
    Paso 2: stock=100 → 200 ud a 13 → PPM = (100*10 + 200*13) / 300 = 3600/300 = 12.000000
    Paso 3: stock=300 → 300 ud a 15 → PPM = (300*12 + 300*15) / 600 = 8100/600 = 13.500000
    """
    registrar_entrada(producto_mp, cantidad=100, costo_unitario='10.00', referencia='INV-A1')
    producto_mp.refresh_from_db()
    assert producto_mp.costo_promedio == Decimal('10.000000')

    registrar_entrada(producto_mp, cantidad=200, costo_unitario='13.00', referencia='INV-A2')
    producto_mp.refresh_from_db()
    assert producto_mp.costo_promedio == Decimal('12.000000')

    registrar_entrada(producto_mp, cantidad=300, costo_unitario='15.00', referencia='INV-A3')
    producto_mp.refresh_from_db()
    assert producto_mp.costo_promedio == Decimal('13.500000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — Atomicidad: ajuste que falla revierte todo
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_ajuste_atomicidad_rollback(producto_mp):
    """
    Si la creación del MovimientoInventario falla, el stock del producto
    no debe haber cambiado (rollback completo del atomic()).
    """
    _set_stock(producto_mp, stock='0', costo_promedio='0')

    with patch(
        'apps.almacen.models.MovimientoInventario.objects.create',
        side_effect=Exception('Fallo de BD simulado'),
    ):
        with pytest.raises(Exception, match='Fallo de BD simulado'):
            registrar_entrada(
                producto=producto_mp,
                cantidad=Decimal('100'),
                costo_unitario=Decimal('10.00'),
                referencia='INV-FAIL',
            )

    producto_mp.refresh_from_db()
    assert producto_mp.stock_actual == Decimal('0')
    assert producto_mp.costo_promedio == Decimal('0')
