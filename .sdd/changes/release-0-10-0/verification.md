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
| REQ-005 | fast-forward y CI main | PASS | main `3b8a11c`; CI run 30061833941 success antes del tag |
| REQ-006 | PyPI/GitHub/MCP Registry/uvx | PASS | publish run 30061883059; PyPI/uv isolated 0.10.0; GitHub Release; Registry active/latest |
| REQ-007 | wiki nativa y Obsidian | PASS | wiki `445399a`; nota `projects/local-delegate/release-0.10.0-remote-backend.md` + índices |
| REQ-008 | secrets/checksum/depscore | PASS con seguimiento | publisher SHA verificado; artefactos publicados limpios; Socket aún no indexa 0.10.0 y quedó registrado |

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
- [x] Main CI: `30061833941`, success.
- [x] Publish OIDC: `30061883059`, success; PyPI descargado y hashes verificados.
- [x] GitHub Release pública `v0.10.0` (no draft/prerelease).
- [x] MCP Registry: 0.10.0 `active`, `isLatest=true`.
- [x] Wiki nativa actualizada en `445399ad029bafac964438fbde8bf88f8856bd0e`.
- [x] Obsidian canónico e índices de memoria actualizados sin secretos.

## Deviations and residual risk

- Un primer build reveló que Hatch incluía `.codex` no trackeado y `.sdd` en el sdist. Se corrigió
  con exclusiones explícitas antes de cualquier tag/publicación; el build descartado no salió del
  host y el nuevo inventario tiene cero rutas prohibidas.
- `local-delegate --help` sin subcomando entra al MCP stdio y consultó el backend, que respondió 401
  sin key; no se usó como prueba de versión. El smoke válido importó el wheel en entorno aislado.
- Socket devolvió `No score found` para 0.10.0 inmediatamente después del publish; 0.9.0 conserva
  100/100/99/97/100. No hay dependencias nuevas y los imports reales se auditaron. Se registró el
  reintento como seguimiento explícito; no se presenta la ausencia de score como resultado verde.
