# -*- coding: utf-8 -*-
"""
Modelos del módulo de Almacén para LacteOps.

Lógica de negocio añadida:
  - AjusteInventario.save(): asigna número automático en creación.
  - AjusteInventario.aprobar(): registra entrada o salida al Kardex según tipo.
  - AjusteInventario.anular(): solo desde estado BORRADOR.
"""
import logging
from decimal import Decimal

from django.db import models

from apps.core.models import AuditableModel
from apps.core.exceptions import EstadoInvalidoError

logger = logging.getLogger(__name__)


class Categoria(AuditableModel):
    nombre = models.CharField(max_length=100, verbose_name="Nombre")
    activo = models.BooleanField(default=True, verbose_name="Activo")

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class UnidadMedida(models.Model):
    nombre = models.CharField(max_length=50, unique=True, verbose_name="Nombre")
    simbolo = models.CharField(max_length=10, unique=True, verbose_name="Símbolo")
    activo = models.BooleanField(default=True, verbose_name="Activo")

    class Meta:
        verbose_name = "Unidad de Medida"
        verbose_name_plural = "Unidades de Medida"
        ordering = ['nombre']

    def __str__(self):
        return f"{self.nombre} ({self.simbolo})"


class Producto(AuditableModel):
    codigo = models.CharField(max_length=20, unique=True, verbose_name="Código")
    nombre = models.CharField(max_length=200, verbose_name="Nombre")
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, verbose_name="Categoría")
    unidad_medida = models.ForeignKey(UnidadMedida, on_delete=models.PROTECT, verbose_name="Unidad de Medida")
    stock_actual = models.DecimalField(max_digits=18, decimal_places=4, default=0, verbose_name="Stock Actual")
    costo_promedio = models.DecimalField(max_digits=18, decimal_places=6, default=0, verbose_name="Costo Promedio")
    precio_venta = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True, verbose_name="Precio de Venta (Ref)")
    peso_unitario_kg = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True, verbose_name="Peso Unitario (kg)")
    es_materia_prima = models.BooleanField(default=False, verbose_name="Es Materia Prima")
    es_producto_terminado = models.BooleanField(default=False, verbose_name="Es Producto Terminado")
    activo = models.BooleanField(default=True, verbose_name="Activo")

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ['codigo']

    def __str__(self):
        return f"[{self.codigo}] {self.nombre}"


class MovimientoInventario(models.Model):
    TIPO_CHOICES = [
        ('ENTRADA', 'Entrada'),
        ('SALIDA', 'Salida'),
    ]

    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, verbose_name="Producto")
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, verbose_name="Tipo de Movimiento")
    cantidad = models.DecimalField(max_digits=18, decimal_places=4, verbose_name="Cantidad")
    costo_unitario = models.DecimalField(max_digits=18, decimal_places=6, verbose_name="Costo Unitario")
    referencia = models.CharField(max_length=50, verbose_name="Referencia")
    fecha = models.DateTimeField(auto_now_add=True, verbose_name="Fecha del Movimiento")
    notas = models.TextField(blank=True, verbose_name="Notas")

    class Meta:
        verbose_name = "Movimiento de Inventario"
        verbose_name_plural = "Movimientos de Inventario"
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.fecha.strftime('%Y-%m-%d %H:%M:%S')} - [{self.producto.codigo}] - {self.tipo}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise NotImplementedError("Los movimientos de inventario no pueden ser modificados, son de log inmutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Los movimientos de inventario no pueden ser eliminados.")


class AjusteInventario(AuditableModel):
    TIPO_CHOICES = [
        ('ENTRADA_AJUSTE', 'Entrada por Ajuste'),
        ('SALIDA_AJUSTE', 'Salida por Ajuste'),
        ('MERMA', 'Merma'),
        ('DIFERENCIA_FISICA', 'Diferencia Física'),
    ]
    ESTADO_CHOICES = [
        ('BORRADOR', 'Borrador'),
        ('APROBADO', 'Aprobado'),
        ('ANULADO', 'Anulado'),
    ]

    # Tipos que incrementan stock
    TIPOS_ENTRADA = {'ENTRADA_AJUSTE', 'DIFERENCIA_FISICA'}
    # Tipos que decrementan stock
    TIPOS_SALIDA = {'SALIDA_AJUSTE', 'MERMA'}

    numero = models.CharField(max_length=20, unique=True, editable=False, verbose_name="Número de Ajuste")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, verbose_name="Producto")
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, verbose_name="Tipo de Ajuste")
    cantidad = models.DecimalField(max_digits=18, decimal_places=4, verbose_name="Cantidad")
    motivo = models.TextField(verbose_name="Motivo")
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES, default='BORRADOR', verbose_name="Estado")

    class Meta:
        verbose_name = "Ajuste de Inventario"
        verbose_name_plural = "Ajustes de Inventario"
        ordering = ['-id']

    def __str__(self):
        return f"Ajuste {self.numero} - {self.producto.codigo}"

    def save(self, *args, **kwargs):
        """Asigna número automático en creación usando la secuencia INV."""
        if self._state.adding and not self.numero:
            from apps.core.services import generar_numero
            self.numero = generar_numero('INV')
        super().save(*args, **kwargs)

    def aprobar(self, usuario=None):
        """
        Aprueba el ajuste registrando el movimiento de inventario correspondiente.

        Tipos que generan ENTRADA al Kardex (incrementan stock):
          ENTRADA_AJUSTE, DIFERENCIA_FISICA → registrar_entrada() al costo promedio vigente.

        Tipos que generan SALIDA del Kardex (decrementan stock):
          SALIDA_AJUSTE, MERMA → registrar_salida().

        Control RBAC: Si el valor total del ajuste supera 1000 USD, requiere
        que el usuario que aprueba pertenezca a Master o Administrador.

        Raises:
            EstadoInvalidoError: Si el ajuste no está en estado BORRADOR.
            StockInsuficienteError: Si la salida dejaría stock negativo.
            PermissionDenied: Si supera umbral y no tiene permisos suficientes.
        """
        if self.estado != 'BORRADOR':
            raise EstadoInvalidoError('Ajuste de Inventario', self.estado, 'aprobar')

        valor_ajuste = Decimal(str(self.cantidad)) * Decimal(str(self.producto.costo_promedio))
        umbral_usd = Decimal('1000.00')

        if valor_ajuste > umbral_usd:
            if not usuario or (not usuario.is_superuser and not usuario.groups.filter(name__in=['Master', 'Administrador']).exists()):
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied(f"Ajustes superiores a {umbral_usd} USD requieren aprobación de Master o Administrador.")


        from apps.almacen.services import registrar_entrada, registrar_salida

        referencia = self.numero
        notas = f'Ajuste de inventario {self.numero}: {self.motivo}'

        if self.tipo in self.TIPOS_ENTRADA:
            # Usar el costo promedio vigente como costo de la entrada por ajuste
            costo_usd = Decimal(str(self.producto.costo_promedio))
            registrar_entrada(
                producto=self.producto,
                cantidad=self.cantidad,
                costo_unitario=costo_usd,
                referencia=referencia,
                notas=notas,
            )
        else:
            # SALIDA_AJUSTE / MERMA
            registrar_salida(
                producto=self.producto,
                cantidad=self.cantidad,
                referencia=referencia,
                notas=notas,
            )

        self.estado = 'APROBADO'
        self.save(update_fields=['estado'])
        logger.info(
            'AjusteInventario %s APROBADO. Tipo: %s | Producto: %s | Cantidad: %s.',
            self.numero, self.tipo, self.producto, self.cantidad
        )

    def anular(self):
        """
        Anula el ajuste. Solo es posible desde estado BORRADOR
        (no se ha tocado el inventario todavía).

        Raises:
            EstadoInvalidoError: Si el ajuste no está en estado BORRADOR.
        """
        if self.estado != 'BORRADOR':
            raise EstadoInvalidoError('Ajuste de Inventario', self.estado, 'anular')

        self.estado = 'ANULADO'
        self.save(update_fields=['estado'])
        logger.info('AjusteInventario %s ANULADO.', self.numero)
