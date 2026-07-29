# Research: Politica de techos de major para las dependencias de runtime

Fecha: 2026-07-29. Rama `feat/techos-major-dependencias`, sacada de `main` (`cf3692f`) en un worktree
aparte para no tocar el checkout donde corre el daemon.

## Current behavior

`pyproject.toml` de `main` declara seis dependencias de runtime. **Solo `mcp` tiene techo de major**,
puesto de urgencia tras el incidente de la 0.12.1 (`.sdd/changes/mcp-sdk-2-breaking-pin/`):

```toml
"mcp>=1.2,<2",     # techo deliberado
"httpx>=0.27",     # sin techo
"platformdirs>=4", # sin techo
"fastapi>=0.115",  # sin techo
"uvicorn>=0.30",   # sin techo
"filelock>=3",     # sin techo
```

El backlog plantea la disyuntiva como *«¿techo a todas, o confiar en la detección de
`install-smoke`?»*. La investigación dice que **no tienen todas el mismo patrón** y que la detección
**no puede** cubrir el modo de fallo que nos mordió, así que la disyuntiva está mal planteada.

### `install-smoke` protege hacia atrás; el techo protege hacia adelante

El job (`.github/workflows/ci.yml`) construye el wheel y lo instala en un venv limpio con
`uv pip install --refresh --resolution highest`, o sea que **sí** resuelve a lo más nuevo que
permitan los rangos. Pero corre **cuando corre el CI**, contra lo que existe en PyPI **ese día**.

El fallo real de la 0.12.1 fue exactamente ese hueco: el CI pasó en verde porque `mcp` 2.0.0
**todavía no existía**, y el paquete se publicó. Cuando 2.0.0 salió —el mismo día— toda instalación
nueva por `uvx` resolvió al major nuevo y murió en el import. **El artefacto publicado es inmutable y
sigue resolviendo libre para siempre**, así que ninguna corrida posterior del CI podía salvarlo.

Un techo declarado viaja **dentro del wheel** y sigue protegiendo después de publicar. No es una
diferencia de grado: son dos ventanas de tiempo distintas, y la que importa es la de después.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `pyproject.toml` (`dependencies`) | Declara los seis rangos; solo `mcp` acotado | Añadir techo donde proteja de verdad, con el porqué al lado | `pyproject.toml` de `main`; el comentario del techo de `mcp` ya sienta el precedente de documentarlo |
| Camino de import de arranque | `server.py` carga `mcp`, `httpx`, `filelock` y (vía `config`) `platformdirs` al importarse | Es donde una rotura es **silenciosa y catastrófica** | `__init__.py:9` → `server.py:30-34`, `config.py:20`, `autostart.py:23` |
| Daemon y dashboard | `fastapi`/`uvicorn` entran por import **perezoso** | Una rotura ahí es visible y acotada; no afecta a `uvx … ` por stdio | `server.py:1753` (`from .web import metrics` dentro de una función), `cli.py:42` (`from . import daemon`, ídem) |
| `install-smoke` | Detecta roturas de majors **ya publicados** | Sigue valiendo; no sustituye al techo ni al revés | `.github/workflows/ci.yml`, job `install-smoke` |
| `uv.lock` | Fija versiones para desarrollo y CI | **No protege a quien instala desde PyPI**, que resuelve libre | El escenario `uvx` de la 0.12.1 |

### Qué está en el camino de arranque (verificado siguiendo los imports, no supuesto)

```
__init__.py → server.py → mcp / httpx / filelock / autostart / config
                                                    ↓          ↓
                                                  httpx   platformdirs
```

| Dependencia | ¿En el arranque del MCP? | Si rompe… |
| --- | --- | --- |
| `mcp` | **sí** | proceso muerto antes de hablar MCP: el cliente solo ve `MCP error -32000: Connection closed` |
| `httpx` / `httpx2` | **sí** | ídem |
| `filelock` | **sí** | ídem |
| `platformdirs` | **sí** (vía `config`) | ídem |
| `fastapi` | no (perezoso) | falla el dashboard; el modo stdio sigue delegando |
| `uvicorn` | **sí, pero no por este paquete** — ver la corrección de abajo | lo arrastra el SDK |

### Corrección durante la implementación: `uvicorn` sí está en el arranque

La tabla de arriba se dedujo leyendo los imports **de este repo**, y para `uvicorn` estaba **mal**.
El test de la invariante (tarea 3 del plan) lo cazó al primer intento, antes de mergear nada. Medido
ejecutando, no leyendo:

| Módulo | ¿Cargado tras `import local_delegate`? |
| --- | --- |
| `fastapi` | **no** |
| `local_delegate.web.metrics` / `daemon` / `cli` | **no** — el import perezoso funciona |
| `uvicorn`, `starlette`, `sse_starlette` | **sí** |

La cadena, rastreada con un hook en `sys.meta_path`:

```
local_delegate/__init__.py → server.py:32 (from mcp.server.fastmcp import FastMCP)
  → mcp/server/fastmcp/server.py:62 → mcp/server/sse.py:49 → sse_starlette → uvicorn
```

**Qué cambia y qué no.** La decisión práctica se mantiene —`uvicorn` sigue sin techo— pero su razón
cambia, y era la mitad del argumento: no es que esté fuera del camino de arranque, es que **está en
`0.x` y quien gobierna su compatibilidad ahí es `sse-starlette`**, una transitiva que este repo ni
declara. Un techo nuestro daría cobertura aparente sin cambiar nada real.

Y asciende el hallazgo F2 de la revisión a central: el arranque del MCP depende de `sse_starlette` y
`starlette`, que **no aparecen en nuestro `pyproject.toml`**.

## Existing conventions

- **El techo se sube, no se quita** — lección de la 0.12.1, ya aplicada en la rama de migración
  (`mcp>=2,<3`).
- **Cada techo lleva su comentario explicando el porqué**, como el de `mcp` en `main`. Un rango
  acotado sin explicación se acaba borrando por «limpieza».
- El modo de instalación recomendado del proyecto es `uvx`, que **resuelve libre y aislado**: es el
  escenario que hay que proteger, y no el del `uv.lock`.

## Dependencies and integrations

| Dependencia | Rango hoy | Última en PyPI (2026-07-29) | Esquema | ¿Un techo de major protege? |
| --- | --- | --- | --- | --- |
| `mcp` | `>=1.2,<2` (`>=2,<3` en la rama de migración) | 2.0.0 | major real | sí |
| `httpx` → `httpx2` | `>=0.27` → `>=2.5` | 2.9.1 | major real (2.x) | sí |
| `platformdirs` | `>=4` | 4.11.0 | major real (4.x) | sí |
| `filelock` | `>=3` | 3.32.0 | major real (3.x) | sí |
| `fastapi` | `>=0.115` | 0.140.13 | **0.x** | **no** |
| `uvicorn` | `>=0.30` | 0.52.0 | **0.x** | **no** |

En `0.x` la ruptura llega por **minor**: `fastapi<1` no impide que 0.141 rompa. El equivalente
honesto sería un techo de minor (`<0.141`), que hay que subir cada pocas semanas — `fastapi` fue de
0.115 a 0.140 en meses. Fricción constante a cambio de proteger la parte **no crítica**.

Que las cuatro del camino de arranque tengan major real, y las dos de `0.x` queden fuera de él, es lo
que hace que la política salga barata.

### Superficie que el proyecto usa de cada una

| Dependencia | Lo que se importa |
| --- | --- |
| `platformdirs` | `user_data_dir` (una función) |
| `filelock` | `FileLock`, `Timeout` |
| `httpx` / `httpx2` | cliente, `Response`, jerarquía de excepciones |
| `fastapi` | `FastAPI`, `Query`, `HTMLResponse`/`JSONResponse`/`Response` |
| `uvicorn` | `uvicorn.run` / `Config` / `Server` |

Importa para el **coste** del techo, no para el riesgo: con una superficie así, adoptar un major
nuevo suele ser trabajo de minutos. El techo no congela el proyecto; obliga a mirar antes de saltar.

## Risks and unknowns

**Confirmado:**

- El fallo de la 0.12.1 ocurrió **después** del release, en una ventana que el CI no puede cubrir.
- `fastapi` no está en el camino de arranque del MCP (import perezoso verificado **ejecutando**).
  `uvicorn` **sí** lo está, arrastrado por el SDK vía `sse_starlette` — corregido durante la
  implementación, ver arriba.
- Las cuatro del camino de arranque tienen major real; las dos de fuera están en `0.x`.

**Coste del techo, que hay que asumir explícitamente:**

1. **Adoptar un major nuevo exige publicar una versión.** Con `scripts/release.py` es un comando.
2. **Puede chocar con otras dependencias del entorno de quien instala.** Riesgo bajo: `uvx` aísla.
3. **Un techo olvidado envejece en silencio.** `install-smoke` **no** avisa: resuelve dentro del
   rango declarado, así que un techo viejo le parece perfecto. Hace falta que algo vigile lo que el
   techo deja fuera. **Es la contrapartida real de esta decisión y no estaba en el planteamiento del
   backlog.**

**Por validar en la spec:**

- ¿Dependabot propone **subir un rango con techo** en `pyproject.toml`, o solo actualiza el lock? De
  la respuesta depende si el punto 3 queda cubierto o hace falta otra cosa.
- **Precedente que conviene no olvidar:** `starlette` saltó de `0.x` a `1.3.1` arrastrada por un
  **minor** de `fastapi`, cambió la preferencia de `TestClient` a `httpx2` y dejó un
  `DeprecationWarning` en la suite. Ningún techo de major lo habría atajado, y el proyecto se enteró
  por un warning, no por un fallo. Es el argumento de que la detección tampoco sobra.
- `main` declara todavía `httpx`, y la rama de migración lo sustituye por `httpx2`: tocar
  `pyproject.toml` en las dos ramas da **conflicto de merge seguro**, trivial pero real.
