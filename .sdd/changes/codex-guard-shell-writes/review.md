# Result review: Guard de Codex: escrituras de shell sobre ficheros resumidos

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-a, result-reviewer-b
- Security reviewer: n/a (lite)
- Verdict: conforms-with-notes (tras los arreglos; A dio «no aprobado tal cual» por F1/F2, B «aprobado con notas»)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | tests | comillas dobles y comentarios saltados tras la revisión |
| REQ-002 | sí | tests | asignación a expresión documentada como límite |
| REQ-003 | sí | tests | `$null = New-Item` añadido tras la revisión |
| REQ-004 | sí | tests | lecturas envueltas con salida canalizada no levantan el guard |
| REQ-005 | sí | tests | 41 controles |
| REQ-006 | sí | tests | medido por proporción; here-strings lineales |
| REQ-007 | sí | cmd | evidence/hook-real-stdin.txt |
| REQ-008 | sí | review | límites de la revisión añadidos a la wiki |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Lectura dentro de `{ }` con la salida canalizada levanta el guard (regresión) | sí | no | suspected | arreglado: `literal_reads` vuelve a la orden sin desbracear; test |
| F2 | Lectura envuelta (`bash -c 'cat x'` seguida de `head`) levanta el guard | sí | no | suspected | arreglado: no cuenta si la etapa sigue por tubería o fichero; test |
| F3 | Comillas dobles, comentarios y apóstrofos desalinean el escáner de .NET | sí | sí | confirmed | arreglado: `_closing_quote` y comentarios; tests en los dos sentidos |
| F4 | `$null = New-Item …` no se ve | no | sí | suspected | arreglado: `_without_assignment`; tests |
| F5 | Llaves sin espacio (`& {Set-Content …}`) | no | sí | suspected | arreglado: pila de llaves en `_unbrace`; test |
| F6 | `Push-Location`, `Set-Location -Path` | sí | sí | confirmed | arreglado en el guard (`_MOVE_VERBS`); `read_parts` intacto |
| F7 | `strip_heredocs` cuadrático con `@'` sin cerrar; deduplicado cuadrático | sí | sí | confirmed | arreglado: `herestring_spans` lineal con test de equivalencia; dict |
| F8 | `$p = (Resolve-Path …).Path`, `powershell 'orden'`, `-cwa`, `-Value:x` | no | sí | suspected | documentado como límite en la wiki |
| F9 | Orden de uso y asignación, `'$p'` literal, mayúsculas en bash, ámbito hijo | sí | sí | confirmed | aceptado: casos raros que solo dan un falso positivo con el mismo nombre de fichero |
| F10 | Test de envoltorio que no discriminaba (`-Command $p = …` sin comillas) | sí | no | suspected | quitado; añadidos `cmd /k`, `Create`, `AppendText`, `param`, `Set-Variable`, `[ref]` |

## Required follow-up

- Ninguno bloqueante. F9 queda como riesgo residual conocido.
