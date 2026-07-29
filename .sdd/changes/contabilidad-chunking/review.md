# Revisión de conformidad — `contabilidad-chunking`

## Veredicto

**`conforms-with-notes`** — los 10 requisitos se cumplen con evidencia; las notas son cambios que
la implementación forzó y que van documentados abajo.

## Comparación contra la especificación

| Req | Implementado | Verificado | Notas |
|---|---|---|---|
| REQ-001 | Sí | Log real: 111 eventos → **114 llamadas al backend**; test del escenario de la spec | `chunks or 1` contabiliza el histórico sin migrarlo |
| REQ-002 | Sí | 7 de 111 eventos estimados, declarados en `estimated_events` | El token real manda; `chars ÷ 4` queda de respaldo |
| REQ-002b | Sí | `local_status` y `/api/stats` en vivo: **118 llamadas, 256 732 tok**, idénticos | Alcance mayor del previsto: eran **tres** superficies |
| REQ-003 | Sí | Panel real: «12 delegaciones · 18 al backend (+6 por trocear)» | KPI «Coste local» nuevo; el chip dice llamadas, no «trozos» |
| REQ-004 | Sí | Delegación real: ahorro 23 754 frente a coste 29 068 | El ahorro de texto conserva su definición, y queda escrito en la wiki |
| REQ-005 | Sí | El evento real pasa de 126 195 tok fantasma a **2 758** | `input_unit` solo viaja cuando no es texto |
| REQ-006 | Sí | 111 eventos previos agregados sin error; 3 tests de degradación | Sin token ni unidad estimable → `0` declarado, nunca extrapolado |
| REQ-007 | Sí | Diff: `_log_event` sigue entero en su `try/except OSError` | Estructura intacta |
| REQ-008 | Sí | Wiki, README y ayuda del panel coherentes entre sí | Ahorro vs coste, token real vs estimación |
| REQ-009 | Sí | `docs/wiki/Architecture.md`, decisiones de diseño | Las tres razones, verificadas ejecutando |

## No-goals: respetados

Ni OpenTelemetry ni dependencias nuevas; no se reescribió el log histórico; no se tocó la estrategia
de troceado (el solapamiento y el glosario del map-reduce siguen siendo su propio change);
`CHARS_PER_TOKEN` sigue como respaldo y no se añadió tokenizer; ni telemetría de hooks ni
autenticación del dashboard.

## Hallazgos

1. **La contabilidad se movió de `web/metrics.py` a `server.py`.** No estaba en el plan: lo forzó
   descubrir que `local_status` era una **tercera** superficie con su propia copia de la cuenta
   (`chars_in // 4` a mano, imágenes incluidas). Como `metrics` ya importa `server`, era la única
   dirección posible sin ciclo, y además es donde vive `_log_event`, que define el formato del log.
2. **`local_status` cambia su salida de texto**: reporta ahora las llamadas al backend y el ahorro
   con la cuenta común. Es visible para quien use esa tool.
3. **Divergencia latente cazada:** el `tok()` del JS redondeaba (`Math.round`) donde Python trunca
   (`//`). Con entradas impares el gráfico se habría ido un token respecto a su propia tarjeta.
4. **Regresión visual propia**, corregida antes de cerrar: la sexta tarjeta rompía la retícula de 5
   columnas y «Tasa de error» caía sola en una fila.
5. **Código muerto propio**, eliminado: `saved_chars` quedó acumulándose sin que nadie lo leyera.

Los hallazgos 1 y 2 son consecuencia directa de REQ-002b, no alcance nuevo. Están reflejados en la
spec (la nota de «tres superficies») y en la trazabilidad.

## Trabajo pendiente antes del cierre

Ninguno bloqueante. Para la nota de memoria:

- El caso «imagen sin token real» está cubierto por test pero **nunca se ha observado** en un log
  real; solo aparecería con un backend que no reporte `usage`.
- El KPI «Contexto conservado» **baja** respecto a lo que se venía viendo, por dos causas legítimas
  ya declaradas en el `CHANGELOG.md`. Conviene no leerlo como regresión al mirar el panel.
