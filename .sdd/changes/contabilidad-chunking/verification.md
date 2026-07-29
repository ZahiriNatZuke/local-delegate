# Verificación — `contabilidad-chunking`

## Entorno

- Rama `feat/contabilidad-chunking`, sobre `main` en `dcc614c` (0.13.1 publicada).
- Windows 11, Python 3.11 del venv editable del repo, `node` disponible en el PATH.
- Backend real: llama-swap en `127.0.0.1:9292`, cómputo **local**, modelo `llama31-8b`.
- Daemon reiniciado sobre el código nuevo antes de cada comprobación en vivo (`Stop-Process` +
  `Start-ScheduledTask LocalDelegateDaemon`): sin eso se prueba el código viejo.

## Evidencia

| Req | Comprobación | Resultado | Evidencia |
|---|---|---|---|
| REQ-001 | Agregado sobre el log real (111 eventos) | **111 delegaciones → 114 llamadas al backend** | ejecución de `_aggregate`; `/api/stats` del daemon |
| REQ-001 | Escenario de aceptación de la spec | 2 eventos, uno con `chunks:4` → `calls:2`, `backend_calls:5` | `test_stats_distingue_delegaciones_de_llamadas_al_backend` |
| REQ-002 | Token real por encima de la estimación | evento chunked real: **26 131** tokens, no 21 044 | `test_accounting_troceado_separa_ahorro_de_coste` |
| REQ-002 | Eventos estimados declarados | 7 de 111 en el log real; `estimated_events` los reporta | `/api/stats`; `test_stats_marca_los_eventos_que_hubo_que_estimar` |
| REQ-002b | Paridad `/api/stats` ↔ panel | los KPIs se piden al servidor; el helper JS restante se compara con Python en `node` | `test_paridad_acct_entre_python_y_el_js_del_panel`; `test_dashboard_pide_los_kpis_al_servidor` |
| REQ-003 | Distinguible a simple vista | el panel muestra **12 delegaciones · 18 al backend (+6 por trocear)** | captura del dashboard en vivo |
| REQ-004 | El ahorro de texto no cambia de definición | troceado real: ahorro 23 754 (documento una vez) frente a coste 29 068 | delegación real, ver abajo |
| REQ-005 | La imagen deja de inflar el ahorro | evento real de 504 780 **bytes**: aporta **2 758** tok, no 126 195 | `test_accounting_imagen_usa_el_token_real_y_no_los_bytes` |
| REQ-005 | La marca viaja al log | `input_unit: "bytes"` escrito, y ausente en tools de texto | `test_describe_image_logs_real_tokens_and_path`, `test_text_tool_does_not_write_input_unit` |
| REQ-006 | El histórico no rompe ni inventa | 111 eventos previos agregados sin error; imagen sin marca reconocida por la tool; sin token real → 0, no un número falso | 3 tests de `_accounting` + ejecución sobre el log real |
| REQ-007 | El logging sigue best-effort | `_log_event` intacto dentro de su `try/except OSError` | inspección del diff |
| REQ-008 | Documentación al día | wiki, README y ayuda del panel reescritas: ahorro vs coste, token real vs estimación | `docs/wiki/Savings-and-metrics.md`, `README.md`, diálogo de ayuda |
| REQ-009 | La decisión de OTel queda registrada | tres razones verificadas en las decisiones de diseño | `docs/wiki/Architecture.md` |

### Verificación por ejecución contra el backend real

Delegación troceada de verdad (`local_summarize` sobre `web/metrics.py`, 95 016 chars), con el
daemon corriendo el código nuevo:

```
EVENTO: chars_in 95016 · chunks 4 · tokens_in 29068 · tokens_out 572 · latency 25137 ms
CUENTAS: ahorro 23 754 tok · coste 29 068 tok en 4 llamadas · overhead de trocear +22 %
```

Antes de este cambio, ese mismo evento aportaba **un** número al panel y era indistinguible de una
delegación de una sola llamada.

Dashboard en vivo, comprobado con el navegador (no leyendo el HTML): los seis KPIs se pintan con
datos reales, los gráficos siguen dibujándose y el panel «En curso» registró la delegación.

### Los tests se verificaron al revés

Como manda el plan, se comprobó que **detectan**, rompiendo la regla a propósito:

- Rompiendo el JS (que el ahorro de imagen vuelva a estimarse desde los bytes) →
  `test_paridad_acct…` falla con **`assert 126195 == 2758`**, que es exactamente el número
  fantasma del defecto original.
- Rompiendo Python (`backend_calls = 1`, la contabilidad vieja) → fallan los 3 tests de troceado.
- Restaurado en ambos casos y suite de nuevo en verde.

## Comprobaciones de calidad

- [x] `pytest -q` → **276 pasan** (263 antes + 13 nuevos), ninguno perdido.
- [x] `ruff check .` → limpio.
- [x] `ruff format --check .` → 46 ficheros ya formateados.
- [x] `extract_dashboard_js.py` + `node --check` → OK.
- [x] Sin secretos ni datos personales: lo añadido son contadores; los fixtures son sintéticos.
- [x] Sin cambios ajenos al change; capturas de trabajo sacadas del repo.

## Hallazgos durante la implementación

1. **Divergencia real cazada al escribir el test de paridad:** el JS usaba `Math.round(c/4)` y
   Python `// 4`. Con entradas impares las series del gráfico se habrían ido un token respecto a la
   tarjeta de encima. El JS pasa a `Math.floor`.
2. **Había una TERCERA superficie con la misma cuenta, que el research no vio.** `local_status`
   —la tool MCP de diagnóstico— recorría el log por su cuenta sumando `chars_in // 4` a mano,
   imágenes incluidas. Habría seguido dando un número distinto al del panel sobre el mismo log,
   que es exactamente el defecto que este change cierra. Como `metrics.py` ya importa `server`,
   la contabilidad se movió a `server.py` —junto a `_log_event`, que define el formato del log— y
   las tres superficies la comparten. Verificado por ejecución contra el daemon real: `local_status`
   y `/api/stats` dicen **118 llamadas al backend y 256 732 tokens ahorrados**, los mismos números.
3. **Código muerto propio:** `saved_chars` quedó acumulándose en `_aggregate` sin que nadie lo
   leyera al pasar los agregados a tokens reales. Eliminado.
4. **Regresión visual propia, detectada mirando:** la sexta tarjeta rompía la retícula de 5
   columnas y «Tasa de error» caía sola en una segunda fila con un hueco enorme. Corregido a 6
   columnas con un breakpoint nuevo a 1320 px, y el hint más largo acortado porque se partía en
   tres líneas. Verificado con captura del elemento, no a ojo sobre el CSS.

## Desviaciones y riesgo residual

- **El KPI «Contexto conservado» baja** respecto a lo que el usuario venía viendo, por dos causas
  legítimas y declaradas en el `CHANGELOG.md`: la corrección del caso de imagen y el fin del
  truncado a 5000 eventos en el cálculo. No es una regresión.
- **El caso «imagen sin token real» (ahorro 0) no se ha observado nunca** en el log: es posible con
  un backend que no reporte `usage`, y está cubierto por test, pero no por ejecución real.
- **El test de paridad se salta si no hay `node`.** En el CI del proyecto `node` está disponible, así
  que allí siempre corre.
