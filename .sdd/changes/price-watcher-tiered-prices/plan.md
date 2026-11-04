# Implementation plan: Price watcher reads the two Haiku 5.5 price tiers (#564)

## Approach

The table reader records each cell's `rowspan`. `extract_price_table` keeps a `pending` tiered
model: its first row is read with `_read_tier` on the input cell (price + caption «up to N»), the
next row must have one cell less and is read with the column indices shifted by one (no name
cell). `_read_price` keeps failing on any extra text; `_read_tier` accepts only the exact tier
caption. `Changes` gains `long_prompt`; `compare`, `updated_table` and the PR body use it.

## Ordered tasks

- [x] T1 — reader `rowspan`, `_read_tier`, two-row parsing and its failures (REQ-001, REQ-002)
  - Files or modules: `scripts/price_watcher.py`, `tests/test_price_watcher_tiers.py`
  - Verification: test
  - Depends on: none
- [x] T2 — `Changes.long_prompt`, `compare`, `updated_table`, PR body (REQ-003)
  - Files or modules: `scripts/price_watcher.py`, `tests/test_price_watcher_tiers.py`
  - Verification: test
  - Depends on: T1
- [x] T3 — web search «USD» and «Verification required» marker; live run (REQ-004)
  - Files or modules: `scripts/price_watcher.py`
  - Verification: test, cmd
  - Depends on: T1
- [x] T4 — existing tests, lexicon words, CHANGELOG (REQ-005)
  - Files or modules: `scripts/data/spanish_lexicon.json`, `CHANGELOG.md`
  - Verification: cmd
  - Depends on: T1-T3

## Test strategy

- Unit: synthetic two-row block with the live page's shape inserted in the saved page copy.
- Integration: `compare` → `updated_table` → `serialize_prices`.
- End-to-end or manual: pure steps against the live page, without GitHub.
- Security and secret scanning: pre-commit hooks.

## Migration and compatibility

- `long_prompt` only appears in the extracted table when the page has a tiered model.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
