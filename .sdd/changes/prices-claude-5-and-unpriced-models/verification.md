# Verification: Haiku 5.5 price and price check that survives unpriced models (#563)

## Environment

- Revision: branch `fix/prices-claude-5-and-unpriced-models` on top of 69d7027e
- Relevant runtime and tool versions: Python 3.11 (uv), pytest with xdist `-n 2`, ruff

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test `test_haiku_55_prices_from_the_official_page` | pass | prices copied from platform.claude.com/docs/en/about-claude/pricing read 2026-11-04; mutant M1 (no entry) fails it |
| REQ-002 | test `test_haiku_55_row_band_spans_both_tiers`, `test_real_haiku_55_rows_are_inside` | pass | mutant M2 (band without long tier) fails it; read-only run over this PC's transcripts: 10/10 Haiku 5.5 rows inside |
| REQ-003 | test `test_request_cost_uses_the_prompt_tier` | pass | mutant M3 fails it |
| REQ-004 | test `test_unpriced_rows_leave_the_verdict`, `test_outside_rows_by_model` | pass | mutants M4 and M7 fail them |
| REQ-005 | test `test_summary_names_the_unpriced_rows` | pass | mutant M6 fails it |
| REQ-006 | test `test_doctor_ok_with_unpriced_note` | pass | mutant M5 fails it |
| REQ-007 | test `test_outside_rows_by_model`, `test_summary_names_the_unpriced_rows` | pass | `outside_by_model` saved and printed |
| REQ-008 | cmd full pytest suite; test `test_already_priced_models_keep_their_prices` | pass | only `SPEC_IDS` of `test_pricing.py` gained the new id |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `uv run ruff check .` | yes | pass | All checks passed |
| `uv run ruff format --check .` | yes | pass | 435 files already formatted |
| `pytest -n 2 -q` (full suite) | yes | pass with exceptions | 6421 passed, 8 failed: 1 was mine (new English words `official`, `priced`, `tier`, `tiers` unclassified; added to `scripts/data/spanish_lexicon.json`, now green); the other 7 (`test_hook_entry`, `test_read_classifier`, `test_mod_record_lost`, `test_hook_record_read_endpoint`) fail the same with my `src` changes reverted: they launch real processes that import the main checkout's package, the known worktree trap; CI decides them |
| `local-delegate recompute-cost` with `LOCAL_DELEGATE_LOG_DIR` temporary | yes | pass | «Cotejo de precios (2026-11-04): pasa; 222 filas juzgadas, 0 fuera, sin precio: ninguno.»; `_probe_cost` over that log dir: `ok` |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- `tests/test_pricing.py::SPEC_IDS` gained `claude-haiku-5-5`: the inventory test pins the exact
  set of ids, so adding a model requires it. No assertion changed.
- The Mac's 70 outside rows are not Haiku 5.5 rows (the code counts `unpriced` apart); their model
  is unknown without the Mac's log. `outside_by_model` will name it on the next run.
- Sonnet 5.5 cache reads: page says $0.10, table and Claude Code's own `costUSD` use $0.20; left
  unchanged (spec non-goal).
- Price watcher red since 2026-10-19 on Haiku 5.5 tier rows: issue #564.

## Final result

- Merged in `main` as `f0ecb390` (PR #565, closes #563).
- PR checks: 22 of 22 green (`gh pr checks 565`: tests on ubuntu/windows/macos, Python 3.11–3.15 matrix, lint, secrets, ci-gate, CodeQL, Socket, GitGuardian).
- `main` CI after the merge: green (`gh run list --branch main`).
- Closed on 2026-11-04 by the closing PR `chore/close-sdd-2026-11-04`.
