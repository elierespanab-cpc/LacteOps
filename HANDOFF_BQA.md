# HANDOFF_BQA — Fase B-QA Sprint 3

## STATUS: OK ✅

## Agente: Claude (Fase B-QA)
## Fecha: 2026-03-13
## Rama: sprint3

---

## Resultado pytest

```
96 passed in 14.04s
```

**0 failures. 0 errors. 0 warnings bloqueantes.**

---

## Archivos de test creados

### tests/test_tasa_cambio.py — 4 tests ✅
| Test | Descripción |
|------|-------------|
| test_tasa_hoy | Creación y recuperación de tasa por fecha exacta |
| test_tasa_fecha_anterior | Recuperación de tasa de fecha pasada |
| test_sin_tasa_exacta_retorna_mas_reciente | filter(fecha__lte).order_by('-fecha').first() |
| test_bulk_create_no_sobreescribe | ignore_conflicts=True no sobreescribe registro existente |

### tests/test_socios.py — 6 tests ✅
| Test | Descripción |
|------|-------------|
| test_prestamo_numero_serie_SOC | Auto-numeración SOC-XXXX |
| test_prestamo_genera_movimiento_caja_entrada | registrar_prestamo() con cuenta_destino crea MovimientoCaja ENTRADA |
| test_pago_parcial_estado_activo | Estado permanece ACTIVO tras pago parcial |
| test_pago_total_estado_cancelado | Estado cambia a CANCELADO cuando total_pagado_usd >= monto_usd |
| test_prestamo_corriente_en_capital_trabajo | Préstamo con vence <= hoy+365 días → pasivo_corriente |
| test_prestamo_sin_fecha_es_no_corriente | Préstamo sin fecha_vencimiento → pasivo_no_corriente |

### tests/test_tesoreria_directa.py — 5 tests ✅
| Test | Descripción |
|------|-------------|
| test_cargo_disminuye_saldo | CARGO reduce saldo de la cuenta |
| test_abono_aumenta_saldo | ABONO aumenta saldo de la cuenta |
| test_cargo_saldo_insuficiente_lanza_error | SaldoInsuficienteError + rollback atómico |
| test_movimiento_tesoreria_inmutable | Segundo save() lanza EstadoInvalidoError |
| test_categoria_contexto_factura_rechazada | contexto='FACTURA' es rechazado (EstadoInvalidoError) |

### tests/test_correcciones_sprint3.py — 6 tests ✅
| Test | Descripción |
|------|-------------|
| test_pago_ves_monto_usd_correcto | monto=500000 VES, tasa=50 → monto_usd=10000.00 (B5+B6) |
| test_cobro_ves_genera_movimiento_caja | Cobro VES crea MovimientoCaja ENTRADA (B5+B6) |
| test_orden_cerrada_no_editable | OrdenProduccion CERRADA bloquea save() (B2) |
| test_reabrir_requiere_master_o_admin | Usuario sin Master/Admin → PermissionDenied (B2) |
| test_cxp_con_pago_parcial_aparece_en_reporte | Factura APROBADA con pago parcial → CxP saldo correcto (B3) |
| test_numeracion_vta_formato | FacturaVenta auto-numerada VTA-0001 (B7) |

---

## Distribución de tests por archivo (96 total)

| Archivo | Tests |
|---------|-------|
| test_ajustes.py | 7 |
| test_bancos.py | 9 |
| test_capital_trabajo.py | 2 |
| test_compras.py | 5 |
| test_correcciones_sprint3.py | 6 ← NEW |
| test_credito.py | 6 |
| test_gastos.py | 7 |
| test_kardex.py | 8 |
| test_listas_precio.py | 5 |
| test_numeracion.py | 5 |
| test_produccion.py | 7 |
| test_produccion_conjunta.py | 4 |
| test_rbac.py | 3 |
| test_reexpresion_idempotente.py | 1 |
| test_socios.py | 6 ← NEW |
| test_tasa_cambio.py | 4 ← NEW |
| test_tesoreria_directa.py | 5 ← NEW |
| test_ventas.py | 5 |
| **TOTAL** | **96** |

---

## Regresiones encontradas

Ninguna. Todos los 75 tests del Sprint 2 continúan en verde.

---

## Decisiones de diseño en tests

- `secuencia_soc`, `secuencia_tes`, `secuencia_vta`, `secuencia_pro`: fixtures locales que resetean el
  contador a 0 usando `get_or_create` + `save(update_fields=...)` para garantizar aislamiento.
- `PrestamoPorSocio.objects.create(estado='ACTIVO')` en tests de capital_trabajo: se crea directamente
  sin pasar por `registrar_prestamo()` para simplificar el fixture.
- `Pago.objects.create(monto_usd=Decimal('200.00'))`: `editable=False` aplica solo a formularios;
  `objects.create()` permite establecer el campo directamente para el test de CxP.
- Tests de OrdenProduccion CERRADA: se usa `OrdenProduccion.objects.filter(...).update(estado='CERRADA')`
  para forzar el estado sin ejecutar el costoso flujo de `cerrar()`.

---

## Próximo paso sugerido

Sprint 3 Fase B-QA completada. El código está listo para revisión final o
para continuar con las siguientes fases del Sprint 3 según la guía.
