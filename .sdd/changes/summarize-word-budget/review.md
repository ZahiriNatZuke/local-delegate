# Result review: local_summarize corta el resumen a mitad de frase con el max_words por defecto (#580)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-1 (subagente autor, revisión contra spec y control positivo con mutantes), result-reviewer-2 (revisión antes de mezclar, que consta en el cuerpo del PR #581 como «Tras la revisión», y CI del PR)
- Security reviewer: no — sin superficie nueva: cambia un tope numérico y el posprocesado de texto de la propia respuesta del modelo
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | test + mutante | 514 con 150 y 184 con 40; mutante 2w+64 → `[364] == [514]` |
| REQ-002 | sí | test + mutante | map, reagrupado y reduce piden 514; mutante sin `max_tokens_for` → `{364} == {514}` |
| REQ-003 | sí | 11 casos + mutantes | más 4 mutantes tras la revisión (negrita-frase, CJK, tabla, valor por defecto 3w) |
| REQ-004 | sí | tests es/en y sin frontera | mutante sin `trim_cut` conserva el texto cortado y el aviso viejo |
| REQ-005 | sí | test + suite | salida con `stop` idéntica; asserts existentes cambiados solo en el número del tope |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Una línea entera en negrita que es frase (`**Conclusión.**`) se trataba como etiqueta y se quitaba | confirmed | confirmed (revisión antes de mezclar) | confirmed | Corregido en la rama: solo es etiqueta si no acaba en `. ! ? …` |
| F2 | Los finales `。！？` de chino y japonés no contaban como final de frase sin espacio detrás | confirmed | confirmed (revisión antes de mezclar) | confirmed | Corregido en la rama |
| F3 | Una fila de tabla cortada (que empieza por barra vertical) quedaba a medias | confirmed | confirmed (revisión antes de mezclar) | confirmed | Corregido en la rama: se quita entera |
| F4 | Una abreviatura («p. ej.», «EE. UU.») cuenta como final de frase | confirmed | confirmed (revisión antes de mezclar) | confirmed | Aceptado como límite conocido y documentado en el PR |

## Required follow-up

- Ninguno. Revisión antes de mezclar: tres ajustes (negrita-frase, finales CJK, fila de tabla cortada) aplicados en la rama con su mutante cada uno, y la abreviatura aceptada como límite. Quién hizo la revisión no consta en el PR (sin reviews ni comentarios en GitHub; solo el cuerpo del PR la menciona). Mezclado en `main` como `e85c0519` (PR #581), 22 checks del PR en verde y CI de `main` en verde.
