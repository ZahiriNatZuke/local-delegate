# Specification: Haiku 5.5 price and price check that survives unpriced models (#563)

## Summary

`local-delegate recompute-cost` compares the package price table with what Claude Code charges
(`cost-state` rows «model × session»). With 0.48.0 a single model missing from the table
(`claude-haiku-5-5`) turned the whole check into `fail` and left `doctor` with a permanent
`[WARN] coste y relleno`. After this change the table prices Claude Haiku 5.5 from the official
pricing page (including its prompt-length tier), and a model that still has no price is reported
apart: its rows leave the check with their own count, and the verdict only depends on priced rows.

Evidence gathered before writing (lite: brief + inspected code):

- Official page `platform.claude.com/docs/en/about-claude/pricing`, read 2026-11-04: Haiku 5.5 is
  $0.10 / $0.125 / $0.20 / $0.01 / $0.50 per MTok (input, 5m write, 1h write, cache read, output)
  for prompts up to 100,000 tokens and $0.50 / $0.625 / $1 / $0.05 / $2.50 above; the tier is
  decided per request and counts all input tokens (input + cache writes + cache reads).
- Opus 5.5, Fable 5.1 and Fable 5 match the table. The page lists Sonnet 5.5 cache reads at $0.10,
  the table has $0.20; a read-only run over this PC's transcripts shows Claude Code's own
  `costUSD` for Sonnet 5.5 is computed at $0.20 (one row: 39,454 cache-read tokens, cost 0.00789),
  so changing it would make the check fail. Left as is and reported (non-goal).
- `pricing._judge` counts `outside` and `unpriced` separately; the 70 rows of the issue are
  `outside` rows of priced models, never Haiku 5.5 rows.

## Requirements

- **REQ-001** — The table has an entry for `claude-haiku-5-5` with the five prices of the
  ≤100K tier, family `new` and `supports_effort: true`, plus the >100K tier with its threshold;
  `consulted` is 2026-11-04.
  - Request: "Add missing Claude 5 prices from a verifiable source"
  - Verify: test `test_haiku_55_prices_from_the_official_page`
- **REQ-002** — The check judges a Haiku 5.5 row inside when Claude Code's cost lies between the
  all-≤100K price (5m writes) and the all->100K price (1h writes), and outside beyond that.
  - Request: derived: Haiku 5.5 is priced by prompt length per request and a row aggregates many
    requests, so the band must span both tiers.
  - Verify: test `test_haiku_55_row_band_spans_both_tiers`
- **REQ-003** — `transcripts.request_cost` prices a Haiku 5.5 request at the >100K tier when its
  prompt (input + cache writes + cache reads) is over the threshold, and at the base tier otherwise.
  - Request: derived: same per-request rule the page states; otherwise quota points use wrong prices.
  - Verify: test `test_request_cost_uses_the_prompt_tier`
- **REQ-004** — Rows of a model without a price are excluded from the verdict: the saved check
  has `unpriced` (ids), `unpriced_rows` (count), `judged` counts only priced rows, and `verdict`
  is `fail` when a priced row is outside or when there are unpriced rows and no priced row inside; with nothing judged it stays `pass` as before.
  - Request: "rows of an unpriced model are excluded from the check with a separate notice"
  - Verify: test `test_unpriced_rows_leave_the_verdict`
- **REQ-005** — The `recompute-cost` summary says the unpriced models and their row count in a
  separate sentence ("sin precio: X, N filas fuera del cotejo"), es and en.
  - Request: "with a separate notice"
  - Verify: test `test_summary_names_the_unpriced_rows`
- **REQ-006** — `doctor` gives `OK` for a passing check that has unpriced models and names them
  in the detail; it keeps `WARN` when priced rows are outside.
  - Request: "doctor only warns when priced rows do not match"
  - Verify: test `test_doctor_ok_with_unpriced_note`
- **REQ-007** — The saved check also says how many outside rows each model has
  (`outside_by_model`), and the summary lists them, so the next report names the culprit model.
  - Request: "find out whether the 70 outside rows belong to the unpriced model"
  - Verify: test `test_outside_rows_by_model`
- **REQ-008** — Results for models already priced do not change: existing tests stay untouched
  except the table inventory test, which must list the new id.
  - Request: "no calculation change for already priced models"
  - Verify: cmd full pytest suite

## Acceptance scenarios

### Scenario: the Mac case

- **Given** `cost-state` rows of Opus 5.5 (inside) and Haiku 5.5
- **When** `recompute-cost` runs with the new table
- **Then** the Haiku rows are judged against the Haiku 5.5 band and the verdict is `pass`

### Scenario: a future unpriced model

- **Given** rows of `claude-nobody-9` and priced rows that are inside
- **When** the check runs
- **Then** verdict `pass`, `unpriced: ["claude-nobody-9"]`, `unpriced_rows: N`, and `doctor` is `OK`
  with a note naming the model

## Edge cases and failure behavior

- Only unpriced rows judged (no priced row ≥ $0.05): verdict `fail`, nothing could be checked; no row judged at all: `pass`, as today;
  `doctor` keeps its current `WARN` with "modelos sin precio".
- An old `cost-aggregates.json` written by 0.48.0 (verdict `fail` caused only by unpriced) keeps
  its `WARN` until `recompute-cost` runs again; the WARN already tells the user to run it.
- Rows below `MIN_JUDGED_COST` are not counted anywhere, as today.

## Non-functional requirements

- No network at load time; the table stays JSON in the package.
- Additive file format change: new keys in `cost-aggregates.json`; readers tolerate their absence.

## Non-goals

- Changing the Sonnet 5.5 cache-read price (see Summary): reported to the session.
- Fixing the weekly price watcher, which fails since 2026-10-19 on the Haiku 5.5 tier rows
  (`celda de precio ilegible en claude-haiku-5-5 / input`): separate issue.
- Valuation/attribution estimates keep using base-tier prices for Haiku 5.5.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
