# Specification: local_summarize: no sacar secciones de las cadenas de un fichero de código

## Summary

`local_summarize` sobre un fichero de código no promociona a títulos del resumen las líneas de
sus cadenas de texto, y avisa cuando el modelo lo hace por su cuenta.

## Requirements

- **REQ-001** — Con `path` de extensión de código (la clase `code` de `cost.CLASS_BY_EXTENSION`),
  `local_summarize` no toma el camino estructurado aunque el texto tenga títulos Markdown y el rol
  sea `long`: el prompt es el de prosa de siempre y no se insertan títulos.
  - Request: "no tratar como encabezados las líneas de un fichero de código (por extensión conocida de código)"
  - Verify: test tests/test_summarize_code_string_literals.py
- **REQ-002** — Si un título del resumen reproduce literalmente una línea del fuente que está dentro
  de un literal de cadena multilínea (template literal de JS o cadena triple de Python), o, en un
  fichero de código, una línea con una interpolación `${…}` sin resolver, la salida lleva un aviso
  `[local-delegate warning: …]` que nombra esos títulos.
  - Request: "Guarda determinista de salida: si un encabezado del resumen reproduce literalmente una línea del fuente que está dentro de un literal de cadena"
  - Verify: test tests/test_summarize_code_string_literals.py
- **REQ-003** — Un resumen correcto de un `.md` real (con sus títulos, acentos graves de código en
  línea y vallas) no lleva ese aviso.
  - Request: "Que no avise en un resumen correcto de un .md real (control de falsos positivos)"
  - Verify: test tests/test_summarize_code_string_literals.py
- **REQ-004** — El cambio queda en el CHANGELOG `[Unreleased]` → Fixed con (#539).
  - Request: "CHANGELOG `[Unreleased]` → «Fixed»"
  - Verify: review CHANGELOG.md

## Acceptance scenarios

### Scenario: el fichero del issue

- **Given** un `.mjs` sintético de más de 6000 caracteres con un template literal con `## Specs`,
  `## Tasks`, `## Log` y `campo: ${variable}` + `---`
- **When** se llama a `local_summarize(path=…)` con un backend falso
- **Then** el prompt no lleva «Secciones, en orden» y la salida no gana títulos insertados

### Scenario: el modelo copia la cadena igual

- **Given** el mismo fichero y un backend que responde con `## Specs` como título
- **Then** la salida lleva el aviso con `Specs`

## Edge cases and failure behavior

- Si la respuesta es un error (`[local-delegate error]`), no se añade aviso.
- Texto en línea (sin `path`) que es código: sigue el camino de hoy, pero la guarda de literales
  multilínea sí avisa.

## Non-functional requirements

- Guarda pura, sin red ni disco; coste lineal en el tamaño del fuente.

## Non-goals

- Cambiar prompts, cambiar `detect` para texto en línea.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
