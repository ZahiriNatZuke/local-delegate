# Result review: local_extract numera las líneas con path para campos de ubicación (#568)

## Review level

- Level: standard
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: no aplica (lite; sin superficie nueva de entrada: solo prompts y post-proceso puro)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | test | reutiliza `_number_lines` y `_numbered_code_pieces` (#460) |
| REQ-002 | sí | test | criterio estrechado tras la revisión |
| REQ-003 | sí | test | el prefijo exige barra y espacio, o fin de línea |
| REQ-004 | sí | test | solo `.md`/`.markdown`/`.mdx`; el trozo descuenta el esquema (test de presupuesto) |
| REQ-005 | sí | test | formas `[inicio, fin]` tratadas como rango |
| REQ-006 | sí | review | skill y bloque de memoria es/en |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Criterio con falsos positivos (`localidad`, `location`, `price_range`, `line_items`, `offset`) | sí | sí | confirmed | criterio estrechado: `lines`/`lineas`/`lineno` o `line`+calificador; tests negativos |
| F2 | Esquema calculado para cualquier fichero (`# comentario` de Python) | sí | no | suspected | solo extensiones Markdown; test con `.py` |
| F3 | `[inicio, fin]` comprobado como dos líneas; lista bajo clave de línea sin comprobar | sí | no | suspected | tratado como rango; test |
| F4 | `isdigit` + `int` lanza con `²` | sí | no | suspected | `isascii` + `isdecimal` + longitud ≤ 6; test |
| F5 | Prefijo quitado sin espacio (una fila de tabla «12 barra 34») | sí | sí | confirmed | exige barra y espacio, o fin de línea; test |
| F6 | Descuento del esquema sin test | no | sí | suspected | test de presupuesto por llamada |
| F7 | Llamada única puede pasar de `max_chars` y `max_tokens=512` corto para listas largas | sí | sí | confirmed | aceptado: mismo criterio que #460; anotado como riesgo residual |
| F8 | Hook y aviso del mod siguen sin la aclaración | sí | no | suspected | fuera de alcance (el mod exige reconstrucción); queda anotado |

### Segunda revisión (independiente, coordinador, PR #573)

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| G1 | Campos de cantidad (`lines_added`, `total_lines`, `num_lines`) activan la numeración | sí | sí | confirmed | palabras de cantidad descartan; plural junto a num/code descarta; tests negativos |
| G2 | Rango suelto junto a una cita explícita da una cita falsa; palabras de todo el elemento | sí | sí | confirmed | con cita explícita no se buscan formas sueltas; palabras de justo antes de cada cita; tests |
| G3 | Reduce con tope de ~512 tokens corta ~60 secciones y sale `not_json` | sí | sí | confirmed | ubicación unida por programa desde los parciales; atajo sin modelo; reduce cortado no pierde datos; tests |
| G4 | El aviso de líneas no se ve si ya había otro | sí | sí | confirmed | se añade con «; »; test |
| G5 | `heading_line`, `section_line`, `linea_del_titulo` no activan | sí | sí | confirmed | calificadores heading/section/título/sección; tests |

## Required follow-up

- Ninguno bloqueante. F7 y F8 quedan como riesgo residual anotado en la entrega.
- Revisión independiente antes de mezclar: consta en la sección «Segunda revisión (independiente, coordinador, PR #573)» de este fichero; pidió cinco ajustes (G1–G5), aplicados en la rama con test; el cuerpo del PR lo recoge («Segunda revisión (cinco hallazgos)»). En el PR no hay reviews ni comentarios de GitHub.
- Mezclado en `main` como `d4a3bb1f` (PR #573) sin los jobs de macOS: 19 checks del PR en verde; `test (macos-latest)`, `plugin (macos-latest)` y `ci-gate` en rojo porque GitHub no asignó runner de macOS («The job was not acquired by Runner of type hosted even after multiple attempts»). El usuario autorizó expresamente esta mezcla sin macOS el 2026-11-04 (bypass temporal del ruleset `protect-main`, restaurado después; consta en el relevo de la jornada).
