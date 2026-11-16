# Brief: Hooks y bloque gestionado ante subagentes con lista cerrada de tools (#664)

## Problem

Un subagente con `tools:` cerrado en su definición (por ejemplo `tools: Read, Grep, Glob`) no tiene
`ToolSearch` ni las `local_*`. Aun así, el recordatorio de `SubagentStart`, la pista del hook de
`Read` para código grande en subagente y el bloqueo de la prosa grande (en `Read` y en el shell) lo
mandan a cargarlas y usarlas, y el bloque gestionado de `CLAUDE.md` da por hecho que puede. El
detector de #595 (`local_tools_absent`) no lo ve porque el transcript de ese subagente no trae
ningún `deferred_tools_delta`, y la falta de delta se trata como duda.

## Desired outcome

Los hooks no mandan a las `local_*` a un subagente que no puede tenerlas, por una prueba que no
depende de que el modelo obedezca prosa; y el bloque y la skill dicen qué hacer en ese caso.

## In scope

- `hook_common.local_tools_absent` y un helper nuevo que lee la definición del agente.
- `subagent_start.py`.
- Bloque gestionado (`resources/memory/local-delegate*.md`) y skill (`SKILL*.md`).
- CHANGELOG, wiki (`Claude-plugin.md`, `Integration-install.md`), léxico del detector.

## Out of scope

- El mod (`mod/read.js`): en subagente la lectura por rango ya pasa literal; su resumen de una
  lectura completa no depende de que el subagente tenga las tools. Queda anotado como seguimiento.
- Codex, `local_extract`, la lectura con `path`, `local_describe_image` (otros PR).
- La mejora opcional 3 del issue (que `local_status` diga si la sesión tiene las tools).

## Constraints and risks

- La entrada del hook no trae la lista de tools (doc oficial de hooks: `agent_id` y `agent_type`).
- Falso positivo a evitar: un agente de lista cerrada que SÍ nombra las `local_*` tampoco tiene
  delta; por eso la prueba es la definición, no el transcript.
- El hook no puede tardar: topes de tamaño y número de ficheros.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data before recording. -->

- L1 2026-11-16 Original request, verbatim:

  > Resolver #664 de `ZahiriNatZuke/local-delegate`: «El paso 1 obligatorio de delegación es imposible en subagentes con lista cerrada de tools (sin ToolSearch)».

- L2 2026-11-16 Hecho el arreglo por definición del agente, tests, prueba instalada y documentación;
  queda el PR, el CI y el cierre de puertas.
