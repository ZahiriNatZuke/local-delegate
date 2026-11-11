# Result review: Panel: desglose y filtro por proyecto con nombres locales; fuera el conmutador del propio repo

## Review level

- Level: deep
- Judges: result-reviewer-1, plan-reviewer-1
- Security reviewer: yes — personal-security-reviewer, no exploitable findings
- Verdict: conforms after fixes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | switch, dialog and ld-self removed |
| REQ-002 | yes | yes | include_self ignored, counters gone |
| REQ-003 | yes | yes | hooks disabled answer now carries project (H2) |
| REQ-004 | yes | yes | cost follows the filter |
| REQ-005 | yes | yes | empty with session= (E10) |
| REQ-006 | yes | yes | process LOG_DIR, mod request untouched |
| REQ-007 | yes | yes | process test with a barrier; strict read under the lock (H3) |
| REQ-008 | yes | yes | caps, bad entries, too big not retried (H6) |
| REQ-009 | yes | yes | names only in the map and by_project name |
| REQ-010 | yes | yes | es and en |
| REQ-011 | yes | yes | escHooks and textContent; Cf and bidi rejected |
| REQ-012 | yes | yes | options rebuilt only on change (H7) |
| REQ-013 | yes | yes | line removed |
| REQ-014 | yes | yes | scripts untouched |
| REQ-015 | yes | yes | once per hash, retried after an incomplete pass |
| REQ-016 | yes | yes | wiki gains E8, E9 and E10 |
| REQ-017 | yes | yes | 8 screenshots |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | status line paid the backfill | plan reviewer | result reviewer H4 | confirmed | session= returns an empty by_project and skips the map |
| F2 | a failed backfill pass was never retried | plan reviewer | result reviewer H5 | confirmed | outcome complete flag; test and mutant |
| F3 | process test without a barrier | plan reviewer | not raised | suspected | barrier file; mutant without the lock caught |
| F4 | exceptions of the filter not in the spec | plan reviewer | result reviewer H8 | confirmed | E8 in the spec, wiki and tooltip text |
| F5 | names visible on a panel published on the network | plan reviewer | result reviewer H9 | confirmed | accepted as E9, documented |
| F6 | hooks disabled answer without project | not raised | result reviewer H2 | suspected | added with test |
| F7 | transient read error under the lock could wipe names | not raised | result reviewer H3 | suspected | strict reader for writers; test and mutant |
| F8 | too big map retried on every call | not raised | result reviewer H6 | suspected | marked as seen; test |
| F9 | drop-down rebuilt on every refresh | not raised | result reviewer H7 | suspected | rebuilt only when the list changes |
| F10 | hash regex accepted a final newline; C1 and bidi characters | security reviewer | result reviewer H10 | confirmed | fullmatch; C0, C1, separators, bidi and Cf rejected; tests |
| F11 | fast path for seen hashes held the thread lock | plan reviewer | not raised | suspected | check before taking the lock |

## Required follow-up

- Live check by the coordinator against the installed daemon: the lazy backfill over the real
  projects root and the map written by the real hooks.
