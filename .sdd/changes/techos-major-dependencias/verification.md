# Verification: Politica de techos de major para las dependencias de runtime

## Environment

- Revision: rama `feat/techos-major-dependencias`, sacada de `main` (`cf3692f`), en el worktree
  `D:\Projects\local-delegate-techos` — aparte a propósito, para no tocar el checkout donde corre el
  daemon (que está en `feat/mcp-sdk-2`).
- Relevant runtime and tool versions: Windows 11, Python 3.11.15, `mcp` 1.29.0, `httpx` 0.28.1,
  `platformdirs` 4.11.0, `filelock` 3.32.0, `fastapi` 0.140.7, `uvicorn` 0.51.0 — es decir, el mundo
  de `main`, sin la migración.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | Techos en el artefacto que de verdad viaja a PyPI | ✅ | `uv build` → `METADATA` del wheel: `Requires-Dist: filelock<4,>=3` y `platformdirs<5,>=4`. **Se comprobó el wheel, no el `pyproject.toml`**: el fichero fuente es la intención, el wheel es el hecho, y lo que rompió la 0.12.1 fue una instalación desde el artefacto |
| REQ-002 | Cada techo con su motivo al lado | ✅ | Comentarios en `pyproject.toml`, siguiendo el precedente del de `mcp` |
| REQ-003 | `fastapi`/`uvicorn` sin techo, con **su** razón cada una | ✅ | Comentario en `pyproject.toml` con las dos razones separadas tras la corrección (ver abajo) |
| REQ-003b | La premisa queda fijada por un test | ✅ | `test_importar_el_paquete_no_arrastra_el_stack_web_propio`, en subproceso limpio. **Cazó un error real antes de mergear** |
| REQ-004 | `httpx` sin tocar, con el motivo escrito | ✅ | `Requires-Dist: httpx>=0.27`, sin cambio; comentario explicando que está en `0.x` y sale con la migración |
| REQ-005 | La resolución real no se rompe | ✅ | `uv lock` no movió **ninguna** versión resuelta: el diff de `uv.lock` son solo los dos `specifier`. `uv lock --check` en verde. `install-smoke` pendiente del PR |
| REQ-006 | Política documentada donde se busca | ✅ | Sección nueva en `docs/wiki/Repo-hardening.md`: criterio, tabla dependencia a dependencia, «el techo se sube, no se quita», alcance y coste |
| REQ-007 | Coste asumido y qué lo vigila | ✅ | Sección «Lo que cuesta» del documento + la verificación pendiente de Dependabot, abajo |

## El test cazó un error del análisis antes de mergearlo

El test de REQ-003b **falló en su primera ejecución**, y tenía razón: importar `local_delegate`
**sí** carga `uvicorn`. El research había deducido lo contrario leyendo los imports **de este repo**,
sin ejecutar.

Rastreado con un hook en `sys.meta_path`:

```
local_delegate/__init__.py → server.py:32 (from mcp.server.fastmcp import FastMCP)
  → mcp/server/fastmcp/server.py:62 → mcp/server/sse.py:49 → sse_starlette → uvicorn
```

Medido, no supuesto:

| Módulo | ¿Cargado tras `import local_delegate`? |
| --- | --- |
| `fastapi` | **no** — la premisa se cumple |
| `local_delegate.web.metrics` / `daemon` / `cli` | **no** — el import perezoso funciona |
| `uvicorn`, `starlette`, `sse_starlette` | **sí** — los arrastra el SDK |

**Qué cambió:** la decisión práctica no —`uvicorn` sigue sin techo— pero su razón sí, y era la mitad
del argumento. No es que esté fuera del camino de arranque: **está dentro**, y lo que gobierna su
compatibilidad ahí es `sse-starlette`, una transitiva que este repo ni declara. Un techo nuestro
habría dado cobertura aparente sin cambiar nada. `spec.md` (REQ-003) y `research.md` quedaron
corregidos con la enmienda marcada como tal, no reescritos por lo bajo.

El test se ajustó para fijar **lo que este repo sí controla** (`fastapi` y los módulos propios) y
deja `uvicorn` fuera del assert con el porqué en el docstring: afirmarlo sería fijar un detalle
interno del SDK.

**Esto es exactamente lo que el hallazgo F1 de la revisión adversarial buscaba**, y llegó antes de lo
previsto: no protegió de un refactor futuro, sino de un error presente en el propio análisis.

## Quality checks

- [x] Project-native tests pass. — `pytest -q` → **234 passed** (233 de `main` + 1 nuevo). Ningún
      test existente se tocó.
- [x] Lint, formatting, type checking, and build checks pass where applicable. — `ruff check .`
      (All checks passed), `ruff format --check .` (43 files), `extract_dashboard_js.py` +
      `node --check` OK, `uv lock --check` OK, `uv build` OK.
- [x] Secret scanning passes. — `gitleaks` del pre-commit.
- [x] No unrelated changes are present. — el diff toca `pyproject.toml`, `uv.lock`, un test,
      `docs/wiki/Repo-hardening.md`, `CHANGELOG.md` y la traza SDD. Nada más.

El único warning de la suite es el `StarletteDeprecationWarning` de `httpx` que **ya existe en
`main`** — y que es, de hecho, el ejemplo de rotura por transitiva que cita la documentación nueva.
Desaparece con la migración a `mcp` 2.x. No es una regresión de este cambio.

## Deviations and residual risk

- **No protege a nadie hasta que se publique.** Los techos viajan en el wheel; la 0.12.2 que está en
  PyPI sigue resolviendo libre. Decisión de release aplazada por el usuario a cuando el PR esté
  listo. Declarado como no-goal en la spec, no como olvido.
- **Verificación que llega sola: el lunes 2026-08-03.** El riesgo de «techo que envejece» se apoya en
  que Dependabot proponga **subir un rango que le bloquea** — no solo actualizar el lock. Hay
  evidencia de que cruza majors cuando el manifiesto se lo permite (PRs #13, #6, #5, #4 con
  `codeql-action` 3→4, `setup-uv` 6→7, `checkout` 4→7), pero **no** de que suba un techo. La prueba
  llega sola: `main` tiene `mcp>=1.2,<2` con `mcp` 2.0.0 ya publicada, así que la corrida semanal del
  lunes lo dirá. Si no propone nada, hace falta otra salvaguarda y se decide entonces.
- **La política no cubre transitivas**, y el propio arranque depende de `sse_starlette` y
  `starlette`, que no declaramos. Está escrito en el documento en vez de dejarlo implícito, porque
  una política que no declara su alcance produce falsa sensación de cobertura.
- **F3 de la revisión, deuda menor anotada:** la política vive en `docs/wiki/Repo-hardening.md` para
  no chocar con la sección «Dependencias» que la rama de migración añade a `SECURITY.md`. Cuando esa
  rama se mergee, conviene reconsiderar si las dos deberían vivir juntas.
- **Conflicto previsto con la rama de migración:** solo en `CHANGELOG.md`, porque las dos añaden bajo
  `Unreleased`. `pyproject.toml` **no** choca: este cambio toca `platformdirs` y `filelock`, líneas
  que la migración no modifica.
- **Limitación de proceso:** la revisión adversarial del plan no fue independiente — la hizo el mismo
  agente que escribió el plan, sin subagentes.
