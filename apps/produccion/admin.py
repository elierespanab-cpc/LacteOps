# -*- coding: utf-8 -*-
import logging

from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse

from apps.produccion.models import (
    Receta, RecetaDetalle, OrdenProduccion, ConsumoOP, SalidaOrden
)
from apps.almacen.models import Producto
from apps.core.exceptions import LacteOpsError

logger = logging.getLogger(__name__)


class RecetaDetalleInline(admin.TabularInline):
    model = RecetaDetalle
    extra = 1

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "materia_prima":
            kwargs["queryset"] = Producto.objects.filter(activo=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Receta)
class RecetaAdmin(admin.ModelAdmin):
    inlines = [RecetaDetalleInline]
    list_display = ("nombre", "rendimiento_esperado", "activo")
    search_fields = ("nombre",)
    list_filter = ("activo",)


class ConsumoOPInline(admin.TabularInline):
    model = ConsumoOP
    extra = 0
    # unidad_medida se auto-asigna desde el producto en ConsumoOP.save();
    # se muestra como readonly para evitar que el usuario ingrese una unidad incorrecta.
    readonly_fields = ("unidad_medida_display", "costo_unitario", "subtotal")
    fields = ("producto", "cantidad_consumida", "unidad_medida_display", "costo_unitario", "subtotal")

    def unidad_medida_display(self, obj):
        if obj.pk and obj.unidad_medida_id:
            return f"{obj.unidad_medida.simbolo} — {obj.unidad_medida.nombre}"
        if obj.producto_id:
            try:
                return obj.producto.unidad_medida.simbolo
            except Exception:
                pass
        return "—"
    unidad_medida_display.short_description = "Unidad de Medida"

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "producto":
            kwargs["queryset"] = Producto.objects.filter(activo=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_extra(self, request, obj=None, **kwargs):
        return 0


class SalidaOrdenInline(admin.TabularInline):
    model = SalidaOrden
    extra = 0
    readonly_fields = ("costo_asignado",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "producto":
            kwargs["queryset"] = Producto.objects.filter(activo=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(OrdenProduccion)
class OrdenProduccionAdmin(admin.ModelAdmin):
    inlines = [ConsumoOPInline, SalidaOrdenInline]
    list_display = ("numero", "receta", "fecha_apertura", "fecha_cierre", "estado", "costo_total")
    readonly_fields = ("fecha_cierre", "costo_total", "estado", "kg_totales_salida", "rendimiento_real")
    fieldsets = (
        (None, {"fields": ("numero", "receta", "estado", "notas")}),
        ("Fechas", {"fields": ("fecha_apertura", "fecha_cierre")}),
        ("Costos", {"fields": ("costo_total", "kg_totales_salida", "rendimiento_real")}),
    )
    search_fields = ("numero", "receta__nombre")
    list_filter = ("estado", "fecha_apertura")
    actions = ["cerrar_ordenes", "anular_ordenes", "reabrir_ordenes"]

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if obj and obj.estado == 'CERRADA':
            if 'fecha_apertura' not in ro:
                ro.append('fecha_apertura')
        return tuple(ro)
    
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

    @admin.action(description='Reabrir órdenes cerradas (Master/Admin)')
    def reabrir_ordenes(self, request, queryset):
        from apps.core.rbac import usuario_en_grupo
        if not (request.user.is_superuser or
                usuario_en_grupo(request.user, 'Master', 'Administrador')):
            self.message_user(
                request,
                'Sin permiso. Solo Master o Administrador pueden reabrir.',
                level=messages.ERROR
            )
            return
        exito = 0
        for obj in queryset:
            try:
                obj.reabrir(request.user, 'Reapertura desde Admin')
                exito += 1
            except Exception as e:
                self.message_user(
                    request,
                    f'Error en {obj.numero}: {e}',
                    level=messages.ERROR
                )
        if exito:
            self.message_user(
                request,
                f'{exito} orden(es) reabierta(s) exitosamente.'
            )





# --- Sprint 2: Configuración de plantilla y URL de impresión ---
_orden_admin = admin.site._registry.get(OrdenProduccion)
if _orden_admin:
    _orden_admin.change_form_template = "admin/print_change_form.html"
    _orden_admin.print_url_name = "produccion:imprimir_orden_produccion"
