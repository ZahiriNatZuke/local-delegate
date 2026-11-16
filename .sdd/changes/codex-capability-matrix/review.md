# Result review: Codex: matriz de capacidades y alternativas para barra, comandos sin modelo y tools fijadas (#671)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: deep
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: yes (personal-security-reviewer, sin hallazgos explotables)
- Verdict: conforms-with-notes tras aplicar los hallazgos (A: conforms-with-notes; B: does-not-conform por H1, arreglado)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | review | estados de la matriz ajustados a la leyenda (A-04, H7) y evidencia matizada (H8) |
| REQ-002 | sí | test | H1/H5 arreglados leyendo la tabla con `tomllib`; tests de H2, H3, H4 añadidos |
| REQ-003 | sí | test | `doctor` usa la misma lectura (H9) |
| REQ-004 | sí | cmd | tabla de las funciones del instalador, no la CLI (anotado) |
| REQ-005 | sí (doc) | review | sin código de producto para barra ni comandos |
| REQ-006 | sí | review | «la línea» → «la lista» (A-01, H6) |
| REQ-007 | sí | test | cifra de la ayuda alineada a 15,8 KB (A-06, H10) |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Un `]` en un comentario dentro de una lista multilínea corta la captura: TOML inválido o valores perdidos | A-02 | H1, H5, H9 | confirmed | `_section_exposure` saca los valores con `tomllib` de la tabla; el texto capturado solo se reemite si dice exactamente eso; si no, se rehace sin perder valores; test `test_a_bracket_in_a_comment_inside_the_list_loses_nothing` (con y sin flag, y `doctor`) |
| F2 | «Conserva la línea tal cual» no es cierto: se pierde el comentario de fin de línea | A-01 | H6 | confirmed | texto corregido a «la lista» en spec, docstrings, CHANGELOG y wiki; test comprueba el texto exacto de la lista |
| F3 | Faltan tests del aviso con `--no-mcp` y con entrada a mano rechazada, y de entrada a mano reemplazada | A-03 | H4 | confirmed | tests añadidos (`test_the_flag_with_no_mcp_says_so`, `test_a_refused_hand_entry_says_the_flag_did_nothing`, `test_a_replaced_hand_entry_keeps_its_list`, `test_the_two_flags_exclude_each_other`) |
| F4 | Sin test de «flag con `deferred` ya presente queda byte a byte» | — | H2, H3 | suspected | test `test_the_flag_keeps_a_list_that_already_has_deferred_byte_for_byte` (comillas simples y espacios) |
| F5 | Estados fuera de la leyenda y evidencia exagerada en la matriz | A-04 | H7, H8 | confirmed | filas reescritas con los cinco estados; «cargado» en vez de «probado» para las tools directas |
| F6 | Dos pares de cifras y 15 frente a 15,8 KB | A-05, A-06 | H10 | confirmed | un solo par (tabla del instalador) y 15,8 KB en la ayuda |
| F7 | Receta de PowerShell sin ejecutar | A-07 | — | suspected | ejecutada: 11 y 0 (verification.md) |
| F8 | Valor que no es lista desaparece sin aviso | A-08 | H6 | confirmed | aceptado: Codex ya rechazaba esa entrada; test de guarda |
| F9 | `test_the_two_flags_exclude_each_other` también pasa en `main` (flag desconocido da el mismo `SystemExit`) | — | — | suspected | aceptado como guarda de regresión, anotado en verification.md |

## Required follow-up

- Prueba en vivo de la persona usuaria (pasos en `docs/wiki/Codex-capabilities.md`).
- Seguimiento aparte: subcomando de CLI que llame a `local_summarize`/`local_commit_msg`/
  `local_lint_summary` para usarlo con `!` en Codex.
