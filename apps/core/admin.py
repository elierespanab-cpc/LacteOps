import os
import subprocess
import tempfile
from io import StringIO

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.db.models import functions

from apps.core.models import AuditLog, ConfiguracionEmpresa, TasaCambio, CategoriaGasto
from apps.bancos.models import RespaldoBD


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
    actions = ["actualizar_tasa_hoy", "importar_historico"]

    def actualizar_tasa_hoy(self, request, queryset):
        out = StringIO()
        call_command("actualizar_tasa_bcv", stdout=out)
        self.message_user(request, out.getvalue())

    def importar_historico(self, request, queryset):
        out = StringIO()
        err = StringIO()
        call_command("importar_historico_bcv", stdout=out, stderr=err)
        if err.getvalue():
            self.message_user(request, err.getvalue(), level=messages.WARNING)
        self.message_user(request, out.getvalue() or "ImportaciÃ³n completada.")

    importar_historico.short_description = "Importar histÃ³rico completo BCV"


@admin.register(CategoriaGasto)
class CategoriaGastoAdmin(admin.ModelAdmin):
    list_display = ("nombre_indentado", "contexto", "activa")
    list_filter = ("contexto", "activa")
    search_fields = ("nombre",)

    def nombre_indentado(self, obj):
        return ("â€” " if obj.padre else "") + obj.nombre

    nombre_indentado.short_description = "CategorÃ­a"

    def get_queryset(self, request):
        return super().get_queryset(request).order_by(
            "contexto",
            functions.Coalesce("padre__nombre", "nombre"),
            "nombre",
        )


def vista_respaldo_bd(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    from django.conf import settings
    db = settings.DATABASES["default"]
    env = os.environ.copy()
    env["PGPASSWORD"] = db["PASSWORD"]
    with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
        tmp_path = tmp.name
    from datetime import datetime
    filename = f"lacteops_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
    try:
        result = subprocess.run(
            [
                "pg_dump",
                "-h", db.get("HOST", "localhost"),
                "-p", str(db.get("PORT", "5432")),
                "-U", db["USER"],
                "-F", "p",
                "-f", tmp_path,
                db["NAME"],
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        exitoso = result.returncode == 0
        tamanio = os.path.getsize(tmp_path) if exitoso else 0
        RespaldoBD.objects.create(
            ejecutado_por=request.user,
            nombre_archivo=filename,
            tamanio_bytes=tamanio,
            exitoso=exitoso,
            error_mensaje=result.stderr if not exitoso else "",
        )
        if exitoso:
            with open(tmp_path, "rb") as f:
                contenido = f.read()
            response = HttpResponse(contenido, content_type="application/sql")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        messages.error(request, f"Error pg_dump: {result.stderr[:300]}")
        return redirect(reverse("admin:index"))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@admin.register(RespaldoBD)
class RespaldoBDAdmin(admin.ModelAdmin):
    list_display = ("fecha", "ejecutado_por", "nombre_archivo", "tamanio_bytes", "exitoso")
    list_filter = ("exitoso",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


