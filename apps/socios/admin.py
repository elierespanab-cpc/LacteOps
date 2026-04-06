from django.contrib import admin
from django.utils.html import format_html

from .models import Socio, PrestamoPorSocio, PagoPrestamo


@admin.register(Socio)
class SocioAdmin(admin.ModelAdmin):
    list_display = ["nombre", "rif", "get_saldo_bruto", "get_saldo_neto", "activo"]
    list_filter = ["activo"]
    search_fields = ["nombre", "rif"]
    readonly_fields = ["get_saldo_bruto", "get_saldo_neto"]


class PagoPrestamoInline(admin.TabularInline):
    model = PagoPrestamo
    readonly_fields = ["monto_usd"]
    extra = 0

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PrestamoPorSocio)
class PrestamoPorSocioAdmin(admin.ModelAdmin):
    list_display = [
        "numero",
        "socio",
        "monto_usd",
        "monto_pagado_display",
        "saldo_neto_display",
        "estado",
        "fecha_prestamo",
        "fecha_vencimiento",
    ]

    @admin.display(description="Pagado USD")
    def monto_pagado_display(self, obj):
        pagado = obj.get_monto_pagado()
        return format_html('<span style="color:green">{}</span>', f"{pagado:,.2f}")

    @admin.display(description="Saldo USD")
    def saldo_neto_display(self, obj):
        saldo = obj.get_saldo_neto()
        color = "red" if saldo > 0 else "gray"
        return format_html('<span style="color:{}">{}</span>', color, f"{saldo:,.2f}")
    readonly_fields = ["numero", "monto_usd"]
    list_filter = ["estado", "moneda", "cuenta_destino"]
    inlines = [PagoPrestamoInline]
    change_form_template = "admin/print_change_form.html"
    print_url_name = "socios:imprimir_prestamo"

    def save_model(self, request, obj, form, change):
        """Al crear un préstamo desde el Admin, usa el servicio para registrar MovimientoCaja."""
        from apps.socios.services import registrar_prestamo
        from django.contrib import messages

        if not change:
            # Nuevo préstamo: usar servicio que registra MovimientoCaja si hay cuenta_destino
            try:
                registrar_prestamo(
                    socio=obj.socio,
                    monto=obj.monto_principal,
                    moneda=obj.moneda,
                    tasa=obj.tasa_cambio,
                    fecha=obj.fecha_prestamo,
                    cuenta_destino=obj.cuenta_destino,
                    fecha_vencimiento=obj.fecha_vencimiento,
                    notas=obj.notas or '',
                )
            except Exception as e:
                messages.error(request, f"Error registrando préstamo: {e}")
        else:
            super().save_model(request, obj, form, change)
