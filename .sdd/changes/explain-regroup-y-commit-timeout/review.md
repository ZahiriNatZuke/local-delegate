# Result review: Regroup cortado en explain_code y diff grande en commit_msg (#598, #596)

## Review level

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: none (no auth, secrets, permissions or user data touched)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | any failure of the optional widened retry now keeps the cut output (B-09/A4) |
| REQ-002 | yes | yes | tail moved right after the main sentence, regroup steps only (B-02/A3) |
| REQ-003 | yes | yes | narrower denial words and inline code excluded (A2/B-04); case with a question tested (A5) |
| REQ-004 | yes | yes | no budget outside a tool call (A1) |
| REQ-005 | yes | yes | map/reduce receipt counts the parts read (B-01); exact warning and receipt asserted (B-05) |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| B-01 | map/reduce receipt said the total parts after a time cut | — | media | suspected | fixed: `parts=time_cut`; test with feedback on |
| A1 | budget also applied outside a tool call (ceiling measurement script) | media | — | suspected | fixed: `_call_started()` is `None` without a token; test |
| A2/B-04 | denial detector too broad («sin», «nada», `None`, inline code) | media-baja | baja-media | confirmed | fixed: `_DENIAL` and `_INLINE_CODE`; new parametrized cases |
| A3/B-02 | combining tail read as referring to the split retries | baja | baja-media | confirmed | fixed: tail right after the main sentence; regroup only |
| A4/B-09 | widened retry failing by timeout/5xx failed the whole operation | baja | baja | confirmed | fixed: any failure keeps the cut output |
| B-03 | overflow test passed without the widened call | — | baja-media | suspected | fixed: guard that the wide call was made |
| B-05 | issue test did not pin 4 maps, warning figures nor receipt | — | media | suspected | fixed: exact asserts |
| A5 | no test of cut + denial with a question | baja | — | suspected | fixed: test added |
| B-06 | widened tests go through `_chat_map_reduce` with `local_summarize` | — | baja | suspected | accepted: the explain path is covered by `test_explain_with_a_question_widens_a_cut_regroup` and the question+denial test |
| B-07 | residual time risks (#455 splits inside a chunk, regroup in reduce, wait > 95 s before chunk 2) | — | note | suspected | accepted and recorded in verification.md |
| B-08/A6 | «límite de la tool (95 s)» wording; CHANGELOG absolute | baja | baja | confirmed | fixed wording; wiki goes with the release |

## Required follow-up

- A time budget for the other chunked tools (summarize, lint, explain) if they reach 120 s.
- `docs/wiki/Tools.md` mention at release time.
