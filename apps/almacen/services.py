# -*- coding: utf-8 -*-
"""
Servicios de inventario para LacteOps.

Este módulo contiene la lógica central del Kardex:
  - convertir_a_usd: normaliza montos a USD antes de entrar al Kardex.
  - registrar_entrada: Promedio Ponderado Móvil + MovimientoInventario ENTRADA.
  - registrar_salida: validación de stock + MovimientoInventario SALIDA.

REGLAS:
  - decimal.Decimal para TODOS los cálculos. NUNCA float.
  - Toda modificación de stock dentro de transaction.atomic().
  - Stock negativo PROHIBIDO; lanza StockInsuficienteError.
  - El costo que entra al Kardex SIEMPRE en USD.
"""
import logging
from decimal import Decimal

from django.db import transaction

from apps.core.exceptions import StockInsuficienteError

logger = logging.getLogger(__name__)


def recalcular_stock(producto):
    """
    Recalcula stock_actual y costo_promedio del producto procesando todos sus
    MovimientoInventario en orden cronológico, usando Promedio Ponderado Móvil.

    Útil para corregir inconsistencias tras ajustes manuales o importaciones.

    Args:
        producto (Producto): Instancia del producto a recalcular.

    Returns:
        dict: {'stock': Decimal, 'costo_promedio': Decimal}
    """
    from apps.almacen.models import MovimientoInventario

    # DIM-06-002: values_list + iterator() — tuplas ligeras, sin cachear el QS entero
    movimientos = (
        MovimientoInventario.objects.filter(producto=producto)
        .order_by('fecha', 'id')
        .values_list('tipo', 'cantidad', 'costo_unitario')
    )

    stock = Decimal('0')
    costo_prom = Decimal('0')

    for tipo, cantidad, costo_unitario in movimientos.iterator():
        if tipo == 'ENTRADA':
            valor_existente = stock * costo_prom
            valor_entrada = cantidad * costo_unitario
            nueva_cantidad = stock + cantidad
            if nueva_cantidad > 0:
                costo_prom = (valor_existente + valor_entrada) / nueva_cantidad
            stock = nueva_cantidad
        elif tipo == 'SALIDA':
            stock = max(Decimal('0'), stock - cantidad)

    with transaction.atomic():
        from apps.almacen.models import Producto as ProductoModel
        prod = ProductoModel.objects.select_for_update().get(pk=producto.pk)
        prod.stock_actual = stock.quantize(Decimal('0.0001'))
        prod.costo_promedio = costo_prom.quantize(Decimal('0.000001'))
        prod.save(update_fields=['stock_actual', 'costo_promedio'])

    logger.info(
        'recalcular_stock | Producto: %s | Stock: %s | CostoPromedio: %s',
        producto, prod.stock_actual, prod.costo_promedio,
    )
    return {'stock': prod.stock_actual, 'costo_promedio': prod.costo_promedio}


def convertir_a_usd(monto, moneda, tasa_cambio):
    """
    Convierte un monto a USD según la moneda y la tasa de cambio.

    Args:
        monto       (Decimal | str | int): Monto en la moneda indicada.
        moneda      (str): 'USD' o 'VES'.
        tasa_cambio (Decimal | str | int): Tipo de cambio BCV (VES/USD).
                    Ignorado cuando moneda == 'USD'.

    Returns:
        Decimal: Monto expresado en USD.

    Raises:
        ValueError: Si la moneda es VES y la tasa_cambio es <= 0.
    """
    monto = Decimal(str(monto))
    tasa_cambio = Decimal(str(tasa_cambio))

    if moneda == 'USD':
        return monto

    # VES → USD
    if tasa_cambio <= Decimal('0'):
        raise ValueError(
            'La tasa de cambio debe ser mayor que cero para convertir de VES a USD.'
        )
    return monto / tasa_cambio


@transaction.atomic
def registrar_entrada(producto, cantidad, costo_unitario, referencia, notas=''):
    """
    Registra una entrada de mercancía al Kardex aplicando Promedio Ponderado Móvil.

    Fórmula del nuevo costo promedio:
        Si stock_actual == 0  → nuevo_costo = costo_unitario
        Si stock_actual  > 0  → nuevo_costo = (stock_actual * costo_promedio
                                                + cantidad * costo_unitario)
                                               / (stock_actual + cantidad)

    Args:
        producto       (Producto): Instancia del modelo Producto (select for update).
        cantidad       (Decimal | str): Cantidad a ingresar. Debe ser > 0.
        costo_unitario (Decimal | str): Costo unitario EN USD.
        referencia     (str): Número de documento origen (ej. 'COM-0001').
        notas          (str): Texto libre opcional.

    Returns:
        MovimientoInventario: El movimiento creado.

    Raises:
        ValueError: Si cantidad <= 0.
    """
    # Importación tardía para evitar circular imports
    from apps.almacen.models import MovimientoInventario, Producto as ProductoModel

    cantidad = Decimal(str(cantidad))
    costo_unitario = Decimal(str(costo_unitario))

    if cantidad <= Decimal('0'):
        raise ValueError(f'La cantidad de entrada debe ser mayor que cero. Recibido: {cantidad}')

    # Bloqueo a nivel de fila para evitar condiciones de carrera
    producto = ProductoModel.objects.select_for_update().get(pk=producto.pk)

    stock_actual = Decimal(str(producto.stock_actual))
    costo_promedio_actual = Decimal(str(producto.costo_promedio))

    # Cálculo del Promedio Ponderado Móvil
    if stock_actual == Decimal('0'):
        nuevo_costo_promedio = costo_unitario
    else:
        valor_existente = stock_actual * costo_promedio_actual
        valor_nuevo = cantidad * costo_unitario
        nuevo_costo_promedio = (valor_existente + valor_nuevo) / (stock_actual + cantidad)

    # Actualizar stock y costo promedio
    producto.stock_actual = stock_actual + cantidad
    producto.costo_promedio = nuevo_costo_promedio
    producto.save(update_fields=['stock_actual', 'costo_promedio'])

    # Registrar movimiento (inmutable)
    movimiento = MovimientoInventario.objects.create(
        producto=producto,
        tipo='ENTRADA',
        cantidad=cantidad,
        costo_unitario=costo_unitario,
        referencia=referencia,
        notas=notas,
    )

    logger.info(
        'ENTRADA Kardex | Producto: %s | Cantidad: %s | '
        'CostoUnitario: %s USD | NuevoCostoPromedio: %s USD | Ref: %s',
        producto, cantidad, costo_unitario, nuevo_costo_promedio, referencia
    )
    return movimiento


@transaction.atomic
def registrar_salida(producto, cantidad, referencia, notas=''):
    """
    Registra una salida de mercancía del Kardex al costo promedio vigente.
    Las salidas NO modifican el costo promedio.

    Args:
        producto   (Producto): Instancia del modelo Producto.
        cantidad   (Decimal | str): Cantidad a retirar. Debe ser > 0.
        referencia (str): Número de documento origen (ej. 'VTA-0001').
        notas      (str): Texto libre opcional.

    Returns:
        MovimientoInventario: El movimiento creado.

    Raises:
        StockInsuficienteError: Si stock_actual < cantidad.
        ValueError: Si cantidad <= 0.
    """
    # Importación tardía para evitar circular imports
    from apps.almacen.models import MovimientoInventario, Producto as ProductoModel

    cantidad = Decimal(str(cantidad))

    if cantidad <= Decimal('0'):
        raise ValueError(f'La cantidad de salida debe ser mayor que cero. Recibido: {cantidad}')

    # Bloqueo a nivel de fila para evitar condiciones de carrera
    producto = ProductoModel.objects.select_for_update().get(pk=producto.pk)

    stock_actual = Decimal(str(producto.stock_actual))
    costo_unitario_salida = Decimal(str(producto.costo_promedio))

    # Validación de stock — NUNCA negativo
    if stock_actual < cantidad:
        raise StockInsuficienteError(
            producto_nombre=producto.nombre,
            disponible=stock_actual,
            requerido=cantidad,
        )

    # Registrar movimiento ANTES de modificar el stock
    movimiento = MovimientoInventario.objects.create(
        producto=producto,
        tipo='SALIDA',
        cantidad=cantidad,
        costo_unitario=costo_unitario_salida,
        referencia=referencia,
        notas=notas,
    )

    # Descontar stock
    producto.stock_actual = stock_actual - cantidad
    producto.save(update_fields=['stock_actual'])

    logger.info(
        'SALIDA Kardex | Producto: %s | Cantidad: %s | '
        'CostoUnitario: %s USD | StockRestante: %s | Ref: %s',
        producto, cantidad, costo_unitario_salida, producto.stock_actual, referencia
    )
    return movimiento
