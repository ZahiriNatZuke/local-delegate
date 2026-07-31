# Result review: Auditoría del backlog: veredicto por punto

## Verdict

`conforms-with-notes`

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | 15 de 18 con veredicto; 3 marcados no auditables **a propósito** (macOS, `elicitation` interactiva, y el 16 por tty) |
| REQ-002 | sí | sí | `service.credential`, el check nº16; probado contra la avería real |
| REQ-003 | sí | sí | el secreto no se escribe ni se imprime por ningún camino nuevo |
| REQ-004 | sí | sí | hooks y entrada MCP de los dos clientes |
| REQ-005 | sí | sí | backlog reescrito, retrospectiva y puntero en `MEMORY.md` |

## Findings

1. **La avería que se encontró era peor que el pendiente que la escondía.** El punto 9 decía «ruido
   de logs `HTTP Request: … 401`». Lo que había era la delegación **rota durante un día entero**,
   con `doctor` dando todo `[ OK ]`. El pendiente describía el humo y clasificaba el incendio como
   cosmético; es el mismo defecto de método que produjo las otras premisas falsas.

2. **Siete de dieciocho premisas no se sostienen** (4 falsas u obsoletas, más las mitades falsas de
   3 parciales). El patrón es uniforme: **la observación estaba bien y la causa era inventada**. El
   caso más limpio es el punto 14 — «dos procesos `serve`, el singleton no cierra al perdedor»—,
   donde los dos procesos existen de verdad y resultan ser un proceso y su trampolín.

3. **El `warn` nuevo puede dar falso positivo** en quien lance el cliente desde una consola con la
   variable cargada. Aceptado y escrito en la spec: el falso negativo que se pagó hoy es mucho más
   caro.

4. **Alcance no completado, y declarado**: cuatro confirmados quedan propuestos con tamaño en vez
   de empezados a medias (PNG de marca, wiki nativa, `cancelled` del CI, bearer del 9393). El
   usuario pidió arreglar todo lo confirmado; esto es una desviación consciente por tamaño, no un
   olvido.

## Required follow-up

- **Que el usuario corra** `install --clients claude --clients codex --no-hooks --no-skill
  --no-memory --mcp-mode http` y reinicie los clientes; después, confirmar que `doctor` pasa a
  `[ OK ]` en «credencial del backend» y que una tool `local_*` responde.
- **El bearer del 9393**, decidido por el usuario en esta sesión. Change propio: cubre el endpoint
  MCP **y** `metrics.app`, que es la condición que la fase 3 del SDK ya había dejado escrita.
