# -*- coding: utf-8 -*-
import logging
from decimal import Decimal

from django.contrib import admin, messages

from apps.ventas.models import Cliente, FacturaVenta, DetalleFacturaVenta, Cobro
from apps.core.exceptions import LacteOpsError

logger = logging.getLogger(__name__)


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rif", "telefono", "limite_credito", "get_saldo_total_pendiente", "activo")
    search_fields = ("nombre", "rif")
    list_filter = ("activo",)

    @admin.display(description="Saldo Pendiente")
    def get_saldo_total_pendiente(self, obj):
        return obj.get_saldo_total_pendiente()


class DetalleFacturaVentaInline(admin.TabularInline):
    model = DetalleFacturaVenta
    extra = 3
    readonly_fields = ("subtotal",)


class CobroInline(admin.TabularInline):
    model = Cobro
    extra = 1


@admin.register(FacturaVenta)
class FacturaVentaAdmin(admin.ModelAdmin):
    inlines = [DetalleFacturaVentaInline, CobroInline]
    list_display = ("numero", "cliente", "fecha", "estado", "moneda", "total", "get_saldo_pendiente")
    readonly_fields = ("total", "estado", "alerta_credito")
    search_fields = ("numero", "cliente__nombre", "cliente__rif")
    list_filter = ("estado", "moneda", "fecha")
    actions = ["emitir_facturas", "marcar_cobradas"]

    class Media:
        js = ("admin/js/calcular_subtotal.js",)

    @admin.display(description="Saldo Pendiente")
    def get_saldo_pendiente(self, obj):
        return obj.get_saldo_pendiente()

    @admin.display(description="Alerta Crédito")
    def alerta_credito(self, obj):
        cliente = obj.cliente
        if not cliente:
            return ""
        limite = cliente.limite_credito or Decimal("0.00")
        if limite <= 0:
            return "Cliente sin límite de crédito definido."
        saldo = cliente.get_saldo_total_pendiente()
        if saldo >= limite * Decimal("0.80"):
            return "⚠️ ADVERTENCIA: saldo pendiente supera 80% del límite de crédito."
        return ""

    def emitir_facturas(self, request, queryset):
        for obj in queryset:
            try:
                obj.emitir()
                messages.success(request, f'Exitoso: {obj}')
            except LacteOpsError as e:
                messages.error(request, f'Error en {obj}: {e.message}')
            except Exception as e:
                logger.error('Error inesperado emitiendo %s: %s', obj, e, exc_info=True)
                messages.error(request, f'Error inesperado en {obj}. Ver logs.')

    emitir_facturas.short_description = 'Emitir facturas seleccionadas (descontar inventario)'

    def marcar_cobradas(self, request, queryset):
        for obj in queryset:
            try:
                obj.marcar_cobrada()
                messages.success(request, f'Exitoso: {obj}')
            except LacteOpsError as e:
                messages.error(request, f'Error en {obj}: {e.message}')
            except Exception as e:
                logger.error('Error inesperado marcando cobrada %s: %s', obj, e, exc_info=True)
                messages.error(request, f'Error inesperado en {obj}. Ver logs.')

    marcar_cobradas.short_description = 'Marcar facturas como cobradas'

# --- Sprint 2: Listas de precios y boton imprimir ---
from django.core.exceptions import PermissionDenied
from apps.ventas.models import ListaPrecio, DetalleLista, FacturaVenta
from apps.ventas.services import aprobar_precio


class DetalleListaInline(admin.TabularInline):
    model = DetalleLista
    extra = 1


@admin.register(ListaPrecio)
class ListaPrecioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activa", "requiere_aprobacion")
    inlines = [DetalleListaInline]
    actions = ["aprobar_precios"]

    def aprobar_precios(self, request, queryset):
        for lista in queryset:
            for detalle in lista.detalles.select_related("producto").all():
                try:
                    aprobar_precio(detalle, request.user)
                    messages.success(request, f"Precio aprobado: {detalle}")
                except PermissionDenied as e:
                    messages.error(request, str(e))
                except Exception as e:
                    logger.error("Error aprobando precio %s: %s", detalle, e, exc_info=True)
                    messages.error(request, f"Error aprobando {detalle}. Ver logs.")

    aprobar_precios.short_description = "Aprobar precios de listas seleccionadas"


_factura_admin = admin.site._registry.get(FacturaVenta)
if _factura_admin:
    _factura_admin.change_form_template = "admin/print_change_form.html"
    _factura_admin.print_url_name = "ventas:imprimir_factura_venta"
