# Fixtures de los hooks de Codex (#669)

- `*.command.input.schema.json` y `*.command.output.schema.json`: copiados sin cambios de
  `codex-rs/hooks/schema/generated/` en el tag `rust-v0.169.0` de `openai/codex`. Son los esquemas
  con los que Codex genera el payload de entrada y parsea la salida de un hook `command`.
- `user_prompt_submit_*.json` y `subagent_start.json`: payloads con todos los campos que esos
  esquemas de entrada marcan como requeridos; los ids tienen la forma de un `ThreadId` (UUID v7) y
  el texto es inventado. `tests/test_codex_hooks.py` comprueba que cumplen el esquema.
- `pre_tool_use_*.json`: payloads de `PreToolUse` con los requeridos de su esquema: shell (`Bash`),
  `apply_patch`, una tool nuestra en el hilo principal (`mcp__local_delegate__…`), otra en un
  subagente (con `agent_id`/`agent_type` y el namespace con `-`), una llamada anidada de code mode
  (`tool_use_id` `exec-<uuid v4>`, como `core/src/tools/code_mode/delegate.rs`) y una tool MCP de otro
  servidor. `tests/test_codex_attribution.py` comprueba que cumplen el esquema.

Al subir la versión de Codex que se da por soportada, se vuelven a copiar los esquemas del tag
nuevo y se corre la suite.
