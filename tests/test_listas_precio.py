# -*- coding: utf-8 -*-
import pytest
from decimal import Decimal
from datetime import date
from django.contrib.auth.models import User, Group
from django.core.exceptions import PermissionDenied
from apps.ventas.models import ListaPrecio, DetalleLista, FacturaVenta, DetalleFacturaVenta, Cliente
from apps.ventas.services import aprobar_precio
from apps.almacen.models import Producto
from apps.core.exceptions import EstadoInvalidoError

@pytest.fixture
def lista_general(db):
    return ListaPrecio.objects.create(nombre='Lista General', requiere_aprobacion=True)

@pytest.fixture
def producto_leche(unidad_kg, categoria_lacteos):
    p = Producto.objects.create(
        codigo='PT-LECHE-PAST',
        nombre='Leche Pasteurizada 1L',
        categoria=categoria_lacteos,
        unidad_medida=unidad_kg,
        stock_actual=Decimal('100'),
        costo_promedio=Decimal('0.80')
    )
    return p

@pytest.fixture
def admin_user(db):
    user = User.objects.create_superuser(username='admin_test', password='password', email='admin@test.com')
    group, _ = Group.objects.get_or_create(name='Administrador')
    user.groups.add(group)
    return user

@pytest.fixture
def assistant_user(db):
    user = User.objects.create_user(username='assistant_test', password='password')
    group, _ = Group.objects.get_or_create(name='Asistente Ventas')
    user.groups.add(group)
    return user

@pytest.mark.django_db
def test_precio_asignado_automaticamente_al_emitir(lista_general, producto_leche, cliente, admin_user):
    """
    Verifica que al emitir una factura, el precio unitario se tome de la lista de precios
    asociada y sea el precio aprobado.
    """
    # Crear detalle de lista aprobado
    detalle_l = DetalleLista.objects.create(
        lista=lista_general, producto=producto_leche, precio=Decimal('1.50'), 
        vigente_desde=date.today()
    )
    aprobar_precio(detalle_l, admin_user)

    # Crear factura
    fv = FacturaVenta.objects.create(
        numero='VTA-LP-001', cliente=cliente, lista_precio=lista_general,
        fecha=date.today(), moneda='USD'
    )
    DetalleFacturaVenta.objects.create(factura=fv, producto=producto_leche, cantidad=Decimal('10'), precio_unitario=Decimal('0'))
    
    # Emitir
    fv.emitir()
    
    detalle_f = fv.detalles.get(producto=producto_leche)
    assert detalle_f.precio_unitario == Decimal('1.50')
    assert fv.total == Decimal('15.00')

@pytest.mark.django_db
def test_producto_sin_precio_en_lista_bloquea_emision(lista_general, producto_leche, cliente):
    """
    Si un producto en la factura no existe en la lista de precios, debe fallar.
    """
    fv = FacturaVenta.objects.create(
        numero='VTA-LP-002', cliente=cliente, lista_precio=lista_general,
        fecha=date.today()
    )
    DetalleFacturaVenta.objects.create(factura=fv, producto=producto_leche, cantidad=Decimal('10'), precio_unitario=Decimal('0'))
    
    with pytest.raises(EstadoInvalidoError, match="sin precio aprobado"):
        fv.emitir()

@pytest.mark.django_db
def test_precio_no_aprobado_no_usable(lista_general, producto_leche, cliente):
    """
    Si existe el precio en la lista pero NO está aprobado, debe fallar.
    """
    DetalleLista.objects.create(
        lista=lista_general, producto=producto_leche, precio=Decimal('1.50'), 
        vigente_desde=date.today(), aprobado=False
    )

    fv = FacturaVenta.objects.create(
        numero='VTA-LP-003', cliente=cliente, lista_precio=lista_general,
        fecha=date.today()
    )
    DetalleFacturaVenta.objects.create(factura=fv, producto=producto_leche, cantidad=Decimal('10'), precio_unitario=Decimal('0'))
    
    with pytest.raises(EstadoInvalidoError, match="sin precio aprobado"):
        fv.emitir()

@pytest.mark.django_db
def test_factura_sin_lista_bloquea_emision(producto_leche, cliente):
    """
    No se puede emitir una factura si no tiene lista de precios seleccionada.
    """
    fv = FacturaVenta.objects.create(
        numero='VTA-LP-004', cliente=cliente, lista_precio=None,
        fecha=date.today()
    )
    DetalleFacturaVenta.objects.create(factura=fv, producto=producto_leche, cantidad=Decimal('10'), precio_unitario=Decimal('0'))
    
    with pytest.raises(EstadoInvalidoError, match="seleccionar una lista de precios"):
        fv.emitir()

@pytest.mark.django_db
def test_solo_admin_y_master_aprueban_precios(lista_general, producto_leche, admin_user, assistant_user):
    """
    Verifica que un usuario sin privilegios (Asistente) no pueda aprobar precios,
    pero un Administrador sí.
    """
    detalle = DetalleLista.objects.create(
        lista=lista_general, producto=producto_leche, precio=Decimal('1.50'), 
        vigente_desde=date.today()
    )

    # Intento por asistente -> debe fallar
    with pytest.raises(PermissionDenied, match="requiere grupo Master o Administrador"):
        aprobar_precio(detalle, assistant_user)
    
    # Intento por admin -> debe pasar
    aprobar_precio(detalle, admin_user)
    detalle.refresh_from_db()
    assert detalle.aprobado is True
    assert detalle.aprobado_por == admin_user
