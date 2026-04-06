# -*- coding: utf-8 -*-
"""
test_sprint6_nota_credito.py — Cobertura QA Sprint 6 para NotaCredito.

Cubre:
  - Numeración automática NTC-XXXX
  - emitir() repone inventario (ENTRADA Kardex)
  - emitir() rebaja saldo pendiente de la factura
  - Validación: cantidad excede lo facturado → StockInsuficienteError
  - Validación: NC contra factura en BORRADOR → EstadoInvalidoError
  - NC en BORRADOR no genera MovimientoInventario

REGLA: todas las aserciones numéricas usan Decimal exacto, NUNCA float.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.almacen.models import MovimientoInventario
from apps.almacen.services import registrar_entrada
from apps.ventas.models import (
    FacturaVenta, DetalleFacturaVenta,
    NotaCredito, DetalleNotaCredito,
    ListaPrecio, DetalleLista,
)
from apps.core.exceptions import EstadoInvalidoError, StockInsuficienteError
from apps.core.models import Secuencia


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dar_stock(producto, cantidad, costo_unitario='5.00', referencia='INIT'):
    registrar_entrada(
        producto=producto,
        cantidad=Decimal(str(cantidad)),
        costo_unitario=Decimal(costo_unitario),
        referencia=referencia,
    )
    producto.refresh_from_db()


def _crear_lista_aprobada(producto, precio='10.00'):
    lista = ListaPrecio.objects.create(nombre='Lista NC Test', activa=True)
    DetalleLista.objects.create(
        lista=lista,
        producto=producto,
        precio=Decimal(precio),
        vigente_desde=date.today(),
        aprobado=True,
    )
    return lista


def _crear_factura_emitida(cliente, producto, cantidad, lista):
    """Crea FacturaVenta en estado EMITIDA (sin llamar emitir() para no descontar stock)."""
    factura = FacturaVenta.objects.create(
        cliente=cliente,
        fecha=date.today(),
        estado='EMITIDA',
        lista_precio=lista,
    )
    DetalleFacturaVenta.objects.create(
        factura=factura,
        producto=producto,
        cantidad=Decimal(str(cantidad)),
        precio_unitario=Decimal('10.000000'),
    )
    factura.refresh_from_db()
    return factura


def _crear_nc_borrador(factura, producto, cantidad, precio='10.000000'):
    # Asegurar secuencia NTC
    Secuencia.objects.get_or_create(
        tipo_documento='NTC',
        defaults={'ultimo_numero': 0, 'prefijo': 'NTC-', 'digitos': 4},
    )
    nc = NotaCredito.objects.create(
        factura_origen=factura,
        fecha=date.today(),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
    )
    DetalleNotaCredito.objects.create(
        nota_credito=nc,
        producto=producto,
        cantidad=Decimal(str(cantidad)),
        precio_unitario=Decimal(precio),
    )
    nc.refresh_from_db()
    return nc


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: secuencia NTC garantizada
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def secuencia_ntc(db):
    seq, _ = Secuencia.objects.get_or_create(
        tipo_documento='NTC',
        defaults={'ultimo_numero': 0, 'prefijo': 'NTC-', 'digitos': 4},
    )
    seq.ultimo_numero = 0
    seq.prefijo = 'NTC-'
    seq.digitos = 4
    seq.save()
    return seq


# ═══════════════════════════════════════════════════════════════════════════════
# test_nc_numero_serie_NTC
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_nc_numero_serie_NTC(cliente, producto_pt):
    """NC creada automáticamente debe tener prefijo NTC-."""
    lista = _crear_lista_aprobada(producto_pt)
    factura = _crear_factura_emitida(cliente, producto_pt, 10, lista)

    nc = NotaCredito.objects.create(
        factura_origen=factura,
        fecha=date.today(),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
    )
    assert nc.numero.startswith('NTC-'), f"Número inesperado: {nc.numero}"


# ═══════════════════════════════════════════════════════════════════════════════
# test_nc_emitir_repone_inventario
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_nc_emitir_repone_inventario(cliente, producto_pt):
    """
    Flujo completo: factura emitida baja stock, NC emitida lo repone.
    """
    _dar_stock(producto_pt, 20, '5.00', 'INIT-NC')
    lista = _crear_lista_aprobada(producto_pt, '10.00')

    # Stock antes de factura
    producto_pt.refresh_from_db()
    stock_inicial = producto_pt.stock_actual  # 20

    # Crear factura emitida con 10 unidades (simula ya descontadas)
    factura = _crear_factura_emitida(cliente, producto_pt, 10, lista)
    # Descontar manualmente el stock (como lo haría emitir())
    from apps.almacen.services import registrar_salida
    registrar_salida(producto_pt, Decimal('10'), referencia=factura.numero)
    producto_pt.refresh_from_db()
    stock_tras_venta = producto_pt.stock_actual  # 10

    nc = _crear_nc_borrador(factura, producto_pt, 10)
    nc.emitir()

    producto_pt.refresh_from_db()
    assert producto_pt.stock_actual == stock_inicial, (
        f"Se esperaba stock={stock_inicial}, obtenido={producto_pt.stock_actual}"
    )

    mov = MovimientoInventario.objects.filter(
        referencia=nc.numero, tipo='ENTRADA'
    ).first()
    assert mov is not None, "No se registró ENTRADA en Kardex al emitir NC"
    assert mov.cantidad == Decimal('10.0000')


# ═══════════════════════════════════════════════════════════════════════════════
# test_nc_emitir_rebaja_saldo_factura
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_nc_emitir_rebaja_saldo_factura(cliente, producto_pt):
    """
    Factura total=1000. NC por 200. Saldo pendiente debe quedar en 800.
    """
    _dar_stock(producto_pt, 100, '5.00', 'INIT-SALDO')
    lista = _crear_lista_aprobada(producto_pt, '100.00')

    factura = _crear_factura_emitida(cliente, producto_pt, 10, lista)
    # Ajustar precio_unitario del detalle para que total = 1000
    detalle = factura.detalles.first()
    detalle.precio_unitario = Decimal('100.000000')
    detalle.save()
    factura.refresh_from_db()
    assert factura.total == Decimal('1000.00')

    # NC por 2 unidades a 100 = 200
    nc = _crear_nc_borrador(factura, producto_pt, 2, precio='100.000000')
    nc.emitir()

    saldo = factura.get_saldo_pendiente()
    assert saldo == Decimal('800.00'), f"Saldo esperado 800.00, obtenido {saldo}"


# ═══════════════════════════════════════════════════════════════════════════════
# test_nc_cantidad_excede_facturado_error
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_nc_cantidad_excede_facturado_error(cliente, producto_pt):
    """
    Factura con 10 unidades. NC por 15 unidades → StockInsuficienteError.
    """
    _dar_stock(producto_pt, 50, '5.00', 'INIT-EXCEDE')
    lista = _crear_lista_aprobada(producto_pt, '10.00')
    factura = _crear_factura_emitida(cliente, producto_pt, 10, lista)

    nc = _crear_nc_borrador(factura, producto_pt, 15)

    with pytest.raises(StockInsuficienteError):
        nc.emitir()


# ═══════════════════════════════════════════════════════════════════════════════
# test_nc_solo_contra_factura_emitida_o_cobrada
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_nc_solo_contra_factura_emitida_o_cobrada(cliente, producto_pt):
    """
    NC contra factura en estado ANULADA debe lanzar EstadoInvalidoError.
    """
    _dar_stock(producto_pt, 10, '5.00', 'INIT-ESTADO')
    lista = _crear_lista_aprobada(producto_pt, '10.00')

    # Crear factura en estado ANULADA directamente
    factura = FacturaVenta.objects.create(
        cliente=cliente,
        fecha=date.today(),
        estado='ANULADA',
        lista_precio=lista,
    )
    DetalleFacturaVenta.objects.create(
        factura=factura,
        producto=producto_pt,
        cantidad=Decimal('5.0000'),
        precio_unitario=Decimal('10.000000'),
    )
    factura.refresh_from_db()

    nc = _crear_nc_borrador(factura, producto_pt, 5)

    with pytest.raises(EstadoInvalidoError):
        nc.emitir()


# ═══════════════════════════════════════════════════════════════════════════════
# test_nc_borrador_no_genera_movimiento
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_nc_borrador_no_genera_movimiento(cliente, producto_pt):
    """
    NC en BORRADOR no debe generar ningún MovimientoInventario con su número.
    """
    _dar_stock(producto_pt, 20, '5.00', 'INIT-BDRDR')
    lista = _crear_lista_aprobada(producto_pt, '10.00')
    factura = _crear_factura_emitida(cliente, producto_pt, 10, lista)

    nc = _crear_nc_borrador(factura, producto_pt, 5)

    assert nc.estado == 'BORRADOR'
    count = MovimientoInventario.objects.filter(referencia=nc.numero).count()
    assert count == 0, f"NC en BORRADOR generó {count} movimientos inesperados"
