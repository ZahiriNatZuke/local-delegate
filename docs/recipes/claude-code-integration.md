# Recipe: integración con Claude Code (subagentes + skill)

> Esta guía describe una integración **personal** de `local-delegate` con Claude Code.
> **No forma parte del paquete publicable**: es un ejemplo de cómo exprimir el MCP en tu
> propio flujo. Adáptala a tu setup.

El paquete `local-delegate` solo expone las 9 tools MCP (`local_*`). Cómo las uses en Claude
Code —qué subagentes las heredan, con qué skill las gobiernas— es tuyo. Aquí va cómo lo tengo montado.

## 1. Registrar el MCP en Claude Code / Desktop

Con el paquete publicado en PyPI, apunta tu config de MCP a `uvx`:

```json
{
  "mcpServers": {
    "local-delegate": {
      "command": "uvx",
      "args": ["local-delegate-mcp"]
    }
  }
}
```

(Ver `examples/claude_desktop_config.example.json` en el repo.)

## 2. Propagar las tools a tus subagentes (`update_agents.py`)

Si tienes subagentes en `~/.claude/agents/*.md` cuyo frontmatter `tools:` ya incluye
`mcp__local-delegate__local_delegate`, el script [`update_agents.py`](./update_agents.py) les
añade el resto de tools locales de forma **idempotente**:

```bash
python docs/recipes/update_agents.py --dry   # previsualiza
python docs/recipes/update_agents.py          # aplica
```

Solo toca agentes que **ya delegan** (contienen el ancla `local_delegate`) y solo agrega las
tools que falten. No reordena ni toca agentes sin delegación.

## 3. Skill de gobierno de la delegación

La regla de oro ("¿el paso se describe en una frase con formato de salida explícito? → delégalo
a una tool `local_*`") vive en una skill personal (`delegacion-local`) + una entrada en
`CLAUDE.md`. La skill no se distribuye con el paquete; es guía de comportamiento para tu agente.

Esquema de la regla:

- **Delegar** (usar `local_*`): resumir, clasificar, extraer, boilerplate, primera pasada mecánica
  — cualquier paso con formato de salida explícito.
- **No delegar** (hacerlo Claude): razonamiento, arquitectura, criterio, multi-fuente.

## 4. Catálogo de tools

| Tool | Qué hace | Rol de modelo (default) |
|---|---|---|
| `local_summarize` | Resume texto/archivo | mecánico / largo (auto) |
| `local_classify` | Una etiqueta de una lista | mecánico |
| `local_extract` | Campos → JSON | mecánico |
| `local_boilerplate` | Genera código | código |
| `local_delegate` | Escape genérico texto→texto | mecánico (o el que pases) |
| `local_lint_summary` | Resume logs de lint/tests/CI | mecánico / largo (auto) |
| `local_commit_msg` | Mensaje de commit desde un diff | código |
| `local_translate` | Traduce texto/archivo | mecánico / largo (auto) |
| `local_explain_code` | Explica código en prosa | código |

Pasar `path` (en vez de `text`) hace que el MCP lea el archivo **server-side**: el contenido
grande nunca entra al contexto de Claude → ahí está el ahorro real de cuota.
