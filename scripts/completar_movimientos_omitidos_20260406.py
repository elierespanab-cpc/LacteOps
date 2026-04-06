import os
import sys
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "erp_lacteo.settings.development")

import django

django.setup()

from django.utils import timezone

from apps.bancos.models import MovimientoCaja
from apps.bancos.services import registrar_movimiento_caja
from apps.core.exceptions import SaldoInsuficienteError
from apps.compras.models import Pago
from scripts.conciliacion_referencias import money, movement_matches_payment


REPORT = ROOT / "EJECUCION_COMPLEMENTARIA_MOVIMIENTOS_2026-04-06.md"
PAGO_IDS = [103, 106, 108, 109, 112, 116, 120, 122, 126, 130, 133, 134, 137, 140, 146, 149]
def _mock_now_for(fecha):
    return datetime.combine(fecha, time(12, 0, 0), tzinfo=timezone.get_current_timezone())


def exact_exists(qs, referencia, fecha, monto):
    return qs.filter(referencia=referencia, fecha=fecha, monto=monto).exists() or qs.filter(fecha=fecha, monto=monto).exists()


def main():
    created = []
    skipped = []
    blocked = []

    for pago in Pago.objects.select_related("cuenta_origen").filter(id__in=PAGO_IDS).order_by("fecha", "id"):
        ref = pago._referencia_pago()
        qs = MovimientoCaja.objects.filter(cuenta=pago.cuenta_origen, tipo="SALIDA")
        if movement_matches_payment(qs.filter(fecha=pago.fecha, monto=pago.monto), pago, strict=True):
            skipped.append((pago.id, pago.fecha, ref, pago.cuenta_origen.nombre, pago.monto, "ya_existia_exacto"))
            continue
        try:
            with patch("apps.bancos.services.now", return_value=_mock_now_for(pago.fecha)):
                mov = registrar_movimiento_caja(
                    cuenta=pago.cuenta_origen,
                    tipo="SALIDA",
                    monto=Decimal(str(pago.monto)),
                    moneda=pago.moneda,
                    tasa_cambio=Decimal(str(pago.tasa_cambio)),
                    referencia=ref,
                    notas=f"Reconciliacion complementaria pago compra {ref}",
                )
            created.append((pago.id, pago.fecha, ref, pago.cuenta_origen.nombre, pago.monto, mov.moneda, mov.tasa_cambio, mov.monto_usd, mov.id))
        except SaldoInsuficienteError as exc:
            blocked.append((pago.id, pago.fecha, ref, pago.cuenta_origen.nombre, pago.monto, str(exc)))

    lines = []
    lines.append("# Ejecucion complementaria de movimientos omitidos")
    lines.append("")
    lines.append("Fecha de ejecucion: 2026-04-06")
    lines.append("")
    lines.append("## Resumen")
    lines.append("")
    lines.append(f"- Pagos objetivos: {len(PAGO_IDS)}")
    lines.append(f"- Movimientos creados: {len(created)}")
    lines.append(f"- Movimientos omitidos: {len(skipped)}")
    lines.append(f"- Movimientos bloqueados: {len(blocked)}")
    lines.append("")
    lines.append("## Creados")
    lines.append("")
    lines.append("| ID Pago | Fecha | Referencia | Cuenta | Monto | Moneda | Tasa | Monto USD | ID MovimientoCaja |")
    lines.append("|---:|---|---|---|---:|---|---:|---:|---:|")
    for row in created:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {money(row[4])} | {row[5]} | {row[6]} | {money(row[7])} | {row[8]} |")
    lines.append("")
    lines.append("## Omitidos")
    lines.append("")
    lines.append("| ID Pago | Fecha | Referencia | Cuenta | Monto | Motivo |")
    lines.append("|---:|---|---|---|---:|---|")
    for row in skipped:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {money(row[4])} | {row[5]} |")
    lines.append("")
    lines.append("## Bloqueados")
    lines.append("")
    lines.append("| ID Pago | Fecha | Referencia | Cuenta | Monto | Motivo |")
    lines.append("|---:|---|---|---|---:|---|")
    for row in blocked:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {money(row[4])} | {row[5]} |")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(REPORT)
    print(f"created={len(created)}")
    print(f"skipped={len(skipped)}")
    print(f"blocked={len(blocked)}")


if __name__ == "__main__":
    main()
