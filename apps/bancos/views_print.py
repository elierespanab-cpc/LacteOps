from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.core.models import ConfiguracionEmpresa
from .models import MovimientoTesoreria


@login_required
def imprimir_voucher_tesoreria(request, pk):
    obj = get_object_or_404(MovimientoTesoreria, pk=pk)
    empresa = ConfiguracionEmpresa.objects.first()
    return render(request, "print/voucher_tesoreria.html", {"obj": obj, "empresa": empresa})
