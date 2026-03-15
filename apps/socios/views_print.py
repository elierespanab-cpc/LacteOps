from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.core.models import ConfiguracionEmpresa
from .models import PrestamoPorSocio


@login_required
def imprimir_prestamo(request, pk):
    obj = get_object_or_404(PrestamoPorSocio, pk=pk)
    empresa = ConfiguracionEmpresa.objects.first()
    return render(request, "print/voucher_prestamo.html", {"obj": obj, "empresa": empresa})
