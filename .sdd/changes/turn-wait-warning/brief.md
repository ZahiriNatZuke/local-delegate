# Brief: Visible common-turn wait warning

## Problem

Issue #537: a `local_summarize` took 343 s; 292 s of it was waiting for the common turn
(`turn.py`) behind a burst that alternated two models that cannot be loaded together. Nothing in the
tool's answer said so, so it looked like the model was slow. Research: `research.md`.

## Desired outcome

When a call waited long for the common turn, its answer says so (how long, that it was the queue of
other delegations and not the model, and that grouping calls by tool reduces it). The docs explain
the behavior under mixed-model bursts.

## In scope

- One notice, applied to every tool output without per-tool code (text tools and `local_extract`).
- Threshold constant with an env override (`LOCAL_DELEGATE_TURN_WAIT_NOTICE_S`, 60 s, `0` off),
  following `LOCAL_DELEGATE_QUEUE_MAX_WAIT_S` / `LOCAL_DELEGATE_PROGRESS_INTERVAL_S`.
- README and `docs/wiki/` (Troubleshooting, Configuration), CHANGELOG.

## Out of scope

- Changing the turn's fairness rule (grouping by model in the queue): separate backlog idea.
- Tool prompts, the usage log format (it already records `turn_wait_ms`).

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-03 Original request, verbatim:

  > Issue #537: make the common-turn wait visible with a warning in tool output and document the behavior under mixed-model bursts
