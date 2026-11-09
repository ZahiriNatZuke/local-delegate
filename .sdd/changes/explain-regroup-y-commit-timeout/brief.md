# Brief: Regroup cortado en explain_code y diff grande en commit_msg (#598, #596)

## Problem

TBD

## Desired outcome

TBD

## In scope

- TBD

## Out of scope

- TBD

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-09 Original request, verbatim:

  > #598: local_explain_code acepta regroup cortados por max_tokens tras el reintento y saca una conclusión negativa que contradice el fichero. #596: local_commit_msg con un diff de ~125 KB supera los 120 s de la tool y acaba cancelado.
