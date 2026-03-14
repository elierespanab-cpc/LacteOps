---
trigger: always_on
---

---
trigger: always_on
---

# REGLAS GLOBALES — Parte 2: Arquitectura y Sprint History
**LacteOps ERP v4.0 — Marzo 2026**
Stack: Python 3.11 / Django 4.2 / PostgreSQL 15 | Moneda funcional: USD
Complementa: Parte 1 — Negocio y Datos

---

## 2.9 Arquitectura Técnica Base

- Tres archivos de settings: `base.py` (común), `development.py`
  (hereda base, SQLite, `DEBUG=True`), `production.py` (hereda base,
  PostgreSQL, `DEBUG=False`).
- `manage.py` apunta a `development` por defecto.
- Ninguna credencial va hardcodeada. `SECRET_KEY`, credenciales de BD y
  claves externas van en `.env` leído con `python-decouple`. El `.env`
  no se commitea.
- Estáticos servidos por **Whitenoise**
  (`whitenoise.middleware.WhiteNoiseMiddleware` inmediatamente después
  de `SecurityMiddleware`). `collectstatic` obligatorio antes de
  arrancar producción.
- Servidor de producción: **Waitress** registrado como servicio Windows
  con **NSSM**.
- **`pg_dump` debe estar en PATH del sistema.** Agregar en instalación:
  `setx PATH "%PATH%;C:\Program Files\PostgreSQL\15\bin" /M`.
  ★ NUEVO v4.0

---

## 2.10 Logging

Configurado en `settings/base.py`. Desarrollo: consola, nivel `DEBUG`.
Producción: archivo con `RotatingFileHandler`, nivel `INFO` para
operaciones normales y `ERROR` para excepciones.

Los `services.py` y `analytics.py` usan
`logger = logging.getLogger(__name__)`.

---

## 2.11 Excepciones Personalizadas

Definidas en `core/exceptions.py`, heredan de
`django.core.exceptions.ValidationError`:

| Excepción | Cuándo se lanza |
|---|---|
| `StockInsuficienteError` | Salida de inventario que dejaría stock negativo |
| `EstadoInvalidoError` | Transición de estado no permitida; bloqueo de crédito; período ya reexpresado; sin tasa BCV al emitir |
| `UnidadIncompatibleError` | Unidad de consumo distinta a la del producto en Orden de Producción |
| `PeriodoCerradoError` | Intento de registrar en un período con Soft/Hard Close activo |
| `SaldoInsuficienteError` | Salida de caja que dejaría saldo de CuentaBancaria negativo |

> **⚠** Todos los `raise` en `services.py` usan estas excepciones
> específicas, nunca `ValidationError` genérico.

---

## 2.12 Fixtures y Datos Maestros

- `fixtures/initial_data.json`: unidades de medida y medios de pago.
- `fixtures/secuencias.json`: series VTA, COM, INV, PRO, TES, APC, SOC.
- `fixtures/rbac.json`: 5 grupos con permisos. Incluye permisos
  explícitos de vista para los 7 reportes operativos + dashboard,
  asignados a grupos Master y Administrador. Carga automática vía
  `post_migrate`.
- Migraciones de esquema y de datos (`RunPython`) van en archivos
  separados. Nunca mezclarlas.
- **Migraciones destructivas:** requieren `pg_dump` previo documentado
  en la guía del sprint. `RunPython` verifica que no existen registros
  incompatibles antes de ejecutar cambio de esquema.

---

## 2.13 Audit Trail

Modelo `AuditLog` en `core/models.py`. Campos: `usuario` (FK User),
`fecha_hora` (auto), `ip_origen`, `modulo`, `accion`
(CREAR/MODIFICAR/ELIMINAR/CAMBIO_ESTADO), `entidad`, `entidad_id`,
`before_data` (JSONField), `after_data` (JSONField).

`AuditLog` no tiene FK en cascada que permitan borrar registros.
`AuditableModel` sobreescribe `save()` y `delete()` para registrar
automáticamente.

---

## 2.14 Tesorería y Cuentas Bancarias ★ v3.0

### CuentaBancaria
- Moneda nativa única (USD o VES). `saldo_actual`: `DecimalField(18,2)`.
- **Saldo negativo prohibido:** CHECK constraint en BD +
  `SaldoInsuficienteError` en Python.
- Cuentas con `activa=False` no reciben movimientos.

### MovimientoCaja
- **Inmutable post-creación.**
- Tipos válidos: `ENTRADA`, `SALIDA`, `TRANSFERENCIA_ENTRADA`,
  `TRANSFERENCIA_SALIDA`, `REEXPRESION`.
- `monto_usd` siempre se recalcula en lógica de negocio.

### Función `registrar_movimiento_caja()` — `apps/bancos/services.py`
Único punto de entrada para crear `MovimientoCaja`. Pasos obligatorios
en orden:
1. Verificar cuenta activa.
2. Validar saldo no negativo para SALIDA.
3. Calcular `monto_usd`.
4. Crear `MovimientoCaja`.
5. Actualizar `cuenta.saldo_actual` vía `instance.save()`.

> **⚠ CRÍTICO:** Ningún código fuera de `registrar_movimiento_caja()`
> puede modificar directamente `CuentaBancaria.saldo_actual`.

---

## 2.15 Control de Crédito ★ v3.0

La verificación ocurre en `FacturaVenta.emitir()`, no en `save()`.
```
fecha_vencimiento = fecha_emision + timedelta(days=cliente.dias_credito)
```
**Factura vencida:** `estado == EMITIDA` AND
`fecha_vencimiento < hoy` AND `saldo_pendiente > 0`.

| `tipo_control_credito` | Comportamiento |
|---|---|
| `BLOQUEO` | `EstadoInvalidoError` con lista de facturas vencidas. |
| `ADVERTENCIA` | `logger.warning()` con detalle y continúa. |

---

## 2.16 Reexpresión Mensual de Saldos en VES ★ v3.0

`ReexpresionMensual.ejecutar(tasa_cierre, fecha_cierre, usuario)` en
`apps/bancos/services.py`.

**Para cada `CuentaBancaria` activa con `moneda == VES`:**
```
usd_antes     = saldo_actual / tasa_inicio_mes
usd_despues   = saldo_actual / tasa_cierre
variacion_usd = usd_despues − usd_antes
→ MovimientoCaja tipo REEXPRESION con variacion_usd
```

**Idempotente:** modelo `PeriodoReexpresado` con
`unique_together(anio, mes)`. Si ya existe →
`EstadoInvalidoError('Período ya reexpresado')`. Se crea al finalizar
dentro del mismo `atomic()`.

---

## 2.19 RBAC ★ v3.1 — Actualizado v4.0

Grupos estándar Django. No se crea modelo custom de roles. Ver §2.6
Parte 1 para tabla de permisos por grupo.

**Reportes:** las vistas de `apps/reportes/` (incluyendo `/dashboard/`)
están protegidas con `@login_required`. El acceso se otorga en
`rbac.json` explícitamente a grupos **Master** y **Administrador**
mediante permiso de vista sobre el modelo dummy `ReporteLink`. Sin este
permiso, el usuario recibe HTTP 403.

**Superusuario:** `is_superuser=True` bypasea `require_group` sin
necesidad de pertenecer a ningún grupo. ★ NUEVO v4.0

---

## 2.20 Valoración de Inventario en Reportes ★ v3.1

| Condición | Valor usado |
|---|---|
| `precio_venta` definido | `precio_venta` |
| `precio_venta is None` | Fallback silencioso a `costo_promedio` |

Aplica a Capital de Trabajo y cualquier reporte futuro que valore
existencias.

---

## 2.26 Score de Riesgo CxC ★ NUEVO v4.0

Índice `S ∈ [0, 100]`. Valor 100 = riesgo nulo. Valor 0 = default
probable. Implementado en `apps/reportes/analytics.py`.
```
S = (0.40 × Puntualidad) + (0.30 × Solvencia) + (0.30 × Tendencia)

── Puntualidad (w=40%) ──────────────────────────────────────────
ADD = promedio(días_retraso_post_vencimiento) en cobros del cliente
Puntualidad = clamp(100 − (ADD × 100/15), 0, 100)
Si ADD >= 15 → Puntualidad = 0

── Solvencia (w=30%) ────────────────────────────────────────────
ratio_utilizacion  = saldo_pendiente / limite_credito
Si limite_credito == 0 → ratio_utilizacion = 1.0
peso_mora_critica  = deuda_mayor_60d / saldo_total
Si saldo_total == 0 → peso_mora_critica = 0
Solvencia = clamp(100 × (1 − ratio_utilizacion) × (1 − peso_mora_critica), 0, 100)

── Tendencia (w=30%) ────────────────────────────────────────────
Regresión lineal simple sobre ADD mensual últimos 3 meses.
x = [0, 1, 2]  (mes_actual=0, hace_1_mes=1, hace_2_meses=2)
y = [ADD_m0, ADD_m1, ADD_m2]
slope = Σ((xi−x_mean)(yi−y_mean)) / Σ((xi−x_mean)²)
tendencia_raw = clamp(−slope / 5, −1, 1)
Tendencia = clamp(tendencia_raw × 100 + 50, 0, 100)
  slope=0  → Tendencia=50 (neutro)
  slope=+5 → Tendencia=0  (máx penalización)
  slope=−5 → Tendencia=100 (máx bonificación)
```

Todas las operaciones intermedias en `Decimal`. El `slope` usa `float`
solo internamente en la regresión; se convierte a `Decimal` antes de
entrar en la fórmula de `S`.

---

## 2.27 Notificaciones ★ NUEVO v4.0

Modelo `Notificacion` en `apps/core/models.py`. Campos principales:
`tipo`, `titulo`, `mensaje`, `entidad`, `entidad_id`,
`fecha_referencia`, `activa` (default True).
`unique_together = ('tipo', 'entidad', 'entidad_id')`.

- `activa=True` → visible en dashboard.
- Marca "leída" → `request.session['notif_leidas'].append(notif.id)`.
  Al cerrar sesión la session se destruye y las notificaciones
  reaparecen (comportamiento correcto, no es un bug).
- Generación siempre por `update_or_create` con la clave natural →
  sin duplicados aunque el command corra varias veces.
- **Desactivación automática:** stock repuesto → `activa=False`;
  tasa cargada → `activa=False`.
- Tipos: `CXC_VENCIENDO`, `STOCK_MINIMO`, `TASA_NO_CARGADA`,
  `PRESTAMO_VENCIENDO`.
- Management command `generar_notificaciones` corre diariamente a
  las 7am vía Task Scheduler.

---

## 2.28 Precio Ponderado Leche Cruda ★ NUEVO v4.0

KPI de dashboard. Implementado en `apps/reportes/analytics.py`.
```
precio_ponderado = Σ(entrada.costo_unitario × entrada.cantidad)
                 / Σ(entrada.cantidad)

Fuente: MovimientoInventario donde:
  tipo = 'ENTRADA'
  producto.es_materia_prima_base = True  (leche vaca Y búfala juntas)
  fecha >= hoy − 7 días
```

Si no hay entradas en 7 días → fallback a `costo_promedio` del
producto; retornar `sin_datos_recientes=True` para mostrar advertencia
en dashboard.

Campo `es_materia_prima_base = BooleanField(default=False)` en
`Producto`. Marcar para leche de vaca y leche de búfala.

---

## 2.29 Exportación Excel ★ NUEVO v4.0

- Librería: `openpyxl`. Función centralizada `exportar_excel(titulo,
  columnas, filas, filename=None)` en `apps/reportes/excel.py`.
- Los 7 reportes operativos + Capital de Trabajo tienen botón
  "Exportar Excel" que recarga la vista con `?exportar=1`.
- Formato: cabecera bold blanca sobre fondo `#1F3864`, ancho de columna
  18 por defecto.
- El archivo se descarga como respuesta HTTP directa, sin guardar en
  disco.

---

## 2.30 Respaldo de Base de Datos ★ NUEVO v4.0

- Vista `vista_respaldo_bd` accesible solo para `is_superuser`.
- Ejecuta `pg_dump` vía `subprocess.run()` con `PGPASSWORD` en entorno.
- Genera descarga `.sql` directa sin guardar permanentemente en disco.
- Registra cada intento en modelo `RespaldoBD` (inmutable, no hereda
  `AuditableModel`): `fecha`, `ejecutado_por`, `nombre_archivo`,
  `tamanio_bytes`, `exitoso`, `error_mensaje`.
- URL: `/admin/respaldo-bd/`. Enlace en `JAZZMIN_SETTINGS custom_links`.
- `pg_dump` debe estar en PATH (ver §2.9).

---

## 2.31 Aprobación Dual de Cambios en Producto ★ NUEVO v4.0

- Roles no-aprobadores (distintos de Master/Administrador/superusuario)
  no pueden guardar cambios directamente en `Producto`.
- Sus modificaciones generan un registro `CambioProducto` con estado
  `PENDIENTE`. El producto NO se modifica hasta aprobación.
- `CambioProducto`: campos `producto`, `campo`, `valor_anterior`
  (JSON), `valor_nuevo` (JSON), `propuesto_por`, `aprobado_por`,
  `estado` (PENDIENTE/APROBADO/RECHAZADO), `fecha_propuesta`.
- Aprobación vía action en `CambioProductoAdmin`. Solo Master,
  Administrador o superusuario pueden aprobar.

---

## Sprint History — Deuda técnica conocida

| Sprint | Deuda | Estado |
|---|---|---|
| S1 | Tasa BCV manual | Resuelto en S3 |
| S2 | Aprobación dual ajustes con RBAC completo | Activo desde S2 |
| S2 | pg_dump no en PATH Windows | Resuelto en S4 |
| S3 | Export Excel reportes (openpyxl) | Resuelto en S4 |
| S3 | Superusuario bloqueado por require_group | Resuelto en S4 |
| S3 | TasaCambio búsqueda hacia atrás (bug) | Resuelto en S4 |
| S3 | CategoriaGasto padres imputables (bug) | Resuelto en S4 |
| S4 | Flujo de Caja Proyectado / Ejecución Presupuestaria | Sprint 5 |
| S4 | Módulo Nómina | Sprint 5 (en evaluación) |
| S4 | Cloudflare Tunnel acceso externo | Sprint 5 |
| S4 | Integración contable exportación asientos | Sprint 5 |

---

## Disposiciones Finales

- Todas las modificaciones por `instance.save()`, nunca por
  `QuerySet.update()`.
- `python manage.py check → 0 issues` es requisito de aceptación en
  cada fase de cada sprint.
- Las reglas de este documento son permanentes. Las restricciones
  temporales viven solo en la guía del sprint.

---
*LacteOps ERP v4.0 — Parte 2 de 2*