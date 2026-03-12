from django.urls import path
from . import views_print

app_name = "produccion"

urlpatterns = [
    path("print/orden-produccion/<int:pk>/", views_print.imprimir_orden_produccion, name="imprimir_orden_produccion"),
]
