# HANDOFF B2-CLA — Sprint 4 LacteOps

**Fecha:** 2026-03-13
**Agente:** Claude (B2-CLA — Lógica Financiera Crítica)
**Rama:** `claude/romantic-hodgkin`

---

## STATUS: OK
- **manage.py check**: 0 issues ✅
- **Prerequisitos**: HANDOFF_B1_GEM (0 issues) ✅ | HANDOFF_B1_COD (0 issues) ✅

---

## FIX 1 — require_group: superusuario siempre pasa

### Archivo modificado
- `apps/core/rbac.py`

### Cambio
- `require_group`: refactorizado para extraer `usuario = request.user` y aplicar el check defensivo `hasattr(usuario, 'is_superuser') and usuario.is_superuser` como primera línea de verificación.

---

## FIX 2 — Tasa automática en documentos VES

### Función nueva
- `apps/core/services.py` → `get_tasa_para_fecha(fecha)`: consulta `TasaCambio.objects.filter(fecha__gte=fecha).order_by('fecha').first()`. Retorna `None` si no hay tasa disponible.

### Documentos modificados

| Archivo | Función | Comportamiento |
|---|---|---|
| `apps/ventas/models.py` | `FacturaVenta.emitir()` | VES: auto-detecta tasa y levanta `EstadoInvalidoError` si no existe. USD: fuerza `tasa_cambio=1`. Persiste en `update_fields=['fecha_vencimiento', 'tasa_cambio']`. |
| `apps/ventas/models.py` | `Cobro.registrar()` | VES: auto-detecta tasa. USD: fuerza `tasa_cambio=1`. Persiste en `update_fields=['monto_usd', 'tasa_cambio']`. |
| `apps/compras/models.py` | `FacturaCompra.aprobar()` | VES: auto-detecta tasa. USD: fuerza `tasa_cambio=1`. Persiste en `update_fields=['estado', 'tasa_cambio']`. |
| `apps/compras/models.py` | `Pago.registrar()` | VES: auto-detecta tasa. USD: fuerza `tasa_cambio=1`. Persiste en `update_fields=['monto_usd', 'tasa_cambio']`. |
| `apps/compras/models.py` | `GastoServicio.pagar()` | VES: auto-detecta tasa (usa `self.fecha_emision`). USD: fuerza `tasa_cambio=1`. Persiste en `update_fields=['monto_usd', 'cuenta_pago', 'tasa_cambio', 'estado']`. |
| `apps/socios/models.py` | `PrestamoPorSocio.save()` | Solo en `_state.adding` y `moneda==VES`: auto-detecta tasa (usa `fecha_prestamo`). USD: fuerza `tasa_cambio=1`. |
| `apps/bancos/models.py` | `MovimientoTesoreria.save()` | Solo en `_state.adding` y `moneda==VES`: auto-detecta tasa (usa `self.fecha`). USD: fuerza `tasa_cambio=1`. |

**Regla común:** Documentos USD → `tasa_cambio = Decimal('1.000000')`, sin consulta a `TasaCambio`.

---

## TAREA 1 — apps/reportes/analytics.py (nuevo)

Funciones implementadas:
- `calcular_add_mes(cliente, anio, mes)` — Average Days Delinquent mensual.
- `calcular_slope_add(cliente)` — Regresión lineal simple sobre 3 meses de ADD.
- `calcular_score_riesgo(cliente)` — Score 0-100 ponderado: 40% Puntualidad, 30% Solvencia, 30% Tendencia.
- `calcular_precio_ponderado_leche()` — Precio ponderado de entradas de materia prima base últimos 7 días; fallback a stock actual.
- `calcular_cce()` — Ciclo de Conversión de Efectivo: DSO + DIO − DPO (ventana 90 días).
- `calcular_proyeccion_caja_7d()` — Proyección de caja a 7 días: saldo USD + cobros esperados − pagos a vencer − préstamos venciendo.

---

## TAREA 2 — management command generar_notificaciones (nuevo)

- `apps/core/management/commands/generar_notificaciones.py`
- Uso: `python manage.py generar_notificaciones`
- Tipos de notificación generados con `update_or_create` (idempotente):
  - `CXC_VENCIENDO` — Facturas de venta con vencimiento en los próximos 7 días.
  - `STOCK_MINIMO` — Productos con stock_actual < stock_minimo; desactiva si se recupera.
  - `TASA_NO_CARGADA` — Si no existe TasaCambio para hoy ni fechas futuras; desactiva si se carga.
  - `PRESTAMO_VENCIENDO` — Préstamos activos con vencimiento en los próximos 7 días.
