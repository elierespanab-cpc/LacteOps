# HANDOFF_FIX_CASCADE — LacteOps ERP

## 1. Diagnóstico realizado

- **Settings de Producción:** Se identificó `erp_lacteo/settings/production.py` apuntando a PostgreSQL (`lacteops_db`).
- **Estado Inicial en BD:** La base de datos PostgreSQL local estaba vacía. Se procedió a inicializarla mediante `python manage.py migrate --settings=erp_lacteo.settings.production`.
- **Verificación de Constraints:** En una base de datos PostgreSQL recién migrada, Django aplica el `on_delete=CASCADE` correctamente (confdeltype='c'). Sin embargo, el error reportado en producción indica que en entornos previamente existentes el constraint puede haber quedado en `NO ACTION` (confdeltype='a').
- **Tests en SQLite:** Se confirmó que el problema de sintaxis en migraciones manuales afectaba la ejecución de tests en SQLite, por lo que se implementó una solución compatible con múltiples vendors.

## 2. Acciones tomadas

### 2.1 Respaldo de Seguridad
- Se generó un respaldo de la base de datos PostgreSQL antes de aplicar cambios estructurales manuales: `pre_fix_cascade.sql`.

### 2.2 Migración Correctiva
- Se creó la migración `apps/produccion/migrations/0007_fix_salidaorden_cascade.py`.
- **Lógica de la migración:**
  - Utiliza `RunPython` con verificación de vendor (`schema_editor.connection.vendor == 'postgresql'`).
  - Ejecuta SQL manual para forzar `ON DELETE CASCADE` en las llaves foráneas de `SalidaOrden.orden` y `ConsumoOP.orden`.
  - Los nombres de los constraints originales detectados para el DROP fueron:
    - `produccion_salidaord_orden_id_0c13fd9e_fk_produccio`
    - `produccion_consumoop_orden_id_5104b342_fk_produccio`
  - Se definieron nombres determinísticos para los nuevos constraints: `produccion_salidaorden_orden_id_fk` y `produccion_consumoop_orden_id_fk`.

### 2.3 Verificación de Integridad
- **Check de Django:** `python manage.py check --settings=erp_lacteo.settings.production` → 0 issues.
- **Pytest:** `python -m pytest tests/ -v` → 132 passed.

## 3. Archivos modificados/creados

- `apps/produccion/migrations/0007_fix_salidaorden_cascade.py` (Nuevo)

## 4. Resultado final con DB PostgreSQL

| Tabla | FK | Constraint Name | Tipo (deltype) |
|---|---|---|---|
| `produccion_salidaorden` | `orden_id` | `produccion_salidaorden_orden_id_fk` | **c (CASCADE)** |
| `produccion_consumoop` | `orden_id` | `produccion_consumoop_orden_id_fk` | **c (CASCADE)** |

Ahora es posible eliminar una `OrdenProduccion` y sus salidas y consumos asociados se eliminarán en cascada automáticamente tanto en Django como a nivel de base de datos PostgreSQL.
