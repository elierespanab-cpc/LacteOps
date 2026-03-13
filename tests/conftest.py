# -*- coding: utf-8 -*-
"""
conftest.py — Fixtures reutilizables para la suite LacteOps QA.

Todos los fixtures tienen scope='function' por defecto para garantizar
aislamiento total entre pruebas. Django usa transacciones que se
revertirán después de cada test gracias a pytest-django (@pytest.mark.django_db).
"""
import pytest
from decimal import Decimal
from datetime import date
from django.contrib.auth.models import User

from apps.almacen.models import UnidadMedida, Categoria, Producto
from apps.compras.models import Proveedor
from apps.ventas.models import Cliente
from apps.produccion.models import Receta, RecetaDetalle


# ─────────────────────────────────────────────────────────────────────────────
# Maestros de catálogo
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def unidad_kg(db):
    """
    UnidadMedida con símbolo 'kg' (kilogramo).
    Usa get_or_create porque la migración almacen.0002_initial_data
    puede haberla insertado ya en la base de datos de prueba.
    """
    unidad, _ = UnidadMedida.objects.get_or_create(
        simbolo='kg',
        defaults={'nombre': 'Kilogramo'},
    )
    return unidad


@pytest.fixture
def categoria_lacteos(db):
    """Categoría 'Lácteos' para agrupar productos."""
    categoria, _ = Categoria.objects.get_or_create(nombre='Lácteos')
    return categoria


# ─────────────────────────────────────────────────────────────────────────────
# Productos
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def producto_mp(db, unidad_kg, categoria_lacteos):
    """
    Producto de Materia Prima con stock=0 y costo_promedio=0.
    Unidad: kg. Listo para recibir entradas de inventario.
    """
    return Producto.objects.create(
        codigo='MP-001',
        nombre='Leche Cruda',
        categoria=categoria_lacteos,
        unidad_medida=unidad_kg,
        stock_actual=Decimal('0'),
        costo_promedio=Decimal('0'),
        es_materia_prima=True,
        es_producto_terminado=False,
    )


@pytest.fixture
def producto_pt(db, unidad_kg, categoria_lacteos):
    """
    Producto Terminado con stock=0 y costo_promedio=0.
    Unidad: kg. Listo para recibir entradas de producción.
    """
    return Producto.objects.create(
        codigo='PT-001',
        nombre='Queso Blanco',
        categoria=categoria_lacteos,
        unidad_medida=unidad_kg,
        stock_actual=Decimal('0'),
        costo_promedio=Decimal('0'),
        es_materia_prima=False,
        es_producto_terminado=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Terceros
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def usuario(db):
    """Usuario estándar para pruebas de auditoría y servicios."""
    return User.objects.create_user(username='tester_admin', password='password123', is_staff=True)


@pytest.fixture
def proveedor(db):
    """Proveedor básico para facturas de compra."""
    return Proveedor.objects.create(
        nombre='Hacienda La Sierra',
        rif='J-12345678-9',
    )


@pytest.fixture
def cliente(db):
    """Cliente con límite de crédito de 1.000,00 USD."""
    return Cliente.objects.create(
        nombre='Supermercado El Buen Precio',
        rif='J-98765432-1',
        limite_credito=Decimal('1000.00'),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Producción
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def receta(db, producto_mp, producto_pt, unidad_kg):
    """
    Receta que produce producto_pt a partir de producto_mp.
    RecetaDetalle: cantidad_base=10, unidad=kg.
    """
    # Sprint 2: Se removió producto_terminado del modelo Receta
    r = Receta.objects.create(
        nombre='Receta Queso Estándar',
        rendimiento_esperado=Decimal('80.00'),
    )
    RecetaDetalle.objects.create(
        receta=r,
        materia_prima=producto_mp,
        cantidad_base=Decimal('10.0000'),
        unidad_medida=unidad_kg,
    )
    return r
