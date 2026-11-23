# Result review: local_summarize troceado: reintentar una vez las secciones que faltan y nombrarlas en el aviso (#691)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B (2026-11-23, sobre el diff de #711 y el código de `main` 0696df14)
- Security reviewer: no — solo cambia cómo se recombinan secciones del resumen; sin red, rutas, ficheros ni secretos nuevos
- Verdict: does-not-conform (A: conforms-with-notes; B: does-not-conform por H1 en REQ-003)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | una sola llamada más, `server.py:6401-6409` |
| REQ-002 | yes | yes | `sections.merge_retry`, orden probado |
| REQ-003 | partial | partial | ver J1: una sección vacía dos veces deja su título en el cuerpo y además sale en el aviso |
| REQ-004 | yes | yes | sin faltantes no hay reintento; 500 en el reintento devuelve el resumen previo |
| REQ-005 | yes | yes | un único evento con el paso dentro de `steps` |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| J1 | Sección vacía en el trozo y en el reintento: `complete(name_missing=True)` solo salta las que faltan (`sections.py:666-668`), así que el título vacío queda en el cuerpo y se nombra en el aviso; ningún test combina `empty=True` con reintento fallido | — | bloqueante (H1) | suspected | abierto: arreglo y test pendientes |
| J2 | La spec dice `kind: "retry"`; código, wiki y CHANGELOG usan `sections_retry` | menor | menor | confirmed | alinear la spec |
| J3 | Sin test: sin tiempo (`_time_fits(1)`), material que no cabe en un trozo, reintento cortado por `length` | menor | menor | confirmed | pendiente |
| J4 | `merge_retry` no quita un título cortado de la respuesta del reintento | sospecha | — | suspected | sin verificar |

## Required follow-up

- Arreglar J1 con su test antes de aprobar `conformance`. Por la regla del 2026-11-16 (parar parches sueltos de las tools de texto), J1 es también evidencia para `text-tools-common-cause`.
