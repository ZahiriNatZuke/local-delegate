# Result review: Tools de texto: rechazo de binarios y rutas exactas en lint_summary

## Review level

- Level: standard
- Judges: revisor-orquestado-1, result-reviewer-2
- Security reviewer: no aplica (lite; entradas no confiables revisadas por los dos jueces: expresiones lineales y lectura de bytes sin ejecutar nada)
- Verdict: conforms

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | JPEG en las seis tools, PNG, GIF, WebP; cero llamadas al backend |
| REQ-002 | sí | sí | NUL y control por proporción en la muestra de 64 KiB; retroceso fuera de los bytes de control |
| REQ-003 | sí | sí | `_read_input` es el único lector de `path` |
| REQ-004 | sí | sí | 12 formas de texto; `tests/test_input_encoding.py` sin cambios |
| REQ-005 | sí | sí | un nombre base solo ya no es dueño de una absoluta |
| REQ-006 | sí | sí | |
| REQ-007 | sí | sí | progreso con colores, `-v`, `-v -n N` y líneas partidas |
| REQ-008 | sí | sí | carpetas de una letra y dominios sin esquema no se avisan |
| REQ-009 | sí | sí | CHANGELOG, wiki, i18n es/en |
| REQ-010 | sí | sí | rol mecánico, rol largo y troceado, con mutantes; prueba en vivo en `verification.md` |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Un NUL suelto en cualquier punto de un log largo lo rechazaba entero | media | no lo vio | suspected | arreglado: NUL por proporción (más del 1 %) en la muestra; tests `one_stray_nul` y `nul_past_the_sample` |
| F2 | Un byte de control en un fichero diminuto superaba el 10 % | baja | no lo vio | suspected | arreglado: mínimo de 8 bytes de control; test `tiny_with_bell` |
| F3 | `_decode_input_file` sin uso tras el cambio | baja | baja | confirmed | quitado |
| F4 | El progreso limpio no reconocía colores ANSI, `-v` ni `-v -n N` | media | sin hallazgo tras el arreglo | suspected | arreglado: `is_clean_progress` con métodos de `str`; tests por forma |
| F5 | Ficheros en verde con entrada en el resumen (#688 en vivo) | alta | cubierto por REQ-010 | confirmed | arreglado: `_lint_check_clean` avisa por programa |
| F6 | `verification.md` sin fila de REQ-010 y con desviación vieja | no lo vio | media | suspected | arreglado en `verification.md` |
| F7 | REQ-010 sin test en rol largo ni troceado | no lo vio | baja | suspected | arreglado: dos tests, que un mutante pone en rojo |
| F8 | Línea de progreso partida: el fallo de la continuación dejaba el fichero como limpio | no lo vio | baja | suspected | arreglado: `_reported_lines`; con fallos en la línea de totales el aviso calla |
| F9 | Sobreimpresión con retrocesos (`man`) rechazada como binaria | no lo vio | baja | suspected | arreglado: 0x08 fuera de los bytes de control |
| F10 | Una relativa que es solo nombre base se unía a una absoluta distinta | no lo vio | baja | suspected | arreglado: el dueño tiene que llevar carpetas |
| F11 | `w/` y `github.com/org/repo/` avisados como carpetas inventadas | no lo vio | baja | suspected | arreglado: `_is_folder_name` |
| F12 | Pasadas repetidas de `files_by_frequency` en el aviso | no lo vio | baja | suspected | arreglado: entradas primero, inventarios una vez |
| F13 | `.py`, `_FOLDER` y `URL` sin caso de tiempo lineal | no lo vio | baja | suspected | arreglado: tres casos en `test_the_clean_line_check_is_linear` |
| F14 | Un fichero de menos de 100 bytes con un NUL cae por la proporción | no lo vio | baja | suspected | aceptado: a ese tamaño un NUL apunta más a binario que a texto |
| F15 | UTF-32 con BOM se lee como UTF-16 (comportamiento de #672) | baja | no lo vio | suspected | fuera de alcance: es anterior a este cambio |

## Required follow-up

- Ninguno bloqueante. F15 queda anotado como posible seguimiento.
