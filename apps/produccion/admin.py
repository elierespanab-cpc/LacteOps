# -*- coding: utf-8 -*-
import logging

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse

from apps.produccion.models import Receta, RecetaDetalle, OrdenProduccion, ConsumoOP
from apps.core.exceptions import LacteOpsError

logger = logging.getLogger(__name__)


class RecetaDetalleInline(admin.TabularInline):
    model = RecetaDetalle
    extra = 1


@admin.register(Receta)
class RecetaAdmin(admin.ModelAdmin):
    inlines = [RecetaDetalleInline]
    list_display = ("nombre", "rendimiento_esperado", "activo")
    search_fields = ("nombre",)
    list_filter = ("activo",)


class ConsumoOPInline(admin.TabularInline):
    model = ConsumoOP
    extra = 0
    readonly_fields = ("costo_unitario", "subtotal")
    # El operador puede ajustar cantidades antes del cierre
    fields = ("producto", "unidad_medida", "cantidad_consumida", "costo_unitario", "subtotal")
    
    def get_extra(self, request, obj=None, **kwargs):
        if obj is None:
            return 0
        return 0


@admin.register(OrdenProduccion)
class OrdenProduccionAdmin(admin.ModelAdmin):
    inlines = [ConsumoOPInline]
    list_display = ("numero", "receta", "fecha_apertura", "fecha_cierre", "estado", "costo_total")
    readonly_fields = ("fecha_apertura", "fecha_cierre", "costo_total", "estado")
    search_fields = ("numero", "receta__nombre")
    list_filter = ("estado", "fecha_apertura")
    actions = ["cerrar_ordenes", "anular_ordenes"]
    
    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)
    
    def response_add(self, request, obj, post_url_continue=None):
        return HttpResponseRedirect(
            reverse(
                'admin:produccion_ordenproduccion_change',
                args=[obj.pk]
            )
        )

    def cerrar_ordenes(self, request, queryset):
        for obj in queryset:
            try:
                obj.cerrar()
                messages.success(request, f'Exitoso: {obj}')
            except LacteOpsError as e:
                messages.error(request, f'Error en {obj}: {e.message}')
            except Exception as e:
                logger.error('Error inesperado cerrando %s: %s', obj, e, exc_info=True)
                messages.error(request, f'Error inesperado en {obj}. Ver logs.')

    cerrar_ordenes.short_description = 'Cerrar órdenes seleccionadas'

    def anular_ordenes(self, request, queryset):
        for obj in queryset:
            try:
                obj.anular()
                messages.success(request, f'Exitoso: {obj}')
            except LacteOpsError as e:
                messages.error(request, f'Error en {obj}: {e.message}')
            except Exception as e:
                logger.error('Error inesperado anulando %s: %s', obj, e, exc_info=True)
                messages.error(request, f'Error inesperado en {obj}. Ver logs.')

    anular_ordenes.short_description = 'Anular órdenes seleccionadas'





# --- Sprint 2: Salidas de Orden y boton imprimir ---
from apps.produccion.models import SalidaOrden, OrdenProduccion


class SalidaOrdenInline(admin.TabularInline):
    model = SalidaOrden
    extra = 0
    readonly_fields = ("costo_asignado",)


_orden_admin = admin.site._registry.get(OrdenProduccion)
if _orden_admin:
    _inlines = list(getattr(_orden_admin, "inlines", []))
    if SalidaOrdenInline not in _inlines:
        _inlines.append(SalidaOrdenInline)
        _orden_admin.inlines = _inlines
    _orden_admin.change_form_template = "admin/print_change_form.html"
    _orden_admin.print_url_name = "produccion:imprimir_orden_produccion"
