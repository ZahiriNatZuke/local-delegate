# Implementation plan: Politica de techos de major para las dependencias de runtime

## Approach

**Un cambio pequeño en `main`, con casi todo el peso en el porqué escrito.** El diff de código son
dos rangos; lo que hay que dejar bien es la política y su criterio, porque el fallo que se previene
tarda meses en aparecer y para entonces nadie recuerda por qué el techo estaba ahí.

El criterio, decidido en la spec: **el techo va donde protege de verdad y donde el fallo sería
silencioso** — es decir, en las dependencias que están en el camino de import de arranque **y** cuyo
versionado tiene major real. En `main`: `platformdirs` y `filelock`. En `fastapi`/`uvicorn` un techo
de major sería teatro (0.x rompe por minor) y además su rotura no es silenciosa.

Tres decisiones de encaje, para que este cambio no pelee con el trabajo ya hecho:

- **Se toca solo `pyproject.toml` en las dos líneas que la rama de migración no modifica.** Cero
  conflicto ahí.
- **La política se documenta en `docs/wiki/Repo-hardening.md`, no en `SECURITY.md`**, porque la
  migración ya añade una sección «Dependencias» a `SECURITY.md` y chocarían.
- **El `CHANGELOG.md` sí va a dar conflicto** con la rama de migración: las dos añaden bajo
  `Unreleased`. Es trivial de resolver y no vale la pena torcer nada para evitarlo.

## Ordered tasks

1. **Acotar `platformdirs` y `filelock`, y dejar escrito por qué las demás no**
   - Files or modules: `pyproject.toml` (`dependencies`)
   - Requirements covered: REQ-001, REQ-002, REQ-003, REQ-004
   - Verification: `uv lock` resuelve sin cambiar las versiones ya en uso (`platformdirs` 4.11.0,
     `filelock` 3.32.0); `uv lock --check` en verde, que es lo que exige el CI
   - Rollback or recovery: revertir dos líneas
   - Detalle: el comentario tiene que decir **las dos cosas** — por qué estas llevan techo y por qué
     `fastapi`, `uvicorn` y `httpx` no. La mitad ausente es la que alguien «arregla» por inercia.

2. **Documentar la política con su criterio**
   - Files or modules: `docs/wiki/Repo-hardening.md` (sección nueva)
   - Requirements covered: REQ-006, REQ-007
   - Verification: el documento responde, sin leer el código, a: cuándo poner techo, cuándo no, qué
     hacer cuando sale un major nuevo (**subirlo, no quitarlo**), y qué coste se acepta
   - Rollback or recovery: revertir el fichero
   - Detalle: incluye el coste asumido de REQ-007 —adoptar un major exige publicar, y un techo
     olvidado envejece sin que `install-smoke` lo note— y la verificación pendiente de Dependabot.
   - **Declarar el alcance** *(hallazgo F2 de la revisión)*: la política cubre dependencias
     **directas**, no el árbol completo. Una transitiva puede romper igual, y no es hipotético —
     `starlette` saltó de `0.x` a `1.3.1` arrastrada por un **minor** de `fastapi`, y ningún techo
     nuestro lo habría evitado. Hay que decir qué cubre lo demás (`install-smoke` por detección,
     Dependabot semanal, `uv.lock` para desarrollo). Una política que no declara su alcance produce
     falsa sensación de cobertura, que es peor que no tenerla.

3. **Fijar con un test la premisa de la que depende la política** *(hallazgo F1 de la revisión)*
   - Files or modules: `tests/` (test nuevo)
   - Requirements covered: REQ-003 — protege su fundamento
   - Verification: importar `local_delegate` en un **subproceso limpio** no debe dejar `fastapi` ni
     `uvicorn` en `sys.modules`. El subproceso es obligatorio: dentro de la suite otros tests ya han
     importado el stack web y `sys.modules` estaría contaminado
   - Rollback or recovery: borrar el test
   - Por qué: «`fastapi` y `uvicorn` no llevan techo» se sostiene **solo** mientras entren por import
     perezoso. Basta un refactor que suba `from .web import metrics` al nivel de módulo para que la
     política quede desactualizada **en silencio**. Hoy no hay ninguna red: no existe un solo test
     que mire `sys.modules`. Si la premisa se rompe, hay que enterarse por un fallo, no por un
     incidente.

4. **Entrada en el `CHANGELOG`**
   - Files or modules: `CHANGELOG.md`
   - Requirements covered: trazabilidad para quien instala
   - Verification: la entrada explica el cambio de resolución en términos de **qué le pasa a quien
     instala**, no solo «se añadieron techos»
   - Rollback or recovery: revertir
   - Riesgo conocido: conflicto con la rama de migración, asumido arriba.

5. **Verificar que la instalación real no se rompe**
   - Files or modules: —
   - Requirements covered: REQ-005
   - Verification: `uv build` y comprobar los `Requires-Dist` del wheel —que es lo que de verdad
     viaja a PyPI, no el `pyproject.toml`—; los cuatro pasos del CI en local; `install-smoke` en
     verde en el PR, que resuelve con `--resolution highest` dentro de los rangos nuevos
   - Rollback or recovery: —
   - Por qué el wheel y no el `pyproject.toml`: el escenario que rompió la 0.12.1 fue una
     instalación desde el artefacto publicado. Comprobar el fichero fuente es comprobar la
     intención; comprobar el wheel es comprobar el hecho.

6. **Dejar anotada la verificación que llega sola**
   - Files or modules: `.sdd/changes/techos-major-dependencias/verification.md`
   - Requirements covered: REQ-007
   - Verification: queda escrito que el **lunes 2026-08-03** la corrida de Dependabot dirá si
     propone subir `mcp>=1.2,<2` teniendo `mcp` 2.0.0 publicada. Si lo hace, el riesgo de «techo que
     envejece» está cubierto sin construir nada; si no, hay que decidir otra salvaguarda
   - Rollback or recovery: —

## Test strategy

- **Unit:** **uno nuevo, y solo uno** (tarea 3): la invariante de imports de la que depende la
  política. No se añade ningún test que afirme el contenido de `pyproject.toml` — eso no prueba nada
  que el propio fichero no diga ya. La diferencia está en que el test nuevo comprueba una propiedad
  **del código**, no de la configuración. La suite existente debe pasar **sin tocar un solo test**:
  si alguno falla, es que el cambio no era inocuo y hay que parar.
- **Integration:** `uv lock --check` y `uv sync` sobre el entorno del worktree.
- **End-to-end o manual:** `uv build` + inspección de los `Requires-Dist` del wheel; `install-smoke`
  en el PR, que es el único escenario que reproduce de verdad al usuario que instala.
- **Security and secret scanning:** `gitleaks` del pre-commit y los checks del PR. No entra ninguna
  dependencia nueva, así que **no hace falta depscore nuevo**: acotar un rango no añade superficie.

## Migration and compatibility

- **Nadie baja de versión.** Los techos se ponen por encima de lo que el proyecto ya resuelve
  (`platformdirs` 4.11.0 < 5, `filelock` 3.32.0 < 4), así que ninguna instalación que hoy funcione
  cambia de resolución.
- **El efecto es solo hacia el futuro:** cuando salga `platformdirs` 5 o `filelock` 4, las
  instalaciones nuevas se quedarán en la serie probada en vez de saltar a ciegas.
- **Sin efecto hasta publicar.** Los techos viajan en el wheel; mientras no haya release, la 0.12.2
  publicada sigue expuesta. La decisión de release se toma con el PR ya listo delante (elección del
  usuario), y **no forma parte de este cambio**.
- **Orden con la migración:** este cambio va a `main` y la rama de migración se rebasa encima cuando
  toque. El único conflicto previsto es el del `CHANGELOG`.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.

Pendiente de la revisión adversarial en `plan-review.md` antes de aprobar el gate.
