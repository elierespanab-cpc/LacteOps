# -*- coding: utf-8 -*-
import logging
from datetime import date

from django.contrib import admin, messages

from apps.compras.models import (
    Proveedor,
    FacturaCompra,
    DetalleFacturaCompra,
    Pago,
    GastoServicio,
)
from apps.almacen.models import Producto
from apps.core.exceptions import LacteOpsError

logger = logging.getLogger(__name__)


@admin.register(Proveedor)
class ProveedorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rif", "telefono", "email", "activo")
    search_fields = ("nombre", "rif")
    list_filter = ("activo",)


class DetalleFacturaCompraInline(admin.TabularInline):
    model = DetalleFacturaCompra
    extra = 3
    readonly_fields = ("subtotal",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "producto":
            kwargs["queryset"] = Producto.objects.filter(activo=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 1


@admin.register(FacturaCompra)
class FacturaCompraAdmin(admin.ModelAdmin):
    inlines = [DetalleFacturaCompraInline, PagoInline]
    list_display = (
        "numero",
        "proveedor",
        "fecha",
        "estado",
        "moneda",
        "total",
        "get_saldo_pendiente",
    )
    readonly_fields = ("total", "estado")
    search_fields = ("numero", "proveedor__nombre", "proveedor__rif")
    list_filter = ("estado", "moneda", "fecha")
    actions = ["aprobar_facturas", "anular_facturas"]

    class Media:
        js = ("admin/js/calcular_subtotal.js", "admin/js/tasa_auto_pago.js")

    @admin.display(description="Saldo Pendiente")
    def get_saldo_pendiente(self, obj):
        return obj.get_saldo_pendiente()

    def aprobar_facturas(self, request, queryset):
        for obj in queryset:
            try:
                obj.aprobar()
                messages.success(request, f"Exitoso: {obj}")
            except LacteOpsError as e:
                messages.error(request, f"Error en {obj}: {e.message}")
            except Exception as e:
                logger.error("Error inesperado aprobando %s: %s", obj, e, exc_info=True)
                messages.error(request, f"Error inesperado en {obj}. Ver logs.")

    aprobar_facturas.short_description = "Aprobar facturas seleccionadas"

    def anular_facturas(self, request, queryset):
        for obj in queryset:
            try:
                obj.anular()
                messages.success(request, f"Exitoso: {obj}")
            except LacteOpsError as e:
                messages.error(request, f"Error en {obj}: {e.message}")
            except Exception as e:
                logger.error("Error inesperado anulando %s: %s", obj, e, exc_info=True)
                messages.error(request, f"Error inesperado en {obj}. Ver logs.")

    anular_facturas.short_description = "Anular facturas seleccionadas"

    def save_formset(self, request, form, formset, change):
        """
        Calcula monto_usd con bimoneda al crear Pagos desde el inline.
        Si el pago es en VES y no hay tasa BCV disponible, lo omite con error.
        Si hay cuenta_origen, registra el MovimientoCaja correspondiente.
        """
        from apps.bancos.services import (
            calcular_bimoneda,
            normalizar_monto_para_cuenta,
            registrar_movimiento_caja,
        )

        instances = formset.save(commit=False)
        for obj in instances:
            if isinstance(obj, Pago) and obj._state.adding:
                try:
                    obj.monto_usd, obj.tasa_cambio = calcular_bimoneda(
                        obj.monto, obj.moneda, obj.fecha or date.today()
                    )
                except LacteOpsError as e:
                    messages.error(request, e.message)
                    continue
                obj.save()
                if obj.cuenta_origen:
                    monto_caja, moneda_caja, tasa_caja = normalizar_monto_para_cuenta(
                        obj.monto, obj.moneda, obj.tasa_cambio, obj.cuenta_origen
                    )
                    try:
                        registrar_movimiento_caja(
                            cuenta=obj.cuenta_origen,
                            tipo="SALIDA",
                            monto=monto_caja,
                            moneda=moneda_caja,
                            tasa_cambio=tasa_caja,
                            referencia=obj.factura.numero,
                        )
                    except LacteOpsError as e:
                        messages.warning(
                            request,
                            f"Pago guardado, pero movimiento de caja falló: {e.message}",
                        )
                    except Exception as e:
                        logger.error(
                            "Error inesperado en movimiento caja para pago %s: %s",
                            obj, e, exc_info=True,
                        )
                        messages.warning(
                            request,
                            "Pago guardado, pero movimiento de caja falló. Ver logs.",
                        )
            else:
                obj.save()
        formset.save_m2m()


@admin.register(GastoServicio)
class GastoServicioAdmin(admin.ModelAdmin):
    list_display = (
        "numero",
        "proveedor",
        "categoria_gasto",
        "monto",
        "moneda",
        "estado",
    )
    search_fields = ("numero", "proveedor__nombre", "descripcion")
    list_filter = ("estado", "moneda", "categoria_gasto")
    actions = ["pagar_gastos"]

    def pagar_gastos(self, request, queryset):
        for obj in queryset:
            if not obj.cuenta_pago:
                messages.error(request, f"{obj}: asigne cuenta_pago antes de pagar.")
                continue
            try:
                obj.pagar(obj.cuenta_pago, obj.monto, obj.moneda, obj.tasa_cambio)
                messages.success(request, f"{obj} pagado.")
            except LacteOpsError as e:
                messages.error(request, e.message)
            except Exception as e:
                logger.error("Error inesperado pagando %s: %s", obj, e, exc_info=True)
                messages.error(request, f"Error inesperado en {obj}. Ver logs.")

    pagar_gastos.short_description = "Pagar gastos/servicios seleccionados"


# --- Sprint 2: Admin Pago + botones de impresion ---
from apps.compras.models import Pago, GastoServicio


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ("factura", "fecha", "monto", "moneda", "monto_usd", "medio_pago")

    class Media:
        js = ("admin/js/tasa_auto_pago_standalone.js",)

    def save_model(self, request, obj, form, change):
        """
        Calcula monto_usd con bimoneda al crear Pagos desde el formulario
        independiente de PagoAdmin (punto de entrada distinto al inline).
        Si el pago es en VES y no hay tasa BCV disponible, lo omite con error.
        Si hay cuenta_origen, registra el MovimientoCaja correspondiente.
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

        if es_nuevo and obj.cuenta_origen:
            monto_caja, moneda_caja, tasa_caja = normalizar_monto_para_cuenta(
                obj.monto, obj.moneda, obj.tasa_cambio, obj.cuenta_origen
            )
            try:
                registrar_movimiento_caja(
                    cuenta=obj.cuenta_origen,
                    tipo="SALIDA",
                    monto=monto_caja,
                    moneda=moneda_caja,
                    tasa_cambio=tasa_caja,
                    referencia=obj.factura.numero if obj.factura else "",
                )
            except LacteOpsError as e:
                messages.warning(
                    request,
                    f"Pago guardado, pero movimiento de caja falló: {e.message}",
                )
            except Exception as e:
                logger.error(
                    "Error inesperado en movimiento caja para pago %s: %s",
                    obj, e, exc_info=True,
                )
                messages.warning(
                    request,
                    "Pago guardado, pero movimiento de caja falló. Ver logs.",
                )


_gasto_admin = admin.site._registry.get(GastoServicio)
if _gasto_admin:
    _gasto_admin.change_form_template = "admin/print_change_form.html"
    _gasto_admin.print_url_name = "compras:imprimir_gasto_servicio"

_pago_admin = admin.site._registry.get(Pago)
if _pago_admin:
    _pago_admin.change_form_template = "admin/print_change_form.html"
    _pago_admin.print_url_name = "compras:imprimir_recibo_compra"
