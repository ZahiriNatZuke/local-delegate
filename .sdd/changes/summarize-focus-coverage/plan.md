# Implementation plan: local_summarize: el enfoque llega a la sección que lo trata, o avisa

## Approach

Tres funciones puras en `sections` (`focus_terms`, `focus_terms_in`, `focus_sections`) y su uso en
`server.local_summarize`: una nota en el mensaje de usuario de cada llamada (calculada sobre el
texto de esa llamada) y un aviso en el `postprocess`, que corre antes del recibo y nunca en error.
En el camino estructurado el aviso se calcula sobre el texto del modelo antes de `sections.complete`.

## Ordered tasks

- [x] T1 — Términos del foco, secciones que los tratan y nota en el mensaje de usuario (REQ-001, REQ-003)
  - Files or modules: src/local_delegate/sections.py, src/local_delegate/server.py
  - Verification: tests del prompt con backend falso; sin foco, prompt idéntico
  - Depends on: none
- [x] T2 — Aviso es/en cuando el resumen no menciona el foco (REQ-002)
  - Files or modules: src/local_delegate/server.py, resources/i18n/{es,en}/mcp.json
  - Verification: tests de extremo a extremo con backend falso; control positivo
  - Depends on: T1
- [x] T3 — CHANGELOG (REQ-004)
  - Files or modules: CHANGELOG.md
  - Verification: revisión
  - Depends on: T2

## Test strategy

- Unit: `focus_terms`, `focus_terms_in`, `focus_sections`.
- Integration: `local_summarize` con backend falso en los caminos prosa y estructurado, llamada
  única y troceada.
- End-to-end or manual: reproducción en vivo con la 0.48.0 (test-window) para confirmar el síntoma.
- Security and secret scanning: el foco ya va saneado; la nota solo cita títulos de la entrada.

## Migration and compatibility

- Sin foco nada cambia. Con foco, el mensaje de usuario gana una línea solo si hay secciones que
  casan; la salida gana un aviso solo en el fallo.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
