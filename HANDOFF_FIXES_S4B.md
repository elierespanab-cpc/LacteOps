# HANDOFF — Fixes Post-Sprint 4 Bloque A

**Fecha:** 2026-03-15
**Rama:** main
**Ejecutor:** Claude Sonnet 4.6

---

## Archivos modificados

| Archivo | Fix aplicado |
|---------|-------------|
| `apps/ventas/admin.py` | FIX 1: `from apps.almacen.models import Producto` en bloque de imports |
| `apps/compras/admin.py` | FIX 2: `from apps.almacen.models import Producto` en bloque de imports |
| `apps/produccion/admin.py` | FIX 3: Action `reabrir_ordenes` + agregado a lista `actions` |
| `apps/produccion/models.py` | FIX 4: Guardia anti-doble-cierre en `cerrar()` con `MovimientoInventario` |

---

## Detalle de cada fix

### FIX 1 — ventas/admin.py
`DetalleFacturaVentaInline` y `DetalleListaInline` usaban `Producto` sin importarlo.
Se agregó `from apps.almacen.models import Producto` junto al resto de imports de modelos.

### FIX 2 — compras/admin.py
`DetalleFacturaCompraInline` usaba `Producto` sin importarlo.
Se agregó `from apps.almacen.models import Producto` junto al resto de imports de modelos.

### FIX 3 — produccion/admin.py
- `'reabrir_ordenes'` agregado a `OrdenProduccionAdmin.actions`.
- Método `reabrir_ordenes` implementado con `@admin.action`:
  - Valida permiso via `usuario_en_grupo(request.user, 'Master', 'Administrador')`.
  - Llama `obj.reabrir(request.user, 'Reapertura desde Admin')` por cada orden seleccionada.
  - Reporta éxitos y errores individuales via `message_user`.

### FIX 4 — produccion/models.py
Guardia anti-doble-cierre insertada en `OrdenProduccion.cerrar()` inmediatamente después
de la validación de estado:

```python
from apps.almacen.models import MovimientoInventario
movs_existentes = MovimientoInventario.objects.filter(
    referencia=self.numero
).exists()
if movs_existentes:
    raise EstadoInvalidoError(
        'Orden de Producción',
        self.estado,
        'ya tiene movimientos registrados — posible doble cierre'
    )
```

Previene que un segundo intento de `cerrar()` (OP en ABIERTA por fallo previo parcial)
genere movimientos de inventario duplicados.

---

## Resultado de verificaciones

```
python manage.py check  →  System check identified no issues (0 silenced)
pytest tests/ -q        →  119 passed in 14.42s
```

---

## Estado post-fixes

- `/admin/ventas/facturaventa/add/` — sin NameError (Producto importado)
- `/admin/compras/facturacompra/add/` — sin NameError (Producto importado)
- `OrdenProduccionAdmin` — action "Reabrir órdenes cerradas (Master/Admin)" disponible
- `OrdenProduccion.cerrar()` — idempotente: segundo intento lanza `EstadoInvalidoError`
