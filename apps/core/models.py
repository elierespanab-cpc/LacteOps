# -*- coding: utf-8 -*-
import json
from datetime import date, datetime
from decimal import Decimal
from django.db import models
from django.conf import settings

class AuditLog(models.Model):
    ACCION_CHOICES = [
        ('CREAR', 'Crear'),
        ('MODIFICAR', 'Modificar'),
        ('ELIMINAR', 'Eliminar'),
        ('CAMBIO_ESTADO', 'Cambio de Estado'),
    ]

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Usuario"
    )
    fecha_hora = models.DateTimeField(auto_now_add=True, verbose_name="Fecha y Hora")
    ip_origen = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP Origen")
    modulo = models.CharField(max_length=50, verbose_name="Módulo")
    accion = models.CharField(max_length=20, choices=ACCION_CHOICES, verbose_name="Acción")
    entidad = models.CharField(max_length=100, verbose_name="Entidad")
    entidad_id = models.PositiveIntegerField(verbose_name="ID de Entidad")
    before_data = models.JSONField(null=True, blank=True, verbose_name="Datos Anteriores")
    after_data = models.JSONField(null=True, blank=True, verbose_name="Datos Nuevos")

    class Meta:
        verbose_name = "Registro de Auditoría"
        verbose_name_plural = "Registros de Auditoría"
        ordering = ['-fecha_hora']

    def __str__(self):
        return f"{self.fecha_hora.strftime('%Y-%m-%d %H:%M:%S')} - {self.accion} - {self.entidad} ({self.entidad_id})"

    def save(self, *args, **kwargs):
        if self.pk:
            raise NotImplementedError("Los registros de auditoría no pueden ser modificados.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Los registros de auditoría no pueden ser eliminados.")


def get_model_data_dict(instance):
    """Helper para obtener un diccionario serializable del estado de la instancia."""
    opts = instance._meta
    data = {}
    for f in opts.concrete_fields:
        val = f.value_from_object(instance)
        if isinstance(val, Decimal):
            data[f.name] = str(val)
        elif isinstance(val, (datetime, date)):
            data[f.name] = val.isoformat()
        else:
            data[f.name] = val
    return data


class AuditableModel(models.Model):
    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._request = None
        if self.pk:
            self._original_state = get_model_data_dict(self)
        else:
            self._original_state = None

    def save(self, *args, **kwargs):
        is_new = not self.pk
        accion = 'CREAR' if is_new else 'MODIFICAR'
        
        # Guardar primero para tener PK si es una inserción nueva
        super().save(*args, **kwargs)
        
        after_data = get_model_data_dict(self)
        
        # Si es una modificación y los datos no han cambiado en sus valores en BDD, lo ignoramos
        if not is_new and self._original_state == after_data:
            return

        ip = getattr(self._request, 'META', {}).get('REMOTE_ADDR') if self._request else None
        usuario = getattr(self._request, 'user', None) if self._request else None
        if usuario and not usuario.is_authenticated:
            usuario = None

        AuditLog.objects.create(
            usuario=usuario,
            ip_origen=ip,
            modulo=self._meta.app_label,
            accion=accion,
            entidad=self._meta.object_name,
            entidad_id=self.pk,
            before_data=self._original_state if not is_new else None,
            after_data=after_data,
        )
        
        self._original_state = after_data

    def delete(self, *args, **kwargs):
        before_data = get_model_data_dict(self)
        
        ip = getattr(self._request, 'META', {}).get('REMOTE_ADDR') if self._request else None
        usuario = getattr(self._request, 'user', None) if self._request else None
        if usuario and not usuario.is_authenticated:
            usuario = None

        AuditLog.objects.create(
            usuario=usuario,
            ip_origen=ip,
            modulo=self._meta.app_label,
            accion='ELIMINAR',
            entidad=self._meta.object_name,
            entidad_id=self.pk,
            before_data=before_data,
            after_data=None,
        )
        super().delete(*args, **kwargs)


class Secuencia(models.Model):
    tipo_documento = models.CharField(max_length=6, unique=True, verbose_name="Tipo de Documento")
    ultimo_numero = models.PositiveIntegerField(default=0, verbose_name="Último Número")
    prefijo = models.CharField(max_length=10, verbose_name="Prefijo")
    digitos = models.PositiveSmallIntegerField(default=4, verbose_name="Dígitos")

    class Meta:
        verbose_name = "Secuencia"
        verbose_name_plural = "Secuencias"

    def __str__(self):
        return f"Secuencia {self.tipo_documento} ({self.prefijo})"


class ConfiguracionEmpresa(models.Model):
    nombre_empresa = models.CharField(max_length=200, verbose_name="Nombre de la Empresa")
    rif = models.CharField(max_length=20, verbose_name="RIF / Identificación")
    direccion = models.TextField(verbose_name="Dirección")
    telefono = models.CharField(max_length=50, verbose_name="Teléfono")
    email = models.EmailField(null=True, blank=True, verbose_name="Email")
    pie_documento = models.TextField(blank=True, verbose_name="Pie de Documento")

    class Meta:
        verbose_name = "Configuración de Empresa"
        verbose_name_plural = "Configuraciones de Empresa"

    def __str__(self):
        return self.nombre_empresa

    def save(self, *args, **kwargs):
        if not self.pk and ConfiguracionEmpresa.objects.exists():
            raise ValueError("Solo puede existir un registro de Configuración de Empresa.")
        self.pk = 1
        super().save(*args, **kwargs)


class TasaCambio(models.Model):
    FUENTES = [('BCV_AUTO', 'BCV Auto'), ('BCV_MANUAL', 'BCV Manual'), ('USUARIO', 'Usuario')]
    fecha = models.DateField(unique=True)
    tasa = models.DecimalField(max_digits=18, decimal_places=6)
    fuente = models.CharField(max_length=20, choices=FUENTES, default='BCV_AUTO')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'Tasa de Cambio'
        verbose_name_plural = 'Tasas de Cambio'

    def __str__(self):
        return f'{self.fecha} — {self.tasa}'


class CategoriaGasto(AuditableModel):
    CONTEXTOS = [('FACTURA', 'Factura'), ('TESORERIA', 'Tesorería')]
    nombre = models.CharField(max_length=100)
    padre = models.ForeignKey('self', null=True, blank=True,
                               on_delete=models.PROTECT, related_name='subcategorias')
    contexto = models.CharField(max_length=10, choices=CONTEXTOS)
    activa = models.BooleanField(default=True)

    class Meta:
        unique_together = ['nombre', 'contexto']
        verbose_name = 'Categoría de Gasto'
        verbose_name_plural = 'Categorías de Gasto'

    def __str__(self):
        return self.nombre
