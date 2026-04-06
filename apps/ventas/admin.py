# -*- coding: utf-8 -*-
import logging
from datetime import date
from decimal import Decimal

from django.contrib import admin, messages

from apps.ventas.models import (
    Cliente,
    FacturaVenta,
    DetalleFacturaVenta,
    Cobro,
    NotaCredito,
    DetalleNotaCredito,
)
from apps.almacen.models import Producto
from apps.core.exceptions import LacteOpsError

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
    # precio_unitario es editable=False en el modelo; se incluye aquí como readonly
    # para que aparezca en la grilla y el JS pueda auto-llenarlo desde la lista de precios.
    fields = ("producto", "cantidad", "precio_unitario", "subtotal")
    readonly_fields = ("precio_unitario", "subtotal")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "producto":
            kwargs["queryset"] = Producto.objects.filter(activo=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class CobroInline(admin.TabularInline):
    model = Cobro
    extra = 1


class DetalleNotaCreditoInline(admin.TabularInline):
    model = DetalleNotaCredito
    extra = 3
    fields = ("producto", "cantidad", "precio_unitario", "subtotal")
    readonly_fields = ["subtotal"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "producto":
            kwargs["queryset"] = Producto.objects.filter(activo=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


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
        # calcular_subtotal.js  → subtotal en tiempo real (compras y ventas)
        # tasa_auto_pago.js     → tasa BCV en CobroInline
        # precio_auto_venta.js  → precio_unitario desde lista al seleccionar producto
        js = (
            "admin/js/calcular_subtotal.js",
            "admin/js/tasa_auto_pago.js",
            "admin/js/precio_auto_venta.js",
        )
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

    change_form_template = "admin/print_change_form.html"
    print_url_name = "ventas:imprimir_factura_venta"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj and obj.estado in ("EMITIDA", "COBRADA"):
            from apps.almacen.models import MovimientoInventario
            tiene_movimientos = MovimientoInventario.objects.filter(
                referencia=obj.numero, tipo="SALIDA"
            ).exists()
            extra_context["show_print_button"] = tiene_movimientos
        else:
            extra_context["show_print_button"] = False
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

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
        Calcula monto_usd con bimoneda al crear Cobros desde el inline.
        Si el cobro es en VES y no hay tasa BCV disponible, lo omite con error.
        Si hay cuenta_destino, registra el MovimientoCaja correspondiente.
        """
        from apps.bancos.services import (
            calcular_bimoneda,
            normalizar_monto_para_cuenta,
            registrar_movimiento_caja,
        )

        instances = formset.save(commit=False)
        for obj in instances:
            if isinstance(obj, Cobro) and obj._state.adding:
                try:
                    obj.monto_usd, obj.tasa_cambio = calcular_bimoneda(
                        obj.monto, obj.moneda, obj.fecha or date.today()
                    )
                except LacteOpsError as e:
                    messages.error(request, e.message)
                    continue
                obj.save()
                if obj.cuenta_destino:
                    monto_caja, moneda_caja, tasa_caja = normalizar_monto_para_cuenta(
                        obj.monto, obj.moneda, obj.tasa_cambio, obj.cuenta_destino
                    )
                    try:
                        registrar_movimiento_caja(
                            cuenta=obj.cuenta_destino,
                            tipo="ENTRADA",
                            monto=monto_caja,
                            moneda=moneda_caja,
                            tasa_cambio=tasa_caja,
                            referencia=obj.factura.numero,
                        )
                    except LacteOpsError as e:
                        messages.warning(
                            request,
                            f"Cobro guardado, pero movimiento de caja falló: {e.message}",
                        )
                    except Exception as e:
                        logger.error(
                            "Error inesperado en movimiento caja para cobro %s: %s",
                            obj, e, exc_info=True,
                        )
                        messages.warning(
                            request,
                            "Cobro guardado, pero movimiento de caja falló. Ver logs.",
                        )
            else:
                obj.save()
        formset.save_m2m()


@admin.register(NotaCredito)
class NotaCreditoAdmin(admin.ModelAdmin):
    list_display = ["numero", "fecha", "cliente", "factura_origen", "total", "estado"]
    list_filter = ["estado", "fecha", "cliente"]
    search_fields = ["numero", "cliente__nombre", "factura_origen__numero"]
    readonly_fields = ["numero", "total", "estado", "cliente"]
    inlines = [DetalleNotaCreditoInline]
    date_hierarchy = "fecha"
    actions = ["emitir_notas_credito", "anular_notas_credito"]
    change_form_template = "admin/print_change_form.html"
    print_url_name = "ventas:imprimir_nota_credito"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        extra_context["show_print_button"] = bool(obj and obj.estado == "EMITIDA")
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def emitir_notas_credito(self, request, queryset):
        for nc in queryset:
            try:
                nc.emitir()
                messages.success(request, f"Nota de crédito emitida: {nc}")
            except LacteOpsError as e:
                messages.error(request, f"Error en {nc}: {e.message}")
            except Exception as e:
                logger.error("Error inesperado emitiendo NC %s: %s", nc, e, exc_info=True)
                messages.error(request, f"Error inesperado en {nc}. Ver logs.")

    emitir_notas_credito.short_description = "Emitir notas de crédito seleccionadas"

    def anular_notas_credito(self, request, queryset):
        for nc in queryset:
            try:
                nc.anular()
                messages.success(request, f"Nota de crédito anulada: {nc}")
            except LacteOpsError as e:
                messages.error(request, f"Error en {nc}: {e.message}")
            except Exception as e:
                logger.error("Error inesperado anulando NC %s: %s", nc, e, exc_info=True)
                messages.error(request, f"Error inesperado en {nc}. Ver logs.")

    anular_notas_credito.short_description = "Anular notas de crédito seleccionadas"


# --- CobroAdmin: formulario independiente con bimoneda ---
@admin.register(Cobro)
class CobroAdmin(admin.ModelAdmin):
    list_display = ("factura", "fecha", "monto", "moneda", "monto_usd", "medio_pago")

    class Media:
        js = ("admin/js/tasa_auto_pago_standalone.js",)

    def save_model(self, request, obj, form, change):
        """
        Calcula monto_usd con bimoneda al crear Cobros desde el formulario
        independiente de CobroAdmin (punto de entrada distinto al inline).
        Si el cobro es en VES y no hay tasa BCV disponible, lo omite con error.
        Si hay cuenta_destino, registra el MovimientoCaja correspondiente.
        """
        from apps.bancos.services import (
            calcular_bimoneda,
            normalizar_monto_para_cuenta,
            registrar_movimiento_caja,
        )

        es_nuevo = obj._state.adding
        if es_nuevo:
            try:
                obj.monto_usd, obj.tasa_cambio = calcular_bimoneda(
                    obj.monto, obj.moneda, obj.fecha or date.today()
                )
            except LacteOpsError as e:
                messages.error(request, e.message)
                return

        super().save_model(request, obj, form, change)

        if es_nuevo and obj.cuenta_destino:
            monto_caja, moneda_caja, tasa_caja = normalizar_monto_para_cuenta(
                obj.monto, obj.moneda, obj.tasa_cambio, obj.cuenta_destino
            )
            try:
                registrar_movimiento_caja(
                    cuenta=obj.cuenta_destino,
                    tipo="ENTRADA",
                    monto=monto_caja,
                    moneda=moneda_caja,
                    tasa_cambio=tasa_caja,
                    referencia=obj.factura.numero if obj.factura else "",
                )
            except LacteOpsError as e:
                messages.warning(
                    request,
                    f"Cobro guardado, pero movimiento de caja falló: {e.message}",
                )
            except Exception as e:
                logger.error(
                    "Error inesperado en movimiento caja para cobro %s: %s",
                    obj, e, exc_info=True,
                )
                messages.warning(
                    request,
                    "Cobro guardado, pero movimiento de caja falló. Ver logs.",
                )


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


