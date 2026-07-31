# Handoff: evaluación de la fase 3 del SDK `mcp` 2.x

## Current state

- SDD status: `result-review`, listo para cerrar.
- Último gate aprobado: `conformance`.
- Revisión: los veredictos entraron en `main` por los PRs #93 y #94; la sección de arquitectura y
  el cierre de la traza van con este trabajo.

## What changed

La fase 3 del SDK deja de ser una lista de pendientes y pasa a ser una decisión escrita:

- **Descartadas del todo, con motivo:** `extension`/`intercept_tool_call` (SEP-2133), `caching`
  (SEP-2549) y `subscriptions` (SEP-2575).
- **`auth` partido en dos:** el servidor de autorización OAuth2 descartado; `middleware/bearer_auth`
  **condicionado** a que el daemon salga de loopback.
- **`elicitation`** se declaró bloqueada por una medición — y esa medición ya se hizo, en el change
  `observador-capabilities-cliente`.
- Todo ello escrito en `docs/wiki/Architecture.md`, sección «Qué se usa del SDK `mcp` 2.x, y qué no»,
  junto al precedente de OpenTelemetry.

## Decisions

Lo que una sesión futura no puede deducir del código:

- **El interceptor no se descartó por pereza, sino por un conteo.** `_log_event` se invoca en
  **tres** sitios de `server.py`, no en once: la telemetría ya está centralizada y está en los
  caminos al backend, que es donde se ve el coste real. Un interceptor solo vería el borde MCP. Es
  la misma objeción que tumbó OpenTelemetry.
- **`subscriptions` no aporta poco: no tendría nada que emitir.** Notifica eventos sobre recursos y
  prompts, y este servidor no expone ni uno (cero `@mcp.resource`, cero `@mcp.prompt`). Cambiaría de
  veredicto solo si algún día se exponen recursos MCP.
- **`bearer_auth` NO está descartado**, aunque el servidor OAuth2 sí. La distinción importa porque
  el daemon puede salir de loopback vía `LOCAL_DELEGATE_WEB_HOST` y ya pasó una vez.
- **Si se expone el daemon hay que cubrir dos apps, no una**: el endpoint MCP y el dashboard de
  métricas. Un middleware del SDK no cubre las dos.
- **Ninguna constante del SDK predice la revisión negociada.** `LATEST` es `2026-07-28` y el defecto
  `2025-03-26`, pero los clientes reales negocian `2025-11-25` y `2025-06-18`.

## Next action

Cerrar el change. Lo que sigue tiene su propia traza: evaluar **`elicitation`** —ya desbloqueada, y
en sentido afirmativo— y el **check de `doctor`** sobre los clientes observados.

## Memory

- Nota canónica: `projects/local-delegate/overview.md` y el backlog del vault.
- Índices actualizados: `docs/wiki/Architecture.md` es la fuente de verdad de los descartes.
