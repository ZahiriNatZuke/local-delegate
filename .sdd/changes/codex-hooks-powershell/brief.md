# Brief: Codex en Windows: hooks que arrancan en PowerShell, cmd y bash (#718)

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

- L1 2026-11-23 Original request, verbatim:

  > Issue #718: la línea de codex_hooks.command() en win32 empieza por la ruta del intérprete entre comillas y PowerShell (shell de los hooks de Codex) da ParserError; los 4 hooks nunca arrancan. Arreglar la forma de la línea, que doctor avise de una línea nuestra que empieza por comilla, y comprobar el plazo tool_timeout_sec de Codex.
