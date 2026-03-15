# -*- coding: utf-8 -*-
"""
Servicios transversales del núcleo de LacteOps.

  generar_numero(tipo_documento) → str
    Único punto de entrada para la numeración automática de documentos.
    Usa select_for_update() dentro de transaction.atomic() para garantizar
    correlatividad sin duplicados ni huecos en entornos concurrentes.
"""
import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def get_tasa_para_fecha(fecha):
    """
    Retorna la TasaCambio más reciente disponible en o antes de la fecha dada.
    Si no existe ninguna en o antes, devuelve la más próxima posterior.
    Retorna None si no hay ninguna tasa registrada.

    Args:
        fecha (date): Fecha para la cual se busca la tasa BCV.

    Returns:
        TasaCambio | None
    """
    from apps.core.models import TasaCambio
    tasa = TasaCambio.objects.filter(fecha__lte=fecha).order_by('-fecha').first()
    if tasa is None:
        tasa = TasaCambio.objects.filter(fecha__gt=fecha).order_by('fecha').first()
    return tasa


def generar_numero(tipo_documento: str) -> str:
    """
    Genera el próximo número correlativo para un tipo de documento.

    Formato de salida: ``{prefijo}-{numero_zfill(digitos)}``
    Ejemplo: ``VTA-0001``, ``COM-0042``, ``PRO-0007``

    Args:
        tipo_documento (str): Clave de la secuencia (ej. 'VTA', 'COM', 'INV').

    Returns:
        str: Número formateado con prefijo y ceros a la izquierda.

    Raises:
        Secuencia.DoesNotExist: Si no existe una secuencia para ese tipo_documento.
    """
    # Import tardío para evitar circular imports (core importa a sí mismo)
    from apps.core.models import Secuencia

    with transaction.atomic():
        # select_for_update() bloquea la fila hasta que la transacción termine,
        # impidiendo que otro proceso lea el mismo numero y lo duplique.
        secuencia = Secuencia.objects.select_for_update().get(
            tipo_documento=tipo_documento
        )
        secuencia.ultimo_numero += 1
        secuencia.save(update_fields=['ultimo_numero'])

        numero = f"{secuencia.prefijo}{str(secuencia.ultimo_numero).zfill(secuencia.digitos)}"

    logger.info(
        'Número generado: %s para tipo_documento=%s',
        numero, tipo_documento
    )
    return numero
