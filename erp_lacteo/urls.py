from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path

from apps.core.admin import vista_respaldo_bd

urlpatterns = [
    path("admin/", admin.site.urls),
    path("admin/respaldo-bd/", login_required(vista_respaldo_bd)),
    path("ventas/", include("apps.ventas.urls")),
    path("compras/", include("apps.compras.urls")),
    path("produccion/", include("apps.produccion.urls")),
    path("almacen/", include("apps.almacen.urls")),
    path("bancos/", include("apps.bancos.urls")),
    path("reportes/", include("apps.reportes.urls", namespace='reportes')),
    path("socios/", include("apps.socios.urls")),
]
