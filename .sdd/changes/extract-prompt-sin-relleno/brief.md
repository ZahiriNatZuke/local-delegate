# Brief: local_extract: el prompt pide null y prohíbe rellenar con otra clave o fila

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

  > Sí se cambia el prompt de local_extract para cerrar el #586. El prompt de la llamada única (y el de los trozos, si lo hay) pide null para lo que la entrada no trae y prohíbe rellenar una clave con datos de otra clave o de otra fila. Declara la frontera en PROMPT_BOUNDARIES. comments_authors_and_gist como la cadena "[]" también es un fallo; mira si el post-proceso puede normalizar una lista vacía en forma de cadena a [] o a null sin riesgo.
