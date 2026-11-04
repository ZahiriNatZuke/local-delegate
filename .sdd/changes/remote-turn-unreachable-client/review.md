# Result review: Turno remoto inalcanzable: en serie, corte y aviso (#577)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-1 (subagente autor, revisión contra spec y control positivo con mutantes), result-reviewer-2 (revisión independiente antes de mezclar y CI del PR)
- Security reviewer: no — sin superficie nueva expuesta: cambia la cola y el corte del cliente; el fichero `remote-turn-cut.json` solo guarda `host[:puerto]`, contadores y fechas
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | test con mutante «sin serie» | la serie es por proceso, no por máquina |
| REQ-002 | sí | test con mutantes del corte | tras la revisión solo cuenta `read_timeout`; un 5xx al momento no abre el corte |
| REQ-003 | sí | test + prueba en vivo con sockets reales | 1 llamada al backend de 4; las otras 3 con `RemoteTurnDown` |
| REQ-004 | sí | test con mutante «sin nota» | `error` y `error_class` sin cambios |
| REQ-005 | sí | test con mutante | tras la revisión, una espera con `429` no se corta por otra |
| REQ-006 | sí | test con mutante «sin evento propio» | |
| REQ-007 | sí | suite completa (6400 passed, 30 skipped) + 22 checks del PR | los 2 rojos de la primera corrida explicados en `verification.md` |
| REQ-008 | sí | tests de la revisión con 5 mutantes | añadido por la revisión independiente (punto 2) |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | El corte se abría también con un 5xx al momento (`capacity_or_load`), no solo con un plazo agotado | confirmed | confirmed (revisión independiente) | confirmed | Arreglado en `58afc614`: solo cuenta `error: "read_timeout"` |
| F2 | El sitio a ciegas no iba en orden de llegada ni lo soltaba una operación troceada; una espera sin avance no tenía tope | confirmed | confirmed (revisión independiente) | confirmed | Arreglado en `58afc614`: fila por llegada, suelta entre trozos, `QueueSaturated` tras `LOCAL_DELEGATE_QUEUE_MAX_WAIT_S` (REQ-008) |
| F3 | Una espera de turno con `429` (daemon vivo) se cortaba por el veredicto de otra operación | confirmed | confirmed (revisión independiente) | confirmed | Arreglado en `58afc614`: solo una respuesta perdida mira ese veredicto |
| F4 | La documentación no decía que la serie es por proceso | confirmed | confirmed (revisión independiente) | confirmed | Arreglado en `58afc614` |
| F5 | CodeQL `py/catch-base-exception` (nivel note) en `tests/test_remote_turn_unreachable.py:198` y `:473`: alertas 202 y 203 abiertas en `main` y sus dos hilos del PR sin resolver | confirmed | no consta | suspected | Pendiente, fuera del alcance de este cierre (solo toca `.sdd/`): queda para la sesión principal |

## Required follow-up

- Revisión independiente antes de mezclar: consta en el commit `58afc614` («address the review of the blind place and the cut»), con cuatro ajustes aplicados en la rama (F1–F4) y en `spec.md` (REQ-002 y REQ-008 citan «revisión del #579»). El texto de la revisión y su veredicto literal no constan en el PR (sin comentarios humanos ni reviews salvo los de CodeQL).
- Arreglar las alertas de CodeQL 202 y 203 (capturar `Exception` o justificar) y resolver sus hilos en el PR #579 (F5).
- Mezclado en `main` como `576344b5` (PR #579), 22 checks del PR en verde (macOS incluido) y CI de `main` en verde.
