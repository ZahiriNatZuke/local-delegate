# Ola A9b — Tests `e*`–`p*`

La subola se parte en 6 lotes (D13: 1507 filas, como mucho 300 por lote y sin partir un módulo):
`A9b-1-mapping.csv` a `A9b-6-mapping.csv` (en `waves/`), aprobados por la sesión principal el
2026-10-13 con las 8 decisiones de la fase 1 tal como se recomendaron. Cada lote es un commit que
hace la sesión principal, en una rama apilada sobre el anterior. Las tablas de controles positivos,
`local_*` y PyCharm son las de todos los lotes, porque `check_wave_records.py` lee la primera tabla
de cada sección; por ahora están los **lotes 1 a 3**: 17 + 25 + 23 = 65 filas `rename_refactoring` =
65 filas `pycharm` de `waves/A9b-1-mapping.csv`, `waves/A9b-2-mapping.csv` y `waves/A9b-3-mapping.csv`.

- Rama: lote 1 en `sdd/english-names-a9b-1`, apilada sobre `sdd/english-names-a9a-7` (`76fe954`, A9a
  completa), commit `5fae972`; lote 2 en `sdd/english-names-a9b-2`, commit `c3ed701`; lote 3 en
  `sdd/english-names-a9b-3`, sobre `c3ed701` · Commit del lote 3: pendiente, con el borrador en
  `waves/A9b-3-commit-msg.txt` (firmado y sin coautoría)
- Quién: un agente hizo los 6 mappings (fase 1) y, tras la aprobación, aplicó los lotes 1 a 3 (fase 2).
- Conteo base: `evidence/A9b/collect-before.txt`, 2569 tests.

## Controles positivos

| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_cooldown.py::test_three_consecutive_failures_cool_the_model_for_120_s` (lote 1; usa la fixture renombrada `clock`/`path`, `_state` y `_fail`) | `src/local_delegate/cooldown.py:167`: `>= self._failures` → `> self._failures` (enfría al fallo N+1) | `assert cooled is not None` → `assert None is not None` | sí, desde copia; sha256 igual al de antes (`evidence/A9b-1/mutant.txt`) |
| `tests/test_failure_captures.py::test_the_timeout_during_loading_is_capacity` (lote 1; usa `_capture`, `_classify_capture` y las claves nuevas del envoltorio) | en `_classify_capture`, la guarda vuelve a la clave vieja (`"excepcion" in doc`), que es el error que dejó el primer reemplazo | `KeyError: 'response'` en `doc["response"]` | sí, desde copia; sha256 igual |
| `tests/test_cooldown.py` (40 tests) | `_fail` registra un fallo menos (`range(times - 1)`) | 7 fallan; el primero, `assert cooled is not None` | sí, desde copia; sha256 igual |
| `tests/test_hook_common.py::test_a_401_means_the_backend_IS_there` (lote 2; usa la anidada renombrada `_raises_401` y `_mark`/`age_s`) | `src/local_delegate/resources/hooks/hook_common.py:241`: un `HTTPError` (401) cuenta como «no hay backend» (`return True` → `return False`) | `assert common.backend_available(marker=…) is True` → `assert False is True` | sí, desde copia; sha256 igual (`evidence/A9b-2/mutant.txt`) |
| `tests/test_failure_captures.py::test_the_oom_without_profile_did_not_reach_timeout_and_stays_uncaptured` (assert negativo del lote 1 con la clave renombrada `exception`) | la captura `oom-without-profile.json` gana una clave `"exception"` | `assert "exception" not in doc` | sí, desde copia; sha256 igual |
| `tests/test_hooks_telemetry_api.py::test_counts_suggested_over_the_total` (lote 3; usa `_event(…, suggested=…)` con los kwargs renombrados) | `src/local_delegate/web/metrics.py:615`: `_aggregate_hooks` deja de sumar las sugeridas (`suggested_total += suggested` → `+= 0`) | `assert aggregate["suggested"] == 2` → `assert 0 == 2` | sí, desde copia; sha256 igual (`evidence/A9b-3/mutant.txt`) |

## Llamadas `local_*` (sesión principal y cada agente)

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente A9b (fase 1) | `local_summarize(path=waves/A9a.md)` | lecciones y desviaciones de los 7 lotes de A9a, sin meter las 592 líneas al contexto |
| Agente A9b-1 | `local_lint_summary(path=evidence/A9b-1/pytest-full-run1.log)` | resumen de la primera corrida de la suite (3 fallos: 1 real del lote y 2 de tiempos de `test_fake_llamaswap`) |
| Agente A9b-2 | (ninguna) | la suite salió verde a la primera (47 líneas de log) y los ficheros se leyeron por franjas concretas: no hubo nada largo que resumir |
| Agente A9b-3 | (ninguna) | suite verde a la primera; los ficheros se leyeron por franjas y las comprobaciones de cadenas las hizo un script AST: nada largo que resumir |

## Llamadas `mcp__pycharm__*`

| Agente | Tool | Símbolo / fichero | Resultado |
| --- | --- | --- | --- |
| A9b-1 | `rename_refactoring` | `INICIO`→`START` (`test_enfriamiento.py`) | 7 usos |
| A9b-1 | `rename_refactoring` | `Reloj`→`Clock` | 2 usos |
| A9b-1 | `rename_refactoring` | `avanzar`→`advance` | 15 usos |
| A9b-1 | `rename_refactoring` | fixture `reloj`→`clock` | 83 usos (arrastra los 32 parámetros que la piden) |
| A9b-1 | `rename_refactoring` | fixture `ruta`→`path` | 96 usos (ídem; no toca los parámetros locales `ruta` de los ayudantes) |
| A9b-1 | `rename_refactoring` | `_estado`→`_state` | 34 usos |
| A9b-1 | `rename_refactoring` | `_fallar`→`_fail` | 48 usos |
| A9b-1 | `rename_refactoring` | `_eventos`→`_events` | 11 usos |
| A9b-1 | `rename_refactoring` | `_viejo`→`_old` | 2 usos |
| A9b-1 | `rename_refactoring` | `_nuevo`→`_new` | 6 usos |
| A9b-1 | `rename_refactoring` | `_mismo_estado`→`_same_state` | 4 usos; reescribió `waves/A4.md` (devuelto a HEAD) |
| A9b-1 | `rename_refactoring` | `_escribir`→`_write` | 3 usos, solo en su fichero |
| A9b-1 | `rename_refactoring` | `_respuesta_http`→`_http_response` (`test_fallos.py`) | 6 usos |
| A9b-1 | `rename_refactoring` | `_cuerpo`→`_body` | 11 usos |
| A9b-1 | `rename_refactoring` | `_captura`→`_capture` (`test_fallos_capturas.py`) | 6 usos |
| A9b-1 | `rename_refactoring` | `_modelo_cargado_al_terminar`→`_model_loaded_at_end` | 3 usos |
| A9b-1 | `rename_refactoring` | `_clasificar_captura`→`_classify_capture` | 5 usos |
| A9b-1 | `get_file_problems` | `test_cooldown.py`, `test_failures.py`, `test_failure_captures.py` | 0 errores salvo `Unresolved reference 'FileLock'` en la cadena de `monkeypatch.setattr(cooldown, "FileLock", …)`: falso positivo que ya existía (el atributo se resuelve en tiempo de ejecución) |
| A9b-2 | `rename_refactoring` | `sin_preguntar→without_asking` (fixture, `test_fallos_integracion.py`) | 8 usos |
| A9b-2 | `rename_refactoring` | `_salida→_output` (`test_hook_common.py`) | 2 usos |
| A9b-2 | `rename_refactoring` | `antiguedad_s→age_s` (parámetro de `_marca`) | 2 usos |
| A9b-2 | `rename_refactoring` | `_marca→_mark` | 3 usos |
| A9b-2 | `rename_refactoring` | `casa→home_env` (fixture, `test_hook_legacy_names.py`) | 5 usos |
| A9b-2 | `rename_refactoring` | `temporal→temp_dir` (fixture) | 10 usos |
| A9b-2 | `rename_refactoring` | `_correr_hook_instalado→_run_installed_hook` | 4 usos |
| A9b-2 | `rename_refactoring` | `_ultimo_evento→_last_event` | 3 usos |
| A9b-2 | `rename_refactoring` | `_evento→_event` | 6 usos |
| A9b-2 | `rename_refactoring` | `relleno→padding` (parámetro de `_escribir_telemetria`) | 2 usos |
| A9b-2 | `rename_refactoring` | `_escribir_telemetria→_write_telemetry` | 2 usos |
| A9b-2 | `rename_refactoring` | `_EVENTOS_SISTEMA→_SYSTEM_EVENTS` (`test_hook_recipes.py`) | 2 usos |
| A9b-2 | `rename_refactoring` | `_correr_hook→_run_hook` | 12 usos |
| A9b-2 | `rename_refactoring` | `_correr_con_bloqueo→_run_with_block` | 5 usos |
| A9b-2 | `rename_refactoring` | `_evento_de_prompt→_prompt_event` | 1 usos |
| A9b-2 | `rename_refactoring` | `_default_del_hook→_hook_default` | 3 usos |
| A9b-2 | `rename_refactoring` | `bloquear→block` (parámetro de `_correr`, `test_hook_shell.py`) | 2 usos |
| A9b-2 | `rename_refactoring` | `_correr→_run` | 12 usos |
| A9b-2 | `rename_refactoring` | `documento→document` (fixture) | 14 usos |
| A9b-2 | `rename_refactoring` | `_motivos→_reasons` | 2 usos |
| A9b-2 | `rename_refactoring` | `TEXTO_READ→READ_TEXT` (`test_hook_shell_ruta_absoluta.py`) | 2 usos |
| A9b-2 | `rename_refactoring` | `TEXTO_SHELL→SHELL_TEXT` | 2 usos |
| A9b-2 | `rename_refactoring` | `_entorno→_env` (fixture autouse: nadie la pide por nombre) | 0 usos |
| A9b-2 | `rename_refactoring` | `_razon→_reason` | 3 usos |
| A9b-2 | `rename_refactoring` | `documento→document` (fixture) | 7 usos |
| A9b-2 | `get_file_problems` | `test_hook_recipes.py`, `test_hook_shell_absolute_path.py`, `test_failures_integration.py` | 0 errores propios: solo `Unresolved reference` en cadenas de `monkeypatch.setattr` sobre hooks cargados con `importlib` (`record`, `backend_available`, `cooled_model`), que ya estaban |
| A9b-3 | `rename_refactoring` | `_evento→_event` (`test_hooks_telemetry_api.py`) | 16 usos |
| A9b-3 | `rename_refactoring` | `_escribir→_write` | 3 usos |
| A9b-3 | `rename_refactoring` | `_etiquetas_js→_labels_js` | 2 usos |
| A9b-3 | `rename_refactoring` | `_extraer_funcion_js→_extract_js_function` | 8 usos |
| A9b-3 | `rename_refactoring` | `_evento_de_lectura→_read_event` | 11 usos |
| A9b-3 | `rename_refactoring` | `_filas_de_lectura→_read_rows` | 3 usos |
| A9b-3 | `rename_refactoring` | `_sin_cache→_without_cache` (fixture autouse) | 0 usos |
| A9b-3 | `rename_refactoring` | `_simular_instalacion_034→_simulate_install_034` (`test_install.py`) | 1 usos |
| A9b-3 | `rename_refactoring` | `_comando_del_hook_de_read→_read_hook_command` | 2 usos |
| A9b-3 | `rename_refactoring` | `_con_huerfanos→_with_orphans` | 7 usos |
| A9b-3 | `rename_refactoring` | `_comando_del_hook_de_shell→_shell_hook_command` | 1 usos |
| A9b-3 | `rename_refactoring` | `_CODEX_REESCRITO_POR_OTRO→_CODEX_REWRITTEN_BY_OTHER` | 5 usos |
| A9b-3 | `rename_refactoring` | `_claude_escribe→_claude_write` (`test_install_cabecera.py`) | 1 usos |
| A9b-3 | `rename_refactoring` | `_claude_lee→_claude_read` | 2 usos |
| A9b-3 | `rename_refactoring` | `_codex_escribe→_codex_write` | 1 usos |
| A9b-3 | `rename_refactoring` | `_codex_lee→_codex_read` | 1 usos |
| A9b-3 | `rename_refactoring` | `_opencode_escribe→_opencode_write` | 1 usos |
| A9b-3 | `rename_refactoring` | `_opencode_lee→_opencode_read` | 1 usos |
| A9b-3 | `rename_refactoring` | `CLIENTES→CLIENTS` | 12 usos |
| A9b-3 | `rename_refactoring` | `_home_con→_home_with` | 8 usos |
| A9b-3 | `rename_refactoring` | `espia_claude→claude_spy` (fixture, `test_install_clients.py`) | 6 usos |
| A9b-3 | `rename_refactoring` | `_codex_a_mano→_codex_by_hand` | 2 usos |
| A9b-3 | `rename_refactoring` | `_prepara_codex_a_mano→_prepare_codex_by_hand` | 6 usos |
| A9b-3 | `get_file_problems` | `test_install_header.py`, `test_install_clients.py`, `test_hooks_telemetry_api.py` | 0 errores |

## A9b-1 — capturas de `tests/fixtures/backend`, `test_enfriamiento`, `test_fallos` y `test_fallos_capturas` (aplicado)

### A9b-1 · Qué se hizo

- 17 `rename_refactoring` (tabla de arriba), en los ficheros con su nombre viejo y antes de cualquier
  edición desde fuera (lección de A5b-1).
- `make_mapping.py apply` con una copia del CSV cuyas definiciones llevan ya los ámbitos renombrados
  por PyCharm (`Reloj.avanzar` → `Clock.advance`…; si no, `apply` no encuentra la función): 232 + 65 +
  47 = 344 reemplazos.
- A mano (`apply` no lo hace): la clase anidada `BloqueoOcupado`→`BusyLock`, la anidada
  `sin_disco`→`without_disk`, los argnames de 6 `parametrize` (`neutra`, `excepcion` ×3, `datos`,
  `viejo,nuevo`, `nombre`), el atributo `ahora`→`now` y los parámetros `reloj` de `_estado` y
  `clase`/`estado`/`modelo` de `_fallar`, con los 3 kwargs `clase=`→`failure_class=` de sus llamadas.
- `git mv` de 3 módulos (`test_cooldown.py`, `test_failures.py`, `test_failure_captures.py`) y de
  las 6 capturas (`load-error.json`, `length-with-reasoning.json`, `oom-with-profile.json`,
  `oom-without-profile.json`, `request-during-load.json`, `timeout-during-load.json`); dentro de
  ellas, 13 claves del envoltorio y el valor de `case` (67 cambios); en el test, 24 lecturas y nombres
  de captura. Los ids de modelo `cap-*` no se tocan (son los de la captura real).
- `ruff format` reflowó una línea de `test_cooldown.py` (`10 ** 7` cabe ahora en una línea).
- EOL: los ficheros tocados son LF y siguen LF (`git ls-files --eol`).

### A9b-1 · Fuera del lote (consecuencia mecánica, aprobada)

- `src/local_delegate/failures.py:73`: cita `tests/test_failure_captures.py`.
- `tests/test_fallos_integracion.py:5` (lote 2): cita `test_failures.py` en su docstring.

### A9b-1 · Barrido final

- AST de los 3 ficheros: ningún nombre de código con un `old` del lote; las cadenas con una clave
  vieja del envoltorio, 0.
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 67 en
  textos (38 docstrings, 17 comentarios y 12 cadenas): prosa en español y valores de prueba.
  Ninguna cita entre comillas invertidas de un nombre renombrado.
- En todo el repo (fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`): `test_enfriamiento`,
  `test_fallos_capturas`, `BloqueoOcupado`, `_clasificar_captura`, `muestras_running`,
  `clase_esperada`… 0. Quedan `cap-error-carga` y `cap-oom-con-perfil` dentro de las capturas: son
  ids de modelo, datos (decisión 7).
- `--collect-only`: 2569 (`evidence/A9b-1/collect.txt`), los mismos 40 + 50 + 10 tests por módulo.
- Suite: 2567 passed, 2 skipped (`evidence/A9b-1/pytest-full.log`). `ruff check` y
  `ruff format --check` en verde (`evidence/A9b-1/ruff-check.txt`).
- CodeQL (aproximación AST de `a9b/codeql_like.py` sobre los 3 ficheros renombrados): 0 patrones.
  Los dos `except OSError: pass` con comentario de la fase 1 están en `test_panel_coste.py:486` y
  `test_precios.py:201`: no son de este lote, se miran en el lote que renombra esos ficheros.

### A9b-1 · Desviaciones

1. **37 filas `pycharm` → `search_edit`**, anotado en la línea `# Fase 2` del CSV: los 32 parámetros
   `reloj` de los tests (los arrastró el `rename_refactoring` de la fixture), el atributo homónimo
   `ahora` (también existe en `_Mezcla` de `test_metrics.py`) y los parámetros homónimos de `_estado`
   y `_fallar`.
2. **Una clave del envoltorio se escapó al reemplazo por `["clave"]`**: `if "excepcion" in doc` en
   `_classify_capture` y `assert "excepcion" not in doc`. La primera hizo fallar
   `test_the_timeout_during_loading_is_capacity` (`KeyError: 'response'`). La segunda **pasaba**
   igual y había dejado de comprobar nada. Se cambiaron las dos. Lección para los lotes siguientes:
   buscar también `"clave" in` / `not in`, no solo `["clave"]` y `.get(`.
3. Primera corrida de la suite: además, 2 fallos de tiempos en `test_fake_llamaswap.py`
   (`t_unload` 4,23 > 4,0 y un 500 en vez de 502 bajo carga). Pasaron sueltos y en la segunda
   corrida completa; no son de este lote (`evidence/A9b-1/pytest-full-run1.log`).

## A9b-2 — `test_fallos_integracion`, `test_hook_common`, `test_hook_legacy_names`, `test_hook_recipes`, `test_hook_shell` y `test_hook_shell_ruta_absoluta` (aplicado)

### A9b-2 · Qué se hizo

- 25 `rename_refactoring` (tabla de arriba), antes de cualquier edición desde fuera. PyCharm no tocó
  `.sdd/` esta vez.
- `make_mapping.py apply` con la copia del CSV con los ámbitos ya renombrados (`a9b/requal.py`):
  54 + 75 + 99 + 128 + 33 + 24 = 413 reemplazos.
- A mano: el `def` de las anidadas `espia`→`spy` y `_lanza_401`→`_raises_401`, la clase anidada
  `_Respuesta`→`_Response` y los argnames de 4 `parametrize` (`preparar`, `plantilla`, `comando` ×2).
- Fuera del CSV, por el barrido de parámetros de lambdas: `lambda modelo: False` → `lambda model:
  False` en `test_hook_shell_absolute_path.py:67` (doble de `cooled_model(model)`, que se llama
  posicional).
- `git mv` de 2 módulos: `test_failures_integration.py` y `test_hook_shell_absolute_path.py`. Nadie
  los cita por ruta fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`.
- `ruff format` juntó en una línea 4 llamadas y firmas que ya caben (`test_hook_legacy_names.py`,
  `test_hook_recipes.py`, `test_hook_shell.py`). EOL: todos LF y siguen LF.
- Claves leídas de datos: este lote no renombra ninguna (ni `["x"]`, `.get("x")`, `"x" in`, `pop`
  ni `{**…}`): sus filas son solo nombres de Python.

### A9b-2 · Fuera del lote (consecuencia mecánica, aprobada)

- Ninguno.

### A9b-2 · Barrido final

- AST de los 6 ficheros: ningún nombre de código, kwarg ni argname con un `old` del lote.
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 94 en
  textos (51 docstrings, 20 comentarios y 23 cadenas): prosa en español y datos de prueba («este
  archivo pesa mucho», `"uno.md"`, `"cat {p} otro.md"`, los textos del aviso que afirman los tests…).
- En todo el repo (fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`), los nombres propios del lote
  (`sin_preguntar`, `_correr_hook_instalado`, `_escribir_telemetria`, `TEXTO_READ`, `_lanza_401`…):
  0. Quedan `_ultimo_evento` en `test_respaldo.py` y `test_observabilidad_respaldo.py`: es otra
  función, de A9c y del lote 5.
- `--collect-only`: 2569 (`evidence/A9b-2/collect.txt`). Suite: 2567 passed, 2 skipped
  (`evidence/A9b-2/pytest-full.log`). `ruff check` y `ruff format --check` en verde.
- CodeQL (aproximación AST) sobre los 2 ficheros renombrados: 0 patrones.

### A9b-2 · Desviaciones

1. Ninguna fila `pycharm` pasó a `search_edit`: los 3 parámetros (`antiguedad_s`, `relleno`,
   `bloquear`) no tienen homónimos en el repo. Anotado en la línea `# Fase 2` del CSV.
2. El parámetro `modelo` de una lambda no estaba en el mapping (ni el detector ni el barrido AST de la
   fase 1 miran los argumentos de lambdas); se cambió y se anota en la misma línea `# Fase 2`.

## A9b-3 — `test_hooks_telemetry_api`, `test_install`, `test_install_cabecera` y `test_install_clients` (aplicado)

### A9b-3 · Qué se hizo

- 23 `rename_refactoring` (tabla de arriba). PyCharm reescribió 3 documentos de `.sdd/`
  (`english-names-bilingual-output/waves/A9a.md`, `js-dashboard-comportamiento/research.md` y
  `telemetria-hooks-dashboard/research.md`: citas históricas de `_con_huerfanos` y
  `_extraer_funcion_js`), devueltos a HEAD con `git show`. Los homónimos de otros ficheros
  (`CLIENTES`, `_home_con` y `_claude_escribe` de `test_install_plazos.py`, `_extraer_funcion_js` de
  `test_metrics.py`) no se tocaron.
- A mano, antes de `apply`: los parámetros `evento`/`categoria`/`sugerida` de `_evento` con sus 24
  kwargs (`a9b/kwfix.py`, por posición AST) y `fuente` de `_extraer_funcion_js`.
- `make_mapping.py apply` con la copia del CSV con los ámbitos ya renombrados: 233 + 169 + 54 + 83 =
  539 reemplazos.
- A mano, después: el `def` de las anidadas `_explota`→`_explodes`, `_espia`→`_spy`,
  `_no_preguntes`→`_do_not_ask` (×3) y `_revienta`→`_blows_up`; los argnames de 6 `parametrize`
  (`cliente` ×5, `esperado`); y el JS propio de `test_hooks_telemetry_api.py` (`casos`→`testCases`,
  `nodos`→`nodes`, `salida`→`results`, `caso`→`testCase`, `pares`→`aliasPairs`: 18 tokens, por
  línea, porque esos literales son concatenaciones con f-strings que `js_apply.py` no admite).
- `git mv` de `test_install_cabecera.py` → `test_install_header.py`; nadie lo cita por ruta.
- `ruff format` reflowó 3 ficheros. EOL: todos LF y siguen LF.
- **Datos que el producto escribe o lee** (bloques gestionados, settings JSON, TOML de Codex, JSON de
  opencode): comparadas las cadenas de los 4 ficheros antes y después por AST, solo cambian los
  literales JS y dos argnames de `parametrize`; ninguna clave ni texto de datos. Los valores
  `"viejo"`/`"nuevo"` de `_read_rows(fmt)` y las claves `motivo`/`bloqueo` de la telemetría vieja se
  quedan: son datos del test y claves persistidas.
- Lambdas: el barrido de sus parámetros en los 4 ficheros no encontró ninguno en español.

### A9b-3 · Fuera del lote (consecuencia mecánica, aprobada)

- Ninguno.

### A9b-3 · Barrido final

- AST de los 4 ficheros: ningún nombre de código, kwarg ni argname con un `old` del lote.
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 146 en
  textos (82 docstrings, 24 comentarios y 40 cadenas): prosa y datos en español; ninguna cita entre
  comillas invertidas.
- En el resto del repo (fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`): solo quedan los
  homónimos de otros lotes (`CLIENTES`, `_home_con`, `_claude_escribe` en `test_install_plazos.py`,
  lote 4; `_extraer_funcion_js` en `test_metrics.py`, lote 5).
- `--collect-only`: 2569 (`evidence/A9b-3/collect.txt`). Suite: 2567 passed, 2 skipped
  (`evidence/A9b-3/pytest-full.log`). `ruff check` y `ruff format --check` en verde.
- CodeQL (aproximación AST) sobre `test_install_header.py`: 0 patrones.

### A9b-3 · Desviaciones

1. **4 filas `pycharm` → `search_edit`** (parámetros homónimos `evento`, `categoria`, `sugerida` y
   `fuente`), anotado en la línea `# Fase 2` del CSV.
2. El JS del test se cambió por línea y no con `js_apply.py` (literales concatenados con f-strings);
   se comprobó con la comparación de cadenas por AST que no cambió nada más.

## Pendientes

1. Lotes A9b-4 a A9b-6, cada uno con su sección. Al aplicar cada uno, barrer también los argumentos
   de lambdas (desviación 2 del lote 2).
2. En el lote 6: el test nuevo de los esquemas de `elicitation` y el arreglo de la carrera de
   `test_turn_wait_shown_in_panel_as_local_wait` (cabecera de `A9b-6-mapping.csv`).
3. Para los lotes que tocan claves en cadenas: buscar también `"clave" in doc` (desviación 2).
4. **Intermitentes vistos** (no son de A9b; se anotan para quien los toque):
   `test_fake_llamaswap.py::test_a_ttl_counts_from_request_end` (`t_unload` 4,23 > 4,0) y
   `::test_d_8_s_request_in_progress_on_reload[cambio_ajeno]` (500 en vez de 502), los dos bajo la
   carga de `-n auto` en la primera corrida del lote 1;
   `test_residency_cli.py::test_restoring_a_copy_end_to_end` (visto en A9a); y la carrera de
   `test_panel_estados.py::test_turn_wait_shown_in_panel_as_local_wait`, que se arregla en el lote 6.
