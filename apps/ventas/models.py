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

from django.db.models import Sum

from apps.core.models import AuditableModel, TasaCambio
from apps.core.exceptions import EstadoInvalidoError, StockInsuficienteError
from apps.core.rbac import usuario_en_grupo
from apps.almacen.models import Producto, MovimientoInventario
from apps.almacen.services import registrar_entrada, registrar_salida, convertir_a_usd

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
        ('BORRADOR', 'Borrador'),
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
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='BORRADOR', verbose_name="Estado")
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
        nc_total = self.notas_credito.filter(estado='EMITIDA').aggregate(
            total=models.Sum('total')
        )['total'] or Decimal('0.00')
        return max(Decimal('0.00'), self.total - Decimal(str(total_cobrado)) - Decimal(str(nc_total)))

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
        Acepta BORRADOR o EMITIDA; si viene de BORRADOR, primero cambia a EMITIDA.
        """
        if self.estado not in ('BORRADOR', 'EMITIDA'):
            raise EstadoInvalidoError('Factura de Venta', self.estado, 'emitir')

        if self.estado == 'BORRADOR':
            self.estado = 'EMITIDA'
            self.save(update_fields=['estado'])

        # ── FIX C2: Respetar fecha_venta_abierta ────────────────────────────────
        # Si la configuración no permite edición manual de fecha, forzar fecha SO.
        from apps.core.models import ConfiguracionEmpresa
        config = ConfiguracionEmpresa.objects.first()
        if config and not config.fecha_venta_abierta:
            self.fecha = date.today()

        # ── FASE 0: Validación de Tasa de Cambio (Sprint 4) ────────────────────
        if self.moneda == 'VES' and self.tasa_cambio == Decimal('1.000000'):
            from apps.core.models import TasaCambio
            tasa_obj = TasaCambio.objects.filter(fecha__gte=self.fecha).order_by('fecha').first()
            if not tasa_obj:
                raise EstadoInvalidoError('Factura de Venta', self.estado, 
                    'emitir (sin tasa BCV cargada para la fecha o posterior)')
            self.tasa_cambio = tasa_obj.tasa

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

        # ── FASE 1: Control de crédito (lectura pura, sin writes a BD) ──────────
        hoy = date.today()

        # Calcular fecha_vencimiento en memoria (se persiste dentro del atomic)
        self.fecha_vencimiento = self.fecha + timedelta(days=self.cliente.dias_credito)

        # Buscar facturas vencidas del mismo cliente (solo lectura)
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

        # ── FASE 2: Persistencia + salidas de inventario (todo atómico) ──────────
        # El save() de fecha/tasa/vencimiento va DENTRO del atomic para que si
        # alguna salida falla por stock insuficiente, el rollback revierta también
        # los campos de cabecera — sin dejar la factura parcialmente modificada.
        with transaction.atomic():
            # Persistir fecha, tasa y vencimiento atómicamente con los movimientos
            self.save(update_fields=['fecha', 'fecha_vencimiento', 'tasa_cambio'])

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
    monto = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Monto")
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


class NotaCredito(AuditableModel):
    ESTADOS = [('BORRADOR', 'Borrador'), ('EMITIDA', 'Emitida'), ('ANULADA', 'Anulada')]
    numero = models.CharField(max_length=20, editable=False, default='')
    factura_origen = models.ForeignKey('FacturaVenta', models.PROTECT, related_name='notas_credito')
    cliente = models.ForeignKey('Cliente', models.PROTECT, related_name='notas_credito')
    fecha = models.DateField()
    moneda = models.CharField(max_length=3, default='USD')
    tasa_cambio = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('1.000000'))
    total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))
    estado = models.CharField(max_length=10, choices=ESTADOS, default='BORRADOR')
    notas = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Nota de Crédito'
        verbose_name_plural = 'Notas de Crédito'
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f'{self.numero} — {self.cliente}'

    def save(self, *args, **kwargs):
        if self._state.adding:
            from apps.core.services import generar_numero
            if not self.numero:
                self.numero = generar_numero('NTC')
            self.cliente = self.factura_origen.cliente
        super().save(*args, **kwargs)

    def emitir(self):
        if self.estado != 'BORRADOR':
            raise EstadoInvalidoError('Nota de Crédito', self.estado, 'emitir')
        if self.factura_origen.estado not in ('EMITIDA', 'COBRADA'):
            raise EstadoInvalidoError(
                'Factura origen', self.factura_origen.estado,
                'emitir Nota de Crédito (debe estar EMITIDA o COBRADA)')

        with transaction.atomic():
            for detalle in self.detalles.select_related('producto').select_for_update():
                # Validar que la cantidad no excede lo facturado menos lo ya devuelto
                facturado = DetalleFacturaVenta.objects.filter(
                    factura=self.factura_origen,
                    producto=detalle.producto
                ).aggregate(total=Sum('cantidad'))['total'] or Decimal('0')

                ya_devuelto = DetalleNotaCredito.objects.filter(
                    nota_credito__factura_origen=self.factura_origen,
                    nota_credito__estado='EMITIDA',
                    producto=detalle.producto
                ).exclude(nota_credito=self).aggregate(
                    total=Sum('cantidad'))['total'] or Decimal('0')

                disponible = Decimal(str(facturado)) - Decimal(str(ya_devuelto))
                if detalle.cantidad > disponible:
                    raise StockInsuficienteError(
                        detalle.producto.nombre, disponible, detalle.cantidad)

                # Reponer inventario al costo promedio vigente (en USD)
                costo_usd = convertir_a_usd(
                    detalle.precio_unitario, self.moneda, self.tasa_cambio)
                registrar_entrada(
                    producto=detalle.producto,
                    cantidad=detalle.cantidad,
                    costo_unitario=costo_usd,
                    referencia=self.numero,
                    notas=f'Devolución NC {self.numero}')

            self.estado = 'EMITIDA'
            self.save(update_fields=['estado'])
            logger.info('Nota de Crédito %s emitida.', self.numero)

    def anular(self):
        if self.estado != 'EMITIDA':
            raise EstadoInvalidoError('Nota de Crédito', self.estado, 'anular')

        with transaction.atomic():
            for detalle in self.detalles.select_related('producto').select_for_update():
                # Revertir la entrada de inventario generada al emitir
                registrar_salida(
                    producto=detalle.producto,
                    cantidad=detalle.cantidad,
                    referencia=self.numero,
                    notas=f'Anulación NC {self.numero}')

            self.estado = 'ANULADA'
            self.save(update_fields=['estado'])
            logger.info('Nota de Crédito %s anulada.', self.numero)


class DetalleNotaCredito(models.Model):
    nota_credito = models.ForeignKey('NotaCredito', models.CASCADE, related_name='detalles')
    producto = models.ForeignKey('almacen.Producto', models.PROTECT)
    cantidad = models.DecimalField(max_digits=18, decimal_places=4)
    precio_unitario = models.DecimalField(max_digits=18, decimal_places=6)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'))

    class Meta:
        verbose_name = 'Detalle Nota de Crédito'

    def __str__(self):
        return f'{self.producto} x {self.cantidad}'

    def save(self, *args, **kwargs):
        self.subtotal = (
            Decimal(str(self.cantidad)) * Decimal(str(self.precio_unitario))
        ).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)
        # Recalcular total de la cabecera
        total_nc = self.nota_credito.detalles.aggregate(
            total=models.Sum('subtotal')
        )['total'] or Decimal('0.00')
        self.nota_credito.total = Decimal(str(total_nc))
        self.nota_credito.save(update_fields=['total'])

