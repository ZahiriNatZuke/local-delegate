# Result review: Codex: guard de escritura y lecturas, huecos de la revisión (#706, #707)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B (2026-11-23, sobre el diff de #712 y el código de `main` 0696df14)
- Security reviewer: yes (personal-security-reviewer sobre el diff, 2026-11-23)
- Verdict: conforms-with-notes (A: conforms-with-notes; B: conforms-with-notes; sin bloqueantes)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | test de CPU |
| REQ-002 | yes | yes | 8 combinaciones de interruptor y lectura |
| REQ-003 | yes | yes | límite: de `cat a b` solo cuenta el primero |
| REQ-004 | yes | yes | clasificador compartido; fila 338 del corpus ajustada |
| REQ-005 | yes | yes | tres separadores y control al 79 % |
| REQ-006 | yes | yes | hilo `daemon` con `join` |
| REQ-007 | yes | yes | wiki y test |
| REQ-008 | yes | yes | 31/29 días y fallo al borrar |
| REQ-009 | yes | yes | — |
| REQ-010 | yes | yes | hallazgos S1-S3 de abajo |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| S1 | Una lectura cuya salida acaba en un fichero (tubería con `> out` o `Out-File`) levantaba el guard en la rama nueva | seguridad | — | confirmed | arreglado: marca `to_file` del clasificador, que el guard de Codex excluye; test |
| S2 | Una cabecera de parche con espacios delante esquivaba `_PATCH_PATH` | seguridad | — | suspected | arreglado: `^[ \t]*`; test |
| S3 | `_TOKEN` del clasificador tardaba tiempo cuadrático con muchos `\"` sin cerrar (medido: 20 000, 31 s de CPU) | seguridad | — | confirmed | arreglado: `\"` y `\'` fuera de comillas son parte de la palabra; test de CPU y de la escritura detrás |
| J1 | REQ-008 promete conservar enlaces y el fichero de la sesión actual, sin test | menor | menor (H) | confirmed | aceptado; evidencia para el análisis de causa común |
| J2 | `sed -e '1,40p' f` da 0 operandos y la lectura pasa con nota en vez de denegarse (falla en abierto) | — | menor (H5) | suspected | aceptado; queda anotado |
| J3 | `>&2` marca la lectura como `to_file` aunque la salida entra al contexto (falla en cerrado, caso raro) | — | menor (H6) | suspected | aceptado; queda anotado |
| J4 | `test_a_read_whose_output_goes_to_a_file_is_marked` pasa con `reads` vacío | — | menor (H7) | suspected | aceptado; mejora de test pendiente |
| J5 | La wiki no matiza que de `cat a b` solo cuenta el primero | — | menor (H8) | suspected | límite aceptado en la spec |
| J6 | `_TOKEN` y `-Skip` tocan el clasificador de Claude Code sin prueba en vivo | menor | — | suspected | pendiente de la prueba con Codex real (`codex-read-summary-write-guard`) |

## Required follow-up

- Revisión de resultado con dos jueces: hecha el 2026-11-23, sin bloqueantes.
- La prueba con Codex real sigue pendiente del SDD `codex-read-summary-write-guard`.
