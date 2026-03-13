# -*- coding: utf-8 -*-
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import models

from apps.core.models import AuditableModel


class Socio(AuditableModel):
    nombre = models.CharField(max_length=150, verbose_name='Nombre')
    rif = models.CharField(max_length=20, null=True, blank=True, verbose_name='RIF')
    telefono = models.CharField(max_length=30, null=True, blank=True, verbose_name='Teléfono')
    email = models.EmailField(null=True, blank=True, verbose_name='Email')
    activo = models.BooleanField(default=True, verbose_name='Activo')

    class Meta:
        verbose_name = 'Socio'
        verbose_name_plural = 'Socios'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class PrestamoPorSocio(AuditableModel):
    """
    Registra un préstamo recibido de un socio.
    monto_usd se calcula automáticamente según la regla bimoneda:
      USD → tasa=1, monto_usd=monto_principal
      VES → monto_usd = monto_principal / tasa_cambio
    """
    MONEDA_CHOICES = [
        ('USD', 'USD - Dólar Americano'),
        ('VES', 'VES - Bolívar Soberano'),
    ]
    ESTADOS = [
        ('ACTIVO', 'Activo'),
        ('CANCELADO', 'Cancelado'),
        ('VENCIDO', 'Vencido'),
    ]

    numero = models.CharField(
        max_length=20, unique=True, editable=False, verbose_name='Número')
    socio = models.ForeignKey(
        Socio, on_delete=models.PROTECT, related_name='prestamos',
        verbose_name='Socio')
    monto_principal = models.DecimalField(
        max_digits=18, decimal_places=2, verbose_name='Monto Principal')
    moneda = models.CharField(
        max_length=3, choices=MONEDA_CHOICES, default='USD', verbose_name='Moneda')
    tasa_cambio = models.DecimalField(
        max_digits=18, decimal_places=6, default=Decimal('1.000000'),
        verbose_name='Tasa de Cambio (VES/USD)')
    monto_usd = models.DecimalField(
        max_digits=18, decimal_places=2, editable=False,
        verbose_name='Monto en USD')
    fecha_prestamo = models.DateField(verbose_name='Fecha del Préstamo')
    fecha_vencimiento = models.DateField(
        null=True, blank=True, verbose_name='Fecha de Vencimiento')
    cuenta_destino = models.ForeignKey(
        'bancos.CuentaBancaria', null=True, blank=True,
        on_delete=models.PROTECT, related_name='prestamos_recibidos',
        verbose_name='Cuenta Destino')
    estado = models.CharField(
        max_length=10, choices=ESTADOS, default='ACTIVO', verbose_name='Estado')
    notas = models.TextField(null=True, blank=True, verbose_name='Notas')

    class Meta:
        verbose_name = 'Préstamo por Socio'
        verbose_name_plural = 'Préstamos por Socio'
        ordering = ['-fecha_prestamo', '-numero']

    def __str__(self):
        return f'{self.numero} — {self.socio}'

    def save(self, *args, **kwargs):
        if self._state.adding:
            from apps.core.services import generar_numero
            if not self.numero:
                self.numero = generar_numero('SOC')
            # Bimoneda: calcular monto_usd según la regla estricta
            if self.moneda == 'USD':
                self.tasa_cambio = Decimal('1.000000')
                self.monto_usd = Decimal(str(self.monto_principal))
            else:
                tasa = Decimal(str(self.tasa_cambio))
                monto = Decimal(str(self.monto_principal))
                self.monto_usd = (monto / tasa).quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)


class PagoPrestamo(AuditableModel):
    """
    Registra un pago realizado por un socio contra un préstamo activo.
    monto_usd es calculado por apps/socios/services.py → registrar_pago_prestamo().
    """
    MONEDA_CHOICES = [
        ('USD', 'USD - Dólar Americano'),
        ('VES', 'VES - Bolívar Soberano'),
    ]

    prestamo = models.ForeignKey(
        PrestamoPorSocio, on_delete=models.PROTECT, related_name='pagos',
        verbose_name='Préstamo')
    monto = models.DecimalField(
        max_digits=18, decimal_places=2, verbose_name='Monto')
    moneda = models.CharField(
        max_length=3, choices=MONEDA_CHOICES, default='USD', verbose_name='Moneda')
    tasa_cambio = models.DecimalField(
        max_digits=18, decimal_places=6, default=Decimal('1.000000'),
        verbose_name='Tasa de Cambio (VES/USD)')
    monto_usd = models.DecimalField(
        max_digits=18, decimal_places=2, editable=False,
        verbose_name='Monto en USD')
    fecha = models.DateField(default=date.today, verbose_name='Fecha de Pago')
    cuenta_origen = models.ForeignKey(
        'bancos.CuentaBancaria', null=True, blank=True,
        on_delete=models.PROTECT, related_name='pagos_prestamo',
        verbose_name='Cuenta Origen')
    notas = models.TextField(null=True, blank=True, verbose_name='Notas')

    class Meta:
        verbose_name = 'Pago de Préstamo'
        verbose_name_plural = 'Pagos de Préstamos'
        ordering = ['-fecha', 'id']

    def __str__(self):
        return f'Pago {self.prestamo.numero} — {self.monto} {self.moneda}'
