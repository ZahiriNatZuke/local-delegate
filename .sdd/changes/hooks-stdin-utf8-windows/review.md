# Result review: Hooks de la entrega por settings leen y escriben UTF-8 en Windows

## Review level

- Level: standard
- Judges: result-reviewer-1 (subagente autor, revisión contra spec), result-reviewer-2 (CI del PR y revisión de la sesión principal antes de mezclar)
- Security reviewer: no — sin superficie nueva: solo la codificación del stdio del propio proceso del hook
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | test + prueba instalada | casos `ñandú` y `Ácido` |
| REQ-002 | sí | test + prueba instalada | sin aviso, línea con `suggested: false` |
| REQ-003 | sí | test + prueba instalada | |
| REQ-004 | sí | review: `install.py` sin cambios | `update` recopia los scripts |
| REQ-005 | sí | test + prueba instalada | también en la rama de imágenes/documentos |
| REQ-006 | sí | test + prueba instalada | ruta con `ñ` íntegra en el `deny` |
| REQ-007 | sí | before.txt / after.txt | |
| REQ-008 | sí | review | `utf8_stdio` no se llama al importar |
| REQ-009 | sí | test + comparación sobre el log real | |
| REQ-010 | sí | test con control positivo | |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | El test de `StringIO` es una guarda de no regresión: pasa también con `utf8_stdio` vacía | confirmed | confirmed (revisión independiente) | confirmed | Aceptado: no puede discriminar el arreglo; protege que el arreglo no rompa los tests que inyectan `StringIO` |

## Required follow-up

- Ninguno. Revisión independiente antes de mezclar: «mezclar» con dos ajustes, aplicados en la rama: la medición deja fuera del recuento de lecturas los eventos `no_file`, y tests de shell y subagente que discriminan el arreglo UTF-8. Mezclado en `main` como `1ae287be` (PR #560), 22 checks del PR en verde y CI de `main` en verde.
