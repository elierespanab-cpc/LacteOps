from django.contrib import admin

from .models import Socio, PrestamoPorSocio, PagoPrestamo


@admin.register(Socio)
class SocioAdmin(admin.ModelAdmin):
    list_display = ["nombre", "rif", "activo"]
    list_filter = ["activo"]
    search_fields = ["nombre", "rif"]


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
        "monto_principal",
        "moneda",
        "estado",
        "fecha_prestamo",
        "fecha_vencimiento",
    ]
    readonly_fields = ["numero", "monto_usd"]
    list_filter = ["estado", "moneda"]
    inlines = [PagoPrestamoInline]
    change_form_template = "admin/print_change_form.html"
    print_url_name = "socios:imprimir_prestamo"
