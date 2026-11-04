# Result review: El daemon sale (y se puede relevar) cuando su listener HTTP muere

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: no — riesgo acotado al pid de `daemon.json`, cubierto por los dos jueces (foco de seguridad en el juez 2)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | test e2e | |
| REQ-002 | sí | test | |
| REQ-003 | sí | test e2e + unitarios | sin relevo en macOS |
| REQ-004 | sí | test | rotación sin test propio |
| REQ-005 | sí | test | mensaje neutro (sin prometer relevo) |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Guarda de pid rompía tests de relevo | — | sí | confirmed | juez 2 vio un estado intermedio; ya corregido (zombi con `started_at` real, `_process_started_at` doblado) |
| F2 | macOS nunca releva y `doctor` lo prometía | sí | sí | confirmed | `skipif` del e2e fuera de Windows/Linux y mensaje sin promesa |
| F3 | Doble `_stop_serving` en selector loops (montaje del test) | — | sí | suspected | el test tolera la segunda parada; CI lo confirmará |
| F4 | SIGKILL sin volver a comprobar el pid | sí | — | suspected | ahora se comprueba la hora de creación antes del SIGKILL |
| F5 | verification.md desfasado | sí | sí | confirmed | actualizado |
| F6 | Errores de asyncio dejan de salir por stderr en primer plano; relevo durante el apagado; posible URL con credenciales en trazas | sí | sí | suspected | aceptado como riesgo residual, anotado |

## Required follow-up

- Ninguno. Revisión independiente antes de mezclar (consta en `verification.md`, «Deviations and residual risk»; no hay comentario de revisión en el PR #578): «mezclar con cambios», con cinco ajustes aplicados en la rama: guarda de pid reutilizado también en `doctor`, reintento de `accept` con espera creciente 0,01 s → 1 s, riesgo de cola de `listen` llena anotado en `_refuses_connections`, excepción a «nunca señal a un pid leído de un fichero» escrita en `update._terminate` y en el CHANGELOG, y código de salida 75 (`EX_TEMPFAIL`) en vez de 3.
- Mezclado en `main` como `d75c09cf` (PR #578) sin macOS: `test (macos-latest)` y `plugin (macos-latest)` quedaron `cancelled` (en el PR solo `plugin (macos-latest)`) y por eso `ci-gate` dio rojo, en el PR y en el CI de `main` de ese commit; el resto de checks en verde. El usuario autorizó expresamente esta mezcla sin macOS el 2026-11-04 (bypass temporal del ruleset `protect-main`, restaurado después; consta en el relevo de la jornada). El CI de `main` está en verde desde `e85c0519` y en `cf1474d8`.
