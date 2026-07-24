# Verification: Release 0.10.0, wiki y distribución

## Environment

- Base revision: `af823bc` sobre `codex/moe-remote-canary`; `origin/main` estaba 7 commits detrás
  y sin divergencia.
- Python 3.11/uv; Node disponible; mcp-publisher oficial v1.8.0, checksum Windows amd64 verificado.
- Stable backend preservado: llama-swap v238 y llama-server b9925.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | limpieza + fixture autouse + hash antes/después de pytest | PASS | 192 filas test retiradas, 76 reales conservadas; 160 tests no cambiaron el log |
| REQ-002 | búsqueda coordinada + lock | PASS local | pyproject/runtime/server.json/uv.lock = 0.10.0; changelog creado |
| REQ-003 | revisión README/wiki/recipe | PASS local | nueva `docs/wiki/Remote-backend.md`, enlaces y troubleshooting |
| REQ-004 | suite equivalente a CI, build y smoke aislado | PASS local | 160 passed; Ruff/format/JS/build; wheel import = 0.10.0 |
| REQ-005 | fast-forward y CI main | PENDING external | se ejecuta después del commit de release |
| REQ-006 | PyPI/GitHub/MCP Registry/uvx | PENDING external | tag solo después de CI main |
| REQ-007 | wiki nativa y Obsidian | PENDING external | después de publicación verificable |
| REQ-008 | secrets/checksum/depscore | PARTIAL | publisher SHA-256 coincide; server.json válido; depscore es post-release |

## Quality checks

- [x] `uv lock --check`.
- [x] `uv run ruff check .`.
- [x] `uv run ruff format --check .`: 31 archivos.
- [x] `uv run pytest -q --basetemp <aislado>`: 160 passed; una advertencia preexistente.
- [x] Dashboard extraído y `node --check` aprobado.
- [x] `uv build --clear`: wheel y sdist 0.10.0.
- [x] Import aislado desde wheel: runtime y metadata = 0.10.0.
- [x] `mcp-publisher validate`: server.json válido contra el registro vivo.
- [x] Sdist reconstruido: 76 entradas, cero `.codex/.sdd/.venv/dist`.
- [x] Log real sin cambios durante la suite.

## Deviations and residual risk

- Un primer build reveló que Hatch incluía `.codex` no trackeado y `.sdd` en el sdist. Se corrigió
  con exclusiones explícitas antes de cualquier tag/publicación; el build descartado no salió del
  host y el nuevo inventario tiene cero rutas prohibidas.
- `local-delegate --help` sin subcomando entra al MCP stdio y consultó el backend, que respondió 401
  sin key; no se usó como prueba de versión. El smoke válido importó el wheel en entorno aislado.
- CI, registros externos, wiki y depscore siguen pendientes hasta que exista el commit de release.
