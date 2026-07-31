# Specification: Auditoría del backlog: veredicto por punto

## Summary

Cada punto del backlog queda con un veredicto respaldado por una ejecución reproducible, y lo que
resulte confirmado y quepa en la sesión queda arreglado. La avería que destapó la auditoría —las
tools `local_*` devolviendo `401` desde el 2026-07-30 sin que ningún check lo viera— deja de ser
invisible para el diagnóstico.

## Requirements

- **REQ-001:** Cada uno de los 18 puntos auditables tiene veredicto y **el comando y la salida** que
  lo respaldan. Los no auditables en esta máquina se marcan como tales, sin veredicto.
- **REQ-002:** `local-delegate doctor` avisa cuando el proceso MCP que arranca el cliente **no
  podrá autenticarse** contra el backend, aunque el daemon lo vea perfectamente.
- **REQ-003:** El aviso ofrece un arreglo que funciona y **no escribe el secreto** en ningún
  fichero de configuración.
- **REQ-004:** `install --dry-run` imprime el **texto exacto** de lo que va a escribir cuando ese
  texto es generado (comandos de los hooks y entrada MCP), no solo cuántas cosas escribe.
- **REQ-005:** El backlog queda reescrito: los FALSO y OBSOLETO borrados, los demás con su
  veredicto y tamaño, y una propuesta de orden de ataque.

## Acceptance scenarios

### Scenario: el cliente no podrá autenticarse y el daemon sí

- **Given** un backend que responde `401` a quien no lleva credencial, y la entrada MCP registrada
  en modo `stdio` sin la variable en el entorno
- **When** se corre `local-delegate doctor`
- **Then** aparece `[WARN] credencial del backend`, nombrando al cliente, diciendo que sus tools
  responderán `401`, y ofreciendo `install --mcp-mode http`

### Scenario: el mismo backend con las entradas por el daemon

- **Given** el mismo backend que exige credencial
- **When** las entradas MCP están en modo `http`
- **Then** el check sale `ok` — es el modo lo que cambia el veredicto, no el backend

### Scenario: revisar el plan antes de aplicarlo

- **Given** un `install --dry-run`
- **When** el plan incluye registrar hooks o la entrada MCP
- **Then** debajo de cada acción aparece el string exacto que se escribiría

## Edge cases and failure behavior

- **No se pudo preguntar al backend** (caído, o responde algo que no es 2xx ni 401/403): el check
  es `unknown`, nunca `missing` ni `warn`. Lo no comprobable no se decide por descarte.
- **La credencial está en el entorno**: el proceso `stdio` la hereda, así que sale `ok` aunque el
  backend la exija.
- **No hay ninguna entrada MCP que mirar**: `unknown`.
- El entorno del proceso de `doctor` se usa como **testigo** del entorno del cliente. No es exacto
  —se puede lanzar el cliente desde una consola con la variable cargada—, y por eso el aviso nombra
  el síntoma comprobable (`401` en las tools) en vez de afirmar que la máquina está rota.

## Non-functional requirements

- **El secreto no se escribe nunca**: ni en `~/.claude.json`, ni en el registro de Windows, ni en
  la salida de `doctor`. `--api-key-env` tampoco salva aquí, porque reenvía una variable que sale
  del mismo entorno vacío.
- **`probe` no escribe**: se mantiene la invariante del registro de comprobaciones.
- **El grupo `andamiaje` no sale a la red**: por eso el check nuevo vive en `servicio`. `install`
  depende de esa propiedad para reportar sin tocar nada externo.
- Los colaboradores de red van doblados en **los dos** arneses (`make_ctx` y `_stub_environment`).

## Non-goals

- Cambiar el default de `install` a `http` cuando detecte un daemon vivo: es una decisión de
  producto mayor y el usuario la descartó para esta sesión.
- Autenticar el endpoint del daemon (`bearer_auth`): decidido hacerlo, pero es change propio.
- Rasterizar los PNG de marca en el CI, sincronizar la wiki nativa y cubrir el `cancelled` del CI:
  confirmados y propuestos con tamaño.

## Traceability

| Requisito | Trabajo | Verificación |
| --- | --- | --- |
| REQ-001 | auditoría de los 18 puntos | `verification.md`, tabla de veredictos |
| REQ-002 | `checks._probe_mcp_credential`, `doctor.backend_requires_key` | 5 tests + `doctor` real |
| REQ-003 | `checks.CREDENTIAL_HINT` | `test_credencial_warn_…`, y no hay secreto en la salida |
| REQ-004 | `install.Action.literal` | `test_dry_run_enseña_el_comando_literal_de_cada_hook` |
| REQ-005 | `projects/local-delegate/backlog.md` en el vault | nota reescrita |
