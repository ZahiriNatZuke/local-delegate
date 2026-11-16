# Brief: Entrega Codex nativa: hooks de usuario, instalador, diagnóstico y atribución por sesión (#669)

## Problem

local-delegate registra el MCP y `AGENTS.md` para Codex, pero no le entrega hooks: el instalador
solo los pone cuando el destino incluye Claude, e importar el plugin de Claude no sirve (#668).
Las delegaciones de Codex quedan en el log sin sesión ni modelo de quien llama.

## Desired outcome

Codex recibe hooks propios en el formato que acepta 0.169.0, instalados, actualizados,
diagnosticados y retirados por local-delegate sin tocar los hooks del usuario; cada delegación
de Codex queda atribuida a su sesión (clave de un solo sentido) y modelo cuando el hook la anotó,
y como desconocida cuando no.

## In scope

- Hooks de usuario en `~/.codex/hooks.json`: consejo de delegación (`UserPromptSubmit`),
  recordatorio a subagentes (`SubagentStart`) y nota de llamada para las tools de local-delegate
  (`PreToolUse`, directas y desde code mode).
- `install`, `update`, `doctor` (check `codex.hooks`) y `uninstall` para esa pieza.
- Atribución por `_meta.callId` de Codex con la nota del hook.
- Documentación de lo cubierto y lo no cubierto; pasos de la prueba de confianza para el usuario.

## Out of scope

- Resumen automático de lecturas y guard de escritura en Codex (lectura, shell, MCP de ficheros,
  `apply_patch`): issue #670.
- Matriz de capacidades, comandos sin modelo, barra de estado y herramientas fijadas: issue #671.
- Plugin de Codex propio (marketplace, caché, `codex plugin add`).
- Generar `trusted_hash` o saltarse la revisión de confianza.

## Constraints and risks

- No tocar el `~/.codex` real: pruebas con `CODEX_HOME` temporal y hash antes/después.
- La clave de confianza de Codex depende de la posición del grupo: reinstalar debe conservarla.
- Un hook nunca bloquea (nunca sale con 2) y nada depende del backend.
- Sin datos sensibles: ni ids de sesión en claro ni rutas de transcript en las notas de Codex.

## Open questions

- Ninguna que cambie la especificación: el nombre exacto del `tool_name` MCP se cubre con un
  matcher que acepta las dos grafías.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-16 Original request, verbatim:

  > Resolver #669 de ZahiriNatZuke/local-delegate: «Implementar entrega Codex nativa: hooks, instalador, diagnóstico y atribución de sesión verificable». Adaptador de hooks Codex con la forma realmente soportada (Codex CLI 0.169.0), integrado en install/update/doctor/uninstall con dry-run, idempotencia, respaldos y coexistencia; atribución por sesión solo con datos observados; fallo en abierto con el backend caído; sin trusted_hash ni saltarse la revisión de confianza. Si el alcance es demasiado grande, núcleo (adaptador + install/update/doctor/uninstall) y el resto documentado.
