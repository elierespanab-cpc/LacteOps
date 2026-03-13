# -*- coding: utf-8 -*-
"""
test_tesoreria_directa.py — Suite para ejecutar_movimiento_tesoreria (Sprint 3).

Cubre:
  - CARGO reduce el saldo de la cuenta.
  - ABONO aumenta el saldo de la cuenta.
  - CARGO con saldo insuficiente lanza SaldoInsuficienteError.
  - MovimientoTesoreria es inmutable: segundo save() lanza EstadoInvalidoError.
  - Categoría con contexto='FACTURA' es rechazada (EstadoInvalidoError).

REGLA: todas las aserciones numéricas usan Decimal exacto, NUNCA float.
"""
import pytest
from decimal import Decimal
from datetime import date

from django.contrib.auth.models import User

from apps.bancos.models import CuentaBancaria, MovimientoTesoreria
from apps.bancos.services import ejecutar_movimiento_tesoreria
from apps.core.models import CategoriaGasto, Secuencia
from apps.core.exceptions import SaldoInsuficienteError, EstadoInvalidoError


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures locales
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cuenta_usd_tes(db):
    """Cuenta USD con saldo 2000.00 para tests de tesorería."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta Tesorería USD',
        moneda='USD',
        saldo_actual=Decimal('2000.00'),
    )


@pytest.fixture
def categoria_tes(db):
    """CategoriaGasto con contexto='TESORERIA' para movimientos de tesorería."""
    cat, _ = CategoriaGasto.objects.get_or_create(
        nombre='Gastos Generales',
        contexto='TESORERIA',
        defaults={'activa': True},
    )
    return cat


@pytest.fixture
def categoria_factura(db):
    """CategoriaGasto con contexto='FACTURA' — debe ser rechazada por tesorería."""
    cat, _ = CategoriaGasto.objects.get_or_create(
        nombre='Insumos de Compra',
        contexto='FACTURA',
        defaults={'activa': True},
    )
    return cat


@pytest.fixture
def secuencia_tes(db):
    """
    Secuencia TES reseteada a 0.
    Compartida con TransferenciaCuentas; el reset garantiza aislamiento.
    """
    seq, _ = Secuencia.objects.get_or_create(
        tipo_documento='TES',
        defaults={'ultimo_numero': 0, 'prefijo': 'TES-', 'digitos': 4},
    )
    seq.ultimo_numero = 0
    seq.prefijo = 'TES-'
    seq.digitos = 4
    seq.save(update_fields=['ultimo_numero', 'prefijo', 'digitos'])
    return seq


@pytest.fixture
def usuario_tes(db):
    """Usuario para registrar movimientos de tesorería."""
    return User.objects.create_user(username='tesorero', password='pass123')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — CARGO reduce el saldo
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cargo_disminuye_saldo(cuenta_usd_tes, categoria_tes, secuencia_tes, usuario_tes):
    """
    Un movimiento CARGO de 300 USD debe reducir el saldo de la cuenta
    en exactamente 300.00 USD.
    """
    saldo_inicial = cuenta_usd_tes.saldo_actual

    ejecutar_movimiento_tesoreria(
        cuenta=cuenta_usd_tes,
        tipo='CARGO',
        monto=Decimal('300.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        categoria=categoria_tes,
        descripcion='Pago servicio de limpieza',
        fecha=date.today(),
        usuario=usuario_tes,
    )

    cuenta_usd_tes.refresh_from_db()
    assert cuenta_usd_tes.saldo_actual == saldo_inicial - Decimal('300.00'), (
        f'Saldo esperado {saldo_inicial - Decimal("300.00")}, '
        f'obtenido {cuenta_usd_tes.saldo_actual}'
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — ABONO aumenta el saldo
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_abono_aumenta_saldo(cuenta_usd_tes, categoria_tes, secuencia_tes, usuario_tes):
    """
    Un movimiento ABONO de 500 USD debe incrementar el saldo de la cuenta
    en exactamente 500.00 USD.
    """
    saldo_inicial = cuenta_usd_tes.saldo_actual

    ejecutar_movimiento_tesoreria(
        cuenta=cuenta_usd_tes,
        tipo='ABONO',
        monto=Decimal('500.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        categoria=categoria_tes,
        descripcion='Reembolso de gasto de viaje',
        fecha=date.today(),
        usuario=usuario_tes,
    )

    cuenta_usd_tes.refresh_from_db()
    assert cuenta_usd_tes.saldo_actual == saldo_inicial + Decimal('500.00'), (
        f'Saldo esperado {saldo_inicial + Decimal("500.00")}, '
        f'obtenido {cuenta_usd_tes.saldo_actual}'
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — CARGO con saldo insuficiente lanza SaldoInsuficienteError
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cargo_saldo_insuficiente_lanza_error(
    cuenta_usd_tes, categoria_tes, secuencia_tes, usuario_tes
):
    """
    Un CARGO mayor al saldo disponible debe lanzar SaldoInsuficienteError
    y el saldo de la cuenta no debe cambiar (rollback atómico).
    """
    saldo_inicial = cuenta_usd_tes.saldo_actual  # 2000.00

    with pytest.raises(SaldoInsuficienteError):
        ejecutar_movimiento_tesoreria(
            cuenta=cuenta_usd_tes,
            tipo='CARGO',
            monto=Decimal('99999.00'),  # mucho mayor que 2000.00
            moneda='USD',
            tasa_cambio=Decimal('1.000000'),
            categoria=categoria_tes,
            descripcion='Cargo imposible',
            fecha=date.today(),
            usuario=usuario_tes,
        )

    # El saldo no debe haber cambiado gracias al rollback atómico
    cuenta_usd_tes.refresh_from_db()
    assert cuenta_usd_tes.saldo_actual == saldo_inicial, (
        f'Saldo no debe cambiar tras error. Esperado {saldo_inicial}, '
        f'obtenido {cuenta_usd_tes.saldo_actual}'
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — MovimientoTesoreria es inmutable
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_movimiento_tesoreria_inmutable(
    cuenta_usd_tes, categoria_tes, secuencia_tes, usuario_tes
):
    """
    Una vez creado, un MovimientoTesoreria no puede ser guardado de nuevo.
    Un segundo save() debe lanzar EstadoInvalidoError.
    """
    mov = ejecutar_movimiento_tesoreria(
        cuenta=cuenta_usd_tes,
        tipo='CARGO',
        monto=Decimal('100.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        categoria=categoria_tes,
        descripcion='Gasto de oficina',
        fecha=date.today(),
        usuario=usuario_tes,
    )

    # mov es el MovimientoTesoreria retornado por el servicio
    assert isinstance(mov, MovimientoTesoreria)

    with pytest.raises(EstadoInvalidoError):
        mov.descripcion = 'Intento de modificación post-creación'
        mov.save()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Categoría con contexto FACTURA es rechazada
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_categoria_contexto_factura_rechazada(
    cuenta_usd_tes, categoria_factura, secuencia_tes, usuario_tes
):
    """
    Si la categoría tiene contexto='FACTURA' (en lugar de 'TESORERIA'),
    ejecutar_movimiento_tesoreria debe lanzar EstadoInvalidoError
    sin crear ningún movimiento.
    """
    assert categoria_factura.contexto == 'FACTURA'

    with pytest.raises(EstadoInvalidoError):
        ejecutar_movimiento_tesoreria(
            cuenta=cuenta_usd_tes,
            tipo='CARGO',
            monto=Decimal('100.00'),
            moneda='USD',
            tasa_cambio=Decimal('1.000000'),
            categoria=categoria_factura,
            descripcion='Intento inválido con categoría de factura',
            fecha=date.today(),
            usuario=usuario_tes,
        )

    # No se debe haber creado ningún MovimientoTesoreria
    assert MovimientoTesoreria.objects.count() == 0
