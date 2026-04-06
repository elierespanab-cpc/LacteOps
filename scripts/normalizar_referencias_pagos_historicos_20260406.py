import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "erp_lacteo.settings.development")

import django

django.setup()

from apps.bancos.models import MovimientoCaja
from apps.compras.models import Pago


REPORT = ROOT / "NORMALIZACION_REFERENCIAS_PAGOS_HISTORICOS_2026-04-06.md"
TARGET_IDS = [151, 152, 153, 154, 155, 156, 157, 158, 159]


def main():
    updated = []
    skipped = []
    for pago in Pago.objects.select_related("factura", "cuenta_origen").filter(id__in=TARGET_IDS).order_by("fecha", "id"):
        mov = (
            MovimientoCaja.objects.filter(
                cuenta=pago.cuenta_origen,
                tipo="SALIDA",
                monto=pago.monto,
                referencia=pago.factura.numero,
            )
            .order_by("fecha", "id")
            .first()
        )
        if not mov:
            skipped.append((pago.id, pago.factura.numero, "sin_movimiento_manual_encontrado"))
            continue

        manual_ref = (mov.referencia or "").strip()
        generated_ref = pago._referencia_pago()
        changed = False

        if (pago.referencia or "").strip() != manual_ref:
            pago.referencia = manual_ref
            changed = True

        alias_note = f"Alias historico MovimientoCaja: {manual_ref} => {generated_ref}"
        notas = (pago.notas or "").strip()
        if alias_note not in notas:
            pago.notas = f"{notas} | {alias_note}".strip(" |")
            changed = True

        if changed:
            pago.save(update_fields=["referencia", "notas"])
            updated.append((pago.id, pago.fecha, manual_ref, generated_ref, pago.cuenta_origen.nombre, mov.id))
        else:
            skipped.append((pago.id, manual_ref, "ya_normalizado"))

    lines = []
    lines.append("# Normalizacion de referencias historicas de pagos")
    lines.append("")
    lines.append("Fecha de ejecucion: 2026-04-06")
    lines.append("")
    lines.append("## Resumen")
    lines.append("")
    lines.append(f"- Pagos objetivo: {len(TARGET_IDS)}")
    lines.append(f"- Pagos actualizados: {len(updated)}")
    lines.append(f"- Pagos omitidos: {len(skipped)}")
    lines.append("")
    lines.append("## Actualizados")
    lines.append("")
    lines.append("| ID Pago | Fecha | Ref. manual | Ref. generada | Cuenta | ID MovimientoCaja |")
    lines.append("|---:|---|---|---|---|---:|")
    for row in updated:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} |")
    lines.append("")
    lines.append("## Omitidos")
    lines.append("")
    lines.append("| ID Pago | Referencia | Motivo |")
    lines.append("|---:|---|---|")
    for row in skipped:
        lines.append(f"| {row[0]} | {row[1]} | {row[2]} |")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(REPORT)
    print(f"updated={len(updated)}")
    print(f"skipped={len(skipped)}")


if __name__ == "__main__":
    main()
