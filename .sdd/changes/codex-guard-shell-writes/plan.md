# Implementation plan: Guard de Codex: escrituras de shell sobre ficheros resumidos

## Approach

Todo en `src/local_delegate/codex_reads.py`, encima del analizador de `read_classifier` que ya
usa `write_targets`: (1) un mapa de variables con valor literal sacado de los tokens de la orden;
(2) sustitución de `$var` en las rutas de las escrituras y lecturas que da `accesses`; (3) un
escáner lineal (bucle por caracteres, sin regex) de las llamadas `[IO.File]::Método(` con sus
argumentos por profundidad de paréntesis y comillas; (4) verbos de escritura de PowerShell que el
clasificador no ve (`New-Item`, `Clear-Content`, `Tee-Object`) recorriendo los mismos `segments`;
(5) desenvolver `cmd /c`, `bash -c`, `powershell -Command` y analizar la orden de dentro. Lo que no
se puede resolver da `None` y no cuenta: pasa. No se toca `read_classifier` para no cambiar los
hooks de Claude Code.

## Ordered tasks

- [x] T1 — Tests rojos: cada forma, las tres shells, controles, tiempo lineal (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006)
  - Files or modules: tests/test_codex_guard_shell_writes.py
  - Verification: pytest de ese fichero falla antes del cambio
  - Depends on: none
- [x] T2 — Implementación en codex_reads (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006)
  - Files or modules: src/local_delegate/codex_reads.py
  - Verification: tests/test_codex_guard_shell_writes.py y tests/test_codex_reads.py
  - Depends on: T1
- [x] T3 — Prueba del proceso del hook con el JSON real (REQ-007)
  - Files or modules: .sdd/changes/codex-guard-shell-writes/evidence/
  - Verification: denegación impresa por el hook alimentado por stdin
  - Depends on: T2
- [x] T4 — Docs y CHANGELOG (REQ-008)
  - Files or modules: src/local_delegate/codex_reads.py (docstring), docs/wiki, CHANGELOG.md
  - Verification: revisión del diff
  - Depends on: T2

## Test strategy

- Unit: `codex_reads.decide` con el mundo de `tests/test_codex_reads.py` (mismas fixtures), cada
  forma con su control sin guard (pasa) y con guard (se rechaza).
- Integration: suite completa con `pesado.sh python -m pytest -q -n 2`.
- End-to-end or manual: el hook por stdin con el JSON de la fixture real y la orden de #724.
- Security and secret scanning: `personal-security-check` antes del commit.

## Migration and compatibility

- Solo amplía lo que se rechaza en Codex; el clasificador compartido no cambia. Sin migración.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
