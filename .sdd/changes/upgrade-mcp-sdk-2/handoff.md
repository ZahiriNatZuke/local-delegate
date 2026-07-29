# Handoff: Analisis del upgrade al SDK mcp 2.x: ajuste de lo implementado y mejoras aprovechables

## Current state

- SDD status: `plan-review`, con los gates **`spec` y `plan` aprobados**. La implementación no ha
  empezado.
- Current revision: rama **`feat/mcp-sdk-2`** (local y remoto), salida de `main` en `cf3692f`.
- `main` sigue en `mcp` 1.x y publicando 0.12.x con normalidad. La migración no la bloquea.

## What changed

Solo análisis; ni una línea de código del paquete. La investigación salió de **leer el wheel
`mcp-2.0.0`** y comparar `requires_dist` en PyPI, no de documentación:

- El código casi no rompe: `MCPServer` sustituye a `FastMCP`, los 11 decoradores y `run()` son
  compatibles, `streamable_http_app()` sigue existiendo. **El único punto que rompe de verdad es
  `daemon.py:116`**, porque `Settings` perdió los campos de transporte.
- **El coste real está en las dependencias**, no en el código: 2.x mete `httpx2`,
  `opentelemetry-api`, `pyjwt[crypto]`, `jsonschema`, `python-multipart` y `pywin32` (Windows).
- Depscore de todo lo que entra: limpio salvo **`pywin32` (license 70, supplyChain 73)**.
  `httpx2` marca 100 en las cinco dimensiones.

## Decisions

- **Una sola librería HTTP: `httpx2`** (decisión del usuario, 2026-07-28). Consecuencia asumida:
  `respx` no lo soporta y sale de la suite — 122 ocurrencias en 5 ficheros, a `httpx2.MockTransport`.
- **El techo de major no se elimina, se sube** a `mcp>=2,<3`. La lección de la 0.12.1 es que un
  rango sin techo es una bomba de tiempo, no que ese techo concreto sobrara.
- **Primero equivalencia, después capacidades.** Con `httpx2` en el camino del backend, mezclarlas
  haría imposible saber si una regresión viene del SDK nuevo o de una feature nueva.
- **Las features solo entran si cierran deuda ya apuntada** en el backlog. Las que no, se anotan
  como descartadas para no re-descubrirlas: `cache_hints`, `subscriptions`, `extensions`,
  `request_state_security`.
- **Versión de la migración: minor, `0.13.0`.**
- **No publicar hasta que el SDK tenga un patch (2.0.1+)** o unas semanas de rodaje: 2.0.0 se
  publicó el mismo día que rompió la 0.12.1.
- `pywin32` es una dependencia **heredada**, no elegida. Este repo ya la evitaba a propósito
  (`_pid_alive` usa `ctypes`) y 2.x la mete por la puerta de atrás.

## Next action

**La tarea 1b del plan: el spike de viabilidad de `httpx2`, antes de tocar `pyproject.toml`.**

En un entorno desechable con `httpx2` y **sin `httpx`**, comprobar que
`fastapi.testclient.TestClient` arranca y sirve una app Starlette. Se usa en **~22 puntos** de
`tests/test_metrics.py` y `tests/test_daemon.py`, que cubren dashboard y daemon.

**Si no funciona, parar y volver al usuario**: la decisión de una sola librería HTTP habría que
revisarla, no forzarla. Es el hallazgo bloqueante F1 de `plan-review.md`.

### Prompt de arranque para una sesión nueva

```
Retoma la implementación del upgrade del SDK `mcp` a 2.x en D:\Projects\local-delegate.

Usa /personal-sdd-workflow. El change YA EXISTE: slug `upgrade-mcp-sdk-2`, en estado
`plan-review` con los gates `spec` y `plan` aprobados. NO crees uno nuevo.

Antes de tocar nada, lee en este orden:
- .sdd/changes/upgrade-mcp-sdk-2/research.md   (evidencia: sale de leer el wheel 2.0.0, no de docs)
- .sdd/changes/upgrade-mcp-sdk-2/spec.md       (13 requisitos en 3 fases)
- .sdd/changes/upgrade-mcp-sdk-2/plan.md       (tareas ordenadas)
- .sdd/changes/upgrade-mcp-sdk-2/plan-review.md (el hallazgo bloqueante F1)

Trabaja en la rama `feat/mcp-sdk-2`, que ya existe en local y en remoto.

EMPIEZA POR LA TAREA 1b DEL PLAN: el spike de viabilidad de httpx2, ANTES de tocar
pyproject.toml. En un entorno desechable con httpx2 y SIN httpx, comprueba que
`fastapi.testclient.TestClient` arranca y sirve una app Starlette — se usa en ~22 puntos de
tests/test_metrics.py y tests/test_daemon.py. Si NO funciona, PARA y pregúntame: la decisión
de una sola librería HTTP habría que revisarla, no forzarla.

Contexto ya decidido, no lo vuelvas a analizar:
- Una sola librería HTTP: httpx2 (decisión mía; depscore 100 en las cinco dimensiones).
- respx NO soporta httpx2 y sale de la suite: 122 ocurrencias en 5 ficheros, a httpx2.MockTransport.
- El techo de major NO se elimina, se sube a `mcp>=2,<3`.
- Solo daemon.py:116 rompe de verdad: `settings.streamable_http_path` ya no existe, la ruta
  se pasa a `streamable_http_app(streamable_http_path=...)`.
- `MCPServer(..., version=...)` arregla que serverInfo reporte hoy la versión del SDK.
- pywin32 (license 70, supplyChain 73) entra obligatoria en Windows por el SDK y no es
  evitable. Documentarla como dependencia heredada.
- Primero equivalencia, después capacidades. Nada de features en la fase 1.
- La versión de la migración será minor: 0.13.0.

Reglas duras del proyecto:
- NO publicar a PyPI sin confirmación explícita mía.
- `main` está protegida: todo entra por PR, solo squash, con los checks en verde.
- Antes de cada push, los CUATRO pasos del CI con `.` (no rutas parciales).
- Verificar el CI de `main` DESPUÉS del merge con `gh run list`, no solo los checks del PR.
- Todo en español. Sin `Co-Authored-By: Claude` en los commits.

Gotchas de esta máquina:
- pytest necesita `--basetemp` propio: falla al limpiar el symlink pytest-current del temp
  de Windows (PermissionError WinError 5). No es un fallo de la suite.
- El daemon corre del venv EDITABLE del repo: `uv sync` + `Stop-Process` del pid +
  `Start-ScheduledTask LocalDelegateDaemon`. Ahora está en 0.12.2.
- PyPI sirve el índice con caché: verificar demasiado pronto devuelve la versión anterior.

Contexto de fondo en Obsidian: projects/local-delegate/overview.md, backlog.md e
incidente-mcp-sdk-2-2026-07-28.md.
```

## Memory

- Canonical note: `projects/local-delegate/incidente-mcp-sdk-2-2026-07-28.md` (por qué existe este
  trabajo). El backlog recoge la migración como deuda declarada.
- Indexes updated: pendiente hasta que la migración avance; hoy el vault ya dice que el techo es
  deuda y que migrar a 2.x es un cambio SDD aparte.
