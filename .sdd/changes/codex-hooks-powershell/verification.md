# Verification: Codex en Windows: hooks que arrancan en PowerShell, cmd y bash (#718)

## Environment

- Revision: rama `fix/codex-hooks-powershell` desde `3bba8117` (v0.54.0)
- Relevant runtime and tool versions: Windows 11, Python 3.11.15, pwsh 7, Windows PowerShell 5.1, Git Bash, Codex CLI 0.171.0

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test_codex_hooks_shells.py::test_the_line_starts_in_every_shell (pwsh, powershell, cmd, bash) y `codex exec` real con `CODEX_HOME` temporal | pass | rojo en main (pwsh y powershell no arrancan); verde tras el cambio; `codex-hooks-seen.json` con `codex-prompt` 2026-11-23T19:12:51Z (UTC) con la línea nueva y sin actualizar con la vieja |
| REQ-002 | test_a_path_with_spaces_starts (8.3 real en C:) y test_without_a_short_name_the_call_operator_starts_in_powershell | pass | las cuatro shells arrancan con el nombre 8.3; `& '…'` arranca en pwsh y powershell |
| REQ-003 | test_every_form_of_ours_is_recognized y tests de install existentes | pass | forma vieja, desnuda, 8.3 y `& '…'`/`& "…"` reconocidas |
| REQ-004 | test_a_quoted_line_is_a_warn_that_names_powershell y su control | pass | `warn` con `doctor.probe.codex_hooks.quoted` y pista `local-delegate update` |
| REQ-005 | test_outside_windows_no_short_name_is_asked y parametrizados linux/darwin | pass | `shlex.quote` sin cambios |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest -q -n 2 (con pesado.sh, PYTHONPATH=src) | sí | pass | 8669 passed, 1 failed (detector de nombres: `slashed`, `powershells`, `pip`), arreglado; repasados los ficheros tocados y el detector: 146 passed |
| ruff check src tests; ruff format --check src tests | sí | pass | sin hallazgos |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- La prueba real con Codex llegó hasta el despacho de `codex-prompt` (marcador escrito con la línea nueva, no con la vieja). La fila del log de uso con `caller_src` y el resumen de un `cat` grande necesitan que el modelo responda, y eso pide la credencial de Codex (`auth.json`) y la del MCP en el `CODEX_HOME` temporal: no se copian credenciales sin permiso del usuario. Queda la orden exacta en el informe.
- Sin 8.3 en la unidad, la forma `& '…'` solo arranca en PowerShell (shell por defecto de Codex en Windows).
- `tool_timeout_sec`: el plazo por defecto de Codex es 300 s (0.169.1 y 0.171.0); la cancelación a los 154 s fue una notificación de cancelación de code mode, no el plazo.
