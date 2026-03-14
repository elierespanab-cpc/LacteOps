# HANDOFF B1-GEM — Sprint 3 LacteOps

**Fecha:** 2026-03-13
**Agente:** Gemini (Modeling)
**Rama:** `sprint3`

---

## STATUS: OK
- **manage.py check**: 0 issues ✅
- **pytest**: 96 tests passed ✅

---

## Modelos Creados / Modificados

### 1. Apps/Core
- **Notificacion**: Nuevo modelo para alertas del sistema (CxC, Stock, Tasa BCV, Préstamos).
  - Campos: `tipo`, `titulo`, `mensaje`, `entidad`, `entidad_id`, `fecha_referencia`, `activa`.
  - Restricción: `unique_together` para evitar duplicados del mismo evento.

### 2. Apps/Almacen
- **Producto**: Se agregaron campos de control de inventario y KPI:
  - `stock_minimo`, `stock_maximo`: Para alertas de reposición.
  - `es_materia_prima_base`: Flag para identificar leches (vaca/búfala) en el precio ponderado del dashboard.
- **CambioProducto**: Nuevo modelo para el flujo de aprobación dual de modificaciones en productos.
  - Campos: `producto`, `campo`, `valor_anterior`, `valor_nuevo`, `propuesto_por`, `aprobado_por`, `estado`, `motivo_rechazo`.

### 3. Apps/Bancos
- **RespaldoBD**: Nuevo modelo (no auditable) para el log inmutable de copias de seguridad.
  - Campos: `fecha`, `ejecutado_por`, `nombre_archivo`, `tamanio_bytes`, `exitoso`, `error_mensaje`.

### 4. Apps/Ventas
- **DetalleLista**: Se modificó el `related_name` del campo `producto` a `'precios_en_tarifas'` para mejorar la legibilidad en consultas inversas.

---

## Migraciones Generadas y Aplicadas

| App | Archivo | Descripción |
|---|---|---|
| **core** | `0006_notificacion.py` | Creación del modelo de notificaciones. |
| **almacen** | `0005_producto_..._cambioproducto.py` | Nuevos campos en Producto y modelo de aprobación dual. |
| **bancos** | `0004_respaldobd.py` | Histórico de respaldos de base de datos. |
| **ventas** | `0004_alter_detallelista_producto.py` | Cambio de related_name en DetalleLista. |

---

## Decisiones Técnicas
- El modelo `RespaldoBD` no hereda de `AuditableModel` por ser en sí mismo un log inmutable de sistema, evitando recursividad o ruido en el AuditLog.
- Se ha verificado que las modificaciones no rompen la integridad de los 96 tests existentes.
