# Changelog

Todos los cambios notables de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

## [0.2.0] - 2026-07-09

### Added
- Nueva tool `local_status` (solo lectura): estado del backend (`/models`), catálogo de
  roles activo con `max_chars`, stats del log del mes actual, estado de la web de
  métricas, y VRAM (`nvidia-smi`) + modelo montado en llama-swap (`/running`) best-effort.
  10 tools en total.
- `local_extract` pide `response_format` con JSON schema por defecto
  (`LOCAL_DELEGATE_JSON_SCHEMA=auto|on|off`); si el backend responde 400 en modo `auto`,
  reintenta una vez sin schema.
- Feedback de ahorro: `_chat` anexa "leído server-side: N chars ≈ M tokens que no
  entraron a tu contexto" cuando `source=path` (apagable con `LOCAL_DELEGATE_FEEDBACK=0`).
- Log rotado por mes (`usage-YYYYMM.jsonl` en `LOCAL_DELEGATE_LOG_DIR`); el `usage.jsonl`
  legado se sigue leyendo como fuente adicional, sin migrarlo.
- Dashboard: selector de rango real (Hoy/7d/30d/mes anterior/todo/personalizado) que
  refetch server-side (`GET /api/events?from=&to=`, `GET /api/stats?from=&to=`) en vez de
  filtrar client-side; solo abre los archivos de log que tocan el rango pedido.
- Visibilidad de delegaciones en curso: `GET /api/inflight` y `GET /api/backend` (proxy de
  `/running` de llama-swap), con una tarjeta "En curso" en el dashboard.
- `LOCAL_DELEGATE_ALLOWED_DIRS`: restringe opcionalmente el parámetro `path` de todas las
  tools a una lista de raíces permitidas (`;` como separador). Vacío = sin restricción.
- Docstrings de las tools que aceptan `path` indican explícitamente cuándo preferirlas
  sobre leer el archivo con `Read`.
- Recipe de hooks de Claude Code (`docs/recipes/claude-code-hooks.md` +
  `docs/recipes/hooks/`) que sugieren delegar sin bloquear nunca la tool original.
- `update_agents.py` v2: mantiene un bloque de catálogo en prosa en los agentes que
  delegan, además de la línea `tools:`.

### Changed
- `_post_chat` devuelve un `ChatResult` estructurado (`ok`, `error`, `finish_reason`,
  `tokens_in`, `tokens_out`) en vez de codificar el error en el propio texto; el log de
  uso ahora registra tokens reales del backend cuando están disponibles, `finish_reason`,
  `error`, truncados y la versión del paquete.
- Cliente `httpx` module-level con keep-alive entre delegaciones.
- Escritura del log protegida con `filelock` (best-effort: si no consigue el lock en 1s,
  escribe igual, nunca bloquea la tool).

### Fixed
- Salida truncada por `max_tokens` ahora produce un aviso visible en el texto devuelto
  (antes se truncaba en silencio); igual para la entrada truncada al leer un `path`.
- Bloques `<think>`/`<thinking>` de modelos razonadores (Qwen3, R1-distill) se eliminan
  de la salida antes de devolverla.
- `local_commit_msg` valida `style` en vez de caer a `'plain'` en silencio si el valor no
  es reconocido.
- `local_extract` enruta por tamaño de entrada (mecánico/largo) igual que las demás tools
  con `path`, en vez de usar siempre el modelo mecánico.

## [0.1.1] - 2026-07-08

### Fixed
- Dashboard: el sparkline del KPI "Contexto conservado" ya no dibuja una línea sobre el texto
  cuando el ahorro es 0; ahora se ancla al borde inferior (`y.min=0`).

### Added
- Recipes de backends en `docs/recipes/`: llama-swap (RTX 5060 Ti Blackwell) y Ollama.
- Sección *Demo* en el README con screenshot del dashboard de ahorro.
- Wiki en `docs/wiki/` (+ wiki nativa de GitHub): Architecture, Configuration, Savings & metrics, Publishing, Troubleshooting.

### Changed
- `publish.yml`: `uv publish --check-url` para hacer la publicación idempotente ante
  re-ejecuciones sobre un tag existente.

## [0.1.0] - 2026-07-07

### Added
- Servidor MCP stdio con 9 tools texto→texto (`local_summarize`, `local_classify`,
  `local_extract`, `local_boilerplate`, `local_delegate`, `local_lint_summary`,
  `local_commit_msg`, `local_translate`, `local_explain_code`).
- Cliente genérico de cualquier endpoint OpenAI-compatible (llama-swap, Ollama, LM Studio, vLLM),
  configurable por variables de entorno; sin rutas hardcodeadas (`platformdirs` para el log).
- Web de métricas embebida (dashboard de uso/ahorro) en un hilo daemon.
- Logging JSONL por llamada (`usage.jsonl`) para calcular el ahorro de contexto.
- Auto-arranque de llama-swap opcional (opt-in, `LOCAL_DELEGATE_AUTOSTART=0` por defecto).
- Empaquetado para PyPI (`local-delegate-mcp`) ejecutable con `uvx`; `server.json` para el
  registro oficial de MCP.

[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ZahiriNatZuke/local-delegate/releases/tag/v0.1.0
