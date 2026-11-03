# Brief: Panel: queued chunked rows say which chunk waits and for how long

## Problem

In the panel's «In progress» list, a chunked delegation that waits between chunks for a backend place (`local_wait: "slot"`) is drawn under «Queued» with the same «Chunk 2/3» chip as one being processed, and its time is the call's total, not how long it has waited. Separately, a «Processing» row wraps its time and characters to a second line depending on the width of the numbers.

## Desired outcome

A queued row says which chunk waits (not as being sent), why it waits (place or turn, with position) in the title, and how long it has waited next to the total; every row keeps time and characters on one line.

## In scope

- `/api/inflight`: a new optional `wait_s` field (seconds the current local wait has lasted).
- Panel «In progress» rows (`renderInflight` in `web/metrics.py`), its CSS and i18n (es, en).
- Tests for the API field and the panel rendering; screenshots light/dark.

## Out of scope

- The Claude mod band (`status.js`): it already says «2/3 · queued», which is correct; not changed.
- How chunks take and release places (`_slot`).

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-03 Original request, verbatim:

  > Issue #547: a queued chunked delegation shows 'Chunk 2/3' as if it were being sent, the time is the total, and a Processing row wraps its time/chars depending on the number width.
