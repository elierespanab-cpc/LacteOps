# -*- coding: utf-8 -*-
"""
test_notificaciones.py — Suite para el management command generar_notificaciones (Sprint 4).
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from django.core.management import call_command

from apps.almacen.models import UnidadMedida, Categoria, Producto
from apps.core.models import Notificacion, Secuencia, TasaCambio
from apps.ventas.models import Cliente, FacturaVenta


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def unidad_notif(db):
    unidad, _ = UnidadMedida.objects.get_or_create(simbolo='kg', defaults={'nombre': 'Kilogramo'})
    return unidad


@pytest.fixture
def cat_notif(db):
    cat, _ = Categoria.objects.get_or_create(nombre='NotifCat')
    return cat


@pytest.fixture
def producto_bajo_minimo(db, unidad_notif, cat_notif):
    """Producto con stock_actual < stock_minimo."""
    return Producto.objects.create(
        codigo='PN-001',
        nombre='Queso Bajo Stock',
        categoria=cat_notif,
        unidad_medida=unidad_notif,
        stock_actual=Decimal('5.0000'),
        stock_minimo=Decimal('20.0000'),
        activo=True,
    )


@pytest.fixture
def producto_stock_ok(db, unidad_notif, cat_notif):
    """Producto con stock_actual >= stock_minimo."""
    return Producto.objects.create(
        codigo='PN-002',
        nombre='Queso Stock OK',
        categoria=cat_notif,
        unidad_medida=unidad_notif,
        stock_actual=Decimal('50.0000'),
        stock_minimo=Decimal('20.0000'),
        activo=True,
    )


@pytest.fixture
def cliente_notif(db):
    return Cliente.objects.create(
        nombre='Cliente Notif',
        rif='J-40000001-0',
        limite_credito=Decimal('5000.00'),
        dias_credito=30,
    )


@pytest.fixture
def secuencia_vta_notif(db):
    seq, _ = Secuencia.objects.get_or_create(
        tipo_documento='VTA',
        defaults={'prefijo': 'VTA-', 'digitos': 4, 'ultimo_numero': 0},
    )
    return seq


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_stock_bajo_genera_notificacion(producto_bajo_minimo):
    """
    Un producto con stock < stock_minimo debe crear una Notificacion
    de tipo STOCK_MINIMO con activa=True.
    """
    call_command('generar_notificaciones')

    notif = Notificacion.objects.filter(
        tipo='STOCK_MINIMO',
        entidad='Producto',
        entidad_id=producto_bajo_minimo.pk,
    ).first()

    assert notif is not None, 'Debe existir notificación STOCK_MINIMO para producto bajo mínimo'
    assert notif.activa is True, 'La notificación debe estar activa'
    assert str(producto_bajo_minimo.nombre) in notif.titulo


@pytest.mark.django_db
def test_stock_repuesto_desactiva(producto_bajo_minimo):
    """
    Si el stock se recupera (>= stock_minimo), la notificación existente
    debe marcarse activa=False.
    """
    # Primera ejecución → crea notificación activa
    call_command('generar_notificaciones')
    notif = Notificacion.objects.get(
        tipo='STOCK_MINIMO', entidad='Producto', entidad_id=producto_bajo_minimo.pk
    )
    assert notif.activa is True

    # Reponer stock
    producto_bajo_minimo.stock_actual = Decimal('50.0000')
    producto_bajo_minimo.save(update_fields=['stock_actual'])

    # Segunda ejecución → debe desactivar
    call_command('generar_notificaciones')
    notif.refresh_from_db()
    assert notif.activa is False, 'La notificación debe desactivarse cuando el stock se recupera'


@pytest.mark.django_db
def test_update_or_create_sin_duplicar(producto_bajo_minimo):
    """
    Ejecutar generar_notificaciones dos veces no debe duplicar registros.
    Debe haber exactamente 1 Notificacion por (tipo, entidad, entidad_id).
    """
    call_command('generar_notificaciones')
    call_command('generar_notificaciones')

    count = Notificacion.objects.filter(
        tipo='STOCK_MINIMO',
        entidad='Producto',
        entidad_id=producto_bajo_minimo.pk,
    ).count()

    assert count == 1, f'Se esperaba 1 notificación, encontradas {count}'


@pytest.mark.django_db
def test_cxc_venciendo_7d(db, cliente_notif, secuencia_vta_notif):
    """
    Solo facturas con fecha_vencimiento en rango [hoy, hoy+7] deben
    generar notificación CXC_VENCIENDO.
    Factura vencida hace 5 días: NO debe generar notificación.
    Factura que vence en 3 días: SÍ debe generar notificación.
    """
    hoy = date.today()

    # Factura en rango (vence en 3 días)
    f_en_rango = FacturaVenta.objects.create(
        numero='VTA-NOTIF-01',
        cliente=cliente_notif,
        fecha=hoy - timedelta(days=27),
        fecha_vencimiento=hoy + timedelta(days=3),
        estado='EMITIDA',
        total=Decimal('100.00'),
    )

    # Factura fuera de rango (vence en 15 días)
    f_fuera_rango = FacturaVenta.objects.create(
        numero='VTA-NOTIF-02',
        cliente=cliente_notif,
        fecha=hoy - timedelta(days=5),
        fecha_vencimiento=hoy + timedelta(days=15),
        estado='EMITIDA',
        total=Decimal('200.00'),
    )

    call_command('generar_notificaciones')

    # En rango → notificación creada
    notif_en = Notificacion.objects.filter(
        tipo='CXC_VENCIENDO', entidad='FacturaVenta', entidad_id=f_en_rango.pk
    ).first()
    assert notif_en is not None, 'Debe generarse notificación para factura en rango 7d'

    # Fuera de rango → NO notificación
    notif_fuera = Notificacion.objects.filter(
        tipo='CXC_VENCIENDO', entidad='FacturaVenta', entidad_id=f_fuera_rango.pk
    ).first()
    assert notif_fuera is None, 'No debe generarse notificación para factura fuera del rango 7d'
