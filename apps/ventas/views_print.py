from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.core.models import ConfiguracionEmpresa
from .models import FacturaVenta


@login_required
def imprimir_factura_venta(request, pk):
    obj = get_object_or_404(FacturaVenta, pk=pk)
    empresa = ConfiguracionEmpresa.objects.first()
    return render(request, "print/factura_venta.html", {"obj": obj, "empresa": empresa})
