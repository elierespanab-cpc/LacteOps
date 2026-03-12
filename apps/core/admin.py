from django.contrib import admin
from apps.core.models import AuditLog


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
from apps.core.models import ConfiguracionEmpresa


@admin.register(ConfiguracionEmpresa)
class ConfiguracionEmpresaAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not ConfiguracionEmpresa.objects.exists()
