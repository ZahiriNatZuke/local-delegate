# Research: Release 0.10.0, wiki y distribución

## Current behavior

- `origin/main...HEAD = 0/7`: la integración puede ser fast-forward, sin resolver divergencia.
- `pyproject.toml`, `src/local_delegate/__init__.py` y `server.json` declaran 0.9.0; `uv.lock`
  deriva la versión del proyecto.
- `.github/workflows/publish.yml` se activa por tag `v*`, construye y publica en PyPI por OIDC,
  pero no crea GitHub Release ni publica el registro MCP.
- GitHub autentica correctamente como `ZahiriNatZuke`; la release pública actual es v0.9.0.
- La wiki nativa responde en `local-delegate.wiki.git`; `docs/wiki` es su fuente versionada.
- La suite final pasó 160 tests y quedó aislada de los logs reales mediante `tests/conftest.py`.
- El piloto remoto autenticado ya pasó 20/20 desde la Mac; la recipe vive en
  `docs/recipes/remote-backend.md`.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| Versión | metadatos de paquete/registro | bump atómico | pyproject, `__version__`, server.json, lock |
| Release | publicación por tag | CI, PyPI, GitHub Release | publish.yml, docs/wiki/Publishing.md |
| Registro MCP | descriptor público | publicar después de PyPI | server.json; publisher oficial |
| Wiki | documentación operativa | añadir remoto y sincronizar | docs/wiki + wiki git remota |
| Mac | cliente MCP local/backend PC | comandos exactos 0.10.0 | remote-backend.md + canary PASS |
| Seguridad | key/telemetría/temp | no secretos; limpieza final | DPAPI/Keychain, gitleaks, inventario temp |

## Existing conventions

- Keep a Changelog y SemVer; `pyproject.toml`, `__version__` y `server.json` deben coincidir.
- Primero push de `main` y CI; solo después tag. PyPI debe existir antes del registro MCP.
- Trusted Publishing OIDC: no crear tokens de PyPI.
- Recetas sin valores secretos ni placeholders ambiguos en el camino principal.

## Dependencies and integrations

- No se añaden dependencias Python. Socket solo audita el paquete publicado.
- Sistemas externos: GitHub Actions/Releases/Wiki, PyPI y MCP Registry.
- `mcp-publisher` oficial latest verificado en vivo: v1.8.0, asset Windows amd64 con digest
  SHA-256 publicado. Se instala temporalmente y se elimina al terminar.

## Risks and unknowns

- Confirmado: auth GitHub, wiki remota, rama fast-forward y workflow OIDC.
- A validar en ejecución: CI verde, disponibilidad 0.10.0 en PyPI, `uvx` en vacío, publicación
  del registro y depscore Socket sin regresión.
- Riesgo: login del publisher puede pedir autorización interactiva; si no hay credencial cacheada,
  ese es el único paso que puede requerir al usuario.
