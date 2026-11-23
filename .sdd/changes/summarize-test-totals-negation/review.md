# Result review: local_summarize: aviso cuando el resumen niega una categoria que el runner de tests conto

## Review level

- Level: standard
- Judges: result-reviewer-a, result-reviewer-b
- Security reviewer: no — solo añade un aviso de texto tras el resumen; sin red, rutas ni secretos nuevos; las regex las revisaron los dos jueces (acotadas a 400 caracteres por línea)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | pytest, jest, cargo y go por test (funciones puras); jest con `todo` no se reconoce |
| REQ-002 | yes | partial | por test con backend falso y control positivo; en vivo el modelo no negó nada en 4 llamadas, así que el aviso no se vio contra el backend real |
| REQ-003 | yes | partial | en vivo, 4 resúmenes fieles sin falso positivo (`evidence/vivo-2026-11-23.md`); pero hay falsos positivos fuera de la lista de la spec (F1, F2) |
| REQ-004 | yes | yes | sin backtracking catastrófico; `\s+in\s+` cuadrático dentro de una línea de ≤400 caracteres |
| REQ-005 | yes | yes | CHANGELOG, `docs/wiki/Tools.md` y CI completo de #686 |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | La coma no corta la negación y una cifra en letras tampoco: «Sin fallos, cuatro pruebas omitidas» avisa en falso; el modelo escribe cifras en letras (visto en vivo) | A1 | B1 | confirmed | seguimiento: cortar por coma y tratar números en letras como cifra; va al análisis de causa común de las tools de texto (no se toca el código en este cierre) |
| F2 | `failed` y `errors` comparten categoría: «1 falló, sin errores» avisa en falso | A2 | — | suspected | seguimiento, mismo análisis |
| F3 | El aviso cita `lines[-1]`, que puede ser la línea de otro runner o un `--- FAIL` cuando se negaron saltos | A5 | B2 | confirmed | seguimiento: citar la línea que cuenta la categoría |
| F4 | El aviso copia la cola cruda de la línea del runner (hasta 200 caracteres) | A4 | — | suspected | seguimiento: citar solo `N outcome`; bajo riesgo, el texto ya venía de la entrada |
| F5 | Dos tests de «resumen fiel» con «y»/«pero» no discriminan (palabra fuera del léxico, cuenta 0) | A3 | — | suspected | seguimiento de tests |
| F6 | Faltan formas verbales («se omitió», «omitieron») y la negación detrás de la palabra no está declarada fuera de alcance | A6 | B5 | confirmed | seguimiento |
| F7 | Una palabra fuera del léxico (`todo` de jest) descarta la línea entera sin avisar | — | B4 | suspected | seguimiento |
| F8 | El test lineal no ejercita las regex en líneas válidas largas | — | B3 | suspected | aceptado: tope de 400 caracteres por línea |

## Required follow-up

- F1 a F7 como tarjeta de seguimiento dentro del análisis de causa común de `local_summarize`; F1 y
  F2 son falsos positivos del aviso (el resumen no cambia nunca, solo se añade el aviso).
- En la próxima prueba en vivo, forzar una negación para ver REQ-002 contra el backend.
