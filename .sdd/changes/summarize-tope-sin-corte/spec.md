# Specification: local_summarize: tope de salida que crece con la entrada grande

## Summary

The single call of `local_summarize` gives a big input room to finish its summary; inputs up to
16 000 characters keep today's cap, and an answer still cut by `max_tokens` keeps ending at its last
complete sentence with the notice.

## Requirements

- **REQ-001** — For an input of more than 16 000 characters the single call asks
  `3w + 64 + (chars - 16 000) // 20` output tokens (884 for the 23 409-char case with 150 words,
  2 114 at the `long` role's 48 000); at 16 000 characters or fewer it asks `3w + 64` as today.
  - Request: "el 31 % de las llamadas del mod de lectura acaba en `finish_reason: length` … con entradas de 20 K caracteres o más"
  - Verify: test tests/test_summarize_big_input_cap.py
- **REQ-002** — A fake backend that answers `length` with a cut sentence: the output ends at the last
  complete sentence and carries the `output_trimmed` notice (no mid-sentence end without a notice),
  on a big input as on a small one.
  - Request: "El resumen no debe acabar a mitad de frase sin avisar."
  - Verify: test tests/test_summarize_big_input_cap.py
- **REQ-003** — The map/reduce, the structured path and the other tools keep their caps; existing
  tests (`test_summarize_word_budget.py`, `test_request_body_compat.py`, `test_structured_summary.py`)
  pass unchanged.
  - Request: "derived: sin regresiones (brief); #610 touches the map/reduce"
  - Verify: test tests/test_summarize_word_budget.py tests/test_request_body_compat.py tests/test_structured_summary.py
- **REQ-004** — A live rerun recipe for the release test: the exact call, a ~23 K-char `.md` of the
  repo and the criterion of «bien».
  - Request: "deja en `scratchpad/live/rerun_580.md` la llamada exacta … y el criterio de «bien»"
  - Verify: review scratchpad/live/rerun_580.md

## Acceptance scenarios

### Scenario: the Mac case

- **Given** a 23 409-char Markdown and `max_words` 150
- **When** `local_summarize(path=...)` takes the single call
- **Then** the request asks 884 tokens instead of 514

## Edge cases and failure behavior

- Input exactly 16 000 characters: today's cap. `max_words` smaller or bigger: the extra term is
  independent of it.
- The extra term counts the characters sent to the model (`len(content)`).

## Non-functional requirements

- No extra backend call: the cap is only a bound, the model stops when it is done.

## Non-goals

- A retry with a wider cap (rejected in brief.md); changing the map/reduce caps.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
