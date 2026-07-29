# Result review: Politica de techos de major para las dependencias de runtime

Revisión hecha **contra el árbol de `main` ya mergeado** (`39cc69e`), no contra la rama de trabajo ni
contra la memoria de la sesión: cada fila de abajo se comprobó ejecutando o leyendo el fichero en su
estado final.

## Verdict

`conforms-with-notes`

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 — techo a las del arranque con major real | sí | `pyproject.toml` en `main`: `platformdirs>=4,<5`, `filelock>=3,<4`. En el wheel: `Requires-Dist: filelock<4,>=3`, `platformdirs<5,>=4` | Se verificó el **wheel** además del fuente: es el artefacto que viaja a PyPI y el que rompió la 0.12.1 |
| REQ-002 — cada techo con su motivo al lado | sí | Comentarios en `pyproject.toml`, siguiendo el precedente del de `mcp` | — |
| REQ-003 — `fastapi`/`uvicorn` sin techo, con su razón | sí | `fastapi>=0.115` y `uvicorn>=0.30` sin cambio, con el comentario que separa las dos razones | La razón de `uvicorn` se **corrigió durante la implementación**; ver hallazgo 1 |
| REQ-003b — la premisa fijada por un test | sí | `pytest -k importar_el_paquete` sobre `main` → **1 passed** | Corre en subproceso limpio |
| REQ-004 — `httpx` sin tocar | sí | `httpx>=0.27` idéntico a antes, con el comentario de por qué | — |
| REQ-005 — la instalación real no se rompe | sí | `install-smoke` en verde en el PR #36: resuelve con `--resolution highest` dentro de los techos nuevos y hace el handshake MCP contra el paquete instalado | Comprobación por ejecución, no por razonamiento |
| REQ-006 — política documentada | sí | `docs/wiki/Repo-hardening.md`, secciones «El criterio», «Alcance: solo dependencias directas», «Lo que cuesta» y «La premisa que hay que vigilar» | — |
| REQ-007 — coste asumido y qué lo vigila | **parcial** | Sección «Lo que cuesta» con los tres costes escritos | La vigilancia se apoya en una verificación **pendiente**; ver seguimiento |

## Findings

1. **El análisis inicial tenía un error, cazado por el test antes de mergear.** Se dedujo —leyendo
   los imports del repo, sin ejecutar— que ni `fastapi` ni `uvicorn` estaban en el camino de
   arranque. Cierto para `fastapi`, **falso para `uvicorn`**: lo arrastra el SDK
   (`mcp.server.fastmcp` → `mcp/server/sse.py` → `sse_starlette` → `uvicorn`). La decisión práctica
   no cambió, pero **la mitad de su justificación sí**. Corregido en `spec.md` y `research.md` con la
   enmienda marcada, no reescrito por lo bajo.
   *Lección de proceso, no del cambio:* rastrear una cadena de imports leyendo solo el repo propio
   ignora lo que arrastran las dependencias. Verificar por ejecución no era opcional.

2. **La política no cubre transitivas, y el arranque depende de dos que ni declaramos**
   (`sse_starlette`, `starlette`). Está escrito en la documentación en vez de quedar implícito. No es
   un defecto del cambio: es su límite, declarado.

3. **Sin efecto hasta publicar.** Los techos viajan en el wheel, así que la 0.12.2 que está en PyPI
   sigue resolviendo libre. Es un no-goal explícito de la spec y una decisión aplazada del usuario,
   no un olvido — pero conviene no perderlo de vista: **el trabajo no protege a nadie todavía**.

4. **Deuda menor (F3 de la revisión del plan):** la política vive en `docs/wiki/Repo-hardening.md`
   para no chocar con la sección «Dependencias» que la rama de migración añade a `SECURITY.md`.
   Cuando esa rama se mergee, conviene reconsiderar si deberían vivir juntas.

## Required follow-up

Nada bloquea el cierre. Dos cosas quedan **abiertas y anotadas**, y ninguna es trabajo pendiente de
este cambio:

- **Lunes 2026-08-03:** comprobar si Dependabot propone subir `mcp>=1.2,<2` con `mcp` 2.0.0 ya
  publicada. De eso depende que REQ-007 quede cubierto sin construir nada; si no lo propone, hay que
  decidir otra salvaguarda.
- **Release:** decidir si los techos salen en una 0.12.3 o esperan a la 0.13.0 de la migración.
  Mientras tanto, la 0.12.2 publicada sigue expuesta.
