# Specification: local_extract: aviso de valores sin respaldo y campos de línea por título

## Summary

`local_extract` (issues #586 y #594) deja de devolver en silencio dos clases de valor que el modelo
inventa o copia:

- #586: un valor corto de texto con palabras que no aparecen en la entrada (`review_verdict:
  "positive"` sin ninguna revisión) sale con aviso y su lista de palabras sin respaldo en
  `_local_delegate.ungrounded_keys`. El valor no se borra: puede ser una deducción legítima.
- #594: un campo de ubicación que pide la línea de UN título (`local_extract_section_heading_line`)
  y recibe el esquema de encabezados entero se recorta por programa al único encabezado que nombra
  el campo (o, si no hay uno solo, se avisa); y «Título: línea 1» sobre un encabezado ya no se marca
  como línea dudosa.

El prompt de `local_extract` NO cambia (ver Non-goals): los cambios son post-proceso del servidor.

## Requirements

- **REQ-001** — Tras normalizar claves, marcadores (#591) y recuentos, cada valor de primer nivel que
  es una cadena (o una lista de cadenas, con o sin nulos) de como mucho 8 palabras, de un campo que no es de
  ubicación ni se recontó, se compara con la entrada entera, sin mayúsculas ni tildes: una palabra
  del valor de solo letras, con 5+ letras (`PREMISE_STEM_LEN`, el umbral de `unsupported_premises`)
  y que no es una palabra de enlace ni una respuesta normalizada (`ninguno`, `nothing`, `false`…), tiene respaldo si es una palabra de la entrada, su
  singular (sin `s`/`es` final) lo es, o aparece dentro del texto de la entrada; de una entrada JSON cuentan también sus cadenas y claves decodificadas (un acento escapado no es otra palabra). Números y palabras
  cortas no se comprueban: se reformatean (`1.000`, `127.0.0.1`) o son respuestas normalizadas
  (`none`, `Mac`), y cuatro tests existentes fijan que esos valores salen sin `_local_delegate`. El campo con alguna palabra sin respaldo entra en
  `_local_delegate.ungrounded_keys` (`{campo: [palabras]}`) y `warning` lleva el aviso es/en
  `mcp.warning.extract_ungrounded_keys`, añadido tras los avisos anteriores con `; ` (su texto no cambia; el de `lines_unverified` sigue yendo el último).
  El valor se devuelve tal cual.
  - Request: "lo mínimo exigible es que un valor sin respaldo en la entrada no salga sin aviso"
  - Verify: test tests/test_extract_field_fidelity.py
- **REQ-002** — No se avisa de: números, booleanos, objetos, textos de más de 8 palabras (resúmenes,
  que parafrasean), valores cuyas palabras están todas en la entrada (aunque sean de otro campo o de
  otra fila) ni valores nulos. Sin ninguna palabra sin respaldo, `_local_delegate` queda como antes.
  - Request: derived: un aviso que salta con valores copiados de la entrada sería ruido y rompería el contrato actual de las extracciones correctas
  - Verify: test tests/test_extract_field_fidelity.py
- **REQ-003** — Con la entrada numerada de un Markdown (#568), un campo de ubicación que pide UN sitio (una palabra en singular: line, heading, title, section, título…, y ninguna en plural: lines, sections, headings…) y cuyo nombre,
  sin las palabras de ubicación (section, heading, line, título, línea…), nombra algo, y cuyo valor
  cita 3+ líneas de encabezados y al menos la mitad del esquema, es una copia del esquema. Si
  un encabezado contiene todas las palabras de ese nombre, iguales o (desde 4 letras) como comienzo de una suya (`intro` → «Introducción»; desempate: el de menos
  palabras de más, único), el valor pasa a `"<encabezado>: N"` (la forma «nombre: línea» que ya entiende `check_values`, sin texto en un idioma) con el texto del encabezado
  sin `#`; si no, el valor se deja. En los dos casos `_local_delegate.outline_copies`
  (`{campo: N | null}`) y `warning` con el aviso es/en `mcp.warning.extract_outline_copies`.
  - Request: "con un campo que pide la línea de un título, devuelve el índice entero de secciones en cada campo"
  - Verify: test tests/test_extract_field_fidelity.py
- **REQ-004** — Un campo de ubicación sin nombre propio o en plural (`sections_with_lines`, `tools_with_lines`) que recibe el
  esquema entero no se toca ni se avisa: es la respuesta pedida.
  - Request: derived: la petición del esquema entero es un uso legítimo de #568
  - Verify: test tests/test_extract_field_fidelity.py
- **REQ-005** — `line_check.check_values`: una cita cuyo nombre son solo palabras genéricas de
  título (título, title, heading, encabezado, cabecera, header) se da por buena si su línea (con la
  tolerancia de siempre) es un encabezado ATX, o, como antes, si la palabra está en esas líneas (`title:` de un front matter); «Título: línea 1» sobre `# Catálogo de tools` ya no
  sale en `lines_unverified`, y «Título: línea 3» sobre una línea que no es encabezado sí.
  - Request: "y marca la línea 1 como dudosa"
  - Verify: test tests/test_extract_field_fidelity.py
- **REQ-006** — Docstring de `local_extract`, `docs/wiki/Tools.md` y CHANGELOG (`[Unreleased]`)
  describen `ungrounded_keys`, `outline_copies` y el límite: un valor copiado de otra fila de la
  entrada no se detecta.
  - Request: "Si una parte no se puede arreglar de forma fiable, que haya un aviso en `_local_delegate` y explícalo"
  - Verify: review diff

## Acceptance scenarios

### Scenario: veredicto inventado

- **Given** el JSON de `gh pr view` con `reviews: []` y un modelo que responde `review_verdict: "positive"`
- **When** se llama a `local_extract` por `path`
- **Then** `review_verdict` sigue siendo `"positive"`, `_local_delegate.ungrounded_keys` es
  `{"review_verdict": ["positive"]}` y `warning` lo nombra

### Scenario: esquema copiado en un campo de un título

- **Given** `docs/wiki/Tools.md` y un modelo que responde el esquema entero a `local_extract_section_heading_line`
- **When** se llama a `local_extract(path=…)`
- **Then** el campo vale `` "`local_extract`: 101" ``, `outline_copies` es `{campo: 101}` y no hay `lines_unverified`

## Edge cases and failure behavior

- Entrada troceada: la comprobación usa el texto entero, no el trozo.
- Valores con prefijo `N| ` (#568): se comprueban ya sin prefijo.
- Escrituras sin espacios (CJK): una palabra larga se acepta si aparece dentro de la entrada.

## Non-functional requirements

- Coste lineal en el tamaño de la entrada (un `findall` y búsquedas de subcadena por palabra); sin
  expresiones con retroceso catastrófico.
- Ningún cambio en las peticiones al backend (prompts, `max_tokens`, schema): las fixtures de
  `tests/fixtures/request_bodies/` y los corpus congelados no cambian.

## Non-goals

- Reforzar el prompt (null para lo que no está, no rellenar con otra clave). Exige declarar una
  frontera en `scripts/build_corpus.py::PROMPT_BOUNDARIES` y regenerar fixtures que hoy comparan
  tests existentes; queda para una decisión aparte (#586 sigue abierto por eso).
- Detectar un valor copiado de otra fila o de otro campo de la entrada (el caso HTML del
  2026-11-08): sus palabras sí están en la entrada; no hay señal fiable por programa.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
