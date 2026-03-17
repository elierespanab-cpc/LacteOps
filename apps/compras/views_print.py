from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.core.models import ConfiguracionEmpresa
from .models import Pago, DetallePagoFactura, GastoServicio


@login_required
def imprimir_recibo_compra(request, pk):
    obj = get_object_or_404(Pago, pk=pk)
    empresa = ConfiguracionEmpresa.objects.first()
    ctx = {"obj": obj, "empresa": empresa}

    if obj.es_consolidado:
        detalles = (
            DetallePagoFactura.objects
            .filter(pago=obj)
            .select_related('factura__proveedor')
            .prefetch_related('factura__detalles__producto')
        )
        ctx["detalles_facturas"] = detalles
        ctx["total_aplicado"] = sum(
            d.monto_aplicado for d in detalles
        ) or Decimal('0')

    return render(request, "print/recibo_compra.html", ctx)


@login_required
def imprimir_gasto_servicio(request, pk):
    obj = get_object_or_404(GastoServicio, pk=pk)
    empresa = ConfiguracionEmpresa.objects.first()
    return render(request, "print/gasto_servicio.html", {"obj": obj, "empresa": empresa})
