# -*- coding: utf-8 -*-
"""
Modelos del módulo de Producción para LacteOps.

Lógica de negocio implementada:
  - OrdenProduccion.save(): en la creación, carga los consumos desde la receta.
  - OrdenProduccion.cargar_consumos_desde_receta(): crea ConsumoOP por cada ingrediente.
  - OrdenProduccion.cerrar(): valida unidades, valida stock, ejecuta salidas, registra entrada
                              del producto terminado, calcula costo_total.
  - OrdenProduccion.anular(): solo desde estado ABIERTA.
"""
import logging
from datetime import date
from decimal import Decimal

from django.db import models, transaction

from apps.core.models import AuditableModel
from apps.core.exceptions import (
    EstadoInvalidoError,
    StockInsuficienteError,
    UnidadIncompatibleError,
)
from apps.almacen.models import Producto, UnidadMedida
from apps.almacen.services import registrar_entrada, registrar_salida

logger = logging.getLogger(__name__)


class Receta(AuditableModel):
    nombre = models.CharField(max_length=100, verbose_name="Nombre")
    rendimiento_esperado = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Rendimiento Esperado")
    activo = models.BooleanField(default=True, verbose_name="Activo")

    class Meta:
        verbose_name = "Receta"
        verbose_name_plural = "Recetas"
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class RecetaDetalle(AuditableModel):
    receta = models.ForeignKey(Receta, related_name='detalles', on_delete=models.CASCADE, verbose_name="Receta")
    materia_prima = models.ForeignKey(Producto, on_delete=models.PROTECT, verbose_name="Materia Prima")
    cantidad_base = models.DecimalField(max_digits=18, decimal_places=4, verbose_name="Cantidad Base")
    unidad_medida = models.ForeignKey(UnidadMedida, on_delete=models.PROTECT, verbose_name="Unidad de Medida")

    class Meta:
        verbose_name = "Detalle de Receta"
        verbose_name_plural = "Detalles de Receta"
        ordering = ['id']

    def __str__(self):
        return f"{self.receta.nombre} - {self.materia_prima.codigo} ({self.cantidad_base} {self.unidad_medida.simbolo})"


class OrdenProduccion(AuditableModel):
    ESTADO_CHOICES = [
        ('ABIERTA', 'Abierta'),
        ('CERRADA', 'Cerrada'),
        ('ANULADA', 'Anulada'),
    ]

    numero = models.CharField(max_length=20, unique=True, verbose_name="Número de Orden")
    receta = models.ForeignKey(Receta, on_delete=models.PROTECT, verbose_name="Receta")
    fecha_apertura = models.DateField(auto_now_add=True, verbose_name="Fecha de Apertura")
    fecha_cierre = models.DateField(null=True, blank=True, verbose_name="Fecha de Cierre")
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='ABIERTA', verbose_name="Estado")
    costo_total = models.DecimalField(max_digits=18, decimal_places=2, default=0, editable=False, verbose_name="Costo Total (USD)")
    notas = models.TextField(blank=True, verbose_name="Notas")

    class Meta:
        verbose_name = "Orden de Producción"
        verbose_name_plural = "Órdenes de Producción"
        ordering = ['-fecha_apertura', '-numero']

    def __str__(self):
        return f"Orden {self.numero} - {self.receta.nombre}"

    def save(self, *args, **kwargs):
        """
        Override de save():
          - Si es una CREACIÓN NUEVA: guarda primero para obtener PK,
            luego pre-carga los consumos desde la receta.
          - Si es una ACTUALIZACIÓN: comportamiento normal.
        """
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            self.cargar_consumos_desde_receta()

    def cargar_consumos_desde_receta(self):
        """
        Pre-carga los ConsumoOP a partir de los detalles de la receta asociada.
        El costo_unitario inicial es el costo_promedio vigente de cada materia prima.
        El operador puede ajustar las cantidades antes de cerrar la orden.
        """
        for detalle_receta in self.receta.detalles.select_related(
            'materia_prima', 'unidad_medida'
        ).all():
            ConsumoOP.objects.create(
                orden=self,
                producto=detalle_receta.materia_prima,
                cantidad_consumida=detalle_receta.cantidad_base,
                unidad_medida=detalle_receta.unidad_medida,
                costo_unitario=detalle_receta.materia_prima.costo_promedio,
                subtotal=Decimal(str(detalle_receta.cantidad_base))
                         * Decimal(str(detalle_receta.materia_prima.costo_promedio)),
            )
        logger.info(
            'OP %s: consumos pre-cargados desde receta "%s".',
            self.numero, self.receta.nombre
        )

    def cerrar(self):
        """
        Cierra la Orden de Producción ejecutando:
          1. Validaciones previas (estado, cantidad_producida, unidades, stock).
          2. Dentro de transaction.atomic():
             a. Actualiza costo_unitario y subtotal de cada ConsumoOP al valor
                del momento del cierre (costo promedio vigente).
             b. Registra la SALIDA de cada materia prima en el Kardex.
             c. Calcula costo_total = suma de subtotales de consumos.
             d. Calcula costo_unitario del producto terminado.
             e. Registra la ENTRADA del producto terminado en el Kardex.
             f. Actualiza la OP: costo_total, fecha_cierre, estado = CERRADA.

        Raises:
            EstadoInvalidoError:    Si la OP no está ABIERTA, o cantidad_producida == 0.
            UnidadIncompatibleError: Si la unidad de un ConsumoOP ≠ unidad del producto.
            StockInsuficienteError: Si alguna materia prima no tiene stock suficiente.
        """
        if self.estado != 'ABIERTA':
            raise EstadoInvalidoError('Orden de Producción', self.estado, 'cerrar')

        salidas = list(self.salidas.select_related('producto').all())
        if not any(s.es_subproducto == False for s in salidas):
            raise EstadoInvalidoError(
                'Orden de Producción',
                self.estado,
                'cerrar (debe tener al menos un producto principal con es_subproducto=False)'
            )

        # ── EJECUCIÓN ATÓMICA ─────────────────────────────────────────────────
        with transaction.atomic():
            # Cargar consumos. select_for_update() explícito en producto para asegurar stock en validaciones
            from apps.almacen.models import Producto
            
            consumos = list(
                self.consumos.select_related('producto__unidad_medida', 'unidad_medida').all()
            )
            
            # Bloquear stock de las materias primas para la validación explícitamente.
            producto_ids = [c.producto_id for c in consumos]
            list(Producto.objects.select_for_update().filter(id__in=producto_ids))

            # ── VALIDACIONES (dentro de la transacción y con bloqueo) ────────────
            for consumo in consumos:
                # Actualizar el objeto producto del consumo con el estado actual ya bloqueado en BD
                consumo.producto.refresh_from_db()
                
                # Validar compatibilidad de unidades
                if consumo.unidad_medida_id != consumo.producto.unidad_medida_id:
                    raise UnidadIncompatibleError(
                        consumo.unidad_medida.simbolo,
                        consumo.producto.unidad_medida.simbolo,
                    )
                # Validar stock suficiente
                stock_disponible = Decimal(str(consumo.producto.stock_actual))
                cantidad_requerida = Decimal(str(consumo.cantidad_consumida))
                if stock_disponible < cantidad_requerida:
                    raise StockInsuficienteError(
                        consumo.producto.nombre,
                        stock_disponible,
                        cantidad_requerida,
                    )

            costo_total = Decimal('0.00')

            for consumo in consumos:
                # Refrescar el costo_promedio al momento exacto del cierre
                consumo.costo_unitario = Decimal(str(consumo.producto.costo_promedio))
                consumo.subtotal = (
                    Decimal(str(consumo.cantidad_consumida)) * consumo.costo_unitario
                )
                consumo.save(update_fields=['costo_unitario', 'subtotal'])

                # Registrar salida en el Kardex
                registrar_salida(
                    producto=consumo.producto,
                    cantidad=consumo.cantidad_consumida,
                    referencia=self.numero,
                    notas=f'Consumo OP {self.numero}',
                )
                costo_total += consumo.subtotal

            # Producción conjunta: calcular valor_total
            salidas_principales = [s for s in salidas if not s.es_subproducto]
            salidas_subproductos = [s for s in salidas if s.es_subproducto]
            
            valor_total = sum((Decimal(str(s.precio_referencia)) * Decimal(str(s.cantidad))) for s in salidas_principales)
            costo_asignado_sum = Decimal('0.00')

            # Ordenar salidas_principales por valor_i
            principales_con_valor = []
            for i, s in enumerate(salidas_principales):
                val_i = Decimal(str(s.precio_referencia)) * Decimal(str(s.cantidad))
                principales_con_valor.append((val_i, i, s))
                
            principales_con_valor.sort(key=lambda x: x[0])  # El de mayor valor queda al final

            for i, (val_i, idx, s) in enumerate(principales_con_valor):
                # El último (el de mayor valor) absorbe el residuo
                if i == len(principales_con_valor) - 1:
                    costo_asignado = costo_total - costo_asignado_sum
                else:
                    costo_asignado = costo_total * (val_i / valor_total)
                
                costo_asignado_sum += costo_asignado
                s.costo_asignado = costo_asignado
                s.save(update_fields=['costo_asignado'])

                costo_unitario_i = costo_asignado / Decimal(str(s.cantidad))

                registrar_entrada(
                    producto=s.producto,
                    cantidad=s.cantidad,
                    costo_unitario=costo_unitario_i,
                    referencia=self.numero,
                    notas=f'Producción Principal OP {self.numero}',
                )

            for s in salidas_subproductos:
                s.costo_asignado = Decimal('0.000000')
                s.save(update_fields=['costo_asignado'])

                registrar_entrada(
                    producto=s.producto,
                    cantidad=s.cantidad,
                    costo_unitario=Decimal('0.000000'),
                    referencia=self.numero,
                    notas=f'Subproducto OP {self.numero}',
                )

            # Cerrar la orden
            self.costo_total = costo_total
            self.fecha_cierre = date.today()
            self.estado = 'CERRADA'
            self.save(update_fields=['costo_total', 'fecha_cierre', 'estado'])

        logger.info(
            'OP %s CERRADA. CostoTotal: %s USD.',
            self.numero, costo_total
        )

    def anular(self):
        """
        Anula la Orden de Producción. Solo es posible desde estado ABIERTA.

        Raises:
            EstadoInvalidoError: Si la OP no está en estado ABIERTA.
        """
        if self.estado != 'ABIERTA':
            raise EstadoInvalidoError('Orden de Producción', self.estado, 'anular')

        self.estado = 'ANULADA'
        self.save(update_fields=['estado'])
        logger.info('OP %s ANULADA.', self.numero)


class ConsumoOP(AuditableModel):
    orden = models.ForeignKey(OrdenProduccion, related_name='consumos', on_delete=models.CASCADE, verbose_name="Orden de Producción")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, verbose_name="Producto (Materia Prima)")
    cantidad_consumida = models.DecimalField(max_digits=18, decimal_places=4, verbose_name="Cantidad Consumida")
    unidad_medida = models.ForeignKey(UnidadMedida, on_delete=models.PROTECT, verbose_name="Unidad de Medida")
    costo_unitario = models.DecimalField(max_digits=18, decimal_places=6, default=Decimal('0.000000'), verbose_name="Costo Unitario (USD)")
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0.00'), editable=False, verbose_name="Subtotal (USD)")

    class Meta:
        verbose_name = "Consumo de Orden de Producción"
        verbose_name_plural = "Consumos de Orden de Producción"
        ordering = ['id']

    def __str__(self):
        return f"Consumo OP {self.orden.numero} - {self.producto.codigo}"


class SalidaOrden(AuditableModel):
    orden = models.ForeignKey(OrdenProduccion, related_name='salidas', on_delete=models.PROTECT, verbose_name="Orden")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, verbose_name="Producto")
    cantidad = models.DecimalField(max_digits=18, decimal_places=4, verbose_name="Cantidad")
    precio_referencia = models.DecimalField(max_digits=18, decimal_places=2, verbose_name="Precio Referencia")
    es_subproducto = models.BooleanField(default=False, verbose_name="Es Subproducto")
    costo_asignado = models.DecimalField(max_digits=18, decimal_places=6, editable=False, default=0, verbose_name="Costo Asignado")

    class Meta:
        verbose_name = "Salida de Orden"
        verbose_name_plural = "Salidas de Orden"

    def __str__(self):
        return f"Salida {self.producto.codigo} OP {self.orden.numero}"
