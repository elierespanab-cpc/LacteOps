from django.contrib import admin
from apps.almacen.models import Categoria, UnidadMedida, Producto, MovimientoInventario


@admin.register(UnidadMedida)
class UnidadMedidaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "simbolo", "activo")
    search_fields = ("nombre", "simbolo")


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo")
    search_fields = ("nombre",)
    list_filter = ("activo",)


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = (
        "codigo",
        "nombre",
        "unidad_medida_simbolo",
        "stock_actual",
        "costo_promedio",
        "es_materia_prima",
        "es_producto_terminado",
        "activo",
    )
    readonly_fields = ("stock_actual", "costo_promedio")
    search_fields = ("codigo", "nombre")
    list_filter = ("activo", "es_materia_prima", "es_producto_terminado", "categoria")

    @admin.display(description="Unidad")
    def unidad_medida_simbolo(self, obj):
        return obj.unidad_medida.simbolo


@admin.register(MovimientoInventario)
class MovimientoInventarioAdmin(admin.ModelAdmin):
    list_display = ("fecha", "producto", "tipo", "cantidad", "costo_unitario", "referencia")
    readonly_fields = ("producto", "tipo", "cantidad", "costo_unitario", "referencia", "fecha", "notas")
    list_filter = ("tipo", "fecha")
    search_fields = ("producto__codigo", "producto__nombre", "referencia")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True

# --- Sprint 1: Ajustes de Inventario ---
import logging
from django.contrib import messages
from apps.almacen.models import AjusteInventario
from apps.core.exceptions import LacteOpsError

logger = logging.getLogger(__name__)


@admin.register(AjusteInventario)
class AjusteInventarioAdmin(admin.ModelAdmin):
    list_display = ("numero", "producto", "tipo", "cantidad", "estado")
    readonly_fields = ("numero", "estado")
    actions = ["aprobar_ajustes", "anular_ajustes"]

    def aprobar_ajustes(self, request, queryset):
        for obj in queryset:
            try:
                obj.aprobar()
                messages.success(request, f'Exitoso: {obj}')
            except LacteOpsError as e:
                messages.error(request, f'Error en {obj}: {e.message}')
            except Exception as e:
                logger.error('Error inesperado aprobando %s: %s', obj, e, exc_info=True)
                messages.error(request, f'Error inesperado en {obj}. Ver logs.')

    aprobar_ajustes.short_description = 'Aprobar ajustes seleccionados'

    def anular_ajustes(self, request, queryset):
        for obj in queryset:
            try:
                obj.anular()
                messages.success(request, f'Exitoso: {obj}')
            except LacteOpsError as e:
                messages.error(request, f'Error en {obj}: {e.message}')
            except Exception as e:
                logger.error('Error inesperado anulando %s: %s', obj, e, exc_info=True)
                messages.error(request, f'Error inesperado en {obj}. Ver logs.')

    anular_ajustes.short_description = 'Anular ajustes seleccionados'

# --- Sprint 2: Botones de impresion ---
from apps.almacen.models import MovimientoInventario, AjusteInventario


_mov_admin = admin.site._registry.get(MovimientoInventario)
if _mov_admin:
    _mov_admin.change_form_template = "admin/print_change_form.html"
    _mov_admin.print_url_name = "almacen:imprimir_movimiento_inventario"

_ajuste_admin = admin.site._registry.get(AjusteInventario)
if _ajuste_admin:
    _ajuste_admin.change_form_template = "admin/print_change_form.html"
    _ajuste_admin.print_url_name = "almacen:imprimir_ajuste_inventario"
