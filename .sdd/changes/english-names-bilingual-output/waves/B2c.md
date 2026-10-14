# Ola B2c: cuerpo de `local_commit_msg` y troceado de `local_explain_code`/`local_extract`

Cuarto PR de B2, en la rama `sdd/english-names-b2c` desde `origin/main` (`6e229a1`). Implementa
«#### B2c» de `plan.md` y las decisiones 7 y 8 de `waves/B2-proposal.md` §11, sobre las causas
medidas en `evidence/local-tools-review/report.md`. Resultado: suite **2927 passed, 2 skipped** con
`LANG=en_US.UTF-8` y `es_ES.UTF-8`, `ruff` limpio, guardián verde, los dos `--check` de corpus en
**ok** con sus avisos de frontera, **9 mutantes** que hacen fallar los **13** tests que los vigilan, y
detector de nombres **0 fuera de la lista y 0 sin clasificar**. Sin commit, push ni PR; nada contra el
daemon vivo salvo la prueba de `local_commit_msg` que pide el encargo (abajo).

## Qué se hizo

**`src/local_delegate/server.py`** (CRLF conservado):

- **Commit.** Formato de las dos variantes: «una línea en blanco y un cuerpo OBLIGATORIO de 2 a 6
  viñetas '- ' que digan qué cambia y para qué» (antes «cuerpo opcional»). El `_build_reduce` del
  troceado lo repite («con su primera línea y un cuerpo de 2 a 6 viñetas»). Topes en constantes:
  `COMMIT_MAX_TOKENS = 700` (antes 256) y `COMMIT_REDUCE_MAX_WORDS = 250` (antes 90; `_tokens(250)` =
  564). El parcial sigue en 350 palabras. El idioma sigue la regla de B2b-2 sin cambios.
- **`local_explain_code`.** Lee entera (`_NO_TRUNCATE`). Si cabe en el rol `code`, la llamada única
  de antes, byte a byte (prompt, `max_tokens=700`). Si no, `_chat_map_reduce`:
  - trozos de `_code_pieces`: `_split_by_top_level_defs` corta antes de cada `def`/`async def`/
    `class`/`@` en columna 0, sin cortar tras un decorador (también los de varias líneas); lo
    anterior a la primera definición es un trozo; `_pack` al presupuesto del map, y un trozo mayor
    cae a `_chunk_text`. Sin ninguna definición, `_chunk_text` directo (`pieces=None`).
  - map: «una viñeta por cada función o clase de este fragmento…» + orden de idioma.
  - reduce: el `system` de la llamada única (con `question` y orden de idioma, 250 palabras) y en el
    `user` el **inventario** `_format_names` (nombres de primer nivel calculados en el servidor,
    recortado con «y N más» al 25 % del presupuesto) delante de las notas.
- **`local_extract`.** Lee entera. Si cabe en su rol, la llamada de antes. Si no, `_chat_map_reduce`
  con `response_format` **en cada paso**, map con «null si no aparece», reduce por el modelo con schema
  («Combina los objetos parciales…») y atajo `_extract_shortcut`: si como mucho un parcial trae
  valores no nulos, ese es el resultado y no hay paso final (decisión 7).
- **Contrato (decisión 8).** `truncated`/`warning` = salida truncada en un trozo: en el troceado,
  `truncated_calls > 0`; en la llamada única, `finish_reason == "length"` (antes el aviso de `_chat`
  se pegaba al JSON y lo rompía). El texto es `mcp.warning.output_truncated_calls`. Salen también
  junto a `error`/`raw` si el JSON truncado no se pudo parsear. `mcp.receipt.input_truncated` queda
  sin uso y se borra de los dos catálogos.
- **Fontanería.** `_CurrentModel.call` acepta `response_format`/`json_schema_fallback` y guarda el
  estado del schema de la primera llamada; `_chat_map_reduce` acepta `response_format`,
  `json_schema_fallback`, `reduce_shortcut` y `report` (con `report` no pega nada al texto y deja
  `truncated_calls`, `calls`, `pieces` y `fallback` —con las claves del contrato, sin el trozo— en el
  dict; el log lleva `json_schema`); `_chat` acepta `report` (`truncated_out` en el dict en vez del
  aviso en el texto). Sin esos parámetros, todo igual que antes.

**`scripts/build_corpus.py`:** `local_commit_msg` entra en `PROMPT_BOUNDARIES["0.36.0"]` con su
motivo. Avisos nuevos: F2, 2 casos × (`system`, `max_tokens`); afinidad, 40 casos × 2.

**Tests:**

- `tests/test_commit_body_and_chunking.py` (nuevo, 15 tests, backend falso que captura `system`,
  `user`, `max_tokens` y `response_format`): cuerpo y topes del commit (llamada única, las dos
  variantes; paso final del troceado); `explain_code` con un módulo de ~60 000 caracteres y
  `def ZZZ_marker` al final (llega al backend, el inventario lo nombra, la pregunta va al paso final,
  ningún decorador separado de su función, orden de idioma en todos los pasos); llamada única sin
  cambios; `_split_by_top_level_defs` (invariante y decoradores), sin definiciones e inventario
  recortado; `extract` con el valor solo al final (sale, sin reduce, schema en todos los pasos),
  con valores en conflicto (reduce por el modelo con schema), `truncated` en el troceado y en la
  llamada única, y entrada grande sin `_local_delegate`.
- Actualizados con su motivo: `test_core.py::test_local_extract_warns_about_truncation_…` (ahora
  salida truncada), `test_tool_contract.py::test_extract_meta_uses_the_new_keys` (`_backend` con
  `finish`; salida truncada en el troceado), `test_corpus.py` (frontera con `max_tokens` además de
  `system`; afinidad con `local_commit_msg`; la regla de «entrada truncada» se prueba reproduciendo
  el camino de antes con `_NO_TRUNCATE` parcheado, y un test nuevo dice que `explain_code` grande
  ya no es de una llamada).
- `tests/data/uncatalogued_exceptions.json`: 3 prompts viejos sustituidos por los nuevos y 7 prompts
  nuevos con motivo (prompts del modelo, no interfaz; REQ-028 no los traduce).

**Documentación:** `CHANGELOG.md` (`[Unreleased]`: cuerpo, troceado y contrato incompatible),
`README.md` (CRLF), `docs/wiki/Tools.md` (tabla, `extract`, cuerpo del commit, `explain_code`),
`docs/wiki/Configuration.md` (el tope por rol ya no trunca en las tools que reducen; la sección del
contrato ya la había dejado B2b-1) y `docs/wiki/Savings-and-metrics.md`.

## Controles positivos (`evidence/B2c/mutants.md`)

Aplicados de verdad sobre el fichero, cada test con `pytest -x`, y restaurados (comprobado byte a
byte). Todos fallan por el assert que vigilan:

| Mutante | Test | Assert que dispara |
|---|---|---|
| M1a formato de hoy («cuerpo opcional») | llamada única y paso final | `BODY in …["system"]` |
| M1b topes de hoy (256 / 90) | llamada única y paso final | `256 >= 700`; `244 >= 564` |
| M2 `explain_code` por el camino de hoy | fichero de 60 000 | `def ZZZ_marker` en algún `user` |
| M3 `extract` por el camino de hoy | valor solo al final | `None == 'ZZZ_value'` |
| M4 sin atajo de `extract` | valor solo al final | «redujo sin necesidad» |
| M5 sin inventario en el paso final | fichero de 60 000 | «el inventario no lo nombra» |
| M6 `truncated` sin la salida truncada | troceado y llamada única | `KeyError: '_local_delegate'` |
| M7 corte entre decorador y función | `_split…` y `explain_code` | lista de cabeceras; `count("@decorator(")` |
| M8 frontera sin `local_commit_msg` | corpus F2 | `check_versioned(...) == []` |

El primer M7 (quitar la guarda de decoradores de la condición exterior) **no mutaba nada**: la guarda
era redundante con la interior. Se simplificó el código y el mutante pasó a ser «cortar también tras
un decorador». El test de integración sobrevivía con el `startswith`, que acepta un trozo que empieza
en `def`; se le añadió la cuenta de decoradores y funciones por trozo, y ahora falla.

## Corridas

- `evidence/B2c/suite-en.txt` y `suite-es.txt`: 2927 passed, 2 skipped (solo 2 `DeprecationWarning`
  de `anyio` en `testclient.py`, resumido con `local_lint_summary`).
- `evidence/B2c/corpus-f2-check.txt` (13 avisos, 4 de commit) y `corpus-affinity-check.txt` (85
  avisos, 80 de commit): los dos **ok**.
- `evidence/B2c/detector.txt`/`.json`: 0 fuera de la lista, 0 sin clasificar (corrido al final).
  La primera pasada dio **8 palabras sin clasificar**, todas inglesas de este lote (`decorator`,
  `decorators`, `definitions`, `defs`, `partials`, `room`, `shortcut` y `zzz` de `ZZZ_marker`): se
  clasificaron a mano en `scripts/data/spanish_lexicon.json` (`en`, orden y sangría conservados) y
  se anotó en el punto 8 de `spanish_lexicon.README.md`, como en A-close-5. Desviación de
  propiedad: esos dos ficheros no estaban en la lista de B2; tras el cambio,
  `test_detect_spanish_names.py`, `test_tool_contract.py` y el guardián siguen verdes (79 passed).
- `ruff check .` y `ruff format --check .` limpios; `tests/test_no_uncatalogued_text.py` verde.

## Observaciones y desviaciones

- **La primera corrida de la suite** (antes de ajustar tests) dio 6 fallos, todos esperados: el
  guardián (prompts nuevos), las tres pruebas que fijaban «entrada truncada» en `extract` y la regla
  de corpus que usaba `explain_code` como ejemplo de truncado. No se guardó aparte.
- **`truncated` en la llamada única de `extract`** es un caso nuevo: el plan habla del troceado, pero
  sin él la llamada única seguiría pegando el aviso al JSON y la decisión 8 quedaría a medias.
- **Docstrings de las tools sin cambios**: el de `local_extract` ya decía `truncated` y `warning` sin
  atarlos a la entrada, así que `tools.json` y `test_tool_contract.py` no cambian.
- **CHANGELOG**: `[Unreleased]` estaba vacío (B2a–B2b-2 no escribieron entradas); B2c deja solo las
  suyas, porque la decisión 8 pide anunciar el contrato. El PR de release completará el resto.
- **CodeQL**: sin lambdas que solo envuelvan una llamada (la de `build_reduce` arma un texto), sin
  imports ni globales sin uso (`_TOP_LEVEL_START`, `_TOP_LEVEL_NAME`, `_EXTRACT_WORDS` y las dos
  constantes del commit se usan), sin ciclos nuevos. Ningún `.py` en `evidence/`.

## Prueba de `local_commit_msg` sobre el diff de este lote

`local_commit_msg(path=<diff de 61 321 bytes, 14 ficheros>)` contra el daemon instalado (0.35.0, sin
B2b-2 ni B2c) devolvió, en 5 partes y 6 pasadas:

```
feat(server): implement map-reduce and mandatory commit body

- replace input truncation in local_extract and local_explain_code
  with map-reduce chunking to process full input
- enforce mandatory commit body in local_commit_msg with increased
  limits
- remove input_truncated i18n keys as truncation is no longer used
- update docs and tests to reflect map-reduce behavior and new
  commit constraints
```

Esta vez con cuerpo, pero en inglés (la 0.35.0 aún usa «el idioma predominante del diff») y sin el
`!` del contrato incompatible. `waves/B2c-commit-msg.txt` se redactó a mano en español a partir de
esto. La muestra en vivo con el código nuevo es de B2d.

## Llamadas `local_*`

| # | Llamada | Para qué | Resultado |
|---|---|---|---|
| 1 | `local_summarize(path=waves/B2b-2.md, focus=…)` | estructura del informe, cómo se corrió el detector y las corridas | sirvió para el formato; el comando literal del detector salió de `evidence/B2b-2/detector.txt` |
| 2 | `local_lint_summary(path=evidence/B2c/suite-en.txt)` | resumir la corrida | 2 `DeprecationWarning`, ningún fallo |
| 3 | `local_commit_msg(path=<diff>)` | borrador del commit | arriba |

## Llamadas `mcp__pycharm__*`

| # | Tool | Motivo |
|---|---|---|
| 1 | ninguna | motivo: B2c no renombra nada (sin mapping); las búsquedas las hizo `grep` y la comprobación de problemas `ruff check` y la suite entera; PyCharm es recurso único sobre el checkout principal |

**Pasos hechos a mano y por qué:** las franjas de `server.py` (`_CurrentModel`, `_chat`,
`_chat_map_reduce`, `_read_input`, prompts y las tres tools) se leyeron con `Read` porque había que
editarlas y citar literales; `local_explain_code`/`local_extract` no sirven sobre `server.py`
(truncan a 20 000 en la 0.35.0, justo lo que arregla este lote) y el resumen no conserva literales.
`plan.md` y `B2-proposal.md` se leyeron por franjas con `grep`: son la norma. Los fallos de la primera
corrida se leyeron con `grep` de las líneas `FAILED`/`E` (6 fallos, hacía falta el texto exacto del
guardián para catalogar). Los mutantes y el catálogo de excepciones los aplicó un script (programa,
no modelo).
