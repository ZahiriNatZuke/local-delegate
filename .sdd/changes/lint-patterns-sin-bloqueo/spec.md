# Specification: lint_patterns: buscar ficheros en tiempo lineal sobre logs con tramos largos sin espacios

## Summary

A lint/test log with long runs without spaces (unittest dots, long words, paths without an
extension) no longer stalls the daemon: finding the files a log names takes linear time, with the
same result as before.

## Requirements

- **REQ-001** — `files_by_frequency` and `code_counts` on a run of 20 000 chars (dots, `a.`, `a/`,
  `~a`, `a.py` + dots + `b.py`) finish in under 1 s each.
  - Request: "las delegaciones con logs de unittest (líneas largas de puntos) bloquean el daemon por `lint_patterns`"
  - Verify: test tests/test_lint_patterns_linear.py
- **REQ-002** — The files found, their order and their spans are exactly those of
  `FILE.findall`/`FILE.sub` before the change, on the existing tests and on a differential fuzz
  (thousands of random strings over an alphabet of path, extension and separator characters).
  - Request: "derived: sin regresiones (brief); the B2e fidelity measure compares against these files"
  - Verify: test tests/test_lint_patterns_linear.py
- **REQ-003** — The finding-counter check on JSON keys (`errorCount`, `offense_count`) gives the same
  verdict as `_FINDING_COUNT.fullmatch`, in linear time (a 200 000-char key in under 1 s).
  - Request: "derived: same class of quadratic regex on untrusted input in the same module"
  - Verify: test tests/test_lint_patterns_linear.py
- **REQ-004** — Through the tool's real path, `local_lint_summary` on a chunked unittest log with a
  long dots line (backend mocked) returns in under 5 s and its inventory still names the log's files.
  - Request: "Reproduce con una entrada sintética, mide el tiempo antes/después y añade un test con tope de tiempo que falle sin el fix"
  - Verify: test tests/test_lint_patterns_linear.py
- **REQ-005** — The time-capped tests fail on `origin/main` by their time assert (positive control),
  and the before/after times are recorded.
  - Request: "mide el tiempo antes/después"
  - Verify: cmd timing script on main and on the branch; recorded in verification.md

## Acceptance scenarios

### Scenario: unittest progress line

- **Given** a log whose first line is 20 000 dots and that then names `tests/test_x.py`
- **When** `local_lint_summary` chunks it and builds the inventory
- **Then** it returns in seconds and the inventory names `tests/test_x.py`

## Edge cases and failure behavior

- Paths with `~`, `\`, doubled slashes, `spec.ts`, `yaml`/`yml`, uppercase extensions, an extension
  followed by `.`, `-` or a word char: same matches as the regex (the fuzz covers them).
- Non-ASCII word characters: `\w` and IGNORECASE are delegated to `re` on the short pieces (runs and
  extension), so Unicode behaves as before.

## Non-functional requirements

- Security: linear time on untrusted input; no new regex with nested quantifiers or overlapping
  alternatives under a quantifier.
- Compatibility: `FILE` stays exported, unchanged.

## Non-goals

- Changing which files count (no new extensions, no anchoring that drops current matches).
- Other modules' regexes.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
