# Result review: Codex en Windows: hooks que arrancan en PowerShell, cmd y bash (#718)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: no — la ruta sale de la instalación de `uv tool`, no de una entrada ajena; sin comillas solo va un conjunto estricto de caracteres y la forma de reserva es literal
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | cuatro shells reales, con controles en ambos sentidos |
| REQ-002 | sí | sí | 8.3 exigido cuando la unidad lo tiene; `& '…'` con `'` duplicada |
| REQ-003 | sí | sí | forma vieja reescrita en su índice |
| REQ-004 | sí | sí | aviso solo en Windows |
| REQ-005 | sí | sí | `shlex.quote` sin cambios |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Ninguna prueba exige que se use el 8.3 ni que `short_path` responda | sí | sí | confirmed | arreglado: control de `short_path` y aserción en el test de espacios |
| F2 | `& "…"` expandía `$` con una `'` en la ruta | sí | sí | confirmed | arreglado: siempre `& '…'` con `''`; `_OURS` y `python_of` lo leen |
| F3 | Falta la prueba de reescritura de la línea de 0.54.0 en su índice | sí | no | suspected | arreglado: test en test_codex_hooks_install.py |
| F4 | Docstrings desfasados (módulo, `merge`, 8.3 que puede cambiar) | sí | sí | confirmed | arreglado |
| F5 | `argtypes` sobre el `kernel32` compartido; faltaba `ctypes.ArgumentError` | sí | sí | confirmed | arreglado: `WinDLL` privado y excepciones ampliadas |
| F6 | Aviso de doctor sin control fuera de Windows | sí | sí | confirmed | aceptado: el código lo evita con `sys.platform` |
| F7 | `& '…'` no arranca en cmd o bash; apóstrofos tipográficos en la ruta | sí | sí | confirmed | aceptado como límite (non-goal: detectar la shell de la sesión) |

## Required follow-up

- Prueba real completa con Codex (fila con `caller_src` y resumen de un `cat` grande): necesita las credenciales de Codex en el `CODEX_HOME` temporal, que no se copian sin permiso del usuario.
