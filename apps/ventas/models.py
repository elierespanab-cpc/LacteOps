# -*- coding: utf-8 -*-
"""
Modelos del módulo de Ventas para LacteOps.

Lógica de negocio implementada:
  - DetalleFacturaVenta.save(): auto-calcula subtotal y recalcula total de cabecera.
  - FacturaVenta.save(): en la creación dispara emitir() automáticamente.
  - FacturaVenta.emitir(): descuenta stock (salidas al Kardex) de forma atómica.
  - FacturaVenta.marcar_cobrada(): valida que el saldo esté cubierto y cambia estado.
"""
import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import models, transaction
from django.conf import settings

from apps.core.models import AuditableModel
from apps.core.exceptions import EstadoInvalidoError
from apps.almacen.models import Producto, MovimientoInventario
from apps.almacen.services import registrar_salida

logger = logging.getLogger(__name__)


class Cliente(AuditableModel):
    nombre = models.CharField(max_length=200, verbose_name="Nombre")
    rif = models.CharField(max_length=20, unique=True, verbose_name="RIF / Identificación")
    telefono = models.CharField(max_length=20, blank=True, verbose_name="Teléfono")
    limite_credito = models.DecimalField(max_digits=18, decimal_places=2, default=0, verbose_name="Límite de Crédito (USD)")
    dias_credito = models.PositiveIntegerField(default=30, verbose_name="Días de Crédito")
    TIPO_CONTROL_CHOICES = [
        ('BLOQUEO', 'Bloqueo'),
        ('ADVERTENCIA', 'Advertencia'),
    ]
    tipo_control_credito = models.CharField(max_length=15, choices=TIPO_CONTROL_CHOICES, default='ADVERTENCIA', verbose_name="Control de Crédito")
    activo = models.BooleanField(default=True, verbose_name="Activo")

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"
        ordering = ['nombre']

    def __str__(self):
        return f"{self.rif} - {self.nombre}"

    def get_saldo_total_pendiente(self):
        saldo_total = Decimal('0.00')
        for factura in self.facturaventa_set.exclude(estado='ANULADA'):
            saldo_total += factura.get_saldo_pendiente()
        return saldo_total


class ListaPrecio(AuditableModel):
    nombre = models.CharField(max_length=100, verbose_name="Nombre de Lista")
    activa = models.BooleanField(default=True, verbose_name="Activa")
    requiere_aprobacion = models.BooleanField(default=True, verbose_name="Requiere Aprobación")

    class Meta:
        verbose_name = "Lista de Precios"
        verbose_name_plural = "Listas de Precios"
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class DetalleLista(AuditableModel):
    lista = models.ForeignKey(ListaPrecio, related_name='detalles', on_delete=models.PROTECT, verbose_name="Lista")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='precios_en_tarifas', verbose_name="Producto")
    precio = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Precio")
    aprobado = models.BooleanField(default=False, verbose_name="Aprobado")
    aprobado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Aprobado por")
    vigente_desde = models.DateField(verbose_name="Vigente Desde")

    class Meta:
        verbose_name = "Detalle de Lista de Precio"
        verbose_name_plural = "Detalles de Lista de Precio"
        unique_together = ('lista', 'producto')

    def __str__(self):
        return f"{self.lista.nombre} - {self.producto.codigo} - {self.precio}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            try:
                original = DetalleLista.objects.get(pk=self.pk)
                if original.precio != self.precio:
                    self.aprobado = False
                    self.aprobado_por = None
            except DetalleLista.DoesNotExist:
                pass
        super().save(*args, **kwargs)


class FacturaVenta(AuditableModel):
    ESTADO_CHOICES = [
        ('EMITIDA', 'Emitida'),
        ('COBRADA', 'Cobrada'),
        ('ANULADA', 'Anulada'),
    ]
    MONEDA_CHOICES = [
        ('USD', 'USD - Dólar Americano'),
        ('VES', 'VES - Bolívar Soberano'),
    ]

    numero = models.CharField(max_length=20, unique=True, verbose_name="Número de Factura")
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, verbose_name="Cliente")
    lista_precio = models.ForeignKey(ListaPrecio, on_delete=models.PROTECT, null=True, verbose_name="Lista de Precios")
    fecha = models.DateField(verbose_name="Fecha")
    fecha_vencimiento = models.DateField(null=True, blank=True, editable=False, verbose_name="Fecha de Vencimiento")
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='EMITIDA', verbose_name="Estado")
    moneda = models.CharField(max_length=3, choices=MONEDA_CHOICES, default='USD', verbose_name="Moneda")
    tasa_cambio = models.DecimalField(max_digits=18, decimal_places=6, default=1.000000, verbose_name="Tasa de Cambio (VES/USD)")
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0, editable=False, verbose_name="Total (USD)")
    notas = models.TextField(blank=True, verbose_name="Notas")

    class Meta:
        verbose_name = "Factura de Venta"
        verbose_name_plural = "Facturas de Venta"
        ordering = ['-fecha', '-numero']

    def __str__(self):
        return f"Factura Venta {self.numero} - {self.cliente.nombre}"

    def get_saldo_pendiente(self):
        total_cobrado = self.cobros.aggregate(
            total=models.Sum('monto')
        )['total'] or Decimal('0.00')
        return self.total - total_cobrado

    def save(self, *args, **kwargs):
        """
        Override de save():
          - B7: Si es una creación y no tiene número, genera uno automáticamente (VTA).
          - En actualizaciones: comportamiento normal de AuditableModel.

        Nota: La llamada a emitir() en la creación ocurre DESPUÉS de que
        los detalles existen, lo que en la práctica significa que emitir()
        se llama explícitamente desde el Admin una vez que los detalles
        ya fueron guardados. La creación vía Admin registra la factura y
        los detalles en dos pasos, por lo que el flujo correcto es:
          1. Crear la factura (estado EMITIDA, sin detalles todavía).
          2. Guardar detalles (auto-calcula subtotales y total).
          3. Ejecutar la action "emitir" desde el Admin para disparar las salidas.
        """
        if self._state.adding and not self.numero:
            from apps.core.services import generar_numero
            self.numero = generar_numero('VTA')
        super().save(*args, **kwargs)

    def emitir(self):
        """
        Ejecuta las salidas de inventario para esta factura de venta.

        FASE 1 — Control de crédito (antes de tocar inventario):
          - Calcula fecha_vencimiento = fecha + dias_credito del cliente.
          - Detecta facturas vencidas del cliente
            (estado==EMITIDA AND fecha_vencimiento < hoy AND saldo_pendiente > 0).
          - Si tipo_control_credito == BLOQUEO: EstadoInvalidoError con lista de facturas.
          - Si tipo_control_credito == ADVERTENCIA: logger.warning() y continúa.

        FASE 2 — Salidas de inventario (transaction.atomic()).

        Raises:
            EstadoInvalidoError: Si la factura no está en EMITIDA, ya fue procesada,
                                 o el cliente tiene crédito bloqueado.
        """
        if self.estado != 'EMITIDA':
            raise EstadoInvalidoError('Factura de Venta', self.estado, 'emitir')

        if not self.lista_precio_id:
            raise EstadoInvalidoError('Factura de Venta', self.estado, 'emitir (debe seleccionar una lista de precios)')

        # Idempotencia: no duplicar salidas
        ya_procesada = MovimientoInventario.objects.filter(
            referencia=self.numero, tipo='SALIDA'
        ).exists()
        if ya_procesada:
            raise EstadoInvalidoError(
                'Factura de Venta',
                self.estado,
                'emitir (ya existen movimientos de inventario para esta factura)',
            )

        # ── FASE 1: Control de crédito ────────────────────────────────────────
        hoy = date.today()

        # Asignar fecha_vencimiento en este momento
        self.fecha_vencimiento = self.fecha + timedelta(days=self.cliente.dias_credito)
        self.save(update_fields=['fecha_vencimiento'])

        # Buscar facturas vencidas del mismo cliente
        facturas_vencidas = []
        for fv in self.cliente.facturaventa_set.filter(estado='EMITIDA').exclude(pk=self.pk):
            if fv.fecha_vencimiento and fv.fecha_vencimiento < hoy:
                saldo = fv.get_saldo_pendiente()
                if saldo > Decimal('0'):
                    facturas_vencidas.append(fv.numero)

        if facturas_vencidas:
            detalle = ', '.join(facturas_vencidas)
            if self.cliente.tipo_control_credito == 'BLOQUEO':
                raise EstadoInvalidoError(
                    'Factura de Venta',
                    self.estado,
                    f'emitir — cliente bloqueado por facturas vencidas: {detalle}',
                )
            else:  # ADVERTENCIA
                logger.warning(
                    'ADVERTENCIA CRÉDITO | Cliente: %s | Facturas vencidas: %s | '
                    'Emisión de %s continúa.',
                    self.cliente, detalle, self.numero
                )

        # ── FASE 2: Asignación de precios y salidas de inventario ────────────────────
        with transaction.atomic():
            detalles = list(self.detalles.select_related('producto').all())
            for detalle in detalles:
                detalle_lista = DetalleLista.objects.filter(
                    lista_id=self.lista_precio_id,
                    producto_id=detalle.producto_id,
                    aprobado=True
                ).first()
                if not detalle_lista:
                    raise EstadoInvalidoError(
                        'Factura de Venta', self.estado,
                        f'emitir (producto {detalle.producto.codigo} sin precio aprobado en la lista)'
                    )
                
                # Asignar detalle.precio_unitario desde DetalleLista
                detalle.precio_unitario = detalle_lista.precio
                # El save() del detalle recalcula subtotal y total de la factura
                detalle.save()

            for detalle in detalles:
                registrar_salida(
                    producto=detalle.producto,
                    cantidad=detalle.cantidad,
                    referencia=self.numero,
                    notas=f'Emisión Factura Venta {self.numero}',
                )

        logger.info('Factura venta %s emitida. Salidas de inventario registradas.', self.numero)

    def marcar_cobrada(self):
        """
        Marca la factura como COBRADA si el total de cobros cubre el total.

        Raises:
            EstadoInvalidoError: Si la factura no está en estado EMITIDA,
                                 o si el saldo pendiente es mayor que cero.
        """
        if self.estado != 'EMITIDA':
            raise EstadoInvalidoError('Factura de Venta', self.estado, 'marcar como cobrada')

        total_cobrado = self.cobros.aggregate(
            total=models.Sum('monto')
        )['total'] or Decimal('0.00')
        total_cobrado = Decimal(str(total_cobrado))
        total_factura = Decimal(str(self.total))

        if total_cobrado < total_factura:
            saldo_pendiente = total_factura - total_cobrado
            raise EstadoInvalidoError(
                'Factura de Venta',
                self.estado,
                f'marcar como cobrada (saldo pendiente: {saldo_pendiente} USD)',
            )

        self.estado = 'COBRADA'
        self.save(update_fields=['estado'])
        logger.info('Factura venta %s marcada como COBRADA. Total cobrado: %s USD.', self.numero, total_cobrado)


class DetalleFacturaVenta(AuditableModel):
    factura = models.ForeignKey(FacturaVenta, related_name='detalles', on_delete=models.CASCADE, verbose_name="Factura")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, verbose_name="Producto")
    cantidad = models.DecimalField(max_digits=18, decimal_places=4, verbose_name="Cantidad")
    precio_unitario = models.DecimalField(max_digits=18, decimal_places=6, editable=False, verbose_name="Precio Unitario")
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, editable=False, verbose_name="Subtotal (USD)")

    class Meta:
        verbose_name = "Detalle de Factura de Venta"
        verbose_name_plural = "Detalles de Facturas de Venta"
        ordering = ['id']

    def __str__(self):
        return f"{self.factura.numero} - {self.producto.codigo} (x{self.cantidad})"

    def save(self, *args, **kwargs):
        """
        Calcula el subtotal de la línea y recalcula el total de la cabecera.
        Intenta obtener el precio de la lista de la factura si aún no está fijado.
        """
        if (self.precio_unitario is None or self.precio_unitario == Decimal('0')) and self.factura.lista_precio:
            # Importar localmente para evitar problemas de orden de carga si fuera necesario
            from .models import DetalleLista
            dl = DetalleLista.objects.filter(
                lista=self.factura.lista_precio,
                producto=self.producto,
                aprobado=True
            ).first()
            if dl:
                self.precio_unitario = dl.precio

        precio = self.precio_unitario if self.precio_unitario is not None else Decimal('0.000000')
        self.subtotal = Decimal(str(self.cantidad)) * Decimal(str(precio))
        super().save(*args, **kwargs)

        # Recalcular el total de la factura cabecera
        total_factura = self.factura.detalles.aggregate(
            total=models.Sum('subtotal')
        )['total'] or Decimal('0.00')
        self.factura.total = total_factura
        self.factura.save(update_fields=['total'])


class Cobro(AuditableModel):
    MEDIO_PAGO_CHOICES = [
        ('EFECTIVO_USD', 'Efectivo USD'),
        ('EFECTIVO_VES', 'Efectivo VES'),
        ('TRANSFERENCIA_USD', 'Transferencia USD'),
        ('TRANSFERENCIA_VES', 'Transferencia VES'),
    ]

    factura = models.ForeignKey(FacturaVenta, related_name='cobros', on_delete=models.PROTECT, verbose_name="Factura de Venta")
    fecha = models.DateField(verbose_name="Fecha de Cobro")
    monto = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Monto del Cobro (USD)")
    moneda = models.CharField(max_length=3, choices=FacturaVenta.MONEDA_CHOICES, default='USD', verbose_name="Moneda")
    tasa_cambio = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('1.000000'), verbose_name="Tasa de Cambio (VES/USD)")
    monto_usd = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'), editable=False, verbose_name="Monto en USD")
    cuenta_destino = models.ForeignKey('bancos.CuentaBancaria', on_delete=models.PROTECT, null=True, blank=True, verbose_name="Cuenta Destino")
    medio_pago = models.CharField(max_length=20, choices=MEDIO_PAGO_CHOICES, verbose_name="Medio de Pago")
    referencia = models.CharField(max_length=100, blank=True, verbose_name="Referencia")
    notas = models.TextField(blank=True, verbose_name="Notas")

    class Meta:
        verbose_name = "Cobro"
        verbose_name_plural = "Cobros"
        ordering = ['-fecha', 'id']

    def __str__(self):
        return f"Cobro de {self.monto} a {self.factura.numero} el {self.fecha}"

    def registrar(self):
        """
        Registra la entrada de caja correspondiente a este cobro en cuenta_destino.
        Solo actúa si cuenta_destino está definida.

        Bimoneda (B5+B6): calcula monto_usd directamente sin depender de convertir_a_usd:
          - VES con tasa > 0: monto_usd = monto / tasa_cambio
          - USD: monto_usd = monto (tasa_cambio forzada a 1)
        Garantiza atomicidad y bloqueo de la cuenta con select_for_update().
        """
        if not self.cuenta_destino:
            return  # Cobro sin cuenta vinculada: solo registro contable, no movimiento caja

        from apps.bancos.services import registrar_movimiento_caja
        from apps.bancos.models import CuentaBancaria

        monto = Decimal(str(self.monto))
        tasa = Decimal(str(self.tasa_cambio))

        # Bimoneda — cálculo explícito de monto_usd
        if self.moneda == 'VES' and tasa > Decimal('0'):
            monto_usd = (monto / tasa).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            monto_usd = monto.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            tasa = Decimal('1.000000')

        with transaction.atomic():
            # Bloquear la cuenta para evitar saldo concurrente incorrecto
            cuenta = CuentaBancaria.objects.select_for_update().get(pk=self.cuenta_destino_id)
            registrar_movimiento_caja(
                cuenta=cuenta,
                tipo='ENTRADA',
                monto=monto,
                moneda=self.moneda,
                tasa_cambio=tasa,
                referencia=f'COBRO-{self.factura.numero}',
                notas=f'Cobro factura venta {self.factura.numero}',
            )
            self.monto_usd = monto_usd
            self.save(update_fields=['monto_usd'])

        logger.info(
            'Cobro registrado | Factura: %s | Cuenta: %s | Monto: %s %s | USD: %s',
            self.factura.numero, self.cuenta_destino, monto, self.moneda, monto_usd
        )

