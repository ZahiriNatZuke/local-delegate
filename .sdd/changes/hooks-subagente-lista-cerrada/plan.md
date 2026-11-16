# Implementation plan: Hooks y bloque gestionado ante subagentes con lista cerrada de tools (#664)

## Approach

Investigación primero (un pendiente es una hipótesis):

- Doc oficial de hooks (code.claude.com/docs/en/hooks): la entrada trae `agent_id` y `agent_type`,
  ninguna lista de tools.
- Transcripts reales de subagentes de esta PC (solo estructura): 85 de 85 de lista cerrada sin MCP
  no tienen ningún `deferred_tools_delta`; los de lista abierta lo tienen antes del primer
  `tool_use`; uno de lista cerrada que nombra las `local_*` (`python-scripting-specialist`)
  tampoco tiene delta y las usa. Por eso el transcript solo no distingue, y #595 trata la falta de
  delta como duda.

Arreglo elegido: la prueba es la definición del agente (`agent_type` → `.claude/agents/*.md`), que
es lo que de verdad decide qué tools tiene. No depende de que el modelo obedezca prosa: el hook deja
de mandarlo a donde no puede ir. La prosa del bloque y la skill se añade como complemento, para
quien orquesta.

## Ordered tasks

- [x] T1 — Tests en rojo por la razón del issue (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: tests/test_hooks_mcp_absent.py
  - Verification: 13 fallos con `'deny' is None`, `'context' is None` y el recordatorio emitido
  - Depends on: none
- [x] T2 — `closed_agent_without_local_tools` y su uso en `local_tools_absent` (REQ-001, REQ-002, REQ-003)
  - Files or modules: src/local_delegate/resources/hooks/hook_common.py
  - Verification: tests del área en verde, en las dos entregas (settings y plugin)
  - Depends on: T1
- [x] T3 — `SubagentStart` sin recordatorio para la lista cerrada (REQ-004)
  - Files or modules: src/local_delegate/resources/hooks/subagent_start.py
  - Verification: test_subagent_start_skips_the_reminder_for_a_closed_list
  - Depends on: T2
- [x] T4 — Bloque gestionado y skill es/en (REQ-005)
  - Files or modules: src/local_delegate/resources/memory/, src/local_delegate/resources/skills/local-delegation/
  - Verification: tests/test_skill_parity.py
  - Depends on: none
- [x] T5 — Prueba instalada con HOME simulado (REQ-006)
  - Files or modules: ninguno del repo (script en el scratchpad)
  - Verification: salida del script y hashes de la config real
  - Depends on: T2, T3, T4
- [x] T6 — CHANGELOG, wiki y léxico del detector (REQ-007)
  - Files or modules: CHANGELOG.md, docs/wiki/Claude-plugin.md, docs/wiki/Integration-install.md, scripts/data/spanish_lexicon.json
  - Verification: revisión y tests/test_detect_spanish_names.py
  - Depends on: T2

## Test strategy

- Unit: `local_tools_absent` con definición, `tool_use` propio, `agent_type` raros.
- Integration: hooks lanzados como proceso, entrega settings y plugin.
- End-to-end or manual: `install` en HOME simulado y los hooks instalados.
- Security and secret scanning: sin secretos; solo lectura de `.md` pequeños con topes.

## Migration and compatibility

- Sin migración. Ante cualquier duda el comportamiento es el de antes.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
