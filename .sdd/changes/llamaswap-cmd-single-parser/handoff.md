# Handoff: llama-swap: un solo lector del cmd

## Current state

- SDD status: closed (al abrir el PR; sin mezclar)
- Last completed gate: memory
- Current revision: rama `fix/llamaswap-cmd-single-parser` sobre `main` `332f0e36`

## What changed

- `llamaswap_config._parse_cmd_flags` es una vista sobre `footprint.cmd_flags`: comillas, `--flag=valor` y formas cortas se leen igual en contexto, ruta del GGUF y tipos de caché.
- `footprint.cmd_flags`: entre la forma corta y la larga gana la última; solo dígitos ASCII cuentan como entero.

## Decisions

- Una macro `${…}` no se expande: el contexto queda como supuesto (8192).
- Un apóstrofo dentro de una ruta sin comillas abre cita (como llama-swap); aceptado.

## Next action

- Mezclar el PR cuando el CI esté en verde.

## Memory

- Canonical note: Sin nota aparte: lo durable va en el CHANGELOG, el PR y `review.md`; la jornada del 2026-11-11 la escribe la sesión principal.
- Indexes updated: ninguno desde este cambio.
