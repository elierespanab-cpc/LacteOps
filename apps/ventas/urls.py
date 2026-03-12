from django.urls import path
from . import views_print

app_name = "ventas"

urlpatterns = [
    path("print/factura-venta/<int:pk>/", views_print.imprimir_factura_venta, name="imprimir_factura_venta"),
]
