# Changelog

Todos los cambios notables de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

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

[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ZahiriNatZuke/local-delegate/releases/tag/v0.1.0
