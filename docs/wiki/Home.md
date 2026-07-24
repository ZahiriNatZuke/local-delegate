# Wiki de local-delegate

Documentación extendida del MCP `local-delegate`. Para empezar rápido, ve al
[README](../../README.md).

## Páginas

- **[Architecture](Architecture.md)** — daemon HTTP/compatibilidad stdio → endpoint OpenAI-compatible, guardrail, logging y dashboard.
- **[Daemon compartido](Daemon.md)** — un solo MCP persistente para Codex, Claude Code y otros clientes.
- **[Configuration](Configuration.md)** — referencia completa de variables de entorno.
- **[Backend versions](Backend-versions.md)** — versiones probadas de llama-server/llama-swap, workspace de referencia y `local-delegate doctor`.
- **[Savings & metrics](Savings-and-metrics.md)** — semántica del ahorro, la web y las APIs.
- **[Publishing](Publishing.md)** — proceso de release (PyPI + registro MCP + CI/OIDC).
- **[Troubleshooting](Troubleshooting.md)** — problemas comunes.

## Recipes

- **[llama-swap (RTX 5060 Ti Blackwell)](../recipes/llama-swap-blackwell.md)**
- **[Ollama](../recipes/ollama.md)**
- **[Integración con Claude Code](../recipes/claude-code-integration.md)** (subagentes + skill)
- **[Backend remoto PC → Mac](../recipes/remote-backend.md)** (MCP local, inferencia remota y paths correctos)
