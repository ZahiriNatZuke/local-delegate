# Handoff: local_lint_summary: recuentos por fichero y por código por programa, con aviso si el resumen da otra cifra (#717)

## Current state

- SDD status: result-review
- Last completed gate: quality
- Current revision: rama `fix/lint-counts-by-program`

## What changed

- `lint_patterns.count_mismatches` y `server._lint_counts`: línea del programa con recuentos y aviso de cifras distintas, en los tres caminos de `local_lint_summary`.

## Decisions

- La línea va tras el resumen y antes de los avisos, para que los avisos existentes sigan cerrando la respuesta.
- Una cifra pegada a un código (`2 errores de E501`) es del código, no total del fichero.

## Next action

- Mezclar el PR (lo decide el usuario) y cerrar el SDD tras la release 0.54.1.
