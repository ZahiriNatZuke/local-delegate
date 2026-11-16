# Handoff: Entrega Codex nativa: hooks de usuario, instalador y diagnóstico (#669, núcleo; la atribución por sesión va aparte)

## Current state

- SDD status: `result-review`; puertas spec, plan, quality y conformance aprobadas; `memory` pendiente (se aprueba al cerrar, tras mezclar).
- Last completed gate: conformance
- Current revision: rama `feat/codex-native-hooks` sobre `6e973c39`, PR #682 («Refs #669»), abierto (no borrador) el 2026-11-16 a las 11:35 (hora de Uruguay).
- Al cerrar la jornada (11:38): los checks del PR seguían corriendo; en verde los rápidos (matriz CLI 3.11 a 3.14, install-smoke, audit, secrets, GitGuardian, Socket) y pendientes CodeQL, lint, test en Windows, Ubuntu y macOS, plugin, test-lang-es y ci-gate.

## Para retomar

1. `gh pr checks 682`: arreglar cualquier rojo. Mirar en el log de `test (windows-latest)` que
   `test_the_generated_command_runs_through_the_codex_shell` **corrió** (con `CI` falla en vez de
   saltarse) y anotarlo en `verification.md`.
2. Si `main` se movió y hay conflicto (CHANGELOG o wiki), actualizar la rama y resolver.
3. Prueba de confianza de la persona (abajo, «Next action», punto 1). Mezclar lo decide el usuario.
4. Tras mezclar: puerta `memory`, `closed`, tarjeta del Project, y el siguiente PR de #669.

## What changed

- `codex_hooks.py` nuevo: dos hooks consultivos de Codex (`UserPromptSubmit` → `codex-prompt`,
  `SubagentStart` → `codex-subagent-start`), su fusión y retirada en `~/.codex/hooks.json` sin
  mover grupos ajenos, y lo que lee `doctor`.
- `install`/`uninstall`/`update` con la acción `codex-hooks`; check `codex.hooks` (37 checks).
- Textos es/en, CHANGELOG, README, wiki («Hooks de Codex»), `scripts/dev/codex_hooks_live.py`.

## Decisions

- Capa de usuario `~/.codex/hooks.json`, no plugin de Codex: Codex la lee siempre, es JSON y no
  añade el hash de contenido del plugin a la confianza.
- Un grupo es nuestro solo con un único manejador `command`, sin `commandWindows`, que acaba en
  `-m local_delegate.hook codex-<nombre>`. Lo que sobra pasa a `{"hooks": []}` si tiene grupos
  detrás; lo que falta ocupa el primer hueco o va al final. Así ninguna clave de confianza ajena
  cambia y reinstalar devuelve la aprobación anterior si el hook no cambió.
- Comando sin versión con el Python del entorno `uv tool` (sale de `claude_ld_bin`): una
  actualización no obliga a aprobar otra vez.
- BOM = fichero que Codex rechaza (medido): `install` no escribe y `doctor` da `warn`.
- Sin telemetría de hooks para Codex (la serie P-4 es de Claude Code); solo la marca
  `codex-hooks-seen.json` con `{nombre: hora UTC}`.

## Next action

1. **Prueba de confianza (la hace la persona usuaria, no se simula):**
   1. Instalar esta rama con `uv tool`: parar el daemon, `uv tool install --force --no-cache
      <checkout de la rama>` y `local-delegate install --clients codex`. El `~/.codex/hooks.json`
      real ya tiene grupos tuyos: `install` deja `hooks.json.bak` la primera vez.
   2. Abrir Codex y escribir `/hooks`: aparecen `codex-prompt` y `codex-subagent-start` pendientes
      de revisar; aprobar los dos.
   3. Escribir un prompt mecánico, por ejemplo «resume este fichero en cinco viñetas», y mirar
      que el modelo recibe el aviso (con el backend en marcha: con el corte abierto calla).
      Luego pedirle algo que lance un subagente, para `codex-subagent-start`.
   4. `local-delegate doctor`: la línea «hooks de local-delegate en Codex» debe decir «aprobados
      en /hooks: 2 de 2» y la hora en que vio despachar cada uno (`codex-hooks-seen.json` en el
      directorio de datos). Si tras aprobar dice «0 de 2», la clave que calculamos no es la de
      Codex en esa máquina: es un fallo (los tests la comprueban contra sí mismos y el script en
      vivo solo contra `hooks/list`).
   5. Vuelta atrás: `local-delegate uninstall --clients codex --no-mcp --no-memory --no-skill`
      quita solo los hooks, o restaurar `~/.codex/hooks.json.bak`.
2. **Siguiente PR de #669 (atribución por sesión):** hook `PreToolUse` sobre
   `^mcp__local[-_]delegate__` con nota de Codex (prefijo propio en el nombre del fichero), leer
   `_meta.callId` solo de `codex-mcp-client`, decidir qué hacer con `_meta.sessionId`, y apartar
   las filas de Codex del relleno a posteriori, del coste (`excluded`) y darles columna propia en
   el panel y el resumen por sesión. Con sus fixtures de `PreToolUse` (Bash, `apply_patch`, MCP,
   code mode con ids `exec-<uuid>`) y controles del matcher.
3. #670 (lecturas, guard de escritura, shell, `apply_patch`) y #671 (comandos sin modelo, barra de
   estado, matriz de capacidades) parten de `codex_hooks.SPECS`: un hook nuevo es una entrada más.

## Memory

- Canonical note: pendiente (se decide al cerrar)
- Indexes updated: no
