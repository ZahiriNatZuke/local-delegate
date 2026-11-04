# Verification: Price watcher reads the two Haiku 5.5 price tiers (#564)

## Environment

- Revision: branch `fix/price-watcher-tiered-prices` on top of `fix/prices-claude-5-and-unpriced-models` (#565)
- Relevant runtime and tool versions: Python 3.11 (uv), pytest, ruff

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests `test_the_two_rows_give_the_base_entry_and_the_long_tier`, `test_a_page_without_tiers_has_no_long_prompt_key` | pass | mutant W1 (no tier rows) fails them |
| REQ-002 | tests `test_a_broken_tier_fails_with_a_clear_message` (5 cases), `test_a_missing_second_row_fails`, `test_a_table_that_ends_after_the_first_row_fails` | pass | mutants W4, W5, W6, W10 each fail their test |
| REQ-003 | tests `test_compare_and_update_the_long_tier`, `test_the_serialised_table_keeps_the_tier_on_one_line` | pass | mutants W2, W3, W9 fail them |
| REQ-004 | tests `test_the_web_search_price_with_usd`, `test_an_ignored_tiered_model_skips_its_second_row`; live run | pass | mutants W7, W8 fail them; live page: 14 models, `long_prompt` for Haiku 5.5, only change proposed Sonnet 5.5 cache read 0.2 → 0.1 |
| REQ-005 | `pytest tests/test_price_watcher.py` | pass | 46 existing tests green, file untouched |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `uv run ruff check .` | yes | pass | All checks passed |
| `uv run ruff format --check .` | yes | pass | 438 files already formatted |
| `pytest -n 2` on watcher, pricing, unpriced-check and name-detector tests | yes | pass | 116 passed |
| live pure steps (`extract_price_table` → `compare` → `updated_table` → `serialize_prices`) on the live page | yes | pass | no `WatcherError`; diff only on Sonnet 5.5 `cache_read` |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- The code was written in the same session right before the spec and plan gates were recorded
  (the request came mid-task); spec and plan describe what was built and were reviewed after.
- The full suite was not rerun for this branch: only `scripts/price_watcher.py`, its new test and
  the lexicon changed; CI runs the full suite.
- `python3 scripts/price_watcher.py prices` was not run as is: without `GITHUB_TOKEN` it stops, and
  with it it would push a branch and open a PR. The pure steps were run instead.
- Once merged, the watcher will open a PR proposing Sonnet 5.5 cache read 0.20 → 0.10 (page
  value); Claude Code's own `costUSD` uses 0.20 on this PC, so that PR needs a human decision.

## Final result

- Merged in `main` as `2ef5cf44` (PR #566, closes #564).
- PR checks: 22 of 22 green (`gh pr checks 566`: tests on ubuntu/windows/macos, Python 3.11–3.15 matrix, lint, secrets, ci-gate, CodeQL, Socket, GitGuardian).
- `main` CI after the merge: green (`gh run list --branch main`).
- Closed on 2026-11-04 by the closing PR `chore/close-sdd-2026-11-04`.
