# Result review: Codex: guard de escritura y lecturas, huecos de la revisión (#706, #707)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: TBD
- Security reviewer: yes (personal-security-reviewer sobre el diff, 2026-11-23)
- Verdict: TBD

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

## Required follow-up

- Revisión de resultado con dos jueces antes de aprobar `conformance`.
- La prueba con Codex real sigue pendiente del SDD `codex-read-summary-write-guard`.
