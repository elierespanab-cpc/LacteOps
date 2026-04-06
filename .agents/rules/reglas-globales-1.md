---
trigger: always_on
---

# Reglas Globales v5.0 — Delta Sprint 6
 
> **Instrucción:** Agregar las siguientes secciones al archivo `.agents/rules/reglas-globales.md` (Parte 1 o Parte 2 según corresponda). Las secciones 2.1–2.20 y las reglas de Sprint 3/4/5 se mantienen íntegras. Solo se agregan las nuevas.
 
---
 
## Sección 2.21 — Notas de Crédito por Devolución (Parte 1)
 
- **NotaCredito es una factura inversa.** Rebaja CxC de la factura origen y repone inventario.
- **Máquina de estados: BORRADOR → EMITIDA → [ANULADA].**
- Una NC solo puede emitirse contra una FacturaVenta en estado EMITIDA o COBRADA.
- La suma de cantidades devueltas (en todas las NCs de una factura) no puede exceder la cantidad facturada original por producto.
- Al emitir la NC: `registrar_entrada()` por cada detalle al **costo promedio vigente del producto** (no al costo original de la factura — el PPM ya fue afectado por transacciones posteriores).
- Al anular una NC emitida: `registrar_salida()` para revertir las entradas. Validar stock suficiente.
- **La NC no puede imprimirse ni emitirse en estado BORRADOR.** El botón de impresión y la action de emisión solo están disponibles cuando el documento está completo.
- **Serie de numeración independiente:** NTC-NNNN. Secuencia registrada en fixtures/secuencias.json.
- **Impacto en FacturaVenta.get_saldo_pendiente():** debe descontar NCs emitidas además de cobros:
  ```
  saldo = total - sum(cobros.monto_usd) - sum(notas_credito.filter(estado='EMITIDA').total)
  ```
 
## Sección 2.22 — Ajuste Manual de Costo de Producto (Parte 1)
 
- **costo_promedio sigue siendo readonly en el Admin.** Esto es correcto y protege la integridad del Kardex.
- Para corregir costos erróneos existe la función `ajustar_costo_producto()` en `apps/almacen/services.py`.
- El ajuste genera un `MovimientoInventario` con `tipo='ENTRADA'`, `cantidad=Decimal('0')` y `costo_unitario=nuevo_costo`. La cantidad cero marca que es un ajuste de costo puro, no una entrada física.
- El movimiento queda como evidencia auditable en el Kardex con referencia `AJC-{codigo_producto}`.
- **Solo Master y Administrador** pueden ejecutar el ajuste (controlado por Admin Action con formulario intermedio).
- El ajuste **no modifica stock_actual** — solo costo_promedio.
- `transaction.atomic()` + `select_for_update()` obligatorio.
 
## Sección 2.23 — OrdenProduccion: Fechas de Apertura y Cierre (Parte 1)
 
- **fecha_apertura** se asigna automáticamente al crear la OP (`default=date.today`). No es editable.
- **fecha_cierre** se asigna automáticamente al cerrar la OP (`self.fecha_cierre = date.today()` en `cerrar()`). No es editable.
- Ambas fechas deben ser visibles en el Admin como `readonly_fields` dentro de un `fieldset` explícito.
- **Nota técnica:** Si el campo usa `auto_now_add=True`, Django lo excluye del formulario del Admin incluso como readonly. La solución es usar `default=date.today` con `editable=False` en su lugar.
 
## Sección 2.24 — Reportes: Reglas de Presentación (Parte 2)
 
- **Todo reporte que agrupe debe mostrar subtotales por grupo y total general al pie.**
- **Todo reporte de cuentas (CxC, CxP) debe mostrar tres columnas:** Total, Pagado/Cobrado, Neto Pendiente.
- **Todo reporte con estatus de documento debe mostrarlo:** Cobrada/Pagada, Parcialmente Pendiente, Pendiente.
- **Reporte de Stock** agrupa por Categoría de producto (Materia Prima, Material de Empaque, Producto Terminado, etc.) con subtotales por categoría y total general.
- **Reporte de Producción** debe permitir filtrar por producto.
- **Reporte de Tesorería** consolida MovimientoCaja + MovimientoTesoreria en una vista única.
 
## Sección 2.25 — Vista de Kardex (Parte 2)
 
- La vista de Kardex (`/reportes/kardex/`) muestra MovimientoInventario con saldo acumulado calculado línea a línea usando PPM.
- Filtros: producto individual, categoría/grupo, rango de fechas.
- Si se selecciona un producto: detalle línea a línea con stock acumulado y costo promedio acumulado.
- Si se selecciona categoría: resumen agrupado por producto con subtotales.
- El cálculo PPM línea a línea es el mismo algoritmo de `recalcular_stock()` pero sin modificar el producto.
 
## Sección 2.26 — Saldo de Socio (Parte 2)
 
- `Socio.get_saldo_bruto()`: suma de monto_usd de préstamos en estado ACTIVO.
- `Socio.get_saldo_neto()`: bruto menos suma de pagos.monto_usd de préstamos ACTIVOS.
- Son métodos calculados, no campos almacenados. No requieren migración.
- Deben ser visibles en SocioAdmin como `readonly_fields` y `list_display`.
 
## Sección 2.27 — Coordinación por Engram (Parte 2)
 
- A partir del Sprint 6, la coordinación entre agentes se realiza mediante un archivo compartido `ENGRAM.md` en la raíz del proyecto.
- El Engram reemplaza los archivos HANDOFF_*.md de sprints anteriores.
- Protocolo: todo agente lee ENGRAM antes de iniciar, verifica dependencias, ejecuta su tarea, y actualiza ENGRAM al terminar.
- El Engram contiene: contexto del sistema, estado de fases, archivos modificados por fase, decisiones tomadas, y errores encontrados.
 
---
 
## Resumen de versiones de Reglas Globales
 
| Versión | Sprint | Secciones agregadas |
|---------|--------|---------------------|
| v1.0 | Sprint 0 | 2.1–2.7: Moneda, Inventario PPM, Unidades, Estados, Atomicidad, MovInventario readonly, Separación agentes |
| v2.0 | Sprint 0 v2 | 2.8–2.12: Settings por entorno, Variables .env, Logging, Excepciones, Fixtures, AuditLog |
| v3.1 | Sprint 2 | 2.17–2.20: Producción conjunta, Listas de precio, RBAC, Valoración inventario |
| v3.2 | Sprint 3 | Correcciones: Tesorería, Socios, CategoriaGasto, TasaCambio BCV |
| v4.0 | Sprint 4-5 | Bimoneda Admin, Unicidad factura compra, SalidaOrden CASCADE, Recálculo stock PPM |
| **v5.0** | **Sprint 6** | **2.21–2.27: NotaCredito, Ajuste costo, OP fechas, Reportes presentación, Kardex, Saldo socio, Engram** |
 