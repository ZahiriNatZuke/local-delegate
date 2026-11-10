# Result review: local_extract: aviso de valor cruzado entre claves y subida al rol long en tablas (#586)

## Review level

- Level: deep
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: yes — sin hallazgos explotables (DoS de `has_table`, fuga en log o respuesta, motivo mezclado entre peticiones concurrentes, fixtures, sdist)
- Verdict: conforms-with-notes

Revisión del 2026-11-10 sobre el diff mezclado en `main` (`da15a6f6`, PR #643, sin `.sdd/`), la
spec, el plan y `verification.md` con la prueba en vivo ya hecha. Compatibilidad comprobada por la
sesión que consolida: `git diff --diff-filter=MDR da15a6f6^ da15a6f6 -- tests` vacío; ninguna
función quitada de `server.py`; la firma de `local_extract` no cambia para el cliente (el esquema
sigue el `__wrapped__` del decorador; `test_tool_signatures` y `test_tool_contract` en verde); los
PR #645 y #646, que entraron en la misma integración de la prueba en vivo, no tocan el enrutado.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | n/a (puerta) | yes | 0 de 8 cruces, 0 de 44 claves falladas (`outputs/gate-g4-research.json`) |
| REQ-002 | yes | yes | `_TABLE_LONG_MIN_FIELDS = 1` (ver E9) |
| REQ-003 | n/a | yes | 2,944 s en la puerta; 3,09 s en vivo; techo 6,5 s |
| REQ-006 | n/a | yes | según el registro de la puerta |
| REQ-007 | yes | yes | la fuente congelada del TOML no da tabla; `tests/test_corpus.py` sin tocar |
| REQ-008 | yes | yes | reparto 16/6 y formas que no ve fijadas; ver E2 |
| REQ-009 | yes | yes | sin `re`, lineal; cinco entradas de 1 MB en proceso hijo |
| REQ-010 | yes | yes | módulo sin `server`; `server` llama a la regla |
| REQ-011 | yes | yes | por `path` y por `text`, `role="long"` |
| REQ-012 | yes | yes | los 6 sin tabla siguen en el mecánico, también en vivo |
| REQ-013 | yes | yes | un solo campo sube |
| REQ-014 | yes | yes | interruptor apagado: comportamiento de antes |
| REQ-015 | yes | yes | summarize, lint y translate sin cambio |
| REQ-016 | yes | yes | también en las dos respuestas de error; nunca en `warning` |
| REQ-017 | yes | yes | `ContextVar` + `Token.role_reason`; no se filtra a la operación siguiente |
| REQ-018 | yes | yes | prompt idéntico byte a byte; parámetros del rol `long` |
| REQ-019 | yes | yes | respaldo al modelo de `code` |
| REQ-031 | yes | yes | docstring; ver E6 |
| REQ-032 | yes | yes | guardián de 7 superficies e i18n; ver E10 |
| REQ-033 | yes | yes | cifras, coste, respaldo, interruptor y límites, releídos por un juez |
| REQ-034 | yes | yes | sin cambios en skills, memoria, plugin, hooks ni `web/` |
| REQ-035 | yes | yes | solo altas en `tests/`; suite entera en el CI del PR y de `main` (E1) |
| REQ-036 | n/a | yes | 17 de 17 mutantes, según el registro |
| REQ-037 | n/a | yes | tabla antes/después y, tras E3, inferencia «después» caso a caso |
| REQ-038 | n/a | yes | ventana `w-20261110T190517Z`, `pass: true`, antes de mezclar (E5) |
| REQ-039 | n/a | yes | #586 cerrado con la primera línea pedida, #650 con el contenido pedido, tarjetas (comprobado con `gh`; ver E11) |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| E1 | La suite entera solo constaba antes del decorador; después, 15 ficheros | yes | yes | confirmed | resuelto: anotados el CI del PR #643 (22 checks en verde) y el de `main` en `da15a6f6` |
| E2 | Una línea `---` sin tuberías tras una línea con dos `|` cuenta como tabla (front matter YAML, título subrayado); la spec lo admite al pie de la letra, pero no está en «Límites» ni en la documentación | yes | yes | confirmed | aceptado para esta versión (cae del lado de subir de más); anotado en «Deviations»; propuesto para el seguimiento #650 |
| E3 | A la tabla antes/después le faltaba la inferencia «después» caso a caso | yes | yes | confirmed | resuelto: tabla añadida en «Prueba en vivo (REQ-038), resultado» |
| E4 | La evidencia del cierre del #586 y del #650 no tenía enlaces | yes | yes | confirmed | resuelto: URL del comentario y del issue; comprobados con `gh` |
| E5 | La prueba en vivo se hizo sobre la integración de cuatro PR, no sobre la rama sola | yes | no | suspected | aceptado: superconjunto sin cambios en el enrutado; anotado en «Deviations» |
| E6 | El docstring no nombra la tabla GFM sin tuberías externas ni `|-|-|` | yes | no | suspected | seguimiento: completar la frase en una versión próxima |
| E7 | `tests/test_extract_table_routing_docs.py` se retocó en el commit de la release | yes | no | suspected | anotado en «Deviations»; es un test del propio cambio |
| E8 | La exclusión de `ruff` es por carpeta de un cambio y `force-exclude = true` vale para todo el repo | yes | yes | confirmed | aceptado como decisión deliberada (ya en `handoff.md`, «Decisions»); seguimiento opcional: patrón genérico para scripts congelados de `.sdd` |
| E9 | `_TABLE_LONG_MIN_FIELDS = 1` nunca falla porque `fields` vacío se rechaza antes | no | yes | suspected | aceptado: fija el valor medido de REQ-002 y el mutante M07 |
| E10 | El guardián de superficies hace `skip` si falta un fichero, así que un doc borrado pasa | no | yes | suspected | seguimiento: fallar dentro del árbol del repo |
| E11 | La tarjeta del tablero «mandar al rol long las tablas… (#586)» sigue en «Por hacer» | no | no | suspected | hallado por la sesión que consolida; la mueve la sesión coordinadora |

El revisor de seguridad no dio hallazgos. Dos notas suyas sin camino de ataque: una entrada no
fiable con `<tr` fuerza el modelo largo (por diseño, avisado y con interruptor), y el fixture
`13-aviso-obras-es.txt` trae un nombre de persona con lugares reales, sin nada que lo ligue a nadie;
se puede cambiar por uno claramente ficticio.

## Required follow-up

- Ninguno bloquea el cierre.
- Seguimiento: E2 en el #650; E6 y E10 en una versión próxima; mover la tarjeta de E11.
