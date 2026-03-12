from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.core.models import ConfiguracionEmpresa
from .models import MovimientoInventario, AjusteInventario


@login_required
def imprimir_movimiento_inventario(request, pk):
    obj = get_object_or_404(MovimientoInventario, pk=pk)
    empresa = ConfiguracionEmpresa.objects.first()
    return render(request, "print/movimiento_inventario.html", {"obj": obj, "empresa": empresa})


@login_required
def imprimir_ajuste_inventario(request, pk):
    obj = get_object_or_404(AjusteInventario, pk=pk)
    empresa = ConfiguracionEmpresa.objects.first()
    return render(request, "print/ajuste_inventario.html", {"obj": obj, "empresa": empresa})
