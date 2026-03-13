# HANDOFF Fase A-1 — Sprint 3 LacteOps

**Fecha:** 2026-03-13
**Agente:** Claude Code
**Rama:** `sprint3`
**Estado:** ✅ COMPLETO — 75 tests en verde, 0 issues en `manage.py check`

---

## Correcciones aplicadas

### B2 — Bloquear OrdenProduccion cerrada + reabrir()
**Archivo:** `apps/produccion/models.py`
- `OrdenProduccion.save()`: consulta el estado actual en DB (no `self.estado`) para bloquear ediciones sobre OPs ya cerradas. Evita el problema circular porque `cerrar()` termina la escritura antes de persistir.
- Nuevo método `reabrir(usuario, motivo)`: requiere grupo Master o Administrador (o superuser). Revierte los `MovimientoInventario` generados por la OP y cambia estado a ABIERTA via `.update()` para no disparar el bloqueo de `save()`. Registra `AuditLog`.

### B3 — Fix CxP con pagos parciales
**Archivo:** `apps/reportes/views.py`
- `reporte_cxp()`: cambiado de `estado='RECIBIDA'` a `estado='APROBADA'`. Ahora usa `annotate + Coalesce(Sum('pagos__monto_usd'), ...)` para calcular el saldo real incluyendo pagos parciales. Devuelve solo facturas con `saldo > 0`.
- **Nota:** `Pago` no tiene campo `estado`, por lo tanto se eliminó el `filter=~Q(pagos__estado='ANULADO')` que causaba `FieldError`.

### B4 — Fix decimales Capital de Trabajo
**Archivo:** `apps/reportes/views.py`
- `reporte_capital_trabajo()`: helper interno `q(v)` aplica `quantize(Decimal('0.01'), ROUND_HALF_UP)` a todos los subtotales antes de acumularlos.
- Tasa VES/USD obtenida del último `PeriodoReexpresado` (no hardcodeada).
- CxP Compras usa el mismo patrón annotate que B3.

### B5+B6 — Bimoneda en Pago y Cobro
**Archivos:** `apps/compras/models.py`, `apps/ventas/models.py`

`Pago.registrar()` y `Cobro.registrar()`:
- Cálculo explícito de `monto_usd` (sin `convertir_a_usd`):
  - VES con tasa > 0: `monto_usd = monto / tasa` (quantize `0.01`)
  - USD o VES sin tasa: `monto_usd = monto`, `tasa = 1.000000`
- Todo dentro de `transaction.atomic()` con `select_for_update()` en la cuenta bancaria.
- `GastoServicio.pagar()`: misma lógica bimoneda aplicada.

### B7 — Numeración automática
**Archivos:** `apps/ventas/models.py`, `apps/compras/models.py`, `apps/produccion/models.py` (ya hecho en sesión anterior)
- `FacturaVenta.save()`: genera `VTA-XXXX` si `_state.adding` y sin número.
- `FacturaCompra.save()`: genera `COM-XXXX` en mismas condiciones.
- `GastoServicio.save()`: genera `APC-XXXX` en mismas condiciones.
- `OrdenProduccion.save()`: ya tenía `PRO-XXXX` (aplicado en sesión previa).
- `AjusteInventario(INV)` y `TransferenciaCuentas(TES)`: ya tenían numeración (Sprint 2).

### B8 — Unidad de rendimiento y métricas de OP
**Archivo:** `apps/produccion/models.py`
- `Receta`: nuevo campo `unidad_rendimiento = CharField(max_length=20, default='L/Kg')`.
- `OrdenProduccion`: nuevos campos `kg_totales_salida (18,4, editable=False)` y `rendimiento_real (18,6, editable=False)`.
- `cerrar()`: al finalizar, calcula `kg_totales_salida` sumando kg de salidas, y `rendimiento_real = kg_salida / kg_mp` (si mp_kg > 0).

### B9 — Permisos reportes RBAC
**Archivos:** `apps/reportes/views.py`, `apps/reportes/admin.py`, `apps/core/rbac.py`
- `views.py`: helper `_check_reporte_perm(request)` añadido a las 7 vistas de reportes. Lanza `PermissionDenied` si el usuario no es superuser ni tiene `reportes.view_reportelink`.
- `admin.py`: `ReporteLinkAdmin.has_module_perms()` ahora retorna `True` si el usuario tiene `view_reportelink` (antes siempre `False`). Añadida `has_view_permission()` con la misma lógica.
- `rbac.py`: `setup_groups()` asigna el permiso `view_reportelink` a los grupos **Master** y **Administrador** (con manejo de `Permission.DoesNotExist` para primera ejecución pre-migración).

---

## Migraciones creadas

| Migración | App | Descripción |
|-----------|-----|-------------|
| `0005_ordenproduccion_kg_totales_salida_and_more.py` | `produccion` | Campos B8: `kg_totales_salida`, `rendimiento_real`, `unidad_rendimiento` |
| `0001_initial.py` | `reportes` | Crea `ReporteLink` (managed=False) → genera permiso `view_reportelink` |

Ambas migraciones aplicadas con `migrate` en entorno development (SQLite).

---

## Resultado de manage.py check

```
System check identified no issues (0 silenced).
```

---

## Tests

```
75 passed in 7.14s
```

- `tests/test_capital_trabajo.py`: fixture `user_viewer` actualizado para incluir permiso `view_reportelink` (adaptación a B9).
- Todos los tests anteriores de Sprint 2 siguen en verde.

---

## Decisiones técnicas

1. **B3 filter eliminado**: `Pago` no tiene campo `estado`, por lo que `~Q(pagos__estado='ANULADO')` causaba `FieldError`. Se sumaron todos los pagos directamente.
2. **B2 circular save**: El bloqueo en `OrdenProduccion.save()` consulta el DB state (`OrdenProduccion.objects.filter(pk=self.pk).values_list('estado'...`), no `self.estado`, para que `cerrar()` pueda hacer su propio `save()` sin ser bloqueado (el DB aún muestra ABIERTA cuando `cerrar()` ejecuta el save final).
3. **B9 test adaptation**: El test `user_viewer` en `test_capital_trabajo.py` fue actualizado para asignar `view_reportelink` al usuario de prueba.
4. **Warning RBAC en migrate**: El warning `No fixture named 'rbac' found` durante `migrate` es pre-existente; ocurre porque `FIXTURE_DIRS` no incluye `fixtures/` explícitamente en el settings. No afecta la funcionalidad.

---

## Archivos modificados

- `apps/produccion/models.py` — B2, B7(PRO), B8
- `apps/reportes/views.py` — B3, B4, B9
- `apps/reportes/admin.py` — B9
- `apps/core/rbac.py` — B9
- `apps/compras/models.py` — B5+B6(Pago), B7(COM, APC)
- `apps/ventas/models.py` — B5+B6(Cobro), B7(VTA)
- `tests/test_capital_trabajo.py` — adaptación B9 (permiso en fixture)
- `apps/produccion/migrations/0005_ordenproduccion_kg_totales_salida_and_more.py` — NUEVO
- `apps/reportes/migrations/0001_initial.py` — NUEVO

---

## Próximos pasos (Fase A-2 en adelante)

- Implementar tests nuevos para B2 (`reabrir()`), B5+B6 (bimoneda), B7 (numeración), B8 (rendimiento_real) hasta alcanzar la meta de ~105 tests.
- Revisar integración de `view_reportelink` en Jazzmin custom_links.
- Validar flujo completo en servidor de desarrollo (puerto 8000).
