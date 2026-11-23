# Brief: Codex: guard de escritura y lecturas, huecos de la revisión (#706, #707)

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

  > Arreglar #706 y #707 (guard de lecturas y escrituras de Codex, src/local_delegate/codex_reads.py) en un PR. #706: la expresión _PATCH_PATH tarda tiempo cuadrático con muchos espacios; hay que hacerla lineal. #707: con la lectura apagada o el backend caído, decide sale antes de note_real_read() y una lectura literal no levanta el guard, así que apply_patch se rechaza en bucle; además los huecos con tuberías, Select-Object -Skip, rangos en comando compuesto y el plazo por operación de socket que lista el issue.
