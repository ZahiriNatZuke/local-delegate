# Result review: local_commit_msg: repo language from the commit history, not the reflog (#548)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-1, result-reviewer-2 (revisión en la rama), independent-reviewer (revisión independiente antes de mezclar)
- Security reviewer: yes — el lector parsea objetos del almacén no confiables; la revisión independiente probó entradas hostiles (cadena de deltas, bomba zip, refs raras) y los topes
- Verdict: conforms-with-notes (revisión independiente: «mezclar con cambios»; los 5 puntos se corrigieron y la alerta de CodeQL se arregló)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | worktree anidado, diff en raíz y subcarpeta: `("en", "repo")` |
| REQ-002 | yes | yes | objetos sueltos, packs v2 y deltas ofs/ref |
| REQ-003 | yes | yes | almacén ilegible o historial corto: el reflog rellena como antes |
| REQ-004 | yes | yes | topes, sin subprocesos, refs validadas, solo ficheros regulares |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F0 | (jueces de la rama) merges, relleno desde el reflog, tope de `packed-refs`, fichero regular | found | found | confirmed | fixed antes de la revisión independiente |
| F1 | Un pack con una cadena compartida de deltas de un byte bajo merges sin cuerpo tardaba 13,5 s por 3 commits (~15 min por `MAX_WALK`) | — | found | suspected | fixed: presupuesto por llamada (32 MiB inflados y de delta, 1,5 s); al agotarse se conserva lo leído y el reflog rellena |
| F2 | Las bases de delta se resolvían una y otra vez | — | found | suspected | fixed: caché de bases resueltas por llamada |
| F3 | `packed-refs` sin un tope único sobre lo leído | — | found | suspected | fixed: un solo tope sobre los bytes leídos, con su test |
| F4 | Sin test para un directorio en lugar de un objeto suelto | — | found | suspected | fixed: test añadido |
| F5 | Un asunto presente en el historial y en el reflog votaba dos veces | — | found | suspected | fixed: vota una vez, con test |
| F6 | CodeQL: `except` vacío en `git_history` | — | CodeQL | confirmed | fixed: comentario que explica que un error de lectura termina el recorrido conservando lo leído |

## Required follow-up

- Ninguno: mezclado en `main` (`5b305b5d`, PR #562, cierra #548) con los 22 checks del PR en verde y el CI de `main` en verde.
