# Ola A7a — `server.py`, núcleo, espera y respaldo (líneas 1-2506)

- Rama: `sdd/english-names-a7a` · PR: (lo abre la sesión principal) · Commit(s): (pendiente; borrador en `waves/A7a-commit-msg.txt`, firmado y sin coautoría), encima de `f2487bc` (`main` con la 0.35.0 y el bump de ruff)
- Quién: un agente hizo el mapping (fase 1) y, tras la aprobación de la sesión principal con las respuestas 1-8, lo aplicó (fase 2): renombrados, arreglo de `make_mapping.py`, tests, evidencias, este registro y el borrador del commit.
- REQ cubiertos: REQ-015 (identificadores internos de `server.py:1-2506`) y REQ-017 (ningún assert cambia de sentido)
- Ficheros poseídos (plan.md A7a/A7b): `src/local_delegate/server.py:1-2506`; en `web/metrics.py`, solo `:826` y el comentario de `:2616` (respuesta 6); los tests que cambian por consecuencia del rename; y `tools/make_mapping.py` con su test (respuesta 3). Lo de fuera, en «Desviaciones»
- EOL: `evidence/A7a/eol-check.txt` (diferencia de `git ls-files --eol` antes y después sobre todo el repo): 0 diferencias. `server.py` y `web/metrics.py` siguen en CRLF; los tests y el resto, en LF
- Mapping: `waves/A7a-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 124 filas; filas `pycharm` 32 = filas `rename_refactoring` 32; filas `search_edit` 92, cada una con su motivo (54 de la fase 1: variables locales con `make_mapping.py apply` y la función anidada `llamar`; 38 parámetros y atributos homónimos que pasaron de `pycharm` a `search_edit` en la fase 2, ver «Desviaciones»)
- Tests recogidos: antes 2567 → después 2567 (+0, −0) en la suite del repo (`evidence/A7a/collect-before.txt`). El test nuevo de la herramienta vive en `tools/tests/` (fuera de la suite del repo): esa carpeta pasa de 11 a 12, y los 12 pasan
- Suite: `evidence/A7a/pytest-full.log` (con `pesado.sh`), verde: 2565 pasan, 2 saltados, 1 aviso de Starlette ya conocido (4 min 19 s)
- `ruff check src tests scripts .sdd/changes/english-names-bilingual-output/tools` y `ruff format --check` sobre lo mismo: limpios (187 ficheros; `ruff format` reformateó `server.py` y `tests/test_respaldo.py`, que se quedaban largos o cortos con los nombres nuevos, sin tocar su EOL)
- Detector (`evidence/A7a/detector-after.json`, con `--exceptions rename-exceptions.md`): hallazgos únicos 7266 (tras A6) → 7179 (−87); fuera de la lista 7259 → 7172. En `server.py:1-2506` solo quedan las cinco claves del dict de respaldo (`respondio`, `en_lugar_de`, `motivo`, `clase`, `trozo`), que no se tocan (respuesta 7, pendiente de B2)

## Alcance y corte A7a/A7b

- **Corte (respuesta 1):** A7a acaba en `_chat` (`def` en `server.py:2370`). A7b empieza en el comentario de sección `# --- Chunking por límites naturales (local_translate / local_delegate)` (`:2507` antes de este cambio; `:2509` después, porque `ruff format` partió la firma de `call` y una expresión de `_chat`), con `_split_by_diff_files` como primer símbolo. Es frontera de sección, no parte ninguna función.
- **Qué entró en A7a:** versión, cliente httpx, delegaciones en curso, helpers (destino de `local_boilerplate`, `_log_event`, `claude_tokens`, `_accounting`), espera frente a lentitud, `ChatResult`/`Attempt`, respaldo (`_fallback_info`, `_fallback_notice`, `_body_failure`), sonda de carga (`_LoadProbe`), `_post_chat`, turno, afinidad, `_call_model`, `_with_fallback`, `_run_chat`, `_CurrentModel`, `_savings_feedback` y `_chat`.
- **Queda para A7b:** troceado y map-reduce (con sus `rol`, `explicito`, `postproceso` y `num_secciones` propios), inventario del diff, prompts de sistema, validación de imagen, resumen estructurado (con los pendientes que cedió A6), las tools y `local_status`.
- **Excluido a propósito:** las claves del dict de `_fallback_info` (`respondio`, `en_lugar_de`, `motivo`, `clase`) y la clave `trozo` de `_CurrentModel.hop`, que acaban en `_local_delegate.respaldo` de `local_extract` (REQ-010, B2); los marcadores `[local-delegate aviso: …]` y `[local-delegate respaldo: …]`; prompts, docstrings (salvo las citas de nombres) y textos de salida (B2); los nombres de otros módulos (`cadenas`, `estado_json`, `preguntas.*`, `clients.observar_cliente`, `config.modelos_por_rol`, `config.TIMEOUT_CONEXION_DELEGACION`), que son de A8a; y los nombres de los tests (`test_*`), de A9.

## Qué se hizo

- **Locales (54 filas `search_edit` de la fase 1):** `make_mapping.py apply`, 210 reemplazos en `server.py`, antes de cualquier rename de PyCharm (lección de A5b-1). Después, a mano, el `def llamar(` anidado de `_with_fallback` → `def call(` (`apply` no renombra el `def` de una anidada).
- **PyCharm (32 `rename_refactoring`):** las funciones, clases, constantes y métodos de nombre único: `_annotations` (y su parámetro `writes`), `_inflight_local_wait` (y `reason`), `_validate_target`, `_write_target` (y `event`), `BLOCK_WINDOW_S`, `_CLAUDE_TOKEN_KINDS`, `claude_tokens`, `Attempt`, `_HOPPABLE_CLASSES`, `_fallback_info`, `_class_value`, `_fallback_notice`, `_body_failure`, `_PROBE_MARGIN_S`, `_PROBE_QUERY_CAP_S`, `_probe_delay`, `_llamaswap_state`, `_LoadProbe` con `start`, `cancel`, `_sample` y `model_loaded`, `_backend_on_loopback`, `_call_model`, `_with_fallback`, `_CurrentModel` con `call`, `log_fields` y `notice`. PyCharm actualizó también las cadenas de `monkeypatch.setattr` de esos nombres (`"_inflight_local_wait"`, `"_with_fallback"` ×3, `"_backend_on_loopback"`, `"_probe_delay"` ×2, `"claude_tokens"`, `"model_loaded"`).
- **Renombrador por AST (38 filas, `a7a/ren.py` en el scratchpad):** los parámetros homónimos (`rol`, `explicito`, `tamano`, `respaldo`, `postproceso`, `num_secciones`, `evento`, `tipo`, `clase`, `modelo`, `retraso_s`, `consultar`, `espera_s`), dentro de su función y en cada `nombre=` de las llamadas a ella en `src/`, `tests/` y `scripts/`; y los atributos (`ChatResult.clase` y `Attempt.clase` → `error_class`, `Attempt.modelo` → `model`, los de `_CurrentModel` y los privados de `_LoadProbe`), en sus accesos, constructores y campos. `elegido.modelo` (`server.py:3726`, `:3728`, de `preguntas`) se excluyó a propósito. Escribe con `newline=""` y comprueba cada posición antes de editar.
- **A mano (`a7a/manual.py`, 43 ediciones):** citas entre comillas invertidas en docstrings y comentarios (`server.py` ×19, `cost.py:9`, `valuation.py:104`, `web/metrics.py:2616`, `test_affinity.py:588`, `test_cadenas.py:256` y `:295`, `test_metrics.py:948`, `test_respaldo.py:568`, `test_slowness.py:249`), los rótulos `"claude_tokens"`/`"_write_target"` de `test_densidad.py:314-316`, los parámetros del lambda de `test_metrics.py:949`, el literal `"return _body_failure("` de `test_post_chat_caminos.py:167`, `role=` a través de `_Thread(...)` en `test_turn_daemon.py` (`:309-310`, `:416-417`, `:553-554`, `:600`, `:635-636`) y la fórmula de `docs/wiki/Savings-and-metrics.md:250-251`. Los `rol=` de `test_turn_daemon.py:302` y `:597` son de `_chat_chunked` (A7b) y se quedan.
- **`make_mapping.py` (respuesta 3):** `apply_mapping` deduplica las ediciones (`edits = sorted(set(edits), reverse=True)`), porque la fila de una función recorre también sus anidadas. Test nuevo: `tools/tests/test_make_mapping.py::test_an_outer_row_and_a_nested_row_with_the_same_name_do_not_edit_twice`.
- **`clase` → `error_class` (respuesta 2):** la comprobación AST de choques por ámbito se repitió con el CSV aprobado y `error_class` no choca en ninguno de los siete ámbitos (`ChatResult`, `Attempt`, `_fallback_info`, `_class_value`, `_body_failure`, `_post_chat`, `_with_fallback`); el `error_class` de `_log_event` (`:699`) y las claves `"error_class"` son de otros ámbitos. Ninguna fila volvió a `failure_class`.

## Cadenas que no debían cambiar

`evidence/A7a/strings-check.txt`. Líneas con cada marcador en literales de `src/` y `tests/` (`git grep -c -F`, HEAD `f2487bc` frente al árbol de A7a):

| Patrón | Antes | Después |
| --- | --- | --- |
| `local-delegate aviso` | 10 | 10 |
| `local-delegate respaldo` | 1 | 1 |
| `"aviso"` | 10 | 10 |
| `"respaldo"` | 2 | 2 |
| `"truncado"` | 15 | 15 |
| `_local_delegate` | 22 | 22 |

Contando la subcadena dentro de cualquier literal (tokenize, docstrings incluidos): `aviso` 105 → 105, `truncado` 30 → 30, `_local_delegate` 17 → 17 y `respaldo` 78 → 72. Las seis de menos son nombres, no marcadores: las tres cadenas de monkeypatch `"_con_respaldo"`, las dos citas `` `_con_respaldo` `` de los docstrings de `test_affinity.py:588` y `test_cadenas.py:295`, y la cita `` `respaldo` `` → `` `fallback` `` del docstring de `_chat` (`server.py:2400`, respuesta 8).

## `web/metrics.py`: lista cerrada de A7a

| Línea | Antes | Después |
| --- | --- | --- |
| `web/metrics.py:826` | `server._backend_en_loopback()` | `server._backend_on_loopback()` (PyCharm) |
| `web/metrics.py:2616` | comentario del espejo JS: `` `tokens_claude` `` | `` `claude_tokens` `` (a mano, respuesta 6) |

El resto de referencias a `server` de `metrics.py` no son de A7a (`_accounting`, `inflight_snapshot`, `_topology`, `_inflight_mutate` ya en inglés; `sondear_backend`, `_plazo_sonda` y `_clashes_by_groups` de A7b).

## Controles positivos
| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_post_chat_caminos.py` (el literal que cuenta las salidas de `_post_chat`) | literal `"return _body_failure("` devuelto a `"return _fallo_de_cuerpo("` | `:168: assert salidas == 7` → `assert 6 == 7` | sí (sha256 `8a3eb27e9ee1`) |
| `tests/test_metrics.py::test_tokens_claude_es_la_unica_conversion` | el lambda con los parámetros viejos (`lambda cantidad, *, tipo, evento: 7`) | no es un assert: `TypeError … got an unexpected keyword argument 'kind'` en `_accounting` (`claude_tokens(…, kind="text", event=row)`), que es lo que demuestra que el lambda tenía que cambiar | sí (sha256 `984afc48b917`) |
| `tools/tests/test_make_mapping.py::test_an_outer_row_and_a_nested_row_with_the_same_name_do_not_edit_twice` | `make_mapping.py` sin deduplicar (`sorted(edits, reverse=True)`) | `ValueError: src/x.py:5:20 no contiene 'cadena'` en `apply_mapping` (el mismo error que dio el ensayo de la fase 1); el test también se escribió antes del arreglo y falló así | sí (sha256 `bb7879e76c99`) |

## Llamadas `local_*` (sesión principal y cada agente)
| Quién | Tool | Para qué | Resultado (útil / corregido / descartado) |
| --- | --- | --- | --- |
| agente A7a (mapping) | `local_summarize(path=src/local_delegate/server.py, focus="secciones del fichero por línea…")` | partir el fichero y confirmar el corte (mínimo del plan §2.1) | útil: confirma que `_chat` es lo último antes de «Chunking»; el corte exacto salió de `grep` de los `# ---` y los `def` |
| agente A7a (aplicación) | `local_lint_summary(path=evidence/A7a/pytest-full.log)` | resumir la suite completa | útil: «no se encontraron errores», solo el aviso de Starlette |

## Llamadas `mcp__pycharm__*`
| Quién | Tool | Símbolo o patrón | Resultado |
| --- | --- | --- | --- |
| agente A7a (mapping) | analyze_calls (INCOMING) | `local_delegate.server._backend_en_loopback` y otras tres formas | error, «No callable symbol found» (como en A0); se usó `search_regex` |
| agente A7a (mapping) | search_symbol | `_backend_en_loopback` | `server.py:1237`, una definición |
| agente A7a (mapping) | search_regex | `server\.(<22 nombres de A7a>)\b` en `src/`, `tests/`, `scripts/` | 30 apariciones en 16 ficheros |
| agente A7a (aplicación) | search_text | `target_model: str, chain: Sequence` en `server.py` | PyCharm ve el fichero tras `apply` (antes de cualquier rename) |
| agente A7a (aplicación) | rename_refactoring | `_anotaciones`→`_annotations` | ok, 11 usos |
| agente A7a (aplicación) | rename_refactoring | `escribe`→`writes` | ok, 2 usos |
| agente A7a (aplicación) | rename_refactoring | `_inflight_espera_local`→`_inflight_local_wait` | ok, 10 usos (también la cadena de monkeypatch de `test_turn_daemon.py:291`) |
| agente A7a (aplicación) | rename_refactoring | `motivo`→`reason` (`_inflight_local_wait`) | ok, 2 usos |
| agente A7a (aplicación) | rename_refactoring | `_validar_destino`→`_validate_target` | ok, 1 uso |
| agente A7a (aplicación) | rename_refactoring | `_escribir_destino`→`_write_target` | ok, 10 usos |
| agente A7a (aplicación) | rename_refactoring | `evento`→`event` (`_write_target`) | ok, 3 usos |
| agente A7a (aplicación) | rename_refactoring | `VENTANA_DE_BLOQUEO_S`→`BLOCK_WINDOW_S` | ok, 4 usos |
| agente A7a (aplicación) | rename_refactoring | `_TIPOS_CLAUDE`→`_CLAUDE_TOKEN_KINDS` | ok, 4 usos |
| agente A7a (aplicación) | rename_refactoring | `tokens_claude`→`claude_tokens` | ok, 79 usos (muchos en documentos históricos de `.sdd/`, devueltos) |
| agente A7a (aplicación) | rename_refactoring | `Intento`→`Attempt` | ok, 20 usos |
| agente A7a (aplicación) | rename_refactoring | `_CLASES_QUE_SALTAN`→`_HOPPABLE_CLASSES` | ok, 4 usos |
| agente A7a (aplicación) | rename_refactoring | `_respaldo_de`→`_fallback_info` | ok, 11 usos |
| agente A7a (aplicación) | rename_refactoring | `_valor_clase`→`_class_value` | ok, 6 usos |
| agente A7a (aplicación) | rename_refactoring | `_aviso_respaldo`→`_fallback_notice` | ok, 4 usos |
| agente A7a (aplicación) | rename_refactoring | `_fallo_de_cuerpo`→`_body_failure` | ok, 6 usos (el literal de `test_post_chat_caminos.py:167`, no: a mano) |
| agente A7a (aplicación) | rename_refactoring | `_MARGEN_SONDA_S`→`_PROBE_MARGIN_S` | ok, 2 usos |
| agente A7a (aplicación) | rename_refactoring | `_TOPE_CONSULTA_SONDA_S`→`_PROBE_QUERY_CAP_S` | ok, 3 usos |
| agente A7a (aplicación) | rename_refactoring | `_retraso_sonda`→`_probe_delay` | ok, 3 usos (con las dos cadenas de monkeypatch) |
| agente A7a (aplicación) | rename_refactoring | `_estado_en_llamaswap`→`_llamaswap_state` | ok, 6 usos |
| agente A7a (aplicación) | rename_refactoring | `_SondaDeCarga`→`_LoadProbe` | ok, 10 usos |
| agente A7a (aplicación) | rename_refactoring | `_backend_en_loopback`→`_backend_on_loopback` | ok, 16 usos |
| agente A7a (aplicación) | rename_refactoring | `_llamar_modelo`→`_call_model` | ok, 5 usos |
| agente A7a (aplicación) | rename_refactoring | `_con_respaldo`→`_with_fallback` | ok, 34 usos |
| agente A7a (aplicación) | rename_refactoring | `_ModeloVigente`→`_CurrentModel` | ok, 11 usos |
| agente A7a (aplicación) | rename_refactoring | `_muestrear`→`_sample` | ok, 1 uso |
| agente A7a (aplicación) | rename_refactoring | `modelo_cargado`→`model_loaded` | ok, 11 usos |
| agente A7a (aplicación) | rename_refactoring | `campos_de_log`→`log_fields` | ok, 6 usos |
| agente A7a (aplicación) | rename_refactoring | `iniciar`→`start` | ok, 6 usos |
| agente A7a (aplicación) | rename_refactoring | `cancelar`→`cancel` | ok, 2 usos; `preguntas.py` sin cambios |
| agente A7a (aplicación) | rename_refactoring | `aviso`→`notice` (método de `_CurrentModel`) | ok, 2 usos; ningún marcador tocado |
| agente A7a (aplicación) | rename_refactoring | `llamar`→`call` (método de `_CurrentModel`) | ok, 2 usos |
| agente A7a (aplicación) | search_text | `error_class=FailureClass.MODEL` | PyCharm ve las ediciones hechas desde fuera (y `ruff format`) |
| agente A7a (aplicación) | lint_files | los 20 ficheros Python del diff (solo errores) | 9 avisos, todos falsos positivos conocidos de cadenas de `monkeypatch.setattr` ajenas a A7a (`"yaml"`, `"Client"`, `"open"`, `"connect"`, `"time"`, `"request"`, `"release_slot"`); ninguno en `server.py` |

Dos llamadas más no cuentan como renombrado: `rename_refactoring` de `evento`→`event` y de `tipo`→`kind` (parámetros de `tokens_claude`, ya `claude_tokens`) devolvieron «Successfully renamed … with 0 usages» y no cambiaron nada en disco. Por eso las 38 filas de parámetros y atributos homónimos pasaron al renombrador por AST («Desviaciones»).

## Revisión del diff tras rename_refactoring
- **Documentos históricos de `.sdd/`.** PyCharm reescribió 26 ficheros de `coste-api-y-cuota/`, `daemon-reparte-el-backend/`, `delegacion-precisa-y-fiable/`, `panel-cuentas-y-estados-honestos/` y de este cambio (`plan.md`, `research-rename.md`, `waves/A3.md`, `A4.md`, `A5b-1.md`); se devolvieron con `git checkout`. `brief.md`, el CSV y este registro, sin tocar.
- **Homónimos.** `preguntas.py` (su `cancelar`, su campo `modelo`), los `clase=` de `tests/test_enfriamiento.py` y `tests/test_medir_enfriamiento.py`, `cadena.rol` de `checks.py` y el JS del panel (`o.modelo`, `b.clase`) no cambiaron. En la zona de A7b de `server.py` solo cambiaron llamadas y argumentos por nombre a funciones de A7a (`role=`, `fallback=`, `postprocess=`, `num_sections=`, `writes=`, `event=`, `kind=`, `size=`, `vigente.call/.notice/.log_fields/.chunk`, `_CurrentModel`, `Attempt`, `_annotations`, `_validate_target`, `_backend_on_loopback`, `claude_tokens`); sus locales en español (`rol`, `explicito`, `evento`, `intentos`, `info_respaldo`, `destino`…) siguen ahí para A7b.
- **Nombres viejos.** Búsqueda de los nombres distintivos de A7a en `src/`, `tests/`, `scripts/`, `docs/`, README y CHANGELOG: solo quedan `info_respaldo` (local de `local_extract`, A7b) y `espera_s` como clave vieja de datos persistidos (`legacy_names.py`, `hook_common.py`, tests de enfriamiento), que no es este parámetro.
- **Marcadores.** Tabla de «Cadenas que no debían cambiar».
- **Código inalcanzable.** No se reescribió ninguna función; solo nombres.
- **Prosa.** Docstrings y comentarios citan los nombres nuevos entre comillas invertidas; la prosa sigue en español (la frase «`rol` habilita el respaldo de ese rol» queda como «`role` habilita el respaldo de ese rol»).

## Scripts (REQ-014, solo olas que renombran en src/)
| Script | `--help` | Corrida mínima o `get_file_problems` |
| --- | --- | --- |
| `scripts/construir_corpus.py` | 0 | `get_file_problems` sin errores; usa `server.Attempt` (cambio de PyCharm), y `tests/test_corpus.py` lo carga y pasa en la suite |

## Desviaciones y nombres «(plan)» ajustados
- **Respuestas 1-8 de la sesión principal:** corte en `:2507` (1); `clase`→`error_class`, sin choques (2); deduplicación en `make_mapping.py` con test y control positivo (3); `target_model` (4); nombres del punto 5 tal cual (5); comentario de `web/metrics.py:2616` actualizado (6); claves del dict de respaldo intactas (7); citas de docstrings actualizadas (8).
- **38 filas de `pycharm` a `search_edit` (método ajustado al aplicar, en la cabecera del CSV y en cada fila).** `rename_refactoring` con `symbolName` de un parámetro o atributo homónimo (`evento`, `tipo`) devolvió «0 usages» y no hizo nada; con 13 parámetros repetidos en varias funciones (`rol`, `explicito`, `tamano`, `evento`, `clase`, `modelo`…) y atributos con el mismo nombre en varias clases, el resultado dependía de qué definición eligiera PyCharm. Se hicieron con un renombrador por AST (ámbito de la función más los argumentos por nombre en las llamadas a ella; para atributos, accesos, constructores y campo), con la comprobación de cada posición antes de escribir. Los usos de tipo atributo en tests (`.clase`, `.modelo`) se acotaron a los ficheros de la fila.
- **Fila nueva en el mapping:** `tokens_claude`→`claude_tokens`. La aprobó la respuesta 5, pero el build no la traía (el detector no la ve). Va con PyCharm.
- **Fuera de «posee», consecuencia mecánica aprobada en el mapping:** `checks.py:1597`, `valuation.py:104-110`, `cost.py:9`, `scripts/construir_corpus.py:699` (A10 dueña), `web/metrics.py:2616` (respuesta 6), las llamadas en la zona de A7b de `server.py` (lista de «Revisión del diff») y `docs/wiki/Savings-and-metrics.md:250-251` (fórmula con `claude_tokens`; PyCharm cambió una de las dos líneas y la otra se cambió a mano: la wiki va con la release).
- **`ruff format`** reformateó `server.py` (la firma de `call`, una condición de `_post_chat` y la suma del recibo en `_chat`) y `tests/test_respaldo.py:648`, porque los nombres nuevos cambiaron el largo de las líneas. EOL conservado.
- **Antes de mezclar:** nada pendiente de otros PR; la rama está encima de `main` (`f2487bc`).

## Pendientes
- **A7b:** el resto de `server.py` desde el comentario de «Chunking», con los parámetros homónimos de `_chat_chunked` y `_chat_map_reduce` (`rol`, `explicito`, `postproceso`, `num_secciones`), sus locales (`intentos`, `evento`, `info_respaldo`, `destino`…) y los pendientes de secciones cedidos por A6; y en `tests/test_turn_daemon.py:302` y `:597`, los `rol=` de `_chat_chunked`. Los tests `test_core.py`, `test_map_reduce.py`, `test_vision.py` y `test_boilerplate_salida.py` no referencian nada de A7a.
- **B2:** las claves del dict de respaldo (`respondio`, `en_lugar_de`, `motivo`, `clase`) y la clave `trozo` de `_CurrentModel.hop`, que llegan a `_local_delegate.respaldo` de `local_extract` (REQ-010), con el resto de las subclaves del contrato.
- **A8a:** los nombres de otros módulos que usa `server.py` (`cadenas`, `estado_json`, `preguntas.*`, `clients.observar_cliente`, `config.modelos_por_rol`, `config.TIMEOUT_CONEXION_DELEGACION`).
- **A8b:** el espejo JS `tokensClaude` de `web/metrics.py` (identificador JS, no Python).
- **A9:** los nombres `test_*` en español de los tests tocados (p. ej. `test_tokens_claude_es_la_unica_conversion`).
