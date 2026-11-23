# Implementation plan: doctor avisa si el MCP local-delegate está deshabilitado para el proyecto en Claude Code (#705)

## Approach

`checks.Context` gana `cwd: Path | None = None` (None: `Path.cwd()` al llamar al probe), para
que los tests lo inyecten. `_probe_mcp_claude`, tras encontrar la entrada, busca el proyecto del
directorio actual en `data["projects"]` (`_claude_project_disabling`, normalizando la ruta y subiendo
por los ancestros) y, si `local-delegate` está en `disabledMcpServers` o `disabledMcpjsonServers`,
devuelve `WARN` con detalle y remedio nuevos del catálogo.

## Ordered tasks

- [x] T1 — Tests rojos con `~/.claude.json` sintéticos (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: tests/test_doctor_mcp_disabled_for_project.py
  - Verification: fallan sin el arreglo
  - Depends on: none
- [x] T2 — `Context.cwd`, `_claude_project_disabling` y aviso en `_probe_mcp_claude` con i18n (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: src/local_delegate/checks.py, resources/i18n/{es,en}/doctor.json
  - Verification: tests de T1 y suite completa
  - Depends on: T1

## Test strategy

- Unit: el probe con HOME temporal y `cwd` inyectado.
- Integration: `doctor --home <HOME simulado>` del worktree, comparando el fichero antes/después.
- End-to-end or manual: lo de arriba.
- Security and secret scanning: `personal-security-check` antes del commit.

## Migration and compatibility

- Aditivo; `Context` con campo opcional nuevo al final.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
