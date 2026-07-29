# Configuración del repositorio

`local-delegate` es un paquete público que se instala con `uvx` y publica en PyPI: quien lo
usa confía en que lo que hay en `main` es lo que se publicó. Esta página recoge la
configuración mínima que sostiene esa confianza, separada en lo que vive **en el repo** (y por
tanto se revisa en un PR) y lo que solo existe en los **ajustes de GitHub**.

## En el repo

| Archivo | Qué aporta |
|---|---|
| `.github/workflows/ci.yml` | tests, ruff, formato, validación del JS del dashboard y escaneo de secretos en cada PR. `permissions: contents: read` (mínimo privilegio) |
| `.github/workflows/codeql.yml` | análisis estático de seguridad (semanal + en cada PR) |
| `.github/workflows/publish.yml` | publicación por OIDC/Trusted Publishing: **sin tokens en secrets**. `permissions: {}` global, ampliado solo en el job |
| `.github/dependabot.yml` | PRs semanales de dependencias Python y de GitHub Actions |
| `.github/CODEOWNERS` | asignación automática de revisión |
| `SECURITY.md` | canal privado de reporte y superficie a tener en cuenta |
| `.pre-commit-config.yaml` | gitleaks + ruff antes de cada commit local |

## En los ajustes de GitHub

No se pueden versionar, así que van en un script idempotente:

```bash
./scripts/setup_repo_security.sh --dry-run   # enseña cada llamada
./scripts/setup_repo_security.sh             # aplica
```

Aplica:

- **Regla sobre la rama por defecto** (`~DEFAULT_BRANCH`, así sigue a la rama y no a su nombre):
  exige PR, prohíbe `force-push` y el borrado, exige la CI en verde con la rama al día, y no deja
  mergear con hilos de revisión sin resolver. Solo squash merge.
- **`code_scanning`**: que el job de CodeQL acabe en verde no basta —puede terminar bien habiendo
  encontrado una alerta—, así que la regla mira las alertas. Se omite con `--no-code-scanning`.
- **Secret scanning** con *push protection*: GitHub rechaza el push que contenga un secreto.
- **Dependabot**: alertas de vulnerabilidades y parches de seguridad automáticos.
- **Private vulnerability reporting**: el canal que anuncia `SECURITY.md`.
- **Ajustes de merge**: solo squash, borrado automático de la rama, auto-merge disponible.

### Usarlo en otro repositorio

Los checks requeridos son los nombres de los jobs de *su* CI, así que se pasan por parámetro:

```bash
./scripts/setup_repo_security.sh --repo OWNER/REPO \
  --checks "Lint, typecheck and unit tests|End-to-end tests" --no-code-scanning
```

El separador es `|` y no la coma **a propósito**: los nombres de job llevan comas
(`Lint, typecheck and unit tests`) y paréntesis (`test (ubuntu-latest)`) con toda naturalidad.
`--check "X"` es la forma repetible para nombres con cualquier cosa rara.

**Antes de aplicar, el script comprueba que alguien reporta cada check pedido** y aborta si no.
Es el error más caro de este script: un check exigido que nadie publica —una errata, un job
renombrado, una matriz que cambió— deja **todos** los PR esperando para siempre. La comprobación
mira la rama por defecto y el PR más reciente, y consulta *check-runs* **y** *commit statuses*:
Actions publica lo primero, pero integraciones como Vercel publican lo segundo. Con
`--skip-verify` se salta, para el caso de un repo cuyo CI todavía no ha corrido nunca.

### Dos decisiones que no son las de por defecto

**Cero aprobaciones requeridas.** Con un único mantenedor, exigir una aprobación bloquea el
repositorio: no puedes aprobar tu propio PR. La barrera que sí aporta aquí es *"todo entra por
un PR con la CI en verde"*, no el conteo de revisiones. Cuando haya más gente:
`./scripts/setup_repo_security.sh --reviews 1`.

**Sin bypass de administrador.** Si el dueño puede saltarse la regla sin darse cuenta, la regla
no protege del descuido — que es exactamente el riesgo en un repo de una persona. Si en algún
momento necesitas la vía de escape: `--admin-bypass`.

### Lo que queda a mano

- **Environment `pypi`**: añade *required reviewers* o restringe el despliegue a tags `v*`, para
  que un push accidental de tag no publique en PyPI sin confirmación
  (*Settings → Environments → pypi*).
- **Settings → Actions**: *Workflow permissions* en **read-only** y desmarcar *Allow GitHub
  Actions to create and approve pull requests*.

## Política de techos de major en las dependencias

Quien instala desde PyPI **resuelve libre y para siempre**: el wheel publicado es inmutable, así que
un major nuevo de una dependencia puede tumbar instalaciones de una versión que llevaba meses
funcionando. Pasó de verdad: `mcp` 2.0.0 salió el 2026-07-28 y dejó la 0.12.1 —ya publicada— muerta
en el import, con el cliente viendo solo `MCP error -32000: Connection closed`.

**`install-smoke` no puede cubrir eso.** Resuelve con `--resolution highest`, sí, pero **cuando corre
el CI** y contra lo que exista en PyPI ese día. El CI de la 0.12.1 pasó en verde porque `mcp` 2.0.0
todavía no existía. Un techo declarado, en cambio, viaja **dentro del wheel** y sigue protegiendo
después de publicar. No son alternativas: `install-smoke` protege hacia atrás y el techo hacia
adelante.

### El criterio

Un techo se pone donde **protege de verdad** y donde el fallo sería **silencioso**. Las dos
condiciones a la vez:

1. **La dependencia está en el camino de import de arranque** — si rompe, el proceso muere antes de
   hablar MCP y el cliente no puede distinguirlo de un problema de conexión.
2. **Su versionado tiene major real.** En `0.x` la ruptura llega por *minor*, así que un `<1` es
   decorativo: da cobertura aparente sin cambiar nada.

| Dependencia | Techo | Por qué |
|---|---|---|
| `mcp` | **sí** | arranque + major real; es la que ya nos costó un incidente |
| `platformdirs` | **sí** | arranque (vía `config.py`) + major real |
| `filelock` | **sí** | arranque + major real |
| `httpx` | no | `0.x`, y **sale del proyecto** con la migración a `mcp` 2.x (su sustituto `httpx2` sí lo lleva, con major real) |
| `fastapi` | no | `0.x` **y** fuera del arranque: `web/metrics.py` entra por import perezoso |
| `uvicorn` | no | `0.x`; **sí** se carga al arrancar, pero lo arrastra el SDK (`mcp` → `sse_starlette`), no este paquete: quien gobierna esa compatibilidad es `sse-starlette`, que ni declaramos |

**El techo se sube, no se quita.** Cuando salga un major nuevo se adopta en un cambio propio, con la
suite y `install-smoke` en verde. Retirarlo «porque molesta» es volver al estado que produjo el
incidente.

### Alcance: solo dependencias directas

Esta política **no cubre el árbol transitivo**, y conviene tenerlo claro para no confiarse. Un
ejemplo real: `starlette` saltó de `0.x` a `1.3.1` arrastrada por un **minor** de `fastapi`, cambió
la preferencia de `TestClient` de `httpx` a `httpx2` y dejó un `DeprecationWarning` en la suite
durante semanas. Ningún techo de este `pyproject.toml` lo habría evitado. Lo mismo vale para
`sse_starlette`, `pydantic`, `anyio` o `httpcore`, que entran por `mcp` y `fastapi` — y de las que
`sse_starlette` está **en el camino de arranque**.

Lo que cubre el resto: `install-smoke` por detección, los PRs semanales de Dependabot con el CI
detrás, y `uv.lock` para desarrollo y CI (que **no** protege a quien instala desde PyPI).

### Lo que cuesta

1. **Adoptar un major nuevo exige publicar una versión.** Con `scripts/release.py` es un comando.
2. **Un techo olvidado envejece en silencio.** `install-smoke` no avisa: resuelve *dentro* del rango
   declarado, así que un techo viejo le parece correcto. Lo que vigila esto son los PRs de
   Dependabot; si alguna vez deja de proponer subidas de rango, hace falta otra salvaguarda.
3. **Puede chocar con otras dependencias** del entorno de quien instala. Riesgo bajo: el modo
   recomendado es `uvx`, que aísla por herramienta, y un choque de resolución es un error visible,
   no un fallo mudo.

### La premisa que hay que vigilar

Que `fastapi` no lleve techo depende de que `web/metrics.py` y `daemon.py` sigan entrando por import
**perezoso**. Un refactor que los suba al nivel de módulo invalidaría la política sin que nadie se
diera cuenta, así que hay un test que lo fija
(`tests/test_core.py::test_importar_el_paquete_no_arrastra_el_stack_web_propio`): corre en un
subproceso limpio y falla apuntando a esta página.

## Convención de ramas

Rama por cambio, con prefijo según lo que hace y un nombre que describa el cambio:

```
feat/<qué-añade>      fix/<qué-arregla>      docs/<qué-documenta>
chore/<mantenimiento> refactor/<qué-reordena>
```

El prefijo del PR y del commit sigue [Conventional Commits](https://www.conventionalcommits.org/es/),
que es lo que alimenta el `CHANGELOG.md`.
