# Implementation plan: local_summarize troceado: reintentar una vez las secciones que faltan y nombrarlas en el aviso (#691)

## Approach

- `sections.py`: `retry_targets` (índices que faltan o vacíos, sin los vacíos del documento),
  `merge_retry` (pone lo que trae el reintento en su sitio: inserta las que faltaban, rellena las
  vacías) y `complete(..., name_missing=True)`, que no inserta nada en el cuerpo y nombra los
  títulos en el aviso (claves nuevas `mcp.warning.sections_not_summarized_named[_one]`).
- `server._chat_map_reduce`: parámetro opcional `concat_retry(text) -> (system, user, tokens,
  merge) | None`; en la rama `concat`, si devuelve algo y hay tiempo, un paso `_one(..., "sections_retry")`
  dentro de la misma operación; si falla, `failed = None` y se queda el texto de antes.
- `server._structured_summary`: construye ese `concat_retry` con las secciones objetivo del plan
  (su tramo de `content`, en orden, mientras quepan en `_map_budget`), y pasa a `_complete` el
  modo `name_missing` solo en el camino troceado.

## Ordered tasks

- [x] T1 — Tests rojos con backend falso troceado (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005)
  - Files or modules: tests/test_summarize_retry_missing_sections.py
  - Verification: fallan sin el arreglo
  - Depends on: none
- [x] T2 — `sections.retry_targets`, `merge_retry`, `complete(name_missing=True)` e i18n (REQ-002, REQ-003)
  - Files or modules: src/local_delegate/sections.py, resources/i18n/{es,en}/mcp.json
  - Verification: tests de T1
  - Depends on: T1
- [x] T3 — Paso de reintento en `_chat_map_reduce` y su uso en `_structured_summary` (REQ-001, REQ-004, REQ-005)
  - Files or modules: src/local_delegate/server.py
  - Verification: tests de T1 y suite completa
  - Depends on: T2

## Test strategy

- Unit: `merge_retry` y `complete(name_missing=True)` sobre textos sintéticos.
- Integration: `local_summarize(path=…)` con presupuesto bajo y backend falso que omite secciones
  la primera vez (y la segunda).
- End-to-end or manual: prueba en vivo en proceso dentro de `test-window`.
- Security and secret scanning: `personal-security-check` antes del commit.

## Migration and compatibility

- Aditivo: el camino de una sola llamada y los demás usuarios de `_chat_map_reduce` no cambian
  (el parámetro nuevo es opcional).

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
