# Ola A9c — Tests `q*`–`z*`

La subola se parte en 5 lotes (D13: 1269 filas, como mucho 300 por lote y sin partir un módulo),
aprobados por la sesión principal el 2026-10-13 con las 9 decisiones de la fase 1 tal como se
recomendaron. Cada lote es un commit que hace la sesión principal, en una rama apilada sobre el
anterior. Las tablas de controles positivos, `local_*` y PyCharm son las de todos los lotes, porque
`check_wave_records.py` lee la primera tabla de cada sección. Por ahora cubren los **lotes 1 y 2**: 31 + 17 = 48
filas `rename_refactoring` = 48 filas `pycharm` de `waves/A9c-1-mapping.csv` y
`waves/A9c-2-mapping.csv` (tras su línea `# Fase 2`).

- Rama: lote 1 en `sdd/english-names-a9c-1`, sacada de `main` (`2888d90`, con A9a y A9b mezcladas).
  Commit del lote 1: `d1d002b` (PR #285). Lote 2 en `sdd/english-names-a9c-2`, encima de `d1d002b`;
  commit pendiente, con el borrador en `waves/A9c-2-commit-msg.txt` (firmado y sin coautoría).
- Quién: un agente hizo los 5 mappings (fase 1) y aplica los lotes tras la aprobación (fase 2).
- Conteo base: `evidence/A9c/collect-before.txt`, 2572 tests.

## Controles positivos

| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_transcripts.py::test_known_n_and_expiries` y `::test_the_ttl_depends_on_the_thread` (lote 1; usan `subagent`, `main_transcript`, `request_entry`, `result_entry`, `write_jsonl`, `KNOWN_N` y la variable renombrada `expiries`) | `src/local_delegate/transcripts.py:242`: `return len(later), caducidades` → `caducidades + 1` (sha256 `fb2e49f6…` → `afe60b28…`) | `assert expiries == 1` → `assert 2 == 1`, y `assert expiries == 0` → `assert 1 == 0` | sí, desde copia; sha256 igual al de antes (`evidence/A9c-1/mutant.txt`) |
| `tests/test_structured_summary.py::test_detects_the_sections_of_the_bench_documents` (lote 2; usa `SOURCES` y los argnames renombrados `name`/`count`, 5 casos) | `src/local_delegate/sections.py:130`: `detect` devuelve los títulos sin el primero (`at_level` → `at_level[1:]`; sha256 `cda2bd16…` → `5aed003d…`) | `assert len(structure.headings) == count` → `assert 10 == 11` (y `8 == 9`…) | sí, desde copia; sha256 igual al de antes (`evidence/A9c-2/mutant.txt`) |

## Llamadas `local_*` (sesión principal y cada agente)

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente A9c (fase 1) | (ninguna) | los mappings necesitaban nombres y líneas literales; las secciones de `A9a.md`/`A9b.md` se leyeron acotadas |
| Agente A9c-1 | `local_lint_summary(path=evidence/A9c-1/pytest-full.log)` | resumen de la corrida de la suite: verde, solo los 12 `DeprecationWarning` de siempre de `starlette.testclient` |
| Agente A9c-2 | `local_lint_summary(path=evidence/A9c-2/pytest-full.log)` | resumen de la suite: verde, solo los 12 `DeprecationWarning` de `starlette.testclient` |

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

## Pendientes

**Fuera de A9c (decisión 9 de la fase 1)**
1. `src/local_delegate/server.py:1101` y `:2308` siguen escribiendo y leyendo las claves
   `respaldo`/`respondio`/`en_lugar_de` de `_local_delegate`, y `test_fallback.py` las lee. Son del
   producto: van al cierre del frente A, no a A9c.
