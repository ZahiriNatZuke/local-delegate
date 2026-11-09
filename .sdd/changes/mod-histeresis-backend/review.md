# Result review: El mod usa la histéresis del panel para el estado del backend

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: no — el bloque que se incrusta es un fichero estatico del propio paquete, leido al importar; no hay datos de fuera, ni endpoint, ni cambio de autenticacion o rutas
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | si | si | `statusShownBackend` + `visibleState` |
| REQ-002 | si | si | ritmo rapido con `failures > 0` |
| REQ-003 | si | si | fuente unica en `common.js`, el panel la incrusta |
| REQ-004 | si | si | redaccion precisada tras la revision (A1) |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| A1 | Con `/api/backend` sin respuesta la banda dice «sin datos» y el panel repinta lo anterior | si | no | suspected | Aceptado y escrito en la spec: es el comportamiento de antes y lo exigen tests existentes; la cuenta no cambia |
| A2 | El test de REQ-004 casi no discriminaba | si | no | suspected | Reforzado: comprueba «sin datos» en ese latido, que no reinicia la cuenta y que no suma un fallo |
| A3 | La mitad del test de atadura compara la regla consigo misma | si | si | confirmed | Aceptado: la fuente unica la prueba la igualdad de texto; lo que ata es el paso a la banda |
| B1 | Ningun test mira `common.js` dentro de la rueda | no | si | suspected | Aceptado como seguimiento: la rueda lleva todo el paquete y el sdist ya se comprueba |

## Required follow-up

- Opcional: comprobar `mod/common.js` en la rueda en `test_build_hook.py`.
