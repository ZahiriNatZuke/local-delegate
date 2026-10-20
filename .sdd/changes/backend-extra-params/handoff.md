# Handoff: Parámetros extra por petición al backend (reasoning effort y extra body)

## Current state

- SDD status: `plan-review` con los gates `spec` y `plan` **aprobados** (2026-10-20). Siguiente
  transición: `implementing`.
- Toda la carpeta del cambio está **sin commitear** en `main` (untracked). La sesión de
  implementación la sube en la primera PR (lote L0) o en una rama propia.
- Nada implementado todavía.

## What changed

- `research.md`: dos rondas (mapa de caminos de petición, catálogo verificado de llama-server
  b10909, prueba en vivo en la ventana de prueba `w-20261020T124016Z`, ya cerrada).
- `spec.md`: 23 REQ, revisada dos veces y con la enmienda de REQ-012 de la revisión del plan.
- `plan.md`: 10 lotes y 19 tareas en seis olas, con «Delegación local» por tarea.
- `review.md`: las revisiones de la spec (dos pasadas) y del plan.

## Decisions

- Las decisiones 1–11 del usuario están en `brief.md` y mandan sobre todo lo demás.
- Hechos medidos que no hay que volver a investigar (`research.md`, segunda ronda):
  - `reasoning_effort` solo **no** vence a `--reasoning off`;
  - `chat_template_kwargs.enable_thinking: true` sí lo vence;
  - el razonamiento consume `max_tokens`: Qwen se comió 700/700 tokens y devolvió el contenido
    vacío.

## Next action

- Pasar a `implementing` y ejecutar la ola 1 del `plan.md` (L0, A1 y E en paralelo), siguiendo
  sus reglas de ejecución y de delegación local.
