# -*- coding: utf-8 -*-
"""
test_gastos.py — Suite de pruebas para gastos/pagos de la tesorería.

En el Sprint 1 los gastos operativos se registran como MovimientoCaja SALIDA
en la CuentaBancaria, y los cobros de ventas como ENTRADA. Este archivo
valida las reglas de negocio relacionadas con el movimiento de efectivo:

  - Gasto (salida de caja) descuenta saldo correctamente.
  - Gasto mayor al saldo disponible se bloquea (SaldoInsuficienteError).
  - Cobro de factura VES: monto_usd se calcula correctamente.
  - Cobro sin cuenta_destino no genera MovimientoCaja (solo registro contable).
  - Cobro con cuenta_destino aumenta saldo de la cuenta.
  - Transferencia entre cuentas ejecutada correctamente (débito/crédito).
  - Transferencia ejecutada no puede re-ejecutarse.
  - Transferencia ejecutada puede anularse generando movimientos inversos.
"""
import pytest
from decimal import Decimal
from datetime import date

from apps.bancos.models import CuentaBancaria, MovimientoCaja, TransferenciaCuentas
from apps.bancos.services import registrar_movimiento_caja
from apps.core.exceptions import SaldoInsuficienteError, EstadoInvalidoError
from apps.ventas.models import FacturaVenta, Cobro, Cliente


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cuenta_operativa(db):
    """Cuenta USD con saldo operativo para pagos de gastos."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta Operativa',
        moneda='USD',
        saldo_actual=Decimal('2000.00'),
    )


@pytest.fixture
def cuenta_ves_gastos(db):
    """Cuenta VES para cobros en bolívares."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta VES',
        moneda='VES',
        saldo_actual=Decimal('0.00'),
    )


@pytest.fixture
def cuenta_secund(db):
    """Cuenta USD secundaria para transferencias."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta Secundaria USD',
        moneda='USD',
        saldo_actual=Decimal('500.00'),
    )


@pytest.fixture
def secuencia_tes(db):
    from apps.core.models import Secuencia
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
def factura_emitida(db, cliente):
    """FacturaVenta EMITIDA con total=200.00 USD."""
    fv = FacturaVenta.objects.create(
        numero='VTA-GASTO-01',
        cliente=cliente,
        fecha=date.today(),
        estado='EMITIDA',
        total=Decimal('200.00'),
    )
    # Asignamos total directamente ya que no hay detalles en este fixture
    FacturaVenta.objects.filter(pk=fv.pk).update(total=Decimal('200.00'))
    fv.refresh_from_db()
    return fv


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Gasto (SALIDA) descuenta saldo
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_gasto_descuenta_saldo(cuenta_operativa):
    """
    Registrar una SALIDA de 350.00 USD desde cuenta_operativa con saldo=2000.00
    debe dejar saldo_actual=1650.00.
    """
    registrar_movimiento_caja(
        cuenta=cuenta_operativa,
        tipo='SALIDA',
        monto=Decimal('350.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        referencia='GASTO-SERV-001',
        notas='Pago servicio eléctrico',
    )

    cuenta_operativa.refresh_from_db()
    assert cuenta_operativa.saldo_actual == Decimal('1650.00')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Gasto mayor al saldo bloqueado
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_gasto_mayor_saldo_bloqueado(cuenta_operativa):
    """
    Un gasto superior al saldo disponible debe lanzar SaldoInsuficienteError
    y el saldo debe quedar intacto.
    """
    saldo_antes = cuenta_operativa.saldo_actual  # 2000.00

    with pytest.raises(SaldoInsuficienteError):
        registrar_movimiento_caja(
            cuenta=cuenta_operativa,
            tipo='SALIDA',
            monto=Decimal('5000.00'),
            moneda='USD',
            tasa_cambio=Decimal('1.000000'),
            referencia='GASTO-EXCESO',
        )

    cuenta_operativa.refresh_from_db()
    assert cuenta_operativa.saldo_actual == saldo_antes


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Cobro VES: monto_usd calculado correctamente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cobro_ves_calcula_monto_usd(cuenta_ves_gastos):
    """
    Cobro de 1 000 000 Bs con tasa=40 → monto_usd = 1 000 000 / 40 = 25 000.00 USD.
    Regla bimoneda invariante.
    """
    mov = registrar_movimiento_caja(
        cuenta=cuenta_ves_gastos,
        tipo='ENTRADA',
        monto=Decimal('1000000.00'),
        moneda='VES',
        tasa_cambio=Decimal('40.000000'),
        referencia='COBRO-VES-001',
    )

    assert mov.monto_usd == Decimal('25000.00')
    assert mov.moneda == 'VES'
    assert mov.tasa_cambio == Decimal('40.000000')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Cobro sin cuenta_destino no genera MovimientoCaja
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cobro_sin_cuenta_no_genera_movimiento(factura_emitida):
    """
    Cobro.registrar() con cuenta_destino=None solo registra el cobro
    contablemente pero NO crea MovimientoCaja.
    """
    cobro = Cobro.objects.create(
        factura=factura_emitida,
        fecha=date.today(),
        monto=Decimal('200.00'),
        medio_pago='EFECTIVO_USD',
        cuenta_destino=None,
    )

    movimientos_antes = MovimientoCaja.objects.count()
    cobro.registrar()
    movimientos_despues = MovimientoCaja.objects.count()

    assert movimientos_despues == movimientos_antes, (
        "No debe generarse MovimientoCaja si no hay cuenta_destino"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Cobro con cuenta_destino aumenta saldo de la cuenta
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cobro_con_cuenta_aumenta_saldo(factura_emitida, cuenta_operativa):
    """
    Cobro.registrar() con cuenta_destino definida debe:
      1. Crear 1 MovimientoCaja ENTRADA.
      2. Aumentar saldo de cuenta_operativa.
      3. Registrar monto_usd correctamente.
    """
    saldo_antes = cuenta_operativa.saldo_actual  # 2000.00

    cobro = Cobro.objects.create(
        factura=factura_emitida,
        fecha=date.today(),
        monto=Decimal('200.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        medio_pago='TRANSFERENCIA_USD',
        cuenta_destino=cuenta_operativa,
    )
    cobro.registrar()

    cuenta_operativa.refresh_from_db()
    cobro.refresh_from_db()

    assert cuenta_operativa.saldo_actual == saldo_antes + Decimal('200.00')
    assert cobro.monto_usd == Decimal('200.00')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — Transferencia ejecutada no puede re-ejecutarse
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_transferencia_ejecutada_no_puede_re_ejecutarse(
        cuenta_operativa, cuenta_secund, secuencia_tes):
    """
    Una TransferenciaCuentas ya en estado EJECUTADA no puede ejecutarse
    de nuevo → EstadoInvalidoError.
    """
    t = TransferenciaCuentas.objects.create(
        cuenta_origen=cuenta_operativa,
        cuenta_destino=cuenta_secund,
        monto_origen=Decimal('100.00'),
        monto_destino=Decimal('100.00'),
        tasa_cambio=Decimal('1.000000'),
    )
    t.ejecutar()

    with pytest.raises(EstadoInvalidoError):
        t.ejecutar()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — Transferencia ejecutada puede anularse (movimientos inversos)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_transferencia_anulacion_genera_inversos(
        cuenta_operativa, cuenta_secund, secuencia_tes):
    """
    Anular una TransferenciaCuentas EJECUTADA debe:
      - Devolver el monto al origen.
      - Retirar el monto del destino.
      - Estado → ANULADA.
    """
    saldo_origen_inicial = cuenta_operativa.saldo_actual  # 2000.00
    saldo_destino_inicial = cuenta_secund.saldo_actual   # 500.00

    t = TransferenciaCuentas.objects.create(
        cuenta_origen=cuenta_operativa,
        cuenta_destino=cuenta_secund,
        monto_origen=Decimal('200.00'),
        monto_destino=Decimal('200.00'),
        tasa_cambio=Decimal('1.000000'),
    )
    t.ejecutar()

    # Verificar estado intermedio
    cuenta_operativa.refresh_from_db()
    cuenta_secund.refresh_from_db()
    assert cuenta_operativa.saldo_actual == saldo_origen_inicial - Decimal('200.00')
    assert cuenta_secund.saldo_actual == saldo_destino_inicial + Decimal('200.00')

    # Anular
    t.anular()

    cuenta_operativa.refresh_from_db()
    cuenta_secund.refresh_from_db()
    t.refresh_from_db()

    # Saldos deben regresar al estado inicial
    assert cuenta_operativa.saldo_actual == saldo_origen_inicial
    assert cuenta_secund.saldo_actual == saldo_destino_inicial
    assert t.estado == 'ANULADA'
