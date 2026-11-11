# Result review: Detector de tablas: GFM sin tuberías externas, |-|-|, CSV, TSV y ARIA; local_summarize sube a long con tabla (#650)

## Review level

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: no — el cambio no toca autenticación, secretos ni permisos; el riesgo de entrada no confiable (coste del detector) lo revisó el juez B y lo fijan 13 entradas hostiles de 1 MB
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | GFM detrás de `> ` o `+` no se ve; escrito |
| REQ-002 | sí | sí | también `;` con última celda vacía (juez B) |
| REQ-003 | sí | sí | coma entre dígitos ya no rompe el filtro de prosa (jueces A y B) |
| REQ-004 | sí | sí | una página que solo nombra `role="row"` sube; escrito |
| REQ-005 | sí | sí | corte temprano por celda larga y entrada hostil de tres pasadas |
| REQ-006 | sí | sí | docstring completado con lo que no ve |
| REQ-007 | sí | sí | |
| REQ-008 | sí | sí | nombra grid y treegrid |
| REQ-009 | sí | sí | |
| REQ-010 | sí | sí | |
| REQ-011 | sí | sí | |
| REQ-012 | sí | sí | CHANGELOG corregido; README y Tools completados |
| REQ-013 | sí | sí | `table_format(delimited=False)` ahorra las pasadas de CSV/TSV |
| REQ-014 | sí | sí | |
| REQ-015 | sí | sí | |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | El CHANGELOG decía que el aviso de cifras miraba CSV y TSV, al revés que el código | bloqueante | no visto | confirmed | corregido en CHANGELOG |
| F2 | Prosa con coma decimal o de miles y log con asctime pasaban por CSV | no bloqueante | no bloqueante | confirmed | la coma entre dígitos no cuenta para el estilo; tres tests negativos y mutante matado |
| F3 | El aviso de cifras recorría CSV/TSV sin usarlos; la prosa se leía entera | no bloqueante | no bloqueante | confirmed | `delimited=False` y corte al pasar de 8 palabras; entrada hostil nueva |
| F4 | Docstrings y docs decían menos que el código | no bloqueante | no bloqueante | confirmed | completados (módulo, local_extract, README, Tools) |
| F5 | CSV con `;` de Excel en español con última celda vacía no se veía | no visto | no bloqueante | suspected | aceptado si ningún `;` lleva blanco detrás; test y mutante |
| F6 | `role="row"` mencionado en un texto sube | no bloqueante | no visto | suspected | escrito como error del lado de subir |
| F7 | Faltaba test de tool con prosa con comas y el de superficies se saltaba | no bloqueante | no visto | suspected | test añadido; el de superficies falla si falta el fichero |
| F8 | `role = "row"` con blancos y GFM detrás de `> ` no se ven | no visto | no bloqueante | suspected | escrito en lo que no ve |

## Required follow-up

- Ninguno obligatorio. La medición del volumen de resúmenes pequeños que subirán la hace la sesión principal con el log real.
