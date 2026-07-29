# Research — contabilidad del chunking y papel de OpenTelemetry

Change `contabilidad-chunking`. Fecha: 2026-07-29. Fase: `understanding`.

Todo lo que sigue está verificado **por ejecución** contra el código instalado y contra el log de
uso real de esta máquina (111 eventos, `usage-202607.jsonl`), no por lectura.

---

## 1. Qué se registra hoy, exactamente

`server.py` tiene tres caminos que terminan en `_log_event`, y **los tres escriben una línea por
operación**, no por llamada al backend:

| Camino | Llamadas al backend | Líneas en el log |
|---|---|---|
| `_chat` (`server.py:568`) | 1 | 1 |
| `_chat_chunked` (`server.py:709`) | N (+ re-splits) | 1, con `chunks: N` |
| `_chat_map_reduce` (`server.py:827`) | N + reduce jerárquico | 1, con `chunks: N` |

Los campos que escribe `_log_event` (`server.py:362`) para un evento chunked:

- `chars_in` = `len(content)` — el contenido **una sola vez**.
- `tokens_in` / `tokens_out` = **suma real** de `usage.prompt_tokens` / `completion_tokens` de las N
  llamadas (`_accumulate`, `server.py:743`). Incluye por tanto el prompt de sistema repetido.
- `latency_ms` = suma de las N latencias.
- `chunks` = `calls`, el número **real** de llamadas, y solo se escribe si `> 1` (`server.py:400`).

**Corrección a la premisa del backlog:** el prompt de sistema **sí queda registrado**, dentro de
`tokens_in`. Lo que pasa es otra cosa, y es peor: **nadie lee ese campo**.

## 2. El defecto real: el dashboard ignora los tokens que ya tiene

`_aggregate` (`web/metrics.py:203`) construye `by_tool`, `by_model`, `by_backend` y `total`
**exclusivamente** a partir de `chars_in`, `chars_out` y `latency_ms`. Comprobado con `grep` sobre el
módulo entero:

- `tokens_in` y `tokens_out` **no aparecen ni una vez** en `metrics.py`. El dato real del backend se
  escribe en el log y muere ahí.
- `chunks` **no entra en ningún agregado**. Aparece solo como adorno: un chip `N×` en la tabla de
  eventos (`metrics.py:1478`) y el `trozo i/N` del panel «En curso» (`metrics.py:1211`).
- `total["calls"]` cuenta **eventos**, no llamadas al backend. Una delegación de 16 trozos suma
  exactamente lo mismo que una de una sola llamada.

Todos los KPIs derivan de la constante `CHARS_PER_TOKEN = 4`: `tokens_context_saved`,
`tokens_generated_local`, `tokens_saved` por tool y por backend, y los tres gráficos
(`metrics.py:1314`, `1353`, `1418`).

Esa es literalmente la frase del backlog — *el dashboard no distingue una delegación eficiente de
una que quemó la GPU 16 veces* — y la causa no es que falte el dato, es que **el agregado no lo
mira**.

## 3. Cuánto se desvía la estimación (medido, no supuesto)

104 de 111 eventos del log traen `tokens_in` real (94%): el backend **sí** reporta `usage`. Desvío de
`chars_in // 4` frente al valor real, por tool:

| Tool | n | est. `chars/4` | `tokens_in` real | desvío |
|---|---:|---:|---:|---:|
| `local_extract` | 13 | 14 172 | 15 306 | **+8 %** |
| `local_explain_code` | 4 | 6 308 | 7 200 | +14 % |
| `local_summarize` | 35 | 124 501 | 144 695 | +16 % |
| `local_commit_msg` | 8 | 14 174 | 17 497 | +23 % |
| `local_lint_summary` | 4 | 8 578 | 12 571 | +47 % |
| `local_boilerplate` | 6 | 496 | 827 | +67 % |
| `local_classify` | 6 | 172 | 566 | +229 % |
| `local_delegate` | 6 | 121 | 684 | +465 % |
| `local_translate` | 5 | 47 | 335 | +613 % |
| `local_describe_image` | 4 | 433 477 | 8 928 | **−98 %** |

Dos lecturas:

1. **En texto, `chars/4` siempre subestima**, y tanto más cuanto más corta es la entrada: el prompt
   de sistema es un coste fijo que la fórmula no ve. En el único evento chunked del log
   (`local_summarize`, 4 llamadas, 84 178 chars) la estimación da 21 044 tokens y el real fue
   **26 131: +24 %**. Ese 24 % *es* el overhead de trocear.
2. **En `local_describe_image` el sesgo se invierte y es enorme**: `chars_in` mide el **base64 de la
   imagen** (433 477 "tokens" estimados frente a 8 928 reales, ×48). Ese evento infla hoy el KPI
   «Contexto conservado» más que todo el resto del log junto. Misma raíz —ignorar el token real—,
   signo contrario.

## 4. OpenTelemetry: qué trae de verdad el SDK 2.x

Verificado sobre el wheel instalado en `.venv`:

- El SDK monta `OpenTelemetryMiddleware` **por defecto** (`mcp/server/lowlevel/server.py:439`), así
  que ya está corriendo hoy en el daemon.
- Lo que instrumenta es el **borde MCP**: un span por mensaje entrante, con `mcp.method.name`,
  `gen_ai.tool.name` y el estado de error (`mcp/server/_otel.py`). Es decir: *«Claude llamó a
  `local_summarize` y tardó X»*. **No ve las llamadas al backend llama-swap**, que es exactamente lo
  que hay que contar.
- La dependencia que entra es `opentelemetry-api` 1.44.0, **la API sola**. `opentelemetry-sdk`
  **no está instalado**. Comprobado ejecutando:

  ```
  opentelemetry.sdk instalado: False
  tracer class: ProxyTracer
  span class: NonRecordingSpan | is_recording: False
  ```

  Sin el SDK, los spans son **no-op**: no se graban ni se exportan a ningún sitio.

**Consecuencia para la decisión:** la frase del plan de la fase 3 —*«`opentelemetry-api` ya entra
como dependencia obligatoria, así que el coste de adoptarlo es cero»*— es cierta para
**instrumentar** y falsa para **recoger**. Recoger exige `opentelemetry-sdk` + un exportador + un
colector o almacén de trazas: dependencias nuevas e infraestructura, en un proyecto cuyo dashboard es
un lector de JSONL local sin servicios externos.

Y aunque se montara todo eso, seguiría sin resolver la deuda: los spans del SDK no cubren
`_run_chat`. Habría que crear spans propios igualmente.

## 5. Impacto — qué se toca

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
|---|---|---|---|
| `server.py` | `_log_event` escribe la línea JSONL; los tres caminos de chat la alimentan | Campo nuevo con las llamadas reales al backend | `server.py:362,568,709,827` |
| `web/metrics.py` | `_aggregate` suma solo chars y latencia | Agregar llamadas al backend y tokens reales | `metrics.py:203-299` |
| JS del dashboard | KPIs y gráficos derivan de `chars/4` | Consumir los agregados nuevos | `metrics.py:1314,1353,1418,1478` |
| `tests/` | `test_metrics.py`, `test_chunking.py`, `test_map_reduce.py` | Cobertura de la contabilidad nueva | — |
| `docs/wiki/Savings-and-metrics.md` | Documenta la fórmula `chars ÷ 4` | Actualizar la explicación | 135 líneas |
| `README.md` | Menciona el cálculo del ahorro | Revisar coherencia | — |

**Compatibilidad hacia atrás:** el log es histórico y no se reescribe. Los 111 eventos actuales no
tienen campo de llamadas y 7 no tienen `tokens_in`. Cualquier agregado nuevo debe degradar
(`chunks or 1`, y `tokens_in` con recurso a la estimación) sin romper ni inventar.

## 6. Convenciones que hay que preservar

- El logging es **best-effort** y jamás propaga (`server.py:423`): un fallo de contabilidad no puede
  tumbar una tool.
- El log se queda en **UTC**; la conversión es solo de presentación (decisión ya tomada en el
  backlog).
- El JSONL solo escribe campos opcionales **cuando aportan** (`chunks` solo si `> 1`), para no
  engordar cada línea.
- El dashboard no tiene build: el JS vive inline en `metrics.py` y se valida con
  `extract_dashboard_js.py` + `node --check`.

## 7. Riesgos

1. **Cambiar los KPIs cambia la historia.** Si «Contexto conservado» pasa a usar tokens reales, el
   número que el usuario lleva viendo desde la 0.11.0 se mueve, y en `local_describe_image` se
   desploma ×48. Hay que decidir si es corrección o si son dos métricas distintas.
2. **Confundir ahorro con coste.** El ahorro de contexto de Claude *es* el contenido contado una
   vez: para ese KPI, `chars_in` una sola vez **es correcto**. Lo que falta no es corregir el
   ahorro, es **añadir la contrapartida de coste**. Un arreglo mal enfocado rompería un KPI que hoy
   está bien.
3. **Scope creep hacia OTel:** instrumentación distribuida en un proyecto de una sola máquina.

## 8. Preguntas abiertas para la spec

- **OTel: ¿sustituye, complementa o se descarta?** Decisión de arquitectura, pendiente del usuario.
- ¿El sesgo de `local_describe_image` entra en este change o se separa?
