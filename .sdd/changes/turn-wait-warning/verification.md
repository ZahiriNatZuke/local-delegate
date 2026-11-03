# Verification: Visible common-turn wait warning

## Environment

- Revision: branch `fix/turn-wait-warning` from `origin/main` 6eea8660
- Relevant runtime and tool versions: Python from the repo `.venv`, `PYTHONPATH=src` (worktree), Windows 11

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test tests/test_turn_wait_notice.py (text notice, real MCP call to `local_classify`, texts es/en) | pass | 18 passed; positive control: without `_install_turn_wait_notice()` the MCP tests fail on the missing notice |
| REQ-002 | test tests/test_turn_wait_notice.py (0, 30 s, 59.5 s, no token, `0` disables, MCP call with 10 s) | pass | answer identical; boundary mutant `<=` makes `test_exactly_the_threshold_counts` fail |
| REQ-003 | test tests/test_turn_wait_notice.py (dict with/without previous warning, real MCP `local_extract`) | pass | `turn_wait` added, existing `warning` kept, JSON text block equals structured content |
| REQ-004 | test tests/test_turn_wait_notice.py::test_every_registered_tool_is_wrapped_once | pass | every registered tool wrapped exactly once; second install is a no-op |
| REQ-005 | test tests/test_turn_wait_notice.py::test_env_variable_sets_the_threshold | pass | fresh process: default 60, `15` and `0` read from `LOCAL_DELEGATE_TURN_WAIT_NOTICE_S` |
| REQ-006 | review README.md, docs/wiki/Troubleshooting.md, docs/wiki/Configuration.md | pass | burst section in README, env row in README and Configuration, measured case in Troubleshooting |
| REQ-007 | review CHANGELOG.md | pass | entry under `[Unreleased]` / Añadido with `(#537)` |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest tests/test_turn_wait_notice.py | yes | pass | 18 passed |
| pytest -q -n 4 --dist loadgroup (full suite, with the machine lock) | yes | see PR | full-suite summary in the PR |
| ruff check src tests | yes | pass | All checks passed |
| ruff format --check (touched files) | yes | pass | already formatted |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- The wrapper replaces `Tool.fn` through `mcp._tool_manager` (SDK-internal, already used by the
  tests). An SDK upgrade that renames it breaks `test_every_registered_tool_is_wrapped_once` and the
  MCP tests loudly, not silently.
- Live check with the real backend is left to the main session after merge.
