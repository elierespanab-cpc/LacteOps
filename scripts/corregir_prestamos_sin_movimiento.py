# -*- coding: utf-8 -*-
"""
Script de correccion: genera MovimientoCaja para prestamos activos que no lo tienen.

Uso:
    python manage.py shell < scripts/corregir_prestamos_sin_movimiento.py
"""
from decimal import Decimal

from apps.bancos.models import MovimientoCaja
from apps.bancos.services import registrar_movimiento_caja
from apps.socios.models import PrestamoPorSocio

corregidos = 0
omitidos = 0

for prestamo in PrestamoPorSocio.objects.filter(estado="ACTIVO").select_related("socio", "cuenta_destino"):
    tiene_mov = MovimientoCaja.objects.filter(referencia=prestamo.numero).exists()

    if tiene_mov:
        print(f"OK  {prestamo.numero}: ya tiene MovimientoCaja")
        continue

    if not prestamo.cuenta_destino:
        print(f"SIN CUENTA  {prestamo.numero}: sin cuenta_destino, omitido")
        omitidos += 1
        continue

    monto = Decimal(str(prestamo.monto_principal))
    moneda = prestamo.moneda
    tasa = Decimal(str(prestamo.tasa_cambio))

    try:
        registrar_movimiento_caja(
            cuenta=prestamo.cuenta_destino,
            tipo="ENTRADA",
            monto=monto,
            moneda=moneda,
            tasa_cambio=tasa,
            referencia=prestamo.numero,
            notas=f"Prestamo socio: {prestamo.socio.nombre} (correccion retroactiva)",
        )
    except Exception as e:
        print(f"ERROR  {prestamo.numero}: {e}")
        continue

    print(f"CORREGIDO  {prestamo.numero}: {monto} {moneda} -> {prestamo.cuenta_destino.nombre}")
    corregidos += 1

print(f"\nResumen: {corregidos} corregidos, {omitidos} omitidos (sin cuenta_destino)")
