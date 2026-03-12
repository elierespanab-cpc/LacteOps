# -*- coding: utf-8 -*-
from django.core.exceptions import ValidationError


class LacteOpsError(ValidationError):
    """
    Clase base para todas las excepciones de negocio de LacteOps.
    Garantiza que todas las excepciones tengan un 'code' definido
    y que el atributo 'message' sea accesible para el Admin.
    """
    code = 'lacteops_error'

    def __init__(self, message, code=None, params=None):
        self.message = message
        super().__init__(message, code=code or self.__class__.code, params=params)


class StockInsuficienteError(LacteOpsError):
    """
    Se lanza cuando una operación de salida intentaría dejar el stock negativo.
    """
    code = 'stock_insuficiente'

    def __init__(self, producto_nombre, disponible, requerido):
        message = (
            f'Stock insuficiente para {producto_nombre}. '
            f'Disponible: {disponible}, Requerido: {requerido}'
        )
        super().__init__(message)


class EstadoInvalidoError(LacteOpsError):
    """
    Se lanza cuando se intenta ejecutar una acción sobre un documento
    cuyo estado actual no lo permite.
    """
    code = 'estado_invalido'

    def __init__(self, entidad, estado_actual, accion):
        message = f'No se puede {accion} un(a) {entidad} en estado {estado_actual}.'
        super().__init__(message)


class UnidadIncompatibleError(LacteOpsError):
    """
    Se lanza cuando la unidad de medida de un consumo de OP no coincide
    con la unidad de medida del producto asociado.
    """
    code = 'unidad_incompatible'

    def __init__(self, unidad_consumo, unidad_producto):
        message = (
            f'Unidad de consumo {unidad_consumo} no coincide con '
            f'unidad del producto {unidad_producto}.'
        )
        super().__init__(message)


class PeriodoCerradoError(LacteOpsError):
    """
    Se lanza cuando se intenta registrar un movimiento en un período
    que ya ha sido cerrado (Soft Close o Hard Close).
    """
    code = 'periodo_cerrado'

    def __init__(self):
        message = 'El período está cerrado. Use la serie APC para ajustes posteriores.'
        super().__init__(message)


class SaldoInsuficienteError(LacteOpsError):
    """
    Se lanza cuando una salida de caja dejaría el saldo de la CuentaBancaria negativo.
    """
    code = 'saldo_insuficiente'

    def __init__(self, cuenta_nombre, disponible, requerido):
        message = (
            f'Saldo insuficiente en cuenta "{cuenta_nombre}". '
            f'Disponible: {disponible}, Requerido: {requerido}'
        )
        super().__init__(message)
