# HANDOFF_C2_CLA — Claude Code: Lógica de Negocio

**Fase:** C2-CLA (Lógica de Negocio Financiera)
**Agente:** Claude Code
**Fecha:** 2026-03-15
**Estado:** ✅ COMPLETO | 0 Issues | 119 Tests PASSED

---

## 1. RESUMEN DE CAMBIOS

### Prerequisito: `apps/core/services.py`
- **Nueva función `get_tasa_para_fecha(fecha)`**: busca la `TasaCambio` más reciente
  en o antes de la fecha dada; si no existe, devuelve la más próxima posterior.
  Retorna `None` si no hay ninguna tasa registrada. Usado por FIX 1.

---

### FIX 1 — `save_formset` bimoneda en Admin (Pago + Cobro)

#### `apps/compras/admin.py`
- Nuevos imports: `from datetime import date`, `from decimal import Decimal`,
  `from apps.core.services import get_tasa_para_fecha`
- Método `save_formset` añadido a `FacturaCompraAdmin`:
  - Al crear un `Pago` nuevo desde el inline:
    - Obtiene tasa BCV para la fecha del pago vía `get_tasa_para_fecha`.
    - Si moneda=VES y no hay tasa → mensaje de error, omite el pago.
    - Calcula `monto_usd` y `tasa_cambio` en Decimal estricto.
    - Si hay `cuenta_origen` → llama `registrar_movimiento_caja(tipo='SALIDA')`.
  - Para pagos existentes (no `_state.adding`): `obj.save()` directo.

#### `apps/ventas/admin.py`
- Nuevos imports: `from datetime import date`,
  `from apps.core.services import get_tasa_para_fecha`
- Método `save_formset` añadido a `FacturaVentaAdmin`:
  - Mismo patrón que Pago pero para `Cobro`:
    - Si moneda=VES sin tasa → error, omite el cobro.
    - Si hay `cuenta_destino` → `registrar_movimiento_caja(tipo='ENTRADA')`.

**Problema resuelto:** `monto_usd` quedaba en 0 al guardar Pagos/Cobros desde el
inline porque el Admin llama `save()` directo, omitiendo `registrar()`.

---

### FIX 2 — `get_saldo_pendiente()` en `FacturaCompra`

#### `apps/compras/models.py`
- Corregido método `get_saldo_pendiente()`:
  - **Antes:** `Sum('monto')` — sumaba el monto en moneda original (VES o USD),
    resultado incorrecto para facturas en VES.
  - **Después:** `sum(p.monto_usd for p in self.pagos.all() if p.monto_usd)` —
    suma solo montos convertidos a USD.
  - Retorna `max(Decimal('0'), total - pagado)` para evitar saldos negativos.

**Nota:** `reporte_cxp` ya usaba `annotate(Sum('pagos__monto_usd'))` correctamente
y fue dejado como estaba (patrón ORM más eficiente).

---

### FIX 3 — `recalcular_stock` en `apps/almacen/services.py`

- **Nueva función `recalcular_stock(producto)`**:
  - Itera todos los `MovimientoInventario` del producto en orden cronológico.
  - Aplica Promedio Ponderado Móvil completo: ENTRADAS recalculan `costo_prom`,
    SALIDAS solo decrementan stock (nunca negativo con `max(0, ...)`).
  - Persiste `stock_actual` (4 dec.) y `costo_promedio` (6 dec.) con
    `transaction.atomic()` + `select_for_update()`.
  - Retorna `{'stock': Decimal, 'costo_promedio': Decimal}`.
  - Útil para auditorías, correcciones post-migración e importaciones masivas.

---

### FIX 4 — `FacturaVenta.emitir()` respeta `fecha_venta_abierta`

#### `apps/ventas/models.py`
- Al inicio de `emitir()`, después de la validación de estado:
  ```python
  from apps.core.models import ConfiguracionEmpresa
  config = ConfiguracionEmpresa.objects.first()
  if config and not config.fecha_venta_abierta:
      self.fecha = date.today()
  ```
- `'fecha'` añadido a `update_fields` del `save()` posterior en FASE 1,
  garantizando que el cambio persiste en BD.
- **Comportamiento:**
  - `fecha_venta_abierta=True` → usuario controla la fecha (sin cambio).
  - `fecha_venta_abierta=False` (default) → `fecha` se fuerza a `date.today()`.
  - Sin `ConfiguracionEmpresa` (tests) → sin efecto, fecha intacta.

---

## 2. ARCHIVOS MODIFICADOS

| Archivo | Tipo de cambio |
|---------|---------------|
| `apps/core/services.py` | Nueva función `get_tasa_para_fecha` |
| `apps/compras/admin.py` | Imports + `save_formset` en `FacturaCompraAdmin` |
| `apps/ventas/admin.py` | Imports + `save_formset` en `FacturaVentaAdmin` |
| `apps/compras/models.py` | `get_saldo_pendiente()` usa `monto_usd`, previene negativo |
| `apps/ventas/models.py` | `emitir()` respeta `fecha_venta_abierta` |
| `apps/almacen/services.py` | Nueva función `recalcular_stock` (PPM completo) |

---

## 3. VERIFICACIÓN

```
python manage.py check  →  System check identified no issues (0 silenced)
pytest tests/ -v        →  119 passed in 36.29s (0 failed, 0 error)
```

---

## 4. CONVENCIONES RESPETADAS

- ✅ `Decimal` estricto en todos los cálculos. Zero floats.
- ✅ `transaction.atomic()` + `select_for_update()` en `recalcular_stock`.
- ✅ Ningún test modificado.
- ✅ Sin nuevas migraciones (solo lógica de negocio).
- ✅ `registrar_movimiento_caja` invocado solo si existe cuenta vinculada.

---

**Siguiente paso:** Fase C3 (UI/UX) puede iniciar. Los inlines de Pago y Cobro
en Admin ya calculan bimoneda correctamente y el saldo pendiente en CxP es real.
