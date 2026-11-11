# Brief: Detector de tablas: GFM sin tuberías externas, |-|-|, CSV, TSV y ARIA; local_summarize sube a long con tabla (#650)

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

  > Parte «tablas que la regla no ve» del issue #650 más el seguimiento «enrutar las tablas de local_summarize al rol long»: ampliar el detector a GFM sin tuberías externas, |-|-|, CSV y TSV (heurística determinista y barata, cuidando falsos positivos en prosa, código, logs, YAML/JSON); decidir las rejillas de <div>; corregir el docstring del detector; que role_reason diga el formato; actualizar la descripción de local_extract; local_summarize con la misma subida a long, su role_reason, variable para apagarlo y descripción; tests de detector y de enrutado.
- L2 2026-11-11 Implementado, revisión adversarial del plan y dos jueces de resultado; hallazgos resueltos en dos commits; PR #658. Queda: CI del PR y la medición de volumen en la sesión principal.
