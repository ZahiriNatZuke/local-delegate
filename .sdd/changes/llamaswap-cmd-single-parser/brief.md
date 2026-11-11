# Brief: llama-swap: un solo lector del cmd

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

- L1 2026-11-11 Original request, verbatim:

  > Dos lectores del cmd de llama-swap no coinciden: _parse_cmd_flags hace cmd.split() y no entiende comillas ni flag=valor; footprint.cmd_flags sí
