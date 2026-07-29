# Revisión adversarial del plan

**Limitación declarada de entrada: la revisión no es independiente.** La hace el mismo agente que
escribió el plan, sin subagentes. Vale para cazar huecos de razonamiento y premisas sin verificar;
no sustituye a un par de ojos ajenos.

## F1 (BLOQUEANTE) — La política se apoya en una propiedad del código que nadie vigila

Todo el argumento de «`fastapi` y `uvicorn` no llevan techo» descansa en que **no están en el camino
de import de arranque**: entran perezosamente desde `server.py:1753` y `cli.py:42`. Es cierto hoy,
verificado.

**Nada impide que deje de serlo.** Basta con que alguien suba `from .web import metrics` al nivel de
módulo en un refactor —un cambio que parece inocuo y que ninguna revisión marcaría— para que
`fastapi` y `uvicorn` pasen al camino crítico. La política quedaría desactualizada **en silencio**, y
el proyecto se creería protegido donde ya no lo está.

Confirmado que hoy no hay red: `grep` sobre `tests/` no encuentra **ningún** test que compruebe
`sys.modules` ni que importe el paquete en un subproceso limpio.

**Corrección:** añadir un test que fije la invariante — importar `local_delegate` **no** debe
arrastrar `fastapi` ni `uvicorn`. Tiene que correr en un **subproceso limpio**, porque dentro de la
suite otros tests ya han importado el stack web y `sys.modules` estaría contaminado.

Esto contradice el «ningún test nuevo» de la estrategia de prueba original, y con razón: no es un
test que afirme el contenido de un fichero de configuración, es un test de una propiedad real del
código de la que **depende la decisión**. Si la premisa se rompe, hay que enterarse por un fallo, no
por un incidente.

## F2 (IMPORTANTE) — El techo no cubre las transitivas, y el plan no lo dice

Acotar `platformdirs` y `filelock` no impide que rompa una **transitiva**. Y no es hipotético: el
propio research documenta que **`starlette` saltó de `0.x` a `1.3.1` arrastrada por un minor de
`fastapi`**, cambió la preferencia de `TestClient` y dejó un `DeprecationWarning` en la suite.
Ningún techo en nuestro `pyproject.toml` habría evitado eso.

Lo mismo aplica a `pydantic`, `anyio` y `httpcore`, que entran por `mcp` y `fastapi`.

**Corrección:** la documentación debe declarar explícitamente el **alcance** de la política — cubre
dependencias **directas**, no el árbol completo — y decir qué queda cubriendo lo demás
(`install-smoke` por detección, Dependabot semanal, y el `uv.lock` para desarrollo). Una política
que no declara su alcance produce falsa sensación de cobertura, que es peor que no tenerla.

## F3 (MENOR) — El sitio de la documentación es un compromiso, no el ideal

`docs/wiki/Repo-hardening.md` se elige **para no chocar** con la sección «Dependencias» que la rama
de migración añade a `SECURITY.md`. Evitar el conflicto es legítimo, pero quien busque «por qué
`filelock` tiene techo» probablemente mire `SECURITY.md` o el `pyproject.toml`.

**Mitigación aceptada:** el comentario del `pyproject.toml` —que es donde de verdad se tropieza uno
con el techo— apunta al documento. Cuando la migración se mergee, conviene reconsiderar si las dos
secciones deberían vivir juntas. Anotado como deuda menor, no bloquea.

## F4 (verificado, sin acción) — Los techos no cambian ninguna resolución actual

`platformdirs` está en 4.11.0 y `filelock` en 3.32.0: las últimas publicadas, ambas dentro de los
rangos nuevos. Ninguna instalación existente cambia. `uv lock --check` está en el CI
(`.github/workflows/ci.yml:27`), así que **regenerar el lock no es opcional**: si se olvida, el CI
lo caza. El plan ya lo cubre.

## F5 (aceptado) — El cambio no protege a nadie hasta que se publique

La 0.12.2 publicada sigue resolviendo libre. Está declarado en la spec como no-goal y la decisión de
release la tomará el usuario con el PR delante. Se acepta con los ojos abiertos, no se pasa por alto.

## Veredicto

**F1 corrige el plan** (entra una tarea de test). **F2 corrige la documentación** (declarar el
alcance). F3 queda como deuda anotada. Con esas dos correcciones aplicadas, el plan puede aprobarse.
