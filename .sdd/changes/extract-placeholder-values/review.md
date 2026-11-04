# Result review: local_extract: marcadores de sin dato a null y cuentas de listas vacías

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-1 (agente revisor de resultado), result-reviewer-2 (revisión independiente de la sesión principal)
- Security reviewer: no aplica (sin entrada externa nueva; el recuento solo lee el JSON que ya llega como entrada)
- Verdict: conforms-with-notes (primera pasada «no aprobado», con todos sus ajustes aplicados y con test; segunda pasada «mezclar con cambios», ajustes aplicados en `6686d9a2`)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | marcadores de «sin dato» a `null` (`test_markers`, `test_markers_become_null_and_missing`) |
| REQ-002 | sí | sí | `missing_keys` en orden, `placeholder_keys` y avisos separados, también tras un renombrado |
| REQ-003 | sí | sí | `none`, `NA`, `0`, `"."`, `"--"`, `"..."` y textos con un marcador dentro no cambian |
| REQ-004 | sí | sí | el relleno desde parciales salta un marcador |
| REQ-005 | no (aplazado) | — | refuerzo del prompt fuera de la 0.49.0 por decisión del usuario; el PR quedó en `Refs #586` y el issue sigue abierto solo con esa parte |
| REQ-006 | sí | sí | recuento de listas de primer nivel con las guardas (a) y (b) de la segunda pasada |
| REQ-007 | sí | sí | suite completa sin tocar tests existentes (ver `verification.md`) |
| REQ-008 | sí | sí | entrada del CHANGELOG, hoy dentro de `[0.49.0]` |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Textos de la cláusula del prompt fuera del catálogo | sí | — | suspected | resuelto al retirar la cláusula (REQ-005 aplazado) y con una excepción para `sin información` |
| F2 | `"."` legítimo convertido a null | sí | — | suspected | arreglado con test |
| F3 | El recuento pisaba una cuenta que trae el propio JSON | sí | sí | confirmed | no se recuenta si el JSON trae la clave pedida; en la segunda pasada, guardas (a) total con otro nombre y (b) total genérico, con test |
| F4 | `ValueError` con enteros de más de 4300 dígitos | sí | — | suspected | arreglado con test |
| F5 | Docstring y wiki sin los campos nuevos; faltaban pruebas de extremo a extremo del aviso tras truncado y del relleno troceado; BOM y float `2.0` | sí | — | suspected | añadidos y arreglados con test |
| F6 | CodeQL `py/side-effect-in-assert` en dos tests | — | sí | suspected | la llamada pasa a una variable |
| F7 | `--` y `...` tomados por marcadores | — | sí | suspected | fuera de la lista de marcadores |
| F8 | En modo numerado el prefijo numérico de línea escondía el marcador | — | sí | suspected | se quita antes de buscarlo, con test |

## Required follow-up

- Ninguno bloqueante para este cambio. El refuerzo del prompt (REQ-005) sigue en el issue #586, abierto por decisión del usuario.
- Revisión independiente antes de mezclar: consta en `verification.md` («Revisión independiente»): dos pasadas; la segunda, «mezclar con cambios», con sus ajustes aplicados en `6686d9a2` dentro del PR #591. En el PR solo hay un comentario automático de `github-advanced-security` (CodeQL), ya resuelto.
- Mezclado en `main` como `c5f8333c` (PR #591) con los 22 checks del PR en verde.
