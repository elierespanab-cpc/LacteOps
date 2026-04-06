# -*- coding: utf-8 -*-
"""
Tests Sprint 7 — Corrección de Bugs Post-Sprint 6
"""
import pytest
from decimal import Decimal
from datetime import date

from django.contrib.auth.models import User

from apps.almacen.models import UnidadMedida, Categoria, Producto
from apps.ventas.models import FacturaVenta, Cliente, ListaPrecio, DetalleLista, DetalleFacturaVenta
from apps.core.exceptions import EstadoInvalidoError
from apps.socios.models import Socio, PrestamoPorSocio


# ─────────────────────────────────────────────────────────────────────────────
# B7-01: Estado BORRADOR en FacturaVenta
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_factura_nueva_inicia_borrador():
    """Nueva factura debe iniciar en BORRADOR."""
    cliente = Cliente.objects.create(nombre='Test', rif='J-00000001-0')
    factura = FacturaVenta(
        cliente=cliente,
        fecha=date.today(),
        moneda='USD',
        tasa_cambio=Decimal('1.0'),
    )
    assert factura.estado == 'BORRADOR'


@pytest.mark.django_db
def test_factura_borrador_no_emitible_si_ya_emitida():
    """emitir() en estado ANULADA debe lanzar EstadoInvalidoError."""
    cliente = Cliente.objects.create(nombre='Test2', rif='J-00000002-0')
    lista = ListaPrecio.objects.create(nombre='L1')
    factura = FacturaVenta.objects.create(
        cliente=cliente,
        fecha=date.today(),
        moneda='USD',
        tasa_cambio=Decimal('1.0'),
        estado='ANULADA',
        lista_precio=lista,
        numero='VTA-TEST-9999',
    )
    with pytest.raises(EstadoInvalidoError):
        factura.emitir()


@pytest.mark.django_db
def test_factura_borrador_choices_incluye_borrador():
    """ESTADO_CHOICES debe incluir BORRADOR."""
    choices_values = [c[0] for c in FacturaVenta.ESTADO_CHOICES]
    assert 'BORRADOR' in choices_values


@pytest.mark.django_db
def test_factura_default_estado_es_borrador():
    """El valor por defecto del campo estado debe ser BORRADOR."""
    field = FacturaVenta._meta.get_field('estado')
    assert field.default == 'BORRADOR'


# ─────────────────────────────────────────────────────────────────────────────
# B7-03: Socios — métodos get_monto_pagado y get_saldo_neto
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_prestamo_get_monto_pagado_sin_pagos():
    """PrestamoPorSocio.get_monto_pagado() retorna 0 si no hay pagos."""
    socio = Socio.objects.create(nombre='Socio Test', rif='V-12345678-9')
    prestamo = PrestamoPorSocio.objects.create(
        socio=socio,
        monto_principal=Decimal('1000.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        monto_usd=Decimal('1000.00'),
        fecha_prestamo=date.today(),
        estado='ACTIVO',
    )
    assert prestamo.get_monto_pagado() == Decimal('0.00')


@pytest.mark.django_db
def test_prestamo_get_saldo_neto_sin_pagos():
    """PrestamoPorSocio.get_saldo_neto() retorna monto_usd si no hay pagos."""
    socio = Socio.objects.create(nombre='Socio Test2', rif='V-22345678-9')
    prestamo = PrestamoPorSocio.objects.create(
        socio=socio,
        monto_principal=Decimal('500.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        monto_usd=Decimal('500.00'),
        fecha_prestamo=date.today(),
        estado='ACTIVO',
    )
    assert prestamo.get_saldo_neto() == Decimal('500.00')


# ─────────────────────────────────────────────────────────────────────────────
# B7-09: GastoServicio — monto_usd calculado automáticamente en save()
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_gasto_servicio_monto_usd_calculado_en_save():
    """GastoServicio.save() debe calcular monto_usd."""
    from apps.compras.models import GastoServicio, Proveedor
    from apps.core.models import CategoriaGasto

    proveedor = Proveedor.objects.create(nombre='Prov Test', rif='J-10000001-0')
    cat_padre = CategoriaGasto.objects.create(nombre='Servicios', contexto='GASTO')
    cat_sub = CategoriaGasto.objects.create(nombre='Electricidad', padre=cat_padre, contexto='GASTO')

    gasto = GastoServicio.objects.create(
        proveedor=proveedor,
        fecha_emision=date.today(),
        fecha_vencimiento=date.today(),
        descripcion='Luz del mes',
        monto=Decimal('100.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        categoria_gasto=cat_sub,
    )
    assert gasto.monto_usd == Decimal('100.00')


@pytest.mark.django_db
def test_gasto_servicio_monto_usd_calculado_ves():
    """GastoServicio en VES debe convertir monto_usd correctamente."""
    from apps.compras.models import GastoServicio, Proveedor
    from apps.core.models import CategoriaGasto

    proveedor = Proveedor.objects.create(nombre='Prov VES', rif='J-20000001-0')
    cat_padre = CategoriaGasto.objects.create(nombre='Servicios VES', contexto='GASTO')
    cat_sub = CategoriaGasto.objects.create(nombre='Agua', padre=cat_padre, contexto='GASTO')

    gasto = GastoServicio.objects.create(
        proveedor=proveedor,
        fecha_emision=date.today(),
        fecha_vencimiento=date.today(),
        descripcion='Agua del mes',
        monto=Decimal('36000.00'),
        moneda='VES',
        tasa_cambio=Decimal('36.000000'),
        categoria_gasto=cat_sub,
    )
    assert gasto.monto_usd == Decimal('1000.00')


# ─────────────────────────────────────────────────────────────────────────────
# B7-06: CxC — incluye facturas EMITIDA y COBRADA con saldo
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_factura_emitida_tiene_saldo_pendiente():
    """FacturaVenta EMITIDA sin cobros debe tener saldo pendiente > 0."""
    cliente = Cliente.objects.create(nombre='CxC Test', rif='J-30000001-0')
    factura = FacturaVenta.objects.create(
        numero='VTA-CXC-001',
        cliente=cliente,
        fecha=date.today(),
        moneda='USD',
        tasa_cambio=Decimal('1.0'),
        estado='EMITIDA',
        total=Decimal('500.00'),
    )
    assert factura.get_saldo_pendiente() == Decimal('500.00')
