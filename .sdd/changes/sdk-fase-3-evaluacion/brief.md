# Brief: Evaluación de la fase 3 del SDK `mcp` 2.x

## Problem

La migración al SDK 2.x dejó una «fase 3» pendiente con tres nombres —`middleware`, elicitation y
`auth`— apuntados como «mejoras aprovechables», pero **nadie ha comprobado qué ofrecen de verdad ni
si aportan algo a este proyecto**. Es una lista heredada, no un diagnóstico.

Y la lista arrastra dos defectos que este análisis confirma:

1. **Estaba incompleta.** El SDK trae además `caching`, `subscriptions` y `extension`, que nadie ha
   mirado nunca aquí.
2. **Uno de sus nombres no corresponde a nada del SDK.** No hay un `middleware` de tools: lo que
   existe es `Extension` (SEP-2133) con `intercept_tool_call`.

## Desired outcome

Un veredicto por capacidad —**se hace / no se hace, y por qué**— apoyado en lo que el SDK ofrece
realmente y en cómo está montado este servidor. Que alguno acabe en «no se hace» es un resultado
válido y deseable: evita re-evaluarlo cada seis meses, como ya se hizo con OpenTelemetry.

## In scope

- Las cinco capacidades reales: `extension` (el mal llamado middleware), `elicitation`, `auth`,
  `caching` y `subscriptions`.
- Para cada una: qué es, qué aportaría **aquí**, qué la bloquea, y veredicto.
- Dejar escrito el porqué de cada descarte, en el sitio donde se vaya a volver a mirar.

## Out of scope

- **Implementar** cualquiera de ellas: cada una que sobreviva se lleva su propio change.
- **OpenTelemetry**: evaluado y descartado en el PR #48, con el porqué en `Architecture.md`. No se
  re-evalúa.

## Constraints and risks

- **La objeción del PR #48 es reutilizable y hay que aplicarla honestamente:** el borde MCP no ve
  las llamadas al backend, que es donde está el coste. Cualquier capacidad que solo observe el borde
  hereda esa limitación.
- **Varias capacidades dependen del cliente**, no de nosotros. Una que Claude Code o Codex no
  negocien es, en la práctica, código muerto o —peor— una tool que se cuelga esperando.
- Dos de ellas pertenecen a una revisión del protocolo de hace tres días.

## Open questions

- ¿Soportan Claude Code y Codex `elicitation`? **No medido**: el daemon ni siquiera mira las
  capabilities del cliente.
- ¿Qué revisión del protocolo se negocia de verdad en cada cliente?
