from django.urls import path
from apps.reportes import views

app_name = 'reportes'

urlpatterns = [
    path('ventas/', views.reporte_ventas, name='ventas'),
    path('cxc/', views.reporte_cxc, name='cxc'),
    path('compras/', views.reporte_compras, name='compras'),
    path('cxp/', views.reporte_cxp, name='cxp'),
    path('produccion/', views.reporte_produccion, name='produccion'),
    path('gastos/', views.reporte_gastos, name='gastos'),
    path('capital_trabajo/', views.reporte_capital_trabajo, name='capital_trabajo'),
]
