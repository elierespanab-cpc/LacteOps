from django.urls import path
from . import views_print

app_name = "ventas"

urlpatterns = [
    path("print/factura-venta/<int:pk>/", views_print.imprimir_factura_venta, name="imprimir_factura_venta"),
    path("print/nota-credito/<int:pk>/", views_print.imprimir_nota_credito, name="imprimir_nota_credito"),
]
