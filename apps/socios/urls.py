from django.urls import path
from . import views_print

app_name = "socios"

urlpatterns = [
    path("prestamo/<int:pk>/print/", views_print.imprimir_prestamo, name="imprimir_prestamo"),
]
