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

# 3. solo entonces publica el tag; dispara publish.yml → PyPI → registro MCP
git checkout main && git pull
git tag vX.Y.Z
git push origin vX.Y.Z
gh run watch --exit-status

# 4. verifica las dos publicaciones y crea la GitHub Release
uvx --from local-delegate-mcp==X.Y.Z local-delegate --help
curl -s "https://registry.modelcontextprotocol.io/v0/servers?search=io.github.ZahiriNatZuke/local-delegate" | jq '.servers[0].version'
gh release create vX.Y.Z --verify-tag --title "vX.Y.Z" --notes-file <release-notes.md>
```

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
