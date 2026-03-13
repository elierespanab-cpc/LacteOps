import os
import django
import datetime
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'erp_lacteo.settings.development')
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from apps.reportes.views import (
    reporte_ventas, reporte_cxc, reporte_compras, reporte_cxp,
    reporte_produccion, reporte_gastos, reporte_capital_trabajo
)

def run_validation():
    rf = RequestFactory()
    user = User.objects.filter(is_superuser=True).first()
    if not user:
        user = User.objects.create_superuser('admin_test', 'admin@test.com', 'admin123')
    
    views = [
        (reporte_ventas, 'Ventas'),
        (reporte_cxc, 'CxC'),
        (reporte_compras, 'Compras'),
        (reporte_cxp, 'CxP'),
        (reporte_produccion, 'Produccion'),
        (reporte_gastos, 'Gastos'),
        (reporte_capital_trabajo, 'Capital de Trabajo'),
    ]
    
    print("\n--- Validaxion de Reportes (HTTP 200) ---")
    for view, name in views:
        request = rf.get('/')
        request.user = user
        try:
            # Add some fake items if needed or just try with current DB
            response = view(request)
            if response.status_code == 200:
                print(f"{name}: OK (200)")
            else:
                print(f"{name}: FAIL ({response.status_code})")
        except Exception as e:
            print(f"{name}: EXCEPTION - {str(e)}")

if __name__ == "__main__":
    run_validation()
