# Implementation plan: local_summarize: el aviso de foco reconoce el término en títulos con contenido

## Approach

In `_focus_missing`, instead of deleting every heading line, delete only the headings whose own body
(lines up to the next ATX heading of any level) has fewer than 3 `\w+` words once
parenthesized fragments are removed. The remaining text (bodies plus headings with content) goes to
the existing `sections.focus_terms_in`, which already folds case/accents and matches by stem. This
keeps the #561 rule for copied headings and placeholders.

## Ordered tasks

<!-- One checklist item per task: "- [ ] T<n> — title (REQ-NNN, ...)". Close it with [x]; drop it with
"- [-] T<n> ... dropped: <reason>". Every requirement needs at least one task that is not dropped. -->

- [x] T1 — Tests first: issue shape, variants, copied heading, real tool path (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: tests/test_summarize_focus_heading.py
  - Verification: they fail on origin/main for the right assert
  - Depends on: none
- [x] T2 — Heading counts when its section has content (REQ-001, REQ-002, REQ-003)
  - Files or modules: src/local_delegate/server.py (`_focus_missing`), CHANGELOG.md
  - Verification: new and existing focus tests green; full suite
  - Depends on: T1

## Test strategy

- Unit: `_focus_missing` with issue-shaped summary, uppercase/accents/plural/backticks, copied heading.
- Integration: `local_summarize` via its real path with the backend mocked (helpers of the existing
  focus test module pattern), prose and structured.
- End-to-end or manual: none (backend-independent logic).
- Security and secret scanning: `personal-security-check` before commit.

## Migration and compatibility

- Output only loses a false warning; no API, schema or config change.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
