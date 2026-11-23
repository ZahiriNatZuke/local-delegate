# Result review: local_lint_summary: recuentos por fichero y por código por programa, con aviso si el resumen da otra cifra (#717)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B (2026-11-23, sobre el diff sin commitear del worktree)
- Security reviewer: no — solo lee el texto del log y de la respuesta y añade texto; sin red, rutas, ficheros ni secretos; regex acotadas revisadas por los dos jueces
- Verdict: conforms-with-notes (A: conforms-with-notes; B: does-not-conform por L1 y L2, arreglados con test rojo antes)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | `server._lint_counts`, línea tras el resumen y antes de los avisos (spec ajustada, L6) |
| REQ-002 | yes | yes | `lint_patterns.count_mismatches`: total, cifra por código, código ajeno, fuera de entradas |
| REQ-003 | yes | yes | sin aviso con línea:columna, `Found N errors`, listas de líneas, totales de dos ficheros, nombres base ambiguos, negrita bajo títulos |
| REQ-004 | yes | yes | eslint por defecto y pytest sin línea ni aviso |
| REQ-005 | yes | yes | mecánico, largo y troceado |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| R1 | Total de una línea que nombra dos ficheros comparado con uno | menor | — | suspected | arreglado: `_names_other` antes del total; test `test_what_the_program_cannot_tell_gives_no_warning` |
| R2 | «2 errores E501 y 1 E741» / «2 errores de E501» / «2 avisos (E501)» leídos como total | menor | bloqueante (L2) | confirmed | arreglado: `_TOTAL_TO_CODE` hace de esa cifra la del código; tests rojos antes |
| R3 | `E501 (10, 22)`, `(10 y 22)`, `(10-22)` leídos como cifra | menor | menor (L4) | confirmed | arreglado en `_AFTER_CODE`; tests |
| R4 | Negrita `**Por código:**` tomada como viñeta de la última entrada de título | menor | bloqueante (L1) | confirmed | arreglado: viñeta exige marcador y espacio; test rojo antes |
| R5 | Nombre base que comparten dos ficheros del log | menor | — | suspected | arreglado: la entrada no se juzga; test |
| R6 | Orden: la línea de totales de tests (#715) va detrás de los avisos y esta delante | menor | menor (L6) | confirmed | arreglado en el PR #722: `_before_warnings` para las dos líneas; tests de orden en lint y summarize, rojos antes |
| R7 | Párrafo sin sangría bajo una entrada de título o fichero a media línea se compara con el total del log | menor | menor (L3) | confirmed | arreglado en el PR #722: el párrafo y sus viñetas no se juzgan; la línea que nombra ficheros avisa solo si su cifra no es ni la de ellos ni la del log; tests rojos antes |
| R8 | `MARKDOWN_ESCAPE.sub` con reemplazo vacío en `_names_other` | — | menor (L5) | suspected | arreglado (`\1`) |

## Required follow-up

- R6 y R7 arreglados en el PR #722. Su revisión independiente (conforms-with-notes) dejó H1 (un
  párrafo dejaba la entrada abierta y daba un aviso de más a las viñetas siguientes), H2 (callar
  toda línea que nombra un fichero perdía avisos reales), H4 (sin test del orden en
  `local_summarize`) y H5 (wiki desfasada): los cuatro arreglados en el mismo PR, con tests rojos
  antes. H3 (un código sin viñeta bajo un título queda sin juzgar) se acepta: antes se comparaba
  con el total del log, que tampoco era correcto.
