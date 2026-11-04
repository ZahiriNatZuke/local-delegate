# Specification: Price watcher reads the two Haiku 5.5 price tiers (#564)

## Summary

The weekly price watcher (`scripts/price_watcher.py prices`) has failed since 2026-10-19 with
«celda de precio ilegible en claude-haiku-5-5 / input». On the live page (read 2026-11-04) Claude
Haiku 5.5 takes two rows: the name cell has `rowSpan="2"`, the input cell of the first row adds
«for prompts up to 100,000 tokens», and the second row has no name cell and says «over 100,000
tokens». After this change the watcher reads both rows: the first as the model entry, the second
as the `long_prompt` tier that `prices.json` gained in #563. Running the pure steps against the
live page also showed two more drifts that stop the job: the web search sentence now reads «$10
USD per 1,000 searches», and Claude Mythos 5.1 / 5 are marked «Verification required» instead of
«Invite only». Both are handled.

Depends on #563 (the `long_prompt` key of `prices.json`): branch created from it.

## Requirements

- **REQ-001** — `extract_price_table` returns the Haiku 5.5 base prices in `models` and its
  `{"above_tokens": 100000, ...}` tier in `long_prompt`; a page without tiered models returns no
  `long_prompt` key, and the other rows are read as before.
  - Request: "reads the two Haiku 5.5 tiers ... and proposes the base entry and the long_prompt tier"
  - Verify: test `test_the_two_rows_give_the_base_entry_and_the_long_tier`, `test_a_page_without_tiers_has_no_long_prompt_key`
- **REQ-002** — A cell that cannot be read still stops the job with a message naming the model and
  the field; a missing second row, a table that ends after the first row, mismatching thresholds
  or a first row that does not say «up to» stop it too.
  - Request: "An unreadable cell must still fail with a clear message"
  - Verify: test `test_a_broken_tier_fails_with_a_clear_message`, `test_a_missing_second_row_fails`, `test_a_table_that_ends_after_the_first_row_fails`
- **REQ-003** — `compare` reports new or changed tiers, `updated_table` writes them (never deletes
  a tier the page lost), `serialize_prices` keeps the tier on one line and the PR body lists it.
  - Request: "extract_price_table/compare/updated_table know long_prompt"
  - Verify: test `test_compare_and_update_the_long_tier`, `test_the_serialised_table_keeps_the_tier_on_one_line`
- **REQ-004** — The web search price is read with or without «USD»; rows marked «Verification
  required» are ignored like «Invite only» (both rows when tiered).
  - Request: "Check locally that the script runs green against the real page"
  - Verify: test `test_the_web_search_price_with_usd`, `test_an_ignored_tiered_model_skips_its_second_row`; cmd live run
- **REQ-005** — Existing watcher tests stay untouched and green.
  - Request: derived: brief rule «tests existentes intactos»
  - Verify: cmd `pytest tests/test_price_watcher.py`

## Acceptance scenarios

### Scenario: the live page

- **Given** the live pricing page of 2026-11-04 and the package table of #563
- **When** the pure steps of the price job run (extract, compare, update, serialize)
- **Then** no error, and the only proposed change is Sonnet 5.5 cache read 0.20 → 0.10

## Edge cases and failure behavior

- A tiered model that is ignored skips its second row without reading it.
- A name cell spanning more than two rows stops the job.

## Non-functional requirements

- Standard library only (existing guard test).

## Non-goals

- Deciding the Sonnet 5.5 cache-read price (the watcher will propose it; the session decides).
- Running the GitHub side of the job locally (it would push a branch and open a PR).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
