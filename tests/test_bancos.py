# -*- coding: utf-8 -*-
"""
test_bancos.py — Suite de pruebas para el módulo de Tesorería.

Cubre:
  - registrar_movimiento_caja(): ENTRADA aumenta saldo, SALIDA descuenta.
  - Bloqueo de saldo negativo (SaldoInsuficienteError).
  - Atomicidad de TransferenciaCuentas.ejecutar() con rollback.
  - Conversión VES → USD en cobros.
  - Inmutabilidad de MovimientoCaja.
  - Cuenta inactiva rechaza movimientos.
  - ReexpresionMensual: cálculo correcto e idempotencia.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch

from apps.bancos.models import CuentaBancaria, MovimientoCaja, TransferenciaCuentas
from apps.bancos.services import registrar_movimiento_caja, ReexpresionMensual
from apps.core.exceptions import SaldoInsuficienteError, EstadoInvalidoError


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cuenta_usd(db):
    """Cuenta bancaria en USD con saldo inicial de 1000.00."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta Corriente USD',
        moneda='USD',
        saldo_actual=Decimal('1000.00'),
    )


@pytest.fixture
def cuenta_ves(db):
    """Cuenta bancaria en VES con saldo inicial de 500000.00."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta VES Operativa',
        moneda='VES',
        saldo_actual=Decimal('500000.00'),
    )


@pytest.fixture
def cuenta_destino_usd(db):
    """Segunda cuenta USD para tests de transferencia."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta Destino USD',
        moneda='USD',
        saldo_actual=Decimal('0.00'),
    )


@pytest.fixture
def secuencia_tes(db):
    """
    Secuencia TES con contador reseteado a 0.
    La migración secuencias.json la pre-carga; get_or_create la recupera
    y el reset garantiza aislamiento por test.
    """
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


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — ENTRADA aumenta saldo
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_movimiento_entrada_aumenta_saldo(cuenta_usd):
    """
    Un MovimientoCaja ENTRADA debe incrementar saldo_actual de la cuenta.
    """
    saldo_inicial = cuenta_usd.saldo_actual  # Decimal('1000.00')

    mov = registrar_movimiento_caja(
        cuenta=cuenta_usd,
        tipo='ENTRADA',
        monto=Decimal('500.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        referencia='COBRO-VTA-0001',
    )

    cuenta_usd.refresh_from_db()

    assert cuenta_usd.saldo_actual == saldo_inicial + Decimal('500.00')
    assert cuenta_usd.saldo_actual == Decimal('1500.00')
    assert mov.tipo == 'ENTRADA'
    assert mov.monto == Decimal('500.00')
    assert mov.monto_usd == Decimal('500.00')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — SALIDA descuenta saldo
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_movimiento_salida_descuenta_saldo(cuenta_usd):
    """
    Un MovimientoCaja SALIDA debe decrementar saldo_actual de la cuenta.
    """
    registrar_movimiento_caja(
        cuenta=cuenta_usd,
        tipo='SALIDA',
        monto=Decimal('300.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        referencia='PAGO-COM-0001',
    )

    cuenta_usd.refresh_from_db()

    assert cuenta_usd.saldo_actual == Decimal('700.00')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Saldo negativo bloqueado
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_saldo_negativo_bloqueado(cuenta_usd):
    """
    Intentar retirar más del saldo disponible debe lanzar SaldoInsuficienteError
    y el saldo debe permanecer intacto.
    """
    saldo_antes = cuenta_usd.saldo_actual  # Decimal('1000.00')

    with pytest.raises(SaldoInsuficienteError):
        registrar_movimiento_caja(
            cuenta=cuenta_usd,
            tipo='SALIDA',
            monto=Decimal('1500.00'),   # mayor que el saldo
            moneda='USD',
            tasa_cambio=Decimal('1.000000'),
            referencia='PAGO-EXCESO',
        )

    cuenta_usd.refresh_from_db()
    assert cuenta_usd.saldo_actual == saldo_antes
    # No se creó ningún MovimientoCaja
    assert MovimientoCaja.objects.filter(referencia='PAGO-EXCESO').count() == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Atomicidad de TransferenciaCuentas: si el crédito falla, el débito
#           se revierte
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(transaction=True)
def test_transferencia_atomica(cuenta_usd, cuenta_destino_usd, secuencia_tes):
    """
    Si el crédito a cuenta_destino falla (simulado con mock), el débito
    a cuenta_origen debe revertirse en su totalidad.
    """
    saldo_origen_antes = cuenta_usd.saldo_actual        # 1000.00
    saldo_destino_antes = cuenta_destino_usd.saldo_actual  # 0.00

    transferencia = TransferenciaCuentas.objects.create(
        cuenta_origen=cuenta_usd,
        cuenta_destino=cuenta_destino_usd,
        monto_origen=Decimal('400.00'),
        monto_destino=Decimal('400.00'),
        tasa_cambio=Decimal('1.000000'),
    )

    # Simulamos fallo en el segundo registrar_movimiento_caja (el crédito)
    call_count = {'n': 0}
    original_fn = registrar_movimiento_caja.__wrapped__ if hasattr(
        registrar_movimiento_caja, '__wrapped__') else None

    from apps.bancos import services as bancos_services

    original = bancos_services.registrar_movimiento_caja

    def fallo_en_segundo(*args, **kwargs):
        call_count['n'] += 1
        if call_count['n'] == 2:
            raise Exception("Fallo simulado al acreditar destino")
        return original(*args, **kwargs)

    with patch.object(bancos_services, 'registrar_movimiento_caja', side_effect=fallo_en_segundo):
        with pytest.raises(Exception, match='Fallo simulado'):
            transferencia.ejecutar()

    cuenta_usd.refresh_from_db()
    cuenta_destino_usd.refresh_from_db()

    # Ambas cuentas deben tener sus saldos originales (rollback total)
    assert cuenta_usd.saldo_actual == saldo_origen_antes,   "El débito no se revirtió"
    assert cuenta_destino_usd.saldo_actual == saldo_destino_antes, "El crédito no está en cero"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Conversión VES → USD en cobro
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cobro_ves_calcula_usd(cuenta_ves):
    """
    Cobro de 500 000 Bs con tasa=50 → monto_usd debe ser Decimal('10000.00').
    Regla bimoneda: monto_usd = monto / tasa_cambio
    """
    mov = registrar_movimiento_caja(
        cuenta=cuenta_ves,
        tipo='ENTRADA',
        monto=Decimal('500000.00'),
        moneda='VES',
        tasa_cambio=Decimal('50.000000'),
        referencia='COBRO-VES-TEST',
    )

    assert mov.monto == Decimal('500000.00')
    assert mov.moneda == 'VES'
    assert mov.monto_usd == Decimal('10000.00'), (
        f"Se esperaba 10000.00 USD pero se obtuvo {mov.monto_usd}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — MovimientoCaja es inmutable post-creación
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_movimiento_caja_inmutable(cuenta_usd):
    """
    Intentar modificar un MovimientoCaja ya creado debe lanzar ValueError.
    """
    mov = registrar_movimiento_caja(
        cuenta=cuenta_usd,
        tipo='ENTRADA',
        monto=Decimal('200.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        referencia='INMUTABLE-TEST',
    )

    mov.referencia = 'MODIFICADO'
    with pytest.raises((ValueError, Exception)):
        mov.save()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — Cuenta inactiva rechaza movimientos
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cuenta_inactiva_rechaza_movimientos(db):
    """
    Una CuentaBancaria con activa=False no debe recibir movimientos.
    Debe lanzar ValueError.
    """
    cuenta_inactiva = CuentaBancaria.objects.create(
        nombre='Cuenta Cerrada',
        moneda='USD',
        saldo_actual=Decimal('0.00'),
        activa=False,
    )

    with pytest.raises(ValueError, match='inactiva'):
        registrar_movimiento_caja(
            cuenta=cuenta_inactiva,
            tipo='ENTRADA',
            monto=Decimal('100.00'),
            moneda='USD',
            tasa_cambio=Decimal('1.000000'),
            referencia='INACTIVA-TEST',
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8 — TransferenciaCuentas flujo exitoso completo
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_transferencia_exitosa(cuenta_usd, cuenta_destino_usd, secuencia_tes):
    """
    Transferencia exitosa: origen pierde monto, destino lo gana, estado=EJECUTADA.
    """
    transferencia = TransferenciaCuentas.objects.create(
        cuenta_origen=cuenta_usd,
        cuenta_destino=cuenta_destino_usd,
        monto_origen=Decimal('300.00'),
        monto_destino=Decimal('300.00'),
        tasa_cambio=Decimal('1.000000'),
    )

    transferencia.ejecutar()

    cuenta_usd.refresh_from_db()
    cuenta_destino_usd.refresh_from_db()
    transferencia.refresh_from_db()

    assert cuenta_usd.saldo_actual == Decimal('700.00')
    assert cuenta_destino_usd.saldo_actual == Decimal('300.00')
    assert transferencia.estado == 'EJECUTADA'


# ═══════════════════════════════════════════════════════════════════════════════
# Test 9 — ReexpresionMensual calcula variación correctamente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_reexpresion_mensual_calcula_variacion(cuenta_ves):
    """
    Cuenta VES con saldo=600 000.
    tasa_inicio=60, tasa_cierre=50 → el bolívar se apreció.

    usd_antes   = 600 000 / 60 = 10 000
    usd_despues = 600 000 / 50 = 12 000
    variacion   = +2 000 (incremento de valor en USD)
    """
    cuenta_ves.saldo_actual = Decimal('600000.00')
    cuenta_ves.save(update_fields=['saldo_actual'])

    fecha_cierre = date.today().replace(day=28)

    movimientos = ReexpresionMensual.ejecutar(
        tasa_inicio_mes=Decimal('60.000000'),
        tasa_cierre=Decimal('50.000000'),
        fecha_cierre=fecha_cierre,
    )

    assert len(movimientos) == 1
    mov = movimientos[0]
    assert mov.tipo == 'REEXPRESION'
    # variacion_usd = 12000 - 10000 = 2000
    assert mov.monto_usd == Decimal('2000.00'), (
        f"Se esperaba variacion_usd=2000.00 pero se obtuvo {mov.monto_usd}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 10 — ReexpresionMensual es idempotente (rechaza segunda ejecución)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_reexpresion_mensual_idempotente(cuenta_ves):
    """
    Ejecutar ReexpresionMensual dos veces para el mismo mes-año debe lanzar
    ValueError en la segunda llamada.
    """
    fecha_cierre = date.today().replace(day=28)

    ReexpresionMensual.ejecutar(
        tasa_inicio_mes=Decimal('60.000000'),
        tasa_cierre=Decimal('50.000000'),
        fecha_cierre=fecha_cierre,
    )

    with pytest.raises(ValueError, match='Ya existe una Reexpresión Mensual'):
        ReexpresionMensual.ejecutar(
            tasa_inicio_mes=Decimal('50.000000'),
            tasa_cierre=Decimal('45.000000'),
            fecha_cierre=fecha_cierre,
        )
