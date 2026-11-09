# Implementation plan: lint_patterns: buscar ficheros en tiempo lineal sobre logs con tramos largos sin espacios

## Approach

Keep `FILE` as the definition and add a linear scanner `file_spans(text)` that returns the spans
`FILE.finditer` would return. The regex decomposes as `D* F`: each `D` (`[\w.~-]+[/\\]`) is
deterministic (its run cannot hold a slash, so a shorter run never helps); `F` (`[\w.-]+\.ext\b`)
from position p succeeds at the LAST extension start q > p inside the `[\w.-]` run of p (greedy
backtracking tries the longest first), with the first alternative of the extension, which
`_EXT.match(text, q)` gives exactly. With right-to-left tables (run ends, last valid extension per
run, best match from each position, deepest segments first) every position is computed once: O(n).
`findall` = walk left to right taking the match at i or moving one char. `files_by_frequency` and
`code_counts` use the spans. `_FINDING_COUNT.fullmatch(k)` becomes string tests: the key, folded
like IGNORECASE does, ends in `count` and holds one of the words before that suffix.

## Ordered tasks

- [x] T1 — Time-capped tests and differential fuzz, failing on main by the time assert (REQ-001, REQ-003, REQ-004, REQ-005)
  - Files or modules: tests/test_lint_patterns_linear.py
  - Verification: run on main (fails by time), on the branch (passes)
  - Depends on: none
- [x] T2 — Linear `file_spans` and its use in `files_by_frequency`/`code_counts` (REQ-001, REQ-002)
  - Files or modules: src/local_delegate/lint_patterns.py
  - Verification: fuzz equality with `FILE.finditer`; existing lint tests unchanged
  - Depends on: T1
- [x] T3 — Linear finding-counter key check (REQ-003)
  - Files or modules: src/local_delegate/lint_patterns.py
  - Verification: fuzz equality with `_FINDING_COUNT.fullmatch`
  - Depends on: T1
- [x] T4 — Before/after timings, CHANGELOG without issue number, full suite (REQ-005)
  - Files or modules: CHANGELOG.md, verification.md
  - Verification: timing script; full suite with -n 2
  - Depends on: T2, T3

## Test strategy

- Unit: spans equal to the regex (fuzz + explicit edge cases); time caps.
- Integration: `local_lint_summary` real path with a chunked unittest log and the backend mocked.
- End-to-end or manual: none (pure function, no backend dependency).
- Security and secret scanning: personal-security-reviewer on the diff; personal-security-check.

## Migration and compatibility

- No API change: `FILE` still exported; outputs equal; scripts under `.sdd/.../evidence` unaffected.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
