# -*- coding: utf-8 -*-
"""
test_produccion.py — Suite de pruebas para el módulo de Producción.

Actualizado para Sprint 2: el modelo Receta ya no tiene el campo
`producto_terminado`. Los productos que produce una OP se modelan con
SalidaOrden(es_subproducto=False). Los tests reflejan el nuevo contrato.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.almacen.models import MovimientoInventario
from apps.almacen.services import registrar_entrada
from apps.core.exceptions import EstadoInvalidoError, StockInsuficienteError
from apps.core.models import AuditLog
from apps.produccion.models import (
    OrdenProduccion, ConsumoOP, Receta, RecetaDetalle, SalidaOrden,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _dar_stock(producto, cantidad, costo_unitario, referencia='INICIAL'):
    """Inyecta stock real vía Kardex."""
    registrar_entrada(
        producto=producto,
        cantidad=Decimal(str(cantidad)),
        costo_unitario=Decimal(str(costo_unitario)),
        referencia=referencia,
    )
    producto.refresh_from_db()


def _crear_op(receta, numero='PRO-0001'):
    """Crea una OrdenProduccion en estado ABIERTA."""
    return OrdenProduccion.objects.create(numero=numero, receta=receta)


def _agregar_salida_principal(op, producto, cantidad='80', precio_referencia='5.00'):
    """Agrega una SalidaOrden de producto principal (no subproducto)."""
    return SalidaOrden.objects.create(
        orden=op,
        producto=producto,
        cantidad=Decimal(cantidad),
        precio_referencia=Decimal(precio_referencia),
        es_subproducto=False,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Pre-carga de consumos al crear la OP
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_orden_precarga_consumos(receta, producto_mp):
    """
    Al crear una OrdenProduccion, cargar_consumos_desde_receta() debe
    crear automáticamente 1 ConsumoOP por cada detalle de la receta.
    """
    op = _crear_op(receta)

    consumos = ConsumoOP.objects.filter(orden=op)
    assert consumos.count() == 1

    consumo = consumos.first()
    assert consumo.producto == producto_mp
    assert consumo.cantidad_consumida == Decimal('10.0000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Flujo completo de cierre
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cierre_op_flujo_completo(receta, producto_mp, producto_pt):
    """
    Stock MP=100, costo_promedio=10.
    OP produce 80 unidades de PT consumiendo 10 de MP.
    Se registra la SalidaOrden del PT antes de cerrar.

    Verificaciones:
      - producto_mp.stock_actual == 90
      - producto_pt.stock_actual == 80
      - op.costo_total == Decimal('100.00')  (10 unidades x $10)
      - producto_pt.costo_promedio == Decimal('1.250000')  (100/80)
      - op.estado == 'CERRADA'
      - op.fecha_cierre == date.today()
    """
    _dar_stock(producto_mp, cantidad=100, costo_unitario='10.00')

    op = _crear_op(receta)
    _agregar_salida_principal(op, producto_pt, cantidad='80', precio_referencia='5.00')
    op.cerrar()

    op.refresh_from_db()
    producto_mp.refresh_from_db()
    producto_pt.refresh_from_db()

    assert producto_mp.stock_actual == Decimal('90')
    assert producto_pt.stock_actual == Decimal('80')
    assert op.costo_total == Decimal('100.00')
    assert producto_pt.costo_promedio == Decimal('1.250000')
    assert op.estado == 'CERRADA'
    assert op.fecha_cierre == date.today()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Cierre bloqueado por stock insuficiente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cierre_op_stock_insuficiente(receta, producto_mp, producto_pt):
    """
    Stock de MP=5, ConsumoOP requiere 10.
    cerrar() debe lanzar StockInsuficienteError y no crear movimientos.
    """
    _dar_stock(producto_mp, cantidad=5, costo_unitario='10.00')

    op = _crear_op(receta)
    _agregar_salida_principal(op, producto_pt)

    with pytest.raises(StockInsuficienteError):
        op.cerrar()

    producto_mp.refresh_from_db()
    op.refresh_from_db()

    assert producto_mp.stock_actual == Decimal('5')
    assert op.estado == 'ABIERTA'

    # No debe existir ningún movimiento de salida relacionado con la OP
    assert MovimientoInventario.objects.filter(referencia=op.numero).count() == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Atomicidad del cierre: rollback total con 2 consumos
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cierre_op_atomico(categoria_lacteos, unidad_kg, producto_pt):
    """
    OP con 2 consumos: MP1 con stock suficiente, MP2 sin stock.
    El cierre debe fallar por MP2 y MP1 NO debe haber sido descontado.
    """
    from apps.almacen.models import Producto

    mp1 = Producto.objects.create(
        codigo='MP-A01', nombre='Materia Prima A',
        categoria=categoria_lacteos, unidad_medida=unidad_kg,
        stock_actual=Decimal('50'), costo_promedio=Decimal('5.000000'),
        es_materia_prima=True,
    )
    mp2 = Producto.objects.create(
        codigo='MP-B01', nombre='Materia Prima B',
        categoria=categoria_lacteos, unidad_medida=unidad_kg,
        stock_actual=Decimal('2'),  # insuficiente para el consumo de 10
        costo_promedio=Decimal('8.000000'),
        es_materia_prima=True,
    )

    # Sprint 2: Receta sin producto_terminado directo
    receta_doble = Receta.objects.create(
        nombre='Receta Doble',
        rendimiento_esperado=Decimal('90.00'),
    )
    RecetaDetalle.objects.create(
        receta=receta_doble, materia_prima=mp1,
        cantidad_base=Decimal('10.0000'), unidad_medida=unidad_kg,
    )
    RecetaDetalle.objects.create(
        receta=receta_doble, materia_prima=mp2,
        cantidad_base=Decimal('10.0000'), unidad_medida=unidad_kg,
    )

    op = OrdenProduccion.objects.create(
        numero='PRO-ATOM',
        receta=receta_doble,
    )
    # Registrar salida principal antes de cerrar
    SalidaOrden.objects.create(
        orden=op, producto=producto_pt,
        cantidad=Decimal('80'), precio_referencia=Decimal('5.00'),
        es_subproducto=False,
    )

    with pytest.raises(StockInsuficienteError):
        op.cerrar()

    # MP1 NO debe haber sido descontado (rollback total)
    mp1.refresh_from_db()
    mp2.refresh_from_db()
    op.refresh_from_db()

    assert mp1.stock_actual == Decimal('50'), "MP1 fue descontado pese al rollback"
    assert mp2.stock_actual == Decimal('2'),  "MP2 no debería haber cambiado"
    assert op.estado == 'ABIERTA'
    assert MovimientoInventario.objects.filter(referencia='PRO-ATOM').count() == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Anular OP abierta
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_anular_op_abierta(receta, producto_mp):
    """
    Una OP en ABIERTA puede anularse. No debe generarse movimiento.
    """
    op = _crear_op(receta)

    op.anular()
    op.refresh_from_db()

    assert op.estado == 'ANULADA'
    assert MovimientoInventario.objects.filter(referencia=op.numero).count() == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — Bloqueo de anulación en OP cerrada
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_anular_op_cerrada_bloqueado(receta, producto_mp, producto_pt):
    """
    Una OP CERRADA no puede anularse directamente.
    Debe lanzar EstadoInvalidoError.
    """
    _dar_stock(producto_mp, cantidad=100, costo_unitario='10.00')

    op = _crear_op(receta)
    _agregar_salida_principal(op, producto_pt, cantidad='80')
    op.cerrar()
    op.refresh_from_db()
    assert op.estado == 'CERRADA'

    with pytest.raises(EstadoInvalidoError):
        op.anular()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — AuditLog registra cambio de estado al cerrar
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_auditlog_registra_cambio_estado(receta, producto_mp, producto_pt):
    """
    Tras cerrar una OP exitosamente debe existir al menos 1 registro
    de AuditLog con entidad='OrdenProduccion' y accion='MODIFICAR'.
    """
    _dar_stock(producto_mp, cantidad=100, costo_unitario='10.00')

    op = _crear_op(receta)
    _agregar_salida_principal(op, producto_pt, cantidad='80')
    op.cerrar()

    registros = AuditLog.objects.filter(
        entidad='OrdenProduccion',
        accion='MODIFICAR',
        entidad_id=op.pk,
    )
    assert registros.count() >= 1, (
        "Se esperaba al menos 1 AuditLog MODIFICAR para OrdenProduccion "
        f"id={op.pk}, pero se encontraron {registros.count()}."
    )
