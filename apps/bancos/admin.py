# -*- coding: utf-8 -*-
import logging
from datetime import date
from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse

from apps.bancos.models import (
    CuentaBancaria,
    MovimientoCaja,
    TransferenciaCuentas,
    MovimientoTesoreria,
)
from apps.bancos.services import ejecutar_movimiento_tesoreria
from apps.core.models import CategoriaGasto
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
        # Permitir para que el Collector de Django no bloquee la vista de eliminación de CuentaBancaria.
        # El modelo MovimientoCaja sigue siendo inmutable vía su método delete() y select_for_update.
        return request.user.is_superuser

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


class MovimientoTesoreriaForm(forms.Form):
    cuenta = forms.ModelChoiceField(queryset=CuentaBancaria.objects.all())
    tipo = forms.ChoiceField(choices=MovimientoTesoreria.TIPOS)
    monto = forms.DecimalField(max_digits=18, decimal_places=2)
    moneda = forms.ChoiceField(choices=MovimientoTesoreria.MONEDA_CHOICES)
    tasa_cambio = forms.DecimalField(max_digits=18, decimal_places=6, initial=Decimal("1.000000"))
    categoria = forms.ModelChoiceField(
        queryset=CategoriaGasto.objects.filter(contexto="TESORERIA", activa=True)
    )
    descripcion = forms.CharField(widget=forms.Textarea)
    fecha = forms.DateField(initial=date.today)


@admin.register(MovimientoTesoreria)
class MovimientoTesoreriaAdmin(admin.ModelAdmin):
    list_display = ("numero", "cuenta", "tipo", "monto", "moneda", "categoria", "fecha")
    list_filter = ("tipo", "cuenta", "fecha")
    readonly_fields = ("numero", "monto_usd", "registrado_por")
    actions = ["registrar_movimiento_directo"]
    change_form_template = "admin/print_change_form.html"
    print_url_name = "bancos:imprimir_voucher_tesoreria"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def registrar_movimiento_directo(self, request, queryset):
        if request.POST.get("apply"):
            form = MovimientoTesoreriaForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                try:
                    movimiento = ejecutar_movimiento_tesoreria(
                        cuenta=data["cuenta"],
                        tipo=data["tipo"],
                        monto=data["monto"],
                        moneda=data["moneda"],
                        tasa_cambio=data["tasa_cambio"],
                        categoria=data["categoria"],
                        descripcion=data["descripcion"],
                        fecha=data["fecha"],
                        usuario=request.user,
                    )
                    self.message_user(request, f"Movimiento creado: {movimiento.numero}")
                    return HttpResponseRedirect(request.get_full_path())
                except LacteOpsError as e:
                    self.message_user(request, e.message, level=messages.ERROR)
                except Exception as e:
                    logger.error("Error registrando movimiento de tesoreria: %s", e, exc_info=True)
                    self.message_user(request, "Error inesperado. Ver logs.", level=messages.ERROR)
        else:
            form = MovimientoTesoreriaForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "Registrar movimiento de tesoreria",
            "form": form,
            "queryset": queryset,
            "action_name": "registrar_movimiento_directo",
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/movimiento_tesoreria_action.html", context)

    registrar_movimiento_directo.short_description = "Registrar movimiento directo"
