# Result review: local_extract: aviso de valor cruzado entre claves (cross_filled_keys, #650)

## Review level

- Level: deep
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: yes (security-reviewer-1)
- Verdict: conforms-with-notes (tras corregir los hallazgos de la primera pasada)

Primera pasada sobre la versión inicial: juez 1 «does-not-conform» (falsos positivos con claves
derivadas), juez 2 «conforms-with-notes» (puerta sesgada, falsos positivos con etiqueta sinónima y
con resumen), seguridad: cuatro excepciones sin capturar y coste. Todos los hallazgos de abajo se
corrigieron y se añadieron como casos al conjunto; no hubo segunda pasada de jueces (la evidencia
nueva es la de `verification.md`).

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | cross_fill.cross_filled |
| REQ-002 | yes | yes | el valor no se toca |
| REQ-003 | yes | yes | fila única; valor y celdas una sola vez en el texto |
| REQ-004 | yes | yes | words() y formas cortas (max) |
| REQ-005 | yes | yes | _trivial() |
| REQ-006 | yes | yes | hojas de listas y objetos; booleanos y null fuera |
| REQ-007 | yes | yes | 0 falsos positivos en los tres conjuntos |
| REQ-008 | yes | yes | 01 y 06 detectados |
| REQ-009 | yes | yes | c01/price callado |
| REQ-010 | yes | yes | tests parametrizados por caso |
| REQ-011 | yes | yes | el aviso anterior se conserva exacto |
| REQ-012 | yes | yes | descripción, CHANGELOG y wiki |
| REQ-013 | yes | yes | el diff de server.py no toca el prompt |
| REQ-014 | yes | yes | casos n26 a n30 |
| REQ-015 | yes | yes | skip de location_fields |
| REQ-016 | yes | yes | seis entradas raras; recorte a 80 |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Claves derivadas (currency de «49 USD», first_name, city, release_year) daban aviso en falso: la coincidencia aceptaba un trozo de celda | blocking | not raised | suspected | coincidencia estricta (celda con o sin unidad); caso n29 |
| F2 | Clave de texto libre que cita una celda daba aviso en falso | raised | raised | confirmed | el valor tiene que estar hecho solo de celdas de la fila; casos n28 y n30 |
| F3 | Una palabra genérica compartida (cost, value) bastaba para que otra clave casara | not raised | raised | suspected | _fits: dos palabras, o una si una contiene a la otra; casos n26 y n27 |
| F4 | Unicidad comprobada sobre la celda y no sobre el valor | not raised | raised | suspected | se cuenta también el valor; caso n32 |
| F5 | Los campos de ubicación entraban en la comprobación | raised | not raised | suspected | skip de location_fields; test propio |
| F6 | Excepciones sin capturar: csv.Error, OverflowError, RecursionError, AssertionError de HTMLParser | raised | not raised | suspected | int sin pasar a float; captura en cross_filled; seis entradas de test (también lo señaló seguridad) |
| F7 | Coste: normalización repetida por celda y hoja | raised | not raised | suspected | normalización una vez por celda y presupuesto de 2 millones de celdas por hojas |
| F8 | Etiqueta de la fila sin límite en el aviso | not raised | not raised | suspected | seguridad; recorte a 80 caracteres |
| F9 | other_key engañoso con una fila de ninguna clave pedida (n04) | not raised | raised | suspected | resuelto por _fits; n04 ya no avisa monthly_active_users |
| F10 | _DIGIT_GAP une «12 345» en el texto donde se cuenta | raised | not raised | suspected | riesgo residual aceptado: dos números separados solo por un espacio cuentan como uno, y una repetición así puede pasar sin verse; muy raro y el aviso no cambia el valor |
| F11 | «in» como palabra vacía deja Check-in sin la palabra in | not raised | raised | suspected | aceptado: fallo de detección conocido, sin falso positivo |

## Required follow-up

- Ninguno bloqueante. La prueba en vivo es opcional (no cambia el prompt ni el enrutado).
