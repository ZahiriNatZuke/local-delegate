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
# 1. bump de versión en pyproject.toml, server.json, CHANGELOG.md
git commit -am "release: vX.Y.Z"
git tag vX.Y.Z
git push origin main vX.Y.Z    # el tag dispara publish.yml → PyPI
```

`publish.yml` usa `uv publish --check-url https://pypi.org/simple/`, así que reejecutar sobre un
tag existente es idempotente (salta lo ya subido).

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
