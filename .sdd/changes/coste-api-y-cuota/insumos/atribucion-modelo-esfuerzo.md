# Atribuir a cada delegación el modelo y el esfuerzo de quien la pidió

Investigación y prueba en vivo del 2026-10-06 para el cambio `coste-api-y-cuota`. Responde a la
decisión del usuario: el coste equivalente a precio de API no se calcula con un modelo supuesto
para todo, sino con el modelo y el esfuerzo de quien pidió cada delegación.

Marcas: **[V]** verificado por mí (ejecutado o leído), **[I]** inferido, **[N]** no verificado.

## Resumen

- **[V] Sí se puede atribuir cada llamada con exactitud.** Claude Code manda en cada `tools/call`
  el `_meta["claudecode/toolUseId"]`, que es el **mismo** `tool_use_id` que reciben los hooks y que
  queda en el transcript. Con esa clave el cruce es exacto, sin heurística de horas.
- **[V] Ninguna vía da el modelo directamente al MCP.** Ni las cabeceras, ni el `clientInfo`, ni
  el `_meta`, ni la entrada de los hooks traen `model`. El modelo solo está en el transcript
  (`message.model`), también en el del subagente.
- **[V] El esfuerzo sí llega al hook** como `effort: {"level": "low"}` cuando el modelo lo admite;
  no aparece con Haiku. El transcript también lo guarda por línea (`effort`).
- **[V] El histórico casa bien:** el 96,5 % de las líneas de Claude Code de los últimos 30 días
  casa con un único `tool_use`, 7 son ambiguas (3,1 %) y 1 no aparece.
- **[V] El resultado varía, pero sobre todo por el hilo y por N, no por el esfuerzo.** Con
  atribución por evento, el total de los casos reales da **$38,5**; el supuesto de la spec
  (REQ-022: Opus 5.5 en subagente, N = 49,5) da **$19,8**, es decir, la mitad. Los 17 casos del
  hilo principal son el 43 % de los tokens y el 58 % del coste.
- **[V] El esfuerzo no se puede contrastar con el histórico:** todas las delegaciones reales se
  pidieron con esfuerzo `high`. Hay que guardarlo desde ya para poder medirlo más adelante.

## Pregunta 1. En el momento de la llamada: de dónde sacar el modelo y el esfuerzo

### Cómo se probó

- Hay un directorio vacío en el scratchpad (`atribucion/vivo/`). Se lanzó `claude -p` con
  `--settings ajustes.json`, que añade hooks `PreToolUse`/`PostToolUse` (matcher `.*`),
  `SessionStart`, `SubagentStart`, `SubagentStop`, `UserPromptSubmit` y `Stop`, y con todos ellos
  vuelca su stdin a `salida/hooks.jsonl`. Para las tools MCP, el hook busca además en el
  transcript (el principal o el del subagente) la línea con ese `tool_use_id` y guarda solo
  modelo y esfuerzo.
- Con `--mcp-config` se añadió una **sonda MCP** propia (`sonda_mcp.py`, Streamable HTTP, solo
  stdlib), que registra cabeceras, método, `clientInfo` y `_meta` de cada petición. Hacía falta
  porque el daemon real no se puede instrumentar sin tocar el repo.
- Se hicieron cuatro corridas, en serie:

| Corrida | Modelo principal | Esfuerzo | Qué hizo | Coste a precio de lista |
|---|---|---|---|---|
| r1 | Haiku 4.5 | (heredado) | Haiku lanzó dos subagentes por su cuenta: uno llamó a `local_status` y el otro a la sonda | $0,18 |
| r2 | Haiku 4.5 | `--effort low` | Las dos llamadas desde el hilo principal (`Agent` prohibido) | $0,08 |
| r3 | Sonnet 5 | `--effort low` | Una llamada principal y un subagente sin modelo indicado | $0,35 |
| r4 | Sonnet 5 | `--effort high` | `local_status` desde el principal y un subagente con `model='haiku'` | $0,21 |

Para medir el esfuerzo hubo que usar Sonnet: con Haiku 4.5 no se puede, porque el modelo no admite
esfuerzo y ni el hook ni el transcript lo guardan.

**`--settings` añade y no reemplaza [V].** Durante mis corridas, el hook `UserPromptSubmit` del
usuario escribió en `~/.claude/hooks/telemetry.jsonl` una línea por cada una de mis cuatro
sesiones. Los hooks de usuario siguieron activos.

### (a) La petición MCP [V con la sonda]

- **Cabeceras:** `User-Agent: claude-code/2.1.291 (sdk-cli)`, `mcp-protocol-version` y
  `mcp-session-id`. No traen modelo, esfuerzo ni sesión de Claude. El sufijo `(sdk-cli)` es el
  punto de entrada; en interactivo sería `cli` **[I]**, que es lo que vale
  `CLAUDE_CODE_ENTRYPOINT` en esta sesión.
- **`clientInfo`** (en `initialize` y también en `_meta` de `server/discover`): nombre
  `claude-code`, título, versión 2.1.291, descripción y web. Nada del modelo.
- **`tools/call` → `params._meta`:**
  `{"claudecode/toolUseId": "toolu_…", "progressToken": N}`. Ese identificador es **idéntico** al
  `tool_use_id` del hook y al `id` del bloque `tool_use` del transcript. Se comprobó en las
  cuatro corridas, también desde subagentes.
- **Hoy el repo no lo lee.** `clients.observar_cliente` (`src/local_delegate/clients.py:254`)
  solo guarda `client_info.name` en un `ContextVar`, y `_log_event`
  (`src/local_delegate/server.py:453`, campo `client` en la línea 514) escribe ese nombre. **[V
  en código, no ejecutado]** El SDK 2.2.0 conserva las claves desconocidas de `_meta`
  (`RequestParamsMeta(TypedDict, extra_items=Any)`, `mcp_types/_types.py:80`) y el contexto del
  servidor las expone como `.meta` (`mcp/server/context.py:46`). El mismo middleware puede leer
  `ctx.meta.get("claudecode/toolUseId")`.

### (b) Los hooks [V]

Entrada de `PreToolUse`/`PostToolUse` sobre una tool `mcp__*` en Claude Code 2.1.291:

| Campo | Hilo principal | Subagente |
|---|---|---|
| `session_id`, `transcript_path`, `cwd`, `permission_mode`, `prompt_id`, `tool_use_id`, `mcp_server` | sí | sí (con el `session_id` y el `transcript_path` del **principal**) |
| `agent_id`, `agent_type` | no | sí (p. ej. `general-purpose`) |
| `effort` | `{"level": "low"\|"high"}` si el modelo admite esfuerzo; falta con Haiku | igual: falta en el subagente Haiku de r4 |
| `model` | **nunca** | **nunca** |

- **`SessionStart`** (en `-p`) solo trae `session_id`, `transcript_path`, `cwd` y `source`, sin
  `model`. **[N]** No probé si en interactivo trae `model`.
- **El modelo del subagente** solo se ve en dos sitios. Uno es el `tool_input.model` del
  `PreToolUse` de `Agent` (`'haiku'` en r4), que es un alias y no se ata al `agent_id` hasta el
  `SubagentStart`. El otro es su transcript, `<sesión>/subagents/agent-<agent_id>.jsonl`, que en
  r4 dio `claude-haiku-4-5-20251001` mientras el principal era `claude-sonnet-5`.
- **Leer el transcript desde el hook funciona, con una carrera.** En `PreToolUse`, la línea del
  assistant con ese `tool_use_id` estaba escrita en 5 de 6 casos; en `PostToolUse`, en 6 de 6.
  El fallo fue la primera tool de la sesión r2.
- **Trampa: la variable `CLAUDE_EFFORT` se hereda.** En r2 (`--effort low`) el hook vio
  `CLAUDE_EFFORT=high`, que era el de **mi** sesión, el proceso padre. Quitándola del entorno (r3
  y r4), sí reflejó el esfuerzo de la corrida, pero no estaba en el entorno del subagente Haiku.
  No sirve como fuente. La buena es el campo `effort` de la entrada.
- **Orden de los eventos [V]:** el hook `PreToolUse` termina antes de que el servidor reciba
  `tools/call` (14:33:14,083 frente a 14:33:14,098 en r2). Una nota que deje el hook ya está
  escrita cuando el servidor procesa la llamada.

### (c) El statusline [V]

`~/.claude/cuota-statusline.jsonl` guarda `session_id`, `model`, `effort.level`, los porcentajes de
cuota y `cost_usd`. Tiene 100 líneas, la primera del 2026-10-06 a las 14:05Z. Tiene tres
limitaciones:

- Solo cubre el hilo principal.
- Solo guarda el último estado de la sesión, sin relación con cada llamada.
- Solo existe en sesiones interactivas.

Sirve para calibrar la cuota, no para atribuir delegaciones: el 86 % de las delegaciones reales
(149 de 173) van por subagentes.

## Pregunta 2. A posteriori, para el histórico

**Contenido del transcript [V]** (barrido de solo lectura de 422 transcripts, que devuelve solo
claves y conteos):

- Las 269 líneas del assistant con `tool_use` de `mcp__local-delegate__*` traen
  `message.model`. 251 traen `effort` en el primer nivel y 233 `perTurnEffort` (que muchas veces
  vale `null`). También traen `agentId`, `isSidechain` y `sessionId`.
- `effort` aparece desde la versión 2.1.215. Falta en Haiku, que no lo admite, y en las líneas de
  `claude-opus-4-8` y `claude-fable-5` (sin dato).
- En todos los transcripts, `effort` solo toma los valores `high` (49 216 líneas) y `medium`
  (1 466). `medium` está casi todo en sesiones de banco.
- **Los subagentes tienen transcript propio** (`<sesión>/subagents/agent-<id>.jsonl`), con su
  `message.model` y su `effort`. Su `.meta.json` trae `agentType`, `toolUseId` (el `Agent` que lo
  lanzó) y `spawnDepth`, pero **no** el modelo ni el esfuerzo.
- **Caché por hilo [V]:** los hilos principales escriben **solo** a 1 h (0 tokens a 5 min) y los
  subagentes escriben a 5 min (43,2 M frente a 0,0 M a 1 h en Opus 5.5).

**Cruce del log de uso con el transcript, últimos 30 días** (desde el 2026-09-06; se excluye mi
ventana de prueba):

- Regla de cruce: misma tool, y `ts` del log dentro de [`tool_use` − 1 s, `tool_result` + 2 s].
  Cuando hay varios candidatos, se desempata con `path` igual, comparando en memoria sin
  guardarlo.
- El desfase entre `ts` del log y `tool_result` tiene p50 = 0,5 s, p95 = 1,0 s y máx. = 1,04 s.
- Ninguna delegación casó con más de una línea.

| Origen de la línea | Líneas | Único | Único tras desempatar por `path` | Ambiguo | No aparece |
|---|---|---|---|---|---|
| `claude-code` | 229 | 166 | 55 | 7 | 1 |
| `local-agent-mode-local-delegate (via mcp-remote)` (Claude Desktop) | 3 | 2 | 1 | 0 | 0 |
| `mcp` (scripts de medición del 2026-09-23) | 40 | 0 | 0 | 0 | 40 |
| sin `client` | 1 | 0 | 0 | 0 | 1 |
| **Total** | **273** | **168** | **56** | **7** | **42** |

- **Claude Code:** el 96,5 % casa de forma única, el 3,1 % es ambiguo y el 0,4 % no aparece. El
  desempate por `path` hace falta en 1 de cada 4 líneas, cuando varios subagentes llaman a la vez
  a la misma tool.
- **Al revés:** hay 255 delegaciones en los transcripts de esos 30 días y 31 no tienen línea de
  log. De ellas, 22 son `local_status`, que no escribe en el log **[V]**. Las otras 9 serían fallos
  o cancelaciones **[I]**.
- **Las 3 líneas de Claude Desktop casaron.** Indica que su modo agente deja transcripts de Claude
  Code **[I]**.

**Conservación de los transcripts [V/I]:**

- `cleanupPeriodDays` no está en `~/.claude/settings.json` ni en `~/.claude.json`, así que rige el
  valor por defecto, 30 días **[I, documentado]**.
- Lo observado cuadra: el transcript más viejo tiene 32,8 días de `mtime` y solo 3 de 422 pasan de
  30. La limpieza corre al arrancar.
- Consecuencia: lo que no se agregue antes de 30 días se pierde.

## Pregunta 3. ¿Varía de verdad?

N son las peticiones posteriores en el mismo hilo (principal o subagente) tras el `tool_result`,
hasta el final o el primer `compact_boundary`. Una caducidad es un hueco entre peticiones mayor que
el TTL del hilo (300 s en subagentes, 3600 s en el principal), y supone una reescritura.

La columna «$/MTok» es el coste por millón de tokens ahorrados: `P_w(hilo)·(1+cad) + (N−cad)·P_r`.
Usa los precios de `viabilidad-cuota.md`. Para `claude-opus-5` se **supone** el precio de Opus 5.5
**[N]**: la tabla no lo trae.

| Modelo | Esfuerzo | Hilo | Casos | De bancos | N p25 / mediana / p75 / p90 | Caducidades (media; casos con alguna) | $/MTok p25 / mediana / p75 |
|---|---|---|---|---|---|---|---|
| claude-opus-5-5 | high | subagente | 149 | 0 | 25 / **40** / 86 / 135 | 1,13; 66 | 12,0 / **16,6** / 22,6 |
| claude-opus-5 | high | principal | 24 | 0 | 78 / **117,5** / 291 / 296 | 0,33; 4 | 24,3 / **38,9** / 66,2 (precio supuesto) |
| claude-opus-5-5 | medium | principal | 39 | 39 | 2 / 2 / 2 / 3 | 0 | 8,4 |
| claude-haiku-4-5 | no aplica | subagente | 11 | 11 | 3 / 3 / 3 / 3 | 0 | 1,6 |
| claude-sonnet-5 | high | subagente | **1** | 1 | 2 | 0 | 2,9 |

- **Solo hay dos grupos reales.** Los grupos `medium`, Haiku y Sonnet son íntegros de sesiones de
  banco o medición (carpetas `Temp*`): no dicen nada del uso real. El de Sonnet tiene menos de 10
  casos y el de Haiku apenas 11, todos artificiales, así que no se sacan conclusiones de ellos.
- **El esfuerzo no se puede contrastar [V]:** las 173 delegaciones reales se pidieron con `high`.
- **[I]** El esfuerzo no entra en la fórmula del ahorro: cambia los tokens de salida y razonamiento
  de quien llama, no el precio de los tokens ahorrados que se escriben y releen en caché. Solo
  influiría a través de N (cuántas peticiones más hace el hilo). Eso hay que medirlo cuando haya
  datos con otros esfuerzos.
- **Lo que sí varía [V]:** el hilo y el modelo, que aquí van juntos (el principal es Opus 5 y los
  subagentes Opus 5.5). La mediana de N es ~3× mayor en el hilo principal (117,5 frente a 40). El
  subagente escribe más barato (5 min) pero caduca más: el 44 % de sus casos sufre al menos una
  reescritura. Y dentro de cada grupo la dispersión de N es enorme (p25 = 25, p90 = 135).

**Totales de los 159 casos reales con `path`** (1,33 MTok netos, chars/4, k_tok = 1):

| Escenario | Total | Frente al por evento |
|---|---|---|
| **B. Por evento: modelo, hilo, N y caducidades** | **$38,51** | referencia |
| C. Por evento sin caducidades | $33,99 | −12 % |
| E. Modelo único supuesto (Opus 5.5, 1 h) con N por evento | $36,27 | −6 % |
| F. Modelo e hilo por evento con la mediana de N de su grupo | $28,50 | −26 % |
| A. Modelo único supuesto (Opus 5.5, 1 h) con N mediana global (47) | $23,17 | −40 % |
| D. Modelo e hilo por evento con N mediana global | $20,89 | −46 % |
| **Spec actual, REQ-022/023: Opus 5.5 en subagente (5 min), N = 49,5** | **$19,84** | **−48 %** |
| Cota baja por evento (una escritura) | $8,37 | — |
| Cota baja de la spec (Opus 5.5, 5 min) | $6,66 | — |

Por grupo, con atribución por evento:

- **Opus 5, hilo principal:** 17 casos, 0,57 MTok, **$22,45**.
- **Opus 5.5, subagente:** 142 casos, 0,76 MTok, **$16,06**.

**Conclusión [V]:** el usuario tiene razón en que varía. Lo que más mueve la cifra es **N por
evento**, que depende sobre todo del hilo. Le sigue la atribución de modelo e hilo; el esfuerzo,
de momento, no se puede medir. Una mediana global de N subestima, porque la distribución tiene una
cola larga y los casos con N alto pesan más. Con el supuesto actual de la spec, la estimación sale
a la mitad.

## Pregunta 4. Diseño recomendado

### Qué se guarda en cada línea del log de uso desde ya

| Campo | Valor | Fuente | Cuándo falta |
|---|---|---|---|
| `tool_use_id` | `toolu_…` | `_meta["claudecode/toolUseId"]`, leído en `clients.observar_cliente` y puesto en un `ContextVar` igual que `_CLIENTE_ACTUAL` | El cliente no lo manda (Codex, scripts, quizá `mcp-remote`) |
| `caller_kind` | `main` \| `subagent` | Nota del hook (`agent_id` presente o no) | Sin nota del hook ni transcript |
| `caller_agent_type` | p. ej. `general-purpose` | Nota del hook | Hilo principal |
| `caller_session` | id de sesión (no es contenido) | Nota del hook | Ídem |
| `caller_effort` | `low`…`max`, o `n/a` si el modelo no lo admite | `effort.level` de la nota del hook; respaldo: `effort` del transcript | Sin nota ni transcript (`n/a` no es «falta») |
| `caller_model` | `claude-opus-5-5`… | El servidor, al escribir la línea, lee la cola del transcript **exacto** que indica la nota (el del subagente si hay `agent_id`) y busca el `tool_use_id`. Para entonces la línea ya está escrita (6/6 en `PostToolUse`) | Transcript no accesible o carrera: se deja vacío con `tool_use_id`, y lo completa el comando de relleno |
| `caller_src` | `hook+transcript` \| `transcript` \| `relleno` | — | — |

**La vía, en concreto:**

1. **Hook `PreToolUse` nuevo** (matcher `mcp__local-delegate__.*`, solo stdlib, como los de
   `resources/hooks/`). Escribe una nota corta en `%LOCALAPPDATA%\local-delegate\` con
   `{tool_use_id, ts, session_id, agent_id, agent_type, effort, transcript_path}`.
   - Es el mismo patrón que `anotar_bloqueo` → `_bloqueo_reciente` (`server.py:423`), con su test
     de ida y vuelta, porque el formato vive en dos sitios.
   - No usa la variable `CLAUDE_EFFORT` (se hereda; ver P1 b).
2. **El servidor, en `_log_event`,** busca la nota por `tool_use_id` y resuelve `caller_model`
   desde el transcript que esa nota señala.
   - **Respaldo sin hook [I, factible]:** buscar el `tool_use_id` en la cola de los `.jsonl` de
     `~/.claude/projects` modificados en los últimos minutos. Sirve si el hook no está instalado,
     pero lee transcripts sin saber cuál.
3. **N no se puede saber al escribir la línea,** porque depende del futuro del hilo. Lo calcula el
   comando de relleno cuando el hilo ya terminó.

Es todo best-effort: igual que hoy, observar nunca rompe una tool.

**Por qué no basta solo con el hook ni solo con el transcript:**

- El hook no trae el modelo **[V]**.
- El formato del transcript no está documentado (`effort` y `agentId` son campos internos que
  pueden cambiar). Los campos del hook (`agent_id`, `agent_type`, `effort`) son la interfaz
  pública **[I]**.
- Con las dos fuentes, el cambio de una se detecta como `caller_src` degradado y no como un dato
  falso.

### Qué hace el panel cuando falta el dato

Es un respaldo declarado y visible. El panel muestra una barra de cobertura con cinco tramos:

- atribuido al momento;
- atribuido por relleno;
- pendiente;
- supuesto;
- excluido.

Cada tramo lleva su número. Ninguna cifra en dólares se muestra sin esa barra.

| Caso | Qué hace |
|---|---|
| Línea de Claude Code con `tool_use_id` y sin `caller_model` | «Pendiente de atribuir»: la completa el comando de relleno mientras el transcript exista |
| Líneas viejas, sin `tool_use_id` | Relleno por ventana de tiempo + `path` (96,5 % único medido). Las ambiguas o no encontradas pasan a «supuesto» |
| Supuesto | Por evento sin modelo: la mezcla medida de los últimos 30 días (modelo, hilo, N) del agregado guardado; si no hay agregado, el defecto declarado (hoy REQ-022). Rótulo: «N de M delegaciones con modelo supuesto: …» |
| Codex (`codex-mcp-client`) | Excluido del coste de Anthropic, con su número a la vista: no es un modelo de Claude |
| Claude Desktop (`via mcp-remote`) | No tiene hooks. **[N]** Falta saber si `mcp-remote` reenvía `_meta`. Sus transcripts casaron, así que entra por relleno; si no casa, va a «supuesto» |
| La Mac | Tiene su propio daemon y su propio log: el mecanismo es el mismo cuando se actualice. Hasta entonces, «supuesto» en el panel de la Mac |
| Scripts y bancos (`mcp`, carpetas `Temp*`) | Excluidos como «pruebas», con su número |
| Modelo sin esfuerzo (Haiku) | `n/a`: no cuenta como falta |

### Relleno del histórico de los últimos 30 días

Se extiende el subcomando de REQ-040 (el que ya lee transcripts y guarda un JSON de agregados).
Para cada línea del log de los últimos 30 días hace esto:

1. Si la línea tiene `tool_use_id`, el cruce es exacto. Si no, usa la ventana de tiempo, la tool y
   `path` en memoria, como el script `casar_y_medir.py`.
2. Calcula N y las caducidades en el hilo, que ya ha terminado.
3. Acumula **solo agregados** por (mes, modelo, esfuerzo, hilo): casos, `Σtok`, `Σtok·N`,
   `Σtok·caducidades`, los percentiles de N y los contadores único / desempate / ambiguo / ninguno.

Con esas tres sumas, el total del escenario B sale **exacto**, sin guardar nada por línea:

`C = P_w·(Σtok + Σtok·cad) + P_r·(Σtok·N − Σtok·cad)`

El resultado se guarda por mes. Los transcripts se borran a los 30 días, así que el comando debe
correr al menos una vez cada 30 días (o el daemon, a diario), y un mes ya agregado no se
recalcula.

**Cambios que esto pide en la spec (para quien la redacte):**

- REQ-022 deja de ser el cálculo y pasa a ser el respaldo declarado.
- REQ-023 calcula N por hilo (o por evento cuando lo haya), no como mediana global única.
- La barra de cobertura entra en REQ-024.

## Tabla de afirmaciones

| Afirmación | Evidencia | Estado |
|---|---|---|
| Claude Code manda el `tool_use_id` en `_meta["claudecode/toolUseId"]` de cada `tools/call` | Sonda MCP, r1–r4, también desde subagentes | V |
| Ni cabeceras, ni `clientInfo`, ni `_meta` traen modelo, esfuerzo o sesión | Sonda MCP: cabeceras y parámetros completos | V |
| El SDK 2.2.0 deja leer claves extra de `_meta` en el middleware | `mcp_types/_types.py:80`, `mcp/server/context.py:46` | V en código, no ejecutado |
| El daemon real recibe el mismo `_meta` que la sonda | Mismo cliente y versión; el daemon no se instrumentó | I |
| La entrada del hook trae `agent_id` y `agent_type` en subagentes, y `mcp_server`, `tool_use_id`, `session_id` y `transcript_path` | `salida/hooks.jsonl`, r1–r4 | V |
| La entrada del hook trae `effort.level` si el modelo lo admite; no trae `model` nunca | r3 (low), r4 (high), r2/r4 con Haiku sin `effort` | V |
| `CLAUDE_EFFORT` en el entorno del hook se hereda del proceso padre | r2: `--effort low` y el hook vio `high` | V |
| `SessionStart` no trae `model` | r1–r4 en `-p` | V en `-p`; N en interactivo |
| En `PreToolUse` la línea del transcript ya está escrita casi siempre; en `PostToolUse`, siempre | 5/6 y 6/6 | V |
| `--settings` añade a la configuración y no la reemplaza | Telemetría del hook de usuario con mis cuatro `session_id` | V |
| El transcript trae `message.model`, `effort`, `agentId` e `isSidechain` en la línea del `tool_use` | 269 líneas; 251 con `effort` | V |
| Los subagentes tienen transcript propio con su modelo; el `.meta.json` no trae modelo | Barrido de claves; r4 | V |
| Hilo principal con caché a 1 h y subagentes a 5 min | `usage.cache_creation` agregado por hilo | V |
| El 96,5 % de las líneas de Claude Code casa de forma única (3,1 % ambiguas, 0,4 % sin cruce) | `casar_y_medir.py` | V |
| Los transcripts duran 30 días | Ajuste ausente; `mtime` máx. 32,8 d | V lo observado; I el valor por defecto |
| Todas las delegaciones reales fueron con esfuerzo `high` | Tabla de la P3 | V |
| La atribución por evento duplica la estimación frente al supuesto de la spec | $38,51 frente a $19,84 | V (con precio de Opus 5 supuesto) |
| El precio de `claude-opus-5` es el de Opus 5.5 | Falta en la tabla de precios | N |
| El esfuerzo solo influye a través de N | Razonamiento sobre la fórmula | I |
| Claude Desktop en modo agente deja transcripts de Claude Code | 3 de 3 líneas casadas | I |

## Ventana a excluir de la medición de adopción

- **Hora:** 2026-10-06, de **14:30:59Z a 14:35:00Z**.
- **Sesiones:** `a42898b2-42f1-40d4-a0d7-425371790775`, `2c1d9c21-efa3-44f8-ac05-30a811c1767d`,
  `dbc508fa-ddfd-45f3-ab70-830c790e3fe5` y `4779cac3-bba6-471b-a925-5e42741afc5d`.
- **Lo que tocaron:** dispararon el `UserPromptSubmit` del usuario (4 líneas en `telemetry.jsonl`)
  y ningún hook de Read o Shell. `local_status` no escribe en el log de uso.
- **Otras sesiones en esa franja:** hubo muchas `claude -p` que no son mías; son del agente de
  densidad.

## Ficheros

Scripts, todos de solo lectura, en
`%USERPROFILE%\AppData\Local\Temp\claude\D--Projects-local-delegate\deec22db-aa02-4e22-b9cb-1cd13039de77\scratchpad\atribucion\`:

- `claves.py` y `effort_valores.py`: estructura y valores agregados de los transcripts.
- `edades.py`: conservación de los transcripts.
- `casar_y_medir.py`: cruce, N, caducidades y escenarios de coste. Resultado en
  `salida/agregados.json`.
- `sonda_mcp.py`, `volcar_hook.py`, `ajustes.json` y `mcp-sonda.json`: la prueba en vivo.
  Capturas en `salida/hooks.jsonl` y `salida/sonda_mcp.jsonl`; solo contienen mis prompts de
  prueba.
