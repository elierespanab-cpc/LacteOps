# -*- coding: utf-8 -*-
"""
Servicios del modulo de Socios para LacteOps.

  registrar_prestamo(...)          -> PrestamoPorSocio
  registrar_pago_prestamo(...)     -> PagoPrestamo

RESTRICCIONES:
  - transaction.atomic() + select_for_update() en toda op que modifique saldo.
  - Decimal estricto. NUNCA float.
  - Bimoneda: USD->tasa=1. VES->monto_usd=monto/tasa (ROUND_HALF_UP).
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from apps.bancos.services import registrar_movimiento_caja

logger = logging.getLogger(__name__)


def registrar_prestamo(
    socio,
    monto,
    moneda,
    tasa,
    fecha,
    cuenta_destino=None,
    fecha_vencimiento=None,
    notas='',
):
    """
    Registra un nuevo prestamo recibido de un socio.
    Si cuenta_destino esta definida, genera MovimientoCaja ENTRADA.
    """
    from .models import PrestamoPorSocio

    monto = Decimal(str(monto))
    tasa = Decimal(str(tasa))

    with transaction.atomic():
        prestamo = PrestamoPorSocio.objects.create(
            socio=socio,
            monto_principal=monto,
            moneda=moneda,
            tasa_cambio=tasa,
            fecha_prestamo=fecha,
            fecha_vencimiento=fecha_vencimiento,
            cuenta_destino=cuenta_destino,
            notas=notas,
            monto_usd=Decimal('0.00'),
        )

        if cuenta_destino:
            registrar_movimiento_caja(
                cuenta=cuenta_destino,
                tipo='ENTRADA',
                monto=monto,
                moneda=moneda,
                tasa_cambio=prestamo.tasa_cambio,
                referencia=prestamo.numero,
                notas=f'Prestamo recibido {prestamo.numero} — Socio: {socio}',
            )

    logger.info('Prestamo registrado: %s | Socio: %s | USD: %s',
                prestamo.numero, socio, prestamo.monto_usd)
    return prestamo


def registrar_pago_prestamo(
    prestamo,
    monto,
    moneda,
    tasa,
    fecha,
    cuenta_origen=None,
    notas='',
):
    """
    Registra un pago contra un prestamo activo.
    Genera MovimientoCaja SALIDA si hay cuenta_origen.
    Marca prestamo como CANCELADO si total_pagado_usd >= prestamo.monto_usd.
    """
    from .models import PagoPrestamo
    from apps.bancos.models import CuentaBancaria

    monto = Decimal(str(monto))
    tasa = Decimal(str(tasa))

    if moneda == 'USD':
        monto_usd = monto
        tasa = Decimal('1.000000')
    else:
        monto_usd = (monto / tasa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    with transaction.atomic():
        pago = PagoPrestamo.objects.create(
            prestamo=prestamo,
            monto=monto,
            moneda=moneda,
            tasa_cambio=tasa,
            monto_usd=monto_usd,
            fecha=fecha,
            cuenta_origen=cuenta_origen,
            notas=notas,
        )

        if cuenta_origen:
            cuenta = CuentaBancaria.objects.select_for_update().get(pk=cuenta_origen.pk)
            registrar_movimiento_caja(
                cuenta=cuenta,
                tipo='SALIDA',
                monto=monto,
                moneda=moneda,
                tasa_cambio=tasa,
                referencia=prestamo.numero,
                notas=f'Pago prestamo {prestamo.numero}',
            )

        total_pagado_usd = sum(
            Decimal(str(p.monto_usd)) for p in prestamo.pagos.all()
        )
        if total_pagado_usd >= Decimal(str(prestamo.monto_usd)):
            prestamo.estado = 'CANCELADO'
            prestamo.save(update_fields=['estado'])

    logger.info('Pago prestamo %s | Monto: %s %s | USD: %s | Estado: %s',
                prestamo.numero, monto, moneda, monto_usd, prestamo.estado)
    return pago
