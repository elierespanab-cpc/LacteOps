from decimal import Decimal

from apps.bancos.models import CuentaBancaria, MovimientoCaja
from apps.core.models import TasaCambio
from apps.socios.models import PrestamoPorSocio

print("=" * 70)
print("VERIFICACION CRITICA 1: PRESTAMO SOC-0043")
print("=" * 70)

prestamo = PrestamoPorSocio.objects.filter(numero="SOC-0043").select_related("socio", "cuenta_destino").first()
if prestamo:
    print("Prestamo existe: SI")
    print(f"Numero: {prestamo.numero}")
    print(f"Socio: {prestamo.socio.nombre}")
    print(f"Fecha: {prestamo.fecha_prestamo}")
    print(f"Monto: {prestamo.monto_principal} {prestamo.moneda}")
    print(f"Monto USD: {prestamo.monto_usd}")
    print(f"Cuenta destino: {prestamo.cuenta_destino.nombre if prestamo.cuenta_destino else 'NULL'}")
else:
    print("Prestamo existe: NO")

cuenta = CuentaBancaria.objects.filter(nombre__icontains="PRESTAMO VALENTIN").first()
if cuenta:
    print(f"Cuenta objetivo: {cuenta.nombre} ({cuenta.moneda}) saldo={cuenta.saldo_actual}")
else:
    print("Cuenta objetivo: NO ENCONTRADA")

movs_soc = MovimientoCaja.objects.filter(referencia="SOC-0043").order_by("fecha", "id")
print(f"Movimientos con referencia SOC-0043: {movs_soc.count()}")
for mov in movs_soc:
    print(f"  {mov.fecha} | {mov.cuenta.nombre} | {mov.tipo} | {mov.monto} {mov.moneda} | USD {mov.monto_usd}")

if cuenta:
    movs_cuenta = MovimientoCaja.objects.filter(cuenta=cuenta).order_by("-fecha", "-id")
    print(f"Movimientos en cuenta {cuenta.nombre}: {movs_cuenta.count()}")
    for mov in movs_cuenta[:5]:
        print(f"  {mov.fecha} | {mov.tipo} | {mov.monto} {mov.moneda} | Ref {mov.referencia}")

activos = PrestamoPorSocio.objects.filter(estado="ACTIVO").select_related("socio", "cuenta_destino")
sin_mov = []
for prest in activos:
    if not MovimientoCaja.objects.filter(referencia=prest.numero).exists():
        sin_mov.append(prest)

print(f"Prestamos activos totales: {activos.count()}")
print(f"Prestamos activos sin MovimientoCaja: {len(sin_mov)}")
for prest in sin_mov[:10]:
    cuenta_txt = prest.cuenta_destino.nombre if prest.cuenta_destino else "SIN CUENTA"
    print(f"  {prest.numero} | {prest.socio.nombre} | {prest.fecha_prestamo} | ${prest.monto_usd} | {cuenta_txt}")

if prestamo:
    socio = prestamo.socio
    print(f"Saldo bruto socio: ${socio.get_saldo_bruto()}")
    print(f"Saldo neto socio: ${socio.get_saldo_neto()}")

print("\n" + "=" * 70)
print("VERIFICACION CRITICA 2: EFECTIVO CAPITAL DE TRABAJO")
print("=" * 70)

ultima = TasaCambio.objects.order_by("-fecha").first()
if ultima:
    tasa_ves = Decimal(str(getattr(ultima, "tasa", Decimal("1.00"))))
    print(f"Tasa usada: {tasa_ves} (fecha {ultima.fecha})")
else:
    tasa_ves = Decimal("36.00")
    print(f"Tasa usada por defecto: {tasa_ves}")

cuentas = CuentaBancaria.objects.filter(activa=True).order_by("moneda", "nombre")
print(f"Cuentas activas: {cuentas.count()}")

total = Decimal("0.00")
subtotal_usd = Decimal("0.00")
subtotal_ves_usd = Decimal("0.00")
ves_count = 0
for cta in cuentas:
    saldo = Decimal(cta.saldo_actual)
    if cta.moneda == "USD":
        saldo_usd = saldo
        subtotal_usd += saldo_usd
        print(f"USD | {cta.nombre}: {saldo:,.2f} -> ${saldo_usd:,.2f}")
    elif cta.moneda == "VES":
        ves_count += 1
        saldo_usd = (saldo / tasa_ves) if tasa_ves else Decimal("0.00")
        subtotal_ves_usd += saldo_usd
        print(f"VES | {cta.nombre}: {saldo:,.2f} / {tasa_ves} -> ${saldo_usd:,.2f}")
    else:
        saldo_usd = Decimal("0.00")
        print(f"OTRA | {cta.nombre}: {saldo:,.2f} {cta.moneda} -> $0.00")
    total += saldo_usd

nivel = "CRITICO" if total > Decimal("1000000.00") else ("ALTO" if total > Decimal("100000.00") else "BAJO")
print(f"Subtotal USD: ${subtotal_usd:,.2f}")
print(f"Subtotal VES->USD: ${subtotal_ves_usd:,.2f}")
print(f"Total efectivo: ${total:,.2f}")
print(f"Nivel problema: {nivel}")
print(f"Cuentas VES analizadas: {ves_count}")

for cta in cuentas.filter(moneda="VES"):
    saldo = Decimal(cta.saldo_actual)
    correcto = (saldo / tasa_ves) if tasa_ves else Decimal("0.00")
    incorrecto = saldo * tasa_ves
    print(f"Conversion check {cta.nombre}: dividir=${correcto:,.2f} | multiplicar=${incorrecto:,.2f}")

print("\n" + "=" * 70)
print("FIN VERIFICACION CRITICA S6.1")
print("=" * 70)
