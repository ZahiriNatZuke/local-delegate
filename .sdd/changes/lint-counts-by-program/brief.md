# Brief: local_lint_summary: recuentos por fichero y por código por programa, con aviso si el resumen da otra cifra (#717)

## Problem

En la prueba de humo de la 0.54.0, `local_lint_summary` le atribuyó a un fichero el F401 de otro y dio recuentos por fichero que sumaban 5 sobre 4 avisos, sin aviso (#717).

## Desired outcome

Los recuentos por fichero y por código los da el programa en una línea fija, con aviso si el resumen da otra cifra.

## In scope

- ruff/flake8 conciso, ruff completo y tsc (los formatos de `per_file_code_counts`), en los tres caminos de la tool.

## Out of scope

- Formatos nuevos (eslint, biome), pytest (ya tiene #641 y #715), cambios de prompt.

## Constraints and risks

- Sin reiniciar el daemon (prueba de Codex del usuario en curso); sin tocar hooks de Codex ni `codex_reads.py`.

## Open questions

- Ninguna.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-23 Original request, verbatim:

  > local_lint_summary: el programa añade una línea fija con el recuento por fichero y por código para los formatos que ya reconoce, y avisa si el resumen del modelo da otra cifra para un fichero o un código; sin formato reconocido, como hoy (#717)

- L2 2026-11-23 Implementado con tests rojos antes; revisión independiente con dos jueces; prueba en vivo en proceso.
