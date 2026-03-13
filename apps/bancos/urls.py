from django.urls import path
from . import views_print

app_name = "bancos"

urlpatterns = [
    path("tesoreria/<int:pk>/print/", views_print.imprimir_voucher_tesoreria, name="imprimir_voucher_tesoreria"),
]
