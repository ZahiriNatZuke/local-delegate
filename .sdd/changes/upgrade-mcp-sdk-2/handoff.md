# Handoff: Analisis del upgrade al SDK mcp 2.x: ajuste de lo implementado y mejoras aprovechables

## Current state

- SDD status: `closed`. **Los cinco gates aprobados.**
- Current revision: **PRs #34 (fase 1) y #35 (fase 2) mergeados** en `main`, y **publicado en la
  0.13.0** el 2026-07-29 (PR #43 de preparación). `publish.yml` verde en sus tres jobs, registro MCP
  en `0.13.0` `active`/`isLatest`.
- **Verificado con instalación limpia desde PyPI**, resolución libre: `local-delegate-mcp` 0.13.0,
  `mcp` **2.0.0**, `httpx2` 2.9.1 y **`httpx` ausente** — la migración a una sola librería HTTP se
  cumple en la instalación real, no solo en el lock. Handshake OK, y **reporta la versión del
  paquete** (0.13.0), que era uno de los defectos que este cambio cerraba.

## Por qué se publicó ahora, y no esperando a `mcp` 2.0.1

Estaba en draft «hasta 2.0.1» por prudencia, sin criterio de salida. Al revisarlo con datos, la
espera no compraba nada: **cero vulnerabilidades** conocidas de 2.0.0, ningún bug que nos afectara,
y un dato que cambió la lectura — **1.29.0 y 2.0.0 se publicaron con cuatro minutos de diferencia**
(13:41 y 13:45 del 2026-07-28). No fue un major apurado, fue una release coordinada. Lo que rompió
la 0.12.1 no fue que 2.0.0 fuera malo: fue **no tener techo**.

Lo que sí crecía era el coste de esperar: las dos ramas estaban ya **7 commits detrás de `main`**, y
cada release las alejaba más.

## Lo que cazó el rebase, y habría sido una regresión silenciosa

La rama era **anterior a la política de techos** de la 0.12.3, así que traía `platformdirs>=4` y
`httpx2>=2.5` **sin techo**: publicarla tal cual habría revertido esa política recién publicada, y
**ningún check lo habría visto** — `install-smoke` resuelve *dentro* del rango declarado, así que le
habría parecido correcto. Al resolver el conflicto se recuperaron `platformdirs<5` y `filelock<4`, y
se añadió `httpx2>=2.5,<3`.

Ese techo de `httpx2` no se puso por simetría: se **verificó por ejecución** que cumple las dos
condiciones del criterio — importar el paquete carga `httpx2` (camino de arranque) y su versionado
tiene major real. De paso se confirmó que en 2.x se mantiene el resto del análisis: `uvicorn` sigue
entrando por el SDK vía `sse_starlette`, y `fastapi` sigue **sin** entrar (import perezoso intacto).

## What changed

Las **fases 1 y 2 están implementadas, mergeadas y publicadas**. Lo que sigue es el análisis previo,
que se conserva porque su evidencia sigue valiendo: salió de **leer el wheel `mcp-2.0.0`** y comparar
`requires_dist` en PyPI, no de documentación. Se cumplió punto por punto:

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
- **Versión de la migración: minor, `0.13.0`.** Se cumplió, y el minor está justificado por el
  cambio de contrato de `local_extract`, no solo por el tamaño del cambio.
- ~~**No publicar hasta que el SDK tenga un patch (2.0.1+)**~~ — **revisada y descartada el
  2026-07-29**, ver la sección de arriba. Era prudencia sin criterio de salida, y el coste de
  esperar (el desfase creciente de las ramas) resultó mayor que el riesgo de publicar.
- `pywin32` es una dependencia **heredada**, no elegida. Este repo ya la evitaba a propósito
  (`_pid_alive` usa `ctypes`) y 2.x la mete por la puerta de atrás.

## Next action

El change está cerrado y publicado en la 0.13.0. Lo que queda es de fuera:

1. **Actualizar el daemon local**: corría del venv editable en la rama `feat/mcp-sdk-2-fase2`, que
   ya no existe como tal — su contenido está en `main`. `git switch main && uv sync` + reinicio de
   la tarea programada.
2. **Actualizar la Mac** con `./scripts/update_to_latest.sh` (salta de 0.10.0 a 0.13.0 de una vez).
3. **La fase 3 sigue sin empezar**, cada mejora en su propio cambio SDD: OpenTelemetry,
   `middleware`, elicitation y `auth`. Las cuatro capacidades descartadas siguen descartadas y
   están anotadas para no re-descubrirlas: `cache_hints`, `subscriptions`, `extensions` y
   `request_state_security`.

## Memory

- Canonical note: `projects/local-delegate/migracion-mcp-sdk-2.md`, actualizada con la publicación
  en la 0.13.0 y con lo que cazó el rebase. `incidente-mcp-sdk-2-2026-07-28.md` sigue siendo el
  porqué de fondo.
- Indexes updated: sí. El `backlog.md` cierra la entrada de la migración y deja anotada la fase 3
  como lo único que queda; la memoria de proyecto de Claude Code lleva el puntero al día.
