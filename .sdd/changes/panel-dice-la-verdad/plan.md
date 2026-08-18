# Implementation plan: el panel puede decir que no hay adopción

## Ficheros

| Fichero | Qué cambia |
|---|---|
| `src/local_delegate/clients.py` | El `ContextVar` con la identidad activa y su lectura pública |
| `src/local_delegate/server.py` | `_log_event` escribe `client` |
| `src/local_delegate/web/metrics.py` | `_aggregate` → `by_client`; `_aggregate_hooks` → `by_motivo`/`by_ext`; las dos tarjetas del HTML |
| `tests/test_clients.py`, `tests/test_metrics*.py` | Tests de cada agregado y del registro |
| `CHANGELOG.md` | Entrada en `Unreleased` |

## Tareas

### T1 — la identidad viaja por `ContextVar`

En `clients.py`: un `ContextVar[str | None]` de módulo y una función `cliente_actual()` que lo
lee. El middleware `observar_cliente` lo **setea antes de `call_next`**, que es lo que hace que el
handler lo vea; ponerlo después no serviría de nada.

El nombre y sólo el nombre (REQ-002). La versión y las capabilities siguen yendo a
`clients.jsonl`, que responde otra pregunta.

**Riesgo:** el middleware se salta `initialize` a propósito. Hay que confirmar que `tools/call`
no queda también fuera por algún atajo del SDK — se ve en la verificación end-to-end, no
razonando.

### T2 — `_log_event` firma la línea

Una clave más, omitida cuando no hay identidad (REQ-001, REQ-007). El bloque ya tiene el patrón
`if X is not None: rec[...] = X` para media docena de campos; este va igual. La lectura se
envuelve para que un fallo suyo no rompa la tool: el logging del módulo ya es best-effort y esto
no puede ser la excepción.

### T3 — los agregados

`_aggregate_hooks`: dos diccionarios más, `por_motivo` y `por_ext`. Los eventos sin el campo
cuentan bajo una clave explícita de desconocido, **nunca repartidos ni omitidos** (REQ-005).
Sólo entran los de `category == "read"`: `motivo` no existe en los otros hooks y mezclarlos daría
un denominador que no es.

`_aggregate`: `por_cliente` sobre las filas de uso, con la misma regla para las líneas sin
`client` (REQ-003).

Las dos son funciones puras y ahí es donde vive el criterio; los tests van contra ellas.

### T4 — las dos tarjetas

En la de hooks, una segunda tabla con los motivos. El texto al pie **se mantiene y se amplía**:
sigue diciendo que esto no mide conversión (REQ-006), y ahora dice qué sí mide.

En la de uso, el desglose por cliente. Cero clientes distintos no esconde la tarjeta —eso es
justo el dato— pero un log vacío sí.

### T5 — verificación

Tests de los agregados y del registro, más el **end-to-end**: levantar el daemon, llamar una tool
con un cliente MCP que se identifique, y leer la línea del `usage` en disco. El script del
research demuestra que el `ContextVar` cruza un threadpool; **no** demuestra que cruce el SDK, y
esa es la única pregunta que importa aquí.

### T6 — CHANGELOG

## Lo que puede salir mal

- **Que el SDK no exponga la identidad en `tools/call`.** Si el end-to-end sale sin `client`, el
  diseño se cae entero y hay que buscar el dato en otro sitio (`ctx.request_context`), no
  parchear el test.
- **Que un test del panel asuma el conjunto exacto de claves de `/api/stats` o `/api/hooks`** y
  se rompa al añadir una. Se mira antes de tocar.
- **`_log_event` se llama desde caminos que no vienen de una tool** (arranque, benchmark). Ahí no
  habrá identidad y la clave se omitirá, que es lo correcto — pero conviene comprobar que ninguno
  peta al leer el `ContextVar` fuera de una petición.
