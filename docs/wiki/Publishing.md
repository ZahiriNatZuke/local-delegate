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
# 1. bump de versión en pyproject.toml, uv.lock, server.json y CHANGELOG.md
uv lock
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

**Al verificar, ojo con la caché**: PyPI sirve el índice y el JSON del paquete con caché y puede
anunciar la versión anterior durante unos minutos. Comprobar demasiado pronto enseña la vieja —
pasó en vivo con la 0.12.2, donde una instalación de prueba trajo la 0.12.1 recién publicada.

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

[`ci.yml`](../../.github/workflows/ci.yml) en cada push/PR: `ruff check`, `ruff format --check`,
`pytest`, `node --check` del `<script>` del dashboard, y **gitleaks** (escaneo de secretos).
