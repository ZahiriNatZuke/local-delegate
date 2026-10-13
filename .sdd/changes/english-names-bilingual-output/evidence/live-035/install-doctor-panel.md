# Pasada en vivo de la 0.35.0 candidata: install, doctor, update, panel y P-4

Fecha: 2026-10-13 (UTC). Rama `main` en `2bca590`. Primera mitad de la pasada de plan.md §4.3; las
11 tools por MCP las pasa otro agente dentro de la misma ventana de prueba.

## Ventana de prueba (REQ-038)

`local-delegate test-window start --label "SDD english-names, 0.35.0 candidata, pasada en vivo"`
→ **`w-20261013T123443Z`**, abierta desde 2026-10-13T12:34:43Z. Se deja **abierta** para la
pasada de las tools.

## 1. Instalación de la candidata

- Primer intento con el daemon arriba: **falló** a mitad y dejó el entorno de uv roto
  (`error: failed to remove directory ~\AppData\Roaming\uv\tools\local-delegate-mcp\Lib: Acceso
  denegado. (os error 5)`; después `local-delegate --version` daba
  `ModuleNotFoundError: No module named 'annotated_types'`). El daemon tiene abiertos ficheros del
  entorno de la tool.
- `schtasks /End /TN LocalDelegateDaemon` dice `CORRECTO` pero **no para el proceso** `pythonw`
  (el lanzador está desacoplado); hubo que pararlo por pid.
- Con el daemon parado, `uv tool install --force --reinstall --no-cache ".[llamaswap]"` (bajo
  `pesado.sh`): OK. `local-delegate --version` → `local-delegate 0.34.0`: el `pyproject.toml` de
  `main` sigue en 0.34.0 (el número se sube en la release). El código instalado es el renombrado
  (módulos `recompute.py`, `cooldown.py`, `quota.py`…, skill `resources/skills/local-delegation`).
- Lección para la memoria del proyecto: **parar el daemon antes** de `uv tool install --force`
  en Windows; el orden «instalar y luego `schtasks /Run`» no basta con el daemon corriendo.

## 2. `install --mcp-mode http --web-token-env --enable-read-hook --agents`

rc=0. Lo relevante de la salida:

- `[prune] ~\.claude\skills — retira skills de una versión anterior (delegacion-local)` →
  `retiradas 1: delegacion-local`; igual en `~\.config\opencode\skill`.
- `[copy]` de `local-delegation` en ambos sitios.
- `[agents] ~\.claude\agents — actualiza 27 subagente(s)` (catálogo `replaced`, +0 tools).
- Bloques gestionados actualizados en `~\.claude\CLAUDE.md`, `~\.codex\AGENTS.md` y
  `~\.config\opencode\AGENTS.md`.
- Entradas MCP de Claude Code, Codex y opencode registradas (http).
- El propio `install` levantó el daemon por la tarea programada (`daemon 0.34.0 arriba`).

Comprobaciones a mano:

| Comprobación | Resultado |
| --- | --- |
| `~/.claude/skills/local-delegation/` existe, `delegacion-local/` no | OK |
| `~/.config/opencode/skill/local-delegation/` existe, `delegacion-local/` no | OK |
| Bloque de `~/.claude/CLAUDE.md`: menciones `local-delegation` / `delegacion-local` | 1 / 0 |
| Bloque de `~/.codex/AGENTS.md` | 1 / 0 |
| Bloque de `~/.config/opencode/AGENTS.md` | 1 / 0 |
| Subagentes con catálogo (`~/.claude/agents/*.md`) | 27, cada uno con las 11 `local_*` en `tools:` |
| `.bak` nuevos | ninguno; los 27 `.bak` de agentes son del 2026-07-31 |

Detalle menor: con la salida redirigida a fichero, sin `PYTHONIOENCODING=utf-8`, los acentos y los
`→`/`·` salen como `�` (consola cp1252). En terminal interactiva o con la variable, bien.

## 3. Daemon

Tarea programada `LocalDelegateDaemon`. Reiniciado dos veces: por `install` (al encontrarlo parado)
y por `local-delegate update` («el servicio paró pero el pid … sigue sirviendo (launcher
desacoplado): se le manda la señal al proceso confirmado» → arriba con pid nuevo). Responde en
`http://127.0.0.1:9393` (401 sin token, 200 con sesión).

## 4. `doctor`

rc=1 por un único `[WARN]` (nombres obsoletos, esperado en esta PC). Grupos: Entorno, Andamiaje,
Servicios, Versiones. `memoria global` y `skill local-delegation` en OK tras el install.

```text
local-delegate doctor — diagnóstico del andamiaje, los servicios y el backend local

LLAMASWAP_EXE:    D:\Projects\llms\llama-swap-v255\llama-swap.exe
LLAMASWAP_CONFIG: D:\Projects\llms\llama-swap\config.yaml
Backend BASE_URL: http://127.0.0.1:9292/v1 — arriba
HOME:             ~

Estados: [ OK ] a punto · [WARN] revisar · [FALT] falta · [ -- ] no se pudo comprobar

Entorno (el CLI y los clientes):
  [ OK ] CLI local-delegate: ~\.local\bin\local-delegate.EXE (versión 0.34.0)
  [ OK ] versión publicada: 0.34.0 (la última publicada)
  [ OK ] clientes: detectados: Claude Code, Codex, opencode
  [ OK ] clientes MCP observados: claude-ai 0.1.0 [2025-11-25] sin elicitation; claude-ai (via mcp-remote 0.1.37) 0.1.0 [2025-11-25] sin elicitation; claude-ai (via mcp-remote 0.13.5) 0.1.0 [2025-11-25] sin elicitation; claude-ai (via mcp-remote 0.8.2) 0.1.0 [2025-11-25] sin elicitation; claude-ai (via mcp-remote 0.8.5) 0.1.0 [2025-11-25] sin elicitation; claude-ai (via mcp-remote 0.8.6) 0.1.0 [2025-11-25] sin elicitation; claude-code 2.1.296 [2026-07-28] elicitation; codex-mcp-client 0.160.0 [2025-06-18] elicitation; local-agent-mode-local-delegate 1.0.0 [2025-11-25] sin elicitation; local-agent-mode-local-delegate (via mcp-remote 0.1.37) 1.0.0 [2025-11-25] sin elicitation; local-agent-mode-local-delegate (via mcp-remote 0.13.5) 1.0.0 [2025-11-25] sin elicitation; local-agent-mode-local-delegate (via mcp-remote 0.8.2) 1.0.0 [2025-11-25] sin elicitation; local-agent-mode-local-delegate (via mcp-remote 0.8.5) 1.0.0 [2025-11-25] sin elicitation; local-agent-mode-local-delegate (via mcp-remote 0.8.6) 1.0.0 [2025-11-25] sin elicitation; local-agent-mode-local-delegate (via mcp-remote 0.8.7) 1.0.0 [2025-11-25] sin elicitation; mcp 0.1.0 [2025-11-25] sin elicitation; mcp-remote-fallback-test 0.0.0 [2025-11-25] sin elicitation
  [ OK ] cadenas de respaldo: cadenas válidas; sin residente
  [WARN] nombres obsoletos: en la shell: LD_HOOK_READ_BLOQUEAR está obsoleto: usa LD_HOOK_READ_BLOCK (se retirará tres versiones menores después) | en el env de settings.json: LD_HOOK_READ_BLOQUEAR está obsoleto: usa LD_HOOK_READ_BLOCK (se retirará tres versiones menores después)
         arréglalo con: renombra LD_HOOK_READ_BLOQUEAR a LD_HOOK_READ_BLOCK
  [ OK ] coste y relleno: el último cotejo (2026-10-06T19:14:04+00:00) cuadra: 144 fila(s) juzgadas con la tabla de precios del 2026-10-06
  [ OK ] ventanas de prueba: 59 ventanas, 1 abierta(s)

Andamiaje (hooks, skill, memoria y entradas MCP):
  [ OK ] hooks copiados: 5 script(s) en ~\.claude\hooks\local-delegate
  [ OK ] hooks huérfanos: ninguno suelto en ~\.claude\hooks
  [ OK ] hooks registrados: 5 registrado(s): PreToolUse/mcp__local-delegate__.*, PreToolUse/Read, PreToolUse/mcp__.+__(read_[a-z_]*|get_file_contents), PreToolUse/Bash|PowerShell, UserPromptSubmit
  [ OK ] skill local-delegation: Claude Code: instalada en ~\.claude\skills\local-delegation · opencode: instalada en ~\.config\opencode\skill\local-delegation
  [ OK ] memoria global: Claude Code: bloque al día en ~\.claude\CLAUDE.md · Codex: bloque al día en ~\.codex\AGENTS.md · opencode: bloque al día en ~\.config\opencode\AGENTS.md
  [ OK ] MCP en Claude Code: registrado en ~\.claude.json (http http://127.0.0.1:9393/mcp)
  [ OK ] MCP en Codex: bloque gestionado en ~\.codex\config.toml (http)
  [ OK ] MCP en opencode: registrado en ~\.config\opencode\opencode.jsonc (remote http://127.0.0.1:9393/mcp)

Servicios:
  [ OK ] daemon: local-delegate 0.34.0 · pid 30744 · http://127.0.0.1:9393/mcp
  [ OK ] backend: http://127.0.0.1:9292/v1/models responde
  [ OK ] credencial del backend: el backend exige credencial y las entradas MCP van por el daemon (http)
  [ OK ] token del puerto del daemon: el puerto del daemon exige token y las entradas MCP lo referencian
  [ OK ] token de Claude Desktop: el daemon acepta el token de Claude Desktop (escrito literal en su configuración)

Versiones (instalada vs probada; usa --online para comparar con GitHub):
  [ OK ] llama-swap: v255 (= probada)
  [ OK ] llama-server: b10909 (= probada)
  [ OK ] residencia de llama-swap: sin residente (recomendado) (la config de este shell)
  [ OK ] turno del daemon: turno activo según el daemon (choques: swap [swap, no exclusivo]: gemma3-4b, gemma4-26b-a4b, qwen36-35b-a3b, qwen35-2b, gemma4-12b)

Resultado: 1 aviso(s) — revisa [FALT] y [WARN] arriba.
```

## 5. `update`

- `update --dry-run`: «Nada que reparar: el andamiaje está completo y los pines al día.»
- `update` (real): mismo diagnóstico, reinicia el daemon, no escribe nada más.
- `update --no-restart` (segunda pasada): «Nada que reparar…», no toca nada.
- Tras las tres, la candidata sigue instalada (`resources/skills/local-delegation` presente): el pin
  a la última de PyPI no reinstaló la 0.34.0 publicada.

## 6. Panel

Playwright contra `http://127.0.0.1:9393/`. Autenticación: primera petición con
`Authorization: Basic` (token leído del entorno de usuario, no pedido a nadie); la respuesta deja
la cookie **`ld_session`** (`HttpOnly`, `SameSite=Lax`). Recargado solo con la cookie:

- Consola: **0 errores**.
- `/api/status`, `/api/backend`, `/api/events`, `/api/stats`, `/api/inflight`,
  `/api/backend/stats`, `/api/hooks`, `/api/system`: todas **200**.
- Diálogo «Coste, cuota e imágenes»: «Densidad de Claude por familia de tokenizador (**nueva 6**):
  celda medida 2, sin numerar 4, conservadora 0; …» → la familia sale en palabras en español.
- Los 8 errores de consola de la primera carga eran de la cabecera `Authorization` extra aplicada a
  terceros (preflight CORS de fonts.gstatic.com y de la inyección de Kaspersky), no del panel.

Capturas (el pie con la ruta del directorio de datos se sustituyó por `~` antes de capturar):
`panel-claro.png`, `panel-oscuro.png`, `panel-coste-claro.png`, `panel-coste-oscuro.png`.

## 7. Comando de P-4

`uv run python scripts/medir_enfriamiento.py --desde 2026-09-15T19:26:41` (bajo `pesado.sh`): rc=0,
sin trazas. 280 delegaciones, 58 filas apartadas por 18 ventanas de prueba, 0 episodios,
**RESULTADO: no concluyente** (lo esperable).

## 8. Avisos de alias

- `LD_HOOK_READ_BLOQUEAR` (shell y `env` de `settings.json`): `doctor` avisa
  «LD_HOOK_READ_BLOQUEAR está obsoleto: usa LD_HOOK_READ_BLOCK (**se retirará tres versiones
  menores después**)».
- `local-delegate recalcular-coste`: stderr «aviso: recalcular-coste está obsoleto: usa
  recompute-cost (se retirará tres versiones menores después)», rc=0, y hace el recálculo.
- `LOCAL_DELEGATE_MODEL_FAST=x`: «ya no tiene efecto desde la 0.30.0».
- `recalcular-coste --help` no muestra el aviso (argparse sale antes de llegar a él).

**No dice «0.38.0»**, y es por diseño: los alias nuevos están registrados con
`introduced="UNRELEASED"` (`deprecations.py`), y `removal_version()` devuelve `None` hasta que la
release fije `introduced="0.35.0"`; entonces el texto pasa a «se retira en la 0.38.0». Queda como
**paso obligatorio de la release** y para comprobar en la pasada de la versión publicada.

## Observaciones

1. **Salida de `recalcular-coste`/`recompute-cost` con claves en inglés dentro de una frase en
   español**: «Líneas del log rellenadas: 484 (ambiguous: 7, exact: 76, no_match: 163, window: 181,
   window+path: 57).» En la 0.34.0 la misma línea decía `exacto`, `ventana`, `ambiguo`,
   `sin_cruce`: el renombrado de valores de A5a se ve en un texto de salida
   (`recompute.py:374`, que imprime las claves de `matches` tal cual). Roza REQ-017; no se corrige
   aquí.
2. Instalar con el daemon arriba rompe el entorno de uv en Windows (ver §1).
