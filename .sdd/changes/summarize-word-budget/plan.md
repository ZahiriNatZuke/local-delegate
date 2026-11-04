# Implementation plan: local_summarize corta el resumen a mitad de frase con el max_words por defecto (#580)

## Approach

Un helper `_summary_max_tokens(words)` (3w+64) en `server.py`, usado por la llamada única de
`local_summarize` y pasado como `max_tokens_for` a su `_chat_map_reduce`. El recorte vive en
`sections.trim_to_last_sentence` (puro, testeable) y `_chat` gana un parámetro opcional
`trim_cut`: solo con `finish_reason == length`, antes del postproceso, y cambia el aviso a la
variante «recortado» cuando de verdad recorta. Sin `trim_cut` (todas las demás llamadas) nada cambia.

## Ordered tasks

- [x] T1 — `_summary_max_tokens` y uso en la llamada única y el map/reduce (REQ-001, REQ-002)
  - Files or modules: src/local_delegate/server.py
  - Verification: tests nuevos que miran el `max_tokens` enviado
  - Depends on: none
- [x] T2 — `trim_to_last_sentence` y `trim_cut` en `_chat`, aviso es/en (REQ-003, REQ-004)
  - Files or modules: src/local_delegate/sections.py, server.py, resources/i18n/{es,en}/mcp.json
  - Verification: tests de recorte (frase, lista, título colgando, código, sin frontera)
  - Depends on: T1
- [x] T3 — Tests, control positivo, suite completa y CHANGELOG (REQ-005)
  - Files or modules: tests/test_summarize_word_budget.py, CHANGELOG.md
  - Verification: pytest completo, ruff
  - Depends on: T2

## Test strategy

- Unit: `trim_to_last_sentence` con casos de Markdown.
- Integration: `local_summarize` contra backend falso (respx) con `stop` y `length`.
- End-to-end or manual: medición previa contra el backend real en ventana de prueba.
- Security and secret scanning: sin datos del usuario en el repo; el log real solo se leyó.

## Migration and compatibility

- Corpus versionado: `local_summarize` ya está declarado en `PROMPT_BOUNDARIES` (0.36.0) para
  `max_tokens`; el cambio sale como aviso, no como error.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
