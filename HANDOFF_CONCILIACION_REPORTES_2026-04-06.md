# Handoff Conciliacion Reportes 2026-04-06

## Archivos modificados

- `apps/reportes/views.py`
- `scripts/conciliacion_referencias.py`
- `scripts/crear_movimientos_huerfanos_20260406.py`
- `scripts/completar_movimientos_omitidos_20260406.py`
- `scripts/reasignar_pagos_caja_prestamo_20260406.py`
- `scripts/normalizar_referencias_pagos_historicos_20260406.py`

## Reportes generados

- `AUDITORIA_PAGOS_GASTOS_HUERFANOS_2026-04-06.md`
- `AUDITORIA_REVERSA_CAJA_A_PAGOS_2026-04-06.md`
- `AUDITORIA_HUERFANOS_REALES_PAGOS_GASTOS_2026-04-06.md`
- `EJECUCION_MOVIMIENTOS_HUERFANOS_2026-04-06.md`
- `EJECUCION_COMPLEMENTARIA_MOVIMIENTOS_2026-04-06.md`
- `EJECUCION_REASIGNACION_CAJA_PRESTAMO_2026-04-06.md`
- `NORMALIZACION_REFERENCIAS_PAGOS_HISTORICOS_2026-04-06.md`

## Resultado de verificacion

- `python manage.py check` -> `0 issues`

## Decisiones tomadas

- Se corrigio el fallback de `Capital de Trabajo` para usar `TasaCambio` cuando no existe `PeriodoReexpresado`.
- Se conciliaron movimientos huerfanos de `Pago` y `GastoServicio` creando `MovimientoCaja` historicos con fecha y tasa del documento.
- Los tres pagos bloqueados por saldo insuficiente en `CAJA PRINCIPAL` se reasignaron a `CAJA PRESTAMO VALENTIN` por instruccion del usuario y se creo su movimiento historico correspondiente.
- No se editaron registros de `MovimientoCaja` existentes por la regla de inmutabilidad.
- La normalizacion de referencias historicas se resolvio guardando alias manuales en `Pago.referencia` y notas, mas una capa de equivalencias para conciliaciones futuras.
