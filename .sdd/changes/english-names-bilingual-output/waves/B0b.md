# Ola B0b — Guardián de textos fuera del catálogo y detector de idioma

Segunda mitad de B0 (frente B), tras B0a (#309, `5660228`). Rama `sdd/english-names-b0b`, sobre
`origin/main` `5660228`. Sin commit ni push: los hace la sesión principal.

- **REQ:** 045 (nace con su lista de pendientes) y el detector de D10.
- **Resultado:** suite **2739 passed, 2 skipped** con `LANG=en_US.UTF-8` y **2739 passed,
  2 skipped** con `LANG=es_ES.UTF-8` (B0a dejó 2706 tests; 35 nuevos); `ruff check` y
  `ruff format --check` limpios; detector de nombres del frente A con **0 fuera de la lista y 0
  palabras sin clasificar**; 15 controles positivos, los 15 disparan el assert esperado.

## 1. Qué se hizo

| Fichero (todos nuevos, LF) | Contenido |
| --- | --- |
| `tests/test_no_uncatalogued_text.py` | El guardián de REQ-045: escáner AST con dos redes (contextos de salida y tildes), las reglas de pendientes y excepciones, y los tests del clasificador sobre código sintético (25 tests) |
| `tests/data/uncatalogued_pending/{cli,doctor,mcp,hooks,panel,install}.json` | `{"surface", "owner", "files"}` por superficie, con la ola dueña de D5: 17 ficheros en `cli` (B1, con los tres scripts y `recompute.py`, `probes.py`, `deprecations.py` y `entrypoint.py`), 2 en `doctor` (B1), 5 en `mcp` (B2, con `questions.py`), 4 en `hooks` (B3), 4 en `panel` (B4, con `quota.py`, `valuation.py` y `attribution.py`) y 3 en `install` (B5) |
| `tests/data/uncatalogued_exceptions.json` | `files`: `scripts/medir_enfriamiento.py` (envoltorio de REQ-046 que se retira tras P-4) y `src/local_delegate/legacy_names.py` (valores viejos de la lectura dual, nunca salida); `texts`: las cabeceras HTTP `Authorization`, `Bearer {}` (`config.py`) y `Basic realm=…` (`web/auth.py`) |
| `scripts/detect_language.py` | `detect(text, min_tokens=20, min_margin=0.15, words=None) -> Detection(lang, tokens, es_ratio, en_ratio)` y una CLI que imprime una línea JSON por fichero. Stdlib, con shebang y bit de ejecución (ya en el índice con `git add --chmod=+x`) |
| `scripts/data/function_words.json` | 172 palabras funcionales en español y 156 en inglés, disjuntas; fuera las compartidas (`a`, `no`, `me`, `era`, `come`, `os`) |
| `tests/data/detect_language_control.json` | Control congelado: 20 frases de `docs/wiki` y 20 del diccionario `en` de `site/index.html`, elegidas por una regla fija (8 a 40 palabras, al menos 8 corrientes y el 70 % o más) |
| `tests/test_detect_language.py` | Control (≥ 97,5 %), listas invertidas, listas disjuntas, umbral de tokens, margen, decisión y CLI (10 tests) |

Existentes: `plan.md` (condición del control del detector, abajo) y
`scripts/data/spanish_lexicon.json` (11 palabras inglesas nuevas: `accuracy`, `contract`,
`disjoint`, `implemented`, `leading`, `nodes`, `owners`, `scanner`, `stmt`, `swapped`,
`uncatalogued`).

Tamaño: 1 244 líneas nuevas (de ellas ~330 de las listas de palabras y ~170 de datos de control) y
+27/−8 en 2 ficheros existentes. El plan enmendado estimaba ~900.

### El guardián

- **Alcance:** `src/local_delegate/**` (sin `vendor/`) y `scripts/measure_cooldown.py`,
  `pair_sheet.py` y `analyze_benchmark.py`, menos los ficheros excluidos con motivo.
- **Red de contextos:** literales y partes fijas de f-strings en (1) argumentos de `print`,
  `write`, `exit`, `error`, `warn`, `emit`, `deny`, `append`, `extend` y `echo`; (2) `raise`;
  (3) argumentos `help`, `description`, `epilog`, `title`, `usage`, `remedy`, `detail`, `message`,
  `reason`, `hint`, `label` y `summary`; (4) `return`; (5) constantes de módulo o de clase cuyo valor
  es un literal. Es texto para personas si tiene dos o más palabras corrientes, o una sola con
  mayúscula o tilde («Latencia», «Hola»). Una palabra suelta en minúsculas y ASCII es un valor de
  enumeración; lo que lleva `_ . / = { } %`, dígitos, `camelCase`, MAYÚSCULAS, o empieza por punto
  o guion (`.md`, `--flag`) es de máquina. Las claves de `t`/`t_lang` y los docstrings no cuentan.
- **Red por tildes:** cualquier literal (no docstring) con `áéíóúñ¿¡`, en cualquier contexto.
- **Reglas:** fuera de pendientes y excepciones, cero apariciones; listas bien formadas (seis
  superficies, dueña de D5, ordenadas, sin repetir, dentro del alcance); cada pendiente con al menos
  una aparición; `web/metrics.py` pendiente mientras `PANEL_SCANNER_IMPLEMENTED = False` (lo cambia
  B4 con su escáner); excepciones de texto vivas, con clase y motivo y sin prosa (salvo un prefijo
  de contrato de la lista cerrada); ficheros excluidos que existen, con motivo y no pendientes.
- `agents.py` va en `install.json` porque el escáner le ve texto; `record_call.py` no entra porque
  no tiene ninguno (si se pusiera, la regla de «al menos una aparición» lo rechaza: mutante G6).

### El detector y su control

**Medida, en este orden:** con las listas tal como se escribieron, el control dio **38/40**
(95 %); con las listas invertidas, **0/40**. Los dos fallos, los dos `unknown`:

- «Ambos proyectos publican en *rolling release* (llama.cpp etiqueta casi cada merge; …)»:
  12,5 % de palabras funcionales, por debajo del margen de 0,15;
- «Summarize a file, classify a prompt, write a commit message from a diff.»: su palabra funcional
  es «a», compartida por los dos idiomas y fuera de las listas.

**Ajuste aprobado por la sesión principal (opción 1, 2026-10-14):** se añadieron «ambos» y «casi»
a la lista española (39/40), no se metió «a» ni se cambió el margen, y en B0b se exige como mucho un
fallo en 40 (`MIN_ACCURACY = 0.975`).

**Condición:** como esas dos palabras salieron del propio control, **las 40 frases de B0b dejan de
ser un control independiente**. El control de verdad es el de **B1**: 60 + 60 frases **nuevas**,
congeladas antes de ver la lista, con ≥ 98 % (como mucho 2 fallos en 120). En B1 ya no se ajustan
las listas a la vista de los fallos; si no llega, se decide en B1. Queda escrito en el plan (D10 y
B0b), en el `_about` de `function_words.json`, en el del control y en el docstring del test.

## 2. Controles positivos

Cada mutante se aplicó sobre el fichero, se corrió su test, se anotó el assert y se restauró el
fichero byte a byte. Salida completa en `evidence/B0b/mutants.txt`.

| Mutante | Test | Assert que dispara |
| --- | --- | --- |
| G1 `print("Hola")` en `config.py` (no pendiente) | `test_no_uncatalogued_text_outside_pending` | `config.py:570 [context] 'Hola'` |
| G2 `raise ValueError("Latencia")` en `i18n.py` | ídem | `i18n.py:39 [context] 'Latencia'` |
| G3 `_PROBE = str("ubicación")` en `cost.py` (fuera de todo contexto) | ídem | `cost.py:21 [accent] 'ubicación'`: solo la red por tildes |
| G4 excepción `"Hola mundo"` | `test_text_exceptions_are_live_and_machine_text` | «es texto para personas, no una excepción» (y «caducada») |
| G5 `entrypoint.py` fuera de `cli.json` | `test_no_uncatalogued_text_outside_pending` | `entrypoint.py:45 [context] 'local-delegate: sin subcomando…'` |
| G6 `record_call.py` en `hooks.json` | `test_every_pending_file_is_seen_by_the_scanner` | `pendientes sin ninguna aparición: [...record_call.py]` |
| G7 `metrics.py` fuera de `panel.json` | `test_the_panel_stays_pending_until_its_scanner_exists` | `'src/local_delegate/web/metrics.py' in [...]` |
| G8 fichero excluido que no existe | `test_file_exceptions_are_live_and_have_a_reason` | `scripts/medir_enfriamiento_viejo.py: ya no existe` |
| G9 el clasificador pierde el contexto `return` | `test_text_in_an_output_context_is_caught` | `[] != []` en `return f"{n} acciones fallaron"` |
| G10 `legacy_names.py` deja de estar excluido | `test_no_uncatalogued_text_outside_pending` | `legacy_names.py:301 'sin base'`, `:507 'cota baja'`… |
| G11 dueña `B2` en `cli.json` | `test_the_pending_lists_are_well_formed` | `'B2' == 'B1'` |
| D1 listas invertidas | `test_the_detector_passes_its_control` | `0.0 >= 0.975` |
| D2 sin «ambos» ni «casi» | ídem | `0.95 >= 0.975` (la medida de antes del ajuste) |
| D3 margen mínimo a 0 | `test_a_small_margin_is_unknown` | `'es' == 'unknown'` |
| D4 «a» en la lista inglesa | `test_the_lists_are_disjoint_and_big_enough` | `not ({'a', …} & …)` |

D3 se repitió: en la primera pasada disparó el assert equivocado (el test comparaba con
`detect_language.MIN_MARGIN`, que el propio mutante cambia). El test escribe ahora el 0,15 de D10
como literal, y el mutante cae en el assert del comportamiento (`'es' == 'unknown'`). G3 se repitió
con un ancla única (la primera, `return "assumed"`, aparece dos veces en `cost.py` y el mutante no
se aplicó).

## 3. Corridas

| Corrida | Resultado | Log |
| --- | --- | --- |
| Suite, `LANG=en_US.UTF-8`, `-n 4 --dist loadgroup`, bajo `pesado.sh` | 2739 passed, 2 skipped, 4 warnings (las `DeprecationWarning` de starlette de siempre) | `evidence/B0b/pytest-en.log` |
| Suite, `LANG=es_ES.UTF-8`, igual | 2739 passed, 2 skipped, 4 warnings | `evidence/B0b/pytest-es.log` |
| `ruff check .` y `ruff format --check .` | limpios (204 ficheros) | — |
| Detector de nombres con `rename-exceptions.md` | 0 fuera de la lista, 0 sin clasificar | `evidence/B0b/detector.txt` |

En Windows las dos corridas no discriminan (plan §4.2); la que sí lo hace es `test-lang-es` en el CI
del PR.

## 4. Desviaciones

- **Control del detector** con ≥ 97,5 % y dos palabras añadidas a la vista de los fallos, con la
  condición de arriba (aprobado por la sesión principal).
- **`legacy_names.py` excluido entero** del guardián (no estaba en la propuesta): sus literales en
  español son los valores viejos que se leen de disco para siempre («cota baja», «solo
  comprobación», «avisó»), no salida. Una excepción por texto no servía porque son prosa, y el test
  de excepciones rechaza la prosa a propósito.
- **Constantes de módulo como contexto**, restringidas a valores literales (no llamadas): así
  entran los rótulos de `valuation.py` y `quota.py` sin que cuente cualquier `x = f("…")`.
- **Léxico del frente A:** 11 palabras inglesas nuevas, y el fichero de prueba del test de la CLI
  se llama `sample.txt` (el detector marcaba `muestra.txt`).

## 5. Pendientes para las olas siguientes

- **B1:** el control independiente del detector (60 + 60 frases nuevas, ≥ 98 %, sin ajustar las
  listas); vaciar `cli.json` y `doctor.json`.
- **B2, B3 y B5:** vaciar `mcp.json`, `hooks.json` e `install.json`. B3 tendrá que excepcionar las
  partes de ruta de `hook_common.log_dir` («Local», «Library», «Application Support»).
- **B4:** escribir el escáner del panel (JS y HTML de `metrics.py`), poner
  `PANEL_SCANNER_IMPLEMENTED = True` con su control positivo y vaciar `panel.json`.
- Al cerrar P-4 y borrar `scripts/medir_enfriamiento.py`, su entrada de excepciones falla y se quita.

## 6. Llamadas `local_*`

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente B0b | `local_lint_summary(path=pytest-en.log)` | resumen de la corrida en inglés: solo las `DeprecationWarning` de starlette |

Total: **1**. El resto del trabajo era escribir código y medir con scripts pequeños sobre el AST y
el detector, sin ficheros grandes que resumir. El mensaje de commit se redactó a mano:
`local_commit_msg` lo dio en inglés y en una línea en B0a. No se usaron tools de PyCharm.
