# -*- coding: utf-8 -*-
import logging

from django.contrib import admin, messages

from apps.bancos.models import CuentaBancaria, MovimientoCaja, TransferenciaCuentas
from apps.core.exceptions import LacteOpsError

logger = logging.getLogger(__name__)


@admin.register(CuentaBancaria)
class CuentaBancariaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "moneda", "saldo_actual", "activa")
    readonly_fields = ("saldo_actual",)


@admin.register(MovimientoCaja)
class MovimientoCajaAdmin(admin.ModelAdmin):
    list_display = ("cuenta", "tipo", "monto", "moneda", "monto_usd", "fecha")
    readonly_fields = (
        "cuenta",
        "tipo",
        "monto",
        "moneda",
        "tasa_cambio",
        "monto_usd",
        "referencia",
        "fecha",
        "notas",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return True


@admin.register(TransferenciaCuentas)
class TransferenciaAdmin(admin.ModelAdmin):
    list_display = (
        "numero",
        "cuenta_origen",
        "cuenta_destino",
        "monto_origen",
        "monto_destino",
        "tasa_cambio",
        "fecha",
        "estado",
    )
    readonly_fields = ("numero", "estado")
    actions = ["ejecutar_transferencias", "anular_transferencias"]

    def ejecutar_transferencias(self, request, queryset):
        for obj in queryset:
            try:
                obj.ejecutar()
                messages.success(request, f'Exitoso: {obj}')
            except LacteOpsError as e:
                messages.error(request, f'Error en {obj}: {e.message}')
            except Exception as e:
                logger.error('Error inesperado ejecutando %s: %s', obj, e, exc_info=True)
                messages.error(request, f'Error inesperado en {obj}. Ver logs.')

    ejecutar_transferencias.short_description = 'Ejecutar transferencias seleccionadas'

    def anular_transferencias(self, request, queryset):
        for obj in queryset:
            try:
                obj.anular()
                messages.success(request, f'Exitoso: {obj}')
            except LacteOpsError as e:
                messages.error(request, f'Error en {obj}: {e.message}')
            except Exception as e:
                logger.error('Error inesperado anulando %s: %s', obj, e, exc_info=True)
                messages.error(request, f'Error inesperado en {obj}. Ver logs.')

    anular_transferencias.short_description = 'Anular transferencias seleccionadas'
