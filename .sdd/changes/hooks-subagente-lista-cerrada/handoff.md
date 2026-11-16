# Handoff: Hooks y bloque gestionado ante subagentes con lista cerrada de tools (#664)

## Current state

- SDD status: ver `state.json`.
- Last completed gate: ver `state.json`.
- Current revision: rama `fix/hooks-subagente-lista-cerrada`.

## What changed

- Los hooks de `Read`, de shell y `SubagentStart` reconocen un subagente de lista cerrada sin las
  `local_*` por su definición (`agent_type` → `.claude/agents/*.md`) y no lo mandan a ellas.
- El bloque gestionado y la skill (es y en) dicen qué hacer sin `ToolSearch`.

## Decisions

- La prueba es la definición, no el transcript: un agente de lista cerrada no tiene ningún
  `deferred_tools_delta`, nombre las `local_*` o no (medido en transcripts reales).
- Un `tool_use` o un delta propio con las `local_*` gana a la definición; el del principal no.
- Toda forma de YAML que el parser no lea entera es duda, nunca «cerrado».

## Next action

- Tarjeta aparte para el mod: no resumir ni añadir la nota de `local_*` a un subagente de lista
  cerrada (su evento solo trae `agentId`).

## Memory

- Canonical note: no hace falta nota nueva; la decisión vive en este SDD y en el docstring de
  `hook_common.py`.
- Indexes updated: ninguno.
