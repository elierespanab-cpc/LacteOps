---
trigger: always_on
---

# REGLAS GLOBALES — Parte 1: Negocio y Datos
**LacteOps ERP v3.0 — Marzo 2026**
Stack: Python 3.11 / Django 4.2 / PostgreSQL 15 | Moneda funcional: USD
Continúa en: Parte 2 — Arquitectura y Sprint 1

---

## Preámbulo

Reglas que aplican a todos los agentes sin excepción. Ningún agente puede desviarse aunque considere que existe una solución más conveniente. Son el contrato de negocio del sistema.

La v3.0 incorpora las reglas permanentes del Sprint 1: bimoneda, tesorería, numeración automática y control de crédito. Las restricciones temporales (tasa BCV manual, aprobación dual pendiente, RBAC pendiente) viven únicamente en la guía del sprint correspondiente, no aquí.

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

**Diferencial cambiario:** NO se registra por transacción individual. Se reconoce exclusivamente en la Reexpresión Mensual (ver Parte 2, sección 2.16).

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

| Documento | Flujo de estados | Regla |
|---|---|---|
| Factura de Compra | RECIBIDA → APROBADA / ANULADA | ANULADA solo si no fue APROBADA |
| Factura de Venta | EMITIDA → COBRADA / ANULADA | Emisión ejecuta salida de inventario |
| Orden de Producción | ABIERTA → CERRADA / ANULADA | ANULADA solo desde ABIERTA |
| Ajuste de Inventario | BORRADOR → APROBADO / ANULADO | ANULADO solo desde BORRADOR |
| Gasto / Servicio | PENDIENTE → PAGADO / ANULADO | PAGADO asigna `cuenta_pago` |
| Transferencia | PENDIENTE → EJECUTADA / ANULADA | ANULADA genera movimientos inversos |
| Cobro / Pago | Inmutable post-creación | Sin flujo de estados |

Los cambios de estado se ejecutan mediante acciones del Admin que llaman a métodos de negocio (`emitir()`, `aprobar()`, `cerrar()`, `anular()`, `ejecutar()`). No se editan como campos de texto. Un documento cerrado o cobrado no puede modificarse ni anularse directamente.

---

## 2.5 Atomicidad de Operaciones

Toda operación que modifique stock o saldo de cuenta va dentro de `transaction.atomic()`. Si cualquier parte falla, todos los cambios se revierten.

Todo acceso a saldo o stock dentro de una transacción usa `select_for_update()` para prevenir condiciones de carrera.

> **⚠ CRÍTICO:** `select_for_update()` es obligatorio en cualquier lectura de `CuentaBancaria.saldo_actual` o `Producto.stock_actual` que preceda a una escritura dentro del mismo `atomic()`.

---

## 2.6 Segregación de Funciones (RBAC)

Sprint 0–1: autenticación estándar Django con superusuario. RBAC completo desde Sprint 2.

Aplica desde Sprint 0:
- `stock_actual` y `costo_promedio` de `Producto` son `readonly` en el Admin.
- `MovimientoInventario` y `MovimientoCaja` no son creables manualmente desde el Admin; solo los genera la lógica de negocio.

---

## 2.7 Separación de Responsabilidades entre Agentes

| Agente | Responsabilidad | Restricción |
|---|---|---|
| Gemini 3.1 Pro High | models.py, migraciones, fixtures | Sin lógica de negocio |
| Codex GPT 5.4 | Scaffolding, Admin, Jazzmin, estructura | Sin métodos de negocio; los deja como stubs |
| Claude Sonnet 4.6 | services.py, métodos de modelos, tests QA | Sin modificar esquema de BD directamente |

Orden: Gemini → Claude → Codex. Cada agente recibe los archivos del anterior como contexto adjunto.

---

## 2.8 Series de Numeración Automática

Formato: `PREFIJO-NNNN` con relleno de ceros (mínimo 4 dígitos). Modelo `Secuencia` en `apps/core/models.py`.

| Serie | Uso |
|---|---|
| VTA- | Facturas de Venta y CxC |
| COM- | Facturas de Compra y CxP |
| INV- | Ajustes de Inventario y conteos físicos |
| PRO- | Órdenes de Producción |
| TES- | Cobros y Pagos directos |
| APC- | Ajustes a Período Cerrado — única serie permitida post Soft/Hard Close |

**Reglas:**
- `generar_numero(tipo_documento)` en `apps/core/services.py` con `select_for_update()` dentro de `transaction.atomic()`.
- Campo `numero` en todos los modelos: `editable=False`, asignado en `save()` solo cuando `_state.adding == True`.
- Numeración correlativa y continua. Un número asignado nunca se reutiliza aunque el documento sea anulado.
- El documento anulado conserva su número con estado `ANULADO` visible.

---

## 2.17 Producción Conjunta ★ NUEVO v3.1

- `OrdenProduccion` siempre tiene una o más `SalidaOrden`. No existe FK directa a producto terminado.
- Una Orden sin al menos una `SalidaOrden` con `es_subproducto=False` no puede cerrarse → `EstadoInvalidoError`.
- **Fórmula de distribución de costo** para productos principales (`es_subproducto=False`):
```
valor_i          = salida_i.precio_referencia × salida_i.cantidad
valor_total      = Σ valor_i  (solo no-subproductos)
costo_asignado_i = costo_total × (valor_i / valor_total)
```

- **Residuo de redondeo:** el último producto en la iteración (el de mayor `valor_i`) absorbe la diferencia entre `costo_total` y la suma de los demás `costo_asignado`. Esto garantiza que `Σ costo_asignado == costo_total` de forma exacta, sin tolerancias.
- **Subproductos:** `costo_asignado = Decimal('0.000000')`. Entran al inventario con `costo_unitario = Decimal('0.000000')`.
- El cierre registra una `EntradaInventario` por cada `SalidaOrden` dentro del mismo `transaction.atomic()`.

---

## 2.18 Listas de Precio ★ NUEVO v3.1

- Toda `FacturaVenta` tiene una `ListaPrecio` asignada al emitirse. No existe facturación sin lista.
- `precio_unitario` en `DetalleFacturaVenta` es `editable=False`. Se asigna desde `DetalleLista.precio` al momento de emitir. Nunca se edita manualmente.
- Si un producto no tiene `DetalleLista` con `aprobado=True` en la lista seleccionada → `EstadoInvalidoError` indicando qué producto.
- Solo usuarios de grupo **Master** o **Administrador** pueden aprobar precios y crear nuevas listas.
- `Asistente de Ventas` solo puede seleccionar listas activas con todos sus precios aprobados.
- `precio_venta` en `Producto` es campo de referencia exclusivo para reportes (Capital de Trabajo). No interviene en facturación.

---

## Disposiciones Finales (aplican a todas las partes)

- Todas las modificaciones por `instance.save()`, nunca por `QuerySet.update()`.
- `python manage.py check → 0 issues` es requisito de aceptación en cada fase de cada sprint.
- Las reglas de este documento son permanentes. Las restricciones temporales de cada sprint viven solo en la guía del sprint.