# -*- coding: utf-8 -*-
"""
Servicios de tesorería para LacteOps.

  registrar_movimiento_caja(...)  → MovimientoCaja
    Único punto de entrada para crear movimientos de caja.
    Valida saldo, calcula monto_usd y actualiza saldo_actual.

  ReexpresionMensual.ejecutar(tasa_cierre, fecha_cierre)
    Reconoce la variación cambiaria mensual en cuentas VES.
    Solo puede ejecutarse una vez por mes-año.

REGLAS ABSOLUTAS:
  - select_for_update() en todo acceso a saldo dentro de atomic().
  - Saldo negativo PROHIBIDO: SaldoInsuficienteError antes de escribir.
  - Decimal estricto, nunca float.
  - Ningún código fuera de registrar_movimiento_caja() puede modificar
    CuentaBancaria.saldo_actual directamente.
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.utils.timezone import now

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _calcular_monto_usd(monto: Decimal, moneda: str, tasa_cambio: Decimal) -> Decimal:
    """
    Normaliza un monto a USD.

    Regla bimoneda invariante:
      moneda == 'USD' → monto_usd = monto,  tasa_cambio = 1
      moneda == 'VES' → monto_usd = monto / tasa_cambio  (tasa > 0 obligatoria)
    """
    monto = Decimal(str(monto))
    tasa_cambio = Decimal(str(tasa_cambio))

    if moneda == 'USD':
        return monto
    # VES
    if tasa_cambio <= Decimal('0'):
        raise ValueError(
            'tasa_cambio debe ser > 0 para convertir VES a USD.'
        )
    return monto / tasa_cambio


# ─────────────────────────────────────────────────────────────────────────────
# Función principal: único punto de entrada para movimientos de caja
# ─────────────────────────────────────────────────────────────────────────────

def registrar_movimiento_caja(
    cuenta,
    tipo: str,
    monto,
    moneda: str,
    tasa_cambio,
    referencia: str = '',
    notas: str = '',
) -> 'MovimientoCaja':
    """
    Registra un MovimientoCaja y actualiza el saldo de la CuentaBancaria.

    Pasos obligatorios (según regla 2.14):
      1. Verificar que la cuenta esté activa.
      2. Validar saldo no negativo para tipos SALIDA/TRANSFERENCIA_SALIDA.
      3. Calcular monto_usd (nunca acepta el valor del caller sin recalcular).
      4. Crear el MovimientoCaja (inmutable post-creación).
      5. Actualizar cuenta.saldo_actual vía instance.save().

    Args:
        cuenta      (CuentaBancaria): Cuenta afectada.
        tipo        (str): ENTRADA | SALIDA | TRANSFERENCIA_ENTRADA |
                           TRANSFERENCIA_SALIDA | REEXPRESION
        monto       (Decimal): Monto en la moneda de la cuenta.
        moneda      (str): 'USD' o 'VES'.
        tasa_cambio (Decimal): Tipo de cambio BCV (VES/USD).
        referencia  (str): Número de documento origen.
        notas       (str): Texto libre.

    Returns:
        MovimientoCaja: El movimiento creado.

    Raises:
        LacteOpsError (SaldoInsuficienteError): Si la cuenta no tiene saldo.
        ValueError: Si la cuenta está inactiva o la tasa es inválida.
    """
    from apps.bancos.models import CuentaBancaria, MovimientoCaja
    from apps.core.exceptions import SaldoInsuficienteError

    monto = Decimal(str(monto))
    tasa_cambio = Decimal(str(tasa_cambio))

    # ── PASO 1: Verificar cuenta activa ──────────────────────────────────────
    if not cuenta.activa:
        raise ValueError(
            f'La cuenta "{cuenta.nombre}" está inactiva y no puede recibir movimientos.'
        )

    with transaction.atomic():
        # Bloqueo de fila para prevenir condiciones de carrera (regla 2.5 crítico)
        cuenta = CuentaBancaria.objects.select_for_update().get(pk=cuenta.pk)

        # ── PASO 2: Validar saldo para salidas ───────────────────────────────
        tipos_salida = ('SALIDA', 'TRANSFERENCIA_SALIDA')
        if tipo in tipos_salida:
            if cuenta.saldo_actual < monto:
                raise SaldoInsuficienteError(cuenta.nombre, cuenta.saldo_actual, monto)

        # ── PASO 3: Calcular monto_usd ───────────────────────────────────────
        monto_usd = _calcular_monto_usd(monto, moneda, tasa_cambio)

        # ── PASO 4: Crear MovimientoCaja (inmutable) ─────────────────────────
        movimiento = MovimientoCaja.objects.create(
            cuenta=cuenta,
            tipo=tipo,
            monto=monto,
            moneda=moneda,
            tasa_cambio=tasa_cambio,
            monto_usd=monto_usd,
            referencia=referencia,
            notas=notas,
            fecha=now().date(),
        )

        # ── PASO 5: Actualizar saldo_actual ──────────────────────────────────
        tipos_entrada = ('ENTRADA', 'TRANSFERENCIA_ENTRADA')
        if tipo in tipos_entrada:
            cuenta.saldo_actual += monto
        elif tipo == 'REEXPRESION':
            # REEXPRESION: monto puede ser positivo (apreciación) o negativo (depreciación).
            # Se aplica con signo para dejar el saldo matemáticamente correcto.
            # No se valida saldo negativo aquí: es un ajuste contable obligatorio.
            cuenta.saldo_actual += monto  # monto ya tiene su signo correcto
        else:
            # SALIDA / TRANSFERENCIA_SALIDA
            cuenta.saldo_actual -= monto

        cuenta.save(update_fields=['saldo_actual'])

    logger.info(
        'MovimientoCaja | Cuenta: %s | Tipo: %s | Monto: %s %s | '
        'MontoCaja: %s | Ref: %s',
        cuenta.nombre, tipo, monto, moneda, monto_usd, referencia
    )
    return movimiento


# ─────────────────────────────────────────────────────────────────────────────
# Reexpresión Mensual de saldos VES
# ─────────────────────────────────────────────────────────────────────────────

class ReexpresionMensual:
    """
    Reconoce el diferencial cambiario de saldos en VES al cierre de mes.

    Algoritmo (regla 2.16):
      Para cada CuentaBancaria activa con moneda == 'VES':
        usd_antes    = saldo_actual / tasa_inicio_mes
        usd_despues  = saldo_actual / tasa_cierre
        variacion    = usd_despues − usd_antes
        → MovimientoCaja tipo REEXPRESION con variacion

    Idempotente por mes-año: rechaza ejecución duplicada para el mismo período.
    Todo el proceso en un único transaction.atomic().
    """

    @staticmethod
    def ejecutar(tasa_inicio_mes, tasa_cierre, fecha_cierre, usuario):
        """
        Ejecuta la reexpresión mensual para todas las cuentas VES activas.

        Args:
            tasa_inicio_mes (Decimal): Tasa BCV al inicio del mes.
            tasa_cierre     (Decimal): Tasa BCV al cierre del mes.
            fecha_cierre    (date):   Fecha de cierre del período.
            usuario         (User):   Usuario que ejecuta la acción.

        Returns:
            list[MovimientoCaja]: Movimientos generados (uno por cuenta VES activa).

        Raises:
            ValueError: Si ya existe una reexpresión para el mismo mes-año.
        """
        from apps.bancos.models import CuentaBancaria, MovimientoCaja, PeriodoReexpresado
        from apps.core.exceptions import EstadoInvalidoError

        tasa_inicio_mes = Decimal(str(tasa_inicio_mes))
        tasa_cierre = Decimal(str(tasa_cierre))

        if tasa_inicio_mes <= Decimal('0') or tasa_cierre <= Decimal('0'):
            raise ValueError('Las tasas deben ser mayores que cero.')

        # Idempotencia: verificar si ya se reexpresó este mes-año
        ya_ejecutada = PeriodoReexpresado.objects.filter(
            anio=fecha_cierre.year,
            mes=fecha_cierre.month,
        ).exists()
        
        if ya_ejecutada:
            raise EstadoInvalidoError('Reexpresión Mensual', 'EJECUTADA', 'Período ya reexpresado')

        movimientos = []
        referencia = f'REEXP-{fecha_cierre.strftime("%Y%m")}'

        with transaction.atomic():
            cuentas_ves = CuentaBancaria.objects.select_for_update().filter(
                moneda='VES', activa=True
            )

            for cuenta in cuentas_ves:
                saldo = Decimal(str(cuenta.saldo_actual))

                usd_antes = saldo / tasa_inicio_mes
                usd_despues = saldo / tasa_cierre
                variacion_usd = usd_despues - usd_antes

                # La variacion_usd tiene signo:
                #   Positiva → tasa bajó → saldo VES vale MÁS en USD → el saldo sube.
                #   Negativa → tasa subió → saldo VES vale MENOS en USD → el saldo baja.
                # Se pasa con signo a registrar_movimiento_caja; el Paso 5 hace += monto.
                # monto_usd en el registro también lleva el signo para trazabilidad.
                movimiento = registrar_movimiento_caja(
                    cuenta=cuenta,
                    tipo='REEXPRESION',
                    monto=variacion_usd,            # con signo: positivo o negativo
                    moneda='USD',
                    tasa_cambio=Decimal('1.000000'),
                    referencia=referencia,
                    notas=(
                        f'Reexpresión {fecha_cierre.strftime("%B %Y")} | '
                        f'Tasa inicio: {tasa_inicio_mes} | '
                        f'Tasa cierre: {tasa_cierre} | '
                        f'Variación USD: {variacion_usd:+.6f}'
                    ),
                )
                movimientos.append(movimiento)

                logger.info(
                    'REEXPRESION | Cuenta: %s | Saldo VES: %s | '
                    'USD antes: %s | USD después: %s | Variación: %s',
                    cuenta.nombre, saldo, usd_antes, usd_despues, variacion_usd
                )

            PeriodoReexpresado.objects.create(
                anio=fecha_cierre.year,
                mes=fecha_cierre.month,
                tasa_cierre=tasa_cierre,
                ejecutado_por=usuario
            )

        logger.info(
            'ReexpresionMensual completada para %s. %s cuentas procesadas.',
            referencia, len(movimientos)
        )
        return movimientos


# ─────────────────────────────────────────────────────────────────────────────
# Movimiento de Tesorería libre
# ─────────────────────────────────────────────────────────────────────────────

def ejecutar_movimiento_tesoreria(
    cuenta,
    tipo: str,
    monto,
    moneda: str,
    tasa_cambio,
    categoria,
    descripcion: str,
    fecha,
    usuario,
):
    """
    Registra un MovimientoTesoreria y genera el MovimientoCaja correspondiente.

    Pasos:
      1. Valida que la categoría tenga contexto 'TESORERIA'.
      2. Crea MovimientoTesoreria (inmutable — calcula número y monto_usd en save()).
      3. Genera MovimientoCaja:
           CARGO  → tipo_caja='SALIDA'
           ABONO  → tipo_caja='ENTRADA'
      Todo dentro de transaction.atomic() con select_for_update() en la cuenta
      (delegado a registrar_movimiento_caja).

    Args:
        cuenta       (CuentaBancaria): Cuenta afectada.
        tipo         (str): 'CARGO' o 'ABONO'.
        monto        (Decimal): Monto en la moneda indicada.
        moneda       (str): 'USD' o 'VES'.
        tasa_cambio  (Decimal): Tasa BCV.
        categoria    (CategoriaGasto): Debe tener contexto='TESORERIA'.
        descripcion  (str): Descripción del movimiento.
        fecha        (date): Fecha del movimiento.
        usuario      (User): Usuario que ejecuta la acción.

    Returns:
        MovimientoTesoreria: El movimiento creado.

    Raises:
        EstadoInvalidoError: Si la categoría no tiene contexto TESORERIA.
        SaldoInsuficienteError: Si la cuenta no tiene saldo para un CARGO.
        ValueError: Si la cuenta está inactiva.
    """
    from apps.bancos.models import MovimientoTesoreria
    from apps.core.exceptions import EstadoInvalidoError

    monto = Decimal(str(monto))
    tasa_cambio = Decimal(str(tasa_cambio))

    if categoria.contexto != 'TESORERIA':
        raise EstadoInvalidoError(
            'CategoriaGasto',
            categoria.contexto,
            'usar en movimiento de tesorería (debe tener contexto=TESORERIA)',
        )

    tipo_caja = 'SALIDA' if tipo == 'CARGO' else 'ENTRADA'

    with transaction.atomic():
        mov = MovimientoTesoreria.objects.create(
            cuenta=cuenta,
            tipo=tipo,
            monto=monto,
            moneda=moneda,
            tasa_cambio=tasa_cambio,
            categoria=categoria,
            descripcion=descripcion,
            fecha=fecha,
            registrado_por=usuario,
            monto_usd=Decimal('0.00'),  # placeholder; save() recalcula
        )

        registrar_movimiento_caja(
            cuenta=cuenta,
            tipo=tipo_caja,
            monto=monto,
            moneda=moneda,
            tasa_cambio=mov.tasa_cambio,
            referencia=mov.numero,
            notas=descripcion,
        )

    logger.info(
        'MovimientoTesoreria %s | %s | Cuenta: %s | %s %s | Categoria: %s',
        mov.numero, tipo, cuenta, monto, moneda, categoria,
    )
    return mov
