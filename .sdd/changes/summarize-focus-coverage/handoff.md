# Handoff: local_summarize: el enfoque llega a la sección que lo trata, o avisa

## Current state

- SDD status: closed (PR de cierre `chore/close-sdd-2026-11-04`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `69d7027e` (PR #561, cierra #558)

## What changed

- `sections.py`: `focus_terms`, `focus_terms_in`, `focus_sections`.
- `server.py`: con foco, el mensaje de usuario nombra las secciones que lo tratan (no en ficheros de código, #539); si el resumen no menciona ningún término que la entrada sí tiene, aviso bilingüe `mcp.warning.focus_not_in_summary`.
- Tras la revisión: solo se juzgan términos copiables o en el idioma del resumen, plurales `-ies`, títulos del resumen no cuentan como mención, una sola pasada de regex, nota solo en el paso map.

## Decisions

- La nota mejora la probabilidad pero no garantiza la cobertura; el aviso es la red.
- Sin `focus`, prompts y salida quedan idénticos byte a byte.

## Next action

- Ninguna. Vigilar en el log de uso cuántos resúmenes con foco llevan el aviso.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: índice de jornadas de `projects/local-delegate` (sesión principal)
