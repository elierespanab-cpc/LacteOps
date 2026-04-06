# -*- coding: utf-8 -*-
"""
Filtros de template personalizados para LacteOps.
Formato español: punto como separador de millares, coma como decimal.
"""
from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()


def _formatear(valor, decimales):
    """Núcleo de formateo: convierte valor a string con formato español."""
    if valor is None or valor == '':
        return '-'
    try:
        if not isinstance(valor, Decimal):
            valor = Decimal(str(valor))

        # Formato con N decimales
        fmt = f"{{:.{decimales}f}}"
        valor_str = fmt.format(valor)

        partes = valor_str.split('.')
        parte_entera = partes[0]
        parte_decimal = partes[1] if len(partes) > 1 else ''

        # Manejar signo negativo
        negativo = parte_entera.startswith('-')
        if negativo:
            parte_entera = parte_entera[1:]

        # Separador de millares (punto)
        grupos = []
        while len(parte_entera) > 3:
            grupos.insert(0, parte_entera[-3:])
            parte_entera = parte_entera[:-3]
        grupos.insert(0, parte_entera)
        entero_formateado = '.'.join(grupos)

        if negativo:
            entero_formateado = '-' + entero_formateado

        if decimales > 0:
            return f"{entero_formateado},{parte_decimal}"
        return entero_formateado

    except (ValueError, TypeError, InvalidOperation):
        return str(valor)


@register.filter(name='formato_numero')
def formato_numero(valor, decimales=2):
    """
    Formato genérico con separador de millares (punto) y decimal (coma).
    Uso: {{ valor|formato_numero }} o {{ valor|formato_numero:6 }}
    """
    try:
        decimales = int(decimales)
    except (ValueError, TypeError):
        decimales = 2
    return _formatear(valor, decimales)


@register.filter(name='formato_moneda')
def formato_moneda(valor, moneda='USD'):
    """
    Formato monetario con símbolo. 2 decimales.
    Uso: {{ valor|formato_moneda }} o {{ valor|formato_moneda:"Bs." }}
    """
    num = _formatear(valor, 2)
    if num == '-':
        return '-'
    return f"{moneda} {num}"


@register.filter(name='formato_costo')
def formato_costo(valor):
    """
    Costo unitario con 6 decimales (para producción).
    Uso: {{ costo_unitario|formato_costo }}
    """
    return _formatear(valor, 6)


@register.filter(name='formato_cantidad')
def formato_cantidad(valor):
    """
    Cantidad con 4 decimales (inventario/producción).
    Uso: {{ cantidad|formato_cantidad }}
    """
    return _formatear(valor, 4)
