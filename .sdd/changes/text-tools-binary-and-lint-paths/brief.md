# Brief: Tools de texto: rechazo de binarios y rutas exactas en lint_summary

## Problem

Las tools de texto con `path` aceptan binarios como texto y gastan llamadas al modelo para devolver
nulls (#693). `local_lint_summary` cuenta dos veces un fichero nombrado con ruta absoluta y
relativa, toma una URL por fichero y lista los ficheros en verde de pytest (#688), y no avisa
cuando el resumen inventa carpetas (#690).

## Desired outcome

Binarios rechazados antes del modelo con un mensaje útil; rutas del lint tratadas de forma exacta.

## In scope

- Arreglos R3 y R4 de `.sdd/changes/text-tools-common-cause/research.md`.

## Out of scope

- R1, R2, R5, R6, R7; el prompt de sistema de lint; `local_describe_image`.

## Constraints and risks

- Tests existentes intactos (#672, #525, #641, linealidad de `file_spans`).
- `server.py` es CRLF; `lint_patterns.py`, los JSON de i18n y el CHANGELOG son LF.

## Open questions

- Ninguna.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-23 Original request, verbatim:

  > Arreglos 3 y 4 de .sdd/changes/text-tools-common-cause/research.md (R3 y R4): rechazar entradas binarias con path en un único punto común antes del modelo (#693); rutas exactas en local_lint_summary: unir absoluta y relativa, descartar URLs, validar ruta completa y carpetas (#688, #690).
