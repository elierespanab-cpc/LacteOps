import os
import sys
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "erp_lacteo.settings.development")

import django

django.setup()

from django.db import transaction
from django.utils import timezone

from apps.bancos.models import MovimientoCaja
from apps.bancos.services import registrar_movimiento_caja
from apps.compras.models import GastoServicio, Pago
from apps.core.exceptions import SaldoInsuficienteError
from scripts.conciliacion_referencias import money, movement_matches_expense, movement_matches_payment

REPORT = ROOT / "EJECUCION_MOVIMIENTOS_HUERFANOS_2026-04-06.md"
def _mock_now_for(fecha):
    return datetime.combine(fecha, time(12, 0, 0), tzinfo=timezone.get_current_timezone())


def existing_match(qs, referencia, fecha, monto):
    if qs.filter(referencia=referencia).exists():
        return True
    if qs.filter(fecha=fecha, monto=monto).exists():
        return True
    if qs.filter(monto=monto, fecha__gte=fecha - timedelta(days=3), fecha__lte=fecha + timedelta(days=3)).exists():
        return True
    return False


def matched_pago_ids():
    return {151, 152, 153, 154, 155, 156, 157, 158, 159}


def pagos_huerfanos_reales():
    skip_ids = matched_pago_ids()
    rows = []
    for pago in Pago.objects.select_related("cuenta_origen", "factura").order_by("fecha", "id"):
        if pago.id in skip_ids or not pago.cuenta_origen_id:
            continue
        qs = MovimientoCaja.objects.filter(cuenta=pago.cuenta_origen, tipo="SALIDA")
        if movement_matches_payment(qs, pago):
            continue
        rows.append(pago)
    return rows


def gastos_huerfanos_reales():
    rows = []
    for gasto in GastoServicio.objects.select_related("cuenta_pago", "proveedor").filter(estado="PAGADO").order_by("fecha_emision", "id"):
        if not gasto.cuenta_pago_id:
            continue
        qs = MovimientoCaja.objects.filter(cuenta=gasto.cuenta_pago, tipo="SALIDA")
        if movement_matches_expense(qs, gasto):
            continue
        rows.append(gasto)
    return rows


def create_pago(pago):
    cuenta = pago.cuenta_origen
    referencia = pago._referencia_pago()
    notas = f"Reconciliacion historica pago compra {referencia}"
    with patch("apps.bancos.services.now", return_value=_mock_now_for(pago.fecha)):
        return registrar_movimiento_caja(
            cuenta=cuenta,
            tipo="SALIDA",
            monto=Decimal(str(pago.monto)),
            moneda=pago.moneda,
            tasa_cambio=Decimal(str(pago.tasa_cambio)),
            referencia=referencia,
            notas=notas,
        )


def create_gasto(gasto):
    cuenta = gasto.cuenta_pago
    notas = f"Reconciliacion historica gasto {gasto.numero}: {gasto.descripcion[:70]}"
    with patch("apps.bancos.services.now", return_value=_mock_now_for(gasto.fecha_emision)):
        return registrar_movimiento_caja(
            cuenta=cuenta,
            tipo="SALIDA",
            monto=Decimal(str(gasto.monto)),
            moneda=gasto.moneda,
            tasa_cambio=Decimal(str(gasto.tasa_cambio)),
            referencia=gasto.numero,
            notas=notas,
        )


def main():
    created = []
    blocked = []
    skipped = []

    pagos = pagos_huerfanos_reales()
    gastos = gastos_huerfanos_reales()

    for pago in pagos:
        qs = MovimientoCaja.objects.filter(cuenta=pago.cuenta_origen, tipo="SALIDA")
        ref = pago._referencia_pago()
        if existing_match(qs, ref, pago.fecha, pago.monto):
            skipped.append(("PAGO", pago.id, pago.fecha, ref, pago.cuenta_origen.nombre, pago.monto, "ya_existia"))
            continue
        try:
            with transaction.atomic():
                mov = create_pago(pago)
            created.append(("PAGO", pago.id, pago.fecha, ref, pago.cuenta_origen.nombre, pago.monto, mov.moneda, mov.tasa_cambio, mov.monto_usd, mov.id))
        except SaldoInsuficienteError as exc:
            blocked.append(("PAGO", pago.id, pago.fecha, ref, pago.cuenta_origen.nombre, pago.monto, str(exc)))

    for gasto in gastos:
        qs = MovimientoCaja.objects.filter(cuenta=gasto.cuenta_pago, tipo="SALIDA")
        if existing_match(qs, gasto.numero, gasto.fecha_emision, gasto.monto):
            skipped.append(("GASTO", gasto.id, gasto.fecha_emision, gasto.numero, gasto.cuenta_pago.nombre, gasto.monto, "ya_existia"))
            continue
        try:
            with transaction.atomic():
                mov = create_gasto(gasto)
            created.append(("GASTO", gasto.id, gasto.fecha_emision, gasto.numero, gasto.cuenta_pago.nombre, gasto.monto, mov.moneda, mov.tasa_cambio, mov.monto_usd, mov.id))
        except SaldoInsuficienteError as exc:
            blocked.append(("GASTO", gasto.id, gasto.fecha_emision, gasto.numero, gasto.cuenta_pago.nombre, gasto.monto, str(exc)))

    lines = []
    lines.append("# Ejecucion de conciliacion de movimientos huerfanos")
    lines.append("")
    lines.append("Fecha de ejecucion: 2026-04-06")
    lines.append("")
    lines.append("## Resumen")
    lines.append("")
    lines.append(f"- Pagos huerfanos detectados: {len(pagos)}")
    lines.append(f"- Gastos huerfanos detectados: {len(gastos)}")
    lines.append(f"- Movimientos creados: {len(created)}")
    lines.append(f"- Movimientos bloqueados por saldo insuficiente: {len(blocked)}")
    lines.append(f"- Movimientos omitidos por idempotencia: {len(skipped)}")
    lines.append("")
    lines.append("## Movimientos creados")
    lines.append("")
    lines.append("| Tipo | ID Doc | Fecha aplicada | Referencia | Cuenta | Monto | Moneda | Tasa | Monto USD | ID MovimientoCaja |")
    lines.append("|---|---:|---|---|---|---:|---|---:|---:|---:|")
    for row in created:
        lines.append(
            f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {money(row[5])} | {row[6]} | {row[7]} | {money(row[8])} | {row[9]} |"
        )
    lines.append("")
    lines.append("## Bloqueados")
    lines.append("")
    lines.append("| Tipo | ID Doc | Fecha | Referencia | Cuenta | Monto | Motivo |")
    lines.append("|---|---:|---|---|---|---:|---|")
    for row in blocked:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {money(row[5])} | {row[6]} |")
    lines.append("")
    lines.append("## Omitidos")
    lines.append("")
    lines.append("| Tipo | ID Doc | Fecha | Referencia | Cuenta | Monto | Motivo |")
    lines.append("|---|---:|---|---|---|---:|---|")
    for row in skipped:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {money(row[5])} | {row[6]} |")

    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(REPORT)
    print(f"created={len(created)}")
    print(f"blocked={len(blocked)}")
    print(f"skipped={len(skipped)}")
    if blocked:
        print("blocked_refs=")
        for row in blocked:
            print(f"{row[0]}|{row[1]}|{row[3]}|{row[4]}|{row[5]}")


if __name__ == "__main__":
    main()
