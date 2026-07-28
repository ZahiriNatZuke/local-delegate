# Research: Acotar el SDK mcp por debajo del major 2 y cerrar el punto ciego de resolucion libre

## Current behavior

Hechos verificados en esta sesión (2026-07-28), no supuestos:

| Hecho | Cómo se verificó |
| --- | --- |
| `mcp` 2.0.0 es la versión **latest** en PyPI | `Invoke-RestMethod https://pypi.org/pypi/mcp/json` → `info.version = 2.0.0` |
| La última 1.x es **1.29.0** | listado de `releases` del mismo JSON |
| El wheel 2.0.0 **no contiene** `mcp/server/fastmcp/` | inspección del zip de `mcp-2.0.0-py3-none-any.whl`: 0 entradas con ese prefijo |
| La ruta nueva es **`mcp.server.mcpserver`** | el wheel contiene `mcp/server/mcpserver/__init__.py` y hermanos |
| `pyproject.toml` declara `mcp>=1.2` sin techo | `pyproject.toml:22` |
| `uv.lock` fija `mcp 1.28.1` | `uv.lock:427-429` |

**Corrección respecto al reporte inicial:** el módulo nuevo es `mcp.server.mcpserver`, no
`mcp.mcpserver`. `mcp/server/` sigue existiendo en 2.0.0; lo que desapareció es el subpaquete
`fastmcp`. El import concreto de una eventual migración depende de este dato.

Consecuencia operativa: `uv.lock` protege al CI y al daemon local del fallo exacto que sufre
cualquier usuario que instale por `uvx`. El CI puede estar verde con el paquete publicado roto —
y lo estuvo.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `pyproject.toml` | Declara `mcp>=1.2` | Añadir techo `<2` | `pyproject.toml:22` |
| `uv.lock` | Fija `mcp 1.28.1` | Regenerar; puede subir dentro de 1.x | `uv.lock:427` |
| `src/local_delegate/server.py` | Único import del SDK y única instanciación | **Sin cambios** con el pin | `server.py:32`, `server.py:36` |
| `src/local_delegate/daemon.py` | Usa `settings.streamable_http_path` y `streamable_http_app()` | **Sin cambios** con el pin; es la superficie que complica migrar | `daemon.py:116-117` |
| `.github/workflows/ci.yml` | Instala siempre desde el lock | Job nuevo de resolución libre + handshake | — |
| `CHANGELOG.md` | Keep a Changelog, sección `[Unreleased]` | Entrada del fix | convención del repo |
| `scripts/bump_version.py` | Sube la versión en los cuatro sitios | Se usa para 0.12.2 | wiki del repo |

Superficie total del SDK en el código: **12 ocurrencias en un solo archivo** (`server.py`,
decoradores de tools) más las dos líneas de `daemon.py`. El pin no toca ninguna.

## Existing conventions

- Todo en español: código, comentarios, commits, documentación.
- El repositorio explica **por qué**, no **qué**. El techo debe llevar comentario con su motivo.
- Conventional Commits; rama `fix/…`; `CHANGELOG.md` actualizado en el propio PR.
- `scripts/bump_version.py` sube la versión en los **cuatro** sitios (pyproject, las dos de
  `server.json` y `uv.lock`). No editar a mano.
- Los checks requeridos llevan el **nombre exacto del job**, con la matriz incluida.

## Dependencies and integrations

Directas: `mcp`, `httpx>=0.27`, `platformdirs>=4`, `fastapi>=0.115`, `uvicorn>=0.30`,
`filelock>=3`. **Ninguna declara techo de major.** `mcp` es la que rompió hoy, pero el patrón se
repite en las otras cinco: es la misma bomba con otra mecha. Se anota como seguimiento, fuera del
alcance de este cambio.

Integración afectada: `uvx local-delegate-mcp` (el modo de instalación documentado en el README y
el que usa `update_to_latest.sh`). El daemon de Windows no está afectado porque corre del venv
editable con lock.

## Risks and unknowns

**Confirmado:**
- El techo `<2` resuelve el fallo: 1.29.0 sigue siendo instalable y contiene `mcp.server.fastmcp`.
- El fix debe ir en el wheel; por eso una versión de patch es obligatoria (no basta con `main`).

**Validado en esta sesión (2026-07-28), antes del gate de spec:**
- El server **sí** responde `initialize` por stdio **sin backend vivo**, con
  `LOCAL_DELEGATE_WEB=0`, `LOCAL_DELEGATE_AUTOSTART=0` y `BASE_URL` apuntando a un puerto muerto:
  respuesta JSON-RPC válida, `returncode 0`, `stderr` limpio. REQ-003 es alcanzable.
- La misma sonda confirma que `serverInfo.version` devuelve **`1.28.1`**, es decir la versión del
  SDK `mcp` fijada en el lock, no la del paquete. `FastMCP("local-delegate")` se instancia sin
  `version=` (`server.py:36`). Defecto real y **separado**: un handshake no sirve para verificar
  qué versión de local-delegate corre. Anotado como no-goal y para el backlog.

**Asumido, pendiente de validar en la implementación:**
- Que `mcp` 1.29.0 (la más alta bajo el techo) funciona igual que 1.28.1. El lock puede subir al
  regenerarse, así que la suite debe correr contra lo que quede fijado.

**Riesgo de proceso:** exigir el job nuevo como check requerido antes de comprobar que reporta
bloquearía el repositorio. Ya ocurrió dos veces en este proyecto.
