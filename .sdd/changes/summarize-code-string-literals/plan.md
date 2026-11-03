# Implementation plan: local_summarize: no sacar secciones de las cadenas de un fichero de código

## Approach

La causa está en nuestro código (`sections.detect` + `sections.complete` sobre un fichero de
código), así que se corta en la entrada: `local_summarize` no toma el camino estructurado con un
`path` de código (reutiliza la tabla de extensiones de `cost`). Encima, una guarda pura en
`sections` (`string_literal_headings`) escanea los literales de cadena multilínea del fuente y
compara sus líneas normalizadas con los títulos de la salida; `server` añade el aviso. Sin cambios
de prompt.

## Ordered tasks

- [x] T1 — Saltar el resumen estructurado con `path` de código (REQ-001)
  - Files or modules: src/local_delegate/server.py
  - Verification: test del prompt con backend falso
  - Depends on: none
- [x] T2 — Guarda de títulos copiados de cadenas y su aviso es/en (REQ-002, REQ-003)
  - Files or modules: src/local_delegate/sections.py, src/local_delegate/server.py, resources/i18n/{es,en}/mcp.json
  - Verification: tests unitarios y de extremo a extremo con backend falso; control de falsos positivos con .md
  - Depends on: T1
- [x] T3 — CHANGELOG (REQ-004)
  - Files or modules: CHANGELOG.md
  - Verification: revisión
  - Depends on: T2

## Test strategy

- Unit: `string_literal_headings` con JS, Python y Markdown.
- Integration: `local_summarize` con backend falso (`_chat` capturado) sobre un `.mjs` sintético y un `.md`.
