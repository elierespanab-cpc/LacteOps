# -*- coding: utf-8 -*-
"""
test_fecha_venta_config.py — ConfiguracionEmpresa.fecha_venta_abierta en emitir() (Sprint 5 C2).

Cubre:
  - fecha_venta_abierta=False → emitir() sobreescribe fecha con date.today().
  - fecha_venta_abierta=True  → emitir() respeta la fecha asignada previamente.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.core.models import ConfiguracionEmpresa
from apps.almacen.services import registrar_entrada
from apps.ventas.models import FacturaVenta, DetalleFacturaVenta, ListaPrecio, DetalleLista


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

FECHA_PASADA = date(2020, 1, 15)


def _crear_config(fecha_venta_abierta: bool):
    """Crea (o actualiza) el singleton ConfiguracionEmpresa."""
    ConfiguracionEmpresa.objects.update_or_create(
        pk=1,
        defaults=dict(
            nombre_empresa='LacteOps Test',
            rif='J-00000000-0',
            direccion='Caracas',
            telefono='0212-0000000',
            fecha_venta_abierta=fecha_venta_abierta,
        ),
    )


def _dar_stock(producto, cantidad, costo_unitario, referencia='INICIAL'):
    registrar_entrada(
        producto=producto,
        cantidad=Decimal(str(cantidad)),
        costo_unitario=Decimal(str(costo_unitario)),
        referencia=referencia,
    )
    producto.refresh_from_db()


def _crear_lista_aprobada(producto, precio='10.00'):
    lista = ListaPrecio.objects.create(nombre='Lista Fecha Test', activa=True)
    DetalleLista.objects.create(
        lista=lista,
        producto=producto,
        precio=Decimal(precio),
        vigente_desde=date(2000, 1, 1),  # muy anterior — siempre vigente
        aprobado=True,
    )
    return lista


def _crear_factura_con_fecha(cliente, producto, lista, fecha, numero='VTA-FECHA-001'):
    factura = FacturaVenta.objects.create(
        numero=numero,
        cliente=cliente,
        fecha=fecha,
        estado='EMITIDA',
        moneda='USD',
        lista_precio=lista,
    )
    DetalleFacturaVenta.objects.create(
        factura=factura,
        producto=producto,
        cantidad=Decimal('1'),
        precio_unitario=Decimal('0'),
    )
    factura.refresh_from_db()
    return factura


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — fecha_venta_abierta=False: emitir() sobreescribe fecha con date.today()
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_fecha_fija_al_emitir_si_config_false(cliente, producto_pt):
    """
    Con fecha_venta_abierta=False, la fecha de la factura se ignora y
    emitir() la fuerza a date.today() (fecha del sistema operativo).
    """
    _dar_stock(producto_pt, cantidad=10, costo_unitario='5.00')
    lista = _crear_lista_aprobada(producto_pt)
    _crear_config(fecha_venta_abierta=False)

    factura = _crear_factura_con_fecha(cliente, producto_pt, lista,
                                       fecha=FECHA_PASADA, numero='VTA-FECHA-001')
    assert factura.fecha == FECHA_PASADA  # antes de emitir, la fecha es la ingresada

    factura.emitir()
    factura.refresh_from_db()

    assert factura.fecha == date.today(), (
        f"emitir() debió sobreescribir la fecha con {date.today()}, "
        f"pero quedó en {factura.fecha}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — fecha_venta_abierta=True: emitir() respeta la fecha asignada
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_fecha_respetada_si_config_true(cliente, producto_pt):
    """
    Con fecha_venta_abierta=True, emitir() no modifica la fecha de la factura;
    respeta la fecha ingresada manualmente por el usuario.
    """
    _dar_stock(producto_pt, cantidad=10, costo_unitario='5.00')
    lista = _crear_lista_aprobada(producto_pt)
    _crear_config(fecha_venta_abierta=True)

    factura = _crear_factura_con_fecha(cliente, producto_pt, lista,
                                       fecha=FECHA_PASADA, numero='VTA-FECHA-002')

    factura.emitir()
    factura.refresh_from_db()

    assert factura.fecha == FECHA_PASADA, (
        f"emitir() no debió modificar la fecha; esperado {FECHA_PASADA}, "
        f"obtenido {factura.fecha}"
    )
