# Result review: El verificador de citas acepta un alias o una constante del nombre citado (#616)

## Review level

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: no — sin autenticación, secretos ni datos; el riesgo de regex sobre entrada del usuario se cubre con el test de linealidad
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | `aliases()` y su uso en `check` |
| REQ-002 | yes | yes | la línea entera es el enlace; argumentos con nombre, sentencias previas y `as` fuera de un `import` no crean alias |
| REQ-003 | yes | yes | casos `CORRECT`/`WRONG` sin cambios |
| REQ-004 | yes | yes | patrón anclado a la línea entera; el test de tiempo recorre líneas que sí contienen el nombre |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | La coma final admitía argumentos con nombre (`name="…",`) como alias genéricos | media | media | confirmed | arreglado: sin coma final; caso en `test_a_name_bound_mid_statement_is_not_an_alias` (mutante con coma: falla) |
| F2 | El test de linealidad no llegaba al regex | media | media | confirmed | arreglado: las líneas largas contienen el nombre |
| F3 | `\s*[;,]?\s*$` cuadrático con muchos espacios | baja | baja | confirmed | arreglado: `fullmatch` sobre la línea sin espacios a los lados |
| F4 | `if ready: x = name`, `case X:` o `except … as` daban alias equivocados | baja | baja | confirmed | arreglado: el enlace es la línea entera (`fullmatch`) y `as` solo cuenta con `import`; casos en el test (mutantes `search` y sin `import`: fallan) |
| F5 | El ejemplo `fn = readSummarize` de la spec no cumple el mínimo de 3 letras | baja | — | suspected | arreglado: `summarize_fn` |
| F6 | `(?<![=!<>])` y `(?!=)` sobraban | — | baja | suspected | quitados al anclar el patrón |

## Required follow-up

- Ninguno.
