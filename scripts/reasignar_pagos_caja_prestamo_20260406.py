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

from django.db import transaction
from django.utils import timezone

from apps.bancos.models import CuentaBancaria, MovimientoCaja
from apps.bancos.services import registrar_movimiento_caja
from apps.compras.models import Pago
from scripts.conciliacion_referencias import money


REPORT = ROOT / "EJECUCION_REASIGNACION_CAJA_PRESTAMO_2026-04-06.md"
TARGET_IDS = [98, 102, 125]
def _mock_now_for(fecha):
    return datetime.combine(fecha, time(12, 0, 0), tzinfo=timezone.get_current_timezone())


def main():
    cuenta_destino = CuentaBancaria.objects.get(nombre="CAJA PRESTAMO VALENTIN")
    created = []
    skipped = []

    for pago in Pago.objects.select_related("cuenta_origen").filter(id__in=TARGET_IDS).order_by("fecha", "id"):
        ref = pago._referencia_pago()
        qs = MovimientoCaja.objects.filter(cuenta=cuenta_destino, tipo="SALIDA")
        if qs.filter(referencia=ref, fecha=pago.fecha, monto=pago.monto).exists():
            skipped.append((pago.id, pago.fecha, ref, cuenta_destino.nombre, pago.monto, "ya_existia_exacto_en_cuenta_destino"))
            continue

        with transaction.atomic():
            pago.cuenta_origen = cuenta_destino
            pago.notas = (pago.notas or "").strip()
            extra = f" | Reconciliado 2026-04-06: cuenta_origen ajustada a {cuenta_destino.nombre}"
            if extra not in pago.notas:
                pago.notas = f"{pago.notas}{extra}" if pago.notas else extra.strip(" |")
            pago.save(update_fields=["cuenta_origen", "notas"])

            with patch("apps.bancos.services.now", return_value=_mock_now_for(pago.fecha)):
                mov = registrar_movimiento_caja(
                    cuenta=cuenta_destino,
                    tipo="SALIDA",
                    monto=Decimal(str(pago.monto)),
                    moneda=pago.moneda,
                    tasa_cambio=Decimal(str(pago.tasa_cambio)),
                    referencia=ref,
                    notas=f"Reconciliacion por reasignacion desde CAJA PRINCIPAL hacia {cuenta_destino.nombre}",
                )

        created.append((pago.id, pago.fecha, ref, cuenta_destino.nombre, pago.monto, mov.moneda, mov.tasa_cambio, mov.monto_usd, mov.id))

    lines = []
    lines.append("# Ejecucion de reasignacion a CAJA PRESTAMO VALENTIN")
    lines.append("")
    lines.append("Fecha de ejecucion: 2026-04-06")
    lines.append("")
    lines.append("## Resumen")
    lines.append("")
    lines.append(f"- Pagos objetivo: {len(TARGET_IDS)}")
    lines.append(f"- Movimientos creados: {len(created)}")
    lines.append(f"- Omitidos: {len(skipped)}")
    lines.append("")
    lines.append("## Creados")
    lines.append("")
    lines.append("| ID Pago | Fecha | Referencia | Cuenta destino | Monto | Moneda | Tasa | Monto USD | ID MovimientoCaja |")
    lines.append("|---:|---|---|---|---:|---|---:|---:|---:|")
    for row in created:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {money(row[4])} | {row[5]} | {row[6]} | {money(row[7])} | {row[8]} |")
    lines.append("")
    lines.append("## Omitidos")
    lines.append("")
    lines.append("| ID Pago | Fecha | Referencia | Cuenta destino | Monto | Motivo |")
    lines.append("|---:|---|---|---|---:|---|")
    for row in skipped:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {money(row[4])} | {row[5]} |")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(REPORT)
    print(f"created={len(created)}")
    print(f"skipped={len(skipped)}")


if __name__ == "__main__":
    main()
