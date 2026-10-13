# Ola A7b — `server.py`, troceado, tools y `local_status` (líneas 2509-4601)

- Rama: `sdd/english-names-a7b` · PR: (lo abre la sesión principal) · Commit(s): (pendiente; borrador en `waves/A7b-commit-msg.txt`, firmado y sin coautoría), encima de `6910d20` (`main` con A7a mezclada, #265)
- Quién: un agente hizo el mapping (fase 1) y, tras la aprobación de la sesión principal con las respuestas 1-6, lo aplicó (fase 2): renombrados, arreglo de `make_mapping.py` con su test, tests, evidencias, este registro y el borrador del commit.
- REQ cubiertos: REQ-015 (identificadores internos de `server.py:2509-4601`) y REQ-017 (ningún assert cambia de sentido)
- Ficheros poseídos (plan.md A7a/A7b): `src/local_delegate/server.py:2509-4601`; en `web/metrics.py`, solo las seis líneas de llamada de la lista cerrada; los tests que cambian por consecuencia del rename; y `tools/make_mapping.py` con su test (respuesta 1). Lo de fuera, en «Desviaciones»
- EOL: `evidence/A7b/eol-check.txt` (diferencia de `git ls-files --eol` antes y después sobre todo el repo): 0 diferencias. `server.py`, `web/metrics.py` y `entrypoint.py` siguen en CRLF; los tests, `daemon.py`, `hook_common.py` y `make_mapping.py`, en LF. Todas las ediciones desde fuera, con Python y `newline=""`
- Mapping: `waves/A7b-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 141 filas; filas `pycharm` 25 = filas `rename_refactoring` 25; filas `search_edit` 116, cada una con su motivo (105 con `make_mapping.py apply`, 366 reemplazos; 11 con el renombrador por AST `a7b/ren.py`)
- Tests recogidos: antes 2567 (`evidence/A7b/collect-before.txt`) → después 2567 (2565 pasan + 2 saltados en `pytest-full.log`), +0 −0. El test nuevo de la herramienta vive en `tools/tests/` (fuera de la suite del repo): esa carpeta pasa de 12 a 13, y los 13 pasan
- Suite: `evidence/A7b/pytest-full.log` (con `pesado.sh`, en serie), verde: 2565 pasan, 2 saltados, 1 aviso de Starlette ya conocido (4 min 17 s)
- `ruff check src tests scripts .sdd/changes/english-names-bilingual-output/tools` y `ruff format --check` sobre lo mismo: limpios (`evidence/A7b/ruff-check.txt`, 187 ficheros; `ruff format` reformateó `server.py` y `tests/test_map_reduce.py`, que se quedaban largos o cortos con los nombres nuevos, sin tocar su EOL)
- Detector (`evidence/A7b/detector-after.json`, con `--exceptions rename-exceptions.md`): hallazgos únicos 7179 (tras A7a) → 7072 (−107); fuera de la lista 7172 → 7065. En `server.py:2509-4601` solo quedan las claves del contrato `_local_delegate` de `local_extract` (`truncado`, `aviso`, `leido_server_side`, `tokens_aprox`, `respaldo`, `crudo`), que son de B2
- Firmas de las tools MCP: `evidence/A7b/tool-signatures.txt`. Las 11 funciones con `@mcp.tool` (nombre, parámetros con defaults y anotaciones, retorno y decoradores, por AST), antes y después: **idénticas**

## Alcance y corte A7a/A7b

- **Corte:** A7b empieza en `:2509`, el comentario `# --- Chunking por límites naturales (local_translate / local_delegate)`, y llega al final del fichero (`prepare_ctrl_break`). Es la frontera que dejó A7a.
- **Qué entró en A7b:** troceado y map-reduce (`_chat_chunked`, `_chat_map_reduce` con sus parámetros `rol`, `explicito`, `postproceso` y `num_secciones`, `_is_context_overflow`, `_role_for_size`, `_map_budget`), el inventario del diff, `_guard`, el resumen estructurado (los pendientes cedidos por A6: `sections_`, `_section_list`, `_MIN_WORDS_PER_SECTION`, `_structured_*`), las variables locales de las tools y `local_status` con su sondeo (`probe_backend`, `BackendState`, `_probe_timeout`, `_failed_probe`, `_LAST_GOOD_LISTS`, `_backend_state_text`, `_describe_cooldown`, `_CAUSES_WITH_RESPONSE`) y `prepare_ctrl_break`.
- **Excluido a propósito:**
  - la API de tools MCP (firmas idénticas, arriba);
  - el contrato `_local_delegate` y los marcadores `[local-delegate aviso|respaldo: …]`, de REQ-010 en B2;
  - prompts, docstrings (salvo las citas de nombres) y textos de salida, de B2;
  - los nombres de otros módulos (`preguntas.*` con los atributos `.modelo` y `.formato`, `cadenas.describir`, `config.modelos_por_rol`, `config.TIMEOUT_SONDA_*`), de A8a;
  - la variable `estado` propia de `web/metrics.py`;
  - los nombres `test_*` y los de fichero de test, de A9;
  - el CHANGELOG histórico y `benchmarks/` (respuesta 6).

## Qué se hizo

- **`make_mapping.py` (respuesta 1):** `_find_function` baja ahora por los bloques de las sentencias compuestas (`if`, `for`, `while`, `try`, `with`, `match`) sin sumar un nivel al nombre cualificado, con un helper `_child_statements`. Test nuevo: `tools/tests/test_make_mapping.py::test_a_nested_function_inside_compound_statements_is_found`, con anidadas dentro de un `if` y de un `try`/`with`. Se escribió antes del arreglo y falló con el `ValueError` de `local_commit_msg._build_map`. Las 4 filas de `_build_map`/`_build_reduce` conservan su definición original.
- **Locales (105 filas `search_edit`):** `make_mapping.py apply`, 366 reemplazos en `server.py`, antes de cualquier rename de PyCharm.
- **Renombrador por AST (11 filas, `a7b/ren.py`):**
  - Los parámetros que se pasan por nombre: `rol`/`explicito` de `_chat_chunked` y `_chat_map_reduce`, `postproceso` y `num_secciones` de `_chat_map_reduce`, `rol`/`estructura` de `_structured_summary` y `excepcion` de `_failed_probe`. Cada uno dentro de su función y en cada `nombre=` de las llamadas a ella en `src/`, `tests/` y `scripts/`.
  - Los campos `causa`→`cause` y `detalle`→`detail` de `BackendState`, en `server.py`, `web/metrics.py` y `tests/test_sondeo_backend.py`.
  - Ver en «Desviaciones» por qué se pasó dos veces sobre `server.py`.
- **PyCharm (25 `rename_refactoring`):** funciones, constantes y la clase de nivel de módulo. PyCharm cambió también las cuatro cadenas `"sondear_backend"` de `monkeypatch.setattr` (`test_cadenas.py:413`, `test_cli_renamed_names.py:261`, `test_observabilidad_respaldo.py:140`, `test_slowness.py:472`) y el `:func:` del docstring de `server.py:4322`.
- **A mano (`a7b/manual.py`, 19 ediciones con su número de apariciones comprobado):**
  - Los `def` de las anidadas `_cerrar`→`_close`, `_completar`→`_complete`, `_system_trozo`→`_chunk_system` y `_user_trozo`→`_chunk_user`.
  - El `nonlocal …, cortadas` de `_one` → `truncated_calls`.
  - La clave interna `"archivo"`→`"file"` del dict `current_file` de `local_commit_msg` (5 apariciones; respuesta 2, ver abajo).
  - La cita `causa`/`detalle` del docstring de `BackendState`.
  - El `rol=` que va por `_Thread(...)` en `tests/test_turn_daemon.py:597`.
  - La cadena `"_LISTAS_BUENAS"` de `tests/conftest.py:59`.
  - La cita de `hook_common.py:372`.
  - Los comentarios de `daemon.py:312`, `entrypoint.py:94`, `tests/test_sondeo_backend.py:98` y `tests/test_observabilidad_respaldo.py:136`, que PyCharm no cambió.
- **La clave `"archivo"` (respuesta 2), comprobada antes de cambiarla:** solo vive en el dict local `current_file` de `local_commit_msg` (`:3900-3913`). La lee y la escribe `_build_map`. Al prompt del modelo llega el **valor** (la ruta), nunca la clave. No va a `_log_event`, a `cost.in_flight_row` ni a ningún texto de salida.
- **`enfriado`→`cooldown_entry` (respuesta 3):** la comprobación AST de choques se repitió con el CSV aprobado: 141 ok, 0 choques (`a7b/check-approved.txt`).

## Cadenas que no debían cambiar

`evidence/A7b/strings-check.txt`. Líneas con cada marcador en literales de `src/` y `tests/` (`git grep -c -F`, HEAD `6910d20` frente al árbol de A7b):

| Patrón | Antes | Después |
| --- | --- | --- |
| `local-delegate aviso` | 10 | 10 |
| `local-delegate respaldo` | 1 | 1 |
| `"aviso"` | 10 | 10 |
| `"respaldo"` | 2 | 2 |
| `"truncado"` | 15 | 15 |
| `_local_delegate` | 22 | 22 |

Contando la subcadena dentro de cualquier literal (tokenize, docstrings incluidos): `aviso` 105 → 105, `respaldo` 72 → 72, `truncado` 30 → 30 y `_local_delegate` 17 → 17.

## `web/metrics.py`: lista cerrada de A7b

| Línea | Antes | Después |
| --- | --- | --- |
| `web/metrics.py:767` | `server.sondear_backend()` | `server.probe_backend()` (PyCharm) |
| `web/metrics.py:776` | `_cause_json(estado.causa, estado.detalle)` | `_cause_json(estado.cause, estado.detail)` (`ren.py`) |
| `web/metrics.py:797` | `server._plazo_sonda()` | `server._probe_timeout()` (PyCharm) |
| `web/metrics.py:828` | `server._plazo_sonda()` | `server._probe_timeout()` (PyCharm) |
| `web/metrics.py:855` | `server.sondear_backend()` | `server.probe_backend()` (PyCharm) |
| `web/metrics.py:878` | `_cause_json(estado.causa, estado.detalle)` | `_cause_json(estado.cause, estado.detail)` (`ren.py`) |

Nada más cambió en `metrics.py` (12 líneas de diff = 6 cambiadas). El `causa` del JS (`:2865`) es de A8b y la variable `estado` se queda.

## Controles positivos
| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tools/tests/test_make_mapping.py::test_a_nested_function_inside_compound_statements_is_found` | `make_mapping.py` sin el arreglo de `_find_function` (la rama nueva → `elif False:`) | no es un assert: `ValueError: no se encontró la función local_commit_msg._build_map` en `_local_edits` (el mismo error del ensayo de la fase 1); el test se escribió antes del arreglo y falló así | sí (sha256 `f42a0930ec83`) |
| `tests/test_turn_daemon.py::test_forced_event_carries_turn_forced` | el `role="long"` que va por `_Thread(...)` (`:597`) devuelto a `rol="long"` | `:603: assert x_stuck.wait(2), "X no llegó a atascarse con el turno"` (el hilo muere con `TypeError` por el kwarg viejo), y luego `RuntimeError: cannot join thread before it is started` | sí (sha256 `3a589cbed4c2`) |
| `tests/test_sondeo_backend.py` | el campo `BackendState.cause` devuelto a `causa`, solo en la definición | `AttributeError: 'BackendState' object has no attribute 'cause'` en los accesos `.cause` (p. ej. el assert de `:131`, `bueno.cause is None`) | sí (sha256 `08f6a3106429`) |

Detalle en `evidence/A7b/mutants.txt`. Tras restaurar: `test_sondeo_backend.py`, `test_turn_daemon.py` y `tools/tests` dan 43 pasan.

## Llamadas `local_*` (sesión principal y cada agente)
| Quién | Tool | Para qué | Resultado (útil / corregido / descartado) |
| --- | --- | --- | --- |
| agente A7b (mapping) | `local_explain_code(code=<_describir_enfriamiento>, question="propón nombres en inglés…")` | segunda opinión sobre los nombres de una función con varios locales | descartado en parte: `get_cooling_status`, `model_name` y `cooling_state` rompían el vocabulario ya fijado (`cooldown` de A4, `model`) |
| agente A7b (aplicación) | `local_lint_summary(path=evidence/A7b/pytest-full.log)` | resumir la suite completa | útil: solo el aviso de Starlette (`BlockingPortal`), sin fallos |
| agente A7b (aplicación) | `local_lint_summary(path=evidence/A7b/ruff-check.txt)` | resumir `ruff check` y `ruff format --check` | útil: sin problemas, 187 ficheros formateados |

## Llamadas `mcp__pycharm__*`
| Quién | Tool | Símbolo o patrón | Resultado |
| --- | --- | --- | --- |
| agente A7b (mapping) | search_regex | `server\.(<12 nombres>)\b` en `src/`, `tests/`, `scripts/` | 43 apariciones, las mismas que `git grep -w` |
| agente A7b (aplicación) | search_text | `truncated_calls = 0` en `server.py` | PyCharm ve el fichero tras `apply` (antes de cualquier rename) |
| agente A7b (aplicación) | rename_refactoring | `_DESBORDE_MARCAS`→`_OVERFLOW_MARKERS` | ok, 2 usos |
| agente A7b (aplicación) | rename_refactoring | `_DESBORDE_CONTEXTO`→`_OVERFLOW_CONTEXT_WORDS` | ok, 2 usos |
| agente A7b (aplicación) | rename_refactoring | `_DESBORDE_EXCESO`→`_OVERFLOW_EXCESS_WORDS` | ok, 2 usos |
| agente A7b (aplicación) | rename_refactoring | `_es_desborde_de_contexto`→`_is_context_overflow` | ok, 11 usos (con documentos de `.sdd/`, devueltos) |
| agente A7b (aplicación) | rename_refactoring | `_rol_por_tamano`→`_role_for_size` | ok, 7 usos; la cita de `hook_common.py:372`, no: a mano |
| agente A7b (aplicación) | rename_refactoring | `_presupuesto_map`→`_map_budget` | ok, 4 usos |
| agente A7b (aplicación) | rename_refactoring | `_PALABRAS_MINIMAS_POR_SECCION`→`_MIN_WORDS_PER_SECTION` | ok, 4 usos |
| agente A7b (aplicación) | rename_refactoring | `_HOLGURA_TOKENS_POR_SECCION`→`_TOKEN_SLACK_PER_SECTION` | ok, 2 usos |
| agente A7b (aplicación) | rename_refactoring | `_FORMATO_ESTRUCTURADO`→`_STRUCTURED_FORMAT` | ok, 2 usos |
| agente A7b (aplicación) | rename_refactoring | `_NOTA_ESTRUCTURADO`→`_STRUCTURED_NOTE` | ok, 2 usos |
| agente A7b (aplicación) | rename_refactoring | `_texto_focus`→`_focus_clause` | ok, 2 usos |
| agente A7b (aplicación) | rename_refactoring | `_system_estructurado`→`_structured_system` | ok, 5 usos |
| agente A7b (aplicación) | rename_refactoring | `_lista_de_secciones`→`_section_list` | ok, 7 usos |
| agente A7b (aplicación) | rename_refactoring | `_user_estructurado`→`_structured_user` | ok, 2 usos |
| agente A7b (aplicación) | rename_refactoring | `_max_tokens_estructurado`→`_structured_max_tokens` | ok, 6 usos |
| agente A7b (aplicación) | rename_refactoring | `_resumen_estructurado`→`_structured_summary` | ok, 3 usos |
| agente A7b (aplicación) | rename_refactoring | `_plazo_sonda`→`_probe_timeout` | ok, 10 usos |
| agente A7b (aplicación) | rename_refactoring | `EstadoBackend`→`BackendState` | ok, 17 usos |
| agente A7b (aplicación) | rename_refactoring | `_LISTAS_BUENAS`→`_LAST_GOOD_LISTS` | ok, 8 usos; la cadena de `conftest.py:59`, no: a mano |
| agente A7b (aplicación) | rename_refactoring | `sondear_backend`→`probe_backend` | ok, 36 usos (con las cuatro cadenas de monkeypatch y documentos de `.sdd/`, devueltos) |
| agente A7b (aplicación) | rename_refactoring | `_sondeo_fallido`→`_failed_probe` | ok, 8 usos |
| agente A7b (aplicación) | rename_refactoring | `_describir_enfriamiento`→`_describe_cooldown` | ok, 4 usos |
| agente A7b (aplicación) | rename_refactoring | `_CAUSAS_CON_RESPUESTA`→`_CAUSES_WITH_RESPONSE` | ok, 4 usos |
| agente A7b (aplicación) | rename_refactoring | `_estado_backend_en_texto`→`_backend_state_text` | ok, 7 usos |
| agente A7b (aplicación) | rename_refactoring | `preparar_ctrl_break`→`prepare_ctrl_break` | ok, 9 usos; los comentarios de `daemon.py:312` y `entrypoint.py:94`, no: a mano; el CHANGELOG, sin tocar |
| agente A7b (aplicación) | lint_files | los 15 ficheros Python de `src/` y `tests/` del diff (solo errores) | 12 avisos, todos falsos positivos conocidos de cadenas de `monkeypatch.setattr` ajenas a A7b (`"request"`, `"release_slot"`, `"yaml"`, `"time"`, `"run"`, `"Config"`, `"Server"`); ninguno en `server.py` |

## Revisión del diff tras rename_refactoring
- **Documentos históricos de `.sdd/`.** PyCharm reescribió 14 ficheros de `commit-msg-diffs-grandes/`, `daemon-reparte-el-backend/`, `fallback-entre-modelos-locales/`, `panel-cuentas-y-estados-honestos/`, `resumen-por-secciones/`, `salida-grande-va-a-fichero/` y de este cambio (`plan.md`, `waves/A4.md`, `A6.md`, `A7a.md`). Se devolvieron con `git checkout` (respuesta 4). `brief.md`, el CSV y este registro quedaron sin tocar.
- **Homónimos.** `preguntas.py` y sus atributos (`.modelo`, `.formato`), el `rol` de `tests/test_analisis_benchmark.py`, el `en_curso` de `tests/test_dashboard_ui.py`, el JS del panel y `benchmarks/` no cambiaron. Por AST, los únicos nombres del mapping que quedan en la zona son los atributos `.modelo` y `.formato` de `preguntas` (A8a).
- **Nombres viejos.** Búsqueda de todos los nombres del mapping en `src/`, `tests/`, `scripts/`, `docs/` y README: no queda ninguno como identificador. Solo quedan en prosa española (`explicito` en docstrings de `test_enfriamiento.py`/`test_medir_enfriamiento.py`, «El postproceso…» en un comentario de `server.py:2437`) y en el léxico del detector.
- **Marcadores.** Ver la tabla de «Cadenas que no debían cambiar».
- **Código inalcanzable.** No se reescribió ninguna función; solo cambiaron nombres.
- **Prosa.** Los docstrings y comentarios citan los nombres nuevos entre comillas invertidas; la prosa sigue en español.

## Scripts (REQ-014, solo olas que renombran en src/)
| Script | `--help` | Corrida mínima o `get_file_problems` |
| --- | --- | --- |
| (ninguno) | — | A7b no cambia nada que use `scripts/`: `construir_corpus.py:1593` solo cita `_chat_chunked`, que ya estaba en inglés; la suite pasa entera |

## Desviaciones y nombres «(plan)» ajustados
- **Respuestas 1-6 de la sesión principal:**
  1. Arreglo de `_find_function`, con test y control positivo; las 4 filas conservan su definición.
  2. `"archivo"`→`"file"`, a mano.
  3. Nombres aprobados, con `enfriado`→`cooldown_entry`.
  4. El orden de A7a, y `.sdd/` devuelto.
  5. Desviaciones de una línea, abajo.
  6. CHANGELOG y `benchmarks/` intactos.
- **PyCharm deshizo las ediciones de `ren.py` en `server.py`** (la lección de A5b-1, otra vez). `apply` y `ren.py` corrieron seguidos, y después `search_text` confirmó que PyCharm veía lo de `apply`. Aun así, tras los `rename_refactoring`, `server.py` conservaba lo de `apply` y había perdido lo de `ren.py`: los parámetros `rol`/`explicito`/`postproceso`/`num_secciones`/`estructura`/`excepcion` y los campos `causa`/`detalle`. Las ediciones de `ren.py` en `web/metrics.py`, `tests/test_sondeo_backend.py` y `tests/test_turn_daemon.py` sí sobrevivieron. Se volvió a pasar `ren.py` **solo sobre `server.py`** (`a7b/ops2.json`, con los nombres de función ya nuevos, `_structured_summary`/`_failed_probe`/`BackendState`), con los mismos recuentos que en el ensayo. Después se comparó `server.py` con el ensayo completo de la fase 1 (`a7b/sim`): solo difieren las ediciones que el ensayo no hacía (la clave `"file"`, la cita del docstring y `cooldown_entry`). **Para próximas olas:** pasar `ren.py` también **después** de PyCharm, o volver a comprobar con un barrido AST que no queda ningún nombre del mapping.
- **Fuera de «posee», consecuencia mecánica aprobada (respuesta 5):**
  - `src/local_delegate/daemon.py:312-313` y `src/local_delegate/entrypoint.py:94-95`: `prepare_ctrl_break`, llamada (PyCharm) y comentario (a mano).
  - `src/local_delegate/resources/hooks/hook_common.py:372`: la cita del docstring.
  - `tests/conftest.py:59`: la cadena de `getattr`.
- **`ruff format`** reformateó `server.py` (la expresión de `times` en `_describe_cooldown`, que se alargó con `cooldown_entry`) y `tests/test_map_reduce.py:393` (el assert cabe ahora en una línea), conservando el EOL. ruff también pidió renombrar la variable de bucle `field` del helper nuevo de `make_mapping.py` (F402, tapaba el `field` importado): ahora es `block`.
- **Antes de mezclar:** no queda nada pendiente de otros PR; la rama está encima de `main` (`6910d20`).

## Pendientes
- **B2:** las claves del contrato `_local_delegate` (`truncado`, `aviso`, `leido_server_side`, `tokens_aprox`, `respaldo`, `crudo`) y los marcadores, junto con las claves del dict de respaldo que dejó A7a.
- **A8a:** `preguntas.*` (con los atributos `.modelo` y `.formato`), `cadenas.describir`, `config.modelos_por_rol` y `config.TIMEOUT_SONDA_*`, que se usan desde esta zona.
- **A8b:** el `causa` del JS del panel (`web/metrics.py:2865`).
- **A9:** los nombres `test_*` y las variables propias de los tests tocados (p. ej. `archivos` de `test_core.py:791`, `estado` de `test_sondeo_backend.py`).
