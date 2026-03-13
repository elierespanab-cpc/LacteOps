from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("ventas/", include("apps.ventas.urls")),
    path("compras/", include("apps.compras.urls")),
    path("produccion/", include("apps.produccion.urls")),
    path("almacen/", include("apps.almacen.urls")),
    path("bancos/", include("apps.bancos.urls")),
    path("reportes/", include("apps.reportes.urls", namespace='reportes')),
]
