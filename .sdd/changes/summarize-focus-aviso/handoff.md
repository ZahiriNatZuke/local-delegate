# Handoff: local_summarize: el aviso de foco reconoce el término en títulos con contenido

## Current state

- SDD status: closed (cerrado en el PR de la release 0.50.0, rama `release/0.50.0`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `2fd7ab43` (PR #606, 2026-11-09T12:32:26Z)

## What changed

- Un título del resumen con el término del enfoque y contenido propio debajo cuenta como mención para el aviso de `focus`.

## Decisions

- Un relleno de 3 o más palabras sin paréntesis bajo un título copiado cuenta como mención (aceptado en la spec).

## Next action

- Ninguna para este cambio.

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG 0.50.0, el PR y `review.md`; la jornada del 2026-11-09 del vault la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio (la sesión principal actualiza el índice de jornadas).
