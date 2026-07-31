# Result review: evaluación de la fase 3 del SDK `mcp` 2.x

## Verdict

`conforms` — los cinco requisitos se cumplen y la decisión queda escrita donde se consulta la
arquitectura, no solo en la traza.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 veredicto de las cinco | sí | sí | tres descartadas, `auth` partida en dos, `elicitation` desbloqueada después |
| REQ-002 comprobación por ejecución | sí | sí | conteos y greps citados uno a uno |
| REQ-003 escrito en `Architecture.md` | sí | sí | sección propia, junto al precedente de OpenTelemetry |
| REQ-004 lo bloqueado, declarado bloqueado | sí | sí | y la medición se hizo: los dos clientes soportan `elicitation` |
| REQ-005 evaluación pieza a pieza | sí | sí | OAuth2 fuera, `bearer_auth` condicionado |

## Findings

1. **El descarte que más cuesta ver es el del interceptor, y por eso es el que mejor sostenido
   está.** Los otros se apoyan en «aquí no existe eso» —cero recursos, cero prompts, un usuario y
   una máquina—; ese se apoya en un conteo que contradice la premisa con la que entró:
   `_log_event` se llama en **tres** sitios, no en once. Sin ese conteo, el argumento habría sido
   una opinión.

2. **`auth` estuvo a punto de descartarse entero, y habría sido un error.** La distinción entre el
   servidor OAuth2 y `bearer_auth` la provocó una pregunta del usuario, no el análisis. Queda
   escrita en `Architecture.md` con su condicionante para que no haya que redescubrirla.

3. **El apunte de las dos aplicaciones no estaba en ningún sitio.** Si algún día se expone el
   daemon, hay que cubrir el endpoint MCP **y** el dashboard de métricas: son dos apps y un
   middleware del SDK no cubre las dos. Ahora está escrito.

4. **La nota sobre la revisión del protocolo mejoró al cerrarse.** Entró como «`LATEST` es
   2026-07-28 pero el defecto es 2025-03-26»; sale con el dato medido: **ninguna de las dos predice
   lo que se negocia** (2025-11-25 y 2025-06-18 en clientes reales).

5. **Alcance respetado**: la implementación del observador no se coló aquí, salió a su propio
   change.

## Required follow-up

- **Nada bloquea el cierre.**
- Queda encolado, ya con el dato: evaluar **`elicitation`** en su propio change, y el **check de
  `doctor`** sobre los clientes observados.
