# HANDOFF — Fixes S4C

**Fecha:** 2026-03-15
**Rama:** main (autorizado por el usuario; mantenimiento post-sprint)

## Archivos modificados
- `erp_lacteo/urls.py`
- `erp_lacteo/settings/base.py`
- `apps/reportes/views.py`
- `apps/reportes/excel.py`
- `apps/reportes/urls.py`
- `apps/reportes/templates/reportes/stock.html`
- `apps/core/admin.py`

## Resumen de cambios
- Respaldo BD movido a `/respaldo-bd/` y link Jazzmin actualizado.
- `vista_respaldo_bd` redirige con `reverse('admin:index')`.
- Dashboard como índice del Admin con `custom_index` en Jazzmin.
- Excel con encabezado de empresa + fecha de emisión + parámetros.
- Nuevo reporte de Stock con exportación Excel y link en sidebar.
- URLs de reportes actualizadas para stock y raíz `/` redirige a dashboard.

## Verificaciones
- `python manage.py check`: no ejecutado (autorizado por el usuario).
- `pytest tests/`: no ejecutado (autorizado por el usuario).

## Observaciones
- Si se desea validar, ejecutar `python manage.py check` y `pytest tests/`.
