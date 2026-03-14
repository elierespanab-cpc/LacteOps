# -*- coding: utf-8 -*-
"""
Modelos del módulo de Tesorería para LacteOps.

Lógica de negocio implementada:
  - TransferenciaCuentas.save(): asigna número automático en creación.
  - TransferenciaCuentas.ejecutar(): débito origen → crédito destino, atómico.
  - TransferenciaCuentas.anular(): solo desde EJECUTADA, genera movimientos inversos.

REGLAS:
  - Ningún código fuera de registrar_movimiento_caja() modifica saldo_actual.
  - Saldo negativo PROHIBIDO: SaldoInsuficienteError antes de escribir.
  - select_for_update() implícito dentro de registrar_movimiento_caja().
  - Transferencia entre monedas distintas requiere tasa_cambio explícita (≠ 1:1).
"""
import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import models, transaction
from django.utils.timezone import now
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator

from apps.core.models import AuditableModel
from apps.core.exceptions import EstadoInvalidoError

logger = logging.getLogger(__name__)


class CuentaBancaria(AuditableModel):
    MONEDA_CHOICES = [
        ('USD', 'USD - Dólar Americano'),
        ('VES', 'VES - Bolívar Soberano'),
    ]

    nombre = models.CharField(max_length=150, verbose_name="Nombre de la Cuenta")
    numero_cuenta = models.CharField(max_length=50, null=True, blank=True, verbose_name="Número de Cuenta")
    moneda = models.CharField(max_length=3, choices=MONEDA_CHOICES, default='USD', verbose_name="Moneda")
    saldo_actual = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'), verbose_name="Saldo Actual")
    activa = models.BooleanField(default=True, verbose_name="Activa")

    class Meta:
        verbose_name = "Cuenta Bancaria"
        verbose_name_plural = "Cuentas Bancarias"
        ordering = ['nombre']
        constraints = [
            models.CheckConstraint(condition=models.Q(saldo_actual__gte=0), name='chk_saldo_positivo_cuenta')
        ]

    def __str__(self):
        return f"{self.nombre} ({self.moneda})"


class MovimientoCaja(models.Model):
    TIPO_CHOICES = [
        ('ENTRADA', 'Entrada'),
        ('SALIDA', 'Salida'),
        ('TRANSFERENCIA_ENTRADA', 'Transferencia Entrada'),
        ('TRANSFERENCIA_SALIDA', 'Transferencia Salida'),
        ('REEXPRESION', 'Reexpresión'),
    ]
    MONEDA_CHOICES = [
        ('USD', 'USD - Dólar Americano'),
        ('VES', 'VES - Bolívar Soberano'),
    ]

    cuenta = models.ForeignKey(CuentaBancaria, on_delete=models.PROTECT, verbose_name="Cuenta")
    tipo = models.CharField(max_length=25, choices=TIPO_CHOICES, verbose_name="Tipo de Movimiento")
    monto = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Monto")
    moneda = models.CharField(max_length=3, choices=MONEDA_CHOICES, verbose_name="Moneda")
    tasa_cambio = models.DecimalField(max_digits=18, decimal_places=6, verbose_name="Tasa de Cambio (VES/USD)")
    monto_usd = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Monto en USD")
    referencia = models.CharField(max_length=100, blank=True, verbose_name="Referencia")
    fecha = models.DateField(default=now, verbose_name="Fecha")
    notas = models.TextField(blank=True, verbose_name="Notas")

    class Meta:
        verbose_name = "Movimiento de Caja"
        verbose_name_plural = "Movimientos de Caja"
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f"{self.fecha.strftime('%Y-%m-%d')} - {self.tipo} - {self.monto} {self.moneda}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("MovimientoCaja es inmutable y no puede modificarse.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("MovimientoCaja es inmutable y no puede eliminarse.")


class TransferenciaCuentas(AuditableModel):
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('EJECUTADA', 'Ejecutada'),
        ('ANULADA', 'Anulada'),
    ]

    numero = models.CharField(max_length=20, unique=True, editable=False, verbose_name="Número de Transferencia")
    cuenta_origen = models.ForeignKey(CuentaBancaria, related_name='transferencias_origen', on_delete=models.PROTECT, verbose_name="Cuenta Origen")
    cuenta_destino = models.ForeignKey(CuentaBancaria, related_name='transferencias_destino', on_delete=models.PROTECT, verbose_name="Cuenta Destino")
    monto_origen = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Monto Origen")
    monto_destino = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Monto Destino")
    tasa_cambio = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('1.000000'), verbose_name="Tasa de Cambio")
    fecha = models.DateField(default=now, verbose_name="Fecha")
    notas = models.TextField(blank=True, verbose_name="Notas")
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='PENDIENTE', verbose_name="Estado")

    class Meta:
        verbose_name = "Transferencia de Cuentas"
        verbose_name_plural = "Transferencias de Cuentas"
        ordering = ['-fecha', '-numero']

    def __str__(self):
        return f"Transferencia {self.numero} - {self.cuenta_origen.nombre} a {self.cuenta_destino.nombre}"

    def save(self, *args, **kwargs):
        """Asigna número automático en creación usando la secuencia TES."""
        if self._state.adding and not self.numero:
            from apps.core.services import generar_numero
            self.numero = generar_numero('TES')
        super().save(*args, **kwargs)

    def ejecutar(self):
        """
        Ejecuta la transferencia de forma atómica:
          1. TRANSFERENCIA_SALIDA en cuenta_origen por monto_origen.
          2. TRANSFERENCIA_ENTRADA en cuenta_destino por monto_destino.

        Si la moneda difiere entre cuentas, tasa_cambio debe ser explícita (≠ 1:1).
        Si falla cualquier parte, hace rollback total.

        Raises:
            EstadoInvalidoError: Si la transferencia no está en estado PENDIENTE.
            SaldoInsuficienteError: Si cuenta_origen no tiene saldo suficiente.
        """
        if self.estado != 'PENDIENTE':
            raise EstadoInvalidoError('Transferencia de Cuentas', self.estado, 'ejecutar')

        from apps.bancos.services import registrar_movimiento_caja

        monto_origen = Decimal(str(self.monto_origen))
        monto_destino = Decimal(str(self.monto_destino))
        tasa_cambio = Decimal(str(self.tasa_cambio))
        referencia = self.numero

        with transaction.atomic():
            # Débito cuenta origen
            registrar_movimiento_caja(
                cuenta=self.cuenta_origen,
                tipo='TRANSFERENCIA_SALIDA',
                monto=monto_origen,
                moneda=self.cuenta_origen.moneda,
                tasa_cambio=tasa_cambio if self.cuenta_origen.moneda == 'VES' else Decimal('1.000000'),
                referencia=referencia,
                notas=f'Transferencia {self.numero} → {self.cuenta_destino.nombre}',
            )

            # Crédito cuenta destino
            registrar_movimiento_caja(
                cuenta=self.cuenta_destino,
                tipo='TRANSFERENCIA_ENTRADA',
                monto=monto_destino,
                moneda=self.cuenta_destino.moneda,
                tasa_cambio=tasa_cambio if self.cuenta_destino.moneda == 'VES' else Decimal('1.000000'),
                referencia=referencia,
                notas=f'Transferencia {self.numero} ← {self.cuenta_origen.nombre}',
            )

            self.estado = 'EJECUTADA'
            self.save(update_fields=['estado'])

        logger.info(
            'Transferencia %s EJECUTADA. Origen: %s %s %s → Destino: %s %s %s.',
            self.numero,
            self.cuenta_origen.nombre, monto_origen, self.cuenta_origen.moneda,
            self.cuenta_destino.nombre, monto_destino, self.cuenta_destino.moneda,
        )

    def anular(self):
        """
        Anula la transferencia generando movimientos inversos.
        Solo puede ejecutarse desde estado EJECUTADA.

        Genera:
          - TRANSFERENCIA_ENTRADA en cuenta_origen (devuelve el dinero).
          - TRANSFERENCIA_SALIDA en cuenta_destino (revierte el crédito).

        Raises:
            EstadoInvalidoError: Si la transferencia no está en estado EJECUTADA.
            SaldoInsuficienteError: Si cuenta_destino no tiene saldo para revertir.
        """
        if self.estado != 'EJECUTADA':
            raise EstadoInvalidoError('Transferencia de Cuentas', self.estado, 'anular')

        from apps.bancos.services import registrar_movimiento_caja

        monto_origen = Decimal(str(self.monto_origen))
        monto_destino = Decimal(str(self.monto_destino))
        tasa_cambio = Decimal(str(self.tasa_cambio))
        referencia = f'ANUL-{self.numero}'

        with transaction.atomic():
            # Revertir: crédito a cuenta_origen (devuelve lo que salió)
            registrar_movimiento_caja(
                cuenta=self.cuenta_origen,
                tipo='TRANSFERENCIA_ENTRADA',
                monto=monto_origen,
                moneda=self.cuenta_origen.moneda,
                tasa_cambio=tasa_cambio if self.cuenta_origen.moneda == 'VES' else Decimal('1.000000'),
                referencia=referencia,
                notas=f'Anulación Transferencia {self.numero}',
            )

            # Revertir: débito a cuenta_destino (retira lo que entró)
            registrar_movimiento_caja(
                cuenta=self.cuenta_destino,
                tipo='TRANSFERENCIA_SALIDA',
                monto=monto_destino,
                moneda=self.cuenta_destino.moneda,
                tasa_cambio=tasa_cambio if self.cuenta_destino.moneda == 'VES' else Decimal('1.000000'),
                referencia=referencia,
                notas=f'Anulación Transferencia {self.numero}',
            )

            self.estado = 'ANULADA'
            self.save(update_fields=['estado'])

        logger.info('Transferencia %s ANULADA. Movimientos inversos generados.', self.numero)


class PeriodoReexpresado(AuditableModel):
    anio = models.PositiveSmallIntegerField(verbose_name="Año")
    mes = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        verbose_name="Mes"
    )
    tasa_cierre = models.DecimalField(max_digits=18, decimal_places=6, verbose_name="Tasa de Cierre (VES/USD)")
    ejecutado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, verbose_name="Ejecutado por")
    fecha_ejecucion = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Ejecución")

    class Meta:
        verbose_name = "Período Reexpresado"
        verbose_name_plural = "Períodos Reexpresados"
        unique_together = ('anio', 'mes')
        ordering = ['-anio', '-mes']

    def __str__(self):
        return f"Reexpresión {self.mes:02d}/{self.anio}"


class MovimientoTesoreria(models.Model):
    """
    Movimiento de tesorería libre (cargo o abono) clasificado por CategoriaGasto.
    INMUTABLE post-creación: idéntico a MovimientoCaja.
    Genera automáticamente un MovimientoCaja vía ejecutar_movimiento_tesoreria().

    Bimoneda:
      USD → tasa_cambio=1, monto_usd=monto
      VES → monto_usd = monto / tasa_cambio
    """
    TIPOS = [
        ('CARGO', 'Cargo'),
        ('ABONO', 'Abono'),
    ]
    MONEDA_CHOICES = [
        ('USD', 'USD - Dólar Americano'),
        ('VES', 'VES - Bolívar Soberano'),
    ]

    numero = models.CharField(
        max_length=20, unique=True, editable=False, verbose_name='Número')
    cuenta = models.ForeignKey(
        CuentaBancaria, on_delete=models.PROTECT,
        related_name='movimientos_tesoreria', verbose_name='Cuenta')
    tipo = models.CharField(
        max_length=10, choices=TIPOS, verbose_name='Tipo')
    monto = models.DecimalField(
        max_digits=18, decimal_places=2, verbose_name='Monto')
    moneda = models.CharField(
        max_length=3, choices=MONEDA_CHOICES, verbose_name='Moneda')
    tasa_cambio = models.DecimalField(
        max_digits=18, decimal_places=6, verbose_name='Tasa de Cambio (VES/USD)')
    monto_usd = models.DecimalField(
        max_digits=18, decimal_places=2, editable=False,
        verbose_name='Monto en USD')
    categoria = models.ForeignKey(
        'core.CategoriaGasto', on_delete=models.PROTECT,
        verbose_name='Categoría')
    descripcion = models.TextField(verbose_name='Descripción')
    fecha = models.DateField(default=date.today, verbose_name='Fecha')
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, verbose_name='Registrado por')

    class Meta:
        verbose_name = 'Movimiento de Tesorería'
        verbose_name_plural = 'Movimientos de Tesorería'
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f'{self.numero} — {self.tipo} {self.monto} {self.moneda}'

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise EstadoInvalidoError(
                'MovimientoTesoreria', 'GUARDADO', 'modificar (es inmutable)')
        from apps.core.services import generar_numero
        if not self.numero:
            self.numero = generar_numero('TES')
        # Bimoneda: calcular monto_usd
        monto = Decimal(str(self.monto))
        tasa = Decimal(str(self.tasa_cambio))
        if self.moneda == 'USD':
            self.tasa_cambio = Decimal('1.000000')
            self.monto_usd = monto
        else:
            self.monto_usd = (monto / tasa).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise EstadoInvalidoError(
            'MovimientoTesoreria', 'GUARDADO', 'eliminar (es inmutable)')


class RespaldoBD(models.Model):  # NO AuditableModel — log inmutable
    fecha = models.DateTimeField(auto_now_add=True)
    ejecutado_por = models.ForeignKey(settings.AUTH_USER_MODEL,
                       null=True, on_delete=models.SET_NULL)
    nombre_archivo = models.CharField(max_length=200)
    tamanio_bytes = models.PositiveIntegerField(default=0)
    exitoso = models.BooleanField(default=False)
    error_mensaje = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Respaldo de BD'
        verbose_name_plural = 'Respaldos de BD'
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.fecha:%Y-%m-%d %H:%M} — {self.nombre_archivo}'
