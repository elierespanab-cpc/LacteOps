# -*- coding: utf-8 -*-
"""
test_tasa_automatica.py — Suite para FIX 2: tasa automática VES (Sprint 4).
Verifica que emitir() detecte TasaCambio de BD o bloquee si no existe.
"""
import pytest
from decimal import Decimal
from datetime import date, timedelta

from apps.almacen.models import UnidadMedida, Categoria
from apps.core.models import Secuencia, TasaCambio
from apps.core.exceptions import EstadoInvalidoError
from apps.ventas.models import Cliente, FacturaVenta


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cliente_tasa(db):
    return Cliente.objects.create(
        nombre='Cliente Tasa Auto',
        rif='J-30000001-0',
        limite_credito=Decimal('5000.00'),
        dias_credito=30,
    )


@pytest.fixture
def secuencia_vta_tasa(db):
    seq, _ = Secuencia.objects.get_or_create(
        tipo_documento='VTA',
        defaults={'prefijo': 'VTA-', 'digitos': 4, 'ultimo_numero': 0},
    )
    return seq


def _factura_ves(cliente, fecha=None, tasa_cambio=None):
    """Helper: crea FacturaVenta VES sin lista_precio (para llegar al check de tasa)."""
    kwargs = dict(
        numero=f'VTA-TASA-{FacturaVenta.objects.count() + 1:04d}',
        cliente=cliente,
        fecha=fecha or date.today(),
        estado='EMITIDA',
        moneda='VES',
        total=Decimal('0.00'),
    )
    if tasa_cambio is not None:
        kwargs['tasa_cambio'] = tasa_cambio
    return FacturaVenta.objects.create(**kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_emitir_ves_sin_tasa_lanza_error(db, cliente_tasa, secuencia_vta_tasa):
    """
    FacturaVenta VES con tasa_cambio en default (1.0) y sin TasaCambio en BD
    debe lanzar EstadoInvalidoError con mensaje de 'sin tasa BCV'.
    """
    factura = _factura_ves(cliente_tasa)
    # No existe TasaCambio en la BD

    with pytest.raises(EstadoInvalidoError) as exc_info:
        factura.emitir()

    assert 'sin tasa BCV' in str(exc_info.value).lower() or 'tasa' in str(exc_info.value).lower(), (
        f"Se esperaba error de tasa BCV, obtenido: {exc_info.value}"
    )


@pytest.mark.django_db
def test_emitir_ves_busca_fecha_futura(db, cliente_tasa, secuencia_vta_tasa):
    """
    Tasa cargada para lunes; documento tiene fecha=sábado (anterior al lunes).
    filter(fecha__gte=sabado) encuentra la tasa del lunes.
    emitir() NO falla por tasa, sino más adelante por lista_precio.
    """
    sabado = date.today() - timedelta(days=date.today().weekday() + 2)  # sábado pasado
    lunes = sabado + timedelta(days=2)  # lunes siguiente al sábado

    TasaCambio.objects.create(fecha=lunes, tasa=Decimal('38.500000'))

    factura = _factura_ves(cliente_tasa, fecha=sabado)

    with pytest.raises(EstadoInvalidoError) as exc_info:
        factura.emitir()

    # El error debe ser de lista_precio, NO de tasa
    error_msg = str(exc_info.value).lower()
    assert 'tasa' not in error_msg or 'lista' in error_msg, (
        f"Se esperaba error de lista_precio, no de tasa. Obtenido: {exc_info.value}"
    )
    assert 'lista' in error_msg, (
        f"Se esperaba error de lista_precio. Obtenido: {exc_info.value}"
    )


@pytest.mark.django_db
def test_emitir_usd_no_requiere_tasa(db, cliente_tasa, secuencia_vta_tasa):
    """
    FacturaVenta USD sin TasaCambio en BD no debe lanzar error de tasa.
    El error esperado es por lista de precios (siguiente validación).
    """
    factura = FacturaVenta.objects.create(
        numero=f'VTA-USD-{FacturaVenta.objects.count() + 1:04d}',
        cliente=cliente_tasa,
        fecha=date.today(),
        estado='EMITIDA',
        moneda='USD',
        total=Decimal('0.00'),
    )
    # No existe TasaCambio en la BD

    with pytest.raises(EstadoInvalidoError) as exc_info:
        factura.emitir()

    # El error NO debe ser de tasa, sino de lista_precio
    error_msg = str(exc_info.value).lower()
    assert 'lista' in error_msg, (
        f"Se esperaba error de lista_precio para USD sin tasa. Obtenido: {exc_info.value}"
    )


@pytest.mark.django_db
def test_tasa_asignada_de_TasaCambio(db, cliente_tasa, secuencia_vta_tasa):
    """
    Después de que emitir() detecta la TasaCambio, self.tasa_cambio == tasa_obj.tasa.
    El test verifica el valor en memoria antes de que el objeto sea persisted por FASE 1.
    """
    tasa_esperada = Decimal('45.250000')
    TasaCambio.objects.create(fecha=date.today(), tasa=tasa_esperada)

    factura = _factura_ves(cliente_tasa)  # tasa_cambio inicial = 1.0 default

    try:
        factura.emitir()
    except EstadoInvalidoError:
        pass  # Esperado: falla en lista_precio, pero tasa ya fue asignada en memoria

    assert factura.tasa_cambio == tasa_esperada, (
        f"tasa_cambio esperada {tasa_esperada}, obtenida {factura.tasa_cambio}"
    )
