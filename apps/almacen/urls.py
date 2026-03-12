from django.urls import path
from . import views_print

app_name = "almacen"

urlpatterns = [
    path("print/movimiento-inventario/<int:pk>/", views_print.imprimir_movimiento_inventario, name="imprimir_movimiento_inventario"),
    path("print/ajuste-inventario/<int:pk>/", views_print.imprimir_ajuste_inventario, name="imprimir_ajuste_inventario"),
]
