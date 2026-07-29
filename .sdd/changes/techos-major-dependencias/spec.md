# Specification: Politica de techos de major para las dependencias de runtime

## Summary

Quien instala `local-delegate-mcp` desde PyPI resuelve las dependencias **libremente y para
siempre**: el wheel publicado es inmutable, así que un major nuevo de cualquier dependencia puede
tumbar instalaciones de una versión que llevaba meses funcionando. Pasó de verdad con `mcp` 2.0.0 y
la 0.12.1 el 2026-07-28.

El resultado que se busca es que **el paquete publicado se defienda solo**: que una instalación nueva
no pueda arrastrar un major que el proyecto nunca probó, en las dependencias donde eso mata el
proceso **en silencio**. Y que la política quede escrita con su porqué, para que nadie la borre por
«limpieza» ni la extienda por inercia a donde no aporta.

**Lo que este cambio decide** es dónde va un techo y dónde no, con un criterio: *el techo va donde
protege de verdad y donde el fallo sería silencioso*. No «a todas por si acaso» — un techo tiene un
coste real y ponerlo donde no protege es teatro de seguridad.

## Requirements

- **REQ-001:** Las dependencias del **camino de import de arranque** que sigan un versionado con
  major real quedan acotadas por debajo del major siguiente. En `main` son `platformdirs` y
  `filelock`. Observable en `pyproject.toml` y en los metadatos del wheel construido.
- **REQ-002:** Cada techo lleva **al lado** el motivo por el que existe, siguiendo el precedente del
  comentario de `mcp`. Un rango acotado sin explicación se borra en la siguiente limpieza.
- **REQ-003:** `fastapi` y `uvicorn` **no** reciben techo de major, y la decisión queda escrita con
  su razón — que **no es la misma para las dos**, corregido durante la implementación:
  - `fastapi`: está en `0.x`, donde un `<1` no protege porque la ruptura llega por minor, **y**
    no está en el camino de arranque (import perezoso, `server.py:1753`).
  - `uvicorn`: está en `0.x` igual, pero **sí se carga al arrancar** — lo arrastra el SDK
    (`mcp.server.fastmcp` → `mcp/server/sse.py` → `sse_starlette` → `uvicorn`), no este paquete.
    Quien gobierna esa compatibilidad es `sse-starlette`, transitiva que no declaramos; un techo
    nuestro daría cobertura aparente sin cambiar nada.
- **REQ-003b:** Queda fijado por un test que el **stack web propio** (`fastapi`,
  `local_delegate.web.metrics`, `local_delegate.daemon`) no entra al importar el paquete, para que
  un refactor no invalide la premisa de `fastapi` en silencio.
- **REQ-004:** `httpx` **no** se toca en `main`, y queda escrito por qué: está en `0.x` (techo
  decorativo) y **sale del proyecto** en la migración a `mcp` 2.x, que ya está hecha y verificada.
  El techo de su sustituto —`httpx2>=2.5,<3`, donde el major sí es real— entra en la rama de la
  migración, no aquí.
- **REQ-005:** El techo no debe romper la instalación real: `install-smoke` sigue en verde
  resolviendo con `--resolution highest` dentro de los rangos nuevos.
- **REQ-006:** La política queda documentada donde se busca, no solo en el `pyproject.toml`, con la
  regla explícita **«el techo se sube, no se quita»** y el criterio de cuándo aplica.
- **REQ-007:** Queda registrado el **coste asumido**: adoptar un major nuevo exigirá publicar una
  versión, y **un techo olvidado envejece en silencio** sin que `install-smoke` lo note —resuelve
  dentro del rango declarado, así que un techo viejo le parece correcto—. Debe quedar dicho qué
  vigila eso.

## Acceptance scenarios

### Scenario: sale un major nuevo de una dependencia acotada

- **Given** una instalación nueva por `uvx local-delegate-mcp` de la versión publicada
- **When** se publica `filelock` 4.0.0 con un cambio incompatible
- **Then** el resolvedor se queda en la serie 3.x y el MCP arranca; **sin el techo**, el proceso
  moriría en el import y el cliente solo vería `MCP error -32000: Connection closed`

### Scenario: sale un minor nuevo de una dependencia no acotada

- **Given** el daemon con el dashboard
- **When** se publica `fastapi` 0.141 con un cambio incompatible
- **Then** el modo stdio —el que usan Claude Code y Codex— **sigue delegando**, porque `fastapi` no
  está en su camino de import; el fallo aparece en el daemon, donde se ve, y lo cubre la detección
  de `install-smoke` y el bump semanal de Dependabot

### Scenario: alguien rompe la premisa con un refactor

- **Given** la política que deja `fastapi` sin techo porque entra por import perezoso
- **When** un refactor sube `from .web import metrics` al nivel de módulo en `server.py`
- **Then** la suite **falla** con un mensaje que apunta a la política, en vez de dejar el proyecto
  creyéndose protegido donde ya no lo está

### Scenario: el proyecto quiere adoptar el major nuevo

- **Given** un techo `filelock>=3,<4` y `filelock` 4.x ya publicada
- **When** se decide adoptarla
- **Then** se sube el techo (`<5`) en un cambio propio, con la suite y `install-smoke` en verde —
  nunca quitándolo

## Edge cases and failure behavior

- **Techo que envejece.** El riesgo se traslada a Dependabot, que ya corre semanal sobre el
  ecosistema `uv` y ha demostrado cruzar majors donde el manifiesto se lo permite (`codeql-action`
  3→4, `checkout` 4→7). **Falta la evidencia de que suba un rango que le bloquea**, y llega sola: en
  `main` está `mcp>=1.2,<2` con `mcp` 2.0.0 ya publicada, así que la corrida del **lunes 2026-08-03**
  lo dirá. Si no propone nada, hace falta otra salvaguarda y se decide entonces — no se construye
  nada por adelantado.
- **Conflicto con la rama de migración.** Se evita por construcción: este cambio toca solo
  `platformdirs` y `filelock`, líneas que la migración no modifica. `httpx`/`httpx2` se resuelve en
  su rama.
- **Resolución imposible en el entorno de quien instala.** Riesgo bajo: el modo recomendado es
  `uvx`, que aísla por herramienta. Si alguien instala en un entorno compartido y choca, el techo es
  visible en el error del resolvedor, no un fallo mudo.

## Non-functional requirements

- **Compatibilidad:** ninguna instalación existente que hoy funcione puede dejar de funcionar. Los
  techos se ponen **por encima** de las versiones que el proyecto ya usa (`platformdirs` 4.11.0,
  `filelock` 3.32.0), así que nadie baja de versión.
- **Operabilidad:** el cambio no altera el comportamiento en tiempo de ejecución; solo la resolución
  de dependencias. La suite debe pasar sin tocar un test.
- **Seguridad:** un techo **no** debe impedir recibir parches de seguridad dentro de la serie
  acotada; por eso se acota el major y no el minor.

## Non-goals

- **No se publica nada como parte de este cambio.** Los techos solo protegen cuando viajan en un
  wheel publicado, así que hay una decisión de release detrás — pero es del usuario y va aparte.
  Queda anotado que la 0.12.2 **ya publicada** sigue expuesta hasta entonces.
- **No se acota `mcp`** aquí: ya tiene techo, y subirlo al major 2 es trabajo de la migración.
- **No se construye un vigilante propio** de majors por encima del techo antes de saber qué hace
  Dependabot el lunes.
- **No se tocan las dependencias de desarrollo.** No viajan en el wheel, así que no pueden romper una
  instalación.
- **No se revisa la política de `uv.lock`**: protege desarrollo y CI, y ese lado ya funciona.

## Traceability

| Requisito | Trabajo previsto | Evidencia de verificación |
| --- | --- | --- |
| REQ-001 | Acotar `platformdirs` y `filelock` en `pyproject.toml` | Rangos en el wheel construido; `uv lock` resuelve |
| REQ-002 | Comentario junto a cada techo | Diff de `pyproject.toml` |
| REQ-003 | Dejar `fastapi`/`uvicorn` sin techo, con **su** razón cada una | Documentación + comentario del `pyproject.toml` |
| REQ-003b | Test de la invariante en subproceso limpio | `pytest` en verde; falla si alguien sube el import |
| REQ-004 | No tocar `httpx`; anotar que `httpx2<3` va en la rama de migración | Diff y documentación |
| REQ-005 | — | `install-smoke` en verde en el PR |
| REQ-006 | Sección de política en la documentación de seguridad/dependencias | Documento publicado |
| REQ-007 | Anotar el coste y la verificación pendiente de Dependabot | Este spec + `verification.md` |
