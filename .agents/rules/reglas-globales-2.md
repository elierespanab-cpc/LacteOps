---
trigger: always_on
---

# Reglas Globales LacteOps ERP — v5.0 Parte 2
**Vigente desde:** Sprint 5  
**Reemplaza:** v4.0 Parte 2  
**Continúa de:** Parte 1 (leer Parte 1 primero)

---

## 11. TASA BCV — COMPORTAMIENTO COMPLETO

```
get_tasa_para_fecha(fecha_documento):
    → TasaCambio.objects.filter(fecha__gte=fecha_documento).order_by('fecha').first()
```

- Busca **hacia adelante** (fecha ≥ fecha del documento). El BCV publica hoy la tasa del próximo día hábil.
- En documentos VES: al seleccionar fecha → cargar tasa automáticamente. `tasa_cambio` es `editable=False` en UI.
- Si no existe tasa para la fecha → permitir guardar en BORRADOR con advertencia visible. Bloquear `emitir()`/`aprobar()`.
- Endpoint Admin para JS: `GET /api/tasa/?fecha=YYYY-MM-DD` → `{'tasa': '38.500000'}`.
- En Pago inline (Compras): cambiar fecha rellena `tasa_cambio` automáticamente vía JS.

---

## 12. CONFIGURACIÓN DE EMPRESA — ConfiguracionEmpresa

Singleton. Un solo registro en BD. Campos activos en v5.0:

| Campo | Tipo | Descripción |
|---|---|---|
| `nombre_empresa` | CharField | Cabecera de documentos |
| `rif` | CharField | RIF fiscal |
| `direccion` | TextField | Dirección para documentos |
| `logo` | ImageField | Logo para cabecera |
| `fecha_venta_abierta` | BooleanField (default=False) | Si True: usuario ingresa fecha en venta. Si False: `emitir()` sobreescribe con `date.today()` |

**Regla `fecha_venta_abierta`:**
- `False` (default): `emitir()` ignora la fecha asignada y usa `date.today()`.
- `True`: `emitir()` respeta la fecha asignada previamente en el formulario.

---

## 13. SCORE DE RIESGO CXC

**S ∈ [0, 100]. Valor 100 = riesgo nulo. Valor 0 = default probable.**

```
S = (0.40 × Puntualidad) + (0.30 × Solvencia) + (0.30 × Tendencia)
```

**Puntualidad (w=40%):**  
`ADD = promedio(días_retraso_post_vencimiento)` en pagos del cliente  
`Puntualidad = clamp(100 − (ADD × 100/15), 0, 100)`  
Si ADD ≥ 15 → Puntualidad = 0

**Solvencia (w=30%):**  
`ratio_utilizacion = saldo_pendiente / limite_credito`  
Si `limite_credito == 0` → `ratio_utilizacion = 1.0`  
`peso_mora_critica = deuda_mayor_60d / saldo_total`  
Si `saldo_total == 0` → `peso_mora_critica = 0`  
`Solvencia = clamp(100 × (1 − ratio_utilizacion) × (1 − peso_mora_critica), 0, 100)`

**Tendencia (w=30%) — regresión lineal sobre ADD mensual últimos 3 meses:**  
`x = [0, 1, 2]` (mes_actual=0, hace_1_mes=1, hace_2_meses=2)  
`y = [ADD_m0, ADD_m1, ADD_m2]`  
`slope = Σ((xi−x̄)(yi−ȳ)) / Σ((xi−x̄)²)`  
`tendencia_raw = clamp(−slope / 5, −1, 1)`  
`Tendencia = clamp(tendencia_raw × 100 + 50, 0, 100)`  
slope=0 → Tendencia=50 (neutro) · slope=+5 → 0 · slope=−5 → 100

---

## 14. PRECIO MEDIO PONDERADO LECHE CRUDA

```
precio_ponderado = Σ(entrada.costo_unitario × entrada.cantidad) / Σ(entrada.cantidad)
```

Fuente: `MovimientoInventario` donde `tipo='ENTRADA'`, `producto.es_materia_prima_base=True`, `fecha >= hoy − 7 días`.  
Leche vaca + leche búfala se unifican bajo el mismo flag.  
Si no hay entradas en 7 días → fallback a `costo_promedio` actual del producto; retornar `sin_datos_recientes=True`.

---

## 15. MÓDULO SOCIOS — PRÉSTAMOS DE CAPITAL

- `Socio` → `PrestamoPorSocio` (pasivo) → `PagoPrestamo`.
- Los préstamos aparecen en CxP y en Capital de Trabajo como pasivo.
- `PrestamoPorSocio` tiene voucher imprimible con doble firma (patrón HTML + `@media print`).
- El saldo pendiente de cada préstamo se calcula igual que CxP: `total − Σ(PagoPrestamo.monto_usd)`.

---

## 16. NOTIFICACIONES — PERSISTENCIA POR SESIÓN

- `Notificacion.activa=True` → visible en dashboard.
- Marca 'leída' → `request.session['notif_leidas'].append(notif.id)`.
- Al cerrar sesión → session destruida → notificaciones reaparecen (comportamiento correcto por diseño).
- Generación: `update_or_create` con `(tipo, entidad, entidad_id)` como clave natural → sin duplicados.
- Desactivación automática: stock repuesto → `activa=False`; tasa cargada → `activa=False`.
- Tipos: `CXC_VENCIENDO`, `STOCK_MINIMO`, `TASA_NO_CARGADA`, `PRESTAMO_VENCIENDO`.

---

## 17. REPORTES — PATRONES Y RESTRICCIONES

### 17.1 Renderizado
- **Todos** los reportes y documentos usan HTML + `@media print`. Sin generación de PDF en servidor.
- Los templates de reporte extienden `admin/base_site.html` o `admin/base.html` de Jazzmin para que el sidebar sea visible. No ocultar ni colapsar el sidebar al abrir un reporte.

### 17.2 Sidebar — dummy model pattern
Reportes se exponen en el sidebar de Jazzmin mediante modelos `managed=False`. No duplicar registros de `RespaldoBD` entre apps (`bancos` y `core`): registrar solo en `apps/core/admin.py`.

### 17.3 Reporte CxP
- Muestra `get_saldo_pendiente()` por factura, no el monto original.
- Excluye facturas con saldo ≤ 0.
- En pagos parciales VES: el saldo se descuenta por `Pago.monto_usd` (ya convertido a USD).

### 17.4 Reporte Stock
- Parámetros GET: `?fecha=YYYY-MM-DD` (stock calculado a esa fecha), `?con_stock=1` (ocultar productos sin stock).
- Sin parámetros: muestra stock actual de todos los productos.

### 17.5 Reporte Diario Operativo (RDO) — Reporte 8
- Cruza Ventas, Tesorería, Compras, Producción y Almacén.
- KPIs: rendimiento real vs teórico (BOM), balance de masa, flujo de caja neto diario.
- Alertas: inventario fantasma, merma anormal (% parametrizable), reconciliación comercial.
- Implementado en `apps/reportes/rdo.py`.

### 17.6 Exportación Excel
- Todos los reportes operativos + Capital de Trabajo son exportables con `openpyxl`.
- Botón de exportación en cada vista de reporte.

---

## 18. RBAC — GRUPOS Y PERMISOS

Grupos auto-cargados vía `post_migrate`. Roles mínimos:

| Grupo | Capacidades clave |
|---|---|
| Administrador | Todo, incluye aprobar listas de precio y reversar OP |
| Master | Igual que Administrador |
| Supervisor | Ver y emitir documentos; no puede aprobar listas de precio |
| Operario | Crear borradores, ver reportes asignados |

- Superusuario Django no es bloqueado por `require_group`: siempre ve todas las acciones, incluido `reabrir()` en OP.
- Los reportes aparecen en permisos de grupos relevantes (no solo superusuario).

---

## 19. INFRAESTRUCTURA Y DESPLIEGUE

| Componente | Detalle |
|---|---|
| WSGI server | Waitress |
| Servicio Windows | NSSM (instalado via winget) |
| Estáticos | Whitenoise |
| Acceso LAN | hostname `ELIER` |
| BD | PostgreSQL 15 |
| Respaldo | `pg_dump` descargable desde Admin (solo superusuario), log en `RespaldoBD` |
| Acceso externo | Cloudflare Tunnel (planificado Sprint 6) |

---

## 20. HANDOFF Y ENTREGABLES POR FASE

Cada fase termina con un archivo `HANDOFF_<FASE>.md` que documenta:
- Archivos modificados
- Migraciones generadas (nombres)
- Resultado de `python manage.py check` (debe ser 0 issues)
- Resultado de `pytest tests/ -v` (número de tests y estado)
- Cualquier decisión de diseño tomada durante la fase

La siguiente fase **no arranca** hasta leer el HANDOFF anterior y confirmar 0 issues + tests verdes.

---

## 21. TABLA DE VERSIONES DE REGLAS GLOBALES

| Versión | Sprint | Cambios principales |
|---|---|---|
| v1.0 | Sprint 1 | Reglas fundacionales, stack, bimoneda básica |
| v2.0 | Sprint 2 | Producción conjunta, listas de precio, RBAC, reportes HTML |
| v3.2 | Sprint 3 | Tesorería directa, socios, BCV automático, categorías gasto |
| v4.0 | Sprint 4 | Score riesgo CxC, dashboard, exportación Excel, notificaciones, respaldo BD |
| **v5.0** | **Sprint 5** | Regla de Oro Admin bimoneda (Pago/Cobro `monto_usd≠0`), `unique_together` FacturaCompra, `CASCADE` SalidaOrden, `recalcular_stock()` PPM, `saldo_pendiente` real en CxP, `fecha_venta_abierta` en ConfiguracionEmpresa, reporte Stock con filtros fecha y con_stock |

---

## 22. DEUDA TÉCNICA Y RESTRICCIONES FUTURAS

- **React:** descartado como Admin UI. Jazzmin es definitivo. React solo como frontend de planta en sprint futuro (posterior a Sprint 6).
- **PDF server-side:** no usar. Patrón HTML + `@media print` para todos los documentos.
- **Docker:** no usado en producción. Entorno es Windows + NSSM + Waitress.
- **Gerencial reports / budgets anuales:** diferidos más allá de Sprint 6.
- **Nómina básica:** en evaluación para Sprint 6.

---

*Fin Reglas Globales v5.0 — ambas partes deben cargarse juntas antes de cada fase de agente.*