# Result review: local_extract: las líneas las calcula el programa y el esquema tiene tipos por campo (#692, #694, #696, #697, #698)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: deep
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: yes (personal-security-reviewer: sin ejecución de código; tres hallazgos de disponibilidad, arreglados con su test y su mutante)
- Verdict: conforms-with-notes tras aplicar los hallazgos (A: quality aprobada con menores, conformance bloqueada por A-H1, arreglado; B: conformance bloqueada por B-H1 y quality por B-H2, arreglados)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | test | M2 en rojo; `model_error.raw` y `dropped` conservan texto del modelo como diagnóstico (desviación anotada) |
| REQ-002 | sí | test | forma `{name, start, end}` en todos los caminos |
| REQ-003 | sí | test | M1 en rojo |
| REQ-004 | sí | test | B-H1 (blanco Unicode leído como palabra por el lexer rápido) arreglado con `(\s*+)`; M12 en rojo |
| REQ-005 | sí | test | |
| REQ-006 | sí | test | mismos rangos que antes, en la forma nueva |
| REQ-007 | sí | test | A-H1 (faltaba `test_the_696_fields`) cerrado; B lo confirma con rangos sacados del texto |
| REQ-008 | sí | test | M4 y M5 en rojo |
| REQ-009 | sí | test | M6 en rojo |
| REQ-010 | sí | test | |
| REQ-011 | sí | test | M3 en rojo; `_Lines.hits` con `str.find` equivalente al anterior (B) |
| REQ-012 | sí | test | |
| REQ-013 | sí | test | M9 en rojo |
| REQ-014 | sí | test | `role_reason` con tabla y todo por programa: test nuevo, M13 en rojo |
| REQ-015 | sí | test | M8 en rojo |
| REQ-016 | sí | test | M8b en rojo |
| REQ-017 | sí | test | M7 en rojo |
| REQ-018 | sí | test | |
| REQ-019 | sí | cmd | suite completa y CI del PR en verde sobre 9dab4c2b |
| REQ-020 | sí | test | CHANGELOG, README, wiki, skill y memoria es/en |
| REQ-021 | sí | review | 14 de 14 mutantes en rojo (tabla de `verification.md`) |
| REQ-022 | sí | test | criterio cambiado a crecimiento lineal (spec, 2026-11-23, con motivo); M10 ×30 y M11 ×72 frente a tope ×25; lineal ×12–14 |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

A revisó el cambio entero (primera pasada); B, el diff desde df3f3b19^ y los arreglos de A. Cada
hallazgo lo vio un solo juez sobre un alcance que el otro no cubría, así que queda «suspected» y se
resolvió verificándolo en el código. Los S-* son de la revisión de seguridad, medidos antes de arreglarlos.

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| A-H1 | faltaba `test_the_696_fields` (REQ-007) | importante | confirmado cerrado | suspected | añadido en df3f3b19 |
| A-M | 8 menores (avisos es/en, `[5, 9]`, `located.index`, reintento, fixtures, skill y memoria, `role_reason`) | menores | cerrados salvo el test de `role_reason` | suspected | arreglados en df3f3b19; test de `role_reason` en 9dab4c2b (M13) |
| B-H1 | el lexer rápido leía un NBSP antes de `{`, `}`, `/`, comillas o comilla invertida como palabra | — | importante | suspected | verificado con el mutante M12 y arreglado con `(\s*+)` en 9dab4c2b |
| B-H2 | `verification.md` desfasada respecto a la cabeza | — | importante | suspected | actualizada con la suite y el CI sobre 9dab4c2b |
| B-H3 | el test de anclas mezcla índice y «anclas × tamaño» | — | menor | suspected | justificado: es lo que pone en rojo a M10; en producción las anclas las acota `max_tokens` |
| B-H4 | `_anchor_block` recorre los contenedores de Markdown por ancla | — | menor | suspected | aceptado como riesgo: lineal en el tamaño con anclas acotadas |
| B-H5 | cuenta de mutantes desfasada | — | menor | suspected | corregida (18 de 18 tras la revisión de seguridad) |
| B-H6 | comentario de `_FILE_WORDS` desfasado; líneas largas en la skill y la memoria | — | menor | suspected | comentario corregido; las líneas largas son prosa Markdown fuera de ruff |
| S-1 | lexer de TS/JS cuadrático en una línea de comillas que no cierran o de `(/[` | — | — | confirmed | medido (40 KB: 13 s y 21 s) y arreglado: memoria de la comilla que no cierra y tope de 512 para la regex literal; M14 y M15 |
| S-2 | secciones de Markdown cuadráticas por copiar la lista de encabezados | — | — | confirmed | medido (100 000: 7,3 s) y arreglado con una pila; M16 |
| S-3 | `RecursionError` sin capturar con una cadena larga de `elif` | — | — | confirmed | reproducido con 1 200 `elif` y arreglado con un recorrido con pila propia; M17 |
| CQ-1 | CodeQL: `except` vacío en `_python_comment_lines` | — | — | confirmed | ahora devuelve lo leído, con el motivo en un comentario |

## Required follow-up

- Prueba en vivo del camino del ancla con el modelo real (en vivo, #694 se resolvió por el `enum`): fuera de este cambio, con `test-window`.
- Mezclar el PR lo decide el usuario.
