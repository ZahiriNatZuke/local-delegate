# Result review: Hooks, mod y caché: lecturas sin MCP, prefiltro multilínea y fallo pasajero

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: no — el codigo nuevo solo lee el transcript que da Claude Code, valida `agent_id` antes de construir la ruta, no registra nada de su contenido y ante cualquier fallo vuelve al comportamiento de antes (el juez B, centrado en seguridad, no encontro via de ataque)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | si | si | `hook_common.local_tools_absent`; hooks de Read (imagen, prosa, codigo en subagente) y de shell |
| REQ-002 | si | si | ante la duda, False; tras la revision tambien con deltas de solo built-ins y rutas que no son fichero |
| REQ-003 | si | si | `READ_CHAINING` con salto de linea, comilla invertida y `(`; tests TS y Python |
| REQ-004 | si | si | fallo simulado y cerrojo real `CreateFileW` |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Un delta con solo built-ins diferidas (MCP cargadas de entrada) daria «ausente» | si | no | suspected | Arreglado: la ausencia exige tambien algun `mcp__` en el conjunto neto; test y mutante comprobado |
| F2 | La ruta principal no pasa por `is_file()` (una FIFO colgaria `read_bytes`) | no | si | suspected | Arreglado: `is_file()` antes de `stat`; test con una carpeta |
| F3 | Se relee el transcript entero (hasta 32 MiB) en cada lectura grande | si | si | confirmed | Aceptado dentro del tope de la spec; cache por (ruta, mtime, tamano) como seguimiento |
| F4 | `mcp_absent` va antes de `protected_path` | no | si | suspected | Aceptado: solo cambia el motivo registrado y solo con el MCP ausente |
| F5 | `READ_CHAINING` no incluye `<` | no | si | suspected | Aceptado: preexistente; `echo < x` no vuelca el fichero |

## Required follow-up

- La release corre `bump_version.py --boundaries` (cambian las huellas de los hooks).
- Opcional: cachear el veredicto del transcript por (ruta, mtime, tamano).
