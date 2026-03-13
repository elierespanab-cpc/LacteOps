from django.contrib import admin
from .models import ReporteLink

@admin.register(ReporteLink)
class ReporteLinkAdmin(admin.ModelAdmin):
    """
    Registro del modelo dummy para activar la visibilidad de la app 'reportes' en Jazzmin.
    """
    def has_module_perms(self, request):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
