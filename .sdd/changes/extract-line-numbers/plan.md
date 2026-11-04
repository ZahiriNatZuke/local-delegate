# Implementation plan: local_extract numera las líneas con path para campos de ubicación (#568)

## Approach

Reutilizar las piezas de #464: `_number_lines` para la llamada única y `_numbered_code_pieces`
(trocea sobre el texto pelado y numera con desplazamiento) para el map, pasándolas como `pieces` a
`_chat_map_reduce`. La decisión de trocear sigue sobre el texto sin numerar (como #464). Lo puro
(criterio de campo, esquema Markdown, comprobación de valores) va a `line_check.py`.

## Ordered tasks

- [x] T1 — Criterio de campo de ubicación y esquema Markdown en `line_check.py` (REQ-002, REQ-004)
  - Files or modules: src/local_delegate/line_check.py
  - Verification: tests unitarios
  - Depends on: none
- [x] T2 — Numeración, cláusula de system, esquema y reduce en `local_extract` (REQ-001, REQ-004)
  - Files or modules: src/local_delegate/server.py
  - Verification: backend falso que captura los prompts
  - Depends on: T1
- [x] T3 — Quitar prefijos de campos no de ubicación y comprobar líneas citadas (REQ-003, REQ-005)
  - Files or modules: src/local_delegate/server.py, line_check.py, i18n es/en mcp.json
  - Verification: tests con respuestas falsas
  - Depends on: T2
- [x] T4 — Skill es/en y CHANGELOG (REQ-006)
  - Files or modules: resources/skills/local-delegation/SKILL*.md, CHANGELOG.md
  - Verification: review
  - Depends on: T2

## Test strategy

- Unit: `tests/test_extract_line_numbers.py` con backend falso (`_run_chat` doblado), Markdown sintético.
- Integration: suite completa con `pesado.sh`.
- End-to-end or manual: opcional, prueba en vivo con `test-window`.
- Security and secret scanning: GitGuardian en el PR.

## Migration and compatibility

- Sin campos de ubicación o con `text=`, nada cambia. El esquema JSON no cambia; `_local_delegate`
  gana la clave opcional `lines_unverified`.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
