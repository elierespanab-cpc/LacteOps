# -*- coding: utf-8 -*-
import logging
from datetime import date
from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.db import transaction

from apps.compras.models import (
    Proveedor,
    FacturaCompra,
    DetalleFacturaCompra,
    Pago,
    DetallePagoFactura,
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
    fk_name = "factura"


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
                    ref = obj.factura.numero if obj.factura else ""
                    try:
                        registrar_movimiento_caja(
                            cuenta=obj.cuenta_origen,
                            tipo="SALIDA",
                            monto=monto_caja,
                            moneda=moneda_caja,
                            tasa_cambio=tasa_caja,
                            referencia=ref,
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


# ─────────────────────────────────────────────────────────────────────────────
# PagoAdmin — Pago individual y consolidado
# ─────────────────────────────────────────────────────────────────────────────

class PagoConsolidadoForm(forms.ModelForm):
    """
    Formulario para Pago que permite:
    - Pago individual: seleccionar UNA factura en el campo FK 'factura'.
    - Pago consolidado: seleccionar VARIAS facturas con checkboxes.
    """
    facturas_consolidado = forms.ModelMultipleChoiceField(
        queryset=FacturaCompra.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Facturas a pagar (consolidado)",
        help_text="Seleccione las facturas que desea cubrir con este pago. "
                  "Deje vacío si usa el campo Factura individual arriba.",
    )

    class Meta:
        model = Pago
        fields = [
            'factura', 'facturas_consolidado',
            'fecha', 'monto', 'moneda', 'tasa_cambio',
            'cuenta_origen', 'medio_pago', 'referencia', 'notas',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Facturas APROBADAS con saldo pendiente > 0
        facturas_abiertas = []
        for f in FacturaCompra.objects.filter(estado='APROBADA').order_by('-fecha', '-numero'):
            if f.get_saldo_pendiente() > Decimal('0'):
                facturas_abiertas.append(f.pk)
        qs = FacturaCompra.objects.filter(pk__in=facturas_abiertas)
        self.fields['facturas_consolidado'].queryset = qs
        choices = []
        for f in qs:
            saldo = f.get_saldo_pendiente()
            label = (
                f"{f.numero} | {f.proveedor.nombre} | "
                f"Total: {f.total} USD | Saldo: {saldo} USD"
            )
            choices.append((f.pk, label))
        self.fields['facturas_consolidado'].choices = choices

        # Si editamos un pago consolidado existente, marcar sus facturas
        if self.instance and self.instance.pk and self.instance.es_consolidado:
            self.initial['facturas_consolidado'] = list(
                self.instance.detalle_facturas.values_list('factura_id', flat=True)
            )

    def clean(self):
        cleaned = super().clean()
        factura = cleaned.get('factura')
        facturas_cons = cleaned.get('facturas_consolidado')

        if factura and facturas_cons:
            raise forms.ValidationError(
                "Seleccione UNA factura individual O varias facturas consolidadas, no ambas."
            )
        if not factura and not facturas_cons:
            raise forms.ValidationError(
                "Debe seleccionar al menos una factura (individual o consolidada)."
            )
        return cleaned


class DetallePagoFacturaInline(admin.TabularInline):
    model = DetallePagoFactura
    extra = 0
    readonly_fields = ('factura', 'monto_aplicado')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    form = PagoConsolidadoForm
    inlines = [DetallePagoFacturaInline]
    list_display = (
        "id", "get_tipo_pago", "get_facturas_display", "fecha",
        "monto", "moneda", "monto_usd", "medio_pago",
    )
    list_filter = ("moneda", "medio_pago", "fecha")
    search_fields = ("referencia", "factura__numero")
    readonly_fields = ("monto_usd",)

    change_form_template = "admin/print_change_form.html"
    print_url_name = "compras:imprimir_recibo_compra"

    class Media:
        js = ("admin/js/tasa_auto_pago_standalone.js",)
        css = {"all": ("admin/css/pago_consolidado.css",)}

    @admin.display(description="Tipo")
    def get_tipo_pago(self, obj):
        return "Consolidado" if obj.es_consolidado else "Individual"

    @admin.display(description="Facturas")
    def get_facturas_display(self, obj):
        if obj.factura:
            return obj.factura.numero
        nums = list(obj.detalle_facturas.values_list('factura__numero', flat=True))
        return ", ".join(nums) if nums else "-"

    def save_model(self, request, obj, form, change):
        from apps.bancos.services import (
            calcular_bimoneda,
            normalizar_monto_para_cuenta,
            registrar_movimiento_caja,
        )

        facturas_cons = form.cleaned_data.get('facturas_consolidado')
        es_consolidado = bool(facturas_cons)
        es_nuevo = obj._state.adding

        if es_nuevo:
            try:
                obj.monto_usd, obj.tasa_cambio = calcular_bimoneda(
                    obj.monto, obj.moneda, obj.fecha or date.today()
                )
            except LacteOpsError as e:
                messages.error(request, e.message)
                return

        if es_consolidado:
            obj.factura = None

        super().save_model(request, obj, form, change)

        # Crear DetallePagoFactura para pago consolidado
        if es_nuevo and es_consolidado:
            total_saldo = Decimal('0')
            detalles = []
            for factura in facturas_cons:
                saldo = factura.get_saldo_pendiente()
                detalles.append(DetallePagoFactura(
                    pago=obj,
                    factura=factura,
                    monto_aplicado=saldo,
                ))
                total_saldo += saldo

            if obj.monto_usd < total_saldo:
                messages.warning(
                    request,
                    f"El monto USD ({obj.monto_usd}) es menor que el saldo total "
                    f"de las facturas ({total_saldo}). Se aplicará proporcionalmente.",
                )
                for det in detalles:
                    proporcion = det.monto_aplicado / total_saldo
                    det.monto_aplicado = (obj.monto_usd * proporcion).quantize(Decimal('0.01'))

            with transaction.atomic():
                DetallePagoFactura.objects.bulk_create(detalles)

        # Registrar movimiento de caja
        if es_nuevo and obj.cuenta_origen:
            monto_caja, moneda_caja, tasa_caja = normalizar_monto_para_cuenta(
                obj.monto, obj.moneda, obj.tasa_cambio, obj.cuenta_origen
            )
            ref = obj._referencia_pago()
            try:
                registrar_movimiento_caja(
                    cuenta=obj.cuenta_origen,
                    tipo="SALIDA",
                    monto=monto_caja,
                    moneda=moneda_caja,
                    tasa_cambio=tasa_caja,
                    referencia=ref,
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

        if es_consolidado and es_nuevo:
            nums = ", ".join(f.numero for f in facturas_cons)
            messages.success(
                request,
                f"Pago consolidado registrado para {len(facturas_cons)} facturas: {nums}",
            )


# --- Print button config ---
_gasto_admin = admin.site._registry.get(GastoServicio)
if _gasto_admin:
    _gasto_admin.change_form_template = "admin/print_change_form.html"
    _gasto_admin.print_url_name = "compras:imprimir_gasto_servicio"
