# Brief: local_extract: aviso de valores sin respaldo y campos de línea por título

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

  > #586: review_verdict sale positive sin ninguna revisión en la entrada (campo inventado sin aviso); con una página HTML de ~33 KB un campo se rellenó con los datos de otra fila. Lo mínimo exigible es que un valor sin respaldo en la entrada no salga sin aviso; si una parte no se puede arreglar de forma fiable, aviso en _local_delegate. #594: con un campo que pide la línea de un título, devuelve el índice entero de secciones en cada campo y marca la línea 1 como dudosa.
