# Specification: local_summarize: el aviso de foco reconoce el término en títulos con contenido

## Summary

The focus-coverage warning of `local_summarize` stops firing when the summary treats the focus in a
section whose heading holds the term, and keeps firing when the heading is only copied.

## Requirements

- **REQ-001** — A summary heading of level 2 or more holding a focus term, followed (up to the next heading of any
  level: its own body) by at least 3 words (letters/digits) outside parentheses, counts as a
  mention: no warning. A level-1 heading (the summary's title) never counts.
  - Request: "El aviso debe reconocer el término también en títulos/encabezados"
  - Verify: test tests/test_summarize_focus_heading.py
- **REQ-002** — The heading match is case-, accent- and plural-insensitive and finds a term inside
  backticks or with underscores (same fold/stem as the body search).
  - Request: "(mayúsculas, acentos, plural)"
  - Verify: test tests/test_summarize_focus_heading.py
- **REQ-003** — A heading with no body, or with only a parenthesized placeholder or fewer than 3
  words, still does not count: the warning keeps firing when the focus is really missing. Existing
  tests of `tests/test_summarize_focus_coverage.py` pass unchanged.
  - Request: "sin dejar de avisar cuando de verdad falta"
  - Verify: test tests/test_summarize_focus_heading.py tests/test_summarize_focus_coverage.py
- **REQ-004** — Through the tool's real path (`local_summarize` with `path` and `focus`, backend
  mocked) the issue's shape gives no warning.
  - Request: "derived: probar el uso, no solo la pieza (brief)"
  - Verify: test tests/test_summarize_focus_heading.py

## Acceptance scenarios

### Scenario: the issue

- **Given** a Markdown input with a `## \`local_extract\`` section and others
- **When** `local_summarize(path=..., focus="local_extract")` returns a summary with that heading and
  bullets under it
- **Then** the output carries no focus warning

### Scenario: copied heading

- **Given** the same input
- **When** the summary has `## La entrada en cp1252` followed only by `(sin datos)`
- **Then** the warning still lists `cp1252`

## Edge cases and failure behavior

- A heading followed directly by a subheading has no body of its own and does not count (a summary
  titled with the document's title, `# Revisión de cp1252` over `##` sections, must not hide a miss);
  each subheading is judged by its own body.
- Setext headings are not recognized by `_SUMMARY_HEADING_LINE` today; unchanged (they count as text
  already).

## Non-functional requirements

- Linear scan of the summary (short text); no new regex with nested quantifiers.

## Non-goals

- Telling filler of 3+ words without parentheses («No hay información disponible.») from a real
  body: accepted limit, recorded in the result review.

- Judging whether the body really talks about the focus (semantic check).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
