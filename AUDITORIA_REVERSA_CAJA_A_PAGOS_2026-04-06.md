# Auditoria reversa de MovimientoCaja -> Pagos/Gastos

Fecha de corte: 2026-04-06

## Resumen

- Salidas en MovimientoCaja revisadas: 9
- Match fuerte: 9
- Match probable: 0
- Ambiguo: 0
- Sin match: 0

## Lectura

- En esta base, las 9 salidas de caja apuntan a pagos de facturas de compra, no a gastos/servicios.
- El patron dominante es referencia manual con numero de factura (`000007`, `1277`, etc.) en lugar de la referencia generada por el sistema (`PAGO-000007`, `PAGO-1277`).
- Esto explica por que el cruce directo desde `Pago` hacia `MovimientoCaja` los marcaba como sospechosos.

## Detalle de cruces

| MovimientoCaja | Fecha mov. | Cuenta | Ref. mov. | Monto | Resultado | Documento sugerido | Fecha doc. | Referencia esperada | Evidencia |
|---:|---|---|---|---:|---|---|---|---|---|
| 108 | 2026-04-05 | BANESCO LACTEOS | 1277 | 25.578,00 | MATCH_FUERTE | PAGO #159 / 1277 | 2026-03-12 | PAGO-1277 | referencia coincide con numero de factura; misma cuenta; mismo monto; fecha relacionada (24d) |
| 107 | 2026-04-05 | CAJA PRESTAMO VALENTIN | 000007 | 67.200,00 | MATCH_FUERTE | PAGO #158 / 000007 | 2026-03-31 | PAGO-000007 | referencia coincide con numero de factura; misma cuenta; mismo monto; fecha relacionada (5d) |
| 106 | 2026-04-05 | CAJA PRESTAMO VALENTIN | 000006 | 45.773,87 | MATCH_FUERTE | PAGO #157 / 000006 | 2026-03-26 | PAGO-000006 | referencia coincide con numero de factura; misma cuenta; mismo monto; fecha relacionada (10d) |
| 105 | 2026-04-05 | CAJA PRESTAMO VALENTIN | 000005 | 114.500,00 | MATCH_FUERTE | PAGO #156 / 000005 | 2026-03-23 | PAGO-000005 | referencia coincide con numero de factura; misma cuenta; mismo monto; fecha relacionada (13d) |
| 104 | 2026-04-05 | CAJA PRESTAMO VALENTIN | 000004 | 90.270,00 | MATCH_FUERTE | PAGO #155 / 000004 | 2026-03-16 | PAGO-000004 | referencia coincide con numero de factura; misma cuenta; mismo monto; fecha relacionada (20d) |
| 103 | 2026-04-05 | CAJA PRESTAMO VALENTIN | 000003 | 46.394,25 | MATCH_FUERTE | PAGO #154 / 000003 | 2026-03-06 | PAGO-000003 | referencia coincide con numero de factura; misma cuenta; mismo monto; fecha relacionada (30d) |
| 102 | 2026-04-05 | CAJA PRINCIPAL | 000002 | 46.704,63 | MATCH_FUERTE | PAGO #153 / 000002 | 2026-03-05 | PAGO-000002 | referencia coincide con numero de factura; misma cuenta; mismo monto |
| 101 | 2026-04-05 | CAJA PRESTAMO VALENTIN | 000001 | 53.825,20 | MATCH_FUERTE | PAGO #152 / 000001 | 2026-02-26 | PAGO-000001 | referencia coincide con numero de factura; misma cuenta; mismo monto |
| 100 | 2026-04-05 | CAJA PRESTAMO VALENTIN | 00000 | 86.000,00 | MATCH_FUERTE | PAGO #151 / 00000 | 2026-02-19 | PAGO-00000 | referencia coincide con numero de factura; misma cuenta; mismo monto |

## Sin correspondencia con GastoServicio

- No se encontro ninguna salida de `MovimientoCaja` cuyo mejor match sea un `GastoServicio` pagado.

## Conclusiones operativas

- El problema principal no parece ser ausencia total de salida en caja para estas 9 operaciones, sino inconsistencia en la referencia usada al registrar el movimiento.
- Los demas pagos/gastos marcados como sospechosos en la auditoria directa siguen necesitando revision, porque no tienen una salida de caja equivalente dentro del ledger actual.
- Antes de automatizar reparaciones, conviene normalizar primero la estrategia de referencia para que `Pago.registrar()` y las cargas manuales hablen el mismo idioma.