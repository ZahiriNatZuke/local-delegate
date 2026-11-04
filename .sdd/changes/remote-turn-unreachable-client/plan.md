# Implementation plan: Turno remoto inalcanzable: en serie, corte y aviso (#577)

## Approach

- `remote_turn.py`: un sitio «a ciegas» por URL (`hold_blind`/`release_blind`, condición con
  sondeo corto, cancelable, sale con `BlindCut` si el corte se abre) y recomprobar `remembered` en
  cada vuelta de `RemoteLease.acquire`.
- `cooldown.py`: `remote_turn_cut()`, otro `CooldownState` como `backend_breaker()`, que cuenta
  `read_timeout` y `capacity_or_load`, con su fichero y su registro de eventos.
- `config.py`: `LOCAL_DELEGATE_REMOTE_TURN_CUT`, `_FAILURES` (1), `_S` (120), `_MAX_S` (600).
- `server.py`: `_OperationTurn._remote_grant` toma el sitio a ciegas con `unreachable` (o lanza
  `RemoteTurnDown` con el corte abierto); `release_slot` lo suelta; `note_attempt` alimenta el
  corte; `_with_fallback.call` añade la nota al error; un turno concedido cierra el corte;
  `_log_aborted` registra `remote_turn_unreachable`.
- i18n es/en; README, `docs/wiki/Configuration.md` y CHANGELOG.

## Ordered tasks

- [x] T1 — Sitio a ciegas y recomprobación en `acquire` (REQ-001, REQ-005)
  - Files or modules: src/local_delegate/remote_turn.py
  - Verification: tests nuevos
  - Depends on: none
- [x] T2 — Corte de turno remoto y su config (REQ-002)
  - Files or modules: src/local_delegate/cooldown.py, src/local_delegate/config.py
  - Verification: tests nuevos
  - Depends on: none
- [x] T3 — Integración en la operación, error con nota y evento (REQ-001, REQ-002, REQ-003, REQ-004, REQ-006)
  - Files or modules: src/local_delegate/server.py, resources/i18n/{es,en}/mcp.json
  - Verification: tests nuevos con turno y backend falsos
  - Depends on: T1, T2
- [x] T4 — Docs, CHANGELOG y suite completa (REQ-007)
  - Files or modules: README.md, docs/wiki/Configuration.md, CHANGELOG.md
  - Verification: pytest completo, ruff
  - Depends on: T3

## Test strategy

- Unit: sitio a ciegas (serie, cancelación, corte), corte (abre/cierra), recomprobación.
- Integration: `_OperationTurn` + `_with_fallback` con turno falso que no responde y `_post_chat`
  falso lento o con `read_timeout`; tool real (`local_classify`) para el evento.
- End-to-end or manual: script fuera de pytest con log temporal y backend/turno falsos.
- Security and secret scanning: ruff, CodeQL y GitGuardian en el PR.
- Control positivo: cada test nuevo falla con el arreglo revertido.

## Migration and compatibility

- Aditivo: dos ficheros nuevos en `LOG_DIR`; variables nuevas con valores por defecto.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
