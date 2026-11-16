# Specification: local_describe_image no mide: aviso por programa ante alineación, píxeles o saltos de línea (#663)

## Summary

`local_describe_image` dice en su descripción que no sirve para verificar alineación, tamaños,
distancias ni saltos de línea, y avisa en la respuesta cuando la pregunta o la respuesta hablan de
eso. El prompt del modelo no cambia.

## Requirements

- **REQ-001** — La descripción de la tool (docstring visible por el cliente MCP) dice que no mide y que eso se mide en el DOM.
  - Request: "que la descripción de la tool (docstring visible por el cliente MCP …) avise de que no sirve para verificar alineación, tamaños ni distancias al píxel y que para eso hay que medir"
  - Verify: test tests/test_vision_measurement_notice.py::test_the_description_says_it_does_not_measure
- **REQ-002** — Si la pregunta o la respuesta hablan de alineación, píxeles, desplazamientos, tamaños comparados, espaciado o saltos de línea (es/en), la respuesta termina con `[local-delegate warning: …]`; la respuesta del modelo queda intacta delante.
  - Request: "o que las marque como no verificables" (issue)
  - Verify: test tests/test_vision_measurement_notice.py (casos del issue y del comentario, parametrizados)
- **REQ-003** — Una descripción que no habla de medidas y un error del backend no llevan el aviso; el prompt del sistema no cambia.
  - Request: derived: no romper el uso normal ni el contrato de errores; riesgo de cambio de prompt
  - Verify: test tests/test_vision_measurement_notice.py::test_a_description_that_does_not_measure_has_no_notice, test_a_backend_error_gets_no_notice, test_the_prompt_is_not_changed
- **REQ-004** — La wiki, la skill `local-delegation` (es/en), CHANGELOG y catálogos es/en lo dicen.
  - Request: "y la doc en `docs/wiki/`"
  - Verify: review docs/wiki/Tools.md, SKILL.md, SKILL.en.md, CHANGELOG.md; test_i18n_parity

## Acceptance scenarios

### Scenario: pregunta de alineación del issue

- **Given** una captura de dos barras apiladas
- **When** se llama con «¿Están alineados los elementos de las dos filas?» y el modelo dice que no
- **Then** la respuesta trae lo que dijo el modelo y, detrás, el aviso de que no mide

## Edge cases and failure behavior

- Respuesta de error del backend: sin aviso (el postproceso solo corre con respuesta buena).
- Palabras de medida en una descripción general («padding», «spacing»): aviso de una línea, aceptado.

## Non-functional requirements

- Expresión lineal sobre texto no confiable.

## Non-goals

- Cambiar el prompt del rol `vision`.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
