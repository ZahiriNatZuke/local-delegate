# Specification: local_extract numera las líneas con path para campos de ubicación (#568)

## Summary

`local_extract` con `path` puede devolver números de línea reales en los campos que los piden, en
una llamada o troceado, sin ensuciar los demás campos, y avisa de las líneas citadas que no casan.

## Requirements

- **REQ-001** — Con `path` y al menos un campo de ubicación, el contenido que ve el modelo (llamada
  única y cada trozo del map) lleva `N| ` con el número ABSOLUTO de línea del fichero, y el system
  explica el prefijo.
  - Request: "Con `path`, `local_extract` numera las líneas que ve el modelo (con el desplazamiento real en cada trozo)"
  - Verify: test tests/test_extract_line_numbers.py
- **REQ-002** — Campo de ubicación: criterio determinista y estrecho por el nombre del campo,
  separado en palabras (camelCase, `_`, `-`, espacios) sin acentos ni mayúsculas: una palabra
  lines/lineas/lineno/linenos (salvo junto a num/number/numero/code), o line/linea junto a
  number/numero/num/no/start/end/inicio/fin/range/rango/heading/section/title/titulo/seccion/
  encabezado. Una palabra de cantidad (count, total, added, removed, changed, loc, cantidad,
  modificadas…) lo descarta. `location`, `position`, `offset`, `price_range`, `line_items`,
  `lines_added` no cuentan (revisión: falsos positivos en datos corrientes). Sin campo de ubicación, o con `text=`, los prompts quedan
  byte a byte como antes.
  - Request: "numera solo cuando algún campo pida líneas/secciones/ubicación (decide un criterio determinista y documéntalo)"
  - Verify: test tests/test_extract_line_numbers.py
- **REQ-003** — Con numeración, un `N| ` copiado al principio de una línea en el valor de un campo
  que no es de ubicación se quita en el servidor.
  - Request: "los números no deben contaminar los VALORES de los campos que no son de localización"
  - Verify: test tests/test_extract_line_numbers.py
- **REQ-004** — Con numeración y un Markdown (`.md`, `.markdown`, `.mdx`) con encabezados ATX fuera de bloques de código, cada
  prompt lleva el esquema `línea: encabezado` calculado por programa, si cabe en el 15 % del
  presupuesto del trozo; si no cabe, no se añade.
  - Request: "Para Markdown, si es barato y determinista: añadir al contexto de cada trozo [...] el esquema de encabezados con su línea"
  - Verify: test tests/test_extract_line_numbers.py
- **REQ-005** — Las líneas citadas en los campos de ubicación se comprueban contra el fichero: una
  fuera del fichero, o cuyo entorno (±1 línea) no contiene ninguna palabra del elemento que la
  cita (las de justo antes de la cita), va en `_local_delegate.lines_unverified` con un aviso
  añadido a los anteriores. Con una cita explícita (`líneas N`, `LN`, `N|`) no se buscan rangos
  ni `: N` sueltos. Al trocear, los campos de ubicación los une el programa desde los parciales
  (el reduce los deja a null), y un reduce cortado no los pierde.
  - Request: "Si el modelo cita líneas, compruébalas en el servidor como en #464 (aviso si no casan)"
  - Verify: test tests/test_extract_line_numbers.py
- **REQ-006** — La skill (es/en) dice que con `local_extract` el nombre del campo debe pedir líneas.
  - Request: "Revisa el texto de la skill/bloque [...] y ajústalo si tras el arreglo no es verdad para algún caso"
  - Verify: review diff de SKILL.md y SKILL.en.md

## Acceptance scenarios

### Scenario: Markdown grande troceado

- **Given** un Markdown de ~60 secciones `###` y >48 K chars
- **When** `local_extract(path=..., fields=["componentes", "secciones_con_lineas"])`
- **Then** cada trozo enviado al backend lleva sus líneas reales y el esquema de encabezados

## Edge cases and failure behavior

- Valor de ubicación sin palabras que comprobar: no se verifica (ni bien ni mal).
- Número mayor que el total de líneas: siempre inválido.

## Non-functional requirements

- Determinista, sin llamadas extra al modelo.

## Non-goals

- Tool `local_locate`; esquema en el recibo; numerar `text=`.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
