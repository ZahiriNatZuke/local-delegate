# Result review: A mod decision record is reported as written even when it is not

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: no — small change in the failure path; leaks checked by both judges (failure line holds only the error type and allow-listed short names)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | strict mode cannot leak (finally + copied context), both judges |
| REQ-002 | yes | yes | 500 on unwritten line; 204/400/403 paths unchanged |
| REQ-003 | yes | yes | classify failure test added after review (finding 1) |
| REQ-004 | yes | yes | fullmatch after review (finding 2) |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | No test for `classify` exiting 1 | found | found | confirmed | fixed: test_a_failed_classify_exits_one_and_leaves_a_failure_line (positive control: assert 0 == 1) |
| F2 | `$` in `_FAILURE_NAME` accepts a trailing newline | found | found | confirmed | fixed: fullmatch + test_a_trailing_newline_is_not_a_short_name |
| F3 | Normal-hook test could not fail | — | found | suspected | fixed: it now asserts no failure line (positive control with strict default: fails) |
| F4 | Docstrings of hook.py / hook_entry.py uneven | — | found | suspected | fixed |
| F5 | One lost decision can leave up to three failure lines (daemon, process, mod) | found | — | suspected | accepted: each road reports its own failure; noted for measurements |
| F6 | A retried `summarized` rewrites its block note | found | — | suspected | accepted: out of scope (block notes), harmless |
| F7 | `read.js` comment still says «Answers 204» | found | — | suspected | accepted: mod out of scope; behaviour already right |

## Required follow-up

- None. Independent review before merge: «mezclar» with three low notes (F5–F7, accepted). Merged in `main` as `3e826b56` (PR #559), 22 PR checks green and `main` CI green.
