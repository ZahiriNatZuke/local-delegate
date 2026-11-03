# Implementation plan: explain_code: flag answers that confirm an unanchored premise of the question

## Approach

Same shape as #460/#527: a pure function in `line_check.py` (`premise_terms`,
`unsupported_premises`) and one more warning in `server._verified_lines`, which already runs only
with `path` and a question, on the single call and on the chunked one. Discriminating signal:
(1) the word is a nominalization of the question (abstract feature/process noun, a cognate across
es/en), (2) its first 5 letters (folded) are not in the file, (3) the answer uses it in a sentence
with no negation and (4) no anchor (verified cited line or identifier in the file).

## Ordered tasks

- [x] T1 — `line_check.premise_terms` / `unsupported_premises` (REQ-001, REQ-002, REQ-003)
  - Files or modules: src/local_delegate/line_check.py
  - Verification: tests/test_explain_code_premise.py (pure cases, mutants)
  - Depends on: none
- [x] T2 — warning in `_verified_lines` + i18n es/en + CHANGELOG (REQ-001, REQ-004)
  - Files or modules: src/local_delegate/server.py, resources/i18n/{es,en}/mcp.json, CHANGELOG.md
  - Verification: tool tests with fake backend in tests/test_explain_code_premise.py
  - Depends on: T1

- [x] T3 — per-word denial, cognate in the answer, space after the colon (REQ-005)
  - Files or modules: src/local_delegate/line_check.py, resources/i18n/{es,en}/mcp.json
  - Verification: tests/test_explain_code_premise.py (#553 real answer, mutants)
  - Depends on: T1

## Test strategy

- Unit: GOOD/BAD/OTHER_GOOD sets; the #507 review set measured (0/26 warned).
- Integration: `local_explain_code` with fake `_run_chat`, es and en.
- End-to-end or manual: live run with the real backend by the main session after merge.
- Security and secret scanning: no new inputs, no secrets; ruff.

## Migration and compatibility

- Additive warning; no API change.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
