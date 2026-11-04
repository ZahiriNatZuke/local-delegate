# Implementation plan: Hooks de la entrega por settings leen y escriben UTF-8 en Windows

## Approach

Una función nueva `utf8_stdio()` en `hook_common.py` (junto a `run_with_environ`, lejos de
`record`/`_log_failure`) reconfigura `sys.stdin` y `sys.stdout` a UTF-8 con `errors="replace"`,
igual que `hook_entry._utf8_streams`. Cada hook la llama lo primero en su `main()`, antes de leer
stdin. No se llama al importar porque el servidor importa `hook_common` y su stdio es el
transporte MCP. Se descarta registrar con `python -X utf8`: el arreglo en el script basta para las
instalaciones nuevas y las existentes (tras `update`), y cambiar el comando obligaría a migrar
entradas y a enseñar a `doctor` las dos formas, con riesgo de duplicados.

## Ordered tasks

- [x] T1 — Repro instalada antes del arreglo (REQ-007)
  - Files or modules: scratchpad/utf8hooks/installed_probe.py
  - Verification: before.txt muestra los tres fallos
  - Depends on: none
- [x] T2 — `utf8_stdio()` en `hook_common.py` y llamada al inicio de `main()` en `suggest_delegate_read.py`, `suggest_delegate_shell.py`, `suggest_delegate_prompt.py` y `subagent_start.py` (REQ-001, REQ-002, REQ-003, REQ-004, REQ-006, REQ-008)
  - Files or modules: src/local_delegate/resources/hooks/
  - Verification: tests nuevos + prueba instalada
  - Depends on: T1
- [x] T3 — `reason: "no_file"` en las dos salidas tempranas del hook de lectura (REQ-005)
  - Files or modules: src/local_delegate/resources/hooks/suggest_delegate_read.py
  - Verification: test del fichero que no existe
  - Depends on: T2
- [x] T4 — Tests nuevos `tests/test_hook_stdin_utf8.py` con control positivo (REQ-001, REQ-002, REQ-003, REQ-005, REQ-006)
  - Files or modules: tests/test_hook_stdin_utf8.py
  - Verification: fallan con el arreglo revertido, por el assert que dicen
  - Depends on: T2, T3
- [x] T5 — Suite completa, ruff, CHANGELOG y prueba instalada después (REQ-004, REQ-007, REQ-008)
  - Files or modules: CHANGELOG.md
  - Verification: pytest -n 2, ruff, after.txt
  - Depends on: T4
- [x] T6 — Ajustes de la revisión: `no_file` fuera de `reads` en `measure_adoption.py` y tests de shell y subagente que discriminen (REQ-009, REQ-010)
  - Files or modules: scripts/measure_adoption.py, tests/test_measure_adoption.py, tests/test_hook_stdin_utf8.py
  - Verification: control positivo de los tres tests; comparación vieja/nueva sobre una copia fija del log real
  - Depends on: T5

## Test strategy

- Unit: `utf8_stdio` sobre un `TextIOWrapper` cp1252 y sobre un `StringIO`.
- Integration: los scripts lanzados por ruta con `PYTHONIOENCODING=cp1252` y stdin en bytes UTF-8
  (discrimina también en el CI de Linux).
- End-to-end or manual: `install --claude-delivery settings` en HOME temporal y el comando del
  settings lanzado por `sh -c`, como Claude Code.
- Security and secret scanning: sin secretos; la telemetría sigue sin rutas.

## Migration and compatibility

- `settings.json` no cambia; `update` recopia los scripts y con eso basta.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
