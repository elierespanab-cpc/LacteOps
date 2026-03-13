from django.contrib import admin
from django.core.management import call_command
from io import StringIO

from apps.core.models import AuditLog, ConfiguracionEmpresa, TasaCambio, CategoriaGasto


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("fecha_hora", "usuario", "modulo", "accion", "entidad", "entidad_id")
    list_filter = ("accion", "modulo", "fecha_hora")
    search_fields = ("usuario__username", "entidad")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True

# --- Sprint 2: Configuracion de Empresa (singleton) ---
@admin.register(ConfiguracionEmpresa)
class ConfiguracionEmpresaAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not ConfiguracionEmpresa.objects.exists()


@admin.register(TasaCambio)
class TasaCambioAdmin(admin.ModelAdmin):
    list_display = ("fecha", "tasa", "fuente", "creado_en")
    list_filter = ("fuente",)
    ordering = ("-fecha",)
    actions = ["actualizar_tasa_hoy"]

    def actualizar_tasa_hoy(self, request, queryset):
        out = StringIO()
        call_command("actualizar_tasa_bcv", stdout=out)
        self.message_user(request, out.getvalue())


@admin.register(CategoriaGasto)
class CategoriaGastoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "padre", "contexto", "activa")
    list_filter = ("contexto", "activa")
    search_fields = ("nombre",)
