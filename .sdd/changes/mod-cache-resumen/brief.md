# Brief: El mod de lectura reutiliza el resumen de un fichero sin cambios (#608)

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

  > Issue #608: el mod de lectura resume una y otra vez el mismo fichero sin cambios (61 % de sus llamadas son repeticiones). Reutilizar el resumen de un fichero que no cambió (clave que detecte un cambio de contenido de forma fiable) y registrar el reuso como acierto de caché, distinto de una delegación nueva, de forma que el panel y las mediciones no lo cuenten como ahorro nuevo ni lo pierdan.
