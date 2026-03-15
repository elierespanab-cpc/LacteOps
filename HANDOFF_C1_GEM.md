# HANDOFF_C1_GEM — Gemini Flash: Modelos

**Fase:** C1-GEM (Modelado de Base de Datos)
**Agente:** Gemini Flash
**Estado:** ✅ COMPLETO | 0 Issues | 119 Tests PASSED

---

## 1. CAMBIOS EN MODELOS

### apps/compras/models.py
- **FacturaCompra**: Se eliminó `unique=True` del campo `numero`.
- **FacturaCompra**: Se agregó `unique_together = [('proveedor', 'numero')]` en la clase `Meta`.
  - *Razón:* Permite que distintos proveedores usen el mismo número de factura, pero garantiza unicidad por proveedor.

### apps/produccion/models.py
- **SalidaOrden**: Se cambió el comportamiento de eliminación de la FK `orden` de `PROTECT` a `CASCADE`.
  - *Razón:* Las salidas de orden son datos derivados de la Orden de Producción; al eliminar o reabrir una OP, sus salidas deben poder eliminarse automáticamente.

### apps/core/models.py
- **ConfiguracionEmpresa**: Se agregó el campo `fecha_venta_abierta` (BooleanField).
  - *Descripción:* Controla si el usuario puede editar la fecha en ventas o si el sistema usa la fecha actual por defecto.

---

## 2. MIGRACIONES GENERADAS

Se generaron y aplicaron las siguientes migraciones de esquema:
- `apps/compras/migrations/0006_alter_facturacompra_numero_and_more.py`
- `apps/core/migrations/0007_configuracionempresa_fecha_venta_abierta.py`
- `apps/produccion/migrations/0006_alter_salidaorden_orden.py`

---

## 3. VERIFICACIÓN

- **System Check:** `python manage.py check` → 0 issues.
- **Tests:** `pytest tests/` → 119 passed.
- **Integridad:** No se detectaron regresiones en la lógica de bimoneda ni cálculos de stock existentes.

---

**Siguiente paso:** Claude Code (Lógica de Negocio) y OpenCode (UI/UX) pueden iniciar sus respectivas fases.
