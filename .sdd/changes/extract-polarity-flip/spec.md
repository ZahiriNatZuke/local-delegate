# Specification: local_extract: aviso cuando un valor invierte la negacion de la fuente

## Summary

Cuando una frase de un valor devuelto por `local_extract` lleva una negación que su frase de la
entrada no tiene, o perdió la que la entrada tiene, la respuesta lo dice en
`_local_delegate.polarity_flipped_keys` y en `warning`, sin tocar el valor.

## Requirements

- **REQ-001** — La causa del issue queda confirmada o refutada con pruebas: el programa devuelve el
  texto del modelo palabra por palabra (también con `path` y campo de ubicación, donde actúa
  `_strip_extract_prefixes`), y la entrada del issue (3219 caracteres) no se trocea.
  - Request: "primero averigua la causa real (¿prompt?, ¿post-proceso que recorta negaciones?, ¿troceado que parte la frase?, ¿solo el modelo?)"
  - Verify: test tests/test_extract_polarity.py::test_the_value_comes_back_word_for_word
- **REQ-002** — Una frase de un valor con negación añadida o quitada respecto de su frase de la
  fuente (también traducida entre español e inglés) marca la clave en `polarity_flipped_keys` con
  `{"value", "source", "flip"}`; el valor no cambia.
  - Request: "comparar contra el texto fuente y avisar en `_local_delegate` cuando el valor extraído contradice [...] la fuente con su negación"
  - Verify: test tests/test_extract_polarity.py::test_a_flipped_clause_is_flagged
- **REQ-003** — Un valor fiel no se marca: traducción fiel, copia literal, negación que abarca una
  lista, palabra negada ausente, celdas y filas de tabla, «X, no Y» traducido como «X and not Y»,
  encabezado o línea `...:` negados, doble negación, clave con nombre de prohibición, fuente que
  dice las dos cosas, negación sin relación, frase corta, salto de línea en cualquier palabra; ni
  ninguna de las 177 respuestas guardadas en `tests/data/cross_fill/` ni ninguna frase de la wiki
  y del CHANGELOG copiada contra su propio fichero.
  - Request: "los tests deben tener un caso que dispara el aviso y otro que no"
  - Verify: test tests/test_extract_polarity.py::test_no_answer_of_the_gate_is_flagged
- **REQ-004** — El aviso va entre los avisos tardíos de `warning`, tras el de `cross_filled_keys`
  (un aviso anterior conserva su texto),
  existe en es y en, y el detector nunca rompe la respuesta (fuente enorme o vacía, excepción,
  presupuesto agotado); los campos de ubicación no se comprueban.
  - Request: "en la línea de los avisos que ya existen (`cross_filled_keys`, `lines_unverified`, `placeholder_keys`)"
  - Verify: test tests/test_extract_polarity.py::test_the_warning_is_appended_after_an_earlier_one
- **REQ-005** — CHANGELOG en «Unreleased», `docs/wiki/Tools.md` y docstring de `local_extract`
  describen el aviso; la suite completa sigue en verde.
  - Request: "CHANGELOG en «Unreleased»; `docs/wiki/Tools.md` si cambia lo documentado"
  - Verify: cmd pytest -n 2 con pesado.sh

## Acceptance scenarios

### Scenario: el caso del issue

- **Given** una fuente con «Revisar el código real del mod y los adaptadores de ambos clientes, no
  inferir la respuesta desde las skills o hooks.»
- **When** el modelo devuelve «Do not review code real of the mod and adapters of both clients, do
  not infer response from the skills or hooks.»
- **Then** `polarity_flipped_keys` nombra la clave con `flip` = `added` y el valor sigue igual

### Scenario: traducción fiel

- **Given** la misma fuente
- **When** el modelo devuelve «Review the real code of the mod and the adapters of both clients; do
  not infer the answer from the skills or hooks.»
- **Then** no hay `_local_delegate`

## Edge cases and failure behavior

- Fuente de más de 400 000 caracteres, vacía o cualquier excepción: sin aviso, respuesta intacta.
- Frase del valor con menos de tres raíces, sin frase que case o con casos de las dos polaridades:
  sin aviso.

## Non-functional requirements

- Solo biblioteca estándar; expresiones regulares sin cuantificadores anidados.
- Presupuesto de comparaciones (frases del valor por frases de la fuente).

## Non-goals

- Cambiar el prompt o corregir el valor.
- Detectar la inversión entre idiomas que no comparten raíces (fuera de español e inglés).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
