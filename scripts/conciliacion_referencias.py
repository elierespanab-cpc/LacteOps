from apps.reportes.views import _decimal


def payment_reference_candidates(pago):
    refs = []
    generated = pago._referencia_pago()
    if generated:
        refs.append(generated)
    manual = (pago.referencia or "").strip()
    if manual and manual not in refs:
        refs.append(manual)
    if pago.factura_id:
        factura_num = (pago.factura.numero or "").strip()
        if factura_num and factura_num not in refs:
            refs.append(factura_num)
    return refs


def movement_matches_payment(qs, pago, strict=False):
    refs = payment_reference_candidates(pago)
    if strict:
        return qs.filter(referencia__in=refs, monto=pago.monto).exists() or qs.filter(fecha=pago.fecha, monto=pago.monto).exists()
    return qs.filter(referencia__in=refs).exists() or qs.filter(fecha=pago.fecha, monto=pago.monto).exists()


def movement_matches_expense(qs, gasto, strict=False):
    if strict:
        return qs.filter(fecha=gasto.fecha_emision, monto=gasto.monto, referencia=gasto.numero).exists() or qs.filter(fecha=gasto.fecha_emision, monto=gasto.monto).exists()
    return qs.filter(referencia=gasto.numero).exists() or qs.filter(fecha=gasto.fecha_emision, monto=gasto.monto).exists()


def money(value):
    return f"{_decimal(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
