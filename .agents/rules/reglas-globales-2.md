---
trigger: always_on
---

# REGLAS GLOBALES — Parte 2: Arquitectura y Sprint 1
**LacteOps ERP v3.1 — Marzo 2026**
Stack: Python 3.11 / Django 4.2 / PostgreSQL 15 | Moneda funcional: USD
Complementa: Parte 1 — Negocio y Datos

---

## 2.9 Arquitectura Técnica Base

- Tres archivos de settings: `base.py` (común), `development.py` (hereda base, SQLite, `DEBUG=True`), `production.py` (hereda base, PostgreSQL, `DEBUG=False`).
- `manage.py` apunta a `development` por defecto.
- Ninguna credencial va hardcodeada. `SECRET_KEY`, credenciales de BD y claves externas van en `.env` en la raíz, leído con `python-decouple`. El `.env` no se commitea (en `.gitignore` desde el inicio).

---

## 2.10 Logging

Configurado en `settings/base.py`. Desarrollo: consola, nivel `DEBUG`. Producción: archivo con `RotatingFileHandler`, nivel `INFO` para operaciones normales y `ERROR` para excepciones.

Los `services.py` usan `logger = logging.getLogger(__name__)` y registran `INFO` al completar operaciones críticas y `ERROR` al capturar excepciones inesperadas.

---

## 2.11 Excepciones Personalizadas

Definidas en `core/exceptions.py`, heredan de `django.core.exceptions.ValidationError`:

| Excepción | Cuándo se lanza |
|---|---|
| `StockInsuficienteError` | Salida de inventario que dejaría stock negativo |
| `EstadoInvalidoError` | Transición de estado no permitida; también en bloqueo de crédito |
| `UnidadIncompatibleError` | Unidad de consumo distinta a la del producto en Orden de Producción |
| `PeriodoCerradoError` | Intento de registrar en un período con Soft/Hard Close activo |
| `SaldoInsuficienteError` | Salida de caja que dejaría saldo de CuentaBancaria negativo |

> **⚠** Todos los `raise` en `services.py` usan estas excepciones específicas, nunca `ValidationError` genérico.

---

## 2.12 Fixtures y Datos Maestros

- `fixtures/initial_data.json`: unidades de medida (kg, g, L, ml, unid) y medios de pago. Carga: `python manage.py loaddata initial_data`.
- `fixtures/secuencias.json`: 6 secuencias activas (VTA, COM, INV, PRO, TES, APC). Carga: `python manage.py loaddata secuencias`.
- `fixtures/rbac.json`: 5 grupos con sus permisos (Master, Administrador, Jefe Producción, Asistente Compras, Asistente Ventas). Carga automática vía signal `post_migrate` en `apps/core/apps.py`. También ejecutable manualmente: `python manage.py loaddata rbac`.
- Migraciones de esquema y de datos (`RunPython`) van en archivos separados. Nunca mezclarlas.
- **Migraciones destructivas** (eliminación de columnas o tablas con datos): requieren backup de PostgreSQL (`pg_dump`) como paso previo obligatorio documentado en la guía del sprint. La migración `RunPython` previa debe verificar que no existen registros en estado incompatible; si los hay, la migración falla con mensaje claro antes de ejecutar cualquier cambio de esquema.

---

## 2.13 Audit Trail

Modelo `AuditLog` en `core/models.py`: `usuario` (FK User), `fecha_hora` (auto), `ip_origen`, `modulo`, `accion` (CREAR / MODIFICAR / ELIMINAR / CAMBIO_ESTADO), `entidad`, `entidad_id`, `before_data` (JSONField), `after_data` (JSONField).

`AuditLog` no tiene FK en cascada que permitan borrar registros. `AuditableModel` sobreescribe `save()` y `delete()` para registrar automáticamente. Todos los modelos transaccionales heredan de `AuditableModel`.

---

## 2.14 Tesorería y Cuentas Bancarias ★ NUEVO v3.0

### CuentaBancaria
- Moneda nativa única (USD o VES). No es mixta.
- `saldo_actual`: `DecimalField(18,2)` en moneda nativa.
- **Saldo negativo absolutamente prohibido:** CHECK constraint en BD + `SaldoInsuficienteError` en Python.
- Cuentas con `activa=False` no reciben movimientos de ningún tipo.

### MovimientoCaja
- **Inmutable post-creación.** Mismo patrón que `MovimientoInventario`.
- Tipos válidos: `ENTRADA`, `SALIDA`, `TRANSFERENCIA_ENTRADA`, `TRANSFERENCIA_SALIDA`, `REEXPRESION`.
- Campos obligatorios: `cuenta` (FK PROTECT), `tipo`, `monto`, `moneda`, `tasa_cambio`, `monto_usd`, `referencia`, `fecha`.
- `monto_usd` siempre se recalcula en lógica de negocio; nunca se acepta el valor del caller sin recalcular.

### TransferenciaCuentas
- Transferencia entre cuentas de distinta moneda requiere `tasa_cambio` explícita. No se asume 1:1.
- `ejecutar()`: `transaction.atomic()`, débito `cuenta_origen` → crédito `cuenta_destino`. Rollback total si falla cualquier parte.
- `anular()`: solo desde `EJECUTADA`; genera movimientos inversos en nuevo `transaction.atomic()`.

### Función `registrar_movimiento_caja()` — `apps/bancos/services.py`
Único punto de entrada para crear `MovimientoCaja`. Pasos obligatorios:
1. Verificar que la cuenta esté activa.
2. Validar saldo no negativo para `SALIDA`.
3. Calcular `monto_usd`.
4. Crear el `MovimientoCaja`.
5. Actualizar `cuenta.saldo_actual` vía `instance.save()`.

> **⚠ CRÍTICO:** Ningún código fuera de `registrar_movimiento_caja()` puede modificar directamente `CuentaBancaria.saldo_actual`.

---

## 2.15 Control de Crédito ★ NUEVO v3.0

La verificación ocurre en `FacturaVenta.emitir()`, no en `save()`.
```
fecha_vencimiento = fecha_emision + timedelta(days=cliente.dias_credito)
```

**Factura vencida:** cumple simultáneamente `estado == EMITIDA`, `fecha_vencimiento < hoy`, `saldo_pendiente > 0`.

| `tipo_control_credito` | Comportamiento |
|---|---|
| `BLOQUEO` | Lanza `EstadoInvalidoError` con lista de facturas vencidas. La emisión no procede. |
| `ADVERTENCIA` | `logger.warning()` con detalle de facturas vencidas y continúa la emisión. |

- `dias_credito` en `Cliente`: `PositiveIntegerField`, `default=30`.
- `tipo_control_credito` en `Cliente`: `BLOQUEO` / `ADVERTENCIA`, `default=ADVERTENCIA`.
- `fecha_vencimiento` en `FacturaVenta`: `DateField`, `null=True`, `editable=False`. Se asigna solo en `emitir()`.

---

## 2.16 Reexpresión Mensual de Saldos en VES ★ NUEVO v3.0

Único mecanismo para reconocer el diferencial cambiario en saldos en bolívares. Se ejecuta al cierre de cada mes: `ReexpresionMensual.ejecutar(tasa_cierre, fecha_cierre)` en `apps/bancos/services.py`.

**Algoritmo — para cada `CuentaBancaria` activa con `moneda == VES`:**
```
usd_antes     = saldo_actual / tasa_inicio_mes
usd_despues   = saldo_actual / tasa_cierre
variacion_usd = usd_despues − usd_antes
→ Crear MovimientoCaja tipo REEXPRESION con variacion_usd
```

- Todo el proceso en un único `transaction.atomic()`. Si falla una cuenta, se revierte todo.
- **Idempotente por mes-año:** controlado por modelo `PeriodoReexpresado` con `unique_together(anio, mes)`. Al inicio de `ejecutar()`: verificar que no existe el período → `EstadoInvalidoError('Período ya reexpresado')` si existe. Al finalizar: crear el `PeriodoReexpresado` dentro del mismo `atomic()`.

---

## 2.19 RBAC — Roles y Permisos ★ NUEVO v3.1

Se usan los Grupos estándar de Django. No se crea modelo custom de roles.

| Grupo | Permisos clave |
|---|---|
| Master | Acceso total. Aprueba precios, ajustes y reexpresión. |
| Administrador | Igual que Master excepto gestión de usuarios y configuración técnica. |
| Jefe Producción | CRUD Órdenes de Producción, aprobación de ajustes bajo umbral. |
| Asistente Compras | CRUD Facturas de Compra y Gastos. Sin acceso a Ventas ni Tesorería. |
| Asistente Ventas | CRUD Facturas de Venta con lista de precios activa y aprobada. Sin acceso a Compras ni Tesorería. |

- Los permisos se cargan vía `fixtures/rbac.json`, aplicado automáticamente en el signal `post_migrate` de `apps/core/apps.py`.
- Decorador `require_group(*grupos)` en `apps/core/rbac.py`: verifica pertenencia al grupo → `PermissionDenied` si no cumple.
- El Admin usa `has_module_perms` y `has_permission` por grupo para ocultar módulos según rol.
- **Umbral de aprobación dual en ajustes:** configurable, `default=1000` USD equiv. Ajustes por encima del umbral requieren grupo Master o Administrador.

---

## 2.20 Valoración de Inventario en Reportes ★ NUEVO v3.1

Aplica al Reporte de Capital de Trabajo y cualquier reporte futuro que requiera valorar existencias.

| Condición | Valor usado |
|---|---|
| `valorar_por == COSTO` | `costo_promedio` siempre |
| `valorar_por == VENTA` y `precio_venta` definido | `precio_venta` |
| `valorar_por == VENTA` y `precio_venta is None` | Fallback a `costo_promedio` (silencioso, sin advertencia) |

El fallback silencioso es la regla correcta para materias primas e insumos, que por naturaleza no tienen precio de venta. No se excluyen del reporte ni se emite advertencia.

---

## Disposiciones Finales (aplican a todas las partes)

- Todas las modificaciones por `instance.save()`, nunca por `QuerySet.update()`.
- `python manage.py check → 0 issues` es requisito de aceptación en cada fase de cada sprint.
- Las reglas de este documento son permanentes. Las restricciones temporales de cada sprint viven solo en la guía del sprint.

---
*LacteOps ERP v3.1 — Parte 2 de 2*