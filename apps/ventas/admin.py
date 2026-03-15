# -*- coding: utf-8 -*-
import logging
from datetime import date
from decimal import Decimal

from django.contrib import admin, messages

from apps.ventas.models import Cliente, FacturaVenta, DetalleFacturaVenta, Cobro
from apps.almacen.models import Producto
from apps.core.exceptions import LacteOpsError
from apps.core.services import get_tasa_para_fecha

logger = logging.getLogger(__name__)


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "rif",
        "telefono",
        "limite_credito",
        "get_saldo_total_pendiente",
        "activo",
    )
    search_fields = ("nombre", "rif")
    list_filter = ("activo",)

    @admin.display(description="Saldo Pendiente")
    def get_saldo_total_pendiente(self, obj):
        return obj.get_saldo_total_pendiente()


class DetalleFacturaVentaInline(admin.TabularInline):
    model = DetalleFacturaVenta
    extra = 3
    readonly_fields = ("subtotal",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "producto":
            kwargs["queryset"] = Producto.objects.filter(activo=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class CobroInline(admin.TabularInline):
    model = Cobro
    extra = 1


@admin.register(FacturaVenta)
class FacturaVentaAdmin(admin.ModelAdmin):
    inlines = [DetalleFacturaVentaInline, CobroInline]
    list_display = (
        "numero",
        "cliente",
        "fecha",
        "estado",
        "moneda",
        "total",
        "get_saldo_pendiente",
    )
    readonly_fields = ("total", "estado", "alerta_credito", "tasa_cambio")
    search_fields = ("numero", "cliente__nombre", "cliente__rif")
    list_filter = ("estado", "moneda", "fecha")
    actions = ["emitir_facturas", "marcar_cobradas"]

    class Media:
        js = ("admin/js/calcular_subtotal.js",)
        css = {"all": ("admin/css/ocultar_campo.css",)}

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        ro.append("moneda")
        from apps.core.models import ConfiguracionEmpresa

        config = ConfiguracionEmpresa.objects.first()
        if config and not config.fecha_venta_abierta:
            ro.append("fecha")
        return ro

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "moneda" in form.base_fields:
            form.base_fields["moneda"].initial = "USD"
        return form

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_save_and_add_another"] = False
        return super().changeform_view(request, object_id, form_url, extra_context)

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
                messages.success(request, f"Exitoso: {obj}")
            except LacteOpsError as e:
                messages.error(request, f"Error en {obj}: {e.message}")
            except Exception as e:
                logger.error("Error inesperado emitiendo %s: %s", obj, e, exc_info=True)
                messages.error(request, f"Error inesperado en {obj}. Ver logs.")

    emitir_facturas.short_description = (
        "Emitir facturas seleccionadas (descontar inventario)"
    )

    def marcar_cobradas(self, request, queryset):
        for obj in queryset:
            try:
                obj.marcar_cobrada()
                messages.success(request, f"Exitoso: {obj}")
            except LacteOpsError as e:
                messages.error(request, f"Error en {obj}: {e.message}")
            except Exception as e:
                logger.error(
                    "Error inesperado marcando cobrada %s: %s", obj, e, exc_info=True
                )
                messages.error(request, f"Error inesperado en {obj}. Ver logs.")

    marcar_cobradas.short_description = "Marcar facturas como cobradas"

    def save_formset(self, request, form, formset, change):
        """
        FIX C2: Calcula monto_usd con bimoneda al crear Cobros desde el inline.
        Si el cobro es en VES y no hay tasa BCV disponible, lo omite con error.
        Si hay cuenta_destino, registra el MovimientoCaja correspondiente.
        """
        instances = formset.save(commit=False)
        for obj in instances:
            if isinstance(obj, Cobro) and obj._state.adding:
                tasa = get_tasa_para_fecha(obj.fecha or date.today())
                if obj.moneda == "VES" and not tasa:
                    messages.error(
                        request,
                        f"Sin tasa BCV para {obj.fecha}. Cobro no guardado.",
                    )
                    continue
                tasa_val = tasa.tasa if tasa else Decimal("1.000000")
                if obj.moneda == "VES":
                    obj.monto_usd = (obj.monto / tasa_val).quantize(Decimal("0.01"))
                    obj.tasa_cambio = tasa_val
                else:
                    obj.monto_usd = obj.monto
                    obj.tasa_cambio = Decimal("1.000000")
                obj.save()
                if obj.cuenta_destino:
                    from apps.bancos.services import registrar_movimiento_caja

                    registrar_movimiento_caja(
                        cuenta=obj.cuenta_destino,
                        tipo="ENTRADA",
                        monto=obj.monto,
                        moneda=obj.moneda,
                        tasa_cambio=obj.tasa_cambio,
                        referencia=obj.factura.numero,
                    )
            else:
                obj.save()
        formset.save_m2m()


# --- Sprint 2: Listas de precios y boton imprimir ---
from django.core.exceptions import PermissionDenied
from apps.ventas.models import ListaPrecio, DetalleLista, FacturaVenta
from apps.ventas.services import aprobar_precio


class DetalleListaInline(admin.TabularInline):
    model = DetalleLista
    extra = 1

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "producto":
            kwargs["queryset"] = Producto.objects.filter(activo=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class DetallePorProductoInline(admin.TabularInline):
    model = DetalleLista
    fields = ("lista", "precio", "aprobado", "vigente_desde")
    readonly_fields = ("aprobado",)
    extra = 0
    verbose_name = "Precio en Tarifa"

    def has_delete_permission(self, request, obj=None):
        return False


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
                    logger.error(
                        "Error aprobando precio %s: %s", detalle, e, exc_info=True
                    )
                    messages.error(request, f"Error aprobando {detalle}. Ver logs.")

    aprobar_precios.short_description = "Aprobar precios de listas seleccionadas"


_factura_admin = admin.site._registry.get(FacturaVenta)
if _factura_admin:
    _factura_admin.change_form_template = "admin/print_change_form.html"
    _factura_admin.print_url_name = "ventas:imprimir_factura_venta"
