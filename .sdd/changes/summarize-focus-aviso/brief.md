# Brief: local_summarize: el aviso de foco reconoce el término en títulos con contenido

## Problem

`local_summarize(focus=...)` warns «el resumen no menciona ninguna palabra del enfoque» when the
summary has a section whose heading is the focus term (issue #593: `## \`local_extract\`` with seven
bullets). Cause, reproduced: `server._focus_missing` removes every heading line of the summary before
looking for the terms (`_SUMMARY_HEADING_LINE.sub`, #561 review: «copying a title is not summarizing
its section»), so a heading with a real body under it never counts.

## Desired outcome

A summary heading that holds a focus term counts as a mention when its section in the summary has
real content under it; a heading copied with nothing (or only a parenthesized placeholder such as
«(sin datos)») under it still does not count, so the warning keeps firing when the focus is missed.

## In scope

- `_focus_missing` in `src/local_delegate/server.py` (prose and structured paths share it).
- New tests in a new test file.
- CHANGELOG line under Unreleased.

## Out of scope

- Term extraction (`focus_terms`, `literal_focus_terms`), the stem/fold rules (they already cover
  case, accents and plural) and the language gate.
- The notes that name the sections to the model.

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-09 Original request, verbatim:

  > Issue #593: local_summarize con focus avisa de que el resumen no menciona el término aunque el resumen tiene una sección con ese título. El aviso debe reconocer el término también en títulos/encabezados (mayúsculas, acentos, plural) sin dejar de avisar cuando de verdad falta.
