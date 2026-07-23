# Publishing / release process

## Versionado

SemVer. Cada release: bump de versión en `pyproject.toml` **y** en `server.json` (deben coincidir
con el paquete), entrada en `CHANGELOG.md`, y tag `vX.Y.Z`.

## PyPI (Trusted Publishing / OIDC)

La publicación a PyPI es automática al empujar un tag `v*`, vía el workflow
[`publish.yml`](../../.github/workflows/publish.yml) con **Trusted Publishing (OIDC)** — sin
tokens guardados.

Requisito único (una vez): configurar un *trusted publisher* en PyPI para el proyecto
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
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
git commit -am "release: vX.Y.Z"

# 2. publica main y espera a que ci.yml termine en verde
git push origin main
gh run watch --exit-status

# 3. solo entonces publica el tag; este dispara publish.yml → PyPI
git tag vX.Y.Z
git push origin vX.Y.Z
gh run watch --exit-status
```

`publish.yml` usa `uv publish --check-url https://pypi.org/simple/`, así que reejecutar sobre un
tag existente es idempotente (salta lo ya subido).

Después del workflow, verifica que PyPI sirva la versión nueva antes de publicar `server.json` en
el registro MCP. El descriptor del registro conserva transporte `stdio` porque describe cómo el
paquete se ejecuta en cualquier host; el daemon HTTP local es un modo operativo adicional.

## Registro oficial MCP

Con el binario [`mcp-publisher`](https://github.com/modelcontextprotocol/registry/releases):

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
