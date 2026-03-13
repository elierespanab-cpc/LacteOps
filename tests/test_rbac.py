# -*- coding: utf-8 -*-
import pytest
from decimal import Decimal
from datetime import date
from django.contrib.auth.models import User, Group
from django.core.exceptions import PermissionDenied
from apps.almacen.models import AjusteInventario, Producto
from apps.ventas.models import ListaPrecio, DetalleLista
from apps.ventas.services import aprobar_precio

@pytest.fixture
def groups(db):
    Group.objects.get_or_create(name='Master')
    Group.objects.get_or_create(name='Administrador')
    Group.objects.get_or_create(name='Jefe Producción')
    Group.objects.get_or_create(name='Asistente Ventas')

@pytest.fixture
def user_asistente(groups):
    u = User.objects.create_user(username='asistente', password='123')
    u.groups.add(Group.objects.get(name='Asistente Ventas'))
    return u

@pytest.fixture
def user_jefe_produccion(groups):
    u = User.objects.create_user(username='jefe_prod', password='123')
    u.groups.add(Group.objects.get(name='Jefe Producción'))
    return u

@pytest.fixture
def user_admin(groups):
    u = User.objects.create_user(username='admin_local', password='123')
    u.groups.add(Group.objects.get(name='Administrador'))
    return u

@pytest.mark.django_db
def test_asistente_ventas_no_aprueba_precios(user_asistente, unidad_kg, categoria_lacteos):
    """Asistente Ventas no tiene permiso para aprobar precios."""
    lista = ListaPrecio.objects.create(nombre='Test', requiere_aprobacion=True)
    prod = Producto.objects.create(codigo='P1', nombre='P1', categoria=categoria_lacteos, unidad_medida=unidad_kg)
    detalle = DetalleLista.objects.create(lista=lista, producto=prod, precio=Decimal('10'), vigente_desde=date.today())

    with pytest.raises(PermissionDenied):
        aprobar_precio(detalle, user_asistente)

@pytest.mark.django_db
def test_jefe_produccion_no_aprueba_ajuste_grande(user_jefe_produccion, unidad_kg, categoria_lacteos):
    """
    Un Jefe de Producción puede aprobar ajustes, pero si el monto supera los 1000 USD
    debe ser bloqueado por falta de rango (requiere Master/Admin).
    """
    # Producto con costo 50 USD
    prod = Producto.objects.create(
        codigo='P2', nombre='P2', categoria=categoria_lacteos, unidad_medida=unidad_kg,
        costo_promedio=Decimal('50.00')
    )
    # Ajuste de 30 unidades = 1500 USD (> 1000 USD)
    ajuste = AjusteInventario.objects.create(
        producto=prod, tipo='ENTRADA_AJUSTE', cantidad=Decimal('30.00'), motivo='Test grande'
    )

    with pytest.raises(PermissionDenied, match="requieren aprobación de Master o Administrador"):
        ajuste.aprobar(usuario=user_jefe_produccion)

@pytest.mark.django_db
def test_administrador_aprueba_ajuste_grande(user_admin, unidad_kg, categoria_lacteos):
    """Un Administrador sí puede aprobar ajustes > 1000 USD."""
    prod = Producto.objects.create(
        codigo='P3', nombre='P3', categoria=categoria_lacteos, unidad_medida=unidad_kg,
        stock_actual=0, costo_promedio=Decimal('100.00')
    )
    # Ajuste de 15 unidades = 1500 USD
    ajuste = AjusteInventario.objects.create(
        producto=prod, tipo='ENTRADA_AJUSTE', cantidad=Decimal('15.00'), motivo='Aprobar'
    )

    ajuste.aprobar(usuario=user_admin)
    assert ajuste.estado == 'APROBADO'
    prod.refresh_from_db()
    assert prod.stock_actual == Decimal('15.00')
