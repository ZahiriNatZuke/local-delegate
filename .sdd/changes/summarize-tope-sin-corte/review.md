# Result review: local_summarize: tope de salida que crece con la entrada grande

## Review level

- Level: standard
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: no — a numeric cap of one backend call; no new input handling
- Verdict: conforms (after the fixes below)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | `path=` with accents added after review |
| REQ-002 | yes | yes | guard (trim already in 0.49.0) |
| REQ-003 | yes | yes | map/reduce and structured unchanged |
| REQ-004 | yes | yes | recipe outside the repo |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Small margin just above 16 K (564 at 17 K) | found | - | suspected | accepted: no default-sized cut below 16 K in the log; the notice covers the rest; recorded |
| F2 | CHANGELOG overpromised («ya no corta», «siempre») | found | found | confirmed | reworded («da más margen», «a menudo») |
| F3 | Worst case of a runaway answer longer (2 114 at 48 K) | found | - | suspected | fixed after the PR review: ceiling `CHUNK_MAX_TOKENS` and context left (REQ-005) |
| F6 | PR review: no ceiling; structured single call without the widening | PR | PR | confirmed | REQ-005 and REQ-006, 4 tests |
| F4 | No test with `path=` and accents (chars vs bytes) | - | found | suspected | added `test_the_cap_counts_characters_not_bytes_of_a_file` |
| F5 | verification.md and plan tasks pending | - | found | confirmed | filled |

## Required follow-up

- Live rerun in the release joint test (`scratchpad/live/rerun_580.md`) before closing #580 for good.
