# -*- coding: utf-8 -*-
import pytest
from decimal import Decimal
from datetime import date
from apps.bancos.models import CuentaBancaria
from apps.bancos.services import ReexpresionMensual
from apps.core.exceptions import EstadoInvalidoError

@pytest.fixture
def cuenta_ves(db):
    return CuentaBancaria.objects.create(
        nombre='Banesco VES', numero_cuenta='0134', moneda='VES', saldo_actual=Decimal('1000.00'), activa=True
    )

@pytest.mark.django_db
def test_segunda_ejecucion_mismo_periodo_lanza_error(cuenta_ves, usuario):
    """
    Verifica que el servicio de reexpresión mensual bloquee una segunda ejecución
    para el mismo mes/año.
    """
    fecha = date(2026, 3, 31)
    tasa_i = Decimal('40.00')
    tasa_f = Decimal('45.00')

    # Primera ejecución -> Suceso
    ReexpresionMensual.ejecutar(tasa_i, tasa_f, fecha, usuario)
    
    # Segunda ejecución -> Error
    with pytest.raises(EstadoInvalidoError, match="Período ya reexpresado"):
        ReexpresionMensual.ejecutar(tasa_i, tasa_f, fecha, usuario)
