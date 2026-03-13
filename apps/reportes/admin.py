from django.contrib import admin
from .models import ReporteLink

@admin.register(ReporteLink)
class ReporteLinkAdmin(admin.ModelAdmin):
    """
    Registro del modelo dummy para activar la visibilidad de la app 'reportes' en Jazzmin.
    Solo visible para usuarios con el permiso 'reportes.view_reportelink'
    (asignado a grupos Master y Administrador vía setup_groups).
    """
    def has_module_perms(self, request):
        return (
            request.user.is_superuser
            or request.user.has_perm('reportes.view_reportelink')
        )

    def has_view_permission(self, request, obj=None):
        return (
            request.user.is_superuser
            or request.user.has_perm('reportes.view_reportelink')
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
