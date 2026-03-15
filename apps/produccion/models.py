# -*- coding: utf-8 -*-
"""
Modelos del módulo de Producción para LacteOps.

Lógica de negocio implementada:
  - OrdenProduccion.save(): asigna número automático (B7), bloquea edición si CERRADA (B2).
  - OrdenProduccion.cargar_consumos_desde_receta(): crea ConsumoOP por cada ingrediente.
  - OrdenProduccion.cerrar(): valida unidades, valida stock, ejecuta salidas, registra entrada
                              del producto terminado, calcula costo_total y rendimiento (B8).
  - OrdenProduccion.anular(): solo desde estado ABIERTA.
  - OrdenProduccion.reabrir(): solo Master/Administrador; revierte movimientos (B2).
"""
import logging
from datetime import date
from decimal import Decimal

from django.db import models, transaction
from django.core.exceptions import PermissionDenied

from apps.core.models import AuditableModel, AuditLog
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
    unidad_rendimiento = models.CharField(max_length=20, default='L/Kg', verbose_name="Unidad de Rendimiento")  # B8
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
    kg_totales_salida = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True, editable=False, verbose_name="Kg Totales Salida")  # B8
    rendimiento_real = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True, editable=False, verbose_name="Rendimiento Real")   # B8
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
          - B7: Asigna número automático PRO-NNNN en creación si no tiene número.
          - B2: Bloquea toda modificación si la OP está CERRADA en BD (usar reabrir()).
          - Carga consumos desde receta en la primera creación.
        """
        # B7 — Numeración automática
        if self._state.adding and not self.numero:
            from apps.core.services import generar_numero
            self.numero = generar_numero('PRO')

        # B2 — Bloquear edición de órdenes cerradas
        # Se consulta el estado actual en BD para no interferir con cerrar() que
        # escribe 'CERRADA' en la misma llamada (en ese momento DB aún dice 'ABIERTA').
        if not self._state.adding:
            db_estado = (
                OrdenProduccion.objects
                .filter(pk=self.pk)
                .values_list('estado', flat=True)
                .first()
            )
            if db_estado == 'CERRADA':
                raise EstadoInvalidoError(
                    'Orden de Producción', 'CERRADA',
                    'modificar (orden cerrada — use reabrir())'
                )

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
          1. Validaciones previas (estado, salidas, unidades, stock).
          2. Dentro de transaction.atomic():
             a. Actualiza costo_unitario y subtotal de cada ConsumoOP al valor
                del momento del cierre (costo promedio vigente).
             b. Registra la SALIDA de cada materia prima en el Kardex.
             c. Calcula costo_total = suma de subtotales de consumos.
             d. Distribuye costo por valor de mercado entre salidas principales.
             e. Registra la ENTRADA del producto terminado en el Kardex.
             f. B8: Calcula kg_totales_salida y rendimiento_real.
             g. Actualiza la OP: costo_total, fecha_cierre, estado = CERRADA.

        Raises:
            EstadoInvalidoError:    Si la OP no está ABIERTA, o sin productos principales.
            UnidadIncompatibleError: Si la unidad de un ConsumoOP ≠ unidad del producto.
            StockInsuficienteError: Si alguna materia prima no tiene stock suficiente.
        """
        if self.estado != 'ABIERTA':
            raise EstadoInvalidoError('Orden de Producción', self.estado, 'cerrar')

        from apps.almacen.models import MovimientoInventario
        movs_existentes = MovimientoInventario.objects.filter(
            referencia=self.numero
        ).exists()
        if movs_existentes:
            raise EstadoInvalidoError(
                'Orden de Producción',
                self.estado,
                'ya tiene movimientos registrados — posible doble cierre'
            )

        salidas = list(self.salidas.select_related('producto').all())
        if not any(s.es_subproducto == False for s in salidas):
            raise EstadoInvalidoError(
                'Orden de Producción',
                self.estado,
                'cerrar (debe tener al menos un producto principal con es_subproducto=False)'
            )

        # ── EJECUCIÓN ATÓMICA ─────────────────────────────────────────────────
        with transaction.atomic():
            from apps.almacen.models import Producto as Prod

            consumos = list(
                self.consumos.select_related('producto__unidad_medida', 'unidad_medida').all()
            )

            # Bloquear stock de las materias primas
            producto_ids = [c.producto_id for c in consumos]
            list(Prod.objects.select_for_update().filter(id__in=producto_ids))

            # ── VALIDACIONES ────────────────────────────────────────────────────
            for consumo in consumos:
                consumo.producto.refresh_from_db()

                if consumo.unidad_medida_id != consumo.producto.unidad_medida_id:
                    raise UnidadIncompatibleError(
                        consumo.unidad_medida.simbolo,
                        consumo.producto.unidad_medida.simbolo,
                    )
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
                consumo.costo_unitario = Decimal(str(consumo.producto.costo_promedio))
                consumo.subtotal = (
                    Decimal(str(consumo.cantidad_consumida)) * consumo.costo_unitario
                )
                consumo.save(update_fields=['costo_unitario', 'subtotal'])

                registrar_salida(
                    producto=consumo.producto,
                    cantidad=consumo.cantidad_consumida,
                    referencia=self.numero,
                    notas=f'Consumo OP {self.numero}',
                )
                costo_total += consumo.subtotal

            # Producción conjunta: distribución de costo por valor de mercado
            salidas_principales = [s for s in salidas if not s.es_subproducto]
            salidas_subproductos = [s for s in salidas if s.es_subproducto]

            valor_total = sum(
                Decimal(str(s.precio_referencia)) * Decimal(str(s.cantidad))
                for s in salidas_principales
            )
            costo_asignado_sum = Decimal('0.00')

            principales_con_valor = []
            for i, s in enumerate(salidas_principales):
                val_i = Decimal(str(s.precio_referencia)) * Decimal(str(s.cantidad))
                principales_con_valor.append((val_i, i, s))

            principales_con_valor.sort(key=lambda x: x[0])

            for i, (val_i, idx, s) in enumerate(principales_con_valor):
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

            # ── B8: Calcular kg totales de salida y rendimiento real ──────────
            kg_salida = sum(
                Decimal(str(s.cantidad)) * Decimal(str(s.producto.peso_unitario_kg or 0))
                for s in salidas
            )
            mp_kg = sum(
                Decimal(str(c.cantidad_consumida)) * Decimal(str(c.producto.peso_unitario_kg or 0))
                for c in consumos
            )
            self.kg_totales_salida = Decimal(str(kg_salida)).quantize(Decimal('0.0001'))
            if mp_kg > 0:
                self.rendimiento_real = (kg_salida / mp_kg).quantize(Decimal('0.000001'))

            # Cerrar la orden
            self.costo_total = costo_total
            self.fecha_cierre = date.today()
            self.estado = 'CERRADA'
            self.save(update_fields=['costo_total', 'fecha_cierre', 'estado', 'kg_totales_salida', 'rendimiento_real'])

        logger.info(
            'OP %s CERRADA. CostoTotal: %s USD. Rendimiento: %s.',
            self.numero, costo_total, self.rendimiento_real
        )

    def reabrir(self, usuario, motivo):
        """
        B2 — Reabre una OrdenProduccion CERRADA revirtiendo los movimientos de inventario.
        Solo puede ejecutarlo un usuario con rol Master o Administrador.

        Args:
            usuario: instancia de User (no request).
            motivo (str): Motivo de la reapertura para auditoría.

        Raises:
            PermissionDenied: Si el usuario no tiene el rol requerido.
            EstadoInvalidoError: Si la OP no está en estado CERRADA.
        """
        if not usuario.is_superuser and not usuario.groups.filter(
            name__in=['Master', 'Administrador']
        ).exists():
            raise PermissionDenied(
                'Solo Master o Administrador pueden reabrir órdenes cerradas.'
            )

        if self.estado != 'CERRADA':
            raise EstadoInvalidoError(
                'Orden de Producción', self.estado, 'reabrir (solo desde CERRADA)'
            )

        with transaction.atomic():
            from apps.almacen.models import MovimientoInventario

            # Revertir movimientos de inventario de esta orden
            movimientos = list(
                MovimientoInventario.objects.filter(referencia=self.numero)
                .select_related('producto')
            )
            for mov in movimientos:
                if mov.tipo == 'SALIDA':
                    # Reversar SALIDA → ENTRADA compensatoria
                    registrar_entrada(
                        producto=mov.producto,
                        cantidad=mov.cantidad,
                        costo_unitario=mov.costo_unitario,
                        referencia=f'REV-{self.numero}',
                        notas=f'Reversión reapertura OP {self.numero}: {motivo}',
                    )
                else:  # ENTRADA
                    # Reversar ENTRADA → SALIDA compensatoria
                    registrar_salida(
                        producto=mov.producto,
                        cantidad=mov.cantidad,
                        referencia=f'REV-{self.numero}',
                        notas=f'Reversión reapertura OP {self.numero}: {motivo}',
                    )

            # Cambiar estado directamente en BD (evita el check B2 de save())
            OrdenProduccion.objects.filter(pk=self.pk).update(
                estado='ABIERTA',
                fecha_cierre=None,
                kg_totales_salida=None,
                rendimiento_real=None,
            )
            self.estado = 'ABIERTA'
            self.fecha_cierre = None
            self.kg_totales_salida = None
            self.rendimiento_real = None

            AuditLog.objects.create(
                usuario=usuario,
                modulo='produccion',
                accion='CAMBIO_ESTADO',
                entidad='OrdenProduccion',
                entidad_id=self.pk,
                before_data={'estado': 'CERRADA', 'numero': self.numero},
                after_data={'estado': 'ABIERTA', 'motivo': motivo},
            )

        logger.info('OP %s REABIERTA por %s. Motivo: %s', self.numero, usuario, motivo)

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
