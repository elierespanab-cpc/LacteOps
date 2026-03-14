# -*- coding: utf-8 -*-
"""
Modelos del módulo de Compras para LacteOps.

Lógica de negocio implementada:
  - DetalleFacturaCompra.save(): auto-calcula subtotal y recalcula total de cabecera.
  - FacturaCompra.aprobar(): registra entradas al Kardex en USD, cambia estado.
  - FacturaCompra.anular(): solo permite anular facturas en estado RECIBIDA.
  - Pago.registrar(): calcula monto_usd con bimoneda y genera MovimientoCaja.
  - GastoServicio.pagar(): calcula monto_usd con bimoneda y genera MovimientoCaja.
"""
import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import models, transaction

from apps.core.models import AuditableModel
from apps.core.exceptions import EstadoInvalidoError
from apps.almacen.models import Producto
from apps.almacen.services import convertir_a_usd, registrar_entrada

logger = logging.getLogger(__name__)


class Proveedor(AuditableModel):
    nombre = models.CharField(max_length=200, verbose_name="Nombre")
    rif = models.CharField(max_length=20, unique=True, verbose_name="RIF / Identificación")
    telefono = models.CharField(max_length=20, blank=True, verbose_name="Teléfono")
    email = models.EmailField(blank=True, verbose_name="Correo Electrónico")
    activo = models.BooleanField(default=True, verbose_name="Activo")

    class Meta:
        verbose_name = "Proveedor"
        verbose_name_plural = "Proveedores"
        ordering = ['nombre']

    def __str__(self):
        return f"{self.rif} - {self.nombre}"


class FacturaCompra(AuditableModel):
    ESTADO_CHOICES = [
        ('RECIBIDA', 'Recibida'),
        ('APROBADA', 'Aprobada'),
        ('ANULADA', 'Anulada'),
    ]
    MONEDA_CHOICES = [
        ('USD', 'USD - Dólar Americano'),
        ('VES', 'VES - Bolívar Soberano'),
    ]

    numero = models.CharField(max_length=20, unique=True, verbose_name="Número de Factura")
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, verbose_name="Proveedor")
    fecha = models.DateField(verbose_name="Fecha")
    fecha_vencimiento = models.DateField(null=True, blank=True, verbose_name="Fecha de Vencimiento")
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='RECIBIDA', verbose_name="Estado")
    moneda = models.CharField(max_length=3, choices=MONEDA_CHOICES, default='USD', verbose_name="Moneda")
    tasa_cambio = models.DecimalField(max_digits=18, decimal_places=6, default=1.000000, verbose_name="Tasa de Cambio (VES/USD)")
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0, editable=False, verbose_name="Total (USD)")
    notas = models.TextField(blank=True, verbose_name="Notas")

    class Meta:
        verbose_name = "Factura de Compra"
        verbose_name_plural = "Facturas de Compra"
        ordering = ['-fecha', '-numero']

    def __str__(self):
        return f"Factura Compra {self.numero} - {self.proveedor.nombre}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.numero:
            from apps.core.services import generar_numero
            self.numero = generar_numero('COM')
        super().save(*args, **kwargs)

    def get_saldo_pendiente(self):
        total_pagado = self.pagos.aggregate(
            total=models.Sum('monto')
        )['total'] or Decimal('0.00')
        return self.total - total_pagado

    def aprobar(self):
        """
        Aprueba la factura de compra: registra las entradas al Kardex (en USD)
        para cada línea de detalle y cambia el estado a APROBADA.

        Reglas:
          - Solo facturas en estado RECIBIDA pueden aprobarse.
          - Todo el proceso es atómico: si un detalle falla, se revierte todo.
          - Los costos se normalizan a USD antes de entrar al Kardex.

        Raises:
            EstadoInvalidoError: Si la factura no está en estado RECIBIDA.
        """
        if self.estado != 'RECIBIDA':
            raise EstadoInvalidoError('Factura de Compra', self.estado, 'aprobar')

        with transaction.atomic():
            for detalle in self.detalles.select_related('producto').all():
                costo_usd = convertir_a_usd(
                    detalle.costo_unitario,
                    self.moneda,
                    self.tasa_cambio,
                )
                registrar_entrada(
                    producto=detalle.producto,
                    cantidad=detalle.cantidad,
                    costo_unitario=costo_usd,
                    referencia=self.numero,
                    notas=f'Aprobación Factura Compra {self.numero}',
                )

            self.estado = 'APROBADA'
            self.save(update_fields=['estado'])

        logger.info('Factura compra %s aprobada. Total: %s USD.', self.numero, self.total)

    def anular(self):
        """
        Anula la factura de compra.

        Reglas:
          - Solo facturas en estado RECIBIDA pueden anularse.
          - Una factura APROBADA no puede anularse directamente
            (requeriría reversar el Kardex, proceso fuera de este sprint).

        Raises:
            EstadoInvalidoError: Si la factura ya está APROBADA o ANULADA.
        """
        if self.estado == 'APROBADA':
            raise EstadoInvalidoError('Factura de Compra', self.estado, 'anular')
        if self.estado == 'ANULADA':
            raise EstadoInvalidoError('Factura de Compra', self.estado, 'anular')

        self.estado = 'ANULADA'
        self.save(update_fields=['estado'])
        logger.info('Factura compra %s anulada.', self.numero)


class DetalleFacturaCompra(AuditableModel):
    factura = models.ForeignKey(FacturaCompra, related_name='detalles', on_delete=models.CASCADE, verbose_name="Factura")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, verbose_name="Producto")
    cantidad = models.DecimalField(max_digits=18, decimal_places=4, verbose_name="Cantidad")
    costo_unitario = models.DecimalField(max_digits=18, decimal_places=6, verbose_name="Costo Unitario")
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, editable=False, verbose_name="Subtotal (USD)")

    class Meta:
        verbose_name = "Detalle de Factura de Compra"
        verbose_name_plural = "Detalles de Facturas de Compra"
        ordering = ['id']

    def __str__(self):
        return f"{self.factura.numero} - {self.producto.codigo} (x{self.cantidad})"

    def save(self, *args, **kwargs):
        """
        Calcula el subtotal de la línea y recalcula el total de la cabecera.
        El subtotal se almacena en la moneda original del documento;
        la conversión a USD ocurre en FacturaCompra.aprobar().
        """
        self.subtotal = Decimal(str(self.cantidad)) * Decimal(str(self.costo_unitario))
        super().save(*args, **kwargs)

        # Recalcular el total de la factura cabecera
        total_factura = self.factura.detalles.aggregate(
            total=models.Sum('subtotal')
        )['total'] or Decimal('0.00')
        self.factura.total = total_factura
        self.factura.save(update_fields=['total'])


class Pago(AuditableModel):
    MEDIO_PAGO_CHOICES = [
        ('EFECTIVO_USD', 'Efectivo USD'),
        ('EFECTIVO_VES', 'Efectivo VES'),
        ('TRANSFERENCIA_USD', 'Transferencia USD'),
        ('TRANSFERENCIA_VES', 'Transferencia VES'),
    ]

    factura = models.ForeignKey(FacturaCompra, related_name='pagos', on_delete=models.PROTECT, verbose_name="Factura de Compra")
    fecha = models.DateField(verbose_name="Fecha de Pago")
    monto = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Monto del Pago (USD)")
    moneda = models.CharField(max_length=3, choices=FacturaCompra.MONEDA_CHOICES, default='USD', verbose_name="Moneda")
    tasa_cambio = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('1.000000'), verbose_name="Tasa de Cambio (VES/USD)")
    monto_usd = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'), editable=False, verbose_name="Monto en USD")
    cuenta_origen = models.ForeignKey('bancos.CuentaBancaria', on_delete=models.PROTECT, null=True, blank=True, verbose_name="Cuenta Origen")
    medio_pago = models.CharField(max_length=20, choices=MEDIO_PAGO_CHOICES, verbose_name="Medio de Pago")
    referencia = models.CharField(max_length=100, blank=True, verbose_name="Referencia")
    notas = models.TextField(blank=True, verbose_name="Notas")

    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ['-fecha', 'id']

    def __str__(self):
        return f"Pago {self.monto} - Factura: {self.factura.numero} ({self.fecha})"

    def registrar(self):
        """
        Registra la salida de caja correspondiente a este pago en cuenta_origen.
        Solo actúa si cuenta_origen está definida.

        Bimoneda (B5+B6): calcula monto_usd directamente sin depender de convertir_a_usd:
          - VES con tasa > 0: monto_usd = monto / tasa_cambio
          - USD: monto_usd = monto (tasa_cambio forzada a 1)
        Garantiza atomicidad y bloqueo de la cuenta con select_for_update().
        """
        if not self.cuenta_origen:
            return  # Pago sin cuenta vinculada: solo registro contable, no movimiento caja

        from apps.bancos.services import registrar_movimiento_caja
        from apps.bancos.models import CuentaBancaria

        monto = Decimal(str(self.monto))
        tasa = Decimal(str(self.tasa_cambio))

        # Bimoneda — cálculo explícito de monto_usd
        if self.moneda == 'VES' and tasa > Decimal('0'):
            monto_usd = (monto / tasa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            # USD (o VES sin tasa): monto se trata directo en USD
            monto_usd = monto.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            tasa = Decimal('1.000000')

        with transaction.atomic():
            # Bloquear la cuenta para evitar saldo negativo concurrente
            cuenta = CuentaBancaria.objects.select_for_update().get(pk=self.cuenta_origen_id)
            registrar_movimiento_caja(
                cuenta=cuenta,
                tipo='SALIDA',
                monto=monto,
                moneda=self.moneda,
                tasa_cambio=tasa,
                referencia=f'PAGO-{self.factura.numero}',
                notas=f'Pago factura compra {self.factura.numero}',
            )
            self.monto_usd = monto_usd
            self.save(update_fields=['monto_usd'])

        logger.info(
            'Pago registrado | Factura: %s | Cuenta: %s | Monto: %s %s | USD: %s',
            self.factura.numero, self.cuenta_origen, monto, self.moneda, monto_usd
        )


class GastoServicio(AuditableModel):
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('PAGADO', 'Pagado'),
        ('ANULADO', 'Anulado'),
    ]
    MONEDA_CHOICES = [
        ('USD', 'USD - Dólar Americano'),
        ('VES', 'VES - Bolívar Soberano'),
    ]

    numero = models.CharField(max_length=20, unique=True, editable=False, verbose_name="Número de Gasto")
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, verbose_name="Proveedor")
    categoria_gasto = models.ForeignKey(
        'core.CategoriaGasto', on_delete=models.PROTECT,
        null=True, blank=True, verbose_name='Categoría')
    descripcion = models.TextField(verbose_name="Descripción")
    monto = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Monto")
    moneda = models.CharField(max_length=3, choices=MONEDA_CHOICES, default='USD', verbose_name="Moneda")
    tasa_cambio = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('1.000000'), verbose_name="Tasa de Cambio (VES/USD)")
    monto_usd = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'), editable=False, verbose_name="Monto en USD")
    fecha_emision = models.DateField(default=date.today, verbose_name="Fecha de Emisión")
    fecha_vencimiento = models.DateField(null=True, blank=True, verbose_name="Fecha de Vencimiento")
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='PENDIENTE', verbose_name="Estado")
    cuenta_pago = models.ForeignKey('bancos.CuentaBancaria', on_delete=models.PROTECT, null=True, blank=True, verbose_name="Cuenta de Pago")

    class Meta:
        verbose_name = "Gasto o Servicio"
        verbose_name_plural = "Gastos y Servicios"
        ordering = ['-numero']

    def __str__(self):
        return f"Gasto {self.numero} - {self.proveedor.nombre}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.numero:
            from apps.core.services import generar_numero
            self.numero = generar_numero('APC')
        if self.categoria_gasto and self.categoria_gasto.padre is None:
            from django.core.exceptions import ValidationError
            raise ValidationError('Seleccione una subcategoría, no una categoría padre.')
        super().save(*args, **kwargs)

    def pagar(self, cuenta_bancaria, monto, moneda, tasa_cambio):
        """
        Registra el pago del gasto/servicio:
          1. Valida que el gasto esté en estado PENDIENTE.
          2. Calcula monto_usd.
          3. Llama registrar_movimiento_caja tipo SALIDA en cuenta_bancaria.
          4. Guarda cuenta_pago, monto_usd y cambia estado a PAGADO.

        Args:
            cuenta_bancaria (CuentaBancaria): Cuenta desde donde se paga.
            monto           (Decimal): Monto en la moneda indicada.
            moneda          (str): 'USD' o 'VES'.
            tasa_cambio     (Decimal): Tasa BCV.

        Raises:
            EstadoInvalidoError: Si el gasto no está en estado PENDIENTE.
            SaldoInsuficienteError: Si la cuenta no tiene saldo.
        """
        if self.estado != 'PENDIENTE':
            raise EstadoInvalidoError('Gasto/Servicio', self.estado, 'pagar')

        from apps.bancos.services import registrar_movimiento_caja
        from apps.bancos.models import CuentaBancaria

        monto = Decimal(str(monto))
        tasa_cambio = Decimal(str(tasa_cambio))

        # Bimoneda — cálculo explícito de monto_usd
        if moneda == 'VES' and tasa_cambio > Decimal('0'):
            monto_usd = (monto / tasa_cambio).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            monto_usd = monto.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            tasa_cambio = Decimal('1.000000')

        with transaction.atomic():
            cuenta = CuentaBancaria.objects.select_for_update().get(pk=cuenta_bancaria.pk)
            registrar_movimiento_caja(
                cuenta=cuenta,
                tipo='SALIDA',
                monto=monto,
                moneda=moneda,
                tasa_cambio=tasa_cambio,
                referencia=self.numero,
                notas=f'Pago Gasto {self.numero}: {self.descripcion[:80]}',
            )
            self.monto_usd = monto_usd
            self.cuenta_pago = cuenta_bancaria
            self.estado = 'PAGADO'
            self.save(update_fields=['monto_usd', 'cuenta_pago', 'estado'])

        logger.info(
            'GastoServicio %s PAGADO | Cuenta: %s | Monto: %s %s | USD: %s.',
            self.numero, cuenta_bancaria, monto, moneda, monto_usd
        )
