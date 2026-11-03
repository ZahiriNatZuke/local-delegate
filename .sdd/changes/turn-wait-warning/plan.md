# Implementation plan: Visible common-turn wait warning

## Approach

The call's token (`cancellation.Token.turn_wait_ms`) already sums every turn wait of the call. A
wrapper (`_with_turn_wait_notice`) reads it when the tool returns and adds the notice to the result:
a `WARNING_MARKER` line for `str`, `_local_delegate.turn_wait` (+ `warning` via `setdefault`) for
`dict`. It is installed once, after all tools are registered, by replacing each registered tool's
`fn` with the wrapped one (`mcp._tool_manager.list_tools()`, already used by the tests). The schema
was built at registration, so it does not change. This leaves the tool bodies and decorators
untouched, which keeps the conflict with today's other PRs minimal, and needs no per-tool code.
Rejected: rewriting the result in `cancellation.middleware` (it would have to edit
`structuredContent` and the JSON text block, which the mod parses); a decorator on every tool
(touches lines other PRs change).

## Ordered tasks

- [x] T1 — Threshold in config + i18n texts (REQ-005, REQ-001)
  - Files or modules: src/local_delegate/config.py, resources/i18n/{es,en}/mcp.json
  - Verification: tests/test_turn_wait_notice.py
  - Depends on: none
- [x] T2 — Wrapper and its installation over every tool (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: src/local_delegate/server.py
  - Verification: tests/test_turn_wait_notice.py, positive control (revert -> fails)
  - Depends on: T1
- [x] T3 — Tests (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005)
  - Files or modules: tests/test_turn_wait_notice.py
  - Verification: pytest
  - Depends on: T2
- [x] T4 — Docs and CHANGELOG (REQ-006, REQ-007)
  - Files or modules: README.md, docs/wiki/Troubleshooting.md, docs/wiki/Configuration.md, CHANGELOG.md
  - Verification: review
  - Depends on: T2

## Test strategy

- Unit: wrapper with a fake token (`turn_wait_ms` injected, no sleeping) above/below/at threshold,
  str and dict results, env override and `0`.
- Integration: every registered tool's `fn` is wrapped; a real tool (`local_classify`) through the
  wrapper with an injected token gets the notice.
- End-to-end or manual: live check after merge by the main session.
- Security and secret scanning: no secrets involved; personal-security-check before commit.

## Migration and compatibility

- Describe compatibility boundaries, data migration, and rollout considerations.

## Plan review

- [ ] Every requirement maps to at least one task and verification step.
- [ ] Risky or destructive operations have safeguards and rollback.
- [ ] Dependencies and configuration changes are explicit.
- [ ] The plan does not include unrelated work.
