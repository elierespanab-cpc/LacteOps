from django.urls import path
from . import views_print

app_name = "compras"

urlpatterns = [
    path("print/recibo-compra/<int:pk>/", views_print.imprimir_recibo_compra, name="imprimir_recibo_compra"),
    path("print/gasto-servicio/<int:pk>/", views_print.imprimir_gasto_servicio, name="imprimir_gasto_servicio"),
]
