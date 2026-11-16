# Brief: Atribución de cada delegación de Codex a su sesión (#669, segunda parte)

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

- L1 2026-11-16 Original request, verbatim:

  > Segunda parte del issue #669: atribución de cada delegación a su sesión de Codex. Hook PreToolUse sobre ^mcp__local[-_]delegate__ con nota de Codex (prefijo propio en el nombre del fichero); leer _meta.callId solo de codex-mcp-client; decidir qué hacer con _meta.sessionId; apartar las filas de Codex del relleno a posteriori y del coste (excluded) y darles columna propia en el panel y en el resumen por sesión; fixtures de PreToolUse (Bash, apply_patch, MCP, code mode con ids exec-<uuid>) y controles del matcher. Si algo no se puede verificar sin Codex real, dejar la prueba en vivo descrita en el handoff.
