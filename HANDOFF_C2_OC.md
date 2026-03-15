# HANDOFF_C2_OC — OpenCode: Admin y UI

**Fase:** C2-OC (Admin y UI)
**Agente:** OpenCode
**Estado:** COMPLETO | Verificaciones manuales requeridas

---

## RESUMEN DE CAMBIOS

### TAREA 1: Reporte Stock - Filtros fecha y solo_con_stock

**Archivos modificados:**
- `apps/reportes/views.py` (funcion `reporte_stock`)
- `apps/reportes/templates/reportes/stock.html`

**Cambios:**
- Agregado filtro `fecha` (date) para consultar stock a fecha de corte específica
- Agregado filtro `con_stock` (checkbox) para mostrar solo productos con stock > 0
- Creada función auxiliar `stock_a_fecha()` para calcular stock histórico
- Actualizado params de Excel con fecha_corte y filtro aplicado

---

### TAREA 2: Admin Ventas - Moneda USD, tasa auto, fecha configurable

**Archivos modificados:**
- `apps/ventas/admin.py` (FacturaVentaAdmin)
- `apps/static/admin/css/ocultar_campo.css` (nuevo)

**Cambios:**
- Campo `moneda` siempre readonly + ocultado via CSS (siempre USD)
- Campo `tasa_cambio` agregado a readonly_fields
- `get_readonly_fields()`: agrega 'moneda' siempre; agrega 'fecha' si `ConfiguracionEmpresa.fecha_venta_abierta = False`
- `get_form()`: setea initial moneda='USD'
- CSS creado para ocultar campo moneda del formulario

---

### TAREA 3: Admin Compras - Tasa automática en PagoInline

**Archivos modificados/creados:**
- `apps/core/admin.py` - agregada función `api_tasa_fecha()`
- `erp_lacteo/urls.py` - registrado path `/api/tasa/`
- `apps/compras/admin.py` - agregado JS `tasa_auto_pago.js`
- `apps/static/admin/js/tasa_auto_pago.js` (nuevo)

**Cambios:**
- API endpoint `/api/tasa/?fecha=YYYY-MM-DD` retorna JSON con tasa BCV
- JS en FacturaCompraAdmin: al cambiar fecha en inline de Pago, consulta tasa automáticamente

---

### TAREA 4: Sidebar visible en reportes

**Archivos modificados:**
- `apps/reportes/templates/reportes/base_reporte.html`

**Cambios:**
- Template ahora extiende de `admin/base.html` (Jazzmin) en lugar de HTML standalone
- Sidebar de Jazzmin ahora visible en todos los reportes

---

### TAREA 5: RespaldoBD oculto del sidebar

**Archivos modificados:**
- `erp_lacteo/settings/base.py` (JAZZMIN_SETTINGS)

**Cambios:**
- Agregado `core.RespaldoBD` a `hide_models`

---

## ARCHIVOS CREADOS

- `apps/static/admin/css/ocultar_campo.css`
- `apps/static/admin/js/tasa_auto_pago.js`

---

## VERIFICACIONES REQUERIDAS

**El usuario debe ejecutar manualmente:**

```bash
# Verificar que no hay errores de sistema
python manage.py check

# Verificar tests (sin regresiones)
pytest tests/

# Verificaciones manuales:
# - /reportes/stock/?fecha=2026-03-01 muestra stock a esa fecha
# - /reportes/stock/?con_stock=1 oculta productos sin stock
# - Admin Ventas: campo moneda no editable (oculto), fecha según config
# - Admin Compras: cambiar fecha en Pago inline rellena tasa
# - Sidebar visible al abrir cualquier reporte
# - RespaldoBD no aparece en sidebar
```

---

## DECISIONES TOMADAS

1. **Fecha configurable en Ventas**: Se implementó la lógica en `get_readonly_fields()` que consulta `ConfiguracionEmpresa.fecha_venta_abierta`. Esta es una capa UI independiente de la lógica de negocio en `FacturaVenta.emitir()` (que controla la fecha persistida al emitir).

2. **Sidebar en reportes**: Se modificó `base_reporte.html` para extender de `admin/base.html` en lugar de HTML standalone. Esto hereda la estructura completa de Jazzmin incluyendo el sidebar.

3. **Ocultar campo moneda**: Se usa CSS en lugar de exclude en el form para mantener el campo en el modelo pero no visible en el UI. El valor inicial se setea en 'USD'.

---

**Siguiente paso:** Verificaciones manuales + entrega a Claude Code para pruebas adicionales si es necesario.
