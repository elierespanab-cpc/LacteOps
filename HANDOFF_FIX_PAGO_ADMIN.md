# HANDOFF — Fix post-Sprint 5: PagoAdmin y CobroAdmin

**Fecha:** 2026-03-15
**Rama:** main
**Tests:** 132 passed, 0 failed

---

## Problema corregido

Pago y Cobro tienen dos puntos de entrada en el Admin:

| Punto de entrada | Estado antes | Estado ahora |
|---|---|---|
| Inline dentro de FacturaCompra/FacturaVenta | ✅ Correcto (save_formset Sprint 5) | ✅ Sin cambios |
| Formulario independiente PagoAdmin/CobroAdmin | ❌ monto_usd=0, sin tasa automática | ✅ Corregido |

Síntomas originales:
- Label del campo `monto` decía "Monto del Pago (USD)" / "Monto del Cobro (USD)" aunque la moneda fuera VES.
- Al guardar en VES desde formulario independiente → `monto_usd = 0.00`.
- La tasa no se cargaba automáticamente al cambiar la fecha en el formulario standalone.
- El saldo pendiente de la factura no se descontaba correctamente.

---

## Archivos modificados

### `apps/compras/models.py`
- `Pago.monto.verbose_name`: `"Monto del Pago (USD)"` → `"Monto"`
- No genera migración (verbose_name no afecta esquema de BD).

### `apps/ventas/models.py`
- `Cobro.monto.verbose_name`: `"Monto del Cobro (USD)"` → `"Monto"`
- No genera migración.

### `apps/compras/admin.py`
- `PagoAdmin`: añadido `save_model()` con lógica bimoneda idéntica a `save_formset`.
- `PagoAdmin.Media`: carga `tasa_auto_pago_standalone.js`.
- Captura `es_nuevo = obj._state.adding` **antes** de `super().save_model()` para evitar que el flag cambie a False tras el save.

### `apps/ventas/admin.py`
- `@admin.register(Cobro)` + `CobroAdmin`: **nuevo** — no existía registro standalone.
- `CobroAdmin`: `save_model()` con lógica bimoneda, tipo `ENTRADA`, `cuenta_destino`.
- `CobroAdmin.Media`: carga `tasa_auto_pago_standalone.js`.

### `apps/static/admin/js/tasa_auto_pago_standalone.js` (NUEVO)
El JS existente `tasa_auto_pago.js` buscaba `tasa_cambio` dentro del mismo `.form-row`
que `fecha` → en standalone cada campo está en su propio `.form-row` → falla silenciosamente.

El nuevo script accede directamente por ID (`id_fecha`, `id_tasa_cambio`, `id_moneda`):
- Cambia fecha → consulta `GET /api/tasa/?fecha=YYYY-MM-DD`.
- Si moneda == USD: fuerza `tasa = 1.000000` y pone readonly.
- Si moneda == VES y hay tasa: rellena y pone readonly.
- Si moneda == VES y no hay tasa: muestra advertencia visible en rojo.
- Al cargar formulario con fecha ya cargada: ejecuta automáticamente.

---

## Decisión de diseño: por qué no se usó `Pago.registrar()`

`Pago.registrar()` y `Cobro.registrar()` encapsulan la lógica de caja pero tienen
un déficit crítico: si no hay `cuenta_origen`/`cuenta_destino`, retornan sin
calcular `monto_usd`. Esto dejaría `monto_usd = 0` en pagos sin cuenta vinculada.

Se replicó el mismo patrón de `save_formset` (Sprint 5) en `save_model`, que:
1. Siempre calcula `monto_usd` independientemente de si hay cuenta bancaria.
2. Solo llama `registrar_movimiento_caja` si hay cuenta vinculada.

---

## Verificación manual recomendada

1. **Pago VES desde PagoAdmin standalone:**
   - Cambiar fecha → tasa se rellena automáticamente.
   - Seleccionar moneda VES → tasa BCV precargada.
   - Guardar → `monto_usd` calculado correctamente (≠ 0).
   - Label del campo: "Monto" (sin "(USD)").

2. **Cobro VES desde CobroAdmin standalone:** mismo comportamiento con tipo ENTRADA.

3. **Inline de FacturaCompra/FacturaVenta:** sin cambios — `save_formset` intacto.

4. **Sin tasa en BD:** mensaje de error claro, el registro NO se guarda.

---

## Tests en verde

```
132 passed in 14.77s
```

Tests relacionados con bimoneda que validan esta corrección:
- `tests/test_pago_bimoneda_admin.py` (3 tests)
- `tests/test_cobro_bimoneda_admin.py` (2 tests)
- `tests/test_correcciones_sprint3.py::test_pago_ves_monto_usd_correcto`
- `tests/test_correcciones_sprint3.py::test_cobro_ves_genera_movimiento_caja`
