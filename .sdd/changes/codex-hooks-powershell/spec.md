# Specification: Codex en Windows: hooks que arrancan en PowerShell, cmd y bash (#718)

## Summary

Codex lanza cada hook `command` con la shell de la sesión (`build_hooks_config` →
`Shell::derive_exec_args`: `pwsh -NoProfile -Command <línea>`, `cmd.exe /c <línea>` o
`bash -c <línea>`). En Windows la shell por defecto es PowerShell, y nuestra línea empezaba por la
ruta del intérprete entre comillas: PowerShell la toma como una cadena literal y da `ParserError`,
así que ninguno de los cuatro hooks llegaba a arrancar. Tras el cambio, la línea que escribe
`install` arranca el intérprete en las tres shells cuando la ruta lo permite, y en PowerShell
siempre; `doctor` avisa de una línea nuestra con la forma vieja.

Plazo de las tools MCP en Codex (`tool_timeout_sec`): por defecto **300 s** en 0.169.1 y 0.171.0
(`codex-rs/codex-mcp/src/rmcp_client.rs`, `DEFAULT_TOOL_TIMEOUT`). La `local_extract` cancelada a
los 154 s de la prueba del 2026-11-23 trae `cancel_reason: notification` y un `tool_use_id`
`exec-…`: la canceló Codex al cerrar una celda de code mode, no el plazo. No hace falta escribir
un plazo; `install` sigue sin escribirlo.

## Requirements

- **REQ-001** — En `win32`, si la ruta del intérprete (con `/`) solo lleva letras, cifras, `_`,
  `.`, `-`, `~` y `/` tras la unidad, la línea empieza por esa ruta sin comillas, y arranca el
  intérprete bajo `pwsh -NoProfile -Command`, `powershell -NoProfile -Command`, `cmd /c` y `bash -c`.
  - Request: "en `win32`, ruta del intérprete **sin comillas** cuando no lleva espacios ni metacaracteres (vale para cmd, PowerShell y bash)"
  - Verify: test tests/test_codex_hooks_shells.py
- **REQ-002** — Si la ruta lleva espacios u otros caracteres, se usa su ruta corta 8.3
  (`GetShortPathNameW`) cuando esta sí cumple REQ-001; si no la hay, la línea es
  `& '<ruta>' -I -m local_delegate.hook <nombre>` (operador de llamada de PowerShell, la shell por
  defecto de Codex en Windows; comillas simples para que un `$` no se expanda, dobles si la ruta
  lleva `'`), que arranca bajo `pwsh` y `powershell`.
  - Request: "si los lleva, usar la ruta corta 8.3 (`GetShortPathNameW`) o, si no hay, elegir la forma según la shell de Codex (`& \"…\"` para PowerShell)"
  - Verify: test tests/test_codex_hooks_shells.py
- **REQ-003** — `our_name` y `python_of` reconocen las tres formas nuevas y la vieja entre
  comillas: `install` reemplaza la línea vieja en su sitio, sin duplicar grupos.
  - Request: "`_OURS` ya acepta el intérprete sin comillas."
  - Verify: test tests/test_codex_hooks.py
- **REQ-004** — `doctor` da `warn` cuando un hook nuestro de `hooks.json` empieza por comilla, y lo
  explica (PowerShell no lo arranca) con la pista de `local-delegate update` y de volver a
  aprobarlos en `/hooks`.
  - Request: "`doctor`: avisar cuando un hook nuestro empieza por comilla y la shell de Codex es PowerShell."
  - Verify: test tests/test_codex_hooks_doctor.py
- **REQ-005** — Fuera de `win32` la línea no cambia (`shlex.quote`).
  - Request: derived: no romper Linux ni macOS, donde la forma actual funciona.
  - Verify: test tests/test_codex_hooks.py

## Acceptance scenarios

### Scenario: PowerShell arranca el hook

- **Given** una instalación en Windows con el intérprete en una ruta sin espacios
- **When** Codex lanza el hook con `pwsh -NoProfile -Command <línea>`
- **Then** el intérprete arranca y el hook escribe su marcador

### Scenario: ruta con espacios

- **Given** el intérprete en una carpeta con espacios
- **When** se genera la línea
- **Then** lleva la ruta 8.3 sin comillas si existe, y si no `& '<ruta>'`, y arranca bajo PowerShell

### Scenario: actualización desde la forma vieja

- **Given** un `hooks.json` con nuestras líneas entre comillas
- **When** se corre `doctor` y luego `install`
- **Then** `doctor` avisa y `install` las reescribe en su sitio con la forma nueva

## Edge cases and failure behavior

- Sin 8.3 en la unidad (habitual en volúmenes que no son el del sistema): forma `& '…'`, válida
  solo en PowerShell; es la shell por defecto de Codex en Windows.
- `GetShortPathNameW` falla o no existe (no es Windows de verdad): se toma como «sin ruta corta».
- El cambio de línea cambia el hash de confianza de Codex: hay que aprobar otra vez en `/hooks`
  (el texto de `install.codex_hooks.written` ya lo dice).

## Non-functional requirements

- Sin dependencias nuevas; `ctypes` solo en Windows.
- No se ejecuta `codex` ni se toca `~/.codex` real en los tests.

## Non-goals

- Escribir `tool_timeout_sec` (ver Summary: el plazo por defecto ya es 300 s).
- Detectar la shell real de la sesión de Codex.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
