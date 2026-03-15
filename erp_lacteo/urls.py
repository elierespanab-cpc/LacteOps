from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path
from django.views.generic import RedirectView

from apps.core.admin import vista_respaldo_bd, api_tasa_fecha

urlpatterns = [
    path(
        "",
        login_required(
            RedirectView.as_view(url="/reportes/dashboard/", permanent=False)
        ),
    ),
    path("admin/", admin.site.urls),
    path("ventas/", include("apps.ventas.urls")),
    path("compras/", include("apps.compras.urls")),
    path("produccion/", include("apps.produccion.urls")),
    path("almacen/", include("apps.almacen.urls")),
    path("bancos/", include("apps.bancos.urls")),
    path("reportes/", include("apps.reportes.urls", namespace="reportes")),
    path("socios/", include("apps.socios.urls")),
    path("respaldo-bd/", login_required(vista_respaldo_bd), name="respaldo_bd"),
    path("api/tasa/", api_tasa_fecha, name="api_tasa"),
]
