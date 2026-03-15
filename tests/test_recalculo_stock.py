# -*- coding: utf-8 -*-
"""
test_recalculo_stock.py — recalcular_stock() de almacen.services (Sprint 5).

Cubre:
  - Entradas y salidas conocidas → stock_actual y costo_promedio correctos (Decimal exacto).
  - Movimientos que dejarían stock negativo → stock clamped en 0.
  - Idempotencia: llamar dos veces produce el mismo resultado.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.almacen.models import MovimientoInventario
from apps.almacen.services import registrar_entrada, registrar_salida, recalcular_stock


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Entradas y salidas conocidas producen resultado correcto
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_recalculo_con_entradas_y_salidas(producto_mp):
    """
    Secuencia:
      ENTRADA 10 u @ 5.00 USD  → stock=10, costo_prom=5.000000
      ENTRADA 10 u @ 15.00 USD → stock=20, costo_prom=(50+150)/20=10.000000
      SALIDA  5 u              → stock=15, costo_prom=10.000000 (inalterado)

    recalcular_stock() debe reproducir stock=15, costo_promedio=10.000000.
    """
    registrar_entrada(producto=producto_mp, cantidad=Decimal('10'),
                      costo_unitario=Decimal('5.000000'), referencia='ENT-001')
    registrar_entrada(producto=producto_mp, cantidad=Decimal('10'),
                      costo_unitario=Decimal('15.000000'), referencia='ENT-002')
    registrar_salida(producto=producto_mp, cantidad=Decimal('5'),
                     referencia='SAL-001')

    # Recalcular desde cero usando los movimientos registrados
    resultado = recalcular_stock(producto_mp)

    assert resultado['stock'] == Decimal('15.0000')
    assert resultado['costo_promedio'] == Decimal('10.000000')

    producto_mp.refresh_from_db()
    assert producto_mp.stock_actual == Decimal('15.0000')
    assert producto_mp.costo_promedio == Decimal('10.000000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Movimientos que dejarían stock negativo quedan en 0
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_recalculo_stock_negativo_queda_en_cero(producto_mp):
    """
    ENTRADA 10 u @ 5.00 USD → stock=10.
    Luego se inserta directamente un MovimientoInventario SALIDA de 20 u
    (bypass del check de stock).
    recalcular_stock() debe aplicar max(0, 10-20) = 0.
    """
    registrar_entrada(producto=producto_mp, cantidad=Decimal('10'),
                      costo_unitario=Decimal('5.000000'), referencia='ENT-001')

    # Crear SALIDA excesiva directamente (bypasa StockInsuficienteError)
    MovimientoInventario.objects.create(
        producto=producto_mp,
        tipo='SALIDA',
        cantidad=Decimal('20.0000'),
        costo_unitario=Decimal('5.000000'),
        referencia='SAL-EXCESO',
    )

    resultado = recalcular_stock(producto_mp)

    assert resultado['stock'] == Decimal('0.0000')

    producto_mp.refresh_from_db()
    assert producto_mp.stock_actual == Decimal('0.0000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — recalcular_stock() es idempotente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_recalculo_idempotente(producto_mp):
    """
    Dos llamadas sucesivas a recalcular_stock() deben producir exactamente
    el mismo stock_actual y costo_promedio.
    """
    registrar_entrada(producto=producto_mp, cantidad=Decimal('20'),
                      costo_unitario=Decimal('8.000000'), referencia='ENT-001')
    registrar_salida(producto=producto_mp, cantidad=Decimal('5'),
                     referencia='SAL-001')

    resultado_1 = recalcular_stock(producto_mp)
    resultado_2 = recalcular_stock(producto_mp)

    assert resultado_1['stock'] == resultado_2['stock']
    assert resultado_1['costo_promedio'] == resultado_2['costo_promedio']

    assert resultado_2['stock'] == Decimal('15.0000')
    assert resultado_2['costo_promedio'] == Decimal('8.000000')
