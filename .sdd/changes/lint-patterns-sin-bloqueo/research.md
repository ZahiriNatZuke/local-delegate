# Research: lint_patterns: buscar ficheros en tiempo lineal sobre logs con tramos largos sin espacios

## Current behavior

`lint_patterns.FILE` (`src/local_delegate/lint_patterns.py:17-21`),
`(?:[\w.~-]+[/\\])*[\w.-]+\.(?:py|…|spec\.ts)\b` with IGNORECASE, is run with `findall` over the
whole log in `files_by_frequency` (line 39) and with `sub` in `code_counts` (line 66). Both are
called from `server._lint_inventory` (`server.py:6508-6538`) when `local_lint_summary` chunks a log,
and from `invented_files`/`not_mentioned`. On a run without spaces made of `[\w.-]` (the progress
line of `python -m unittest`, `....F..E...`), every start position fails after scanning to the end of
the run: quadratic time, pure CPU with the GIL held in the daemon.

Measured on `origin/main` (`ac33807a`), this PC, `FILE.findall("." * n)`:

| n | time |
| --- | --- |
| 2 000 | 0.35 s |
| 4 000 | 1.43 s |
| 8 000 | 6.05 s |

`_FINDING_COUNT` (`lint_patterns.py:210`, `.*(?:error|…).*count` with `fullmatch` on every key of
a JSON report, `clean_verdict`): quadratic in the key length (8 000 chars: 0.028 s; ×4 per
doubling). `CODE`, `RULE`, `MARKDOWN_ESCAPE`, `_ANSI`, `CLEAN_LINE`, `_PYTEST_*` and
`_PER_FILE_FORMATS`: under 1 ms at n = 8 000 on dots, `a`, `a.`, `a/`, `a-`, `error `, `a.b/`.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `lint_patterns.files_by_frequency` | files a log names, by frequency | same result, linear time | line 39 |
| `lint_patterns.code_counts` | codes outside file tokens | same result, linear time | line 66 |
| `lint_patterns._json_object_is_clean` | finding counters in JSON keys | same result, linear time | lines 210, 237 |
| `lint_patterns.FILE` (constant) | `fullmatch` in `mentions`; public name | kept unchanged | line 117 |
| `server._lint_inventory` | inventory of chunked lint logs | none (calls the functions above) | server.py:6524-6537 |

## Existing conventions

- Code and names in English; comments explain the why. File is LF.
- Tests in `tests/test_lint_*.py` call the public functions and `local_lint_summary` with
  `backend_mock`.

## Dependencies and integrations

- No new dependency (stdlib `re`). The `.sdd/.../evidence/*` scripts call `files_by_frequency`
  and keep working.

## Risks and unknowns

- Confirmed: the regex is polynomial (quadratic), not exponential. The leftmost-match semantics of
  `findall` must be kept exactly (tests and the B2e fidelity measure depend on it): a linear scanner
  is checked against the old regex with a differential fuzz over an adversarial alphabet.
- `FILE.fullmatch(item)` stays: one start only, linear on the measured shapes.
