# Research: qué le falta al panel para poder decir que no hay adopción

## De dónde sale este cambio

De la medición del 2026-08-18 ([[medicion-adopcion-delegacion]]), donde el panel marcaba
406 329 tokens ahorrados mientras la adopción real era **cero desde el 5 de agosto**. El KPI no
mentía —esos tokens se ahorraron— pero es acumulativo y no distingue quién los pidió, así que un
mes de smoke tests y un mes de trabajo real se ven igual.

Son dos huecos distintos y conviene no confundirlos:

1. **El panel no sabe quién delegó.** El log de uso anota qué se hizo, no quién lo pidió. En la
   primera medición (2026-08-03) las 20 líneas del smoke test del 28-jul sólo se distinguieron
   porque **no aparecían en ningún transcript** — un cruce manual que el panel no puede hacer.
2. **El panel no muestra la puntería del hook.** Desde el PR #146 la telemetría registra `ext` y
   `motivo`, pero `_aggregate_hooks` sólo agrupa por `event`, `category` y día. El defecto que
   costó tres semanas —el hook apuntando a código— seguiría siendo invisible en la interfaz.

## Lo que ya está y no hay que tocar

- `clients.py` **ya observa la identidad** de cada cliente MCP: el middleware `observar_cliente`
  corre en todo mensaje inbound y lee `ctx.session.client_params.client_info`. Lo que falta no es
  observarla, es **llevarla hasta `_log_event`**.
- `_aggregate_hooks` ya es una función pura con su propia batería de tests, y su docstring fija
  una línea que este cambio respeta: **no cruzar sugerencias con delegaciones**. Son dos registros
  sin identificador común y correlacionarlos sería inventar un dato.

## La pieza dudosa, medida

Las tools son **síncronas** (`def local_summarize`, no `async def`), así que el SDK las corre en
un threadpool. La pregunta era si un `ContextVar` puesto por el middleware sobrevive ese salto.

Medido contra el entorno real del proyecto:

```
anyio.to_thread.run_sync ve: claude-code
asyncio.to_thread        ve: claude-code
middleware -> handler    ve: desde-middleware
```

Los tres propagan. **Esto prueba la pieza, no el uso:** entre el middleware y el handler está el
SDK real, y la verificación de este cambio tiene que ser end-to-end —daemon levantado, tool
llamada por un cliente identificado, línea de `usage` inspeccionada— y no este script.

## La puntería que SÍ se puede medir

No la conversión (nada enlaza una sugerencia con la delegación que vino después), sino la
**selectividad interna del hook**: de todas las lecturas que vio, en cuántas avisó y por qué
descartó el resto. Ese dato vive entero dentro de `telemetry.jsonl` y no necesita cruzarse con
nada:

| motivo | qué significa |
|---|---|
| `acotada` | la lectura traía `offset`/`limit` |
| `codigo` | la extensión es de código fuente |
| `pequeno` | por debajo del umbral |
| (sin motivo, `suggested: true`) | avisó |

## Límite conocido

Los eventos anteriores al PR #146 no tienen `ext` ni `motivo`. El agregado tiene que tratar su
ausencia como «desconocido» y no como una categoría vacía, o el panel dirá que el hook descartaba
nada durante tres semanas.
