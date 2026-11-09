# Specification: local_extract: aviso de valores sin respaldo y campos de línea por título

## Summary

`local_extract` (issue #594) deja de devolver en silencio el esquema de encabezados entero en un
campo que pide la línea de UN título (`local_extract_section_heading_line`): lo recorta por
programa al encabezado que nombra cuando no hay duda, y si la hay lo deja y avisa; y «Título:
línea 1» sobre un encabezado ya no se marca como línea dudosa.

El aviso de palabras sin respaldo (`ungrounded_keys`) que este cambio llegó a tener para #586 se
retiró tras la revisión independiente: daba avisos falsos en los usos normales (traducciones,
clasificaciones, fechas, paráfrasis). #586 se cierra en el cambio aparte del prompt
(`fix/extract-prompt-sin-relleno`), que ataca la causa.

## Requirements

- **REQ-003** — Con la entrada numerada de un Markdown (#568), un campo de ubicación que pide UN
  sitio (una palabra de sitio en singular: line, heading, title, section, título, capítulo…) y
  cuyo nombre, sin las palabras de ubicación, nombra algo, y cuyo valor cita 3+ líneas de
  encabezados y al menos la mitad del esquema, es una copia del esquema. Se recorta a
  `"<encabezado>: N"` (la forma «nombre: línea» que ya entiende `check_values`) solo sin duda: el
  sujeto está en singular (ninguna palabra acaba en `s`) y exactamente un encabezado tiene todas
  sus palabras como palabras enteras (desempate: el de menos palabras de más, único). Con duda
  (`tools_section_line`, `pasos_heading_line`, `tool_heading_line` frente a «Tools», ningún
  encabezado o varios) se deja como vino. En los dos casos `_local_delegate.outline_copies`
  (`{campo: N | null}`) y `warning` con el aviso es/en `mcp.warning.extract_outline_copies`.
  - Request: "con un campo que pide la línea de un título, devuelve el índice entero de secciones en cada campo"
  - Verify: test tests/test_extract_field_fidelity.py
- **REQ-004** — Un campo que pide varios sitios no es una copia y no se toca ni se avisa: sin
  nombre propio o con una palabra de sitio en plural, en inglés o en español
  (`sections_with_lines`, `tools_with_lines`, `capitulos_con_linea`), o con `each`/`every`/`all`/
  `cada`/`todos`/`todas` (`line_of_each_heading`, `linea_de_cada_seccion`).
  - Request: derived: la petición del esquema entero es un uso legítimo de #568
  - Verify: test tests/test_extract_field_fidelity.py
- **REQ-005** — `line_check.check_values`: una cita cuyo nombre son solo palabras genéricas de
  título (título, title, heading, encabezado, cabecera, header) se da por buena si una línea
  CITADA (sin la tolerancia) es un encabezado del esquema (ATX fuera de bloques de código), o,
  como antes, si la palabra está en esas líneas o alrededor (`title:` de un front matter).
  «Título: línea 1» sobre `# Catálogo de tools` ya no sale en `lines_unverified`; «Título: línea 2»
  junto a ese encabezado, «línea 3» sobre texto y un `# comentario` dentro de un bloque de código sí.
  - Request: "y marca la línea 1 como dudosa"
  - Verify: test tests/test_extract_field_fidelity.py
- **REQ-006** — Docstring de `local_extract`, `docs/wiki/Tools.md` y CHANGELOG (`[Unreleased]`)
  describen `outline_copies` y cuándo se recorta y cuándo solo se avisa.
  - Request: derived: la documentación de la release describe toda clave nueva de `_local_delegate`
  - Verify: review diff

## Acceptance scenarios

### Scenario: esquema copiado en un campo de un título

- **Given** `docs/wiki/Tools.md` y un modelo que responde el esquema entero a `local_extract_section_heading_line`
- **When** se llama a `local_extract(path=…)`
- **Then** el campo vale `` "`local_extract`: 101" ``, `outline_copies` es `{campo: 101}` y no hay `lines_unverified`

## Edge cases and failure behavior

- Entrada troceada: los campos de ubicación se unen por programa (#568) antes del recorte.
- Encabezados repetidos: empate, se deja y se avisa.

## Non-functional requirements

- Sin expresiones regulares nuevas sobre la entrada; el esquema se calcula una vez por llamada.
- Ningún cambio en las peticiones al backend (prompts, `max_tokens`, schema): las fixtures de
  `tests/fixtures/request_bodies/` y los corpus congelados no cambian.

## Non-goals

- #586 (valores inventados o de otra fila): va en el cambio del prompt, aparte.
- Recortar con un sujeto dudoso (plural, coincidencia por prefijo): se prefiere avisar.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
