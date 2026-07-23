# Architecture

## Visión general

```text
Codex / Claude Code / otros
        │  Streamable HTTP /mcp
        ▼
  local-delegate daemon ──HTTP POST──▶ endpoint OpenAI-compatible
  (MCP + dashboard)       /chat/completions  (llama-swap · Ollama · LM Studio · vLLM)
        │
        ├─ escribe usage-YYYYMM.jsonl
        └─ sirve dashboard web en /
```

`local-delegate` es un servidor MCP (Python + FastMCP). El modo recomendado para varias sesiones
es el daemon singleton Streamable HTTP; el transporte `stdio` sigue disponible sin argumentos para
compatibilidad. Expone 11 tools texto/imagen→texto
(10 texto→texto + `local_describe_image` imagen→texto). Cada tool arma un prompt con *guardrails*,
hace `POST /chat/completions` al endpoint configurado y devuelve **solo texto**.

## Decisiones de diseño

- **Cliente genérico.** El paquete solo asume "un endpoint OpenAI-compatible en una URL"
  (`LOCAL_DELEGATE_BASE_URL`). No sabe ni le importa qué motor lo sirve, en qué hardware, ni con
  qué modelos. Todo lo específico (llama-swap, GPU, GGUF) es configuración + recipes.
- **Texto→texto, sin tool-calling en el modelo local.** Los modelos locales NO usan function
  calling: el server construye el prompt completo y espera texto plano. Esto los hace robustos y
  compatibles con cualquier backend, incluso modelos pequeños.
- **El guardrail.** Cada llamada inyecta un system prompt: *"Responde directo desde el input. NO
  uses herramientas, NO busques en internet. Output EXACTO: <formato>. Nada fuera del formato."*
  Mantiene la salida acotada al formato pedido.
- **`path` server-side = el ahorro real.** `summarize`/`extract`/`lint_summary`/… aceptan `path`:
  el MCP lee el archivo **en tu máquina** y solo devuelve el resultado corto. El contenido grande
  **nunca entra al contexto de Claude** → ahí está la cuota conservada.
- **Roles de modelo.** Las tools enrutan a 4 roles de texto (mecánico, largo, código, rápido) más
  un rol de visión (`local_describe_image`), cada uno un id de modelo configurable. Las que
  dependen del tamaño del input eligen mecánico vs. largo por un umbral
  (`LOCAL_DELEGATE_LONG_INPUT_CHARS`).
- **Backend opt-in.** El auto-arranque de un backend (llama-swap) está **desactivado por defecto**
  (`LOCAL_DELEGATE_AUTOSTART=0`); el paquete asume que tu endpoint ya corre.

## Módulos

| Módulo | Rol |
|---|---|
| `server.py` | Las 11 tools, `_chat`/`_post_chat`, guardrail, logging |
| `config.py` | Toda la config por env + `platformdirs` (log de usuario) |
| `autostart.py` | Arranque opt-in de llama-swap (específico de ese backend) |
| `daemon.py` | ASGI singleton: MCP `/mcp`, dashboard `/`, lock y estado por usuario |
| `web/metrics.py` | Dashboard de ahorro (FastAPI, montado por el daemon o embebido en `stdio`) |
