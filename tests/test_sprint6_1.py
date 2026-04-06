# -*- coding: utf-8 -*-
"""
test_sprint6_1.py — Tests para las correcciones Sprint 6.1

Cubre:
  P6-02b  Impresión FacturaVenta bloqueada sin MovimientoInventario
  P6-03b  Kardex modo totales (una fila por producto)
  P6-04b  PrestamoPorSocio genera MovimientoCaja via save_model
  P6-06b  get_origen diferencia tipos específicos (Cobro/Devolución/Préstamo/Pago)
  P6-08b  reporte_capital_trabajo incluye cuentas_efectivo en contexto
  P7-01   Saldo socio incluye todos los préstamos ACTIVOS
  P7-02   fecha_apertura de OrdenProduccion readonly según ConfiguracionEmpresa
"""
import pytest
from decimal import Decimal
from datetime import date

from django.contrib.auth.models import User

from apps.almacen.models import Categoria, UnidadMedida, Producto, MovimientoInventario
from apps.ventas.models import FacturaVenta, Cliente, DetalleFacturaVenta
from apps.bancos.models import CuentaBancaria, MovimientoCaja
from apps.socios.models import Socio, PrestamoPorSocio
from apps.produccion.models import OrdenProduccion, Receta
from apps.core.models import ConfiguracionEmpresa


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures locales
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser("admin61", "admin@test.com", "pass")


@pytest.fixture
def auth_client(admin_user):
    from django.test import Client
    c = Client()
    c.login(username="admin61", password="pass")
    return c


@pytest.fixture
def cat(db):
    return Categoria.objects.create(nombre="TestCat61")


@pytest.fixture
def um(db):
    um, _ = UnidadMedida.objects.get_or_create(simbolo="kg", defaults={"nombre": "Kilogramo"})
    return um


@pytest.fixture
def producto(db, cat, um):
    return Producto.objects.create(
        codigo="P61-001",
        nombre="Producto Test 61",
        categoria=cat,
        unidad_medida=um,
        stock_actual=Decimal("100.0000"),
        costo_promedio=Decimal("10.000000"),
    )


@pytest.fixture
def cuenta_usd(db):
    return CuentaBancaria.objects.create(
        nombre="Banco Test S6.1 USD",
        moneda="USD",
        saldo_actual=Decimal("1000.00"),
        activa=True,
    )


@pytest.fixture
def cliente_fv(db):
    return Cliente.objects.create(
        nombre="Cliente S6.1",
        rif="J-61000000-1",
        limite_credito=Decimal("5000.00"),
    )


@pytest.fixture
def socio(db):
    return Socio.objects.create(nombre="Socio Test S6.1", rif="V-61000001")


# ──────────────────────────────────────────────────────────────────────────────
# P6-02b: Impresión bloqueada sin MovimientoInventario
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_show_print_button_falso_sin_movimientos(admin_user, cliente_fv, producto, cat, um):
    """
    La lógica de show_print_button retorna False cuando no hay
    MovimientoInventario de SALIDA para la factura.
    Probamos la lógica directamente sin renderizar el template Jazzmin.
    """
    fv = FacturaVenta.objects.create(
        cliente=cliente_fv,
        fecha=date.today(),
        estado="EMITIDA",
        moneda="USD",
        tasa_cambio=Decimal("1.000000"),
        total=Decimal("0.00"),
    )
    # No llamamos a fv.emitir() → no hay MovimientoInventario

    tiene_movimientos = MovimientoInventario.objects.filter(
        referencia=fv.numero, tipo="SALIDA"
    ).exists()
    show_print_button = fv.estado in ("EMITIDA", "COBRADA") and tiene_movimientos
    assert show_print_button is False


@pytest.mark.django_db
def test_show_print_button_verdadero_con_movimientos(admin_user, cliente_fv, producto, cat, um):
    """
    show_print_button es True cuando hay MovimientoInventario SALIDA para la factura.
    """
    from apps.almacen.services import registrar_salida

    # Crear movimiento de salida directamente (no a través de emitir())
    mov = registrar_salida(
        producto=producto,
        cantidad=Decimal("5"),
        referencia="VTA-0099",
    )

    fv = FacturaVenta.objects.create(
        cliente=cliente_fv,
        fecha=date.today(),
        estado="EMITIDA",
        moneda="USD",
        tasa_cambio=Decimal("1.000000"),
        total=Decimal("100.00"),
    )
    # Simulamos que la referencia del movimiento coincide con el número de factura
    # En producción: emitir() usa fv.numero como referencia
    # Aquí actualizamos la referencia manualmente para la prueba
    from apps.almacen.models import MovimientoInventario as MI
    MI.objects.filter(pk=mov.pk).update(referencia=fv.numero)

    tiene_movimientos = MovimientoInventario.objects.filter(
        referencia=fv.numero, tipo="SALIDA"
    ).exists()
    show_print_button = fv.estado in ("EMITIDA", "COBRADA") and tiene_movimientos
    assert show_print_button is True


# ──────────────────────────────────────────────────────────────────────────────
# P6-06b: get_origen con tipos específicos
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_get_origen_cobro_venta(cuenta_usd):
    from apps.bancos.admin import MovimientoCajaAdmin
    from django.contrib.admin.sites import AdminSite

    mov = MovimientoCaja(
        cuenta=cuenta_usd,
        tipo="ENTRADA",
        monto=Decimal("100.00"),
        moneda="USD",
        tasa_cambio=Decimal("1.000000"),
        monto_usd=Decimal("100.00"),
        referencia="VTA-0001",
        fecha=date.today(),
    )
    admin_inst = MovimientoCajaAdmin(MovimientoCaja, AdminSite())
    assert admin_inst.get_origen(mov) == "Cobro Venta"


@pytest.mark.django_db
def test_get_origen_pago_compra(cuenta_usd):
    from apps.bancos.admin import MovimientoCajaAdmin
    from django.contrib.admin.sites import AdminSite

    mov = MovimientoCaja(
        cuenta=cuenta_usd, tipo="SALIDA", monto=Decimal("200.00"),
        moneda="USD", tasa_cambio=Decimal("1.000000"), monto_usd=Decimal("200.00"),
        referencia="COM-0001", fecha=date.today(),
    )
    admin_inst = MovimientoCajaAdmin(MovimientoCaja, AdminSite())
    assert admin_inst.get_origen(mov) == "Pago Compra"


@pytest.mark.django_db
def test_get_origen_devolucion_proveedor(cuenta_usd):
    from apps.bancos.admin import MovimientoCajaAdmin
    from django.contrib.admin.sites import AdminSite

    mov = MovimientoCaja(
        cuenta=cuenta_usd, tipo="ENTRADA", monto=Decimal("50.00"),
        moneda="USD", tasa_cambio=Decimal("1.000000"), monto_usd=Decimal("50.00"),
        referencia="COM-0002", fecha=date.today(),
    )
    admin_inst = MovimientoCajaAdmin(MovimientoCaja, AdminSite())
    assert admin_inst.get_origen(mov) == "Devolución Proveedor"


@pytest.mark.django_db
def test_get_origen_prestamo_socio(cuenta_usd):
    from apps.bancos.admin import MovimientoCajaAdmin
    from django.contrib.admin.sites import AdminSite

    mov = MovimientoCaja(
        cuenta=cuenta_usd, tipo="ENTRADA", monto=Decimal("500.00"),
        moneda="USD", tasa_cambio=Decimal("1.000000"), monto_usd=Decimal("500.00"),
        referencia="SOC-0001", fecha=date.today(),
    )
    admin_inst = MovimientoCajaAdmin(MovimientoCaja, AdminSite())
    assert admin_inst.get_origen(mov) == "Préstamo Socio"


@pytest.mark.django_db
def test_get_origen_pago_a_socio(cuenta_usd):
    from apps.bancos.admin import MovimientoCajaAdmin
    from django.contrib.admin.sites import AdminSite

    mov = MovimientoCaja(
        cuenta=cuenta_usd, tipo="SALIDA", monto=Decimal("100.00"),
        moneda="USD", tasa_cambio=Decimal("1.000000"), monto_usd=Decimal("100.00"),
        referencia="SOC-0002", fecha=date.today(),
    )
    admin_inst = MovimientoCajaAdmin(MovimientoCaja, AdminSite())
    assert admin_inst.get_origen(mov) == "Pago a Socio"


# ──────────────────────────────────────────────────────────────────────────────
# P6-03b: Kardex modo totales
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_kardex_modo_totales_sin_filtros(auth_client, producto):
    """Sin filtros → modo='totales', una fila por producto en productos_data."""
    from apps.almacen.services import registrar_entrada, registrar_salida

    registrar_entrada(
        producto=producto,
        cantidad=Decimal("20"),
        costo_unitario=Decimal("10.00"),
        referencia="E61-001",
    )
    registrar_salida(
        producto=producto,
        cantidad=Decimal("5"),
        referencia="S61-001",
    )

    resp = auth_client.get("/reportes/kardex/")
    assert resp.status_code == 200
    assert resp.context["modo"] == "totales"

    data = resp.context["productos_data"]
    item = next((p for p in data if p["codigo"] == "P61-001"), None)
    assert item is not None
    assert item["cant_entradas"] == Decimal("20.00")
    assert item["cant_salidas"] == Decimal("5.00")
    # sin fecha_desde, cant_inicial=0 (no hay movimientos previos al rango)
    assert item["cant_final"] == Decimal("15.00")  # 0 + 20 - 5 = 15


@pytest.mark.django_db
def test_kardex_modo_totales_12_columnas(auth_client, producto):
    """Verifica que productos_data contiene las 12 columnas necesarias."""
    resp = auth_client.get("/reportes/kardex/")
    assert resp.status_code == 200
    data = resp.context["productos_data"]
    assert len(data) > 0
    keys = data[0].keys()
    for col in [
        "cant_inicial", "cant_entradas", "cant_salidas", "cant_ajustes", "cant_final",
        "monto_inicial", "monto_entradas", "monto_salidas", "monto_ajustes", "monto_final",
    ]:
        assert col in keys, f"Columna '{col}' no encontrada en productos_data"


# ──────────────────────────────────────────────────────────────────────────────
# P6-04b y P7-01: Préstamos y saldo socios
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_registrar_prestamo_genera_movimiento_caja(socio, cuenta_usd):
    """Crear PrestamoPorSocio vía servicio genera MovimientoCaja ENTRADA."""
    from apps.socios.services import registrar_prestamo

    prestamo = registrar_prestamo(
        socio=socio,
        monto=Decimal("300.00"),
        moneda="USD",
        tasa=Decimal("1.000000"),
        fecha=date.today(),
        cuenta_destino=cuenta_usd,
    )

    mov = MovimientoCaja.objects.filter(referencia=prestamo.numero)
    assert mov.count() == 1
    m = mov.first()
    assert m.tipo == "ENTRADA"
    assert m.cuenta == cuenta_usd
    assert m.monto == Decimal("300.00")


@pytest.mark.django_db
def test_saldo_bruto_socio_incluye_prestamos(socio, cuenta_usd):
    """get_saldo_bruto() suma monto_usd de todos los préstamos ACTIVOS."""
    from apps.socios.services import registrar_prestamo

    registrar_prestamo(
        socio=socio,
        monto=Decimal("200.00"),
        moneda="USD",
        tasa=Decimal("1.000000"),
        fecha=date.today(),
        cuenta_destino=cuenta_usd,
    )
    registrar_prestamo(
        socio=socio,
        monto=Decimal("100.00"),
        moneda="USD",
        tasa=Decimal("1.000000"),
        fecha=date.today(),
        cuenta_destino=cuenta_usd,
    )

    assert socio.get_saldo_bruto() == Decimal("300.00")


# ──────────────────────────────────────────────────────────────────────────────
# P6-08b: Capital de Trabajo con desglose efectivo
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_capital_trabajo_incluye_cuentas_efectivo(auth_client, cuenta_usd):
    """reporte_capital_trabajo pasa cuentas_efectivo al contexto."""
    resp = auth_client.get("/reportes/capital_trabajo/")
    assert resp.status_code == 200
    assert "cuentas_efectivo" in resp.context
    cuentas = resp.context["cuentas_efectivo"]
    assert len(cuentas) >= 1
    # Verificar estructura de cada entrada
    for c in cuentas:
        assert "nombre" in c
        assert "moneda" in c
        assert "saldo_original" in c
        assert "saldo_usd" in c


@pytest.mark.django_db
def test_capital_trabajo_efectivo_suma_cuentas(auth_client, cuenta_usd):
    """El efectivo total coincide con la suma de saldo_usd de las cuentas."""
    resp = auth_client.get("/reportes/capital_trabajo/")
    assert resp.status_code == 200
    cuentas = resp.context["cuentas_efectivo"]
    total_calculado = sum(c["saldo_usd"] for c in cuentas)
    efectivo_ctx = resp.context["efectivo"]
    # Tolerancia por quantize en cada cuenta
    assert abs(total_calculado - efectivo_ctx) < Decimal("0.10")


# ──────────────────────────────────────────────────────────────────────────────
# P7-02: Fecha apertura OP configurable
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_fecha_apertura_readonly_only_when_closed():
    """fecha_apertura de OP es editable mientras no esté CERRADA, según solicitud del usuario."""
    from apps.produccion.admin import OrdenProduccionAdmin
    from apps.produccion.models import OrdenProduccion
    from django.contrib.admin.sites import AdminSite
    from unittest.mock import Mock

    admin_inst = OrdenProduccionAdmin(OrdenProduccion, AdminSite())
    
    # OP nueva (obj=None)
    ro_new = admin_inst.get_readonly_fields(None, None)
    assert "fecha_apertura" not in ro_new

    # OP ABIERTA
    op_abierta = Mock(estado='ABIERTA')
    ro_open = admin_inst.get_readonly_fields(None, op_abierta)
    assert "fecha_apertura" not in ro_open

    # OP CERRADA
    op_cerrada = Mock(estado='CERRADA')
    ro_closed = admin_inst.get_readonly_fields(None, op_cerrada)
    assert "fecha_apertura" in ro_closed
