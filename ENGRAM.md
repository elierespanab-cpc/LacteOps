# ENGRAM — LacteOps
> Memoria compartida entre agentes y sub-agentes. Leer §0 y §1 ANTES de escribir una sola línea de código.

---

## §0. ESTADO ACTUAL — LEER PRIMERO

**Fecha última actualización:** 2026-04-05
**Sprint activo:** Sprint 7 completado — rama `sprint7`
**Tests:** 191/191 ✅ — `manage.py check` 0 issues
**Servidor:** Waitress, puerto 8000 (Windows service via NSSM)

### Qué está hecho (no repetir)
- ✅ NotaCredito: modelo, lógica emitir/anular, admin, impresión
- ✅ B6-14: `fecha_apertura` con `default=date.today, editable=False` + migración 0008
- ✅ B6-15: `ajustar_costo_producto()` en almacen/services.py + Admin Action
- ✅ Reportes: Ventas, Compras, CxC, CxP, Producción, Gastos, Capital Trabajo, Stock, Kardex, Tesorería
- ✅ Formato numérico español: `apps/core/templatetags/custom_filters.py` (usar en todos los templates)
- ✅ CxP: columnas Monto Pagado USD + Neto Pendiente USD
- ✅ Producción: subtotales por orden + total general
- ✅ Gastos: variables `gastos_display_n1` / `gastos_display_n2`, subtotales reales
- ✅ Capital Trabajo: desglose cuentas bancarias, préstamos socios corriente/no corriente
- ✅ ~~FieldError en Admin OrdenProduccion~~: resuelto agregando `fecha_apertura` estáticamente a `readonly_fields` [RESUELTO — Fase Bugfix, 2026-04-04]

- ✅ B7-01: FacturaVenta inicia en BORRADOR; emitir() acepta BORRADOR→EMITIDA [Sprint 7, 2026-04-05]
- ✅ B7-02: CuentaBancaria saldo_formateado con moneda en Admin [Sprint 7, 2026-04-05]
- ✅ B7-03: PrestamoPorSocio.get_monto_pagado() / get_saldo_neto() + columnas admin [Sprint 7, 2026-04-05]
- ✅ B7-06: CxC incluye COBRADA con saldo pendiente; fix encoding template [Sprint 7, 2026-04-05]
- ✅ B7-07: CxP alineación colspan corregida (12 columnas) [Sprint 7, 2026-04-05]
- ✅ B7-09: GastoServicio.save() calcula monto_usd automáticamente [Sprint 7, 2026-04-05]
- ✅ B7-11: Stock usa custom_filters (formato español) [Sprint 7, 2026-04-05]
- ✅ B7-12: Kardex migrado a base_reporte.html con sidebar [Sprint 7, 2026-04-05]
- ✅ B7-13: Tesorería migrada a base_reporte.html con sidebar [Sprint 7, 2026-04-05]

### Qué está pendiente para el próximo sprint
- [ ] Sprint 8: por definir con el usuario

### Archivos con restricciones activas (no modificar sin coordinación)
- `apps/ventas/models.py` — NotaCredito es estable; cualquier cambio afecta emitir/anular/saldo
- `apps/almacen/services.py` — PPM y ajuste de costo; cambios requieren tests
- `apps/core/templatetags/custom_filters.py` — usado por todos los templates de reportes
- `apps/reportes/views.py` — contexto de gastos usa `gastos_display_n1/n2`, no renombrar

---

## §1. REGLAS DE USO PARA AGENTES

> Estas reglas son obligatorias para cualquier agente (Claude, Gemini, Codex, GPT, etc.) que trabaje en este proyecto.

### 1.1 Antes de empezar cualquier tarea

1. **Leer §0 completo.** Si el ítem que te piden ya está en "Qué está hecho", detente y notifica al orquestador.
2. **Verificar contra el código real.** Una memoria puede estar desactualizada. Si §0 dice que algo está hecho, confirma que el archivo existe y el código está presente antes de asumir.
3. **Leer §4 (Trampas conocidas).** Evita repetir errores documentados.
4. **No crear archivos que ya existen.** Usa Glob o Grep para verificar antes de crear.

### 1.2 Durante la tarea

5. **Un solo archivo modificado a la vez** cuando hay riesgo de conflicto. No tocar `apps/ventas/models.py` y `apps/almacen/services.py` en la misma fase si otro agente está activo.
6. **Nunca float. Siempre `Decimal`.** Sin excepciones.
7. **`select_for_update()` + `transaction.atomic()`** en toda operación que modifique stock o saldo.
8. **`generar_numero()`** es el único punto de numeración. No auto-incrementar manualmente.
9. **`registrar_movimiento_caja()`** es el único punto para modificar `saldo_actual` de una cuenta.
10. **Los modelos `MovimientoInventario`, `MovimientoCaja`, `AuditLog` son INMUTABLES.** No implementar `.save()` ni `.delete()` que los modifiquen.
11. **Formato numérico en templates:** usar `{% load custom_filters %}` y los filtros `formato_moneda`, `formato_numero`, `formato_costo`, `formato_cantidad`. No usar `intcomma` de humanize para cifras monetarias.

### 1.3 Al terminar cada tarea

12. **Ejecutar `python manage.py check`** antes de declarar la tarea completa. Debe retornar 0 issues.
13. **Ejecutar `python -m pytest tests/ -x -q`** y verificar que no hay regresiones. El baseline es 183 tests en verde.
14. **Actualizar §0** de este ENGRAM: mover el ítem de "pendiente" a "hecho", agregar archivos modificados en §6.
15. **Registrar en §4** cualquier trampa nueva encontrada durante la tarea.

### 1.4 Reglas de escritura en este ENGRAM

16. **No borrar secciones existentes.** Solo agregar o marcar como `[RESUELTO]`.
17. **Fechas absolutas siempre.** No escribir "ayer" o "esta semana". Escribir `2026-04-04`.
18. **Al documentar un bug resuelto**, agregar `~~texto~~` al título y `[RESUELTO — Fase X, fecha]` al final.
19. **Al agregar una decisión técnica**, incluir el motivo. "Decidimos X porque Y" — no solo "Decidimos X".

---

## §2. STACK Y REGLAS ABSOLUTAS DE NEGOCIO

### Stack
- Python 3.11 / Django 4.2 / PostgreSQL 15
- django-jazzmin (admin UI — React descartado definitivamente)
- Waitress + NSSM (servicio Windows, puerto 8000)
- pytest + pytest-django
- Moneda funcional: USD. Dual USD/VES.

### Reglas de negocio irrompibles
| Regla | Detalle |
|-------|---------|
| NUNCA float | `DecimalField(18,6)` costos, `(18,2)` totales |
| Concurrencia | `select_for_update()` + `transaction.atomic()` en toda op que modifique stock/saldo |
| Inmutabilidad | `MovimientoInventario`, `MovimientoCaja`, `AuditLog`: no se modifican ni eliminan |
| Stock negativo | Lanza `StockInsuficienteError` |
| Saldo negativo | Lanza `SaldoInsuficienteError` |
| Numeración | Solo vía `generar_numero()` en `apps/core/services.py` |
| Saldo cuentas | Solo vía `registrar_movimiento_caja()` en `apps/bancos/services.py` |

### Ruta del proyecto
`C:\Users\elier\Documents\Desarollos\LacteOps`

### Comandos frecuentes
```bash
# Activar entorno
source venv/Scripts/activate

# Verificar integridad
python manage.py check

# Tests
python -m pytest tests/ -x -q --tb=short

# Backup BD (ruta completa necesaria en bash Windows)
"/c/Program Files/PostgreSQL/15/bin/pg_dump" -U lacteops_user -d lacteops_db -F c -f "backups/backup_$(date +%Y%m%d_%H%M%S).dump"
```

---

## §3. ARQUITECTURA DE APPS

### apps/core
- `AuditableModel` — base para todos los modelos transaccionales
- `AuditLog` — inmutable, registra cambios de estado
- `Secuencia` — numeración por tipo_documento (ver tabla en §5)
- `TasaCambio` — tasa BCV diaria
- `ConfiguracionEmpresa` — singleton
- `Notificacion` — alertas internas
- `CategoriaGasto` — jerárquica (padre/hijo); usar para gastos y tesorería
- `templatetags/custom_filters.py` — filtros de formato numérico (ver §4)

### apps/almacen
- `Producto` — `stock_actual` y `costo_promedio` son readonly (PPM via Kardex)
- `MovimientoInventario` — INMUTABLE. Kardex Promedio Ponderado Móvil
- `AjusteInventario` — estados: BORRADOR → APROBADO / ANULADO
- `CambioProducto` — flujo de aprobación para cambios en Producto
- Servicios: `registrar_entrada()`, `registrar_salida()`, `ajustar_costo_producto()`

### apps/ventas
- `FacturaVenta` — estados: EMITIDA → COBRADA / ANULADA. Auto VTA-NNNN
- `DetalleFacturaVenta` — `save()` recalcula `total` de cabecera automáticamente
- `Cobro` — `registrar()` hace entrada a caja + cálculo bimoneda
- `NotaCredito` — estados: BORRADOR → EMITIDA → ANULADA. Auto NC-NNNN
  - `emitir()`: devuelve stock (ENTRADA Kardex) + reduce saldo cliente
  - `anular()`: revierte entradas de stock + restaura saldo
- `FacturaVenta.get_saldo_pendiente()` descuenta cobros **y** NCs EMITIDAS

### apps/compras
- `FacturaCompra` — estados: RECIBIDA → APROBADA → ANULADA. Auto COM-NNNN
- `GastoServicio` — `fecha_emision` + `fecha_vencimiento`. `monto_usd` se calcula al guardar
- `Pago` — contra FacturaCompra APROBADA

### apps/produccion
- `OrdenProduccion` — estados: ABIERTA → CERRADA / ANULADA. Auto PRO-NNNN
  - `fecha_apertura`: Editable mientras la OP esté `ABIERTA`; readonly cuando `CERRADA`. (Override B6-14 por petición del usuario)
  - `cerrar()`: salidas MP + distribución costo por valor de mercado + entrada PT
  - `reabrir()`: solo Master/Admin; revierte movimientos
- `ConsumoOP` — materias primas consumidas
- `SalidaOrden` — productos terminados con `costo_asignado`

### apps/bancos
- `CuentaBancaria` — `moneda` (USD|VES), `saldo_actual` readonly
- `MovimientoCaja` — INMUTABLE. Tipos: ENTRADA|SALIDA|TRANSFERENCIA_ENTRADA|TRANSFERENCIA_SALIDA|REEXPRESION
- `TransferenciaCuentas` — estados: PENDIENTE → EJECUTADA / ANULADA. Secuencia 'TES'
- `MovimientoTesoreria` — INMUTABLE. Tipos: CARGO|ABONO. Secuencia 'TES' (compartida)
- `PeriodoReexpresado` — (anio, mes) unique

### apps/socios
- `PrestamoPorSocio` — estados: ACTIVO|CANCELADO|VENCIDO. Auto SOC-NNNN
- `Socio.get_saldo_bruto()` — suma monto_usd préstamos ACTIVOS
- `Socio.get_saldo_neto()` — bruto menos pagos

### apps/reportes
- Sin modelos reales. `ReporteLink` managed=False (solo para sidebar Jazzmin)
- Contexto de gastos: variables `gastos_display_n1` (nivel 1) y `gastos_display_n2` (nivel 2)
- Todos los templates usan `{% load custom_filters %}` para formato numérico

---

## §4. TRAMPAS CONOCIDAS

> Errores que ya ocurrieron. Leer antes de tocar cualquier archivo relacionado.

| # | Archivo/Área | Trampa | Solución correcta |
|---|-------------|--------|-------------------|
| T-01 | `apps/produccion/models.py` | `auto_now_add=True` impide que el campo aparezca en Admin aunque esté en `readonly_fields` | Usar `default=date.today, editable=False` — ya corregido |
| T-02 | Templates `gastos.html` / `capital_trabajo.html` | Variable `gastos_display` no existe en contexto | Usar `gastos_display_n1` (nivel 1) o `gastos_display_n2` (nivel 2) |
| T-03 | Cualquier template | `intcomma` de humanize da formato inglés (1,234.56) | Usar `formato_moneda`, `formato_numero` de `custom_filters` |
| T-04 | `apps/reportes/views.py` | `sum()` sobre generador vacío retorna `int(0)`, que no tiene `.quantize()` | Siempre `sum(generador, Decimal("0.00"))` |
| T-05 | Bash en Windows | `pg_dump` no está en PATH de bash | Usar ruta completa: `"/c/Program Files/PostgreSQL/15/bin/pg_dump"` |
| T-06 | Tests con templates Jazzmin | Renderizar templates Jazzmin en tests falla por `Missing staticfiles manifest` | Usar `RequestFactory` + `mock.patch('apps.reportes.views.render')` para capturar contexto sin renderizar |
| T-07 | `apps/ventas/models.py` | `sum()` sobre NCs sin el segundo argumento puede retornar 0 entero | `sum((nc.total for nc in ...), Decimal("0.00"))` |
| T-08 | `apps/reportes/templates/reportes/cxp.html` | `colspan` debe coincidir con número total de columnas | Actualmente 13 columnas — verificar al agregar/quitar columnas |
| T-09 | `admin.py` (cualquier modelo) | `FieldError: cannot be specified for model form` si el modelo tiene `editable=False` y el admin lo agrega a `fieldsets` pero lo oculta condicionalmente de `readonly_fields` | Todo campo `editable=False` que aparezca en `fieldsets` DEBE estar permanentemente garantizado en `readonly_fields` |
| T-10 | `apps/produccion/models.py` `cerrar()` | Validar `MovimientoInventario.filter(referencia=numero).exists()` bloquea el 2do cierre tras reabrir, porque los movimientos originales son inmutables | Comparar conteo de movimientos vs. reversiones: solo bloquear si `movs_cierre > 0 AND movs_cierre != movs_reversion` |
| T-11 | `apps/produccion/admin.py` `ConsumoOPInline` | Permitir editar `unidad_medida` en el inline causa error "Unidad incompatible" al cerrar si el usuario elige una unidad distinta a la del producto | `unidad_medida` debe ser readonly en el inline; `ConsumoOP.save()` siempre fuerza `unidad_medida_id` desde el producto |

---

## §5. SECUENCIAS DE NUMERACIÓN

| pk | tipo_documento | prefijo | dígitos | Usado por |
|----|----------------|---------|---------|-----------|
| 1  | VTA            | VTA-    | 4       | FacturaVenta |
| 2  | COM            | COM-    | 4       | FacturaCompra |
| 3  | INV            | INV-    | 4       | AjusteInventario |
| 4  | PRO            | PRO-    | 4       | OrdenProduccion |
| 5  | TES            | TES-    | 4       | TransferenciaCuentas + MovimientoTesoreria (compartida) |
| 6  | APC            | APC-    | 4       | (reservado) |
| 7  | SOC            | SOC-    | 4       | PrestamoPorSocio |
| 8  | NC             | NC-     | 4       | NotaCredito |

---

## §6. HISTORIAL DE CAMBIOS POR SESIÓN

### Sesión Sprint 7 — 2026-04-05 (Claude Code)
- **Issues Resueltos:** B7-01, B7-02, B7-03, B7-06, B7-07, B7-09, B7-11, B7-12, B7-13
- **Archivos Modificados:**
  - `apps/ventas/models.py` — BORRADOR state, emitir() acepta BORRADOR
  - `apps/ventas/migrations/0006_add_borrador_state.py` — migración
  - `apps/bancos/admin.py` — saldo_formateado en CuentaBancaria
  - `apps/socios/admin.py` — columnas pagado/saldo en PrestamoPorSocio
  - `apps/socios/models.py` — get_monto_pagado(), get_saldo_neto()
  - `apps/compras/models.py` — GastoServicio.save() calcula monto_usd
  - `apps/reportes/views.py` — CxC incluye estado COBRADA
  - `apps/reportes/templates/reportes/cxc.html` — fix encoding
  - `apps/reportes/templates/reportes/cxp.html` — fix alineación colspan
  - `apps/reportes/templates/reportes/stock.html` — custom_filters
  - `apps/reportes/templates/reportes/kardex.html` — CREADO (extiende base_reporte)
  - `apps/reportes/templates/reportes/tesoreria.html` — CREADO (extiende base_reporte)
  - `tests/test_sprint7.py` — CREADO (9 tests)
- **Resultado:** 191/191 ✅

### Sesión Sprint 6 — 2026-04-03 (múltiples agentes)

**Fase A-0 (Claude Code)**
- Rama `sprint6` creada desde `sprint4`
- `backups/backup_pre_sprint6.sql` — 1.3 MB
- `backups/lacteops_sprint6_pre.dump` — 261 KB
- `ENGRAM.md` — creado

**Fase A-1 (Gemini)**
- `apps/ventas/models.py` — NotaCredito + DetalleNotaCredito
- `apps/ventas/migrations/0002_...` — migración NotaCredito
- `apps/produccion/models.py` — B6-14: `auto_now_add` → `default=date.today, editable=False`
- `apps/produccion/migrations/0008_alter_ordenproduccion_fecha_apertura.py`
- `fixtures/secuencias.json` — secuencia NC pk=8
- `erp_lacteo/settings/base.py` — icono `ventas.notacredito`

**Fase A-2 (Claude Code)**
- `apps/ventas/models.py` — `NotaCredito.emitir/anular`, `DetalleNotaCredito.save()`, `FacturaVenta.get_saldo_pendiente()` descuenta NCs
- `apps/socios/models.py` — `Socio.get_saldo_bruto/neto()`
- `apps/almacen/services.py` — `ajustar_costo_producto()`

**Fase B-1 (Codex)**
- `apps/ventas/admin.py` — NotaCreditoAdmin con actions emitir/anular
- `apps/ventas/views_print.py` — `imprimir_nota_credito`
- `apps/ventas/urls.py` — ruta `/ventas/print/nota-credito/<pk>/`
- `templates/print/nota_credito.html`
- `templates/admin/print_change_form.html` — botón imprimir condicional
- `apps/socios/admin.py` — saldo bruto/neto visibles
- `apps/bancos/admin.py` — MovimientoCajaAdmin mejorado
- `apps/produccion/admin.py` — fieldsets con fecha_apertura/cierre
- `apps/almacen/admin.py` — action `ajustar_costo`
- `templates/admin/almacen/ajustar_costo.html`

**Fase B-2 (Claude Code)**
- `apps/reportes/views.py` — `kardex_view` + `tesoreria_view`
- `apps/reportes/urls.py` — rutas kardex/ y tesoreria/
- `erp_lacteo/settings/base.py` — Kardex y Tesorería en sidebar
- `templates/reportes/kardex.html` — CREADO
- `templates/reportes/tesoreria.html` — CREADO

**Fase C-1 (Codex)**
- `apps/reportes/views.py` — ventas/compras con monto_usd + estatus; cxc con cobrado/NC/neto; produccion con filtro producto
- `apps/reportes/templates/reportes/ventas.html` — subtotales por cliente, estatus
- `apps/reportes/templates/reportes/compras.html` — subtotales por proveedor, estatus
- `apps/reportes/templates/reportes/cxc.html` — columnas cobrado/NC/neto pendiente
- `apps/reportes/templates/reportes/produccion.html` — filtro por producto

**Fase C-2 (Claude Code)**
- `apps/reportes/views.py` — reporte_gastos con `gastos_display_n1/n2`; capital_trabajo con saldos USD correctos y préstamos socios; reporte_stock con categorias_data
- `templates/reportes/gastos.html` — CREADO (nivel 1 resumen / nivel 2 detalle)
- `templates/reportes/capital_trabajo.html` — CREADO (dos columnas activo/pasivo)
- `templates/reportes/stock.html` — CREADO (subtotales por categoría)

**Fase D-1 (Gemini)**
- `tests/test_sprint6_reportes.py` — CREADO (12 tests)
- `tests/test_sprint6_produccion.py` — CREADO (4 tests, B6-14)
- `tests/test_sprint6_ajuste_costo.py` — CREADO (6 tests, B6-15)
- `apps/reportes/views.py` — B6-16: `sum()` sobre lista vacía con `Decimal("0.00")`
- `tests/test_correcciones_sprint3.py` — fix staticfiles con override_settings
- **Resultado:** 168/168 ✅

### Sesión BugFixes Reportes — 2026-04-04 (Claude Code)

- `apps/core/templatetags/__init__.py` — CREADO
- `apps/core/templatetags/custom_filters.py` — CREADO (formato_numero, formato_moneda, formato_costo, formato_cantidad)
- `apps/reportes/views.py` — reporte_produccion agrega `total_general_mp` + `total_general_costo`
- `apps/reportes/templates/reportes/cxp.html` — columnas Monto Pagado + Neto Pendiente; `custom_filters`
- `apps/reportes/templates/reportes/produccion.html` — subtotales por orden + total general; `custom_filters`
- `apps/reportes/templates/reportes/gastos.html` — reescrito: variables correctas `gastos_display_n1/n2`; `custom_filters`
- `apps/reportes/templates/reportes/capital_trabajo.html` — reescrito: variables correctas; desglose cuentas; préstamos socios; `custom_filters`
- `apps/reportes/templates/reportes/ventas.html` — `intcomma` → `custom_filters`
- `apps/reportes/templates/reportes/compras.html` — `intcomma` → `custom_filters`
- `apps/reportes/templates/reportes/cxc.html` — `intcomma` → `custom_filters`
- **Resultado:** 183/183 ✅

### Sesión BugFixes Admin OP — 2026-04-04 (Antigravity)

- `apps/produccion/admin.py` — `fecha_apertura` es permanentemente `readonly_fields`, eliminado `get_readonly_fields` condicional.
- `tests/test_sprint6_1.py` — Actualizadas aserciones porque `fecha_apertura` ahora es inmutable de acuerdo con D-03.
- **Resultado:** 182/182 ✅ (test obsoleto borrado).

### Sesión Reversión Parcial D-03 — 2026-04-04 (Antigravity)

- **Requisito Modificado:** El usuario solicitó explícitamente que la `fecha_apertura` de la OrdenProduccion pueda ser editada "hasta que la orden sea cerrada".
- `apps/produccion/models.py` — Eliminado `editable=False` de `fecha_apertura`.
- `apps/produccion/migrations/0009_alter_ordenproduccion_fecha_apertura.py` — Generada y aplicada.
- `apps/produccion/admin.py` — Implementado `get_readonly_fields` para hacer `fecha_apertura` readonly *solo* si `obj.estado == 'CERRADA'`.
- `tests/test_sprint6_1.py` — Modificadas las aserciones con `unittest.mock.Mock` para contemplar edición condicional.
- **Resultado:** 182/182 ✅

### Sesión BugFixes OP Cálculos Web y Cierre — 2026-04-05 (Antigravity)

- **Issues Resueltos:**
  1. `costo_unitario` de ConsumoOP no se actualizaba al cambiar (ej. si Kardex cambia, o si el input es alterado en Borrador).
  2. Totales (`costo_total`, `kg_totales`, `rendimiento_real`) no se previsualizaban en el Admin antes del cierre, forzando un vuelo a ciegas.
  3. UI retornaba "Error inesperado" en `cerrar()` debido a divisiones por cero no atajadas `DivisionByZero` (`s.cantidad == 0` o `valor_total == 0` sin tratamiento `try/except`).
- **Archivos Modificados:**
  - `apps/produccion/models.py`: 
    - Agregado método `recalcular_totales()` a `OrdenProduccion`.
    - Agregado `save()` a `ConsumoOP` y `SalidaOrden` que invocan dinámicamente este recalculo permitiendo visualización en vivo del admin si el estado es `ABIERTA`.
    - Corrección atómica en `cerrar()` para prevenciones de División por cero con `Decimal('0.000000')`.
- **Resultado:** 182/182 ✅ Completado sin regresiones.

### Sesión BugFixes OP v2 — 2026-04-04 (Claude Code)

- **Issues Resueltos:**
  1. `ConsumoOP.save()` accedía a `self.orden` / `self.producto` asumiendo que estaban cargados en memoria — fallaba silenciosamente si Django solo tenía `orden_id`/`producto_id`. Corregido usando queries directas por `_id`.
  2. `costo_unitario` no reflejaba el Kardex actual porque leía la instancia cacheada. Corregido: ahora lee `costo_promedio` fresco desde BD en cada `save()` de previsualización.
  3. `cerrar()` no validaba `cantidad_consumida > 0` antes de `registrar_salida()`. Cantidad=0 lanzaba `ValueError` capturado como "Error inesperado". Corregido: `EstadoInvalidoError` explícito (hereda `LacteOpsError` → mensaje legible al usuario).
  4. `cerrar()` disparaba `recalcular_totales()` desde cada `save()` durante la transacción atómica. Corregido pasando `skip_recalcular=True` en todos los `save()` internos del cierre.
- **Archivos Modificados:**
  - `apps/produccion/models.py` — `ConsumoOP.save()`, `SalidaOrden.save()`, `cerrar()`
- **Resultado:** 182/182 ✅ Sin regresiones.

### Sesión BugFixes Rendimiento OP — 2026-04-04 (Claude Code)

- **Issue Resuelto:** `kg_totales_salida` y `rendimiento_real` siempre daban 0 porque usaban `peso_unitario_kg` (campo no cargado en la mayoría de productos). La lógica correcta para empresas lácteas es:
  - `kg_totales_salida` = suma directa de `SalidaOrden.cantidad` (todas las salidas están en Kg).
  - `rendimiento_real` = `kg_salida / litros_base` donde `litros_base` = suma de `cantidad_consumida` de consumos cuyo producto tiene `es_materia_prima_base=True`.
  - La unidad es configurable por receta via `Receta.unidad_rendimiento` (`L/Kg` o `Kg/L`).
- **Archivos Modificados:**
  - `apps/produccion/models.py` — nuevo método privado `_calcular_kg_y_rendimiento()` compartido entre `cerrar()` y `recalcular_totales()`. Eliminado uso de `peso_unitario_kg`.
- **Resultado:** 182/182 ✅ Sin regresiones. Test real: 1000 L base → 119.5 Kg salida → rendimiento 8.368201 L/Kg.

### Sesión BugFixes OP Reapertura y Unidad Consumo — 2026-04-04 (Claude Code)

- **Issues Resueltos:**
  1. `cerrar()` bloqueaba con "posible doble cierre" al intentar cerrar una OP reabierta, porque buscaba cualquier movimiento con `referencia=self.numero` sin considerar que `reabrir()` los compensa con `REV-{numero}`. Corregido: solo bloquea si `movs_cierre > 0 AND movs_cierre != movs_reversion`.
  2. Error "Unidad de consumo kg no coincide con unidad del producto g" al cerrar. El usuario podía seleccionar una unidad de medida distinta a la del producto en el inline. Corregido:
     - `ConsumoOP.save()` fuerza siempre `unidad_medida_id` desde el producto (un solo query que también trae `costo_promedio`).
     - Admin inline: `unidad_medida` reemplazada por campo readonly `unidad_medida_display` — el usuario la ve pero no puede cambiarla.
- **Archivos Modificados:**
  - `apps/produccion/models.py` — `cerrar()` (validación doble cierre), `ConsumoOP.save()` (forzar unidad desde producto)
  - `apps/produccion/admin.py` — `ConsumoOPInline`: `unidad_medida_display` readonly, eliminado select editable
- **Resultado:** 182/182 ✅ Sin regresiones.


---

## §7. DECISIONES TÉCNICAS

> Cada decisión incluye el motivo. No revertir sin leer el motivo primero.

| # | Decisión | Motivo | Fecha |
|---|----------|--------|-------|
| D-01 | NotaCredito vive en `apps/ventas` | Mismo módulo que FacturaVenta; acoplamiento intencional | 2026-04-03 |
| D-02 | Secuencia NC pk=8, prefijo 'NC-' | Evitar colisión con secuencias existentes 1-7 | 2026-04-03 |
| D-03 | `fecha_apertura`: `default=date.today` en OP | Parcialmente revertido (Bugfix): El usuario requiere edición mientras esté ABIERTA. Se maneja `readonly` vía admin en estado CERRADA. | 2026-04-04 |
| D-04 | `ajustar_costo_producto()` registra MovimientoInventario cantidad=0 | Deja traza auditable en Kardex sin afectar PPM | 2026-04-03 |
| D-05 | Categoría "Material Empaque" pk=2 no se crea en Sprint 6 | Ya existe en BD desde Sprint anterior | 2026-04-03 |
| D-06 | Tests de vistas con templates Jazzmin usan `mock.patch` sobre `render` | Evita error `Missing staticfiles manifest` sin requerir `collectstatic` en CI | 2026-04-03 |
| D-07 | Formato numérico: filtros propios en `custom_filters.py` en lugar de `intcomma` | `intcomma` usa formato inglés (coma millares, punto decimal); el sistema usa formato español (punto millares, coma decimal) | 2026-04-04 |
| D-08 | `gastos_display_n1` / `gastos_display_n2` como nombres de contexto en reporte_gastos | Permite dos niveles de detalle (resumen por padre / detalle por subcategoría) desde una sola vista | 2026-04-03 |

---

## §8. BACKUPS DISPONIBLES

| Archivo | Fecha | Tamaño | Notar |
|---------|-------|--------|-------|
| `backups/backup_pre_sprint6.sql` | 2026-04-03 | 1.3 MB | SQL puro, restaurable con psql |
| `backups/lacteops_sprint6_pre.dump` | 2026-04-03 | 261 KB | Formato custom pg_restore |

**Restaurar:**
```bash
# SQL
PGPASSWORD=postgres psql -U postgres -h localhost -d lacteops_db < backups/backup_pre_sprint6.sql
# Custom
PGPASSWORD=postgres "/c/Program Files/PostgreSQL/15/bin/pg_restore" -U postgres -h localhost -d lacteops_db --clean backups/lacteops_sprint6_pre.dump
```

---

## §9. URLS REGISTRADAS

| Nombre | URL | Vista |
|--------|-----|-------|
| `reportes:dashboard` | `/reportes/dashboard/` | dashboard |
| `reportes:ventas` | `/reportes/ventas/` | reporte_ventas |
| `reportes:cxc` | `/reportes/cxc/` | reporte_cxc |
| `reportes:compras` | `/reportes/compras/` | reporte_compras |
| `reportes:cxp` | `/reportes/cxp/` | reporte_cxp |
| `reportes:produccion` | `/reportes/produccion/` | reporte_produccion |
| `reportes:gastos` | `/reportes/gastos/` | reporte_gastos |
| `reportes:capital_trabajo` | `/reportes/capital_trabajo/` | reporte_capital_trabajo |
| `reportes:stock` | `/reportes/stock/` | reporte_stock |
| `reportes:kardex` | `/reportes/kardex/` | kardex_view |
| `reportes:tesoreria` | `/reportes/tesoreria/` | tesoreria_view |
| `ventas:imprimir_factura` | `/ventas/print/factura-venta/<pk>/` | — |
| `ventas:imprimir_nota_credito` | `/ventas/print/nota-credito/<pk>/` | — |

---

## §10. JAZZMIN

```
Sidebar: ventas → compras → produccion → almacen → bancos → socios → reportes → core → auth
hide_models: ["reportes.ReporteLink", "bancos.RespaldoBD"]
Icono NotaCredito: "ventas.notacredito": "fas fa-file-minus"
```
