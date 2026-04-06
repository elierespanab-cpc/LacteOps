# -*- coding: utf-8 -*-
"""
test_sprint6_ajuste_costo.py — Cobertura QA Sprint 6 para ajustar_costo_producto().

Cubre:
  - Ajustar costo cambia costo_promedio correctamente
  - Ajuste genera MovimientoInventario con cantidad=0 y referencia AJC-
  - El movimiento tiene notas que incluyen 'Ajuste costo'
  - El ajuste NO afecta stock_actual

REGLA: todas las aserciones numéricas usan Decimal exacto, NUNCA float.
Referencia: apps/almacen/services.py — ajustar_costo_producto()
            Sección 2.22 reglas-globales.
"""
import pytest
from decimal import Decimal

from django.contrib.auth.models import User

from apps.almacen.models import Producto, Categoria, UnidadMedida, MovimientoInventario
from apps.almacen.services import ajustar_costo_producto, registrar_entrada


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def unidad(db):
    u, _ = UnidadMedida.objects.get_or_create(simbolo='kg', defaults={'nombre': 'Kilogramo'})
    return u


@pytest.fixture
def categoria(db):
    cat, _ = Categoria.objects.get_or_create(nombre='Cat Ajuste Test')
    return cat


@pytest.fixture
def producto_ajuste(db, unidad, categoria):
    """Producto con stock=100 y costo_promedio=10 para tests de ajuste de costo."""
    return Producto.objects.create(
        codigo='AJC-TEST-01',
        nombre='Queso Ajuste Costo',
        categoria=categoria,
        unidad_medida=unidad,
        stock_actual=Decimal('100'),
        costo_promedio=Decimal('10.000000'),
        es_producto_terminado=True,
    )


@pytest.fixture
def usuario_admin(db):
    """Usuario administrador para ejecutar el ajuste de costo."""
    return User.objects.create_user(
        username='admin_ajuste',
        password='pass123',
        is_staff=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# test_ajustar_costo_cambia_promedio
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_ajustar_costo_cambia_promedio(producto_ajuste, usuario_admin):
    """
    Producto con costo_promedio=10. Ajustar a 15.
    Después del ajuste, costo_promedio debe ser exactamente 15.000000.
    """
    assert producto_ajuste.costo_promedio == Decimal('10.000000')

    ajustar_costo_producto(
        producto=producto_ajuste,
        nuevo_costo=Decimal('15.000000'),
        motivo='Corrección precio mercado',
        usuario=usuario_admin,
    )

    producto_ajuste.refresh_from_db()
    assert producto_ajuste.costo_promedio == Decimal('15.000000'), (
        f"costo_promedio esperado 15.000000, obtenido {producto_ajuste.costo_promedio}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# test_ajustar_costo_genera_movimiento
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_ajustar_costo_genera_movimiento(producto_ajuste, usuario_admin):
    """
    El ajuste de costo debe generar un MovimientoInventario con:
      - referencia que empieza con 'AJC-'
      - cantidad == 0 (ajuste puro, no entrada física)
      - notas que contienen 'Ajuste costo'
    """
    ajustar_costo_producto(
        producto=producto_ajuste,
        nuevo_costo=Decimal('12.500000'),
        motivo='Ajuste por auditoria',
        usuario=usuario_admin,
    )

    mov = MovimientoInventario.objects.filter(
        producto=producto_ajuste,
        referencia__startswith='AJC-',
    ).last()

    assert mov is not None, "No se generó MovimientoInventario con prefijo AJC-"
    assert mov.cantidad == Decimal('0'), (
        f"Cantidad esperada 0 (ajuste puro), obtenida {mov.cantidad}"
    )
    assert 'Ajuste costo' in mov.notas, (
        f"Las notas del movimiento no contienen 'Ajuste costo': '{mov.notas}'"
    )


@pytest.mark.django_db
def test_ajustar_costo_referencia_incluye_codigo(producto_ajuste, usuario_admin):
    """
    La referencia del MovimientoInventario debe ser 'AJC-{codigo_producto}'.
    """
    ajustar_costo_producto(
        producto=producto_ajuste,
        nuevo_costo=Decimal('11.000000'),
        motivo='Test referencia',
        usuario=usuario_admin,
    )

    ref_esperada = f'AJC-{producto_ajuste.codigo}'
    mov = MovimientoInventario.objects.filter(
        producto=producto_ajuste,
        referencia=ref_esperada,
    ).last()

    assert mov is not None, (
        f"No se encontró movimiento con referencia '{ref_esperada}'"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# test_ajustar_costo_no_afecta_stock
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_ajustar_costo_no_afecta_stock(producto_ajuste, usuario_admin):
    """
    Ajustar el costo NO debe modificar stock_actual.
    El producto tiene stock=100 antes y debe seguir con 100 después.
    """
    stock_antes = producto_ajuste.stock_actual
    assert stock_antes == Decimal('100'), f"Stock inicial esperado 100, obtenido {stock_antes}"

    ajustar_costo_producto(
        producto=producto_ajuste,
        nuevo_costo=Decimal('20.000000'),
        motivo='Sin impacto en stock',
        usuario=usuario_admin,
    )

    producto_ajuste.refresh_from_db()
    assert producto_ajuste.stock_actual == Decimal('100'), (
        f"El stock fue modificado inesperadamente: {producto_ajuste.stock_actual}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests adicionales de robustez
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_ajustar_costo_a_cero_permitido(producto_ajuste, usuario_admin):
    """
    Ajustar el costo a 0.000000 es válido (p.ej. para mercancías donadas).
    """
    ajustar_costo_producto(
        producto=producto_ajuste,
        nuevo_costo=Decimal('0.000000'),
        motivo='Donación recibida',
        usuario=usuario_admin,
    )
    producto_ajuste.refresh_from_db()
    assert producto_ajuste.costo_promedio == Decimal('0.000000')


@pytest.mark.django_db
def test_ajustar_costo_multiples_veces(producto_ajuste, usuario_admin):
    """
    Múltiples ajustes deben generar múltiples movimientos AJC-.
    El último costo_promedio debe ser el del último ajuste.
    """
    ajustar_costo_producto(
        producto=producto_ajuste,
        nuevo_costo=Decimal('11.000000'),
        motivo='Ajuste 1',
        usuario=usuario_admin,
    )
    ajustar_costo_producto(
        producto=producto_ajuste,
        nuevo_costo=Decimal('13.000000'),
        motivo='Ajuste 2',
        usuario=usuario_admin,
    )
    ajustar_costo_producto(
        producto=producto_ajuste,
        nuevo_costo=Decimal('17.000000'),
        motivo='Ajuste 3',
        usuario=usuario_admin,
    )

    producto_ajuste.refresh_from_db()
    assert producto_ajuste.costo_promedio == Decimal('17.000000')

    count_ajustes = MovimientoInventario.objects.filter(
        producto=producto_ajuste,
        referencia__startswith='AJC-',
    ).count()
    assert count_ajustes == 3, f"Se esperaban 3 movimientos AJC-, obtenidos {count_ajustes}"
