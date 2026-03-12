from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.core.models import ConfiguracionEmpresa
from .models import OrdenProduccion


@login_required
def imprimir_orden_produccion(request, pk):
    obj = get_object_or_404(OrdenProduccion, pk=pk)
    empresa = ConfiguracionEmpresa.objects.first()
    return render(request, "print/orden_produccion.html", {"obj": obj, "empresa": empresa})
