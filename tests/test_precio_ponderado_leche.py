# -*- coding: utf-8 -*-
"""
test_precio_ponderado_leche.py — Suite para calcular_precio_ponderado_leche (Sprint 4).
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from apps.almacen.models import UnidadMedida, Categoria, Producto, MovimientoInventario
from apps.reportes.analytics import calcular_precio_ponderado_leche


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def unidad_litros(db):
    unidad, _ = UnidadMedida.objects.get_or_create(simbolo='L', defaults={'nombre': 'Litro'})
    return unidad


@pytest.fixture
def cat_lacteos(db):
    cat, _ = Categoria.objects.get_or_create(nombre='LechePond')
    return cat


@pytest.fixture
def leche_vaca(db, unidad_litros, cat_lacteos):
    return Producto.objects.create(
        codigo='LP-VACA',
        nombre='Leche Vaca',
        categoria=cat_lacteos,
        unidad_medida=unidad_litros,
        es_materia_prima_base=True,
        stock_actual=Decimal('100.0000'),
        costo_promedio=Decimal('0.500000'),
        activo=True,
    )


@pytest.fixture
def leche_bufala(db, unidad_litros, cat_lacteos):
    return Producto.objects.create(
        codigo='LP-BUFALA',
        nombre='Leche Búfala',
        categoria=cat_lacteos,
        unidad_medida=unidad_litros,
        es_materia_prima_base=True,
        stock_actual=Decimal('50.0000'),
        costo_promedio=Decimal('1.000000'),
        activo=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_ponderacion_dos_tipos(leche_vaca, leche_bufala):
    """
    Entradas en los últimos 7 días:
      - Leche Vaca:  100 L × 0.50 USD = 50.00
      - Leche Búfala: 50 L × 1.00 USD = 50.00
    Precio ponderado = (50 + 50) / (100 + 50) = 100/150 ≈ 0.666667
    """
    hoy = date.today()
    # Creación directa de MovimientoInventario (inmutables, sin save() override para edición)
    MovimientoInventario.objects.create(
        producto=leche_vaca,
        tipo='ENTRADA',
        cantidad=Decimal('100.0000'),
        costo_unitario=Decimal('0.500000'),
        referencia='TEST-POND-1',
    )
    MovimientoInventario.objects.create(
        producto=leche_bufala,
        tipo='ENTRADA',
        cantidad=Decimal('50.0000'),
        costo_unitario=Decimal('1.000000'),
        referencia='TEST-POND-2',
    )

    resultado = calcular_precio_ponderado_leche()
    assert resultado['sin_datos'] is False
    # 100/150 = 0.666666...
    expected = (Decimal('100') / Decimal('150')).quantize(Decimal('0.000001'))
    assert resultado['precio'] == expected, (
        f"Precio ponderado esperado {expected}, obtenido {resultado['precio']}"
    )


@pytest.mark.django_db
def test_sin_entradas_7d_fallback(leche_vaca, leche_bufala):
    """
    Sin entradas en los últimos 7 días → sin_datos=True, usa costo_promedio del stock.
    leche_vaca: 100 L × 0.50 = 50; leche_bufala: 50 L × 1.00 = 50
    Promedio ponderado por stock = 100/150
    """
    # No creamos movimientos recientes
    resultado = calcular_precio_ponderado_leche()
    assert resultado['sin_datos'] is True
    assert resultado['precio'] is not None
    # costo_promedio ponderado por stock: (100*0.5 + 50*1.0) / (100+50)
    expected = (Decimal('100') / Decimal('150')).quantize(Decimal('0.000001'))
    assert resultado['precio'] == expected, (
        f"Fallback esperado {expected}, obtenido {resultado['precio']}"
    )


@pytest.mark.django_db
def test_formula_correcta(leche_vaca):
    """
    Verificación exacta con Decimal: Σ(costo×cantidad)/Σcantidad.
    Una sola entrada: 200L × 0.75 USD → precio = 0.750000.
    """
    MovimientoInventario.objects.create(
        producto=leche_vaca,
        tipo='ENTRADA',
        cantidad=Decimal('200.0000'),
        costo_unitario=Decimal('0.750000'),
        referencia='TEST-FORM-1',
    )

    resultado = calcular_precio_ponderado_leche()
    assert resultado['sin_datos'] is False
    assert resultado['precio'] == Decimal('0.750000'), (
        f"Precio esperado 0.750000, obtenido {resultado['precio']}"
    )
