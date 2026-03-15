---
trigger: always_on
---

# Reglas Globales LacteOps ERP — v5.0 Parte 1
**Vigente desde:** Sprint 5  
**Reemplaza:** v4.0 Parte 1A + 1B  
**Stack:** Python 3.11 · Django 4.2 · PostgreSQL 15 · Jazzmin · Waitress · NSSM  
**Moneda funcional:** USD  
**Base de producción:** v0.4.1 — 119 tests en verde

---

## 1. IDENTIDAD DEL PROYECTO

LacteOps es un ERP agroindustrial on-premise para una planta de procesamiento lácteo venezolana. Opera en un PC Windows con Waitress + NSSM. El sistema es bimoneda (USD/VES). La moneda funcional es USD; el bolívar es moneda de transacción local. No se registran diferencias de cambio por transacción: solo se calcula reexpresión mensual comparando saldos VES a tasa inicio vs fin de mes.

**Módulos activos:** Almacén · Compras · Ventas · Producción · Tesorería · Reportes · Core · Bancos · Socios  
**UI Admin:** Jazzmin (definitivo). React reservado para frontend de planta en sprint futuro.  
**Despliegue:** Whitenoise para estáticos · LAN hostname `ELIER` · sin Docker.

---

## 2. PIPELINE DE AGENTES — ROLES Y FRONTERAS

| Agente | Responsabilidad exclusiva |
|---|---|
| **Gemini Flash** | Modelos (`models.py`), migraciones, esquema de BD |
| **Claude Code** | Lógica de negocio (`services.py`), Admin overrides financieros (`save_model`, `save_formset`), tests |
| **OpenCode** | Admin UI/UX (JS, inlines visuales, plantillas, sidebar, estáticos) |

**Regla absoluta:** Ningún agente toca los archivos del otro sin instrucción explícita. Una violación de frontera se reporta inmediatamente y se revierte.

**Secuencia de fases:** Gemini siempre ejecuta primero. Claude Code y OpenCode arrancan en paralelo **solo** después de `HANDOFF_GEM` con 0 issues y pytest verde.

---

## 3. REGLAS DE CÓDIGO — INVARIANTES ABSOLUTAS

### 3.1 Aritmética financiera
- **NUNCA usar `float` en cálculos financieros.** Toda operación monetaria usa `Decimal` de Python.
- Precisión estándar: `quantize(Decimal('0.01'))` para montos; `Decimal('0.000001')` para tasas de cambio y costos unitarios.
- Los campos monetarios en modelos son `DecimalField` con `max_digits` y `decimal_places` explícitos.
- En tests: toda aserción financiera compara `Decimal` exacto, nunca `float` ni `round()`.

### 3.2 Concurrencia e integridad
- Toda operación que modifique saldo monetario, stock o movimiento de caja se ejecuta dentro de `transaction.atomic()`.
- Usar `select_for_update()` sobre el objeto principal cuando haya riesgo de escritura concurrente (Producto, CuentaBancaria, Socio).
- El patrón de detección new/existing es `self._state.adding` (nunca `self.pk` para este propósito).

### 3.3 Migraciones
- Migraciones de **esquema** y migraciones de **datos** (`RunPython`) van en **archivos separados**.
- Ejecutar `pg_dump` antes de cualquier migración destructiva (eliminar campo, cambiar tipo, cambiar `unique`).
- `python manage.py check` debe dar 0 issues antes y después de cada fase.

### 3.4 Tests
- **No modificar tests existentes** para hacer pasar código nuevo. Si un test falla, corregir el código.
- Toda aserción sobre `monto_usd`, `costo_promedio`, `stock_actual` o `saldo_pendiente` usa `Decimal` exacto.
- Fixture loading requiere rutas relativas explícitas.

---

## 4. MODELO BIMONEDA — REGLAS DE ORO

### 4.1 Documentos con moneda VES
1. Al seleccionar fecha en un documento VES → cargar tasa BCV automáticamente (campo `tasa_cambio` `editable=False` en UI).
2. `get_tasa_para_fecha(fecha)` busca **hacia adelante**: `TasaCambio.objects.filter(fecha__gte=fecha).order_by('fecha').first()` (el BCV publica hoy la tasa que rige el próximo día hábil).
3. Si no existe tasa → guardar en BORRADOR con advertencia. En `emitir()`/`aprobar()`: `raise EstadoInvalidoError('Sin tasa BCV para fecha del documento.')`.
4. Documentos USD: `tasa_cambio = Decimal('1.000000')`, sin validación BCV.

### 4.2 Pagos y Cobros — Regla de Oro Admin
**⚠ El Admin NUNCA puede guardar un Pago o Cobro con `monto_usd = 0`.**  
Si `monto_usd` llega a cero, significa que la lógica de negocio no fue invocada.

**Patrón correcto en `save_formset` de `FacturaCompraAdmin` y `FacturaVentaAdmin`:**

```python
def save_formset(self, request, form, formset, change):
    instances = formset.save(commit=False)
    for obj in instances:
        if isinstance(obj, Pago) and obj._state.adding:
            tasa = get_tasa_para_fecha(obj.fecha or date.today())
            if obj.moneda == 'VES' and not tasa:
                messages.error(request, f'Sin tasa BCV para {obj.fecha}. Pago no guardado.')
                continue
            tasa_val = tasa.tasa if tasa else Decimal('1.000000')
            if obj.moneda == 'VES':
                obj.monto_usd = (obj.monto / tasa_val).quantize(Decimal('0.01'))
                obj.tasa_cambio = tasa_val
            else:
                obj.monto_usd = obj.monto
                obj.tasa_cambio = Decimal('1.000000')
            obj.save()
            # generar MovimientoCaja si hay cuenta_origen
        else:
            obj.save()
    formset.save_m2m()
```

El mismo patrón aplica para `Cobro` en `FacturaVentaAdmin`.

### 4.3 Diferencias de cambio
No se registran diferenciales por transacción. La reexpresión es mensual: comparar saldos VES a tasa inicio de mes vs tasa fin de mes.

### 4.4 Tasa histórica BCV
La automatización BCV usa el scraper externo de Elier (GitHub). Soporta fechas históricas. El endpoint y formato del API son provistos por Elier antes de cada sprint que lo requiera.

---

## 5. MOVIMIENTOCAJA — REGLAS DE GENERACIÓN

- Todo Pago (compras) y Cobro (ventas) con `cuenta_origen`/`cuenta_destino` genera un `MovimientoCaja` (o equivalente en `CuentaBancaria`) al momento de guardarse desde el Admin.
- Los movimientos de tesorería directa (sin documento fuente) también generan `MovimientoCaja`.
- `MovimientoCaja` es **inmutable** una vez creado: no se edita, solo se revierte con un movimiento compensatorio.
- Detección de nuevo registro: `self._state.adding`.

---

## 6. ESTADOS DE DOCUMENTOS Y REVERSIÓN

### 6.1 Ciclo de vida estándar
`BORRADOR → EMITIDO/APROBADO → CERRADO`  
Documentos cerrados no son editables desde el Admin sin acción explícita de reversión.

### 6.2 Órdenes de Producción
- `CERRADA`: no editable, afecta inventario de forma definitiva.
- `REABIERTA`: movimientos revertidos. Puede editarse y cerrarse de nuevo.
- Una OP reabierta y con movimientos revertidos puede **eliminarse**. `SalidaOrden` usa `on_delete=CASCADE` (no PROTECT): son datos derivados de la OP.

### 6.3 Numeración automática
Todos los documentos con número de secuencia usan numeración automática. El número lo asigna el sistema, no el usuario, excepto en `FacturaCompra` donde el número lo asigna el proveedor.

---

## 7. UNICIDAD DE DOCUMENTOS

| Documento | Regla de unicidad |
|---|---|
| `FacturaCompra.numero` | `unique_together = [('proveedor', 'numero')]` — el número es del proveedor, puede repetirse entre proveedores distintos |
| Demás documentos internos | `unique=True` global o secuencia automática del sistema |

**⚠ `FacturaCompra` no tiene `unique=True` a nivel de campo `numero`. Requiere `unique_together` en `Meta`.**

---

## 8. RECÁLCULO DE STOCK — ALGORITMO PPM

La función `recalcular_stock(producto)` en `apps/almacen/services.py`:

1. Lee **todos** los `MovimientoInventario` del producto ordenados por `fecha ASC, id ASC`.
2. Recalcula `stock_actual` y `costo_promedio` transacción a transacción usando Precio Promedio Móvil (PPM).
3. Guarda resultado en `producto.stock_actual` y `producto.costo_promedio` via `instance.save()`.
4. Se ejecuta dentro de `transaction.atomic()` con `select_for_update()` sobre el producto.
5. **Nunca modifica los `MovimientoInventario` existentes** — solo recalcula los campos del `Producto`.
6. `stock_actual` nunca queda negativo: `max(Decimal('0'), stock_calculado)`.
7. Es idempotente: dos llamadas consecutivas producen el mismo resultado.

**Algoritmo PPM en cada movimiento:**
- `ENTRADA`: `nuevo_costo_prom = (stock × costo_prom + cantidad × costo_unitario) / (stock + cantidad)`; `stock += cantidad`
- `SALIDA`: `stock -= cantidad` (costo_promedio no cambia)

---

## 9. SALDO PENDIENTE CXP/CXC

`FacturaCompra.get_saldo_pendiente()`:
```python
def get_saldo_pendiente(self):
    pagado = sum(p.monto_usd for p in self.pagos.all() if p.monto_usd) or Decimal('0')
    return max(Decimal('0'), self.total - pagado)
```

- El reporte CxP usa `get_saldo_pendiente()` para cada factura y **excluye** facturas con saldo ≤ 0.
- No mostrar el monto original de la factura como saldo si ya tiene pagos parciales.
- Equivalente para `FacturaVenta` en CxC.

---

## 10. CATEGORÍAS DE GASTO

- Categorías raíz (`padre=None`) son **solo agrupadores**: no imputables en documentos.
- Validación en `GastoServicio.save()`: si `categoria_gasto.padre is None` → `raise ValidationError(...)`.
- En reportes: `nivel_detalle=1` agrupa por padre; `nivel_detalle=2` muestra subcategorías.