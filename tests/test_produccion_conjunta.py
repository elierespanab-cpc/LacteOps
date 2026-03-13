# -*- coding: utf-8 -*-
import pytest
from decimal import Decimal
from django.db import transaction
from apps.produccion.models import Receta, RecetaDetalle, OrdenProduccion, SalidaOrden
from apps.almacen.models import Producto
from apps.core.exceptions import EstadoInvalidoError
from apps.almacen.services import registrar_entrada

@pytest.fixture
def mp_leche_cruda(unidad_kg, categoria_lacteos):
    p = Producto.objects.create(
        codigo='MP-LECHE',
        nombre='Leche Cruda',
        categoria=categoria_lacteos,
        unidad_medida=unidad_kg,
        es_materia_prima=True,
        costo_promedio=Decimal('0.50')
    )
    # Dar stock inicial
    registrar_entrada(p, Decimal('1000'), Decimal('0.50'), 'STOCK-INICIAL')
    p.refresh_from_db()
    return p

@pytest.fixture
def receta_queso(mp_leche_cruda, unidad_kg):
    r = Receta.objects.create(nombre='Receta Queso y Suero', rendimiento_esperado=Decimal('100'))
    RecetaDetalle.objects.create(receta=r, materia_prima=mp_leche_cruda, cantidad_base=Decimal('10'), unidad_medida=unidad_kg)
    return r

@pytest.fixture
def producto_queso(unidad_kg, categoria_lacteos):
    return Producto.objects.create(
        codigo='PT-QUESO',
        nombre='Queso Blanco',
        categoria=categoria_lacteos,
        unidad_medida=unidad_kg,
        es_producto_terminado=True
    )

@pytest.fixture
def producto_crema(unidad_kg, categoria_lacteos):
    return Producto.objects.create(
        codigo='PT-CREMA',
        nombre='Crema de Leche',
        categoria=categoria_lacteos,
        unidad_medida=unidad_kg,
        es_producto_terminado=True
    )

@pytest.fixture
def producto_suero(unidad_kg, categoria_lacteos):
    return Producto.objects.create(
        codigo='SP-SUERO',
        nombre='Suero de Leche',
        categoria=categoria_lacteos,
        unidad_medida=unidad_kg,
        es_producto_terminado=True
    )

@pytest.mark.django_db
def test_costo_distribuido_por_valor_mercado(receta_queso, producto_queso, producto_crema):
    """
    Verifica que el costo total de la OP se distribuya entre los productos principales
    según su valor de mercado relativo (precio_referencia * cantidad).
    """
    op = OrdenProduccion.objects.create(numero='OP-001', receta=receta_queso)
    
    # Salidas: Queso (10 kg @ 5 USD) y Crema (5 kg @ 10 USD) -> Valor total = 50 + 50 = 100
    # Como el valor es 50/50, el costo se debe dividir 50/50.
    SalidaOrden.objects.create(orden=op, producto=producto_queso, cantidad=Decimal('10'), precio_referencia=Decimal('5.00'), es_subproducto=False)
    SalidaOrden.objects.create(orden=op, producto=producto_crema, cantidad=Decimal('5'), precio_referencia=Decimal('10.00'), es_subproducto=False)

    # Costo total de consumos = 10 kg * 0.50 = 5.00 USD
    op.cerrar()
    op.refresh_from_db()

    assert op.costo_total == Decimal('5.00')
    
    salida_queso = op.salidas.get(producto=producto_queso)
    salida_crema = op.salidas.get(producto=producto_crema)

    # Distribución 50/50
    assert salida_queso.costo_asignado == Decimal('2.500000')
    assert salida_crema.costo_asignado == Decimal('2.500000')
    
    # Verificar costo promedio en productos
    producto_queso.refresh_from_db()
    producto_crema.refresh_from_db()
    assert producto_queso.costo_promedio == Decimal('0.250000') # 2.50 / 10
    assert producto_crema.costo_promedio == Decimal('0.500000') # 2.50 / 5

@pytest.mark.django_db
def test_subproducto_entra_a_costo_cero(receta_queso, producto_queso, producto_suero):
    """
    Verifica que los subproductos reciban costo asignado cero y no resten costo
    a los productos principales.
    """
    op = OrdenProduccion.objects.create(numero='OP-002', receta=receta_queso)
    
    # Principal: Queso (10 kg), Subproducto: Suero (50 kg)
    SalidaOrden.objects.create(orden=op, producto=producto_queso, cantidad=Decimal('10'), precio_referencia=Decimal('5.00'), es_subproducto=False)
    SalidaOrden.objects.create(orden=op, producto=producto_suero, cantidad=Decimal('50'), precio_referencia=Decimal('0.10'), es_subproducto=True)

    op.cerrar()
    
    salida_queso = op.salidas.get(producto=producto_queso)
    salida_suero = op.salidas.get(producto=producto_suero)

    assert salida_suero.costo_asignado == Decimal('0.000000')
    assert salida_queso.costo_asignado == op.costo_total
    
    producto_suero.refresh_from_db()
    assert producto_suero.costo_promedio == Decimal('0.000000')

@pytest.mark.django_db
def test_orden_sin_producto_principal_no_cierra(receta_queso, producto_suero):
    """
    Una orden que solo tiene subproductos definidos debe fallar al cerrar.
    """
    op = OrdenProduccion.objects.create(numero='OP-003', receta=receta_queso)
    SalidaOrden.objects.create(orden=op, producto=producto_suero, cantidad=Decimal('50'), precio_referencia=Decimal('0.10'), es_subproducto=True)

    with pytest.raises(EstadoInvalidoError, match="debe tener al menos un producto principal"):
        op.cerrar()

@pytest.mark.django_db
def test_residuo_redondeo_absorbido(receta_queso, producto_queso, producto_crema):
    """
    Verifica que la suma de los costos asignados sea exactamente igual al costo total,
    incluso si hay residuos de divisiones infinitas.
    El residuo debe ser absorbido por el producto de mayor valor.
    """
    op = OrdenProduccion.objects.create(numero='OP-004', receta=receta_queso)
    
    # Forzar un costo total difícil de dividir: 5.00 USD
    # Salidas con pesos relativos que generen periódicos: 1/3 y 2/3
    # Queso: 10 kg @ 1 USD = 10 USD valor
    # Crema: 10 kg @ 2 USD = 20 USD valor
    # Valor total = 30 USD. 
    # Queso absorbe 1/3 de 5 = 1.6666666...
    # Crema absorbe 2/3 de 5 = 3.3333333...
    SalidaOrden.objects.create(orden=op, producto=producto_queso, cantidad=Decimal('10'), precio_referencia=Decimal('1.00'), es_subproducto=False)
    SalidaOrden.objects.create(orden=op, producto=producto_crema, cantidad=Decimal('10'), precio_referencia=Decimal('2.00'), es_subproducto=False)

    op.cerrar()
    op.refresh_from_db()
    
    salidas = op.salidas.all()
    suma_asignada = sum(s.costo_asignado for s in salidas)
    
    # REGLA DE ORO: Exactitud Decimal
    assert suma_asignada == op.costo_total
    assert suma_asignada == Decimal('5.00')
    
    # El más valioso (Crema) debe haber absorbido el residuo
    salida_crema = op.salidas.get(producto=producto_crema)
    salida_queso = op.salidas.get(producto=producto_queso)
    
    # 5 * (10/30) = 1.666666 (truncate/round)
    # 5 - 1.666666 = 3.333334
    assert salida_queso.costo_asignado == Decimal('1.666666') or salida_queso.costo_asignado == Decimal('1.666667')
    assert salida_crema.costo_asignado == op.costo_total - salida_queso.costo_asignado
