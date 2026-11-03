# Brief: explain_code: flag answers that confirm an unanchored premise of the question

## Problem

Issue #538: `local_explain_code(path=<JS installer module that creates timestamped backups and
never deletes one>, question="¿cómo gestiona los backups y su retención?")` answered that the
module applies an "implicit retention". There is no retention or pruning code. No warning came
back: a silent failure. The model confirmed the premise of the question instead of checking it.

## Desired outcome

With `path` and a question, an answer that asserts a concept of the question the file does not
hold, in a sentence that neither negates it nor stands on the code, carries a
`[local-delegate warning: …]`. An answer that denies the premise ("no hay retención; nunca borra")
carries none. Deterministic, no extra model call.

## In scope

- A pure check in `line_check.py` and its use in `server._verified_lines` (#460/#527 pattern).
- i18n keys es/en for the warning; CHANGELOG `[Unreleased]` → Corregido.

## Out of scope

- Prompt changes (they are the fingerprint of the affinity measurements).
- Answers given with `code=` (no file) or without a question: unchanged byte for byte.

## Constraints and risks

- Spanish question vs English code: almost every Spanish word is absent from English code; a
  check on every absent word warned on 5 of 6 correct answers. Only nominalizations count.
- An assertion in a sentence that names a real identifier counts as anchored (known miss).

## Open questions

- None blocking. Whether to add a short prompt instruction is left to a live measurement.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-03 Original request, verbatim:

  > Issue #538: local_explain_code affirms behaviour the code does not have (backup retention) because the question presupposed it, with no warning. Add a deterministic guard in _local_delegate.warning.
