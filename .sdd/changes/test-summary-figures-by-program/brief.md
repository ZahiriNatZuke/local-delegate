# Brief: Resumen de salidas de tests: totales y versión por programa, y aviso de negación sin falsos positivos

## Problem

Issue #714. Sobre salidas de tests, el aviso del #684 salta en falso (coma, cifra en letras, failed contra errors) y el modelo cambia cifras que el programa conoce (version de Python, total de pruebas, omitidas).

## Desired outcome

Sin aviso sobre resumenes fieles, y los totales y la version leidos por programa, no pedidos al modelo.

## In scope

- runner_totals.py, _test_totals_notice y el postproceso de local_lint_summary en server.py, catalogos i18n, tests, CHANGELOG y wiki.

## Out of scope

- local_extract, locate*.py, line_check.py (PR #713 de otro agente); el prompt de las tools; F4 a F7 del review del #684.

## Constraints and risks

- Record known technical, security, compatibility, and delivery constraints.

## Open questions

- Resolve questions that materially change the specification before implementation.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-23 Original request, verbatim:

  > Issue #714: aviso falso de totales (#684: coma, cifra en letras, failed contra errors) y cifras cambiadas por el modelo (versión de Python, total de pruebas, omitidas) en local_summarize y local_lint_summary.
