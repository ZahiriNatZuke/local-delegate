# Brief: local_summarize: tope de salida que crece con la entrada grande

## Problem

#581 (0.49.0) raised the flat `local_summarize` cap from 2w+64 to 3w+64 (514 with 150 words) and
added `trim_cut=sections.trim_to_last_sentence` with the notice `output_trimmed`. So a cut answer
already ends at a complete sentence with a notice; what remains is that the summary of a big input is
cut back at all: on the Mac 5 of 5 calls over a 23 409-char `.md` ended in `length` at 514 tokens
(the model wants more than 3.4 tokens per word asked on big inputs). The cap is flat in the input
size, while the answers grow with it: in this PC's log (gemma4-26b-a4b, single-call sizes) the
median `tokens_out` of `stop` answers goes 442 (8-16 K chars) -> 552 (16-24 K) -> 769 (24-32 K), and
every `length` of a default-sized call is on inputs of 16 K chars or more.

## Desired outcome

The single call of a big input gets room to finish; a still-cut answer keeps ending at its last
complete sentence with the notice.

## In scope

- `_summary_max_tokens` and the single `_chat` of `local_summarize` (server.py).
- Tests with a fake backend that answers `length`; live rerun recipe in the scratchpad.

## Out of scope

- `_chat_map_reduce`/`_regroup` (PR #610 touches them) and the structured path (off by default).
- The mod's own summary (#608).

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Retry on `length`: rejected. It regenerates the whole answer (on the mod's interactive read
  path that doubles the wait) while a larger cap costs nothing when the model stops earlier.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-09 Original request, verbatim:

  > Issue #580 reabierto: local_summarize con el max_words por defecto sigue cortándose en la 0.49.0 con el tope 3w+64=514 tokens (31 % del mod de lectura en finish_reason length, gemma4-26b-a4b, entradas de 20 K caracteres o más). Decidir con datos entre tope proporcional, reintento con más tope o corte en la última frase con aviso; el resumen no debe acabar a mitad de frase sin avisar.
