# Brief: lint_patterns: buscar ficheros en tiempo lineal sobre logs con tramos largos sin espacios

## Problem

`lint_patterns.FILE` backtracks in quadratic time on long runs without spaces (unittest
progress dots): 8 000 dots take 6 s of CPU with the GIL held in the daemon. See research.md.

## Desired outcome

Linear time with exactly the same files found.

## In scope

- `src/local_delegate/lint_patterns.py` (file search and JSON finding-counter keys), new tests,
  CHANGELOG line without issue number.

## Out of scope

- Regexes of other modules; changing which files count.

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-09 Original request, verbatim:

  > Tarjeta del board: las delegaciones con logs de unittest (líneas largas de puntos) bloquean el daemon por lint_patterns. lint_patterns.FILE tarda un tiempo cuadrático con un tramo largo sin espacios de [\w.-] (8000 puntos: 7,5 s). Reproducir con entrada sintética, medir antes/después y añadir un test con tope de tiempo que falle sin el fix. Subir a standard si la causa es un regex con backtracking catastrófico (entrada no confiable).
