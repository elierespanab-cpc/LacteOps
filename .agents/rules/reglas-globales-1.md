---
trigger: always_on
---

---
trigger: always_on
---

# REGLAS GLOBALES — Parte 1: Negocio y Datos
**LacteOps ERP v3.2 — Marzo 2026**
Stack: Python 3.11 / Django 4.2 / PostgreSQL 15 | Moneda funcional: USD
Continúa en: Parte 2 — Arquitectura y Sprint History

---

## Preámbulo

Reglas que aplican a todos los agentes sin excepción. Ningún agente puede desviarse aunque considere que existe una solución más conveniente. Son el contrato de negocio del sistema.

La v3.2 incorpora las reglas permanentes del Sprint 3: TasaCambio, CategoriaGasto, Socios/Préstamos, MovimientoTesoreria, permisos de reportes y orden del sidebar. Las restricciones temporales viven únicamente en la guía del sprint correspondiente.

---

## 2.1 Moneda y Tipos de Dato

La moneda funcional es USD. Todos los montos, costos, precios y totales se almacenan en USD.

- **DecimalField obligatorio:** 18,6 para cantidades y costos unitarios. 18,2 para totales de factura y saldos de cuenta.
- **FloatField absolutamente prohibido** en cualquier campo monetario o de cantidad.
- Todos los cálculos financieros en Python usan `decimal.Decimal` estricto, nunca `float`.

### Bimoneda USD / VES

Regla de normalización única e innegociable:
- `moneda == USD` → `tasa_cambio = Decimal('1.000000')`, `monto_usd = monto`.
- `moneda == VES` → `tasa_cambio > 0` obligatorio, `monto_usd = monto / tasa_cambio`.

Todo modelo transaccional con flujo de efectivo incluye tres campos obligatorios: `moneda` (USD/VES), `tasa_cambio` (Decimal 18,6), `monto_usd` (Decimal 18,2, `editable=False`, calculado en lógica de negocio).

**Diferencial cambiario:** NO se registra por transacción individual. Se reconoce exclusivamente en la Reexpresión Mensual (ver Parte 2, §2.16).

---

## 2.2 Inventario y Kardex

Método de valoración: **Promedio Ponderado Móvil**. Única fórmula permitida.
```
nuevo_costo_promedio = (valor_stock_existente + valor_entrada) / nueva_cantidad_total
```

Las salidas se valoran al costo promedio vigente y no lo modifican.

**Stock negativo absolutamente prohibido.** Nivel Python: `StockInsuficienteError` antes de ejecutar. Nivel BD: CHECK constraint en `stock_actual`. El error indica producto, stock disponible y cantidad requerida, sin ejecutar ninguna parte de la operación.

---

## 2.3 Unidades de Medida

Maestro configurable, no texto libre. FK al modelo `UnidadMedida`. Pre-cargado con: `kg`, `g`, `L`, `ml`, `unid`.

En Recetas y Consumos de Orden de Producción la unidad del consumo debe coincidir con la del producto. Si hay discrepancia, el cierre se bloquea con `UnidadIncompatibleError`.

---

## 2.4 Estados de Documentos y Transiciones

| Documento | Flujo | Regla |
|---|---|---|
| Factura de Compra | RECIBIDA → APROBADA / ANULADA | ANULADA solo si no fue APROBADA |
| Factura de Venta | EMITIDA → COBRADA / ANULADA | Emisión ejecuta salida de inventario |
| Orden de Producción | ABIERTA → CERRADA / ANULADA | CERRADA bloquea edición. Reapertura requiere Master/Administrador con motivo en AuditLog |
| Ajuste de Inventario | BORRADOR → APROBADO / ANULADO | ANULADO solo desde BORRADOR |
| Gasto / Servicio | PENDIENTE → PAGADO / ANULADO | PAGADO asigna `cuenta_pago` |
| Transferencia | PENDIENTE → EJECUTADA / ANULADA | ANULADA genera movimientos inversos |
| Préstamo de Socio | ACTIVO → CANCELADO / VENCIDO | CANCELADO cuando suma pagos >= monto_principal |

Los cambios de estado se ejecutan mediante métodos de negocio (`emitir()`, `aprobar()`, `cerrar()`, `anular()`, `ejecutar()`). No se editan como campos de texto.

---

## 2.5 Atomicidad de Operaciones

Toda operación que modifique stock o saldo de cuenta va dentro de `transaction.atomic()`. Si cualquier parte falla, todos los cambios se revierten.

Todo acceso a saldo o stock dentro de una transacción usa `select_for_update()` para prevenir condiciones de carrera.

> **⚠ CRÍTICO:** `select_for_update()` es obligatorio en cualquier lectura de `CuentaBancaria.saldo_actual` o `Producto.stock_actual` que preceda a una escritura dentro del mismo `atomic()`.

---

## 2.6 Segregación de Funciones (RBAC)

| Grupo | Permisos clave |
|---|---|
| Master | Acceso total. Aprueba precios, ajustes y reexpresión. Reabre órdenes cerradas. |
| Administrador | Igual que Master excepto gestión de usuarios y configuración técnica. |
| Jefe Producción | CRUD Órdenes de Producción, aprobación de ajustes bajo umbral. |
| Asistente Compras | CRUD Facturas de Compra y Gastos. Sin acceso a Ventas ni Tesorería. |
| Asistente Ventas | CRUD Facturas de Venta con lista de precios activa y aprobada. Sin Compras ni Tesorería. |

- Permisos cargados vía `fixtures/rbac.json`, aplicado en signal `post_migrate` de `apps/core/apps.py`.
- Decorador `require_group(*grupos)` en `apps/core/rbac.py`: verifica pertenencia → `PermissionDenied` si no cumple.
- **Los reportes operativos son vistas Django protegidas con `@login_required`. El acceso se concede explícitamente en `rbac.json` a los grupos Master y Administrador. Ningún otro grupo ve reportes por defecto.**
- **Umbral de aprobación dual:** `default=1000` USD. Ajustes por encima requieren Master o Administrador.

---

## 2.7 Separación de Responsabilidades entre Agentes

**Agentes disponibles Sprint 3:**

| Agente | IDE | Responsabilidad | Restricción |
|---|---|---|---|
| Gemini Flash 3 | Antigravity | Modelos simples sin lógica: TasaCambio, CategoriaGasto, Socio | Sin métodos de negocio. Sin migraciones destructivas. |
| Claude Sonnet 4.6 | Claude Code | Modelos complejos, services.py, correcciones, tests QA | Sin modificar esquema directamente |
| Codex GPT 5.4 | Antigravity | Admin, Jazzmin, scaffolding, print, Task Scheduler | Sin métodos de negocio |

**Handoff entre agentes:** cada agente escribe su entregable en un archivo `.md` o `.txt` en la raíz del proyecto con nombre `HANDOFF_<FASE>.md`. El agente siguiente lee ese archivo antes de iniciar. Ver guía del sprint para rutas exactas.

---

## 2.8 Series de Numeración Automática

Formato: `PREFIJO-NNNN` con relleno de ceros (mínimo 4 dígitos). Modelo `Secuencia` en `apps/core/models.py`.

| Serie | Uso |
|---|---|
| VTA- | Facturas de Venta |
| COM- | Facturas de Compra |
| INV- | Ajustes de Inventario |
| PRO- | Órdenes de Producción |
| TES- | Movimientos de Tesorería directos |
| APC- | Gastos y Servicios |
| SOC- | Préstamos de Socios ★ NUEVO v3.2 |

**Reglas:**
- `generar_numero(tipo_documento)` en `apps/core/services.py` con `select_for_update()` dentro de `transaction.atomic()`.
- Campo `numero` en todos los modelos: `editable=False`, asignado en `save()` solo cuando `_state.adding == True`.
- Número asignado nunca se reutiliza aunque el documento sea anulado.

---

## 2.17 Producción Conjunta ★ v3.1

- `OrdenProduccion` siempre tiene una o más `SalidaOrden`. No existe FK directa a producto terminado.
- Sin al menos una `SalidaOrden` con `es_subproducto=False` → `EstadoInvalidoError` al cerrar.
- **Fórmula de distribución de costo:**
```
valor_i          = salida_i.precio_referencia × salida_i.cantidad
valor_total      = Σ valor_i  (solo no-subproductos)
costo_asignado_i = costo_total × (valor_i / valor_total)
```
- **Residuo de redondeo:** el producto con mayor `valor_i` absorbe la diferencia. `Σ costo_asignado == costo_total` exacto.
- **Subproductos:** `costo_asignado = Decimal('0.000000')`.
- Al cerrar: calcular `kg_totales_salida` y `rendimiento_real = kg_totales_salida / materia_prima_kg`.

---

## 2.18 Listas de Precio ★ v3.1

- Toda `FacturaVenta` requiere `ListaPrecio` asignada al emitirse.
- `precio_unitario` en `DetalleFacturaVenta` es `editable=False`. Se asigna desde `DetalleLista.precio` al emitir.
- Producto sin `DetalleLista` con `aprobado=True` → `EstadoInvalidoError`.
- Solo Master o Administrador aprueban precios y crean listas.

---

## 2.21 TasaCambio ★ NUEVO v3.2

- Modelo `TasaCambio` en `apps/core/models.py`: `fecha` (DateField unique), `tasa` (Decimal 18,6), `fuente` (BCV_AUTO / BCV_MANUAL / USUARIO).
- **Ningún documento puede guardar `tasa_cambio` sin antes consultar `TasaCambio.objects.filter(fecha__lte=fecha_doc).order_by('-fecha').first()`.**
- Si no hay tasa: el formulario muestra la más reciente como sugerencia. El usuario puede aceptarla o corregirla.
- El scraper histórico (`importar_historico_bcv`) puebla la tabla desde el inicio del histórico del BCV.
- El management command `actualizar_tasa_bcv` corre diariamente a las 6am vía Windows Task Scheduler.
- Backfill de días sin publicación: se llena con la tasa del día hábil siguiente.

---

## 2.22 CategoriaGasto ★ NUEVO v3.2

- Árbol de dos niveles: categoría padre → subcategoría hija. FK self null=True.
- Campo `contexto`: FACTURA (para GastoServicio) o TESORERIA (para MovimientoTesoreria). No mezclable.
- `GastoServicio.categoria_gasto` es FK a `CategoriaGasto` (reemplaza CharField).
- Categorías por defecto FACTURA: Electricidad, Agua, Gas, Mantenimiento, Transporte, Honorarios, Otro.

---

## 2.23 Socios y Préstamos ★ NUEVO v3.2

- `Socio` es modelo independiente. No es `Proveedor`.
- `PrestamoPorSocio`: pasivo de la empresa. Genera `MovimientoCaja ENTRADA` al registrarse si hay cuenta destino.
- `PagoPrestamo`: genera `MovimientoCaja SALIDA` si hay cuenta origen.
- Capital de Trabajo: préstamo es **pasivo corriente** si `fecha_vencimiento <= hoy + 365 días`, **no corriente** si mayor o si `None`.
- CxP incluye préstamos de socios en aging con los mismos buckets 0-30, 31-60, 61-90, +90 días.

---

## 2.24 MovimientoTesoreria ★ NUEVO v3.2

- Documento de origen para cargos/abonos directos sin factura.
- **Siempre genera un `MovimientoCaja`** en la cuenta seleccionada dentro del mismo `transaction.atomic()`.
- **Inmutable post-creación.** Mismo patrón que `MovimientoCaja`.
- `categoria` FK a `CategoriaGasto` con `contexto == TESORERIA` obligatorio.
- Genera voucher imprimible. Afecta saldo de cuenta y aparece en Capital de Trabajo.

---

## 2.25 Sidebar Jazzmin — Orden Canónico ★ NUEVO v3.2

El sidebar debe respetar este orden en `JAZZMIN_SETTINGS['order_with_respect_to']`:
```
ventas → compras → produccion → almacen → bancos → socios → reportes → core → auth
```
Las secciones deben estar colapsadas por defecto (`navigation_expanded: False`).
El modelo dummy `ReporteLink` nunca es visible en el sidebar (`has_module_perms` retorna False).

---

## Disposiciones Finales

- Todas las modificaciones por `instance.save()`, nunca por `QuerySet.update()`.
- `python manage.py check → 0 issues` es requisito de aceptación en cada fase de cada sprint.
- Las reglas de este documento son permanentes. Las restricciones temporales viven solo en la guía del sprint.