# Specification: Visible common-turn wait warning

## Summary

A tool call that waited for the common turn at least a threshold (60 s by default) carries, in its
answer, a notice that says how long it waited, that it was the queue of other delegations and not
the model's speed, and that grouping calls by tool reduces it. Shorter waits add nothing.

## Requirements

- **REQ-001** — A text tool whose call waited for the turn at least the threshold ends its answer
  with a `[local-delegate warning: ...]` line that states the seconds waited, that it was the queue of
  other delegations (not the model), and that grouping calls by tool reduces it.
  - Request: "Aviso en `_local_delegate` cuando la espera del turno común supere un umbral"
  - Verify: test tests/test_turn_wait_notice.py
- **REQ-002** — Below the threshold (including no wait at all) the answer is byte-for-byte what it
  is today.
  - Request: "que no aparezca aviso en el caso normal"
  - Verify: test tests/test_turn_wait_notice.py
- **REQ-003** — `local_extract` (JSON) carries the notice inside `_local_delegate`: a `turn_wait`
  object (`seconds`, `notice`), and `warning` only if no other warning is there (an existing warning
  keeps its exact text). Its data fields are untouched.
  - Request: "Combínalo con los avisos existentes siguiendo el patrón actual (no pises otro `warning`)"
  - Verify: test tests/test_turn_wait_notice.py
- **REQ-004** — The notice is applied once, for every registered tool, without per-tool code.
  - Request: "Que valga para todas las tools que pasan por el turno, sin duplicar código por tool"
  - Verify: test tests/test_turn_wait_notice.py
- **REQ-005** — The threshold is a named constant, overridable by `LOCAL_DELEGATE_TURN_WAIT_NOTICE_S`
  (seconds, default 60, `0` disables), documented with the other env variables.
  - Request: "constante con nombre, y una variable de entorno solo si el repo ya tiene ese patrón"
  - Verify: test tests/test_turn_wait_notice.py
- **REQ-006** — README and `docs/wiki/` explain that a burst mixing tools of different models can
  wait minutes for the turn, that Claude Code moves the call to the background and the result still
  arrives, and that grouping by tool reduces it.
  - Request: "Documentación: README ... y `docs/wiki/`"
  - Verify: review README.md docs/wiki/Troubleshooting.md docs/wiki/Configuration.md
- **REQ-007** — CHANGELOG `[Unreleased]` has the entry with `(#537)`.
  - Request: "CHANGELOG `[Unreleased]` ... con `(#537)`"
  - Verify: review CHANGELOG.md

## Acceptance scenarios

### Scenario: long turn wait

- **Given** a call whose token accumulated `turn_wait_ms` = 292000
- **When** the tool returns its text
- **Then** the text ends with the notice saying 292 s

### Scenario: normal call

- **Given** a call with no turn wait, or 30 s
- **When** the tool returns
- **Then** the answer is unchanged

## Edge cases and failure behavior

- A tool that raises keeps raising; nothing is added.
- A result that is neither `str` nor `dict` passes through unchanged.
- No call token (direct call outside the MCP middleware): nothing is added.
- Building the notice must never break the tool: any failure returns the original result.

## Non-functional requirements

- Spanish and English texts in the i18n catalog.
- Minimal diff in `server.py` (other PRs touch the tool bodies today).

## Non-goals

- Changing turn fairness or the progress heartbeat.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
