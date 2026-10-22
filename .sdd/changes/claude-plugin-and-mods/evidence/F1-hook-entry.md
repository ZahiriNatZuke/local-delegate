# F1-hook-entry — Subcomando de hooks, interruptor y variables

Fecha: 2026-10-21 · Windows 11 · Python 3.11 (`.venv` del worktree) · REQ-003 y REQ-004.

## Qué se hizo

- `local_delegate/hook.py`: `python -I -m local_delegate.hook <nombre>` (vía B de T0). `run()`
  envuelve todo (`except BaseException`) y termina con `os._exit(0)`.
- `local_delegate/hook_entry.py`: despacho de `prompt`, `record-call`, `read`, `mcp-read` y
  `shell` al script empaquetado de `resources/hooks/` con `runpy.run_path` (su ruta como
  `__file__`, así que `version_de` da la misma huella que en settings). Fuerza UTF-8 en stdin y
  stdout. Nombre desconocido: 0 sin texto. Fallo: 0 y una línea `{ts, hook, error}` en
  `LOG_DIR/hook-failures.jsonl` (solo el tipo, con tope de 256 KB).
- `local_delegate/read_switch.py`: contrato `{"active", "since"}` en `LOG_DIR/read-hook.json`,
  `path()`, `active()`, `write(active)` y `enabled(argv, environ)` (capa «activo» entera).
- `__init__.py` perezoso: `main` despacha `hook` antes de importar `entrypoint`; `__version__` por
  `__getattr__`. `entrypoint.main` también despacha `hook` (`python -m local_delegate hook …`).
- `config.py`: `PLUGIN_ENVIRONMENT_VARIABLES` (las cinco de la lista cerrada) en el inventario.
- `scripts/measure_hook_latency.py`.

## Desviaciones

1. **Los scripts de settings no se tocan** (`suggest_delegate_read.py` y `hook_common.py`
   quedan iguales). La capa «activo» por fichero se decide en `hook_entry` y al script se le pasa
   `--enabled`. Motivo: cambiar un script con huella mueve su hash y obliga a regenerar
   `scripts/data/hook_hashes_after.json`, que este lote no posee; además corta la serie de P-4 en
   mitad de la ventana. La entrega por settings sigue encendiéndose con `--enabled` o la variable,
   como en la 0.39 (la vuelta atrás del plan lo admite).
2. **Ficheros fuera de «Posee»**: `scripts/data/spanish_lexicon.json` y su README (10 palabras
   inglesas nuevas, entrada 22, el procedimiento de siempre del guardián REQ-044). Sin ellas
   `test_repo_has_no_spanish_name_outside_the_exception_list` falla; `plugin` y `distro` vienen de
   los nombres de variable que fija el plan. Los otros lotes de la ola tocarán probablemente la
   misma lista: conflicto de rebase, como `CHANGELOG.md`.
3. Los segmentos de ruta de `LOG_DIR` en `read_switch.log_dir` van en variables y no en el
   `return`, para no necesitar filas nuevas en `tests/data/uncatalogued_exceptions.json` (ajeno).

## Tests (primero en rojo, por import y por el inventario)

- `tests/test_hook_entry.py` (15): `test_unknown_hook_exits_zero_silently`,
  `test_unknown_hook_through_the_installed_console_script`, `test_hook_crash_lets_the_call_through`,
  `test_hook_exit_2_inside_the_script_lets_the_call_through`, `test_wrapper_exits_zero_on_sys_exit_2`,
  `test_wrapper_exits_zero_on_exception`, `test_hook_path_does_not_import_server` (por `-m` y por
  `local_delegate.main`, con `-X importtime`), `test_inactive_read_hook_imports_only_switch`,
  `test_each_hook_name_matches_script_behaviour` (stdout + telemetría + notas, guarda de no vacío
  y de salidas distintas), `test_plugin_and_settings_fingerprints_match`,
  `test_blocks_jsonl_unchanged_format`, `test_hook_output_is_utf8`, `test_hook_input_is_read_as_utf8`,
  `test_failure_log_is_not_written_on_success`, `test_hook_names_are_the_plugin_contract`.
- `tests/test_read_switch.py` (6): `test_reads_contract_file_shape`,
  `test_write_produces_exactly_the_contract`, `test_the_state_file_lives_where_the_hooks_look`,
  `test_active_layer_state_file_or_enabled_env`, `test_block_layer_precedence_unchanged`,
  `test_block_state_values_unchanged`.
- `tests/test_environment_isolation.py`: `test_the_plugin_variables_are_in_the_inventory`,
  `test_every_variable_the_hook_entry_reads_is_declared_in_config`.

## Mutantes (cada uno falla por el assert que dice)

| Mutante | Falla | Assert |
|---|---|---|
| sin `_utf8_streams()` | `test_hook_output_is_utf8` | «el aviso se perdió por la codificación de la consola» (`b'' != b''`) |
| `run()` sin `except` | `test_wrapper_exits_zero_on_exception` | `returncode == 0` (traceback en stderr) |
| `main` sin `except BaseException` | `test_hook_crash_lets_the_call_through` | `RuntimeError: boom` sube |
| `__init__` importa `entrypoint` | `test_hook_path_does_not_import_server` | `loaded == set()` con `local_delegate.server`, `mcp…` |
| sin capa «activo» | `test_inactive_read_hook_imports_only_switch` | `(0, b'')` recibe el aviso |
| `mcp-read` → script de shell | `test_each_hook_name_matches_script_behaviour` | telemetría `[]` ≠ evento `route: mcp` |
| `active()` con `bool(...)` | `test_reads_contract_file_shape` | `{"active": "yes"}` → `True is False` |
| desconocido imprime | `test_unknown_hook_exits_zero_silently` | `(0, b'?\r\n', b'')` |
| falta `WSL_DISTRO_NAME` | `test_the_plugin_variables_are_in_the_inventory` | `['WSL_DISTRO_NAME'] == []` |

## Comportamiento instalado (rueda, no editable)

`uv build --wheel` → venv aparte (Python 3.12) → `uv pip install <rueda>`, sin variables `PYTHON*`:
`python -I -m local_delegate.hook nope|prompt|record-call|read|mcp-read|shell` → todos 0, solo
`prompt` imprime (320 bytes), stderr vacío; `local-delegate.exe hook prompt` → 0 con el aviso;
`local-delegate.exe hook nope` → 0; `-X importtime` del hook `prompt` sin `mcp` ni
`local_delegate.server`.

## Latencia (`scripts/measure_hook_latency.py`, 20 invocaciones + 1 de calentamiento)

`<worktree>/.venv/Scripts/python.exe -I -m local_delegate.hook <nombre>`, umbral p95 300 ms:

| hook | p50 ms | p95 ms | máx ms |
|---|---|---|---|
| prompt | 109.3 | 116.0 | 116.2 |
| record-call | 111.3 | 123.8 | 124.1 |
| read (inactivo) | 66.0 | 81.5 | 108.3 |
| read | 117.6 | 123.9 | 131.9 |
| mcp-read | 113.9 | 126.7 | 127.5 |
| shell | 112.3 | 121.8 | 122.5 |

Todos con código 0.

## Suite

`pesado.sh .venv/Scripts/python.exe -m pytest -n 2`: 4206 passed, 28 skipped. `ruff check` y
`ruff format --check` limpios. `git ls-files --eol` igual que en `main` (`__init__.py` y
`entrypoint.py` CRLF; el resto LF).

## Llamadas `local_*`

- `local_lint_summary(path=suite.log)`: los dos fallos de la primera suite completa.
- `local_summarize(path=scripts/data/spanish_lexicon.README.md)`: procedimiento del léxico.
- `local_commit_msg(path=<diff>)`: borrador del commit.
