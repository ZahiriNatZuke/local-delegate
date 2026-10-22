# Brief — SDD `claude-plugin-and-mods`

## Objetivo (decisión del usuario, 2026-10-21)

Aprovechar los **mods** de Claude Code y **empaquetar local-delegate como plugin** para Claude Code
y Claude Desktop. **Codex se queda como hasta ahora** (instalador y hooks actuales).

Alcance aprobado:

1. **Tools `local_*` siempre cargadas** (fuera de ToolSearch), con la lista configurable.
2. **Comandos sin turno del modelo**: `/local:resumir`, `/local:commit`, `/local:lint`.
3. **Cuota y ahorro en la barra de estado o una banda** (`session.measure` + daemon).
4. **Lectura delegada transparente**: retener un `Read` grande y ofrecer «resumir con el modelo
   local / leer entero» (variante con botones, al estilo de `blast-radius`).
5. **Empaquetar todo como plugin** (MCP + hooks + mod + skill + agentes) para Claude Code y
   Claude Desktop, que sustituya lo que hoy escribe `install` para esos clientes, con migración.

## Punto de partida

- Investigación previa: vault `projects/local-delegate/investigacion-mods-claude-code-2026-10-21.md`
  (léela con `mcp__obsidian__read_note` o resúmela con `local_summarize`). Mod de prueba `ld-probe`
  (si sigue): `C:/Users/Yohan/AppData/Local/Temp/claude/D--Projects-local-delegate/ed2ae533-e76e-4dce-ae5d-1dd44f83b27e/scratchpad/mods-research/ld-probe/`.
- Skill `plugin-authoring` (tool Skill) con la API de mods y `types/claude-code.d.ts`.
- Doc oficial: `https://code.claude.com/docs/en/plugins/mods/*` y la de plugins de Claude Code.
- Backlog del vault `projects/local-delegate/backlog.md`: §1.1 (Claude Desktop fuera del registro:
  fase A hecha, fase B pendiente), §4.1 ideas 2 y 3 (comandos, plugin).
- Repo: `src/local_delegate/{install,clients,agents,checks,update,daemon,cli}.py`, `hooks/` o
  scripts de hooks, `docs/wiki/`.

## Lecciones que aplican (memoria del proyecto)

- **La obediencia no viene de la prosa**: una instrucción se obedece cuando el camino alternativo
  no existe, nunca se equivoca y esperar no cuesta. Diseñar para eso, no para convencer.
- **Escritura, diagnóstico y reparación**: añadir un destino son tres verbos (`install`, `doctor`,
  `update`); media abstracción da un falso OK.
- **Probar la pieza no es probar el uso**: el banco de pruebas de mods (`claude plugin test`) NO
  imita bien al motor (dice que `$.mcp.call` no dispara hooks y en sesión real sí): la integración
  se prueba en vivo con `claude -p --plugin-dir … --max-turns 1` **desde PowerShell** (desde Git
  Bash convierte rutas y gasta un turno real: pasó, 0,52 $), dentro de una ventana de prueba
  (`local-delegate test-window start/stop`).
- Mods: acceso anticipado, sin sandbox; el token del daemon se lee del entorno y nunca se escribe.
- Reiniciar el daemon tira el MCP de la sesión; no se reinicia el daemon desde un agente.

## Reglas para agentes

- Primer paso: cargar las `local_*` con ToolSearch y usarlas (ficheros grandes con `path`, páginas
  web volcadas a fichero y resumidas); listar las llamadas en la entrega.
- Responder en español; código y comentarios en inglés; textos al usuario por catálogo es/en.
- No tocar `~/.claude/settings.json`, `~/.claude.json`, `claude_desktop_config.json` reales, el
  daemon ni el `uv tool` instalado. Pruebas en carpetas propias del scratchpad o HOME simulado.
- Comandos pesados con `bash ~/.claude/scripts/pesado.sh …` desde la tool Bash.
- Nada huérfano al acabar.
