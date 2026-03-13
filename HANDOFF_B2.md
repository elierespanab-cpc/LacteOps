# HANDOFF Fase B2 — Sprint 3 LacteOps

**Fecha:** 2026-03-13
**Agente:** Claude Code
**Rama:** `sprint3`

---

## STATUS: OK

---

## Verificación previa de B1

| HANDOFF | manage.py check | Estado |
|---------|----------------|--------|
| HANDOFF_B1_GEM.md | 0 issues | ✅ |
| HANDOFF_B1_COD.md | 0 issues | ✅ |

---

## Archivos modificados / creados

| Archivo | Tipo | Cambio |
|---------|------|--------|
| `apps/socios/models.py` | MODIFICADO | Tarea 1: PrestamoPorSocio + PagoPrestamo |
| `apps/bancos/models.py` | MODIFICADO | Tarea 2: MovimientoTesoreria (inmutable) |
| `apps/core/management/commands/actualizar_tasa_bcv.py` | MODIFICADO | Tarea 3: reemplaza stub |
| `apps/core/management/commands/importar_historico_bcv.py` | MODIFICADO | Tarea 4: reemplaza stub |
| `apps/socios/services.py` | MODIFICADO | Tarea 5: registrar_prestamo + registrar_pago_prestamo |
| `apps/bancos/services.py` | MODIFICADO | Tarea 6: ejecutar_movimiento_tesoreria |
| `apps/reportes/views.py` | MODIFICADO | Tarea 7: Capital de Trabajo incluye préstamos socios |
| `apps/bancos/migrations/0003_movimientotesoreria.py` | NUEVO | Migración MovimientoTesoreria |
| `apps/socios/migrations/0002_alter_socio_options_alter_socio_activo_and_more.py` | NUEVO | PrestamoPorSocio + PagoPrestamo |

---

## Funciones implementadas

### apps/socios/services.py
- **`registrar_prestamo(socio, monto, moneda, tasa, fecha, cuenta_destino, fecha_vencimiento, notas)`**
  - Crea `PrestamoPorSocio` (número y monto_usd generados en `save()`)
  - Si `cuenta_destino` definida → `registrar_movimiento_caja(tipo='ENTRADA')`
  - Todo dentro de `transaction.atomic()`

- **`registrar_pago_prestamo(prestamo, monto, moneda, tasa, fecha, cuenta_origen, notas)`**
  - Cálculo bimoneda explícito: USD→tasa=1 / VES→monto/tasa ROUND_HALF_UP
  - Si `cuenta_origen` definida → `select_for_update()` + `registrar_movimiento_caja(tipo='SALIDA')`
  - Verifica total_pagado_usd >= prestamo.monto_usd → marca `CANCELADO`

### apps/bancos/services.py
- **`ejecutar_movimiento_tesoreria(cuenta, tipo, monto, moneda, tasa_cambio, categoria, descripcion, fecha, usuario)`**
  - Valida `categoria.contexto == 'TESORERIA'` (EstadoInvalidoError si no)
  - Crea `MovimientoTesoreria` (inmutable; `save()` asigna número TES y monto_usd)
  - CARGO → `registrar_movimiento_caja(tipo='SALIDA')` / ABONO → `tipo='ENTRADA'`
  - Todo dentro de `transaction.atomic()`

---

## Modelos nuevos

### PrestamoPorSocio (apps/socios)
- Numeración automática: `SOC-XXXX` vía `generar_numero('SOC')`
- Bimoneda en `save()`: USD→tasa=1 / VES→monto_usd = principal/tasa ROUND_HALF_UP
- FK a `bancos.CuentaBancaria` (cuenta_destino, nullable)
- Estados: ACTIVO / CANCELADO / VENCIDO

### PagoPrestamo (apps/socios)
- FK a PrestamoPorSocio (related_name='pagos')
- monto_usd calculado en `registrar_pago_prestamo()`
- FK a `bancos.CuentaBancaria` (cuenta_origen, nullable)

### MovimientoTesoreria (apps/bancos)
- **INMUTABLE**: `save()` lanza `EstadoInvalidoError` si `not _state.adding`
- Numeración automática: `TES-XXXX` vía `generar_numero('TES')`
- Bimoneda en `save()`: USD→tasa=1 / VES→monto/tasa ROUND_HALF_UP
- FK a `core.CategoriaGasto` (contexto='TESORERIA' validado en service)
- FK a `settings.AUTH_USER_MODEL` (registrado_por, nullable)

---

## Capital de Trabajo — cambios (Tarea 7)

Añadido al contexto del reporte:
- `prestamos_corriente`: sum monto_usd de préstamos activos con vencimiento <= hoy+365d
- `prestamos_no_corriente`: sum monto_usd de préstamos sin vencimiento o > 365d
- `prestamos_activos`: queryset completo para la tabla
- `pasivo_corriente`: cxp_compras + cxp_gastos + prestamos_corriente
- `capital_neto`: activo_corriente - pasivo_corriente
- `capital_trabajo`: alias de capital_neto (compatibilidad con plantilla existente)

---

## Resultado manage.py check

```
System check identified no issues (0 silenced).
```

---

## Resultado manage.py migrate

```
Applying core.0005_tasacambio_categoriagasto... OK
Applying bancos.0003_movimientotesoreria... OK
Applying compras.0004_migrate_categories... OK
Applying compras.0005_alter_gastoservicio_categoria_gasto... OK
Applying socios.0001_initial... OK
Applying socios.0002_alter_socio_options_alter_socio_activo_and_more... OK
```
0 errores.

---

## Tests

```
75 passed in 7.18s  (sin regresiones)
```

---

## Decisiones técnicas

1. **monto_usd placeholder en services**: `PrestamoPorSocio.save()` recalcula `monto_usd` correctamente desde `monto_principal` y `tasa_cambio`. Se pasa `monto_usd=Decimal('0.00')` al `create()` como placeholder porque el campo es `editable=False` y `save()` lo sobreescribe antes de persistir.

2. **MovimientoTesoreria usa TES como secuencia**: La guía indica `generar_numero('TES')` para `MovimientoTesoreria`. Esta misma secuencia la usan `TransferenciaCuentas`. Ambos modelos son independientes pero comparten el correlativo TES (según el fixture `secuencias.json` que solo define un registro TES). Si se requiere separación futura, hay que agregar una secuencia dedicada (ej: `MVT`).

3. **Warning RBAC en migrate**: Pre-existente. `FIXTURE_DIRS` no incluye `fixtures/` en settings → `loaddata('rbac')` falla durante `post_migrate`. No afecta la funcionalidad.

4. **Capital de Trabajo `capital_trabajo` alias**: Se mantiene el nombre `capital_trabajo` en el contexto para no romper la plantilla HTML existente (`reportes/capital_trabajo.html`). Se agrega `capital_neto` como nombre semántico nuevo.
