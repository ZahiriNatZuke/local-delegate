# Result review: Haiku 5.5 price and price check that survives unpriced models (#563)

## Review level

- Level: standard
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: no — no auth, secrets or destructive operation; prices are public data
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | |
| REQ-002 | yes | yes | |
| REQ-003 | yes | yes | threshold `>` matches «over 100,000» |
| REQ-004 | yes | yes | F1 fixed |
| REQ-005 | yes | yes | F2 kept |
| REQ-006 | yes | yes | |
| REQ-007 | yes | yes | |
| REQ-008 | yes | yes | `_row_cost` regroups the sum: one-ulp difference, far below the 0.005 tolerance |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | `priced_verdict` gave `fail` when no row was judged at all (all under $0.05), where `verdict` gave `pass`: a new permanent WARN | yes | yes | confirmed | fixed: `fail` only on outside rows or on unpriced rows with no priced row inside; nothing judged stays `pass`; test and mutant M8 added |
| F2 | the unpriced models appear in the main line and again in the new sentence | yes | yes | confirmed | kept: the main line is the existing format; the new sentence is the separate notice the request asks for, with the row count |
| F3 | «fuera del cotejo» next to «N fuera» (outside the band) | no | yes | suspected | kept: wording requested literally by the task |
| F4 | WARN for outside rows still lists unpriced models | no | yes | suspected | kept: existing behavior pinned by `test_both_things_at_once` |
| F5 | plan named a non-existent test file; handoff empty | no | yes | suspected | fixed |
| F6 | the price watcher `compare` ignores `long_prompt` | yes | no | suspected | out of scope: issue #564 |

## Required follow-up

- Issue #564 (price watcher and the Haiku 5.5 tier rows).
- Sonnet 5.5 cache-read price: page $0.10, table and Claude Code $0.20; decision for the session.
