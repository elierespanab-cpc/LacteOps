# -*- coding: utf-8 -*-
"""
test_sprint6_produccion.py — Cobertura QA Sprint 6 para OrdenProduccion.

Cubre:
  - fecha_apertura se asigna automáticamente al crear la OP (fix B6-14)
  - fecha_cierre se asigna al cerrar la OP

REGLA: todas las aserciones numéricas usan Decimal exacto, NUNCA float.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.almacen.models import Producto, Categoria, UnidadMedida
from apps.almacen.services import registrar_entrada
from apps.produccion.models import OrdenProduccion, Receta, RecetaDetalle, SalidaOrden
from apps.core.models import Secuencia


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def secuencia_pro(db):
    seq, _ = Secuencia.objects.get_or_create(
        tipo_documento='PRO',
        defaults={'ultimo_numero': 0, 'prefijo': 'PRO-', 'digitos': 4},
    )
    seq.ultimo_numero = 0
    seq.save(update_fields=['ultimo_numero'])
    return seq


@pytest.fixture
def unidad_kg(db):
    u, _ = UnidadMedida.objects.get_or_create(simbolo='kg', defaults={'nombre': 'Kilogramo'})
    return u


@pytest.fixture
def categoria_mp(db):
    cat, _ = Categoria.objects.get_or_create(nombre='MP Produccion Test')
    return cat


@pytest.fixture
def categoria_pt(db):
    cat, _ = Categoria.objects.get_or_create(nombre='PT Produccion Test')
    return cat


@pytest.fixture
def mp(db, unidad_kg, categoria_mp):
    return Producto.objects.create(
        codigo='MP-PROD-T01',
        nombre='Leche Cruda Prd T',
        categoria=categoria_mp,
        unidad_medida=unidad_kg,
        stock_actual=Decimal('100'),
        costo_promedio=Decimal('0.50'),
        es_materia_prima=True,
        es_producto_terminado=False,
    )


@pytest.fixture
def pt(db, unidad_kg, categoria_pt):
    return Producto.objects.create(
        codigo='PT-PROD-T01',
        nombre='Queso Blanco Prd T',
        categoria=categoria_pt,
        unidad_medida=unidad_kg,
        stock_actual=Decimal('0'),
        costo_promedio=Decimal('0'),
        es_materia_prima=False,
        es_producto_terminado=True,
    )


@pytest.fixture
def receta_simple(db, mp, pt, unidad_kg):
    receta = Receta.objects.create(
        nombre='Receta Prod Tests',
        rendimiento_esperado=Decimal('80.00'),
    )
    RecetaDetalle.objects.create(
        receta=receta,
        materia_prima=mp,
        cantidad_base=Decimal('10.0000'),
        unidad_medida=unidad_kg,
    )
    return receta


def _crear_op(receta):
    """Crea una OrdenProduccion abierta."""
    return OrdenProduccion.objects.create(receta=receta)


# ═══════════════════════════════════════════════════════════════════════════════
# test_op_fecha_apertura_visible
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_op_fecha_apertura_visible(receta_simple):
    """
    Al crear una OP, fecha_apertura debe tener el valor de hoy.
    Fix B6-14: cambiado auto_now_add=True → default=date.today, editable=False.
    """
    op = _crear_op(receta_simple)
    assert op.fecha_apertura is not None, "fecha_apertura no debe ser None al crear la OP"
    assert op.fecha_apertura == date.today(), (
        f"fecha_apertura esperada {date.today()}, obtenida {op.fecha_apertura}"
    )


@pytest.mark.django_db
def test_op_fecha_apertura_persiste_en_bd(receta_simple):
    """
    fecha_apertura debe persistir correctamente en la BD (no solo en memoria).
    """
    op = _crear_op(receta_simple)
    op_reloaded = OrdenProduccion.objects.get(pk=op.pk)
    assert op_reloaded.fecha_apertura == date.today()


# ═══════════════════════════════════════════════════════════════════════════════
# test_op_fecha_cierre_al_cerrar
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_op_fecha_cierre_al_cerrar(receta_simple, mp, pt):
    """
    Al cerrar una OP, fecha_cierre debe asignarse automáticamente como date.today().
    """
    # Asegurar stock suficiente de la MP
    mp.stock_actual = Decimal('100')
    mp.costo_promedio = Decimal('0.50')
    mp.save(update_fields=['stock_actual', 'costo_promedio'])

    op = _crear_op(receta_simple)

    # La OP necesita al menos una SalidaOrden (producto terminado) para cerrar
    SalidaOrden.objects.create(
        orden=op,
        producto=pt,
        cantidad=Decimal('8.0000'),
        precio_referencia=Decimal('5.00'),
        es_subproducto=False,
    )

    assert op.fecha_cierre is None, "fecha_cierre debe ser None antes de cerrar"

    op.cerrar()
    op.refresh_from_db()

    assert op.fecha_cierre is not None, "fecha_cierre no debe ser None después de cerrar"
    assert op.fecha_cierre == date.today(), (
        f"fecha_cierre esperada {date.today()}, obtenida {op.fecha_cierre}"
    )
    assert op.estado == 'CERRADA'


@pytest.mark.django_db
def test_op_fecha_cierre_none_antes_de_cerrar(receta_simple):
    """
    Una OP recién creada debe tener fecha_cierre = None.
    """
    op = _crear_op(receta_simple)
    assert op.fecha_cierre is None
