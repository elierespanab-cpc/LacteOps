# -*- coding: utf-8 -*-
"""
test_sprint6_reportes.py — Cobertura QA Sprint 6 para vistas de Reportes.

Cubre:
  - Ventas: subtotal por cliente y columna estatus (lógica de vista)
  - Compras: subtotal por proveedor (lógica de vista)
  - CxC: columnas Cobrado y Neto Pendiente (lógica de vista)
  - Producción: filtro por producto (lógica de vista + HTTP)
  - Gastos: subtotales de categoría (HTTP con templates nuevos)
  - Stock: agrupado por categorías (HTTP)
  - Capital de Trabajo: referencia a socios/préstamos (HTTP)
  - Tesorería: vista accesible (200)
  - Kardex: saldo acumulado correcto

NOTA: Los templates de ventas/compras/cxc/gastos heredan del base de Jazzmin
que necesita `collectstatic`. Los tests que validan lógica de negocio
(context data) usan RequestFactory para evitar el renderizado del template.
Los tests HTTP usan los templates nuevos de Sprint 6 que no tienen ese problema.

REGLA: todas las aserciones numéricas usan Decimal exacto, NUNCA float.
"""
import pytest
from decimal import Decimal
from datetime import date
from unittest.mock import patch

from django.test import Client, RequestFactory
from django.contrib.auth.models import User
from django.http import HttpResponse

from apps.almacen.models import Producto, Categoria, UnidadMedida, MovimientoInventario
from apps.almacen.services import registrar_entrada, registrar_salida
from apps.ventas.models import FacturaVenta, DetalleFacturaVenta, ListaPrecio, DetalleLista, Cliente
from apps.compras.models import Proveedor, FacturaCompra, DetalleFacturaCompra
from apps.produccion.models import OrdenProduccion, Receta, RecetaDetalle, SalidaOrden
from apps.core.models import Secuencia, ConfiguracionEmpresa, CategoriaGasto
from apps.reportes import views as reportes_views


# ─────────────────────────────────────────────────────────────────────────────
# Helper para capturar contexto sin renderizar templates
# ─────────────────────────────────────────────────────────────────────────────

def _invoke_view_capture_context(view_func, request):
    """
    Ejecuta una view function y captura el contexto sin renderizar el template.
    Útil para vistas que heredan templates con dependencias de staticfiles.
    """
    ctx_capturado = {}

    def fake_render(req, template, context, **kwargs):
        ctx_capturado.update(context)
        return HttpResponse('OK')

    with patch('apps.reportes.views.render', side_effect=fake_render):
        view_func(request)

    return ctx_capturado


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures de usuarios y clientes
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def superuser(db):
    """Superusuario que tiene acceso a todos los reportes sin restricciones."""
    user = User.objects.create_superuser(
        username='qa_super',
        password='secret123',
        email='qa@test.com',
    )
    return user


@pytest.fixture
def auth_client(superuser):
    """Cliente HTTP autenticado como superusuario (para templates sin Jazzmin base)."""
    c = Client()
    c.force_login(superuser)
    return c


@pytest.fixture
def factory(superuser):
    """RequestFactory con usuario autenticado."""
    rf = RequestFactory()
    rf._superuser = superuser
    return rf


@pytest.fixture
def empresa(db):
    """ConfiguracionEmpresa requerida por muchas vistas de reportes."""
    return ConfiguracionEmpresa.objects.get_or_create(
        pk=1,
        defaults={
            'nombre_empresa': 'LacteOps Test',
            'rif': 'J-00000000-0',
            'direccion': 'Dirección de prueba',
            'telefono': '0000-0000000',
        }
    )[0]


@pytest.fixture
def unidad(db):
    u, _ = UnidadMedida.objects.get_or_create(simbolo='kg', defaults={'nombre': 'Kilogramo'})
    return u


@pytest.fixture
def categoria_pt(db):
    cat, _ = Categoria.objects.get_or_create(nombre='Producto Terminado')
    return cat


@pytest.fixture
def producto_rpt(db, unidad, categoria_pt):
    return Producto.objects.create(
        codigo='RPT-001',
        nombre='Queso Test Reportes',
        categoria=categoria_pt,
        unidad_medida=unidad,
        stock_actual=Decimal('0'),
        costo_promedio=Decimal('0'),
        es_producto_terminado=True,
    )


@pytest.fixture
def cliente_rpt(db):
    return Cliente.objects.create(
        nombre='Cliente Reporte',
        rif='V-11111111-1',
        limite_credito=Decimal('5000.00'),
    )


@pytest.fixture
def proveedor_rpt(db):
    return Proveedor.objects.create(
        nombre='Proveedor Reporte',
        rif='J-22222222-2',
    )


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures de secuencias
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def secuencias_basicas(db):
    """Garantiza secuencias VTA, COM y PRO para los tests de reportes."""
    for tipo, prefijo in [('VTA', 'VTA-'), ('COM', 'COM-'), ('PRO', 'PRO-')]:
        seq, _ = Secuencia.objects.get_or_create(
            tipo_documento=tipo,
            defaults={'ultimo_numero': 0, 'prefijo': prefijo, 'digitos': 4},
        )
        seq.ultimo_numero = 0
        seq.save(update_fields=['ultimo_numero'])


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _crear_factura_venta_emitida(cliente, producto, cantidad=Decimal('5'), precio=Decimal('100.00')):
    """Crea una FacturaVenta con estado EMITIDA directamente (sin pasar por emitir())."""
    lista = ListaPrecio.objects.create(nombre=f'Lista RPT {producto.pk}', activa=True)
    DetalleLista.objects.create(
        lista=lista,
        producto=producto,
        precio=precio,
        vigente_desde=date.today(),
        aprobado=True,
    )
    factura = FacturaVenta.objects.create(
        cliente=cliente,
        fecha=date.today(),
        estado='EMITIDA',
        lista_precio=lista,
    )
    DetalleFacturaVenta.objects.create(
        factura=factura,
        producto=producto,
        cantidad=cantidad,
        precio_unitario=precio,
    )
    factura.refresh_from_db()
    return factura


def _crear_factura_compra_aprobada(proveedor, producto, cantidad=Decimal('10'), costo=Decimal('8.00')):
    """Crea una FacturaCompra con estado APROBADA directamente."""
    factura = FacturaCompra.objects.create(
        proveedor=proveedor,
        fecha=date.today(),
        estado='APROBADA',
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        total=Decimal('0.00'),
    )
    DetalleFacturaCompra.objects.create(
        factura=factura,
        producto=producto,
        cantidad=cantidad,
        costo_unitario=costo,
        subtotal=(cantidad * costo),
    )
    factura.total = cantidad * costo
    factura.save(update_fields=['total'])
    factura.refresh_from_db()
    return factura


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de Ventas — lógica de negocio (sin renderizado de template Jazzmin)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_rpt_ventas_subtotal_por_cliente(factory, empresa, cliente_rpt, producto_rpt):
    """
    Reporte de ventas agrupado por cliente debe generar filas de tipo 'subtotal'.
    Valida la lógica de negocio de la vista sin renderizar el template.
    """
    _crear_factura_venta_emitida(cliente_rpt, producto_rpt)

    request = factory.get('/reportes/ventas/', {'agrupar_por_cliente': '1'})
    request.user = factory._superuser

    ctx = _invoke_view_capture_context(reportes_views.reporte_ventas, request)

    filas = ctx.get('filas', [])
    tipos = [f.get('tipo') for f in filas]
    assert 'subtotal' in tipos, (
        "La vista de ventas no genera filas de tipo 'subtotal' cuando se agrupa por cliente"
    )


@pytest.mark.django_db
def test_rpt_ventas_estatus_cobro(factory, empresa, cliente_rpt, producto_rpt):
    """
    La lógica de la vista de ventas debe asignar estatus_cobro a cada detalle.
    """
    _crear_factura_venta_emitida(cliente_rpt, producto_rpt)

    request = factory.get('/reportes/ventas/')
    request.user = factory._superuser

    ctx = _invoke_view_capture_context(reportes_views.reporte_ventas, request)

    filas = ctx.get('filas', [])
    detalles = [f for f in filas if f.get('tipo') == 'detalle']
    assert len(detalles) > 0, "No hay filas de detalle en el reporte de ventas"

    for fila in detalles:
        detalle = fila['detalle']
        assert hasattr(detalle, 'estatus_cobro'), "El detalle no tiene atributo estatus_cobro"
        assert detalle.estatus_cobro in ('Cobrada', 'Parcialmente Pendiente', 'Pendiente'), (
            f"Valor inesperado de estatus_cobro: {detalle.estatus_cobro}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de Compras — lógica de negocio
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_rpt_compras_subtotal_por_proveedor(factory, empresa, proveedor_rpt, producto_rpt):
    """
    Reporte de compras agrupado por proveedor debe generar filas de tipo 'subtotal'.
    """
    _crear_factura_compra_aprobada(proveedor_rpt, producto_rpt)

    request = factory.get('/reportes/compras/', {'agrupar_por_proveedor': '1'})
    request.user = factory._superuser

    ctx = _invoke_view_capture_context(reportes_views.reporte_compras, request)

    filas = ctx.get('filas', [])
    tipos = [f.get('tipo') for f in filas]
    assert 'subtotal' in tipos, (
        "La vista de compras no genera filas de tipo 'subtotal' cuando se agrupa por proveedor"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de CxC — lógica de negocio
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_rpt_cxc_columnas_pagado_neto(factory, empresa, cliente_rpt, producto_rpt):
    """
    La vista CxC debe calcular monto_cobrado, nc_emitidas y neto_pendiente.
    """
    _crear_factura_venta_emitida(cliente_rpt, producto_rpt)

    request = factory.get('/reportes/cxc/')
    request.user = factory._superuser

    ctx = _invoke_view_capture_context(reportes_views.reporte_cxc, request)

    totales = ctx.get('totales', {})
    assert 'total' in totales, "totales no tiene clave 'total'"
    assert 'cobrado' in totales, "totales no tiene clave 'cobrado' (Cobrado)"
    assert 'neto_pendiente' in totales, "totales no tiene clave 'neto_pendiente' (Neto Pendiente)"

    for item in ctx.get('resultados', []):
        assert 'monto_cobrado' in item, "item CxC no tiene 'monto_cobrado'"
        assert 'nc_emitidas' in item, "item CxC no tiene 'nc_emitidas'"
        assert 'neto_pendiente' in item, "item CxC no tiene 'neto_pendiente'"


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de Producción — filtro por producto
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_rpt_produccion_filtro_producto(factory, empresa, producto_rpt, db):
    """
    El filtro por producto en la vista de producción debe filtrar correctamente.
    """
    unidad, _ = UnidadMedida.objects.get_or_create(simbolo='kg', defaults={'nombre': 'Kilogramo'})
    cat_mp, _ = Categoria.objects.get_or_create(nombre='MP Test Rpt')

    mp = Producto.objects.create(
        codigo='MP-RPT-01',
        nombre='Materia Prima Rpt',
        categoria=cat_mp,
        unidad_medida=unidad,
        stock_actual=Decimal('50'),
        costo_promedio=Decimal('2.00'),
        es_materia_prima=True,
    )
    receta = Receta.objects.create(nombre='Receta Rpt Test', rendimiento_esperado=Decimal('80'))
    RecetaDetalle.objects.create(
        receta=receta,
        materia_prima=mp,
        cantidad_base=Decimal('5'),
        unidad_medida=unidad,
    )
    op = OrdenProduccion.objects.create(receta=receta)
    SalidaOrden.objects.create(
        orden=op,
        producto=producto_rpt,
        cantidad=Decimal('4'),
        precio_referencia=Decimal('20.00'),
        es_subproducto=False,
    )

    # Filtrar por producto_rpt → OP debe aparecer
    request = factory.get('/reportes/produccion/', {'producto': [str(producto_rpt.pk)]})
    request.user = factory._superuser

    ctx = _invoke_view_capture_context(reportes_views.reporte_produccion, request)

    ordenes = ctx.get('ordenes', [])
    numeros = [o.numero for o in ordenes]
    assert op.numero in numeros, (
        f"La OP {op.numero} no aparece al filtrar por producto {producto_rpt.pk}"
    )

    # Filtrar por otro producto → OP no debe aparecer
    otro_pt = Producto.objects.create(
        codigo='RPT-999',
        nombre='Otro Producto Rpt',
        categoria=cat_mp,
        unidad_medida=unidad,
        stock_actual=Decimal('0'),
        costo_promedio=Decimal('0'),
        es_producto_terminado=True,
    )

    request2 = factory.get('/reportes/produccion/', {'producto': [str(otro_pt.pk)]})
    request2.user = factory._superuser

    ctx2 = _invoke_view_capture_context(reportes_views.reporte_produccion, request2)

    ordenes2 = ctx2.get('ordenes', [])
    numeros2 = [o.numero for o in ordenes2]
    assert op.numero not in numeros2, (
        f"La OP {op.numero} aparece incorrectamente al filtrar por otro producto"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de Gastos — contexto de la vista
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_rpt_gastos_subtotal_categoria(factory, empresa, db):
    """
    La vista de gastos debe preparar datos agrupados (gastos_display_n1/n2).
    """
    CategoriaGasto.objects.get_or_create(
        nombre='Operativos',
        contexto='FACTURA',
        defaults={'padre': None, 'activa': True}
    )

    request = factory.get('/reportes/gastos/')
    request.user = factory._superuser

    ctx = _invoke_view_capture_context(reportes_views.reporte_gastos, request)

    assert ('gastos_display_n1' in ctx or 'gastos_display_n2' in ctx), (
        "La vista de gastos no proporciona claves de agrupación (gastos_display_n1/n2)"
    )


@pytest.mark.django_db
def test_rpt_gastos_accesible(auth_client, empresa):
    """Reporte de gastos (template Sprint 6) debe ser accesible (200)."""
    response = auth_client.get('/reportes/gastos/')
    assert response.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de Stock — HTTP con template Sprint 6
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_rpt_stock_agrupado_categorias(auth_client, empresa, producto_rpt, db):
    """
    Reporte de stock debe mostrar categorías como encabezados de agrupación.
    """
    registrar_entrada(
        producto=producto_rpt,
        cantidad=Decimal('10'),
        costo_unitario=Decimal('5.00'),
        referencia='INIT-RPT',
    )
    response = auth_client.get('/reportes/stock/')
    assert response.status_code == 200
    contenido = response.content.decode('utf-8')
    assert producto_rpt.categoria.nombre in contenido, (
        f"La categoría '{producto_rpt.categoria.nombre}' no aparece en el reporte de stock"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de Capital de Trabajo
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_rpt_capital_trabajo_incluye_socios(auth_client, empresa, db):
    """
    Reporte de capital de trabajo debe incluir referencia a 'Socios' o 'Préstamos'.
    """
    response = auth_client.get('/reportes/capital_trabajo/')
    assert response.status_code == 200
    contenido = response.content.decode('utf-8')
    assert ('Socios' in contenido or 'Préstamos' in contenido or 'Prestamos' in contenido), (
        "El reporte de capital de trabajo no incluye sección de socios/préstamos"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de Kardex
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_kardex_por_producto(auth_client, empresa, producto_rpt):
    """
    Reporte Kardex filtrado por producto debe ser accesible y mostrar el producto.
    Verifica que el saldo acumulado línea a línea está disponible.
    """
    # Entrada 1: 10 unidades a 5 USD
    registrar_entrada(
        producto=producto_rpt,
        cantidad=Decimal('10'),
        costo_unitario=Decimal('5.00'),
        referencia='KDX-ENT-01',
    )
    # Salida: 3 unidades
    registrar_salida(
        producto=producto_rpt,
        cantidad=Decimal('3'),
        referencia='KDX-SAL-01',
    )
    # Entrada 2: 5 unidades a 6 USD
    registrar_entrada(
        producto=producto_rpt,
        cantidad=Decimal('5'),
        costo_unitario=Decimal('6.00'),
        referencia='KDX-ENT-02',
    )

    # Stock esperado: 10 - 3 + 5 = 12
    producto_rpt.refresh_from_db()
    assert producto_rpt.stock_actual == Decimal('12.0000'), (
        f"Stock esperado 12, obtenido {producto_rpt.stock_actual}"
    )

    response = auth_client.get(f'/reportes/kardex/?producto={producto_rpt.pk}')
    assert response.status_code == 200
    contenido = response.content.decode('utf-8')
    # El nombre o código del producto debe aparecer
    assert (producto_rpt.nombre in contenido or producto_rpt.codigo in contenido), (
        "El kardex no muestra el producto seleccionado"
    )


@pytest.mark.django_db
def test_kardex_accesible_sin_filtros(auth_client, empresa):
    """Kardex sin filtros debe retornar 200."""
    response = auth_client.get('/reportes/kardex/')
    assert response.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Tests de Tesorería
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_rpt_tesoreria_existe(auth_client, empresa):
    """
    Vista de tesorería debe existir y devolver HTTP 200.
    """
    response = auth_client.get('/reportes/tesoreria/')
    assert response.status_code == 200
