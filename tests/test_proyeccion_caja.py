# -*- coding: utf-8 -*-
"""
test_proyeccion_caja.py — Suite para calcular_proyeccion_caja_7d (Sprint 4).
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from django.contrib.auth.models import User

from apps.almacen.models import UnidadMedida, Categoria, Producto
from apps.bancos.models import CuentaBancaria
from apps.compras.models import Proveedor, FacturaCompra
from apps.ventas.models import Cliente, FacturaVenta
from apps.socios.models import Socio, PrestamoPorSocio
from apps.core.models import Secuencia
from apps.reportes.analytics import calcular_proyeccion_caja_7d


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cuenta_usd_proy(db):
    return CuentaBancaria.objects.create(
        nombre='Cuenta Proyección USD',
        moneda='USD',
        saldo_actual=Decimal('5000.00'),
        activa=True,
    )


@pytest.fixture
def cliente_proy(db):
    return Cliente.objects.create(
        nombre='Cliente Proyección',
        rif='J-20000001-0',
        limite_credito=Decimal('10000.00'),
        dias_credito=30,
    )


@pytest.fixture
def proveedor_proy(db):
    return Proveedor.objects.create(
        nombre='Proveedor Proyección',
        rif='J-20000002-0',
    )


@pytest.fixture
def socio_proy(db):
    return Socio.objects.create(nombre='Socio Proyección')


@pytest.fixture
def secuencia_soc_proy(db):
    seq, _ = Secuencia.objects.get_or_create(
        tipo_documento='SOC',
        defaults={'prefijo': 'SOC-', 'digitos': 4, 'ultimo_numero': 0},
    )
    return seq


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_incluye_prestamos_con_vencimiento_en_rango(
    cuenta_usd_proy, socio_proy, secuencia_soc_proy
):
    """
    Préstamo con fecha_vencimiento dentro de los próximos 7 días
    debe reducir la proyección neta.
    """
    hoy = date.today()
    prestamo = PrestamoPorSocio.objects.create(
        socio=socio_proy,
        monto_principal=Decimal('500.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        fecha_prestamo=hoy - timedelta(days=10),
        fecha_vencimiento=hoy + timedelta(days=3),
        estado='ACTIVO',
    )
    # forzar monto_usd ya que el save() lo calcula
    prestamo.refresh_from_db()

    resultado = calcular_proyeccion_caja_7d()

    assert resultado['prestamos_venciendo'] >= Decimal('500.00'), (
        f"Préstamo de 500 USD debe aparecer en prestamos_venciendo, "
        f"obtenido {resultado['prestamos_venciendo']}"
    )
    # proyección neta debe ser menor que saldo_usd
    assert resultado['proyeccion_neta'] < resultado['saldo_usd'], (
        "La proyección neta debe ser < saldo_usd cuando hay préstamo venciendo"
    )


@pytest.mark.django_db
def test_excluye_prestamos_sin_fecha_vencimiento(
    cuenta_usd_proy, socio_proy, secuencia_soc_proy
):
    """
    Préstamo sin fecha_vencimiento (indefinido) no debe sumarse
    a prestamos_venciendo en el horizonte de 7 días.
    """
    hoy = date.today()
    PrestamoPorSocio.objects.create(
        socio=socio_proy,
        monto_principal=Decimal('1000.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        fecha_prestamo=hoy - timedelta(days=5),
        fecha_vencimiento=None,
        estado='ACTIVO',
    )

    resultado = calcular_proyeccion_caja_7d()

    assert resultado['prestamos_venciendo'] == Decimal('0.00'), (
        f"Préstamo sin fecha_vencimiento no debe aparecer; "
        f"obtenido {resultado['prestamos_venciendo']}"
    )


@pytest.mark.django_db
def test_suma_correcta_Decimal(cuenta_usd_proy, cliente_proy, proveedor_proy):
    """
    proyeccion_neta = saldo_usd + cobros_esperados - pagos_a_vencer - prestamos_venciendo
    Verificación con Decimal exacto sin facturas ni préstamos adicionales.
    """
    resultado = calcular_proyeccion_caja_7d()

    expected = (
        resultado['saldo_usd']
        + resultado['cobros_esperados']
        - resultado['pagos_a_vencer']
        - resultado['prestamos_venciendo']
    )
    assert resultado['proyeccion_neta'] == expected, (
        f"proyeccion_neta {resultado['proyeccion_neta']} ≠ fórmula {expected}"
    )
