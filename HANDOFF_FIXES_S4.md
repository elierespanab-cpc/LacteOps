# HANDOFF_FIXES_S4 — Sprint 4 LacteOps

**Fecha:** 2026-03-13
**Agente:** Gemini (Modeling)
**Rama:** `sprint4`

---

## Cambios Realizados

| Archivo | Cambio |
|---------|--------|
| `apps/core/rbac.py` | Se añadió la función `usuario_en_grupo()` como helper funcional. |
| `apps/reportes/views.py` | Reemplazada definición local de `_usuario_en_grupo` por import de `core.rbac`. |
| `apps/almacen/admin.py` | Reemplazada definición local de `_usuario_en_grupo` por import de `core.rbac`. Actualizadas todas las llamadas. |
| `apps/ventas/models.py` | `DetalleLista.save()`: Ahora resetea `aprobado=False` si el precio cambia (con bloque try/except). |
| `apps/compras/models.py` | `GastoServicio.save()`: Verificada/asegurada la validación que bloquea el uso de categorías padre. |

---

## Verificaciones

- **Grep Check**: Se confirmó que no existen definiciones ni usos del antiguo `_usuario_en_grupo` en la carpeta `apps/`.
- **Issues**: No se realizaron cambios a nivel de esquema (sin migraciones).
- **Terminal Note**: Debido a restricciones de seguridad en el entorno de ejecución del agente, no fue posible ejecutar `manage.py check` ni `pytest` directamente desde esta instancia. Se recomienda al usuario ejecutar:
  ```powershell
  python manage.py check
  pytest tests/
  ```
  para confirmar el estado de los 119 tests mencionados.

---
**STATUS:** Fixes aplicados. Pendiente validación final por el usuario vía terminal.
