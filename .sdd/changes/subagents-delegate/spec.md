# Los subagentes delegan en local_* (issue #443)

## Qué

Dos revisores lanzados como subagentes hicieron 26 `Grep` + 16 `Read` y 0 `ToolSearch`/`local_*`.
Las piezas que instala el paquete hablaban al hilo principal y le daban al subagente una salida
(«léelo si necesitas líneas exactas»; el código grande pasaba en silencio). El cambio les dice a los
subagentes un patrón concreto: **localiza con `local_extract`/`local_explain_code` (`path`) y lee
solo ese rango con `offset`/`limit`**, y les recuerda cargar las tools diferidas con `ToolSearch`.

## Requisitos

- **R1 — mod de lectura (`mod/read.js`)**: con `agentId` en el evento, la lectura entera de un
  archivo grande que no es prosa pasa igual, registrada como `not_prose`, y lleva la nota
  `read.warn.subagent` (es/en). La vía no clasificable usa esa nota en vez de `read.warn.large`.
  Una lectura por rango no lleva nota. El hilo principal no cambia.
- **R2 — hook de `Read` por settings (`suggest_delegate_read.py`)**: con `agent_id`, el código
  grande ya no calla y la sugerencia de prosa pasa a `read.subagent` (sin «léelo directamente si
  necesitas líneas exactas»). El bloqueo de prosa no cambia. El hilo principal no cambia.
- **R3 — bloque de memoria** (`resources/memory/local-delegate*.md`, CLAUDE.md y AGENTS.md): dos
  reglas, al lanzar un subagente (paso 1 = delegación concreta + `ToolSearch("select:…")`) y si
  eres un subagente (localiza y lee el rango). `update` reescribe el bloque viejo.
- **R4 — catálogo de subagentes** (`install.agents.rule`): la regla de oro añade «ante un archivo
  grande, localiza y lee el rango». `update` regenera el bloque (`refresh_catalog_block`).
- **R5 — skill `local-delegation`** (es y en): sección «Subagentes» para quien orquesta y para
  quien trabaja, con un ejemplo de revisión y uno de implementación.
- **R6 — hook `SubagentStart`** (`subagent_start.py`, `hook subagent-start`, `hooks.json` del
  plugin y `_HOOK_EVENTS` de settings): `additionalContext` con cómo cargar las tools y el patrón.
  No bloquea, no escribe telemetría, sale con 0 con entrada rota.

## Fuera de alcance

- Distinguir en el panel las delegaciones del hilo principal y de subagentes (queda como tarjeta).
- Bloquear la lectura entera en un subagente (decisión de producto pendiente).

## Verificación

- `claude plugin test` del mod: `subagent_large_file_gets_locate_then_range_note` (control
  positivo: con `read.js` de `main` falla en `Expected ["read.warn.subagent …"] / Received []`).
- `tests/test_hook_texts.py`: hook de `Read` **instalado** con `agent_id` (código y prosa) y control
  del hilo principal; hook `SubagentStart` instalado. Control positivo: con el
  `suggest_delegate_read.py` de `main` fallan los dos casos de subagente.
- `tests/test_update.py::test_update_rewrites_an_old_block_with_the_subagent_rules`: CLAUDE.md y
  AGENTS.md con el bloque de la 0.41.1 → `scaffold.memory` WARN → `update` lo deja al día.
- `tests/test_hook_entry.py`, `test_plugin_package.py`, `test_plugin_migration.py`: el hook nuevo en
  el contrato del plugin y en la entrega por settings.
- Efecto real (después de publicar): contar `ToolSearch` y `local_*` en las transcripciones de
  subagentes (`…/subagents/agent-*.jsonl`) y `caller_kind=subagent` en el log de uso.
