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

**Lote nuevo (2026-10-15):** el tope de salida de lint, la sección vacía avisada como «no resumida», el corte por tope que borra una sección y el largo crudo de la salida en el log pasan al lote B2d-2 (`plan.md`, §1.4, «B2d-2»), entre B2d y B2e. La decisión de cómo juzgar el idioma (solo prosa o texto entero) se queda en B2d, pendiente de la prueba en vivo en curso.

## Juez de prosa y etiquetas (B2d-fix, 2026-10-15)

Tras las pruebas en vivo X e Y (`evidence/B2d-fix/live-probe-X.json`, `live-probe-Y.json`): el
modelo de lint corto copiaba en español 5 a 8 etiquetas en negrita del informe de `doctor`, y el
juez de texto entero mezclaba lo que el formato obliga a copiar (títulos, rutas, `I001`/`UP006`)
con lo que el modelo redacta. Tres pasos, en este orden y cada uno con su commit firmado. Esta parte
NO mide en vivo ni reinstala el daemon.

### 1. Conjunto de control 3 (fijado antes de todo)

`evidence/B2d-fix/lang-sample-docs-3.json` (sha256
`fcf3b4462b193739a00ff3acf633aba365b9e50c8a021d76fd37b14cf3d68593`), commit `b3e9d08`, antes de
escribir el juez y de tocar código. 20 documentos distintos de los conjuntos 1 y 2, copias byte a
byte en `evidence/B2d-fix/docs-3/` (marcadas `-text` en `.gitattributes`), con las reglas escritas
en el JSON. Por tanda: 2 documentos con muchos títulos (≥ 12) en summarize y 2 logs cortos
(< 1 000 caracteres) en lint. Lint en español: dos `--check` de corpus ya versionados, un `doctor
--home <vacío>` y dos `check-llamaswap` cortos generados hoy; en inglés, salidas reales de hoy
(biome, dos ruff concisos cortos, pytest, tsc; no hay eslint instalado en ningún proyecto).
Desviaciones respecto al conjunto 2, escritas en el JSON: los METADATA en inglés bajan a 4 000
bytes (por encima de 6 000 solo quedaban 4 sin usar) y el detector sobre la entrada se anota sin
exigirlo en los logs generados (los cortos dan `unknown`: son nombres, rutas y códigos).

### 2. Juez «solo prosa» (fijado antes de puntuar)

`scripts/judge_response_language.py`, commit `6d29ceb` (sha256 del script
`c212c71eeecea65151cc10fd0e4a3adf4ab923f3692aa8c209841d723dc953a0`). Reglas en su docstring y en
`evidence/B2d-fix/judge-rules.md`: quita solo las líneas del producto, los títulos `#` que coinciden
(normalizados) con un título del documento original, el código, las URLs, las rutas, los nombres de
regla en kebab-case, los identificadores y todo trozo con dígitos (números y códigos como `E501`);
NO quita las etiquetas en negrita. Con menos de 20 tokens del detector, `not_judgeable`; si no, el
detector sin tocar da `requested`/`opposite`/`unknown`. 23 tests sintéticos
(`tests/test_judge_response_language.py`) y un mutante por regla, aplicados de verdad
(`judge-mutants.md`): cada uno hace fallar solo el test de su regla, en `result.tokens == LIMIT - 1`.
El primer pase mostró una regla muerta (los códigos con dígitos ya caían por la de números) y se
quitó.

**Re-puntuado retrospectivo** (`evidence/B2d-fix/rescore-sets-1-2.json`, commit `4840ed9`): las 55
respuestas ya medidas, con el juez escrito después de ver esos fallos. NO valida nada por sí mismo.

| Tool | Tanda / prueba | n | Antes (pedido / unknown) | Después (pedido / unknown / no juzgable) |
|---|---|---|---|---|
| summarize | tanda 1 (conj. 1+2) | 10 | 7 / 3 | 10 / 0 / 0 |
| summarize | tanda 2 (conj. 1+2) | 10 | 10 / 0 | 10 / 0 / 0 |
| lint_summary | tanda 1 (conj. 1+2) | 10 | 8 / 2 | 8 / 1 / 1 |
| lint_summary | tanda 2 (conj. 1+2) | 10 | 9 / 1 | 9 / 0 / 1 |
| lint_summary | prueba X | 6 | 1 / 5 | 3 / 3 / 0 |
| lint_summary | prueba Y | 6 | 3 / 3 | 5 / 1 / 0 |
| summarize | prueba Y | 3 | 3 / 0 | 3 / 0 / 0 |

Ninguna en el idioma contrario, ni antes ni después. Cambian 10: los tres `unknown` de summarize
pasan a pedido (los títulos copiados del documento ya no cuentan), cinco `doctor` vacíos de lint
pasan a pedido, y dos lint pasan a no juzgable (el pytest del conjunto 2, que antes aprobaba con 28
tokens y ahora tiene 19 de prosa, y un ruff del conjunto 1). Los `doctor` completos de X siguen
`unknown`: son justo los de las etiquetas copiadas, que el juez no perdona.

**Muestra para revisión humana:** `evidence/B2d-fix/human-review-sample.md`, 12 respuestas (6 de las
10 que cambian y 6 de las 45 que no, `random.Random(20261015)`), con los dos veredictos y una
casilla vacía «¿está en el idioma pedido?». La rellena el usuario.

### 3. `local_lint_summary`: las etiquetas también en el idioma pedido

- `src/local_delegate/server.py:3484` `_lint_language_clause()`: la cabeza endurecida de siempre
  (`_written_language_head`, `:3475`) más «También van en X las etiquetas en negrita, los nombres de
  sección y los nombres de cada chequeo o prueba: tradúcelos aunque en el contenido aparezcan en otro
  idioma. Solo se quedan tal cual las rutas, el código, los identificadores y los códigos de regla o
  de error.». Ya no dice «los títulos que se piden literales», que lint no tiene y el modelo podía
  tomar por sus etiquetas. Va en `_lint_system` (`:3523`, que llega a la llamada única y a cada
  trozo del map) y en el `reduce_extra` (`:4188`).
- `local_summarize` no cambia: `_written_language_clause()` (`:3455`) da el mismo texto byte a byte
  (`test_the_summarize_order_does_not_change` lo compara con el de `71846c1`).
- Tests: `tests/test_language_hardening.py` (`_assert_lint_labels`, el test nuevo de map y reduce en
  las dos tandas con guardas de «de verdad troceó» y «el último paso reduce», y el de summarize sin
  cambio) y `tests/test_response_language.py` (`_lint_order`).
- Mutantes (`evidence/B2d-fix/lint-labels/mutants.md`, aplicados por bytes sobre el CRLF y
  restaurados por sha256): L1 lint con la orden de summarize → 14 fallos; L2 solo el reduce → 5,
  solo en los de troceado; L3 sin la frase de etiquetas → 14. En los tres salta el primer `in` de
  `_assert_lint_labels` (`test_language_hardening.py:78`).
- Corpus: `evidence/B2d-fix/lint-labels/corpus-f2-check.txt` y `corpus-affinity-check.txt`, los dos
  `ok` (solo las fronteras declaradas de `system` y `max_tokens` de la 0.36.0).
- `CHANGELOG.md` (`[Unreleased]`, «Cambia»): una entrada.
- Suites: `evidence/B2d-fix/lint-labels/suite-es.txt` (`LANG=es_ES.UTF-8`) y `suite-en.txt`
  (`LANG=en_US.UTF-8`): **2976 passed, 2 skipped** en las dos, solo los 2 `DeprecationWarning` de
  starlette. `ruff check .` y `ruff format --check .` limpios (`lint-labels/ruff.txt`). La primera
  corrida dio 3 fallos esperables y arreglados aquí: el guardián de textos (la excepción de la orden
  endurecida se parte en tres: cabeza común, cierre de summarize y cierre de lint, en
  `tests/data/uncatalogued_exceptions.json`) y `test_wiki` (el juez lleva shebang y le faltaba el
  bit de ejecución en git: `git update-index --chmod=+x`, en este commit).

### Medición en vivo del conjunto 3 (la hace la sesión principal)

Instalar la rama en el daemon (`uv tool install --force --reinstall --no-cache ".[llamaswap]"` y
reinicio), con `LOCAL_DELEGATE_STRUCTURED_SUMMARY` encendida como en las mediciones anteriores. Una
ventana de prueba por tanda (`local-delegate test-window start --label «B2d-fix conjunto 3 tanda
N»`, guardar el id, `stop <id>` al acabar). Cada tool con `path=<ruta absoluta>` y los valores por
defecto (`max_words`, sin `focus`), de una en una; guardar cada respuesta literal en un fichero.

- **Tanda 1** (producto `es`, `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en`), bajo
  `evidence/B2d-fix/docs-3/`:
  - `local_summarize`: `es-doc-docs_recipes_claude-code-hooks.md`,
    `es-doc-docs_recipes_llama-swap-groups.md`, `es-doc-docs_recipes_remote-backend.md`,
    `en-doc-pycparser-3.0.METADATA.md`, `en-doc-distlib-0.4.3.METADATA.md`.
  - `local_lint_summary`: `es-log-check-llamaswap-pre-b10909.txt`,
    `es-log-B2c_corpus-f2-check.txt`, `es-log-doctor-empty-home.txt`,
    `en-log-biome-lint-nest.txt`, `en-log-ruff-concise-build-site.txt`.
- **Tanda 2** (`LOCAL_DELEGATE_LANG=en`, `LOCAL_DELEGATE_OUTPUT_LANGUAGE=es`):
  - `local_summarize`: `en-doc-pywin32-312.METADATA.md`, `en-doc-identify-2.6.19.METADATA.md`,
    `en-doc-python_discovery-1.6.1.METADATA.md`, `es-doc-docs_wiki_Configuration.md`,
    `es-doc-src_local_delegate_resources_skills_local-delegation_SKILL.md`.
  - `local_lint_summary`: `en-log-pytest-chunking-density.txt`,
    `en-log-ruff-concise-clean-watcher.txt`, `en-log-tsc-angular.txt`,
    `es-log-check-llamaswap-pre-no-resident.txt`, `es-log-B2d-fix_corpus-affinity-check.txt`.
- **Juez:** por respuesta, `python scripts/judge_response_language.py --document
  evidence/B2d-fix/docs-3/<doc> --requested en|es <respuesta>` (o `judge()` desde Python para
  guardar también `judged_text`); comprobar antes que el sha256 de cada documento sigue siendo el
  del JSON. Anotar al lado el juez de antes (respuesta menos líneas del producto, `detect(20,
  0.15)`) para comparar.
- **Criterio** (escrito en el JSON): ≥ 90 % en el idioma pedido entre las juzgables, por tool y
  tanda, y 0 en el contrario; `not_judgeable` aparte, no cuenta como aprobado. Además, para lint,
  contar las etiquetas `**…**` copiadas del documento en el otro idioma (la regla de etiquetas de
  `live-probe-X.json`). El juicio humano de `human-review-sample.md` dice si el juez merece
  confianza antes de darle valor a este número.

### Llamadas `local_*`

| # | Llamada | Para qué | Resultado |
|---|---|---|---|
| 1 | `local_commit_msg(path=<diff del arreglo de lint>)` | borrador del commit del arreglo | borrador revisado y reescrito a mano |
| 2 | `local_lint_summary(path=lint-labels/suite-es.txt)` (primera corrida) | resumir los 3 fallos | guardián de textos (3 textos nuevos, 1 excepción caducada) y bit de ejecución del juez |

**Pasos hechos a mano y por qué:** la elección de los documentos del conjunto 3 la hizo un script
(reglas, tamaños, títulos, detector), no un modelo. El juez, sus tests y los mutantes son código que
había que escribir exacto. Los textos de `server.py` y de los tests se editaron por tramos con
Python para respetar el CRLF de `server.py`. Las respuestas se re-puntuaron con el juez (programa).

## Resultado

- **Conjunto 3 en vivo:** `local_summarize` 10/10 y `local_lint_summary` 10/10 en el idioma pedido
  entre las juzgables, 0 en el contrario (`evidence/B2d-fix/lang-sample-set3-batch1.json` y
  `lang-sample-set3-batch2.json`).
- **Revisión humana:** 9/10 juzgables con el juez nuevo, frente a 6/12 con el de antes
  (`evidence/B2d-fix/human-review-result.md`).
- **Control negativo:** 20/20 `opposite` (`evidence/B2d-fix/judge-negative-control.json`).
- **Decisión:** se juzga solo la prosa (`scripts/judge_response_language.py`, reglas en
  `evidence/B2d-fix/judge-rules.md`).
- **Pendientes:** sección repetida, contenido inventado en lint, etiquetas copiadas en summarize y
  lectura cp1252 del juez pasan a B2d-2 (`plan.md`, sección «B2d-2»).
