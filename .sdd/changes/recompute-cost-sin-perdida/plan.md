# Implementation plan: recompute-cost no pierde el relleno ni los agregados si la lectura previa falla

## Approach

One shared helper in `json_state.py`, next to the other cross-process JSON helpers:
`read_before_merge(path)` returns missing / parsed data / damaged, retries `OSError`, and raises
`UnreadableStateError(OSError)` when the retries run out; `set_aside(path, now)` copies a damaged
file next to it. `write_backfill` and `recompute.run` use it instead of the tolerant readers, which
stay for the panel. `run` takes a `FileLock` on `recompute-cost.lock` for its whole body and reads
`cost-aggregates.json` strictly BEFORE writing any backfill, so a persistent failure writes nothing.
The CLI maps the two new errors to their own messages.

## Ordered tasks

- [x] T1 — Tests first; check each fails on `main` by its own assert (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006)
  - Files or modules: tests/test_recompute_no_loss.py
  - Verification: pytest on the new file before the fix
  - Depends on: none
- [x] T2 — `json_state.read_before_merge`, `UnreadableStateError`, `set_aside` (REQ-001, REQ-002, REQ-005)
  - Files or modules: src/local_delegate/json_state.py
  - Verification: new tests
  - Depends on: T1
- [x] T3 — `write_backfill` reads strictly, with `on_damaged` callback (REQ-001, REQ-002, REQ-005)
  - Files or modules: src/local_delegate/attribution.py
  - Verification: new tests + tests/test_attribution.py unchanged
  - Depends on: T2
- [x] T4 — `recompute.run`: lock, strict aggregates read first, `set_aside` count, summary line (REQ-003, REQ-005, REQ-006)
  - Files or modules: src/local_delegate/recompute.py, i18n es/en
  - Verification: new tests + tests/test_recompute*.py unchanged
  - Depends on: T3
- [x] T5 — CLI messages for unreadable and busy (REQ-004, REQ-006)
  - Files or modules: src/local_delegate/cli.py, i18n es/en
  - Verification: new CLI tests
  - Depends on: T4
- [x] T6 — Full suite, ruff, CHANGELOG line without issue number (REQ-007)
  - Files or modules: CHANGELOG.md
  - Verification: pytest -n 2, ruff
  - Depends on: T5

## Test strategy

- Unit: `write_backfill` with a monkeypatched `Path.read_bytes` that fails N times (the card's
  antivirus simulation), and a persistent failure with byte comparison.
- Integration: `recompute.run` and `cli.run(["recompute-cost", ...])` on synthetic HOME/log in
  `tmp_path` (the real usage log is never touched). Lock: hold the `FileLock` from the test and run
  with a tiny timeout.
- End-to-end or manual: none beyond the CLI test.
- Security and secret scanning: no secrets; messages carry file names only.

## Migration and compatibility

- `write_backfill(log_dir, month, entries)` keeps its positional signature; `on_damaged` is a new
  keyword-only argument. `run` returns one more key (`set_aside`); `summary_text` reads it with
  `.get` so older dicts keep working. New i18n keys in both catalogs.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
