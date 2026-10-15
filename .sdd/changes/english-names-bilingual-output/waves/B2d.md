# Ola B2d: muestras en vivo

Quinto PR de B2, en la rama `sdd/english-names-b2d` desde `origin/main` (`359af3b`). Ejecuta
«B2d» de `plan.md` y las decisiones 5 y 9 de `waves/B2-proposal.md` §11 contra el daemon vivo
(0.35.0 con B2a–B2c). Ventana de prueba **`w-20261014T215251Z`**, cerrada. Resultado: **una de tres
muestras cumple**. La de idioma de respuesta quedó **bloqueada** (el llama-swap pide clave al arnés
en proceso) y la de `local_explain_code` sobre `cli.py` **no cumple** (omite `doctor` y
`benchmark`). Sin cambios de código ni de prompts; sin commit, push ni PR. Detalle y salidas
literales en `evidence/B2d/live.md`.

## Qué se hizo

1. Lectura del diseño: `plan.md` («B2d», decisión 9), `waves/B2-proposal.md` §3.3, §5 y §11,
   `evidence/local-tools-review/report.md` y `scripts/detect_language.py`.
2. Comprobación previa del arnés en proceso (decisión 5): el llama-swap de `127.0.0.1:9292`
   responde **401** sin clave, tanto a `/v1/models` como a `/v1/chat/completions`, y la clave no
   está en el entorno del agente. Por la decisión 5 se para esa muestra y se pregunta; no se
   escribió arnés.
3. Ventana `w-20261014T215251Z` abierta y cerrada (21:52:51Z a 22:01:18Z).
4. `local_commit_msg` por el MCP vivo sobre los diffs de B0a y B1a.
5. `local_explain_code` por el MCP vivo sobre `src/local_delegate/cli.py` pidiendo los subcomandos.
6. Veredicto de idioma de los dos commits con `scripts/detect_language.py`.

## Corridas

| Muestra | Criterio | Resultado |
|---|---|---|
| Idioma de respuesta (REQ-028): producto `es` + variable `en` y producto `en` + variable `es`, 4 tools × ≥ 5 documentos | ≥ 90 % en el idioma pedido (detector, `min_tokens=20`, margen 0,15) | **bloqueada**: 401 del llama-swap fuera del daemon; `evidence/B2/lang-sample.json` con `status: blocked` y sin respuestas |
| `local_commit_msg`, diff de B0a | español, cuerpo de 2–6 viñetas | **cumple**: `es` (69 tokens, 0,29 frente a 0,03), 5 viñetas |
| `local_commit_msg`, diff de B1a | español, cuerpo de 2–6 viñetas | **cumple**: `es` (73 tokens, 0,38 frente a 0,01), 6 viñetas |
| `local_explain_code`, `cli.py` (58 875 caracteres) | nombra `doctor`, `benchmark` y `llamaswap`; sin aviso de truncado | **no cumple**: sin truncado (4 trozos) y con `llamaswap`, pero sin `doctor` ni `benchmark` |

## Observaciones y desviaciones

- **Muestra de idioma bloqueada.** Hace falta una decisión: un reinicio planificado del daemon por
  combinación (y `/mcp` después) o una vía para que el arnés herede la clave del lanzador sin verla.
  No se reinició nada, como pedía el encargo.
- **`explain_code` mejora pero no llega.** Frente a la 0.35.0 (truncaba a 20 000 y no nombraba
  `llamaswap`), ahora lee la entrada entera y lista 9 subcomandos. Faltan `doctor`
  (`cli.py:1343`) y `benchmark` (`cli.py:1231`, registrado con `benchmark.add_parser(sub)`, sin el
  literal en el fichero). Están en `build_parser()`, la misma función de `serve`, `recompute-cost` y
  `check-llamaswap`, que sí salen: la omisión pasa en el map-reduce (paso map de ese trozo o el
  reduce), no por pérdida de entrada. El inventario de nombres del paso final lista `def`/`class`,
  no subcomandos, así que no los rescata. Separar map de reduce exige ver las salidas parciales, que
  hoy no se registran.
- **No se repitió** la llamada de `explain_code`: RAM al límite (< 2 GB libres) y una repetición
  suelta no decide.
- **Sin muestra de `local_describe_image`**: no se llegó a preparar, porque la muestra entera quedó
  bloqueada antes de generar documentos.
- Ningún `.py` en `evidence/`. Los diffs y los mensajes juzgados quedaron en el scratchpad de la
  sesión; sus sha256 están en `evidence/B2d/live.md`.

## Llamadas `local_*`

| # | Llamada | Para qué | Resultado |
|---|---|---|---|
| 1 | `local_summarize(path=waves/B2-proposal.md, focus=…)` | mapa del diseño de B2d | sirvió para ubicar §5 y §11; las secciones normativas se leyeron literales después |
| 2 | `local_summarize(path=plan.md, focus=…)` | lote B2d y decisión 9 | confirmó el criterio de ≥ 90 % con idioma contrario |
| 3 | `local_status` | estado del daemon y del backend | idioma `es`, modelos, RAM al límite |
| 4 | `local_commit_msg(path=b0a.diff)` | muestra 2 | arriba |
| 5 | `local_commit_msg(path=b1a.diff)` | muestra 2 | arriba |
| 6 | `local_explain_code(path=cli.py, question=…)` | muestra 3 | arriba |
| 7 | `local_summarize(path=evidence/local-tools-review/report.md, focus=…)` | causas medidas antes de B2c | sirvió para comparar con la 0.35.0 |

## Llamadas `mcp__pycharm__*`

| # | Tool | Motivo |
|---|---|---|
| 1 | ninguna | motivo: B2d no edita código ni renombra; las comprobaciones de líneas de `cli.py` se hicieron con `grep` |

**Pasos hechos a mano y por qué:** §3.3, §5 y §11 de `B2-proposal.md` se leyeron literales con
`sed` porque son la norma de la ola y el resumen no conserva literales. Los encabezados y franjas de
`B2c.md` se leyeron con `sed`/`grep` para copiar el formato. Las líneas de `cli.py` donde se
registran `doctor` y `benchmark` se buscaron con `grep`: hacía falta el número de línea exacto para
el diagnóstico. El veredicto de idioma lo dio el detector (programa, no modelo).

## Endurecimiento (B2d-fix, 2026-10-15)

Decisión del usuario tras la medición de antes (`8c5e07f`): endurecer la orden de idioma de
`local_summarize` y `local_lint_summary`, arreglar las secciones duplicadas del resumen por secciones
y volver a medir con un segundo conjunto de documentos fijado antes. Esta parte NO mide en vivo: no
se instaló ni se reinició el daemon (lo hace la sesión principal).

### Causas, leídas en `evidence/B2/lang-sample.json`

Los 6 fallos de summarize y lint_summary son `unknown`, ninguno en el idioma contrario:

- **Respuestas mezcladas, no en el otro idioma.** El modelo traducía el marco y dejaba fragmentos de
  la entrada tal cual, en sintagmas sin verbo: «Múltiples `if` statements», «Restoration
  successful.», «Key inconsistencies: … vs `entrada`». Con pocas palabras funcionales el margen del
  detector no llega a 0,15. La orden de antes solo decía «Responde en X», sin decir qué se redacta
  en X ni qué se queda literal.
- **Sección duplicada (Backend-versions.md).** La «Introducción» sintética salía en el idioma del
  producto (`es`) aunque al modelo se le pedía responder en inglés; el modelo escribió
  «Introduction» y `sections.complete`, que empareja por texto, añadió «Introducción (sin resumir)»
  otra vez. Lo mismo pasa con cualquier título del documento que el modelo traduzca.
- Los títulos del documento salen literales a propósito (el formato pide «el título tal cual», para
  que Claude los busque en el documento): eso no se cambia.

### Arreglos

- `src/local_delegate/server.py:3455` `_written_language_clause()`: la orden endurecida («Escribe
  toda la respuesta en X…: redacta en X cada frase, también la descripción de cada error o regla,
  con frases completas y sin copiar frases del contenido. Solo se quedan tal cual los títulos que se
  piden literales, las rutas, el código, los identificadores y los códigos de regla o de error.»).
  Va en el mismo sitio que la de antes (detrás de `_guard`, en el `system`): en `_lint_system`
  (`:3496`), en el `extra` de `local_summarize` (`:3743`, que llega al map, a cada trozo del resumen
  por secciones y al reduce) y en el reduce de `local_lint_summary` (`:4161`). `local_explain_code`
  y `local_describe_image` (10/10) siguen con `_response_language_clause()`. Solo cambia el
  `system`, ya declarado como frontera de la 0.36.0 (`PROMPT_BOUNDARIES`); los dos `--check` de
  corpus dan `ok`.
- `src/local_delegate/sections.py:365` `introduction()`: en el idioma de respuesta si el catálogo lo
  tiene (`es`/`en`, también `en-GB`); si no (`fr`, texto libre), en el del producto, como antes.
- `src/local_delegate/sections.py:187` `_pair_translated()` + `match_headings(..., positional=True)`
  (`:274`), que usa `complete()` (`:322`): un título que falta se empareja con el que el modelo
  escribió en su hueco en otro idioma, y `complete` le devuelve la forma del documento conservando
  el nivel (`:325`). Estrecho a propósito: entre los mismos dos vecinos emparejados tiene que haber
  UN solo esperado que falte y UNA sola línea ATX libre, del nivel de las emparejadas (2 si no hay
  ninguna), que no coincida con ningún esperado; las negritas no cuentan.
  `scripts/measure_structured_summary.py` sigue con el emparejamiento por texto (el valor por
  defecto), con el que se congeló su línea base.
- Alternativa descartada: dejar que el modelo traduzca los títulos y reconocerlos traducidos. Rompe
  «el título tal cual» (Claude no podría buscarlos en el documento) y exigiría traducir en el
  servidor.
- `CHANGELOG.md` (`[Unreleased]`): una entrada en «Cambia» y otra en «Corrige».

### Conjunto de control 2 (fijado antes de medir)

`evidence/B2d-fix/lang-sample-docs-2.json` (sha256
`a7b333a448731b4574d2e58e34a4466267ffc78211d914faa1846d1486543a22`), commit `ea0ee67`, ANTES de
cualquier cambio de código y de cualquier medición. 20 documentos, copias byte a byte en
`evidence/B2d-fix/docs-2/` (marcadas `-text` en `.gitattributes`), elegidos por las reglas escritas
en el propio JSON: documentos del repo en español (README, investigación, planes), METADATA de
paquetes en inglés, salidas de `doctor` y de los `--check` de corpus en español, y cinco salidas
reales generadas el 2026-10-15 (biome lint, pytest, ruff conciso, ruff completo, tsc). Cada tanda
lleva idioma de entrada mezclado, con mayoría en el idioma contrario al pedido. El detector y su
umbral no se tocan.

### Verificación

- Tests nuevos: `tests/test_language_hardening.py` (23): la orden endurecida en las dos tools y en
  cada paso del troceado, en las dos tandas; explain_code/describe_image sin cambio; la introducción
  en el idioma de respuesta (6 casos); el caso en vivo de B2d de punta a punta; el rescate del título
  traducido, su nivel, y tres controles de estrechez (dos faltantes en un hueco, subsección `###`,
  negrita) más «un título inventado sin faltantes no se toca». Ajustados a la orden nueva:
  `tests/test_response_language.py`, `tests/test_structured_summary.py` y la excepción del guardián
  en `tests/data/uncatalogued_exceptions.json`.
- Suite completa: `evidence/B2d-fix/suite-es.txt` (`LANG=es_ES.UTF-8`) y `suite-en.txt`
  (`LANG=en_US.UTF-8`): **2950 passed, 2 skipped** en las dos, solo los 2 `DeprecationWarning` de
  starlette de siempre. `ruff check .` y `ruff format --check .` limpios (`ruff.txt`). Corpus:
  `corpus-f2-check.txt` y `corpus-affinity-check.txt`, `ok` (solo fronteras declaradas de `system` y
  `max_tokens`).
- Mutantes (`evidence/B2d-fix/mutants.md`, seis, aplicados de verdad con comprobación de sha256 y
  restaurados): M1 orden de antes → falla el primer `in` de `_assert_hardened` («Escribe toda la
  respuesta en inglés…»); M2 introducción en el idioma del producto → `plan[0].heading == expected`;
  M3 `complete` sin `positional` → `len(headings) == len(EXPECTED)`; M4 (M2+M3, el caso en vivo) →
  `"Introducción" not in output`; M5 sin filtro de nivel → `done.missing >= 1` en subsección y
  negrita; M6 sin «un solo faltante» → `done.missing >= 1` en dos faltantes.

### Medición en vivo pendiente (la hace la sesión principal)

Tras instalar la rama en el daemon (`uv tool install --force --reinstall --no-cache
".[llamaswap]"` y reinicio), con `LOCAL_DELEGATE_STRUCTURED_SUMMARY` encendida como en la medición
de antes, una ventana de prueba por tanda (`local-delegate test-window start --label …`):

- Tanda 1: producto `es`, `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en`. Tanda 2: `LOCAL_DELEGATE_LANG=en`,
  `LOCAL_DELEGATE_OUTPUT_LANGUAGE=es`.
- Cada tool con `path=<ruta>` de los 5 documentos de su tanda en `lang-sample-docs-2.json`, con los
  valores por defecto (`max_words`, sin `focus`).
- Puntuación como en `evidence/B2/lang-sample.json`: texto juzgado = respuesta literal sin las líneas
  del producto («(leído server-side: …)»/«(read server-side: …)», «[local-delegate warning: …]» y
  «(sin resumir)»/«(not summarized)»); `detect(min_tokens=20, min_margin=0.15)`. Criterio: ≥ 90 %
  en el idioma pedido por tool y tanda, y 0 en el contrario. Además, para summarize: ninguna sección
  con dos títulos (uno traducido y otro «(sin resumir)»).
- Se vuelven a pasar también los 20 documentos del conjunto 1 (`evidence/B2d/lang-sample-docs.json`)
  para comparar con el 34/40 de antes.

### Llamadas `local_*`

| # | Llamada | Para qué | Resultado |
|---|---|---|---|
| 1 | `local_lint_summary(path=evidence/B2d-fix/suite-en.txt)` | resumir la corrida en inglés | 2 `DeprecationWarning`, ningún fallo |
| 2 | `local_commit_msg(path=<diff del arreglo>)` | borrador del commit del arreglo | borrador revisado y reescrito a mano |

**Pasos hechos a mano y por qué:** los 6 fallos de `lang-sample.json` se leyeron literales con
`python`: el diagnóstico depende de palabras concretas de la respuesta y un resumen no las conserva.
`server.py` y `sections.py` se leyeron por tramos con `sed`/`grep`: había que editar líneas exactas.
El idioma de los documentos de entrada lo dio el detector (programa, no modelo).
