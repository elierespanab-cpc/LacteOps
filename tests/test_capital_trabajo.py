# -*- coding: utf-8 -*-
import pytest
from decimal import Decimal
from datetime import date
from django.contrib.auth.models import User
from django.urls import reverse
from apps.almacen.models import Producto

@pytest.fixture
def user_viewer(db):
    user = User.objects.create_user(username='viewer', password='123')
    return user

@pytest.mark.django_db
def test_inventario_sin_precio_venta_usa_costo_promedio(client, user_viewer, unidad_kg, categoria_lacteos):
    """
    En el reporte de capital de trabajo, si se valora a precio de VENTA y un producto
    no tiene precio_venta definido, debe usar su costo_promedio como fallback.
    """
    prod = Producto.objects.create(
        codigo='P_VAL', nombre='P_VAL', categoria=categoria_lacteos, unidad_medida=unidad_kg,
        stock_actual=Decimal('100'), costo_promedio=Decimal('5.00'), precio_venta=None
    )

    client.force_login(user_viewer)
    url = reverse('reportes:capital_trabajo')
    response = client.get(url, {'valorar_inventario': 'VENTA', 'fecha_corte': str(date.today())})
    
    context = response.context
    # Inventario debe ser 100 * 5.00 = 500.00
    assert context['inventario'] == Decimal('500.00')

@pytest.mark.django_db
def test_materia_prima_incluida_en_valoracion(client, user_viewer, unidad_kg, categoria_lacteos):
    """Verifica que las materias primas con stock sumen al valor total del inventario."""
    mp = Producto.objects.create(
        codigo='MP_VAL', nombre='MP_VAL', categoria=categoria_lacteos, unidad_medida=unidad_kg,
        stock_actual=Decimal('1000'), costo_promedio=Decimal('0.10'), es_materia_prima=True
    )

    client.force_login(user_viewer)
    url = reverse('reportes:capital_trabajo')
    response = client.get(url, {'valorar_inventario': 'COSTO', 'fecha_corte': str(date.today())})
    
    context = response.context
    # 1000 * 0.10 = 100.00
    assert context['inventario'] >= Decimal('100.00')
