from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.core.models import ConfiguracionEmpresa
from .models import Pago, GastoServicio


@login_required
def imprimir_recibo_compra(request, pk):
    obj = get_object_or_404(Pago, pk=pk)
    empresa = ConfiguracionEmpresa.objects.first()
    return render(request, "print/recibo_compra.html", {"obj": obj, "empresa": empresa})


@login_required
def imprimir_gasto_servicio(request, pk):
    obj = get_object_or_404(GastoServicio, pk=pk)
    empresa = ConfiguracionEmpresa.objects.first()
    return render(request, "print/gasto_servicio.html", {"obj": obj, "empresa": empresa})
