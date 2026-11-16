# Handoff: Codex: matriz de capacidades y alternativas para barra, comandos sin modelo y tools fijadas (#671)

## Current state

- SDD status: `closing`. Puertas spec, plan, quality y conformance aprobadas; falta `memory` y
  `closed`, que hace la sesión principal al integrar el PR único (con el CI completo).
- Last completed gate: conformance.
- Current revision: rama `feat/codex-capability-matrix`.

## What changed

- `install --codex-direct-tools` / `--no-codex-direct-tools`: `omit_tools_from` con `"deferred"`
  en `[mcp_servers.local-delegate]` de Codex; sin flag, `install` y `update` conservan la lista.
- `doctor`: «tools directas sin tool_search» en la línea de la entrada MCP de Codex.
- Wiki `Codex-capabilities.md` (matriz con evidencia), enlaces en README y Home, fila nueva en
  `Integration-install.md`, CHANGELOG, textos es/en, `tests/test_codex_direct_tools.py`.

## Decisions

- Apagado por defecto: Codex solo deja sacar de `tool_search` el servidor entero (11 tools, unos
  15,8 KB por turno), no las 4 que fija el mod en Claude Code.
- Los valores de la lista salen de leer la tabla con `tomllib`; el texto capturado solo se reemite
  si dice exactamente eso (una lista multilínea con `]` en un comentario cortaba la regex).
- Comandos sin modelo y banda de estado: «no disponible» en Codex 0.169.0 (slash commands internos,
  sin prompts personalizados, `/statusline` de campos fijos). La alternativa real es `!comando`, pero
  local-delegate no tiene un subcomando que llame a las tools: seguimiento aparte.
- `codex debug prompt-input` necesita `-c mcp_servers.local-delegate.required=true` para esperar al
  servidor; sin él captura la entrada sin tools.
- Sin hooks nuevos en `codex_hooks.SPECS`: #671 no los necesita.

## Next action

- Sesión principal: integrar en el PR único (rebasar CHANGELOG y `docs/wiki/` con #669/#670), CI
  completo en verde, puerta `memory` y `closed`.
- Persona usuaria: prueba en vivo de `docs/wiki/Codex-capabilities.md` («Pruebas en vivo
  pendientes»), incluida Codex Desktop.
- Abrir tarjeta de seguimiento: subcomando de CLI para `!` en Codex.

## Memory

- Canonical note: sin nota aparte; lo durable va en este handoff (Decisions), `review.md`, el
  CHANGELOG y la wiki; la jornada del vault la escribe la sesión principal.
- Indexes updated: no
