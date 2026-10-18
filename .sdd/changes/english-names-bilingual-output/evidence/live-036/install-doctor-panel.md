# Pasada en vivo de la 0.36.0 candidata: install, doctor, hooks y panel

Fecha: 2026-10-18 (UTC). Rama `release/0.36.0` con la versión en 0.36.0. Segunda mitad de la
pasada de plan.md §4.3 (las 11 tools están en `tools.md`). Las dos ventanas de prueba:
`w-20261018T132615Z` (en) y `w-20261018T134632Z` (es).

## 1. Instalación de la candidata

- Daemon parado antes de instalar (`schtasks /End` y el `pythonw` por pid, la lección de la
  0.35.0), `uv tool install --force --reinstall --no-cache ".[llamaswap]"` bajo `pesado.sh` y
  `schtasks /Run`. `local-delegate --version` → 0.36.0; `daemon.json` → 0.36.0; `/mcp` sin token
  da 401 (vivo).
- Lanzador `start-local-delegate-secure.ps1` sin tocar: huella
  `c96f022aeb1b2570fc273419203f2f870d7a13022c373e35f7ae6af7ae69f69a` al principio y al final.

## 2. `install --mcp-mode http --web-token-env --enable-read-hook --agents` real

| Paso | en (`LOCAL_DELEGATE_LANG=en`) | es (`LOCAL_DELEGATE_LANG=es`) |
| --- | --- | --- |
| rc | 0 | 0 |
| `language.json` | `{"lang": "en", "source": "variable"}` | `{"lang": "es", "source": "variable"}` |
| Salida del propio `install` | en inglés (`[MISS]` en la leyenda) | en español (`[FALT]`) |
| Skill `local-delegation` (Claude Code y opencode) | `(en)` | `(es)`; `SKILL.md` empieza por «## Regla de oro» |
| Bloque de `CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.config/opencode/AGENTS.md` | `(en)`, actualizado | `(es)`, actualizado; **un solo** bloque en `CLAUDE.md` |
| 27 subagentes | catálogo reemplazado, +0 tools | catálogo reemplazado, +0 tools |
| 5 hooks en `settings.json` | 5 registrados (5 entradas previas quitadas) | igual |
| Entradas MCP (Claude Code, Codex, opencode) | http, registradas | igual |
| Daemon | `install` lo reinició: 0.36.0, pid 54200 | `install` lo reinició: 0.36.0, pid 42728 |

- `settings.json` tras los dos `install`: **igual en contenido** al de antes (solo cambia el orden de
  la clave `matcher` dentro de dos grupos). `env.LD_HOOK_READ_BLOCK = "1"` sigue: el bloqueo de
  lectura sigue **encendido**, y no existe `~/.claude/local-delegate-block-off`.
- La entrada MCP de Claude Code (`~/.claude.json`) es `http` con
  `Authorization: Bearer ${LOCAL_DELEGATE_WEB_TOKEN}`; con la variable de usuario, un `initialize`
  al `/mcp` da **200**.
- Salidas completas (rutas con `~`): `install-en.txt`, `install-es.txt`.

## 3. `doctor` y `local_status` (REQ-019, REQ-047)

| | en | es |
| --- | --- | --- |
| `doctor`, cabecera | `Language: en (preference; ~\AppData\Local\local-delegate\language.json)` y `Response: en (preference)` | `Idioma: es (preferencia; ~\AppData\Local\local-delegate\language.json)` y `Respuesta: es (preferencia)` |
| `doctor`, remedio D11 | «to follow the system again, delete `…language.json` and run `local-delegate install`» | «para volver a seguir al sistema, borra `…language.json` y ejecuta `local-delegate install`» |
| `local_status` (por MCP) | `Language: en (preference; ~\AppData\Local\local-delegate\language.json)` | `Idioma: es (preferencia; ~\AppData\Local\local-delegate\language.json)` |
| Resultado de `doctor` | rc=1 por un único `[WARN]` | igual |

Mismo idioma, mismo origen («preferencia») y misma ruta en `doctor` y en `local_status`, en los
dos idiomas. El único `[WARN]` es «nombres obsoletos: `LD_HOOK_READ_BLOQUEAR` leído por los hooks
en los últimos 7 días»: telemetría de sesiones abiertas antes del cambio de nombre en esta PC
(la variable de `settings.json` ya es `LD_HOOK_READ_BLOCK`); se va solo al salir de la ventana de
7 días. Salidas: `doctor-en.txt`, `doctor-es.txt`.

## 4. Hooks instalados (REQ-024)

`smoke_hooks_real.py`: lee los comandos registrados en el `~/.claude/settings.json` real y los
ejecuta tal cual en `sh` y en PowerShell, con el `env` de `settings.json` y el `language.json`
real; la telemetría de los hooks va a un fichero de prueba. No cambia nada de su configuración.

| Hook | Shell | en | es |
| --- | --- | --- | --- |
| `PreToolUse/Read` (51 KB de prosa) | sh, PowerShell | rc=0, ASCII, `deny`: «This file is 51 KB and it is prose. Pass it to a local tool with `path=…`» | rc=0, ASCII, `deny`: «Este archivo pesa 51 KB y es prosa. Pasalo por una tool local con `path=…`» |
| `UserPromptSubmit` («summarize this log») | sh, PowerShell | rc=0, ASCII: «Mechanical task detected (summarize)…» | rc=0, ASCII: «Oportunidad mecanica detectada (summarize)…» |

`RESULT: OK` en los dos. El `deny` confirma que el bloqueo de lectura está activo con los hooks
nuevos. Salidas: `hooks-en.txt`, `hooks-es.txt`.

## 5. Panel con dos navegadores (REQ-020, REQ-025)

`capture_panel_live.py`: Playwright contra el daemon instalado (`:9393`, Basic con el token del
daemon), un contexto `es-ES` y otro `en-US`, cada uno en claro y en oscuro. Datos reales del
daemon. Resultado: `panel-live.json` y las capturas `panel-<locale>-<tema>.png`.

| Contexto | `<html lang>` | Selector | «Procesos del backend» | Filas de procesos |
| --- | --- | --- | --- | --- |
| es-ES claro / oscuro | es | es | «Procesos del backend», tarjeta «Sistema» | `pythonw.exe` (DAEMON MCP, pid 42728) y **un** `llama-swap.exe` (pid 1688, el del backend) |
| en-US claro / oscuro | en | en | «Backend processes», tarjeta «System» | `pythonw.exe` (MCP DAEMON) y el mismo `llama-swap.exe` |
| es-ES, selector a EN | en | en | «Backend processes» | — |
| … tras recargar | en | en | «Backend processes»; `localStorage['ld-lang'] = "en"` | — |

Sin `llama-swap` de tests en la lista. Revisada a ojo la captura en inglés y oscuro: todo el texto
visible en inglés, también las tarjetas de coste y cuota y la tabla de sugerencias de los hooks
(los diálogos ⓘ no se abrieron en esta pasada; los cubren las capturas de B4). El pie de página
muestra la carpeta de datos con la ruta del usuario (igual que en las capturas de la 0.35.0).
