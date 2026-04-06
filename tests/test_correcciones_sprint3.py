# -*- coding: utf-8 -*-
"""
test_correcciones_sprint3.py — Suite de regresión para las correcciones del Sprint 3 (B-QA).

Cubre:
  - Bimoneda: Pago VES → monto_usd calculado con ROUND_HALF_UP correctamente.
  - Cobro VES → genera MovimientoCaja ENTRADA en la cuenta destino.
  - OrdenProduccion CERRADA bloquea edición (EstadoInvalidoError).
  - reabrir() sin Master/Administrador lanza PermissionDenied.
  - CxP con pago parcial aparece en el reporte con el saldo correcto.
  - FacturaVenta auto-numerada con formato VTA-XXXX.

REGLA: todas las aserciones numéricas usan Decimal exacto, NUNCA float.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from django.contrib.auth.models import User, Permission
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.test import override_settings

from apps.bancos.models import CuentaBancaria, MovimientoCaja
from apps.compras.models import FacturaCompra, Pago
from apps.ventas.models import FacturaVenta, Cobro
from apps.core.models import Secuencia
from apps.core.exceptions import EstadoInvalidoError


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures locales
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def user_viewer_corr(db):
    """Usuario con permiso view_reportelink para acceder a reportes."""
    user = User.objects.create_user(username='viewer_corr', password='123')
    perm = Permission.objects.get(
        codename='view_reportelink', content_type__app_label='reportes'
    )
    user.user_permissions.add(perm)
    return user


@pytest.fixture
def cuenta_ves_sprint3(db):
    """Cuenta VES con saldo 600000.00 para pruebas de pagos/cobros en VES."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta VES Sprint3',
        moneda='VES',
        saldo_actual=Decimal('600000.00'),
    )


@pytest.fixture
def cuenta_usd_sprint3(db):
    """Cuenta USD con saldo 0.00 para recibir cobros."""
    return CuentaBancaria.objects.create(
        nombre='Cuenta USD Sprint3',
        moneda='USD',
        saldo_actual=Decimal('0.00'),
    )


@pytest.fixture
def secuencia_vta(db):
    """
    Secuencia VTA reseteada a 0 para garantizar formato VTA-0001 predecible.
    """
    seq, _ = Secuencia.objects.get_or_create(
        tipo_documento='VTA',
        defaults={'ultimo_numero': 0, 'prefijo': 'VTA-', 'digitos': 4},
    )
    seq.ultimo_numero = 0
    seq.prefijo = 'VTA-'
    seq.digitos = 4
    seq.save(update_fields=['ultimo_numero', 'prefijo', 'digitos'])
    return seq


@pytest.fixture
def secuencia_pro(db):
    """Secuencia PRO reseteada para órdenes de producción."""
    seq, _ = Secuencia.objects.get_or_create(
        tipo_documento='PRO',
        defaults={'ultimo_numero': 0, 'prefijo': 'PRO-', 'digitos': 4},
    )
    seq.ultimo_numero = 0
    seq.save(update_fields=['ultimo_numero'])
    return seq


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Pago VES: monto_usd calculado correctamente con ROUND_HALF_UP
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_pago_ves_monto_usd_correcto(proveedor, cuenta_ves_sprint3):
    """
    Pago en VES: monto=500000, tasa_cambio=50 → monto_usd = 500000/50 = 10000.00
    Verifica la corrección B5+B6 (bimoneda ROUND_HALF_UP en Pago.registrar()).
    """
    factura = FacturaCompra.objects.create(
        numero='COM-TEST-VES-1',
        proveedor=proveedor,
        fecha=date.today(),
        moneda='VES',
        tasa_cambio=Decimal('50.000000'),
        estado='APROBADA',
        total=Decimal('10000.00'),
    )
    pago = Pago.objects.create(
        factura=factura,
        fecha=date.today(),
        monto=Decimal('500000.00'),
        moneda='VES',
        tasa_cambio=Decimal('50.000000'),
        cuenta_origen=cuenta_ves_sprint3,
        medio_pago='TRANSFERENCIA_VES',
    )

    pago.registrar()
    pago.refresh_from_db()

    assert pago.monto_usd == Decimal('10000.00'), (
        f'monto_usd esperado 10000.00, obtenido {pago.monto_usd}'
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Cobro VES genera MovimientoCaja ENTRADA
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_cobro_ves_genera_movimiento_caja(cliente, cuenta_ves_sprint3):
    """
    Un Cobro en VES con cuenta_destino debe crear un MovimientoCaja ENTRADA
    con el monto en VES registrado correctamente.
    Verifica la corrección B5+B6 (bimoneda en Cobro.registrar()).
    """
    factura = FacturaVenta.objects.create(
        numero='VTA-TEST-VES-1',
        cliente=cliente,
        fecha=date.today(),
        estado='EMITIDA',
        total=Decimal('10000.00'),
    )
    cobro = Cobro.objects.create(
        factura=factura,
        fecha=date.today(),
        monto=Decimal('500000.00'),
        moneda='VES',
        tasa_cambio=Decimal('50.000000'),
        cuenta_destino=cuenta_ves_sprint3,
        medio_pago='TRANSFERENCIA_VES',
    )

    cobro.registrar()

    mov = MovimientoCaja.objects.filter(
        cuenta=cuenta_ves_sprint3,
        tipo='ENTRADA',
    ).first()
    assert mov is not None, 'No se creó MovimientoCaja ENTRADA para el cobro VES'
    assert mov.monto == Decimal('500000.00'), (
        f'Monto esperado 500000.00, obtenido {mov.monto}'
    )
    assert mov.moneda == 'VES'


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — OrdenProduccion CERRADA bloquea edición
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_orden_cerrada_no_editable(receta, secuencia_pro):
    """
    Una OrdenProduccion con estado CERRADA en BD debe lanzar EstadoInvalidoError
    al intentar guardar cualquier modificación (corrección B2).
    """
    from apps.produccion.models import OrdenProduccion

    orden = OrdenProduccion.objects.create(receta=receta)
    assert orden.estado == 'ABIERTA'

    # Forzar estado CERRADA directamente en BD (sin pasar por cerrar())
    OrdenProduccion.objects.filter(pk=orden.pk).update(estado='CERRADA')
    orden.refresh_from_db()
    assert orden.estado == 'CERRADA'

    # Cualquier save() sobre la instancia debe fallar
    with pytest.raises(EstadoInvalidoError):
        orden.notas = 'Intento de modificación inválido'
        orden.save()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — reabrir() sin permisos lanza PermissionDenied
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_reabrir_requiere_master_o_admin(receta, secuencia_pro):
    """
    Un usuario sin grupo Master ni Administrador no puede reabrir
    una OrdenProduccion CERRADA. Debe lanzar PermissionDenied (corrección B2).
    """
    from apps.produccion.models import OrdenProduccion

    usuario_basico = User.objects.create_user(
        username='operador_basico', password='pass'
    )

    orden = OrdenProduccion.objects.create(receta=receta)
    OrdenProduccion.objects.filter(pk=orden.pk).update(estado='CERRADA')
    orden.refresh_from_db()

    with pytest.raises(PermissionDenied):
        orden.reabrir(usuario_basico, 'motivo de prueba')


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — CxP con pago parcial aparece en el reporte con saldo correcto
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
def test_cxp_con_pago_parcial_aparece_en_reporte(client, user_viewer_corr, proveedor):
    """
    Una FacturaCompra APROBADA con un pago parcial debe aparecer en el reporte CxP
    con el saldo pendiente correcto = total - total_pagado (corrección B3).
    """
    factura = FacturaCompra.objects.create(
        numero='COM-CXP-001',
        proveedor=proveedor,
        fecha=date.today(),
        fecha_vencimiento=date.today() + timedelta(days=30),
        estado='APROBADA',
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        total=Decimal('1000.00'),
    )
    # Pago parcial: 200 USD — se establece monto_usd directamente (sin registrar())
    Pago.objects.create(
        factura=factura,
        fecha=date.today(),
        monto=Decimal('200.00'),
        moneda='USD',
        tasa_cambio=Decimal('1.000000'),
        monto_usd=Decimal('200.00'),
        medio_pago='TRANSFERENCIA_USD',
    )

    client.force_login(user_viewer_corr)
    url = reverse('reportes:cxp')
    response = client.get(url, {
        'fecha_corte': str(date.today()),
        'tipo': 'COMPRAS',
    })

    assert response.status_code == 200
    resultados = response.context['resultados']
    facturas_cxp = [
        r for r in resultados
        if not r.get('es_gasto', True)
        and r['documento'].numero == 'COM-CXP-001'
    ]
    assert len(facturas_cxp) == 1, (
        f'La factura COM-CXP-001 no aparece en el reporte CxP. '
        f'Resultados: {[r["documento"].numero for r in resultados]}'
    )
    assert facturas_cxp[0]['saldo'] == Decimal('800.00'), (
        f"Saldo esperado 800.00, obtenido {facturas_cxp[0]['saldo']}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — FacturaVenta auto-numerada con formato VTA-XXXX
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
def test_numeracion_vta_formato(cliente, secuencia_vta):
    """
    Una FacturaVenta creada sin especificar número debe recibir automáticamente
    un número con prefijo 'VTA-' (corrección B7 — auto-numeración).
    """
    factura = FacturaVenta.objects.create(
        cliente=cliente,
        fecha=date.today(),
    )
    assert factura.numero.startswith('VTA-'), (
        f'Formato incorrecto: se esperaba VTA-XXXX, obtenido {factura.numero}'
    )
    # VTA- (4 chars) + 4 dígitos = 8 chars mínimo
    assert len(factura.numero) >= 8, (
        f'Número demasiado corto: {factura.numero}'
    )
    # El número debe ser exactamente VTA-0001 si la secuencia está en 0
    assert factura.numero == 'VTA-0001', (
        f'Se esperaba VTA-0001, obtenido {factura.numero}'
    )
