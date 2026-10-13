# Ola A9c — Tests `q*`–`z*`

La subola se parte en 5 lotes (D13: 1269 filas, como mucho 300 por lote y sin partir un módulo),
aprobados por la sesión principal el 2026-10-13 con las 9 decisiones de la fase 1 tal como se
recomendaron. Cada lote es un commit que hace la sesión principal, en una rama apilada sobre el
anterior. Las tablas de controles positivos, `local_*` y PyCharm son las de todos los lotes, porque
`check_wave_records.py` lee la primera tabla de cada sección. Cubren los **5 lotes**: 31 + 17 + 17 + 10 + 24 = 99
filas `rename_refactoring` = 99 filas `pycharm` de `waves/A9c-1-mapping.csv`,
`waves/A9c-2-mapping.csv`, `waves/A9c-3-mapping.csv`, `waves/A9c-4-mapping.csv` y
`waves/A9c-5-mapping.csv` (tras su línea `# Fase 2`). El cierre de la subola está en «Cierre de A9c»
y el de toda la ola A9 en «Cierre de la ola A9», al final.

- Rama: lote 1 en `sdd/english-names-a9c-1`, sacada de `main` (`2888d90`, con A9a y A9b mezcladas).
  Commit del lote 1: `d1d002b` (PR #285). Lote 2: `34eb1fa` (PR #286), rebasado sobre `main` (`1d6290f`).
  Lote 3: `a9a87ba` (PR #287), rebasado sobre `main` (`2ed4fff`). Lote 4: `92e9879` (PR #288).
  Lote 5 en `sdd/english-names-a9c-5`, encima de `92e9879`; commit pendiente, con el borrador en
  `waves/A9c-5-commit-msg.txt` (firmado y sin coautoría).
- Quién: un agente hizo los 5 mappings (fase 1) y aplica los lotes tras la aprobación (fase 2).
- Conteo base: `evidence/A9c/collect-before.txt`, 2572 tests.

## Controles positivos

| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_transcripts.py::test_known_n_and_expiries` y `::test_the_ttl_depends_on_the_thread` (lote 1; usan `subagent`, `main_transcript`, `request_entry`, `result_entry`, `write_jsonl`, `KNOWN_N` y la variable renombrada `expiries`) | `src/local_delegate/transcripts.py:242`: `return len(later), caducidades` → `caducidades + 1` (sha256 `fb2e49f6…` → `afe60b28…`) | `assert expiries == 1` → `assert 2 == 1`, y `assert expiries == 0` → `assert 1 == 0` | sí, desde copia; sha256 igual al de antes (`evidence/A9c-1/mutant.txt`) |
| `tests/test_structured_summary.py::test_detects_the_sections_of_the_bench_documents` (lote 2; usa `SOURCES` y los argnames renombrados `name`/`count`, 5 casos) | `src/local_delegate/sections.py:130`: `detect` devuelve los títulos sin el primero (`at_level` → `at_level[1:]`; sha256 `cda2bd16…` → `5aed003d…`) | `assert len(structure.headings) == count` → `assert 10 == 11` (y `8 == 9`…) | sí, desde copia; sha256 igual al de antes (`evidence/A9c-2/mutant.txt`) |
| `tests/test_backend_probe.py::test_the_poll_never_raises` (lote 3; el arreglo de CodeQL: `raise AssertionError(…) from exc` en vez de `pytest.fail`) | `src/local_delegate/server.py:4293`: `probe_backend` relanza lo inesperado (`raise` como primera línea del `except Exception`; sha256 `2bfc147a…` → `e76ac534…`) | `raise AssertionError(f"el sondeo lanzó {exc!r}") from exc` → `AssertionError: el sondeo lanzó RuntimeError('inesperado')` (1 failed) | sí, desde copia; sha256 igual al de antes (`evidence/A9c-3/mutant.txt`) |
| `tests/test_load_probe.py::test_the_sample_translates_to_model_loaded` (lote 3; argnames renombrados `state`/`expected` y el parámetro de la lambda `_model`) | `src/local_delegate/server.py:1232`: `_LoadProbe` toma `"starting"` por cargado en vez de `"ready"` (sha256 → `52eaccc2…`) | `assert probe.model_loaded(wait_s=1.0) is expected` → `assert None is True` y `assert True is False` | sí, desde copia; sha256 igual |
| `tests/test_test_windows.py::test_the_edge_second` (lote 4; usa la fixture renombrada `wave11`, `_write` y los argnames nuevos `hour`/`inside`) | `src/local_delegate/test_windows.py:149`: `find` excluye el segundo final de la ventana (`t <= end` → `t < end`; sha256 `73a816a0…` → `9445e896…`) | `assert (wave11.find(ts) is not None) is inside, ts` → `assert (None is not None) is True` en `01:22:31` (1 failed, 4 passed) | sí, desde copia; sha256 igual al de antes (`evidence/A9c-4/mutant.txt`) |
| `tests/test_valuation.py` (lote 5; `test_each_expiry_is_a_rewrite`, con `_merged`, `_line` y `_backfill(exp=2)`, y el test de `n_of` con el relleno) | `src/local_delegate/valuation.py:95`: `n_of` ignora las caducidades del relleno (`… or 0` → `0`; sha256 `c04849d2…` → `53942581…`) | `assert c["estimate"] == pytest.approx(expected, …)` → `6.5 == 11.3`, y `assert valuation.n_of(…) == (7, 1, "backfill")` → `(7, 0, …) == (7, 1, …)` | sí, desde copia; sha256 igual al de antes (`evidence/A9c-5/mutant.txt`) |

## Llamadas `local_*` (sesión principal y cada agente)

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente A9c (fase 1) | (ninguna) | los mappings necesitaban nombres y líneas literales; las secciones de `A9a.md`/`A9b.md` se leyeron acotadas |
| Agente A9c-1 | `local_lint_summary(path=evidence/A9c-1/pytest-full.log)` | resumen de la corrida de la suite: verde, solo los 12 `DeprecationWarning` de siempre de `starlette.testclient` |
| Agente A9c-2 | `local_lint_summary(path=evidence/A9c-2/pytest-full.log)` | resumen de la suite: verde, solo los 12 `DeprecationWarning` de `starlette.testclient` |
| Agente A9c-3 | `local_lint_summary(path=evidence/A9c-3/pytest-full.log)` | resumen de la suite: verde (2570 passed, 2 skipped), solo los 12 `DeprecationWarning` de `starlette.testclient` |
| Agente A9c-4 | `local_lint_summary(path=evidence/A9c-4/pytest-full.log)` | resumen de la suite: verde (2570 passed, 2 skipped), solo los 12 `DeprecationWarning` de `starlette.testclient` |
| Agente A9c-5 | `local_lint_summary(path=evidence/A9c-5/pytest-full.log)` | resumen de la suite: 1 `TimeoutError` de `Page.goto` en `test_dashboard_ui.py` (intermitente, ver lote 5) y los 12 `DeprecationWarning` de siempre |

## Llamadas `mcp__pycharm__*`

| Agente | Tool | Símbolo / fichero | Resultado |
| --- | --- | --- | --- |
| A9c (fase 1) | `search_text` | `_ultimo_evento` en `tests/` | 9 apariciones en `test_respaldo.py` y `test_fallback_observability.py` (verifica las filas cross_module) |
| A9c (fase 1) | `search_regex` | constructores de `test_transcripts` en los que los importan | 35 apariciones en `test_quota.py`, `test_recalcular.py`, `test_recalcular_legacy.py` y `test_cli_renamed_names.py` |
| A9c-1 | `rename_refactoring` | `AHORA`→`NOW` (`test_recalcular.py`) | 14 usos |
| A9c-1 | `rename_refactoring` | `MES`→`MONTH` | 8 usos |
| A9c-1 | `rename_refactoring` | `_delegacion_con_n`→`_delegation_with_n` | 10 usos (con el import y el uso de `test_cli_renamed_names.py`) |
| A9c-1 | `rename_refactoring` | `_textos`→`_texts` | 3 usos |
| A9c-1 | `rename_refactoring` | `_foto`→`_tree_snapshot` | 2 usos |
| A9c-1 | `rename_refactoring` | `_sin_fechas`→`_without_dates` | 2 usos |
| A9c-1 | `rename_refactoring` | `AHORA`→`NOW` (`test_recalcular_legacy.py`) | 10 usos |
| A9c-1 | `rename_refactoring` | `MECANICO`→`MECHANICAL` (`test_respaldo.py`) | 59 usos (con `test_fallback_observability.py`) |
| A9c-1 | `rename_refactoring` | `LARGO`→`LONG` | 83 usos (con `test_fallback_observability.py` y `test_slowness.py`) |
| A9c-1 | `rename_refactoring` | `CODIGO`→`CODE` | 75 usos (ídem) |
| A9c-1 | `rename_refactoring` | `CAPACIDAD`→`CAPACITY_ERROR` | 3 usos |
| A9c-1 | `rename_refactoring` | `_fallo`→`_failure` | 39 usos |
| A9c-1 | `rename_refactoring` | `_estado_fichero`→`_state_file` | 9 usos |
| A9c-1 | `rename_refactoring` | `_enfriar`→`_cool_down` | 9 usos |
| A9c-1 | `rename_refactoring` | `_entradas`→`_entries` | 10 usos |
| A9c-1 | `rename_refactoring` | `_ultimo_evento`→`_last_event` | 10 usos; reescribió `waves/A9b.md` (devuelto a HEAD) |
| A9c-1 | `rename_refactoring` | `_texto`→`_text` | 20 usos |
| A9c-1 | `rename_refactoring` | `_vencido`→`_expired` | 2 usos |
| A9c-1 | `rename_refactoring` | `SESION`→`SESSION` (`test_transcripts.py`) | 8 usos |
| A9c-1 | `rename_refactoring` | `PREFIJO`→`PREFIX` | 2 usos |
| A9c-1 | `rename_refactoring` | `peticion`→`request_entry` | 32 usos |
| A9c-1 | `rename_refactoring` | `resultado`→`result_entry` | 11 usos; reescribió `.sdd/changes/subagente-lector-local/control_t4.py` (un atributo homónimo; devuelto a HEAD) |
| A9c-1 | `rename_refactoring` | `sintetica`→`synthetic` | 8 usos |
| A9c-1 | `rename_refactoring` | `compactacion`→`compaction` | 1 usos |
| A9c-1 | `rename_refactoring` | `escribir`→`write_jsonl` | 24 usos |
| A9c-1 | `rename_refactoring` | `linea_log`→`log_line` | 20 usos |
| A9c-1 | `rename_refactoring` | `escribir_log`→`write_log` | 8 usos |
| A9c-1 | `rename_refactoring` | `casar_todo`→`match_all` | 3 usos |
| A9c-1 | `rename_refactoring` | `_dos_subagentes`→`_two_subagents` | 2 usos |
| A9c-1 | `rename_refactoring` | `principal`→`main_transcript` | 15 usos |
| A9c-1 | `rename_refactoring` | `subagente`→`subagent` | 17 usos |
| A9c-1 | `get_file_problems` | `test_fallback.py`, `test_transcripts.py`, `test_recompute.py` | 0 errores |
| A9c-2 | `rename_refactoring` | `RAIZ`→`ROOT` (`test_resumen_estructurado.py`) | 2 usos |
| A9c-2 | `rename_refactoring` | `FUENTES`→`SOURCES` | 7 usos |
| A9c-2 | `rename_refactoring` | `ESPERADOS`→`EXPECTED_HEADINGS` | 9 usos |
| A9c-2 | `rename_refactoring` | `_llamar`→`_call_summary` | 16 usos |
| A9c-2 | `rename_refactoring` | `_eventos`→`_events` | 8 usos |
| A9c-2 | `rename_refactoring` | `_eco_prosa`→`_echo_prose` | 8 usos |
| A9c-2 | `rename_refactoring` | `_documento`→`_document` | 1 usos |
| A9c-2 | `rename_refactoring` | `SISTEMA_MAIN`→`MAIN_SYSTEM` | 7 usos |
| A9c-2 | `rename_refactoring` | `_lista_del_prompt`→`_prompt_list` | 8 usos |
| A9c-2 | `rename_refactoring` | `_largo`→`_long_doc` | 5 usos |
| A9c-2 | `rename_refactoring` | `_responde_titulos`→`_answer_headings` | 5 usos |
| A9c-2 | `rename_refactoring` | `_secciones_de`→`_sections_of` | 5 usos |
| A9c-2 | `rename_refactoring` | `MODELO_RETIRADO`→`RETIRED_MODEL` (`test_rol_fast_retirado.py`) | 5 usos |
| A9c-2 | `rename_refactoring` | `VARIABLES_RETIRADAS`→`RETIRED_VARIABLES` | 5 usos |
| A9c-2 | `rename_refactoring` | `_responde`→`_reply` | 1 usos |
| A9c-2 | `rename_refactoring` | `_no_responde`→`_no_answer` | 1 usos |
| A9c-2 | `rename_refactoring` | `_delegar`→`_delegate` | 2 usos |
| A9c-2 | `get_file_problems` | `test_structured_summary.py`, `test_fast_role_retired.py` | 0 errores |
| A9c-3 | `rename_refactoring` | `RAIZ`→`ROOT` (`test_site.py`) | 16 usos |
| A9c-3 | `rename_refactoring` | `FAVICON_SITIO`→`SITE_FAVICON` | 3 usos |
| A9c-3 | `rename_refactoring` | `FAVICON_PAQUETE`→`PACKAGE_FAVICON` | 5 usos |
| A9c-3 | `rename_refactoring` | `_cargar_build_site`→`_load_build_site` | 1 usos |
| A9c-3 | `rename_refactoring` | `_cabecera_png`→`_png_header` | 2 usos |
| A9c-3 | `rename_refactoring` | `_manifiesto_iconos`→`_icon_manifest` | 3 usos |
| A9c-3 | `rename_refactoring` | `RAIZ`→`ROOT` (`test_sonda.py`) | 3 usos |
| A9c-3 | `rename_refactoring` | `solo_windows`→`windows_only` | 5 usos; reescribió `waves/A9a.md` (devuelto a HEAD) |
| A9c-3 | `rename_refactoring` | `backend_falso`→`fake_backend` | 4 usos (fixture: arrastra los parámetros que la piden) |
| A9c-3 | `rename_refactoring` | `_cargar_script`→`_load_probe_script` | 2 usos |
| A9c-3 | `rename_refactoring` | `_HIJO`→`_CHILD` | 2 usos |
| A9c-3 | `rename_refactoring` | `_timeout_tras`→`_timeout_after` (`test_sonda_carga.py`) | 1 usos |
| A9c-3 | `rename_refactoring` | `remoto`→`remote` (`test_sondeo_backend.py`) | 9 usos (fixture: arrastra los parámetros que la piden) |
| A9c-3 | `rename_refactoring` | `_linea_backend`→`_backend_line` | 3 usos |
| A9c-3 | `rename_refactoring` | `_estado_de`→`_state_of` | 3 usos |
| A9c-3 | `rename_refactoring` | `_ip_de_salida`→`_outbound_ip` | 1 usos |
| A9c-3 | `rename_refactoring` | `status_sin_extras`→`status_without_extras` | 4 usos (fixture) |
| A9c-3 | `get_file_problems` | `test_site.py`, `test_resource_probe.py`, `test_load_probe.py`, `test_backend_probe.py` | 0 errores propios: solo `Unresolved reference 'Client'` en la cadena de `monkeypatch.setattr(benchmark.httpx2, "Client", …)`, que ya estaba |
| A9c-4 | `rename_refactoring` | `_escribir`→`_write` (`test_test_windows.py`) | 3 usos |
| A9c-4 | `rename_refactoring` | `ola11`→`wave11` | 6 usos (fixture: arrastra los parámetros que la piden) |
| A9c-4 | `rename_refactoring` | `_abrir`→`_open` | 1 usos |
| A9c-4 | `rename_refactoring` | `_ventanas`→`_windows` (`test_test_windows_cli.py`) | 6 usos |
| A9c-4 | `rename_refactoring` | `MODELO_LARGO`→`LONG_MODEL` (`test_topes_por_rol.py`) | 8 usos |
| A9c-4 | `rename_refactoring` | `_respuesta`→`_response` | 6 usos; reescribió `waves/A9a.md` (devuelto a HEAD) |
| A9c-4 | `rename_refactoring` | `_texto`→`_text` | 5 usos |
| A9c-4 | `rename_refactoring` | `pet`→`req` (`test_turn.py`) | 48 usos |
| A9c-4 | `rename_refactoring` | `_sin_senales_reales`→`_without_real_signals` (`test_update.py`) | 0 usos (fixture `autouse`: lo esperado) |
| A9c-4 | `rename_refactoring` | `_finge_prefix`→`_fake_prefix` | 8 usos |
| A9c-4 | `get_file_problems` | `test_update.py`, `test_role_caps.py`, `test_test_windows.py` | 0 errores |
| A9c-5 | `rename_refactoring` | `AHORA`→`NOW` (`test_valoracion.py`) | 20 usos |
| A9c-5 | `rename_refactoring` | `MES`→`MONTH` | 4 usos |
| A9c-5 | `rename_refactoring` | `_sin_respaldo_del_entorno`→`_without_env_fallback` | 0 usos (fixture `autouse`: lo esperado) |
| A9c-5 | `rename_refactoring` | `_linea`→`_line` | 25 usos |
| A9c-5 | `rename_refactoring` | `_fundidas`→`_merged` | 11 usos |
| A9c-5 | `rename_refactoring` | `_relleno`→`_backfill` | 14 usos |
| A9c-5 | `rename_refactoring` | `_con_ventana`→`_with_window` | 2 usos |
| A9c-5 | `rename_refactoring` | `MUY_POSTERIOR`→`MUCH_LATER` (`test_vendor.py`) | 7 usos |
| A9c-5 | `rename_refactoring` | `vendor_copia`→`vendor_copy` | 32 usos (fixture: arrastra los parámetros que la piden) |
| A9c-5 | `rename_refactoring` | `_caido`→`_down` | 3 usos |
| A9c-5 | `rename_refactoring` | `VERSION_VENDORIZADA`→`VENDORED_VERSION` | 6 usos |
| A9c-5 | `rename_refactoring` | `_sin_red`→`_without_network` | 9 usos |
| A9c-5 | `rename_refactoring` | `cliente`→`client` (`test_web_auth.py`) | 16 usos (fixture); reescribió 10 documentos de `.sdd/` de otros cambios (devueltos a HEAD) |
| A9c-5 | `rename_refactoring` | `_con_cookie`→`_with_cookie` | 7 usos |
| A9c-5 | `rename_refactoring` | `RAIZ`→`ROOT` (`test_wiki.py`) | 6 usos |
| A9c-5 | `rename_refactoring` | `_GRUPOS_DE_LA_TABLA`→`_TABLE_GROUPS` | 2 usos |
| A9c-5 | `rename_refactoring` | `_NUMERO_DE_TOOLS`→`_TOOL_COUNT_WORDS` | 2 usos |
| A9c-5 | `rename_refactoring` | `_NUMERO_DE_CHECKS`→`_CHECK_COUNT_WORDS` | 13 usos |
| A9c-5 | `rename_refactoring` | `ENLACE_RE`→`LINK_RE` | 2 usos (no tocó el homónimo de `scripts/sync_wiki.py`) |
| A9c-5 | `rename_refactoring` | `_paginas`→`_pages` | 7 usos |
| A9c-5 | `rename_refactoring` | `_enlaces`→`_links` | 4 usos |
| A9c-5 | `rename_refactoring` | `_filas_de_la_tabla_de_checks`→`_check_table_rows` | 1 usos |
| A9c-5 | `rename_refactoring` | `_tools_del_servidor`→`_server_tools` | 3 usos |
| A9c-5 | `rename_refactoring` | `_tools_documentadas`→`_documented_tools` | 1 usos |
| A9c-5 | `get_file_problems` | `test_valuation.py`, `test_web_auth.py`, `test_wiki.py`, `test_vendor.py` | 0 errores |

## A9c-1 — `fake_llamaswap`, `test_fake_llamaswap`, `test_recalcular`, `test_recalcular_legacy`, `test_release_metadata`, `test_residency`, `test_respaldo` y `test_transcripts` (aplicado)

### A9c-1 · Qué se hizo

- 31 `rename_refactoring` (tabla de arriba), en los ficheros con su nombre viejo y antes de cualquier
  edición desde fuera.
- Los 14 parámetros homónimos (`sesion` ×6, `proyecto` ×2, `modelo` ×3, `mes`, `raiz` y `coste`) por
  `a9c/param_ren.py`: dentro del tramo de su función y en los kwargs de sus llamadas
  (`test_recalcular.py` 13 y `test_quota.py` 2). Los dos usos dentro de f-strings
  (`f"{sesion}.jsonl"`, `f"usage-{mes}.jsonl"`) a mano: el tokenizador de 3.11 no entra en ellas.
- `make_mapping.py apply` con una copia del CSV con los ámbitos ya renombrados (`a9c/requal.py`):
  114 + 9 + 7 + 209 + 84 = 423 reemplazos.
- A mano (`apply` no lo hace): la anidada `efecto`→`effect` y la clase anidada `_Eleccion`→`_Choice`
  de `test_respaldo.py`; las 8 claves de llama-swap (`"recargando"`/`"recargada"`/`"rechazo"` ×3 en
  `fake_llamaswap.py`; `"durante"`/`"t_descarga"`/`"cargado_a_los_4s"` ×2, `"estado"` ×3 y
  `"duracion"` ×2 en `test_fake_llamaswap.py`, más las dos lecturas `r['…']` del f-string de :72;
  el rótulo `durante=`/`t_descarga=` del `print` se queda, decisión 5); las citas entre comillas
  invertidas del docstring de `test_transcripts.py` (`request_entry`, `result_entry`, `write_jsonl`,
  `test_recompute.py`) y la de `fake_llamaswap.py:421` (`escribir()` → `write()`, el parámetro que ya
  renombró A9b).
- `git mv` de 3 módulos (`test_recompute.py`, `test_recompute_legacy.py`, `test_fallback.py`) y sus
  imports en `test_cli_renamed_names.py`, `test_fallback_observability.py` y `test_slowness.py`.
- `ruff format` reflowó 3 ficheros y `ruff check --fix` reordenó 4 bloques de imports (I001) por los
  nombres nuevos.
- EOL: los ficheros tocados son LF y siguen LF (`git ls-files --eol`).

### A9c-1 · Fuera del lote (consecuencia mecánica, aprobada)

- `tests/test_cli_renamed_names.py`, `tests/test_quota.py`, `tests/test_fallback_observability.py`
  y `tests/test_slowness.py`: imports, usos y kwargs `sesion=`.
- `tests/test_chains.py:4`: cita `test_fallback.py` en su docstring.

### A9c-1 · Barrido final

- AST de los 8 ficheros y de los 4 de fuera del lote: ningún nombre de código, kwarg, argname de
  `parametrize`, `except … as` ni alias de import con un `old` del lote; todos los argnames de
  `parametrize` son parámetros de su test.
- Tokens con un `old` en los 8 ficheros: 0 en código; 22 + 14 + 34 + 12 + 26 + 3 + 50 + 14 en
  cadenas y 41 en comentarios: prosa en español, valores de prueba y claves del producto o
  persistidas (`respaldo` de `_local_delegate`, `espera_s` del fichero viejo de enfriamiento).
- `git grep -w` de los `old` multipalabra en `tests/`, `src/` y `scripts/`: solo homónimos ajenos
  (`peticion` en `scripts/ci_gate.py`, palabras del léxico del detector).
- `--collect-only`: 2572 (`evidence/A9c-1/collect.txt`), los mismos tests por módulo que en
  `collect-before.txt` (con los tres módulos renombrados).
- Suite (`-n auto --dist loadgroup`): 2570 passed, 2 skipped (`evidence/A9c-1/pytest-full.log`); sin
  intermitentes en esta corrida. `ruff check` y `ruff format --check` en verde
  (`evidence/A9c-1/ruff-check.txt`).
- CodeQL (aproximación AST de `a9c/codeql_like.py` y `a9c/codeql_more.py` sobre los 3 ficheros
  renombrados): 0 patrones; ningún `except X: pass`.

### A9c-1 · Desviaciones

1. **14 filas `pycharm` → `search_edit`**, anotado en la línea `# Fase 2` del CSV: los parámetros
   homónimos de los ayudantes.
2. PyCharm reescribió `waves/A9b.md` y `.sdd/changes/subagente-lector-local/control_t4.py`; los dos
   se devolvieron a HEAD.


## A9c-2 — `test_resumen_estructurado` y `test_rol_fast_retirado` (aplicado)

### A9c-2 · Qué se hizo

- 17 `rename_refactoring` (tabla de arriba), antes de cualquier edición desde fuera. Ninguno
  reescribió ficheros de `.sdd/`.
- Los 4 parámetros homónimos (`rol_largo` y `estructurado` de `_llamar`, con sus 3 kwargs; `modelo`
  de la anidada `_responde._fn` y de `_no_responde`) por `a9c/param_ren.py`.
- `make_mapping.py apply` con la copia del CSV con los ámbitos ya renombrados: 443 + 39 = 482
  reemplazos.
- A mano (`apply` no lo hace): los `def` de 8 anidadas (`_modelo` ×5 → `_model`, `_falla` → `_fails`,
  `_con_desborde` → `_with_overflow`, `_lista` → `_listing`) y los argnames de 2 `parametrize`
  (`("nombre", "cuantos")` → `("name", "count")`, `"marca"` → `"mark"`).
- `git mv` de los 2 módulos (`test_structured_summary.py`, `test_fast_role_retired.py`).
- `ruff format` reflowó los 2 ficheros (líneas que ahora caben).
- EOL: los ficheros tocados son LF y siguen LF.

### A9c-2 · Fuera del lote (consecuencia mecánica, aprobada)

- `src/local_delegate/sections.py:13`: cita `tests/test_structured_summary.py` en su docstring.
- `tests/test_chains.py:248`: cita `test_fast_role_retired.py` en un comentario.

### A9c-2 · Barrido final

- AST de los 2 ficheros: ningún nombre de código, kwarg, argname de `parametrize`, `except … as` ni
  alias de import con un `old` del lote; todos los argnames son parámetros de su test.
- Tokens con un `old`: 0 en código; 45 + 11 en cadenas y 8 + 3 en comentarios. Las cadenas (fuera de
  docstrings) son markdown de prueba (`texto`, `fin`), textos del producto que el test afirma
  (`Secciones, en orden:`, `salida truncada`, `Resume el siguiente contenido:`, `modelo inválido`) y
  la carpeta `benchmarks/resumen-estructurado/` (no cambia).
- `git grep -w test_resumen_estructurado|test_rol_fast_retirado` fuera de `.sdd/`, `benchmarks/` y
  `CHANGELOG.md`: 0.
- `--collect-only`: 2572 (`evidence/A9c-2/collect.txt`), los mismos tests por módulo que en el lote 1.
- Suite (`-n auto --dist loadgroup`): 2570 passed, 2 skipped (`evidence/A9c-2/pytest-full.log`), sin
  intermitentes. `ruff check` y `ruff format --check` en verde (`evidence/A9c-2/ruff-check.txt`).
- CodeQL (aproximación AST sobre los 2 ficheros renombrados): 0 patrones; ningún `except X: pass`.

### A9c-2 · Desviaciones

1. **4 filas `pycharm` → `search_edit`**, anotado en la línea `# Fase 2` del CSV: los parámetros
   homónimos.


## A9c-3 — `test_site`, `test_smoke`, `test_sonda`, `test_sonda_carga` y `test_sondeo_backend` (aplicado)

### A9c-3 · Qué se hizo

- 17 `rename_refactoring` (tabla de arriba), antes de cualquier edición desde fuera.
- Los 7 parámetros homónimos (`modelo`/`estado` de `_running`; `estado`, `clase` y `cuerpo` de tests
  parametrizados; `modelo` de la anidada `consultar`) por `a9c/param_ren.py` o a mano por línea (hay
  dos anidadas `consultar` en el fichero).
- `make_mapping.py apply` con la copia del CSV con los ámbitos ya renombrados: 250 + 46 + 119 + 59 +
  77 = 551 reemplazos.
- A mano (`apply` no lo hace): los `def` de 8 anidadas (`_no_arrancar` ×3 → `_do_not_start`,
  `_Cerrado` → `_Closed`, `rota` → `broken`, `consultar` ×2 → `query`, `efecto` → `effect`), los
  argnames de 4 `parametrize` (`("estado", "esperado")` → `("state", "expected")`,
  `("estado", "clase")` → `("state", "error_class")`, `"efecto"` → `"effect"`, `"cuerpo"` → `"body"`)
  y el parámetro de la lambda `_modelo` → `_model`.
- **Arreglo de CodeQL aprobado**: en `test_backend_probe.py`, el `pytest.fail(...)` del `except` de
  `test_the_poll_never_raises` pasa a `raise AssertionError(f"el sondeo lanzó {exc!r}") from exc`.
  `a9c/codeql_more.py` daba `uninitialized-local? ['estado']` sobre la copia de antes y ya no da nada;
  el mutante 1 de arriba prueba que el test sigue fallando si el sondeo lanza.
- `git mv` de 3 módulos (`test_resource_probe.py`, `test_load_probe.py`, `test_backend_probe.py`).
- `ruff format` reflowó 2 ficheros.
- EOL: `test_smoke.py` es CRLF y sigue CRLF; el resto, LF y siguen LF (`git ls-files --eol`).

### A9c-3 · Fuera del lote (consecuencia mecánica, aprobada)

- Ninguno: nadie importa ni cita por ruta estos módulos fuera de `.sdd/` histórico.

### A9c-3 · Barrido final

- AST de los 5 ficheros: ningún nombre de código, kwarg, argname de `parametrize`, `except … as` ni
  alias de import con un `old` del lote; todos los argnames son parámetros de su test.
- Tokens con un `old`: 0 en código; 44 + 7 + 27 + 5 + 11 en cadenas y 26 en comentarios. Las cadenas
  (fuera de docstrings) son mensajes de assert en español, nombres de fichero de prueba
  (`medida.json`, `mapeado.bin`), los ids de `parametrize` (`data-texto`) y el programa hijo `_CHILD`
  con sus claves `quieto`/`anonimo`/`mapeado` (decisión 4: se quedan).
- `git grep -w test_sonda|test_sonda_carga|test_sondeo_backend` fuera de `.sdd/`, `benchmarks/` y
  `CHANGELOG.md`: 0.
- `--collect-only`: 2572 (`evidence/A9c-3/collect.txt`), los mismos tests por módulo que en el lote 2.
- Suite (`-n auto --dist loadgroup`): 2570 passed, 2 skipped (`evidence/A9c-3/pytest-full.log`), sin
  intermitentes. `ruff check` y `ruff format --check` en verde (`evidence/A9c-3/ruff-check.txt`).
- CodeQL (aproximación AST sobre los 3 ficheros renombrados): 0 patrones; ningún `except X: pass`.

### A9c-3 · Desviaciones

1. **7 filas `pycharm` → `search_edit`**, anotado en la línea `# Fase 2` del CSV: los parámetros
   homónimos.
2. El primer intento del mutante 1 no mutó nada (`server.py` es CRLF y la búsqueda era con `
`); la
   guarda del sha256 lo detectó (`antes` = `con mutante`) y se repitió con el fin de línea del fichero;
   `mutant.txt` guarda solo la corrida buena.


## A9c-4 — `test_test_windows`, `test_test_windows_cli`, `test_topes_por_rol`, `test_turn`, `test_turn_daemon` y `test_update` (aplicado)

### A9c-4 · Qué se hizo

- 10 `rename_refactoring` (tabla de arriba), antes de cualquier edición desde fuera.
- Los 6 parámetros homónimos `inicio`/`fin` de tres tests parametrizados por `a9c/param_ren.py`, con
  sus argnames.
- `make_mapping.py apply` con la copia del CSV con los ámbitos ya renombrados: 65 + 39 + 27 + 2 + 188
  = 321 reemplazos.
- A mano (`apply` no lo hace): los `def` de 2 anidadas (`sin_aviso` → `without_warning`, `_espia` →
  `_spy`) y los argnames de 10 `parametrize` más (`hora`/`dentro`, `contenido`/`motivo`, `operacion`,
  `abiertas`/`codigo`, `publicada`, `instalada`, `esperado`/`comando`, `espera_ruta`), por script que
  toma el `new` de la fila `param` de cada uno.
- La `y` de `test_turn_daemon.py` se queda (decisión 3).
- `git mv` de `test_topes_por_rol.py` → `test_role_caps.py`.
- `ruff format` reflowó 1 fichero.
- EOL: los ficheros tocados son LF y siguen LF.

### A9c-4 · Fuera del lote (consecuencia mecánica, aprobada)

- Ninguno: nadie importa ni cita por ruta `test_topes_por_rol` fuera de `.sdd/` histórico, y
  `test_install_opencode.py` importa de `test_update` solo `opts_for`, que no cambia.

### A9c-4 · Barrido final

- AST de los 6 ficheros: ningún nombre de código, kwarg, argname de `parametrize`, `except … as` ni
  alias de import con un `old` del lote; todos los argnames son parámetros de su test.
- Tokens con un `old`: 0 en código; 141 en cadenas y 50 en comentarios. Las cadenas (fuera de
  docstrings) son mensajes de assert en español, textos del producto que afirman los tests
  (`publicada`, `sin tocar los pines`, `sin LLAMASWAP_CONFIG`…) y valores de prueba (`motivo`,
  `sin-numeros`, `# viejo`).
- `git grep -w test_topes_por_rol` fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`: 0.
- `--collect-only`: 2572 (`evidence/A9c-4/collect.txt`), los mismos tests por módulo que en el lote 3.
- Suite (`-n auto --dist loadgroup`): 2570 passed, 2 skipped (`evidence/A9c-4/pytest-full.log`), sin
  intermitentes. `ruff check` y `ruff format --check` en verde (`evidence/A9c-4/ruff-check.txt`).
- CodeQL (aproximación AST sobre el fichero renombrado): 0 patrones; ningún `except X: pass`.

### A9c-4 · Desviaciones

1. **6 filas `pycharm` → `search_edit`**, anotado en la línea `# Fase 2` del CSV: los parámetros
   homónimos `inicio`/`fin`.
2. El primer script de argnames usaba los `col_offset` del AST, que cuentan bytes UTF-8: falló su
   propia comprobación en una línea con dos argnames antes de escribir nada, y se rehízo con reemplazo
   de la cadena entre comillas, línea a línea.


## A9c-5 — `test_valoracion`, `test_vendor`, `test_vision`, `test_web_auth` y `test_wiki` (aplicado)

### A9c-5 · Qué se hizo

- 24 `rename_refactoring` (tabla de arriba), antes de cualquier edición desde fuera. El de la fixture
  `cliente` reescribió 10 documentos de `.sdd/` de otros cambios (`chartjs-4-5-1`,
  `coste-api-y-cuota`, `daemon-reparte-el-backend`, `test-windows-out-of-metrics`); los 10 se
  devolvieron a HEAD.
- Los 3 parámetros homónimos (`modelo` y `cad` de `_relleno`, `duracion` de `_app`) por
  `a9c/param_ren.py`, con sus 6 kwargs (`cad=` ×2, `modelo=`, `duracion=` ×3).
- `make_mapping.py apply` con la copia del CSV con los ámbitos ya renombrados: 118 + 50 + 4 + 178 +
  148 = 498 reemplazos.
- A mano (`apply` no lo hace): los `def` de 8 anidadas (`raiz` → `root`, `montada` → `mounted`, `ruta`
  ×2 → `path`, `recibir` → `receive` y `enviar` → `send` en `test_web_auth.py`; `falso` → `fake` en
  `test_vendor.py`; `_rota` → `_broken` en `test_valoracion.py`), los argnames de 3 `parametrize`
  (`"ruta"` → `"path"`, `"cabecera"` → `"header"`, `("version", "esperado")` →
  `("version", "expected")`) y las citas entre comillas invertidas de `VENDORED_VERSION` y
  `MUCH_LATER` (comentario de `test_vendor.py`) y de `exp` (docstring de `test_valoracion.py`).
- `test_wiki.py`: solo nombres del test. Los títulos, grupos y números escritos de la wiki con los que
  compara (`"Entorno"`, `"diez"`, `"once"`…) son datos y no se tocan.
- `git mv` de `test_valoracion.py` → `test_valuation.py`.
- `ruff format` reflowó 2 ficheros.
- EOL: `test_vendor.py` es CRLF y sigue CRLF; el resto, LF y siguen LF.

### A9c-5 · Fuera del lote (consecuencia mecánica, aprobada)

- Ninguno: nadie importa ni cita por ruta `test_valoracion` fuera de `.sdd/` histórico.

### A9c-5 · Barrido final

- AST de los 5 ficheros: ningún nombre de código, kwarg, argname de `parametrize`, `except … as` ni
  alias de import con un `old` del lote; todos los argnames son parámetros de su test.
- Tokens con un `old`: 0 en código; 200 en cadenas y 56 en comentarios. Las cadenas (fuera de
  docstrings) son mensajes de assert en español, textos del producto (`Extensión de imagen no
  soportada`, `leído server-side…`), los cuerpos de respuesta de prueba `"raiz"`/`"montada"`
  (decisión de la fase 1), los rótulos de los casos de `test_web_auth.py` (`"caducada"`,
  `"firma inventada"`) y rutas de prueba (`fuera-del-repo.md`).
- `--collect-only`: 2572 (`evidence/A9c-5/collect.txt`), los mismos tests por módulo que en el lote 4
  y que en `evidence/A9c/collect-before.txt` (con los 10 módulos renombrados).
- Suite (`-n auto --dist loadgroup`): **1 fallo intermitente ajeno al lote** en las tres corridas
  completas y en una cuarta que excluye los 5 ficheros del lote
  (`evidence/A9c-5/pytest-control-sin-lote5.log`): un `Page.goto` de Playwright que agota sus 30 s en
  un test `[cargadas]` de `test_dashboard_ui.py`, distinto cada vez
  (`test_the_kpi_row_is_symmetric_and_uses_decimal_comma`, `test_the_hero_line_does_not_overlap_its_hint`,
  `test_the_kpi_unit_is_not_cut_off`). Suelto pasa, y el módulo entero con `-n auto` también
  (38 passed, 1 skipped). Corridas: `pytest-full-run1.log` (2 failed, 2568 passed);
  `pytest-full-run2.log` y `pytest-full.log` (1 failed, 2569 passed cada una). Tras los arreglos de las desviaciones 3 y 4, `pytest-full-final.log`: 2 failed, 2568 passed (el mismo `Page.goto` y el intermitente de tiempos de `test_fake_llamaswap.py`, pendiente 9; los dos pasan sueltos). `ruff check` y
  `ruff format --check` en verde (`evidence/A9c-5/ruff-check.txt`).
- CodeQL (aproximación AST sobre el fichero renombrado): 0 patrones; ningún `except X: pass`.

### A9c-5 · Desviaciones

1. **3 filas `pycharm` → `search_edit`**, anotado en la línea `# Fase 2` del CSV: los parámetros
   homónimos.
2. El intermitente de `test_dashboard_ui.py` salió en todas las corridas completas de este lote y en
   ninguna de los lotes 1 a 4; como sale igual sin los ficheros del lote, se anota como intermitente
   (pendiente 11) y no se toca.
3. **Dos restos de renombrados de A9 arreglados en este lote** (pedido de la sesión principal):
   - `test_fallback.py:658`: `kwargs.get("ultimo")` → `kwargs.get("last")` (el kwarg de
     `server._next_hop` se llama `last` desde una ola anterior).
   - `test_residency.py:858-881`: la clave propia del test `reads = {"durante": 0}` → `"during"`, con
     sus 2 lecturas.
4. **Control positivo del arreglo de `"ultimo"` → `"last"`: NO discrimina** (`evidence/A9c-5/control-last.txt`).
   Con el test instrumentado (copia restaurada, sha256 igual), las dos claves dan lo mismo: A toma
   **una sola** decisión de salto, con `last` a `None` (el respaldo sale bien y no hay segunda), así
   que la guarda vale lo mismo con `"ultimo"` que con `"last"`; y en cualquier decisión posterior
   `b_entered` ya estaría puesto y la espera no esperaría. El defecto solo cambiaría la duración en un
   escenario que el test no tiene (salto dentro de la plaza y un segundo salto), y el test no afirma
   duraciones. No se forzó un mutante: el arreglo es de nombre y lo que el test afirma
   (`peak == 1` y el orden A, B) no depende de él.
5. **Barrido del mismo patrón en todo `tests/`** (`evidence/A9c-5/stale-keys-sweep.txt`): toda
   lectura `.get("x")`, `["x"]`, `.pop("x")` o `"x" in`/`not in` cuya `x` es un `old` de cualquier
   mapping de A0 a A9c. 107 claves; 81 siguen entre comillas en `src/` o `scripts/` (claves del
   producto, valores viejos con lectura dual o de A10). Las 26 que ya no salen en `src/` ni en
   `scripts/` se revisaron una a una: textos en prosa (`"trocear" not in`, `"cierre" in`,
   `"publicada" in`), datos y nombres de campo que el propio test define (`"puerto"` en
   `local_extract(fields=…)`, `"otro"`/`"proyecto"` de configs de prueba, `"# cabecera"` del YAML de
   prueba, `"secreto"`), ids de casos, las claves del programa hijo (decisión 4) y ficheros de A10
   (`test_vigilante`, `test_medir_enfriamiento`, `test_analisis_benchmark`). **Ninguna es una lectura
   obsoleta como `"ultimo"`**; con los dos arreglos, el barrido no deja nada de A9.

## Cierre de A9c

- **Barrido de los 5 mappings** sobre los ficheros con su nombre final, incluidos los 4 de fuera del
  lote 1 (`evidence/A9c-5/a9c-close-sweep.txt`): 0 nombres de código con un `old` en los 31 ficheros;
  ninguno de los 10 módulos viejos sigue en disco.
- **Detector** (`scripts/detect_spanish_names.py --exceptions rename-exceptions.md`; completo en
  `evidence/A9c-5/detector-full.json`, filtrado a los ficheros de A9c en `detector-a9c.json`):
  **114 hallazgos en los ficheros de A9c, 0 identificadores**. Son 37 `string_key` y 77
  `string_value`:
  - claves y valores del producto, persistidos o viejos que el test lee a propósito:
    `respaldo`/`respondio`/`en_lugar_de` de `_local_delegate` (pendiente 5); `fallos`/`espera_s`/`hasta`
    del fichero viejo de enfriamiento; el formato viejo de `coste-agregados.json` en
    `test_recompute_legacy.py` (`puntos`, `fuente`, `veredicto`, `n_por_mes`…); `pruebas` de la
    valoración (pendiente 10); los nombres viejos con alias (`LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO`,
    `config.rol_retirado`);
  - de scripts (A10): `sonda_recursos`/`sonda_recursos.py` en `test_resource_probe.py`;
  - datos de prueba:
    - ids de casos: `ancla`, `duplicadas`, `flujo` y `residente` en `test_residency.py`; los 18
      `*_es_lista`/`*_es_texto` de `test_topology.py`; `cambio_ajeno` y `yaml_roto` en
      `test_fake_llamaswap.py`;
    - nombres de fichero (`medida.json`, `mapeado.bin`, `copia.bak`…);
    - tokens y sesiones falsos (`clave-falsa`, `sesion-sintetica-0001`, `otro-token`…);
    - las claves `quieto`/`anonimo`/`mapeado` del programa hijo (decisión 4);
    - los rótulos del espía `tomar_plaza`/`soltar_plaza` de `test_turn_daemon.py`;
  - **dos restos del propio test que la fase 1 no listó**: `kwargs.get("ultimo")` en
    `test_fallback.py:658` y la clave `"durante"` de `reads` en `test_residency.py:858`. **Hechos** en
    el lote 5 (desviaciones 3 a 5 de A9c-5).
- **Tests recogidos**: `evidence/A9c/collect-before.txt` 2572 → `evidence/A9c-5/collect.txt`
  **2572**, los mismos por módulo.
- **Mappings**: 1269 filas en 5 lotes, todas aplicadas. 99 `pycharm` = 99 `rename_refactoring`. Las
  filas que pasaron de `pycharm` a `search_edit` en la fase 2 suman 34 (14 + 4 + 7 + 6 + 3), todas
  parámetros homónimos, y cada lote las anota en su línea `# Fase 2`.
- **Lecciones** (además de las de A9a y A9b):
  1. PyCharm también reescribe documentos de `.sdd/` de **otros** cambios (lote 5: 10 ficheros por la
     fixture `cliente`): revisar `git status` entero, no solo la carpeta del SDD.
  2. Los argnames de `parametrize` y los `def` de las anidadas son la mayor fuente de restos de
     `apply`. Un check AST «todo argname es parámetro de su test» los encuentra todos.
  3. Las posiciones del AST (`col_offset`) cuentan bytes UTF-8: para editar por columnas, convertir
     o reemplazar la cadena entera.
  4. En un fichero CRLF, un mutante buscado con `\n` falla en silencio. Lo que lo destapa es la guarda
     del sha256.
  5. Una clave que viaja como **kwarg de una función del producto** (`kwargs.get("ultimo")`) no la ve
     ni el mapping ni el barrido de nombres: la encontró el detector de cadenas.

## Cierre de la ola A9

- **Detector sobre todo `tests/` salvo los ficheros de A10** (`test_medir_*`,
  `test_analisis_benchmark`, `test_corpus`, `test_hoja_*`, `test_vigilante`,
  `test_experimento_adopcion`, `test_sesiones*` y `fixtures/vigilante/`; filtrado en
  `evidence/A9c-5/detector-a9.json`): **503 hallazgos**: 358 `string_value`, 127 `string_key` y
  **18 identificadores**. En los ficheros de A10 quedan 1074, que son de A10.
- **Los 18 identificadores**, todos explicados y ninguno de A9:
  - 4 kwargs de `ci_gate` (`leer`, `reloj`, `dormir` y `escribir`, en `test_ci_gate.py:175-178`): A10;
  - 2 kwargs `descartada`/`descartada_motivo` (`test_affinity_batch.py:229`): claves persistidas del
    benchmark, A10;
  - 3 kwargs que dan nombre de fichero (`ajeno`, `raro`, `roto` en `test_agents.py`): datos
    (decisión 6 de A9a);
  - 3 kwargs con claves viejas que el test mete a propósito (`bloqueo_id`, `secciones` y
    `fallo_conexion` en `test_metrics.py:1522-1528`): compatibilidad con logs viejos;
  - el kwarg `LOCAL_DELEGATE_COSTE_RESPALDO` (`test_cli_renamed_names.py:270`): nombre viejo a
    propósito;
  - 2 `test_*` que nombran el script retirado `anotar_llamada` (`test_install.py`): dato;
  - 3 falsos positivos del detector en nombres ingleses (`…_as_suspicion` ×2 y
    `…_appears_as_a_meter`).
- **Las cadenas** (485): textos del producto que afirman los tests, valores y claves persistidos o
  viejos a propósito, datos de prueba (ids, nombres de fichero, etiquetas) y lo de los pendientes de
  abajo. Ninguna es un nombre de Python de un test.
- **Tests recogidos al cerrar A9**: 2572 (2567 al empezar A9a, +2 de A9a y +3 de A9b; A9c no añade
  ninguno).

## Pendientes de A9 (para A10 y el cierre del frente A), por ola

**A10 (scripts)**
1. Los kwargs de `ci_gate.esperar_veredicto` (`leer=`, `reloj=`, `dormir=`, `escribir=`), su
   `v.estado`/`v.motivo` y sus constantes: `test_ci_gate.py` cambia por consecuencia (A9a, pendiente 7).
2. El JS propio de `scripts/dev/capture_dashboard.py` heredado de A8b (A9a, pendiente 8).
3. Las claves persistidas del benchmark `descartada`/`descartada_motivo` que pasa
   `test_affinity_batch.py:229` (A9a, pendiente 9), y `sonda_recursos`, que lee
   `test_resource_probe.py` y cambia con `scripts/sonda_recursos.py` → `resource_probe.py`.
4. Las claves del informe de `scripts/measure_slowness.py` que lee `test_measure_slowness.py`
   (`cumple`, `faltan`, `eventos_pc`…; A9b, pendiente 4).

**Cierre del frente A (producto; decide la sesión principal)**
5. Las claves `respaldo`/`respondio`/`en_lugar_de` de `_local_delegate` que escribe y lee
   `src/local_delegate/server.py:1101` y `:2308`, y que lee `test_fallback.py` (decisión 9 de A9c).
6. La clave `desconocido` (cliente por defecto de `web/metrics.py:365`, `LABELS.client`, afirmada
   en `test_metrics.py` y `test_dashboard_ui.py`): si se traduce, van servidor, JS y tests a la vez
   (A9a, pendiente 10).
7. Las claves de huella `modelo`/`tamano_bytes`/`ruta` de `matrix.py`, `footprint.py` y
   `checks.py:1534`, que lee `test_footprint.py` (A8a, respuesta 8; A9b, pendiente 4).
8. `pruebas`: la clave de las filas en ventana de prueba que lee `test_valuation.py`; es del
    producto.

**Hechos en A9c-5** (eran restos de renombrados de A9): `kwargs.get("ultimo")` → `"last"` en
`test_fallback.py:658` y `reads = {"durante": 0}` → `"during"` en `test_residency.py:858-881`; ver las
desviaciones 3 a 5 de A9c-5, con el barrido del mismo patrón en todo `tests/`.

**Intermitentes abiertos**
9. `test_fake_llamaswap.py::test_a_ttl_counts_from_request_end` y
   `::test_d_8_s_request_in_progress_on_reload[cambio_ajeno]` (vistos en A9b-1): **volvió a fallar
   una vez** el primero, en la última corrida completa de A9c-5 (`pytest-full-final.log`:
   `assert r["during"] == {1.0: True, …}` → `{1.0: False, …}`, la carga a 1 s todavía no se veía);
   suelto, con `test_fallback.py` y `test_residency.py`, pasa (112 passed). Es tiempo, no el
   renombrado de la clave: el valor es el mismo con otro nombre.
10. `test_residency_cli.py::test_restoring_a_copy_end_to_end` (visto en A9a): **no volvió a fallar en
    A9c**.
11. **Nuevo en A9c-5:** `test_dashboard_ui.py`, un test `[cargadas]` distinto en cada corrida completa,
    con `Page.goto` agotando sus 30 s (las 4 corridas completas del lote 5, también la que excluye
    los ficheros del lote, y la corrida final). Suelto y con el módulo solo, pasa. Carga de la
    máquina en la corrida final (`evidence/A9c-5/load-final.txt`): CPU al 33 % antes y al 26 %
    después, 15,6 GB libres de 31,1, PyCharm con 3,4 GB y **Chrome abierto con 24-29 procesos**:
    `pesado.sh` serializa los comandos pesados de los agentes, no el navegador del usuario. Parece la
    carga sobre el primer `goto` del grupo `dashboard_ui`; A9a ya vio uno parecido (`[ancha]`).
