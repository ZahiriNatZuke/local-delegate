# Handoff: Politica de techos de major para las dependencias de runtime

## Current state

- SDD status: `closed` — los cinco gates aprobados.
- Last completed gate: `memory`.
- Current revision: mergeado en `main` como **`39cc69e`** (PR #36, squash). CI de `main` verificado
  después del merge con `gh run list`: CI, CodeQL y Dependency Graph en `success`.

## What changed

- `pyproject.toml`: `platformdirs>=4,<5` y `filelock>=3,<4`. Cada techo con su motivo al lado, y
  también el motivo de las que **no** lo llevan.
- `tests/test_core.py`: un test nuevo que fija, en subproceso limpio, que importar `local_delegate`
  no arrastra `fastapi` ni los módulos del daemon/dashboard. **234 tests** (233 + 1).
- `docs/wiki/Repo-hardening.md`: sección con el criterio, la tabla dependencia a dependencia, el
  alcance (solo directas) y el coste asumido.
- `CHANGELOG.md` y `uv.lock` (solo los dos specifiers; ninguna versión resuelta se movió).

## Decisions

- **`install-smoke` y el techo no son alternativas.** El job protege *hacia atrás* (detecta majors ya
  publicados cuando corre el CI); el techo protege *hacia adelante* (viaja dentro del wheel, que es
  inmutable y resuelve libre para siempre). El CI de la 0.12.1 pasó en verde porque `mcp` 2.0.0
  todavía no existía: ninguna corrida posterior podía salvarla.
- **Techo solo donde protege**, con dos condiciones a la vez: estar en el camino de import de
  arranque **y** tener major real. En `0.x` un `<1` es decorativo porque la ruptura llega por minor.
- **`uvicorn` sí está en el camino de arranque** — lo arrastra el SDK
  (`mcp.server.fastmcp` → `mcp/server/sse.py` → `sse_starlette` → `uvicorn`), no este paquete. Sigue
  sin techo, pero por estar en `0.x` y porque quien gobierna esa compatibilidad es `sse-starlette`,
  transitiva que no declaramos. **El análisis inicial decía lo contrario y el test lo corrigió.**
- **La política no cubre transitivas**, y está declarado. `starlette` saltó de `0.x` a `1.3.1` por un
  *minor* de `fastapi`; ningún techo nuestro lo habría evitado.
- **El techo se sube, no se quita.**

## Next action

**Decidir la publicación**, que es lo único que convierte este trabajo en protección real: los techos
viajan en el wheel, así que la 0.12.2 que está en PyPI sigue resolviendo libre. Las opciones son una
**0.12.3** solo con esto, o esperar a la **0.13.0** de la migración a `mcp` 2.x (que a su vez espera
a `mcp` 2.0.1+). Requiere confirmación explícita del usuario antes de tocar PyPI.

Además, con fecha: **el lunes 2026-08-03**, comprobar si Dependabot propone subir `mcp>=1.2,<2`
teniendo `mcp` 2.0.0 publicada. Si lo hace, el riesgo de «techo que envejece» queda cubierto sin
construir nada; si no, hay que decidir otra salvaguarda.

## Memory

- Canonical note: `projects/local-delegate/techos-major-dependencias.md` en el vault de Obsidian,
  enlazada desde `incidente-mcp-sdk-2-2026-07-28`, `migracion-mcp-sdk-2`, `backlog` y `overview`.
- Indexes updated: memoria de Claude Code del proyecto (puntero con las dos trampas: no protege hasta
  publicar, y `uvicorn` sí está en el arranque vía el SDK). `backlog.md` actualizado como nota viva.
