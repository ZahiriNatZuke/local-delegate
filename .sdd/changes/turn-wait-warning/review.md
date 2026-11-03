# Result review: Visible common-turn wait warning

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: regression-reviewer, orchestrator
- Security reviewer: no — the change only appends a notice to tool output; no input parsing, paths or credentials
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ (all) | yes | yes | See verification.md; live: notice shown at 62-63 s waits on 2026-11-03 |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Notice contradicted a model error (timeout) | regression-reviewer | orchestrator | confirmed | Fixed in PR #544: no notice on error output |
| F2 | local_classify exact label broken by the notice | regression-reviewer | orchestrator | confirmed | Fixed in PR #544: classify excluded |

## Required follow-up

- None: all findings fixed or documented as known limits; released in 0.48.0.
