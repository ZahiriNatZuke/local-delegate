# Research — `local-delegate update`: actualizar, completar lo que falte y dejar el daemon arriba

## Current behavior

`scripts/update_to_latest.sh` (175 líneas de bash) hace tres cosas: pregunta a PyPI la última
versión, reemplaza el pin `local-delegate-mcp==X.Y.Z` en `~/.claude.json` y `~/.codex/config.toml`
si lo encuentra, y precalienta la caché de `uvx`. **No reinicia nada**: su línea 171 se limita a
`"Listo. Reinicia Claude Code y Codex para que tomen ${VERSION}."`

Tres defectos confirmados por ejecución:

1. **No reinicia el daemon**, así que hay que hacer a mano lo que se hace siempre después.
2. **En esta PC no hace nada útil**: aquí la entrada MCP es `type: http` contra el 9393 y **no hay
   pin que cambiar**. El script imprime «sin entrada / sin pin — no se toca» y termina.
3. **No viaja a la máquina que debe actualizar.** Dato duro: el wheel publicado de la 0.13.1 tiene
   **28 entradas y ninguna de `scripts/`**, porque `pyproject.toml:77-78` empaqueta solo
   `src/local_delegate`. El script cuyo propósito es actualizar la Mac solo existe allí si el repo
   está clonado; el mecanismo de despliegue real es `uvx` contra PyPI.

## El criterio que faltaba: CLI contra `scripts/`

`pyproject.toml:62-66` expone **dos entry points** (`local-delegate` y `local-delegate-mcp`) sobre
`local_delegate:main`, y el CLI ya tiene `serve`, `install`, `uninstall`, `check-llamaswap`, `init`,
`doc` y `benchmark`. El paquete ya es servidor MCP **y** CLI; no hay frontera nueva que cruzar.

| ¿Quién lo corre? | Dónde vive | Por qué |
|---|---|---|
| El usuario, en su máquina | subcomando del CLI | viaja en el wheel, sale en `--help`, se prueba con pytest, corre en los tres sistemas |
| El repo o el CI | `scripts/` | no debe viajar al wheel; su usuario es el mantenedor |

Con ese criterio, hoy están mal colocados **tres** ficheros: `scripts/update_to_latest.sh` (este
change), `scripts/install_claude_code_hooks_macos.sh` y `docs/recipes/update_agents.py` (el backlog
ya lo tenía anotado como «encajaría como `local-delegate install --agents`»). Los otros nueve
(`release.py`, `bump_version.py`, `check_vendor.py`, `extract_dashboard_js.py`,
`setup_repo_security.sh`, los dos canarios de macOS, `check_install_handshake.py` y `scripts/dev/*`)
**están bien** donde están: los corre el repo o el CI.

Los dos que sobran se anotan en el backlog como changes propios; **no entran aquí**.

## Impact map

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
|---|---|---|---|
| `src/local_delegate/cli.py` (615 líneas) | subcomandos con `sub.add_parser(...)` | **nuevo** `update` | `cli.py:378-380` |
| `src/local_delegate/install.py` (591) | `Options` + `plan_install()` → `list[Action]` + `apply()` | se reusa tal cual para completar lo que falte | `install.py:312,343,575` |
| `src/local_delegate/daemon.py` (195) | `query_daemon(host, port)` devuelve `{version, pid, host, port}`; estado en `config.LOG_DIR/daemon.json` | fuente de verdad para «¿está arriba?» y «¿reinició de verdad?» | `daemon.py:53-54,97-110` |
| **nuevo** `src/local_delegate/update.py` | — | pin + completar + reinicio, con la misma forma `plan_* / apply` | — |
| `scripts/update_to_latest.sh` | toda la lógica | envoltorio fino que delega en el CLI | — |
| `docs/wiki/Daemon.md` | receta de Windows detallada; macOS/Linux en **una frase** | gana receta de LaunchAgent y de `systemd --user` | `Daemon.md:71-73` |
| `src/local_delegate/autostart.py` | `ensure_backend()` solo **arranca** llama-swap si no responde, y es opt-in | referencia para `--restart-backend`; **no** se toca | `autostart.py:44-51` |

## Existing conventions

- **`plan_* / apply(dry_run)`**: `install.py` no toca disco al planificar; `apply()` ejecuta y
  respeta `--dry-run`. `update` debe seguir exactamente ese patrón.
- **Copia `.bak` antes de escribir** y **conservar el terminador de línea** del fichero
  (`install.py:87-111`) — el bug del instalador que reescribía el `CLAUDE.md` entero.
- **Idempotencia**: correrlo dos veces no debe duplicar nada; el script actual ya lo cumplía y
  `tests/test_install.py` lo verifica contra `tmp_path`.
- **`--home` para HOME simulado**, patrón de `install` y del script; hace testeable todo sin tocar el
  HOME real (`scripts/dev/README.md`, sección 3).
- Tests de scripts como módulo cargado con `importlib` (`tests/test_bump_version.py:18-25`). **No hay
  ningún test de un `.sh` en el repo** — otra razón para que la lógica sea Python.

## Mecanismos de arranque por sistema

| Sistema | Mecanismo | Detección | Reinicio |
|---|---|---|---|
| Windows | Tarea programada `LocalDelegateDaemon` (`Daemon.md:85-92`) | `schtasks /Query /TN` | matar el pid del estado + `schtasks /Run /TN` |
| macOS | LaunchAgent **que hoy no existe**; hay que escribir la receta | `launchctl print gui/<uid>/<label>` | `launchctl kickstart -k gui/<uid>/<label>` |
| Linux | `systemd --user`, tampoco documentado | `systemctl --user cat <unit>` | `systemctl --user restart <unit>` |
| Cualquiera | sin gestor registrado | — | matar el pid + relanzar `serve` desacoplado |

En Windows el procedimiento manual que funciona (y está en la memoria del proyecto) es
**`Stop-Process` del pid + `Start-ScheduledTask`**, no `Stop-ScheduledTask`: la tarea lanza un
launcher bajo `conhost --headless` y detener la tarea no siempre se lleva al proceso hijo.

## Dependencies and integrations

- Sin dependencias nuevas: `httpx2` (ya en runtime, lo usa `query_daemon`), `platformdirs` (ya, vía
  `config.LOG_DIR`) y `subprocess`/`urllib` de la stdlib.
- PyPI se consulta por el **índice simple** y no por `/pypi/<pkg>/json`, que se sirve con caché y
  puede tardar en reflejar una release recién publicada — visto en vivo con la 0.12.0
  (`update_to_latest.sh:52-53`). Ese detalle hay que conservarlo al portar.
- El daemon de esta PC corre del **venv editable del repo**, así que aquí «actualizar» no es cambiar
  un pin: es `git pull` + `uv sync` + reiniciar.

## Risks and unknowns

**Confirmado por ejecución:**

- `/api/daemon` responde `{"service":"local-delegate","mode":"daemon","version":"0.13.1","pid":27032,…}`.
- El wheel no contiene `scripts/` (28 entradas, 0 coincidencias).
- `codex mcp list` ve `local-delegate` como HTTP contra el 9393, sin pin.

**Sin validar todavía:**

- El comportamiento exacto de `launchctl kickstart -k` **no se puede probar en esta máquina**: no hay
  macOS. Se cubre con tests contra un doble del ejecutor de comandos, y la ejecución real queda como
  riesgo residual declarado, junto al pendiente ya conocido de que el instalador nunca corrió en macOS.
- Si el daemon corre desde un venv editable, reiniciarlo **no cambia la versión**: solo recarga el
  código del working tree. El caso hay que detectarlo y decirlo, o el usuario leerá «reiniciado» y
  esperará una versión nueva que nadie trajo.
- Matar el pid del `daemon.json` es seguro solo si ese pid **sigue siendo** el daemon: un pid
  reciclado por otro proceso sería un disparo a ciegas. Hay que confirmar contra `/api/daemon` antes
  de matar, nunca contra el fichero a secas.
