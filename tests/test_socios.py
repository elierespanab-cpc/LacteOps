# -*- coding: utf-8 -*-
"""
test_socios.py — Suite para PrestamoPorSocio y PagoPrestamo (Sprint 3).

Cubre:
  - Auto-numeración SOC-XXXX en creación.
  - Generación de MovimientoCaja ENTRADA al registrar un préstamo con cuenta.
  - Estado ACTIVO tras pago parcial.
  - Estado CANCELADO tras pago total (total_pagado_usd >= monto_usd).
  - Préstamo corriente (vence <= hoy+365) aparece en pasivo_corriente del Capital de Trabajo.
  - Préstamo sin fecha_vencimiento va al pasivo_no_corriente.

REGLA: todas las aserciones numéricas usan Decimal exacto, NUNCA float.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from django.contrib.auth.models import User, Permission
from django.urls import reverse

from apps.bancos.models import CuentaBancaria, MovimientoCaja
from apps.core.models import Secuencia
from apps.socios.models import Socio, PrestamoPorSocio
from apps.socios.services import registrar_prestamo, registrar_pago_prestamo


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures locales
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def socio(db):
    """Socio de prueba para todos los tests de este módulo."""
    return Socio.objects.create(nombre='Juan García', rif='V-12345678')


@pytest.fixture
def cuenta_usd_socios(db):
    """Cuenta USD con saldo 5000.00 para pagos/recepción de préstamos."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta Principal USD Socios',
        moneda='USD',
        saldo_actual=Decimal('5000.00'),
    )


@pytest.fixture
def secuencia_soc(db):
    """
    Secuencia SOC reseteada a 0 para garantizar aislamiento entre tests.
    Usa get_or_create porque la migración puede haberla pre-insertado.
    """
    seq, _ = Secuencia.objects.get_or_create(
        tipo_documento='SOC',
        defaults={'ultimo_numero': 0, 'prefijo': 'SOC-', 'digitos': 4},
    )
    seq.ultimo_numero = 0
    seq.prefijo = 'SOC-'
    seq.digitos = 4
    seq.save(update_fields=['ultimo_numero', 'prefijo', 'digitos'])
    return seq


@pytest.fixture
def user_viewer_socios(db):
    """Usuario con permiso view_reportelink para acceder al reporte Capital de Trabajo."""
    user = User.objects.create_user(username='viewer_socios', password='123')
    perm = Permission.objects.get(
        codename='view_reportelink', content_type__app_label='reportes'
    )
    user.user_permissions.add(perm)
    return user


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Auto-numeración SOC-XXXX
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_prestamo_numero_serie_SOC(socio, secuencia_soc):
    """El número generado debe tener prefijo 'SOC-' seguido de dígitos."""
    prestamo = PrestamoPorSocio.objects.create(
        socio=socio,
        monto_principal=Decimal('1000.00'),
        moneda='USD',
        fecha_prestamo=date.today(),
    )
    assert prestamo.numero.startswith('SOC-'), (
        f'Se esperaba prefijo SOC-, obtenido: {prestamo.numero}'
    )
    # SOC- (4 chars) + al menos 4 dígitos = mínimo 8 chars
    assert len(prestamo.numero) >= 8, (
        f'Número demasiado corto: {prestamo.numero}'
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Préstamo con cuenta_destino genera MovimientoCaja ENTRADA
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_prestamo_genera_movimiento_caja_entrada(socio, cuenta_usd_socios, secuencia_soc):
    """
    registrar_prestamo() con cuenta_destino debe:
      - Crear MovimientoCaja de tipo ENTRADA en la cuenta.
      - Aumentar el saldo de la cuenta en monto del préstamo.
    """
    saldo_inicial = cuenta_usd_socios.saldo_actual

    prestamo = registrar_prestamo(
        socio=socio,
        monto=Decimal('2000.00'),
        moneda='USD',
        tasa=Decimal('1.000000'),
        fecha=date.today(),
        cuenta_destino=cuenta_usd_socios,
    )

    cuenta_usd_socios.refresh_from_db()
    assert cuenta_usd_socios.saldo_actual == saldo_inicial + Decimal('2000.00')

    mov = MovimientoCaja.objects.filter(
        cuenta=cuenta_usd_socios,
        tipo='ENTRADA',
        referencia=prestamo.numero,
    ).first()
    assert mov is not None, 'No se creó MovimientoCaja ENTRADA para el préstamo'
    assert mov.monto == Decimal('2000.00')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Pago parcial deja el préstamo en ACTIVO
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_pago_parcial_estado_activo(socio, cuenta_usd_socios, secuencia_soc):
    """
    Un pago por monto menor al monto_usd del préstamo
    no debe cambiar el estado (debe permanecer ACTIVO).
    """
    prestamo = registrar_prestamo(
        socio=socio,
        monto=Decimal('1000.00'),
        moneda='USD',
        tasa=Decimal('1.000000'),
        fecha=date.today(),
    )

    registrar_pago_prestamo(
        prestamo=prestamo,
        monto=Decimal('400.00'),
        moneda='USD',
        tasa=Decimal('1.000000'),
        fecha=date.today(),
        cuenta_origen=cuenta_usd_socios,
    )

    prestamo.refresh_from_db()
    assert prestamo.estado == 'ACTIVO', (
        f'Estado debería ser ACTIVO, obtenido: {prestamo.estado}'
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Pago total cambia el estado a CANCELADO
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_pago_total_estado_cancelado(socio, cuenta_usd_socios, secuencia_soc):
    """
    Cuando total_pagado_usd >= monto_usd del préstamo, el estado
    debe cambiar automáticamente a CANCELADO.
    """
    prestamo = registrar_prestamo(
        socio=socio,
        monto=Decimal('1000.00'),
        moneda='USD',
        tasa=Decimal('1.000000'),
        fecha=date.today(),
    )

    registrar_pago_prestamo(
        prestamo=prestamo,
        monto=Decimal('1000.00'),
        moneda='USD',
        tasa=Decimal('1.000000'),
        fecha=date.today(),
        cuenta_origen=cuenta_usd_socios,
    )

    prestamo.refresh_from_db()
    assert prestamo.estado == 'CANCELADO', (
        f'Estado debería ser CANCELADO, obtenido: {prestamo.estado}'
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Préstamo corriente suma al pasivo_corriente en Capital de Trabajo
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_prestamo_corriente_en_capital_trabajo(
    client, user_viewer_socios, socio, secuencia_soc
):
    """
    Un préstamo ACTIVO con fecha_vencimiento <= hoy+365 días debe aparecer
    en el contexto 'prestamos_corriente' del reporte de Capital de Trabajo.
    """
    hoy = date.today()
    PrestamoPorSocio.objects.create(
        socio=socio,
        monto_principal=Decimal('1500.00'),
        moneda='USD',
        fecha_prestamo=hoy,
        fecha_vencimiento=hoy + timedelta(days=90),  # dentro de los próximos 365 días
        estado='ACTIVO',
    )

    client.force_login(user_viewer_socios)
    url = reverse('reportes:capital_trabajo')
    response = client.get(url, {
        'valorar_inventario': 'COSTO',
        'fecha_corte': str(hoy),
    })

    assert response.status_code == 200
    ctx = response.context
    assert ctx['prestamos_corriente'] == Decimal('1500.00'), (
        f"prestamos_corriente esperado 1500.00, obtenido {ctx['prestamos_corriente']}"
    )
    assert ctx['pasivo_corriente'] >= Decimal('1500.00')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — Préstamo sin fecha_vencimiento va al pasivo_no_corriente
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_prestamo_sin_fecha_es_no_corriente(
    client, user_viewer_socios, socio, secuencia_soc
):
    """
    Un préstamo ACTIVO sin fecha_vencimiento debe clasificarse como
    no corriente (no debe aparecer en prestamos_corriente).
    """
    hoy = date.today()
    PrestamoPorSocio.objects.create(
        socio=socio,
        monto_principal=Decimal('3000.00'),
        moneda='USD',
        fecha_prestamo=hoy,
        fecha_vencimiento=None,
        estado='ACTIVO',
    )

    client.force_login(user_viewer_socios)
    url = reverse('reportes:capital_trabajo')
    response = client.get(url, {
        'valorar_inventario': 'COSTO',
        'fecha_corte': str(hoy),
    })

    assert response.status_code == 200
    ctx = response.context
    assert ctx['prestamos_no_corriente'] == Decimal('3000.00'), (
        f"prestamos_no_corriente esperado 3000.00, obtenido {ctx['prestamos_no_corriente']}"
    )
    # No debe contaminarse el corriente
    assert ctx['prestamos_corriente'] == Decimal('0.00'), (
        f"prestamos_corriente debería ser 0.00, obtenido {ctx['prestamos_corriente']}"
    )
