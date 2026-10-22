# R4 — Diseño de las 4 piezas del mod y línea base de medición

Fecha: 2026-10-21. Motor probado: Claude Code **2.1.306** (CLI); tipos de la skill `plugin-authoring`
de la **2.1.305**. Marcas: **[PRUEBA]** comprobado en vivo aquí; **[DOC]** tipos `claude-code.d.ts`
o doc oficial `code.claude.com/docs/en/plugins/mods/*`; **[3º]** inferencia mía sin verificar.

Mod desechable de las pruebas: `C:/Users/Yohan/AppData/Local/Temp/claude/D--Projects-local-delegate/ed2ae533-e76e-4dce-ae5d-1dd44f83b27e/scratchpad/r4/ld-r4/`
(salidas en `…/r4/out/`). Ventana de prueba `w-20261021T201550Z` (20:15:50Z–20:18:16Z), cerrada.

## Hallazgos que cambian el diseño (leer primero)

1. **[PRUEBA] En la 2.1.306 en modo `-p`, `Edit` NO exige un `Read` previo.** Control negativo sin
   mod, sin `acceptEdits` y con `--allowedTools Edit`: el modelo editó `none.txt` sin leerlo y salió
   bien (corrida 3). También con el mod (corrida 2) y vía `$.tool.call` (corrida 1). Así que la
   pregunta «¿responder un `Read` sin `next` cuenta como lectura para `Edit`?» **no se pudo
   discriminar**: las 5 variantes editaron, el control negativo incluido. Queda sin verificar si en
   sesión interactiva la regla existe (mismo motor, **[3º]** probablemente igual). Si hiciera falta,
   la variante segura es la C (abajo), que pasa por el núcleo y deja la lectura real registrada.
2. **[PRUEBA] El resumen sustituye de verdad lo que lee el modelo.** En el transcript de la corrida 2,
   el `tool_result` de `fake.txt` (respuesta sin `next`) y de `fake3.txt` (`next` y luego cambiar
   `result.file.content`) es `1\tSUMMARY FROM LOCAL MODEL (fake)`, y `toolUseResult.file.content`
   guarda el resumen. Riesgo **[3º]**: al reanudar (`--resume`), el estado de ficheros que el motor
   reconstruye desde el transcript creerá que el contenido del fichero es el resumen.
3. **[DOC] Orden con los hooks de settings** (`events.md` §«Where settings hooks run»): los
   `PreToolUse` de settings de usuario y de `hooks/hooks.json` de plugins **corren después del último
   `next` de los mods**, como parte del núcleo. Un mod que responde `Read` **sin** `next` impide que
   corra el hook actual de bloqueo (`suggest_delegate_read.py`); uno que llama a `next` recibe su
   `deny` como resultado. Los `PreToolUse` de settings *gestionados* van antes de todos los mods.
4. **[PRUEBA] Comandos sin turno del modelo cuestan 0**: `claude -p "/r4probe"` con el mod hizo
   `$.mcp.call`, `$.process.run`, `$.http.fetch`, `$.session.usage({breakdown:'full'})` y cinco
   `$.tool.call`, con `num_turns: 0` y `total_cost_usd: 0`.
5. **[DOC] Un nombre de comando registrado no admite `:`** (`CommandSpec.name`: letras, dígitos, `_`,
   `-`, hasta 64). `/local:resumir` no se puede registrar con `$.command.register`; **[PRUEBA]**
   `$.command.list()` muestra el registrado tal cual (`r4probe`, `source: plugin`), sin prefijo del
   plugin. Propuesta: `/local-resumir`, `/local-commit`, `/local-lint` (o `/ld-…`).

## A. Las cuatro piezas

### 1. Tools `local_*` siempre cargadas

- **Evento** [DOC]: `tool.describe` (se dispara al renderizar el esquema; una tool MCP diferida lo
  dispara dos veces). Devolver `{ ...(await next(e)), isDeferred: false }` la saca de ToolSearch.
  Cacheado hasta `$.ui.invalidate('tool.describe')`; un cambio **reescribe toda la caché del prompt**.
- **[PRUEBA]** las 11 `mcp__local-delegate__*` llegaron con `isDeferred: true` y el mod las fijó. Con
  las 11 fijadas, `$.session.usage({breakdown:'full'})` dio **«MCP tools» = 5 319 tokens** no diferidos
  (el resto de MCP, 185 378, siguió diferido). ≈ 480 tokens por tool; descripciones de 208
  (`local_classify`) a 1 107 caracteres (`local_extract`). Un subconjunto de 4 (summarize, extract,
  lint_summary, commit_msg) rondaría **~2 000 tokens** [3º, por proporción].
- **Configurable** [DOC]: `userConfig` en `plugin.json` llega como `options` a `register(on, options)`;
  con `--plugin-dir` se lee de `pluginConfigs["<name>@inline"]`; cada campo no secreto sale como fila
  en `/config` y cambiarlo recarga el módulo. Un `string` con `options` es un selector.
- **Riesgos**: coste fijo por turno (en caché, pero cada cambio de la lista invalida la caché); el
  matcher por nombre depende de que el servidor se llame `local-delegate` (en plugin, el MCP del
  manifiesto podría llamarse distinto: casar por sufijo `__local_`).
- Boceto:
  ```ts
  const PINNED = new Set((options.pinned ?? 'summarize,extract,lint_summary,commit_msg').split(','))
  on('tool.describe', async ($, e, next) => {
    const r = await next(e)
    const m = /__local_(\w+)$/.exec(e.tool)
    return m && PINNED.has(m[1]) ? { ...r, isDeferred: false } : r
  })
  ```

### 2. Comandos `/local-resumir <ruta>`, `/local-commit`, `/local-lint <comando|fichero>`

- **APIs** [DOC]: `$.command.register({ name, description, argumentHint })` en `session.start`;
  servir con `on('command.run', { command }, …)` devolviendo `{ text, context? }` **sin `next`**.
  `text` sale en el transcript como salida del comando; **`context`** son mensajes ocultos que el
  modelo lee después (así el resultado queda como contexto). `exitCode` vale para `claude -p "/cmd"`.
  `immediate: true` permite lanzarlo con un turno en curso.
- **`$.mcp.call` vs `$.tool.call`** [DOC]: `$.mcp.call(server, tool, args)` usa la conexión del
  motor, **sin diálogo de permiso** («la llamada del plugin es el permiso»), devuelve `{content,
  isError}` crudo de MCP y la ven los hooks de mods por encima. `$.tool.call({tool:'mcp__…', …})`
  pasa por **todos los hooks menos el que llama, la comprobación de permisos con su diálogo y la
  tool**, con `tool_use_id` propio; devuelve `ToolCallResult` (`text`, `result`). La memoria del
  proyecto apunta que en sesión real `$.mcp.call` sí dispara hooks y en `claude plugin test` no.
  **Recomendación**: `$.mcp.call` (sin prompt, salida cruda, sin pasar por el bloqueo de lectura).
  **[PRUEBA]** `$.mcp.call('local-delegate','local_status',{})` → 1 942 caracteres, `isError:false`.
- **`$.process.run`** [DOC]: «Commands on the host… **CLI only**»; sin shell, 30 s por defecto, 10 min
  máx., 4 MiB por flujo. **[PRUEBA]** `local-delegate --version` → `0.39.0`. En Desktop (pestaña
  Code, sesión local con `entrypoint: claude-desktop`) y en la extensión de VS Code el motor es el
  mismo CLI en la máquina, así que **[3º]** debería funcionar; donde no hay host (nube, móvil) no.
  Para `/local-lint <comando>` hace falta (ejecutar el comando, volcar a fichero con `$.fs.write`,
  luego `$.mcp.call('local_lint_summary', {path})`); para `/local-commit`, `git diff --cached`.
  Política: un admin puede vetar mods que llaman a `process.run` (`admin.md`).
- **Cómo se ve** [DOC]: la salida bajo el nombre del plugin como fila del transcript; en `-p`
  llega como resultado. **[PRUEBA]** `{ text, context }` aceptado en `-p` sin turno.
- Boceto:
  ```ts
  on('command.run', { command: 'local-resumir' }, async ($, e) => {
    const path = e.args.trim(); if (!path) return { text: t('usage.resumir') }
    const r = await $.mcp.call('local-delegate', 'local_summarize', { path })
    const s = textOf(r)
    return { text: s, context: [`Resumen local de ${path}:\n${s}`] }
  })
  on('command.run', { command: 'local-commit' }, async ($) => {
    const d = await $.process.run(['git', 'diff', '--cached'])
    const f = await tmpFile($, d.stdout)           // $.fs.write en el dir de logs/temp
    const r = await $.mcp.call('local-delegate', 'local_commit_msg', { path: f })
    return { text: textOf(r), context: ['Borrador de commit (revísalo): ' + textOf(r)] }
  })
  ```

### 3. Cuota y ahorro en la barra de estado o una banda

- **Eventos/APIs** [DOC]: `session.measure` (tras cada turno del hilo principal y cuando una ventana
  de cuota se mueve un punto entero; trae `context`, `rateLimits[]` con `percentUsed`, `cost?`,
  `changed`); `$.session.usage()` gratis sin `breakdown`; `$.ui.status(text)` (una línea por mod,
  empieza por `⚠ <mod>:`, se corta a 200 caracteres/2 filas; en VS Code se ve sobre la caja del
  prompt); banda con `ui.render` en `{component:'AbovePrompt'}` (**Terminal y Desktop**, no VS Code).
  `$.clock.every` para refrescar sin turno.
- **Panel** [PRUEBA]: `$.http.fetch('http://127.0.0.1:9393/api/stats', {headers:{Authorization:
  'Bearer '+token}})` → 200. Claves: `total`, `tokens_context_saved`, `tokens_returned`,
  `tokens_context_net`, `by_tool`, `by_client`, `excluded_tests`, `open_test_windows`, `cost`,
  `quota`, … Acepta `from`, `to`, `include_tests`, `lang` (`web/metrics.py:544`). Otros endpoints:
  `/api/events`, `/api/hooks`, `/api/inflight`, `/api/backend`, `/api/backend/stats`, `/api/status`,
  `/api/system`, `/api/daemon` (daemon), `/api/llamaswap/*`. **Todo** el daemon va detrás del token
  (`auth.protect` envuelve la raíz, `daemon.py:220`).
- **Token** [PRUEBA]: `$.env.get('LOCAL_DELEGATE_WEB_TOKEN')` lo encontró (`hasToken: true`); el
  nombre debe ser literal y `claude plugin validate` lo lista en «env reads». Nunca se escribe.
- **[PRUEBA] En `-p` `rateLimits` vino vacío y `cost.usd = 0`** (sin respuesta del modelo todavía):
  la cuota real solo aparece tras la primera respuesta, en sesión con suscripción.
- Riesgo: `/api/stats` sin `from`/`to` no cubre el histórico (memoria del proyecto); pedir la ventana
  de la sesión (`from = startedAt`). No poner `Authorization` vía `auth` de `HttpInit` (lo veta
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`); la cabecera normal no.
- Boceto:
  ```ts
  on('session.measure', async ($, e, next) => {
    const q = e.rateLimits.find(w => w.kind === 'five_hour')?.percentUsed
    const s = await stats($, (await $.session.usage()).startedAt)   // fetch + Bearer
    $.ui.status(`5h ${q ?? '–'}% · ahorro ${fmt(s.tokens_context_saved)} tok`)
    return next(e)
  })
  ```

### 4. Lectura delegada transparente

- **Evento** [DOC]: `tool.call` con matcher `{ tool: 'Read' }`. Tres variantes probadas [PRUEBA]:
  - **A — responder sin `next`** con `{ result: { type:'text', file:{ filePath, content: resumen,
    numLines, startLine:1, totalLines } } }`: el núcleo lo valida contra el esquema de salida, lo
    mapea con el mapper de `Read` (`1\t…`) y lo graba como resultado. No corre ningún `PreToolUse`
    de settings (ni el bloqueo actual). No hay lectura real en el estado del motor.
  - **B — reescribir** a `next({...e, offset, limit})` + `context: [resumen]`: el modelo ve la franja
    real y el resumen como recordatorio; el bloqueo actual no actúa (lectura acotada).
  - **C — `next(e)` y sustituir `result.file.content`**: la lectura real pasa por el núcleo (permisos,
    `PreToolUse`, estado de ficheros) y el modelo solo ve el resumen. Si el bloqueo de lectura está
    encendido, `next` devuelve su `deny` y el mod debe decidir (ver convivencia).
  - Ninguna rompió un `Edit` posterior, pero el control negativo tampoco falló (hallazgo 1).
- **Elección del usuario (botones)** [DOC]: `$.ui.ask(pregunta, ['Resumir con el modelo local',
  'Leer entero'])` usa el diálogo AskUserQuestion, **rechaza en `-p`** y al cerrarlo (→ caer al
  comportamiento por defecto). Alternativa al estilo `blast-radius` (mod de muestra en
  `anthropics/claude-code-playground/claude-code/mods/blast-radius`, «retiene un comando y muestra
  botones de seguir/cancelar»): dibujar `Button`s en la fila de la tool con `ui.render`
  (`requestId` = `tool_use_id`) y esperar la pulsación con un `atom`. No leí su código [3º sobre el
  mecanismo exacto]. Ojo: esperar al usuario **cuesta** (la obediencia no viene de la prosa: preguntar
  en cada lectura grande se volverá ruido); mejor por defecto resumir prosa ≥ umbral y ofrecer «leer
  entero» como botón posterior o reintento con `offset/limit`.
- **Umbral**: reutilizar el de hoy (`LD_HOOK_READ_SUGGEST_KB` 8 KB / `LD_HOOK_READ_STRONG_KB` 100 KB;
  solo prosa `.md/.txt/.markdown/.rst` se bloquea; datos y código solo avisan; lecturas con
  `offset`/`limit` nunca). `$.fs.stat` da el tamaño sin leer. Excluir imágenes/PDF/notebooks.
- **Convivencia con el bloqueo actual** (`PreToolUse` sobre Read, `LD_HOOK_READ_BLOCK`): son dos
  caminos para lo mismo. Con A el hook nunca corre (el mod lo sustituye en silencio); con C el hook
  bloquea antes que el mod pueda resumir. Propuesta: cuando el plugin esté activo, `install` **no**
  escribe el `PreToolUse` de lectura en settings y el mod asume su lógica (mismo umbral, mismo
  interruptor `~/.claude/local-delegate-bloqueo-apagado`, misma telemetría a `blocks.jsonl`); `doctor`
  avisa si están los dos.
- **Riesgos**: (1) resumen equivocado = el modelo trabaja sobre datos falsos sin saberlo → el
  resultado debe decir que es un resumen y cómo pedir el texto (`offset/limit`); (2) `--resume` con
  el resumen como «contenido» del fichero (hallazgo 2); (3) latencia del backend local en cada Read
  grande; (4) un hook que falla sin `.catch` deja pasar la lectura (falla abierto: aquí es lo bueno);
  (5) en subagentes también dispara (`e.agentId`).
- Boceto (variante recomendada: C con salida de escape):
  ```ts
  on('tool.call', { tool: 'Read' }, async ($, e, next) => {
    if (e.offset || e.limit || !isProse(e.file_path)) return next(e)
    const { size } = await $.fs.stat(e.file_path)
    if (size < options.thresholdKb * 1024 || await switchOff($)) return next(e)
    const r = await $.mcp.call('local-delegate', 'local_summarize', { path: e.file_path, focus: '' })
    if (r.isError) return next(e)                          // backend caído: lectura normal
    const s = textOf(r)
    return { result: { type: 'text', file: { filePath: e.file_path, content:
      `[Resumen local de ${size} B; para el texto literal usa Read con offset/limit]\n${s}`,
      numLines: s.split('\n').length, startLine: 1, totalLines: 0 } } }
  })
  ```
  (A en vez de C evita leer el fichero dos veces y evita el choque con el hook viejo; C solo si la
  regla de «leer antes de editar» resulta existir en interactivo.)

## B. Línea base de medición (últimos 28 días, pruebas excluidas)

Script: `C:/Users/Yohan/AppData/Local/Temp/claude/D--Projects-local-delegate/ed2ae533-e76e-4dce-ae5d-1dd44f83b27e/scratchpad/r4/baseline_sessions.py`
(ejecutar con `.venv/Scripts/python.exe … --days 28`). Usa las reglas del repo:
`attribution.test_reason` (cliente `mcp`, `bench` del relleno `attribution-AAAAMM.json` por clave
`file_keys`) + `test_windows.load().find(ts)`. Cuenta sesiones buscando cada `tool_use_id` de las
filas `client = claude-code` en `~/.claude/projects/**/*.jsonl` (los de subagente se asignan a su
sesión padre). Solo imprime cifras; no saca contenido de los transcripts.

Ventana 2026-09-23T20:11Z → 2026-10-21T20:11Z:

| Cifra | Valor |
| --- | --- |
| Filas excluidas como prueba | 2 130 (`tests`) + 144 (ventana de prueba) |
| Filas que cuentan | 570 `claude-code` + 4 sin cliente |
| …con `tool_use_id` (decididas por el modelo, atribuibles) | 406, las 406 encontradas en transcripts |
| …sin `tool_use_id` (sin atribuir) | 164, todas del 30-sep al 8-oct |
| **Sesiones de Claude Code con ≥1 delegación** | **25** (todas `entrypoint: cli`) — cota baja |
| Sesiones de Claude Code con actividad en la ventana (denominador) | 167: 87 `cli`, 24 `claude-desktop`, 54 `sdk-cli`, 2 `?` |
| **Sesiones de Codex con ≥1 delegación** | **0** (ninguna fila con `client = codex-mcp-client` en todo el log) |
| Sesiones de Codex en la ventana | 1 fichero en `~/.codex/sessions` |

Lectura: **25 de 111 sesiones interactivas (cli + desktop) ≈ 23 %**, o 25/167 ≈ 15 % contando las
`sdk-cli` (casi todas `claude -p` de bancos y pruebas). Cautelas: el denominador es «transcript con
`mtime` en la ventana» (incluye sesiones viejas tocadas y no descuenta subagentes porque solo cuenta
ficheros de primer nivel); `cleanupPeriodDays` (30 por defecto) borra transcripts más viejos; las 164
filas sin id pueden añadir sesiones (máx. una por día con filas: +6 si fueran sesiones nuevas cada
día, sin garantía). Ninguna sesión de Desktop delegó con atribución: o no delega o su hook no deja
nota (**[3º]**, a mirar). Codex en esta PC apenas se usa; su línea base real está en la Mac.

## Pendientes / qué falta verificar

- La regla «leer antes de editar» en sesión **interactiva** (aquí no existe en `-p`).
- `$.process.run` y la banda en Desktop/VS Code en vivo.
- Si `context` de la variante B llega al modelo como recordatorio (no lo comprobé en el transcript).
- Código de `blast-radius` para copiar el patrón de botones.
