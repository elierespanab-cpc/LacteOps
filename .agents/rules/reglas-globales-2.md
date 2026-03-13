---
trigger: always_on
---

---
trigger: always_on
---

# REGLAS GLOBALES — Parte 2: Arquitectura y Sprint History
**LacteOps ERP v3.2 — Marzo 2026**
Stack: Python 3.11 / Django 4.2 / PostgreSQL 15 | Moneda funcional: USD
Complementa: Parte 1 — Negocio y Datos

---

## 2.9 Arquitectura Técnica Base

- Tres archivos de settings: `base.py` (común), `development.py` (hereda base, SQLite, `DEBUG=True`), `production.py` (hereda base, PostgreSQL, `DEBUG=False`).
- `manage.py` apunta a `development` por defecto.
- Ninguna credencial va hardcodeada. `SECRET_KEY`, credenciales de BD y claves externas van en `.env` leído con `python-decouple`. El `.env` no se commitea.
- Estáticos servidos por **Whitenoise** (`whitenoise.middleware.WhiteNoiseMiddleware` inmediatamente después de `SecurityMiddleware`). `collectstatic` obligatorio antes de arrancar producción.
- Servidor de producción: **Waitress** registrado como servicio Windows con **NSSM**.

---

## 2.10 Logging

Configurado en `settings/base.py`. Desarrollo: consola, nivel `DEBUG`. Producción: archivo con `RotatingFileHandler`, nivel `INFO` para operaciones normales y `ERROR` para excepciones.

Los `services.py` usan `logger = logging.getLogger(__name__)`.

---

## 2.11 Excepciones Personalizadas

Definidas en `core/exceptions.py`, heredan de `django.core.exceptions.ValidationError`:

| Excepción | Cuándo se lanza |
|---|---|
| `StockInsuficienteError` | Salida de inventario que dejaría stock negativo |
| `EstadoInvalidoError` | Transición de estado no permitida; bloqueo de crédito; período ya reexpresado |
| `UnidadIncompatibleError` | Unidad de consumo distinta a la del producto en Orden de Producción |
| `PeriodoCerradoError` | Intento de registrar en un período con Soft/Hard Close activo |
| `SaldoInsuficienteError` | Salida de caja que dejaría saldo de CuentaBancaria negativo |

> **⚠** Todos los `raise` en `services.py` usan estas excepciones específicas, nunca `ValidationError` genérico.

---

## 2.12 Fixtures y Datos Maestros

- `fixtures/initial_data.json`: unidades de medida y medios de pago.
- `fixtures/secuencias.json`: series VTA, COM, INV, PRO, TES, APC, SOC.
- `fixtures/rbac.json`: 5 grupos con permisos. **Incluye permisos explícitos de vista para los 7 reportes operativos, asignados a grupos Master y Administrador.** Carga automática vía `post_migrate`.
- Migraciones de esquema y de datos (`RunPython`) van en archivos separados. Nunca mezclarlas.
- **Migraciones destructivas:** requieren `pg_dump` previo documentado en la guía del sprint. `RunPython` verifica que no existen registros incompatibles antes de ejecutar cambio de esquema.

---

## 2.13 Audit Trail

Modelo `AuditLog` en `core/models.py`. Campos: `usuario` (FK User), `fecha_hora` (auto), `ip_origen`, `modulo`, `accion` (CREAR/MODIFICAR/ELIMINAR/CAMBIO_ESTADO), `entidad`, `entidad_id`, `before_data` (JSONField), `after_data` (JSONField).

`AuditLog` no tiene FK en cascada que permitan borrar registros. `AuditableModel` sobreescribe `save()` y `delete()` para registrar automáticamente.

---

## 2.14 Tesorería y Cuentas Bancarias ★ v3.0

### CuentaBancaria
- Moneda nativa única (USD o VES). `saldo_actual`: `DecimalField(18,2)`.
- **Saldo negativo prohibido:** CHECK constraint en BD + `SaldoInsuficienteError` en Python.
- Cuentas con `activa=False` no reciben movimientos.

### MovimientoCaja
- **Inmutable post-creación.**
- Tipos válidos: `ENTRADA`, `SALIDA`, `TRANSFERENCIA_ENTRADA`, `TRANSFERENCIA_SALIDA`, `REEXPRESION`.
- `monto_usd` siempre se recalcula en lógica de negocio.

### Función `registrar_movimiento_caja()` — `apps/bancos/services.py`
Único punto de entrada para crear `MovimientoCaja`. Pasos obligatorios en orden:
1. Verificar cuenta activa.
2. Validar saldo no negativo para SALIDA.
3. Calcular `monto_usd`.
4. Crear `MovimientoCaja`.
5. Actualizar `cuenta.saldo_actual` vía `instance.save()`.

> **⚠ CRÍTICO:** Ningún código fuera de `registrar_movimiento_caja()` puede modificar directamente `CuentaBancaria.saldo_actual`.

---

## 2.15 Control de Crédito ★ v3.0

La verificación ocurre en `FacturaVenta.emitir()`, no en `save()`.
```
fecha_vencimiento = fecha_emision + timedelta(days=cliente.dias_credito)
```
**Factura vencida:** `estado == EMITIDA` AND `fecha_vencimiento < hoy` AND `saldo_pendiente > 0`.

| `tipo_control_credito` | Comportamiento |
|---|---|
| `BLOQUEO` | `EstadoInvalidoError` con lista de facturas vencidas. |
| `ADVERTENCIA` | `logger.warning()` con detalle y continúa. |

---

## 2.16 Reexpresión Mensual de Saldos en VES ★ v3.0

`ReexpresionMensual.ejecutar(tasa_cierre, fecha_cierre, usuario)` en `apps/bancos/services.py`.

**Para cada `CuentaBancaria` activa con `moneda == VES`:**
```
usd_antes     = saldo_actual / tasa_inicio_mes
usd_despues   = saldo_actual / tasa_cierre
variacion_usd = usd_despues − usd_antes
→ MovimientoCaja tipo REEXPRESION con variacion_usd
```

**Idempotente:** modelo `PeriodoReexpresado` con `unique_together(anio, mes)`. Si ya existe → `EstadoInvalidoError('Período ya reexpresado')`. Se crea al finalizar dentro del mismo `atomic()`.

---

## 2.19 RBAC ★ v3.1

Grupos estándar Django. No se crea modelo custom de roles. Ver §2.6 Parte 1 para tabla de permisos por grupo.

**Reportes:** las 7 vistas de `apps/reportes/` están protegidas con `@login_required`. El acceso se otorga en `rbac.json` explícitamente a grupos **Master** y **Administrador** mediante permiso de vista sobre el modelo dummy `ReporteLink`. Sin este permiso, el usuario recibe HTTP 403.

---

## 2.20 Valoración de Inventario en Reportes ★ v3.1

| Condición | Valor usado |
|---|---|
| `precio_venta` definido | `precio_venta` |
| `precio_venta is None` | Fallback silencioso a `costo_promedio` |

Aplica a Capital de Trabajo y cualquier reporte futuro que valore existencias.

---

## Sprint History — Deuda técnica conocida

| Sprint | Deuda | Estado |
|---|---|---|
| S1 | Tasa BCV manual | Resuelto en S3 |
| S2 | Aprobación dual ajustes con RBAC completo | Activo desde S2 |
| S2 | pg_dump no en PATH Windows | Pendiente — documentar en instalación S3 |
| S3 | Export Excel reportes (openpyxl) | Sprint 4 |
| S3 | Reportes gerenciales (Flujo Caja, Ejecución Presupuestaria) | Sprint 4 |
| S3 | Módulo Nómina | Sprint 5 |

---

## Disposiciones Finales

- Todas las modificaciones por `instance.save()`, nunca por `QuerySet.update()`.
- `python manage.py check → 0 issues` es requisito de aceptación en cada fase de cada sprint.
- Las reglas de este documento son permanentes. Las restricciones temporales viven solo en la guía del sprint.

---
*LacteOps ERP v3.2 — Parte 2 de 2*