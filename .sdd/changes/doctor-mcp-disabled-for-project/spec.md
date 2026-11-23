# Specification: doctor avisa si el MCP local-delegate está deshabilitado para el proyecto en Claude Code (#705)

Nivel `lite`: solo diagnóstico (lee `~/.claude.json`, no escribe), pero cambia una comprobación
visible de `doctor`.

## Summary

Claude Code guarda lo que se deshabilita con `/mcp` por proyecto, en `~/.claude.json`,
`projects.<ruta>.disabledMcpServers` (servidores de usuario/local) y
`projects.<ruta>.disabledMcpjsonServers` (los de `.mcp.json`). Si `local-delegate` está en una
de esas listas del proyecto del directorio actual, `doctor` lo dice como aviso con el remedio.

## Requirements

- **REQ-001** — La comprobación `scaffold.mcp_claude` da `warn` cuando la entrada está registrada
  pero `local-delegate` figura en `disabledMcpServers` o `disabledMcpjsonServers` del proyecto
  del directorio actual, y el remedio dice `/mcp` → habilitar.
  - Request: "doctor debe avisar con el remedio (`/mcp` → habilitar) para el proyecto del directorio actual"
  - Verify: test tests/test_doctor_mcp_disabled_for_project.py
- **REQ-002** — Deshabilitado en **otro** proyecto, o sin esas claves, o sin entrada del proyecto:
  sigue `ok` como hoy.
  - Request: derived: datos que distingan (otro proyecto, sin la clave)
  - Verify: test tests/test_doctor_mcp_disabled_for_project.py
- **REQ-003** — La ruta del proyecto se compara normalizada (barras `\` y `/`, mayúsculas en
  Windows) y, si el directorio actual no tiene entrada, vale la del ancestro más cercano que la
  tenga.
  - Request: derived: `~/.claude.json` mezcla `D:/…` y `D:\\…` en sus claves
  - Verify: test tests/test_doctor_mcp_disabled_for_project.py
- **REQ-004** — `doctor` no escribe `~/.claude.json` ni imprime otros valores suyos; `update` no
  intenta repararlo (el aviso es `warn`, no `missing`).
  - Request: derived: el fichero puede llevar secretos y habilitarlo es decisión del usuario
  - Verify: test tests/test_doctor_mcp_disabled_for_project.py

## Acceptance scenarios

### Scenario: deshabilitado en este proyecto

- **Given** un `~/.claude.json` sintético con la entrada y `local-delegate` en
  `disabledMcpServers` del proyecto del directorio actual
- **When** se corre el probe
- **Then** `warn`, el detalle nombra el proyecto y el remedio lleva `/mcp`

## Edge cases and failure behavior

- `projects` o las listas con tipos raros: se ignoran (queda `ok`).

## Non-functional requirements

- Mensajes en es y en (catálogo i18n); nombres de código en inglés.

## Non-goals

- Cambiar los hooks para que no recomienden las `local_*` (otra tarea).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
