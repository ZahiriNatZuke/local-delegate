# Investigación — `claude-plugin-and-mods` (2026-10-21)

Cuatro informes en esta carpeta; aquí solo el resumen y lo que decide el diseño. Previa: vault
`projects/local-delegate/investigacion-mods-claude-code-2026-10-21.md`.

| Informe | Tema |
|---|---|
| `research-r1-plugin-format.md` | Formato de plugin de Claude Code, distribución, CI (con pruebas en config aislada) |
| `research-r2-claude-desktop.md` | Claude Desktop: pestaña Code vs chat, `.mcpb`, token, logs |
| `research-r3-install-surface.md` | Qué escribe hoy `install`/`doctor`/`update`/`uninstall` (fichero:línea) |
| `research-r4-mod-design.md` | Diseño de las 4 piezas del mod y línea base de medición |

## Hechos que deciden el diseño

1. **MCP HTTP dentro del plugin funciona**: `Bearer ${LOCAL_DELEGATE_WEB_TOKEN}` se expande;
   `${CLAUDE_PLUGIN_ROOT}` también [R1, PRUEBA].
2. **Las tools del MCP de un plugin se renombran** a
   `mcp__plugin_local-delegate_local-delegate__local_*` [R1 PRUEBA, R2 DOC]. Hoy dependen del nombre:
   filtro de `record_call`, `ANCHOR`/`TOOL_PREFIX` de `agents.py`, `transcripts.py:30,154`
   (`recompute-cost`), `scripts/_claude_bench.py`, listas `tools:` de los agentes del usuario, la
   línea de `ToolSearch` del bloque de `CLAUDE.md`, permisos y conteos del panel [R3].
3. **Si un MCP de usuario apunta a la misma URL que el del plugin, gana el de usuario** y el del
   plugin se descarta [R1, PRUEBA]. Con el MCP dentro del plugin, `install` debe retirar la entrada
   de `~/.claude.json`, o el plugin no aporta su MCP.
4. **La entrada `local-delegate` de `claude_desktop_config.json` también se carga en la pestaña
   Code de Desktop** y gana sobre la de `~/.claude.json` [R2]. En esa pestaña las tools pueden
   seguir con el nombre viejo: hay que aceptar los dos prefijos.
5. **Un hook igual en `settings.json` y en el plugin se dispara dos veces** [R1, PRUEBA + DOC].
6. **Instalación no interactiva**: `claude plugin marketplace add`, `install --config K=V --json`,
   `configure --values-stdin`, `update`, `enable`/`disable`, `list --json` [R1, PRUEBA]. `update`
   deja la versión nueva al lado (atómico en la práctica).
7. **Hooks en Windows**: la forma exec ejecuta `local-delegate` (`.exe` de `uv tool`) por nombre;
   en macOS no hay `python` por defecto → subcomando `local-delegate hook <nombre>` [R1].
8. **Mismo repo como marketplace** (`.claude-plugin/marketplace.json`), plugin en subcarpeta; sin
   `bin/` en la raíz del plugin [R1].
9. **CI sin cuenta**: `claude plugin validate --strict --json`, instalación en config aislada
   (`CLAUDE_CONFIG_DIR`), `claude -p` sin sesión dispara hooks de inicio [R1].
10. **Chat de Desktop**: ignora hooks, mods, agentes y el MCP de un plugin; solo MCP local por
    `claude_desktop_config.json` o `.mcpb` (sin instalación desatendida documentada) [R2]. Si Desktop
    pasa `LOCAL_DELEGATE_WEB_TOKEN` al hijo está **sin medir**; sonda de solo lectura lista
    (`scratchpad/r2/env-name-probe.ps1`), necesita Desktop abierto. Logs vivos en
    `%LOCALAPPDATA%\Claude\Logs\`.
11. **Mods**: comandos sin `:` en el nombre (→ `/local-…`); 0 turnos y 0 $ medidos; fijar 11 tools
    ≈ 5 319 tokens, 4 ≈ 2 000; `/api/stats` del panel responde con el token del entorno [R4].
12. **Lectura transparente**: responder `Read` sin `next` (o cambiar el contenido tras `next`) hace
    que el modelo reciba solo el resumen [R4 PRUEBA]. **Sin medir** si después `Edit` funciona en
    sesión interactiva (en `-p` `Edit` no exige `Read` previo). Los `PreToolUse` de settings corren
    después del último `next` de los mods: el mod y el bloqueo actual chocan.
13. **`install` hoy** [R3]: MCP en `~/.claude.json` (`claude mcp add-json --scope user`,
    `install.py:2441`), hooks copiados a `~/.claude/hooks/local-delegate/` y registrados en
    `settings.json` (2 siempre + 3 con `--enable-read-hook`), skill en `~/.claude/skills`, bloque en
    `CLAUDE.md`, `--agents` edita agentes del usuario (y `uninstall` no lo deshace). Desktop: solo
    `doctor` (`service.desktop_auth`). La definición de cliente está repartida (no hay registro).

## Línea base [R4]

Últimos 28 días, sin pruebas: **25 de 111 sesiones interactivas de Claude Code (23 %)** con ≥ 1
delegación decidida por el modelo (87 terminal + 24 Desktop; 25/167 contando `claude -p`; cota baja
por 164 filas sin `tool_use_id` del 30-sep al 8-oct). Codex: 0. Script:
`scratchpad/r4/baseline_sessions.py` (se versionará en el SDD).

## Decisiones del usuario (2026-10-21)

- Alcance: mods (tools fijas, comandos, cuota, lectura transparente) + plugin para Claude Code y
  Desktop; Codex sin cambios.
- **El MCP va dentro del plugin.**
- **El mod sustituye al bloqueo de lectura** con el plugin activo; `doctor` avisa si quedan los dos.
- **Token del chat de Desktop por variable; si no hereda, literal.**
- **Orden**: plugin primero (con migración y chat de Desktop), luego tools fijas + comandos, luego
  cuota, luego lectura transparente.
