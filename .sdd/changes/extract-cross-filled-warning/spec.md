# Specification: local_extract: aviso de valor cruzado entre claves (cross_filled_keys, #650)

## Summary

`local_extract` avisa, sin tocar el valor, cuando la respuesta de una clave solo aparece en la fila
o línea de la entrada que pertenece a otra clave pedida. El aviso va en
`_local_delegate.cross_filled_keys` y en `warning`, y no salta en falso en el conjunto medido.

## Requirements

- **REQ-001** — Una clave cuyo valor toca celdas de una sola fila etiquetada, con esas celdas sin
  repetirse en la entrada, y cuya etiqueta casa en más palabras con otra clave pedida que con la
  propia, sale en `_local_delegate.cross_filled_keys` como `{clave: {"row": etiqueta, "other_key": B}}`.
  - Request: "aviso determinista en `_local_delegate.cross_filled_keys` cuando el valor de la clave A aparece literal en una fila/línea de la fuente cuya etiqueta coincide en palabras con OTRA clave pedida B"
  - Verify: test tests/test_extract_cross_fill.py::test_a_value_from_the_row_of_another_key_is_flagged
- **REQ-002** — El valor se devuelve tal cual; nunca pasa a null.
  - Request: "Solo aviso, nunca poner null."
  - Verify: test tests/test_extract_cross_fill.py::test_local_extract_reports_a_cross_and_keeps_the_value
- **REQ-003** — Un valor que también aparece en otra fila o en otra parte del texto no se avisa.
  - Request: "avisar solo si el valor aparece en la fila de B y en ninguna otra fila/línea de la fuente (ocurrencia única)"
  - Verify: test tests/test_extract_cross_fill.py::test_a_value_repeated_elsewhere_is_not_flagged
- **REQ-004** — Las etiquetas y claves se comparan por palabras: snake_case y camelCase partidos,
  minúsculas, sin acentos, sin palabras vacías y sin plurales simples.
  - Request: "normalizar etiquetas (snake_case/camelCase → palabras, minúsculas, sin plurales simples)"
  - Verify: test tests/test_extract_cross_fill.py::test_label_words_are_normalized
- **REQ-005** — Se ignoran valores triviales: null, booleanos, marcadores «sin datos», sí/no y
  cualquier valor de menos de dos caracteres (un número de una cifra).
  - Request: "ignorar valores triviales (vacíos, booleanos, números de 1 dígito, etc.)"
  - Verify: test tests/test_extract_cross_fill.py::test_trivial_values_are_not_flagged
- **REQ-006** — Se revisan strings y números, y los strings y números dentro de listas y objetos.
  - Request: "Valores lista/objeto: cubre al menos strings y números; di qué haces con el resto."
  - Verify: test tests/test_extract_cross_fill.py::test_strings_inside_a_list_or_an_object_are_checked
- **REQ-007** — Puerta de medición: 0 avisos en falso sobre las respuestas a mano del conjunto nuevo
  (≥ 20 tablas en HTML, Markdown, CSV y texto) y del `holdout`, y sobre las respuestas reales grabadas.
  - Request: "Objetivo: 0 falsos positivos en el conjunto"
  - Verify: test tests/test_extract_cross_fill.py::test_gate_totals
- **REQ-008** — Los dos cruces del #586 se detectan con su fila y su clave.
  - Request: "que detecte los cruces del #586"
  - Verify: test tests/test_extract_cross_fill.py::test_the_crosses_of_586_are_flagged
- **REQ-009** — El falso positivo de ayer (`price` = `39`, «Retail cost (USD)») no salta.
  - Request: "dio 1 falso positivo por pasada [...] clave `price` = `39`"
  - Verify: test tests/test_extract_cross_fill.py::test_yesterdays_false_positive_stays_quiet
- **REQ-010** — El conjunto queda como test parametrizado.
  - Request: "Deja el conjunto como test parametrizado."
  - Verify: test tests/test_extract_cross_fill.py::test_new_set_flags_only_crossed_keys
- **REQ-011** — El aviso se añade a `warning` sin pisar uno anterior, con texto en es y en.
  - Request: "derived: convención #455/#497 de avisos tardíos y catálogos i18n"
  - Verify: test tests/test_extract_cross_fill.py::test_the_warning_is_appended_after_an_earlier_one
- **REQ-012** — La descripción de `local_extract` nombra `cross_filled_keys` (en inglés) y el
  CHANGELOG lo cuenta en `[Unreleased]`.
  - Request: "Documenta el campo en la descripción de la tool `local_extract` (en inglés, una frase) y en el CHANGELOG."
  - Verify: test tests/test_extract_cross_fill.py::test_the_docstring_names_cross_filled_keys
- **REQ-013** — El prompt de `local_extract` no cambia.
  - Request: "No cambies el prompt."
  - Verify: review git diff de server.py: solo la llamada, el aviso y la descripción

- **REQ-014** — Un valor que es un trozo de una celda (`USD` de «49 USD») o prosa alrededor de una
  celda (un resumen que cita el peso) no cuenta como sacado de esa fila; sí la celda con o sin
  unidad y el valor hecho solo de celdas de la fila. Otra clave solo «casa» con una fila si comparte
  dos palabras, o una cuando una de las dos contiene todas las palabras de la otra.
  - Request: "derived: revisión de resultado (falsos positivos con claves derivadas, de texto libre y palabras genéricas)"
  - Verify: test tests/test_extract_cross_fill.py::test_new_set_flags_only_crossed_keys
- **REQ-015** — Los campos de ubicación (`…_con_lineas`) no se revisan.
  - Request: "derived: revisión de resultado (un `10-14` toca una celda `14`)"
  - Verify: test tests/test_extract_cross_fill.py::test_location_fields_are_not_checked
- **REQ-016** — Una entrada rara (campo CSV enorme, comilla sin cerrar, `\r` suelto, entero
  enorme, JSON muy anidado, HTML mal formado) nunca rompe la respuesta; la etiqueta del aviso se
  recorta a 80 caracteres; el recorrido tiene un presupuesto de celdas por hojas.
  - Request: "derived: revisión de seguridad"
  - Verify: test tests/test_extract_cross_fill.py::test_an_odd_source_never_breaks_the_answer

- **REQ-017** — Segunda pasada: la cabecera de columna solo cuenta si el valor sale de una sola
  columna; la fila tiene que ser la mejor de la otra clave en toda la entrada; cualquier excepción
  del detector se traga en la frontera; el presupuesto cuenta caracteres; una página HTML de más de
  100 000 caracteres no se revisa.
  - Request: "derived: segunda pasada de revisión del PR #659"
  - Verify: test tests/test_extract_cross_fill.py::test_a_big_html_page_is_not_scanned

## Acceptance scenarios

### Scenario: cruce del #586

- **Given** la tabla de precios con «Custom domains» y las claves `licensed_user_limits` y `custom_domain_limits`
- **When** el modelo da a `licensed_user_limits` las celdas de «Custom domains»
- **Then** `cross_filled_keys` trae `licensed_user_limits` con esa fila y `custom_domain_limits`, y el valor no cambia

### Scenario: número repetido con etiqueta sinónima

- **Given** `39` en «Retail cost (USD)» y en «Noise level (dB)», con `price` y `noise_level` pedidas
- **When** el modelo responde `price` = `39`
- **Then** no hay aviso

## Edge cases and failure behavior

- Una sola clave pedida, entrada vacía o de más de 400 000 caracteres: no se busca.
- Empate de palabras entre la clave propia y otra: no se avisa.
- Fila de ninguna clave pedida: no se avisa (B debe existir).
- CSV/TSV: la coma entre celdas no cuenta como coma decimal.

## Non-functional requirements

- Determinista, sin red, solo biblioteca estándar, regex sin cuantificadores anidados.
- Coste lineal en el tamaño de la entrada.

## Non-goals

- Detector de tablas y enrutado a `long`; prompt; corregir valores; cruces con etiquetas en otro
  idioma que la clave.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
