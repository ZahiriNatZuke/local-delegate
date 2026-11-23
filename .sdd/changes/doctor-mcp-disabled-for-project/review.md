# Result review: doctor avisa si el MCP local-delegate está deshabilitado para el proyecto en Claude Code (#705)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B (2026-11-23, sobre el diff de #711 y el código de `main` 0696df14)
- Security reviewer: no — solo lee dos listas de `~/.claude.json`; no escribe
- Verdict: conforms-with-notes (A: conforms; B: conforms-with-notes; sin bloqueantes)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | WARN con remedio `/mcp`, `checks.py:1243-1254`, las dos listas |
| REQ-002 | yes | yes | OK si lo deshabilita otro proyecto o faltan claves |
| REQ-003 | yes | yes | ancestro más cercano manda; normalización solo en Windows |
| REQ-004 | yes | yes | fichero igual byte a byte; `REPAIRS` no actúa sobre WARN |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| J1 | `update` (`_infer_mcp_mode`, `_daemon_applies`) solo cuenta la entrada de Claude como HTTP si está en OK; con el WARN nuevo puede perder esa señal | — | menor (H4) | suspected | queda anotado para el siguiente arreglo de `update` |
| J2 | Con `Context.cwd` relativo, `cwd.parents` no sube más allá de la raíz relativa | menor | — | suspected | sin efecto: la CLI usa `Path.cwd()` |

## Required follow-up

- Nada bloquea el cierre. J1 queda como mejora de `update`.
