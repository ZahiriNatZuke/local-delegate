# Implementation plan: llama-swap: un solo lector del cmd

## Approach

`_parse_cmd_flags` becomes a thin adapter over `footprint.cmd_flags` (the package's single `cmd`
parser, already imported by `llamaswap_config`): it keeps its `dict[str, str]` shape with the keys
present, so its callers (`parse_model_gguf_path`, `estimate_model_vram`, `_context_sizes`) do not
change. The `isdigit` check that turns a macro into the estimate stays.

## Ordered tasks

- [x] T1 — Tests first: `=`, quotes, spaces, macro, short form, agreement with footprint (REQ-001, REQ-002, REQ-003)
  - Files or modules: tests/test_model_context_size.py, tests/test_llamaswap_config.py
  - Verification: the new tests fail on the base commit by their asserts
  - Depends on: none
- [x] T2 — `_parse_cmd_flags` delegates to `footprint.cmd_flags` (REQ-001, REQ-002, REQ-003)
  - Files or modules: src/local_delegate/llamaswap_config.py, CHANGELOG.md
  - Verification: area tests and full suite
  - Depends on: T1
- [x] T3 — Check that doctor and local_status already flag the estimate (REQ-004)
  - Files or modules: none (read only)
  - Verification: existing tests of `context_estimated`
  - Depends on: none
- [x] T4 — After review: last of the short and long form wins; only ASCII digits are integers (REQ-001, REQ-003)
  - Files or modules: src/local_delegate/footprint.py, tests/test_model_context_size.py
  - Verification: 4 of the 5 new cases fail without the footprint change
  - Depends on: T2

## Test strategy

- Unit: parser and `model_context_size` with a temporary config.
- Integration: `estimate_model_vram` with a quoted path to a real temporary file.
- End-to-end or manual: none (no backend call, no prompt change).
- Security and secret scanning: pre-commit hooks.

## Migration and compatibility

- Same function signatures; only values that were wrong change.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
