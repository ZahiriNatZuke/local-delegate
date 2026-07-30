# Specification (lite) — probar Codex contra el daemon migrado

Change `probar-codex-daemon`, modo `lite`. **No cambia código del proyecto:** es una verificación
pendiente desde la migración al SDK `mcp` 2.x (publicada en la 0.13.0).

## Resumen

La migración dejó anotado: *«Codex no se ha probado contra el daemon migrado. Comparte transporte con
Claude Code y el riesgo del protocolo ya está descartado, pero no es lo mismo que haberlo visto.»*
Esto lo ve.

## Requisitos

- **REQ-001:** Codex reconoce el servidor `local-delegate` con el transporte correcto contra el
  daemon del SDK 2.x.
- **REQ-002:** Codex **llama** de verdad a una tool `local_*` y recibe la respuesta, no solo hace
  handshake.
- **REQ-003:** La llamada queda registrada en el log del daemon: se verifica **por los dos extremos**,
  no solo por lo que dice el cliente.
- **REQ-004:** Cualquier fallo que aparezca se acota a su causa antes de darlo por bueno o por malo.

## Escenario de aceptación

- **Dado** el daemon corriendo el SDK 2.x en `127.0.0.1:9393`,
- **Cuando** Codex ejecuta una tarea que necesita una tool `local_*`,
- **Entonces** la tool responde, Codex usa su resultado, y el evento aparece en
  `usage-YYYYMM.jsonl` con `ok: true`.

## No-goals

- No se cambia la configuración de Codex del usuario: es suya, no del repo.
- No se prueban las 11 tools; basta una que ejercite el camino completo.
- No se arregla nada de fuera de local-delegate sin permiso explícito.

## Trazabilidad

| Req | Evidencia |
|---|---|
| REQ-001 | `codex mcp get local-delegate` → `transport: streamable_http`, `url: http://127.0.0.1:9393/mcp`, `enabled: true` |
| REQ-002 | `codex exec` → `mcp: local-delegate/local_classify started` → `(completed)`; devolvió `error`, la etiqueta correcta |
| REQ-003 | Evento en el log del daemon: `local_classify`, `gemma3-4b`, `ok: true`, `tokens_in: 67`, `v: 0.13.1` |
| REQ-004 | Dos fallos acotados a su causa, ninguno de local-delegate — ver `verification.md` |
