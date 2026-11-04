# Verification: A mod decision record is reported as written even when it is not

## Environment

- Revision: branch fix/mod-decision-record-lost on top of 89551158 (0.48.0)
- Relevant runtime and tool versions: Python 3.11.15 (worktree .venv via uv sync --locked), Windows 11

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test_record_ignores_outside_record_or_raise_and_raises_inside; test_a_normal_hook_with_the_same_broken_destination_exits_zero | pass | tests/test_mod_record_lost.py; positive control: without the fix `record_or_raise` is missing (AttributeError) |
| REQ-002 | test_endpoint_answers_500_when_the_line_is_not_written; test_endpoint_still_answers_204_when_written | pass | positive control: without the fix `assert 204 == 500` fires |
| REQ-003 | test_cli_in_process_reports_a_lost_line; test_real_process_exit_codes; installed check (uv tool install into a temp UV_TOOL_DIR, temp HOME) | pass | installed: good=0, folder destination=1, broken JSON=1, prompt hook with the same destination=0; positive control: `assert 0 == 1` fires without the fix |
| REQ-004 | test_cli_in_process_reports_a_lost_line; test_failure_line_keeps_only_short_names | pass | installed hook-failures.jsonl line: hook=record-read, error=PermissionError, decision=summarized, via=read_whole; no path |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| uv run --locked pytest (as .venv/Scripts/python -m pytest -n 2) | yes | pass (see note) | full suite: only failures were test_build_hook sdist (ignored register.js in worktree, known worktree artifact) and the Spanish-name detector, fixed by renaming |
| ruff check / ruff format --check | yes | pass | All checks passed |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [ ] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Record skipped checks, known limitations, and why the evidence is still sufficient or not.

## Final result

- Merged in `main` as `3e826b56` (PR #559).
- PR checks: 22 of 22 green (`gh pr checks 559`: tests on ubuntu/windows/macos, Python 3.11–3.15 matrix, lint, secrets, ci-gate, CodeQL, Socket, GitGuardian).
- `main` CI after the merge: green (`gh run list --branch main`).
- Closed on 2026-11-04 by the closing PR `chore/close-sdd-2026-11-04`.
