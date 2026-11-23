# Result review: local_extract: nombres de campo de ficheros y hunks de un diff por programa, sin null silencioso (#665)

## Review level

- Level: standard
- Judges: result-reviewer-a, result-reviewer-b
- Security reviewer: no — cambio de lectura local de un diff ya cargado (sin red, sin rutas nuevas, sin secretos); recorrido lineal sin regex nuevas, confirmado por los dos jueces
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | tests y prueba en vivo del 2026-11-23 (`evidence/vivo-2026-11-23.md`): 14 ficheros con rangos y hunks, sin `warning`; el rango largo del último hunk venía de recuentos inflados en la entrada sintética (comprobado en local) |
| REQ-002 | yes | yes | `changed_files_with_lines` por programa en vivo; `lines_changed` sigue siendo recuento |
| REQ-003 | yes | yes | `.patch` con preámbulo de `format-patch` leído como diff en vivo; un `.md` con preámbulo no (test) |
| REQ-004 | yes | partial | solo por test, con `.patch`; no en vivo |
| REQ-005 | yes | partial | solo por test; no en vivo |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | El último hunk en vivo incluía la firma `-- `/`2.47.0`; la nota de la evidencia lo atribuía al código | A1 | B1 | confirmed | la causa eran los recuentos `-N,6 +N,7` del generador (una línea de más); con recuentos exactos sale `1757-1764`; evidencia corregida |
| F2 | La excepción de recuento + plural de ficheros vuelve campo de líneas a `total_files_with_lines`, `count_files_lines`, `cantidad_archivos_con_lineas` | A2 | B2 | confirmed | seguimiento: acotarla a participios (`changed`, `modified`, `added`, `deleted`…) con test; va al análisis de causa común de las tools de texto |
| F3 | Sin test de hunks junto a un campo del modelo sobre un diff troceado (desde #687 los tests de hunks van solo por programa) | A3 | B3 | confirmed | seguimiento de tests |
| F4 | El plan decía «ningún test existente cambia» y el commit conjunto cambió 4 tests de `test_extract_diff_files_and_cut.py` (por #687) | A4 | — | suspected | aceptado: efecto de #687 en el mismo commit; anotado aquí como desviación |
| F5 | Sin tests de `.diff` con preámbulo, `.diff` sin cabeceras ni sufijo en mayúsculas | — | B5 | suspected | seguimiento de tests; el código ya pasa el sufijo a minúsculas |
| F6 | 4 de los 15 fallos del control positivo eran `AttributeError` (función nueva), no conducta | — | B4 | suspected | aceptado; el control de conducta lo dan los otros 11 |

## Required follow-up

- F2, F3 y F5 como tarjeta de seguimiento, dentro del análisis de causa común de `local_extract`
  (no se toca su código en este cierre).
