# Brief — concurrencia-pc-mac

Tarjeta del GitHub Project 3: «Concurrencia y cola de delegaciones de la PC y la Mac en un solo
turno visible» (prioridad 1 del 2026-10-29). Objetivo: una sola cola visible en el panel, sin
bloqueos para siempre y sin romper el uso solo local, con progreso MCP durante las esperas.

- Paso 0 (instrumentación del log y cabecera de origen): `spec-step0.md`, `plan-step0.md`, rama
  `feat/concurrency-log-fields`.
- Research y opciones A/B/C, con el plan de medición del paso 1: `research.md`.
- Paso 1 (medición, 2026-10-29): `measurement-step1.md`.
- Diseño (opción B, turno con arrendamiento en el daemon de la PC): `spec.md` y `plan.md`, aprobados
  en dos rondas (`spec-review.md`, `plan-review.md`). Siguiente: implementar por lotes (1 y 2 en
  paralelo; luego 3, 4 y 5).
