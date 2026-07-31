# Publishing / release process

## Versionado

SemVer. Cada release: bump de versión en `pyproject.toml`, `uv.lock` y **las dos** versiones de
`server.json` (`version` y `packages[0].version`), entrada en `CHANGELOG.md`, y tag `vX.Y.Z`.

Que las cuatro coincidan lo comprueba `tests/test_release_metadata.py` en cada PR, y otra vez el
job `check-version` antes de publicar nada: olvidar el bump de `server.json` solo se notaría
cuando PyPI ya tiene la versión, y en PyPI no se puede sobreescribir.

## Un tag publica en los dos sitios

`publish.yml` se dispara con el tag `v*` y encadena tres jobs:

```
check-version  →  pypi  →  mcp-registry
(tag == pyproject == server.json)   (Trusted Publishing OIDC)   (mcp-publisher login github-oidc)
```

Ninguno de los dos publicadores usa secretos: PyPI confía en el OIDC del workflow (Trusted
Publishing) y el registro MCP valida el namespace `io.github.ZahiriNatZuke/*` contra ese mismo
token. `mcp-registry` va **después** de `pypi` y espera a que PyPI sirva la versión, porque el
registro comprueba que el paquete existe y que su README lleva la línea `mcp-name:` antes de
aceptar el descriptor.

Requisito único de PyPI (una vez): configurar un *trusted publisher* para el proyecto
`local-delegate-mcp` con:

| Campo | Valor |
|---|---|
| Owner | `ZahiriNatZuke` |
| Repository | `local-delegate` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

Luego, para publicar una versión nueva:

```bash
# 1. cerrar la sección `## [Unreleased]` del CHANGELOG con la versión y la fecha, y bumpear.
#    `bump_version.py` toca los CUATRO sitios de una vez y regenera el lock: acertar cuatro
#    veces a mano es justo lo que falló en la 0.8.1, donde el lock se quedó atrás.
uv run python scripts/bump_version.py X.Y.Z
uv run python scripts/bump_version.py --check     # los cuatro declaran lo mismo

uv run ruff check .
uv run ruff format --check .
uv run pytest -q          # test_release_metadata.py valida el bump completo
uv build

# 2. el bump entra por PR (main está protegida) y espera a que ci.yml quede en verde
gh pr create --title "chore: release vX.Y.Z" --fill
gh pr merge --squash

# 3. solo entonces publica; un comando hace el resto
git checkout main && git pull
uv run python scripts/release.py X.Y.Z --dry-run   # comprueba y enseña el plan
uv run python scripts/release.py X.Y.Z

# 4. verifica las dos publicaciones
uvx --from local-delegate-mcp==X.Y.Z local-delegate --help
curl -s "https://registry.modelcontextprotocol.io/v0/servers?search=io.github.ZahiriNatZuke/local-delegate" | jq '.servers[] | select(._meta."io.modelcontextprotocol.registry/official".isLatest) | .server.version'
```

## `scripts/release.py`

Un solo comando para todo el release: construye, crea la **GitHub Release** con las notas sacadas
de la sección `## [X.Y.Z]` del `CHANGELOG.md`, le adjunta wheel y sdist, y crea el tag — que es lo
que dispara `publish.yml` → PyPI → registro MCP.

Existe porque el tag a mano dejaba fuera dos pasos que había que recordar cada vez: adjuntar los
artefactos y crear la Release, **que `publish.yml` no crea**.

Aborta antes de tocar nada remoto si: la versión no tiene forma `X.Y.Z`; `pyproject.toml` o
cualquiera de las dos de `server.json` no la declaran; no estás en `main`; `main` local y
`origin/main` difieren; el tag o la release ya existen; o el `CHANGELOG.md` no tiene su sección.
**PyPI es inmutable**: publicar mal no se deshace, solo se tapa con otra versión.

Es un script local y no una acción de GitHub a propósito: `gh release create` crea el tag con tu
credencial y por eso dispara `publish.yml`. Un tag empujado por un workflow con el `GITHUB_TOKEN`
no dispararía nada — GitHub lo bloquea para evitar bucles entre workflows.

**Al verificar, ojo con la caché**: el índice simple y el JSON del paquete se sirven por caminos
distintos y **cualquiera de los dos puede ir por detrás** unos minutos. Comprobar demasiado pronto
enseña la versión vieja y parece que el release falló. Pasó en las dos direcciones: con la 0.12.2 el
índice trajo la 0.12.1 recién publicada, y con la 0.13.0 fue al revés — el índice ya servía la nueva
mientras el JSON seguía anunciando la anterior. Espera un par de minutos y repite con `--refresh`.

**Regenera la captura del README después del bump**, porque la imagen enseña el badge de versión.
Ya no depende de que te acuerdes: `docs/assets/dashboard.json` declara con qué versión se generó
y `tests/test_captura.py` lo compara con `pyproject.toml`, así que **el PR del bump falla hasta
que la regeneres**. Antes esto se pedía solo con palabras, y de 25 releases solo 5 la
regeneraron — la 0.16.0 se publicó con el badge diciendo `v0.15.0`.

**Captura contra el repo, no contra el daemon**, que sirve la versión que tenga instalada y tras
el bump ya no es la del árbol. Y `local-delegate serve --port 9494` **no vale** —es singleton y
el lock lo tiene el daemon del 9393—, igual que `python -m local_delegate.web.metrics`, que
intenta bindear ese mismo puerto y no acepta otro. Hay que montar solo la app de métricas:

```bash
# en una terminal
uv run python -c "import uvicorn; from local_delegate.web import metrics; \
uvicorn.run(metrics.app, host='127.0.0.1', port=9494)"

# en otra
uv run python scripts/dev/capture_dashboard.py --url http://127.0.0.1:9494/
```

El script escribe el PNG **y** su manifiesto. Si aun así capturas contra el daemon, no se cuela
nada: el manifiesto registra la versión vieja —la que la imagen enseña de verdad— y el test sigue
fallando.

Usa datos de ejemplo deterministas, así que no publica tu actividad real; el pie del README lo
declara y ese pie es parte del trato.

`publish.yml` usa `uv publish --check-url https://pypi.org/simple/`, así que reejecutar sobre un
tag existente es idempotente (salta lo ya subido).

El descriptor del registro conserva transporte `stdio` porque describe cómo el paquete se
ejecuta en cualquier host; el daemon HTTP local es un modo operativo adicional.

La wiki nativa se sincroniza después desde `docs/wiki/` en un clone temporal de
`local-delegate.wiki.git`. No publiques la wiki antes de que el tag y PyPI existan.

## Registro oficial MCP

Lo hace el job `mcp-registry` de `publish.yml`; **no hay que ejecutar nada a mano**. Si alguna
vez hay que publicar el descriptor fuera del workflow (una corrección del `server.json` sin
versión nueva del paquete), con el binario
[`mcp-publisher`](https://github.com/modelcontextprotocol/registry/releases):

```bash
mcp-publisher login github     # device-code auth (autorizas en el navegador)
mcp-publisher publish          # publica server.json (desde la raíz del repo)
```

- El `name` es `io.github.ZahiriNatZuke/local-delegate` (autenticación por GitHub).
- **Verificación PyPI↔registro:** el README publicado en PyPI incluye la línea
  `mcp-name: io.github.ZahiriNatZuke/local-delegate` (comentario HTML al inicio del README).
- La `description` de `server.json` debe ser **≤ 100 caracteres** (lo valida el registro).

## CI

[`ci.yml`](../../.github/workflows/ci.yml) en cada push/PR:

| Job | Qué hace |
|---|---|
| `lint` | `uv lock --check`, `ruff check`, `ruff format --check` y `node --check` del `<script>` del dashboard |
| `test` | `pytest` en **matriz de tres sistemas** (ubuntu, windows, macOS): rutas, locks entre procesos y ctypes se comportan distinto en cada uno |
| `install-smoke` | el **único** que no usa `uv.lock`: construye el wheel, lo instala con resolución libre y le exige un handshake MCP. Es lo que caza un major de dependencia que rompa el import |
| `secrets` | gitleaks |

Además, en workflows propios: [`codeql.yml`](../../.github/workflows/codeql.yml) (análisis estático,
también en cron semanal) y [`vendor-audit.yml`](../../.github/workflows/vendor-audit.yml), que vigila
el JavaScript vendorizado —integridad, CVEs en OSV y versión publicada— en cada PR y en cron. El
detalle de los dos está en [Configuración del repositorio](Repo-hardening.md).
