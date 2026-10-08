# Research: Las pruebas fuera de las métricas: ventanas de prueba y una sola regla de exclusión en todo el panel

Investigado el 2026-10-08 sobre `main` en `663cd62` (release 0.33.0). Todas las referencias
`fichero:línea` se leyeron en ese commit. Otro agente está cambiando `web/metrics.py` en paralelo:
los números de línea de ese fichero pueden moverse antes de implementar (ver T0 del plan).

## Current behavior

### Qué ensucia las métricas

Las pruebas en vivo contra el MCP o el daemon (pasos 5 y 7 de la ola 11 del SDD
`daemon-reparte-el-backend`, el fallo provocado de P-4, las tandas `claude -p` del banco) escriben en
el **mismo** log de uso (`usage-AAAAMM.jsonl` en `LOG_DIR`) que el trabajo real, y casi siempre con
`client: "claude-code"`, que es indistinguible de una sesión normal. Hoy nada las separa, salvo:

1. **Por cliente**: `atribucion.CLIENTES_EXCLUIDOS = {"codex-mcp-client": "no es Claude", "mcp":
   "pruebas"}` (`src/local_delegate/atribucion.py:40`). El cliente `mcp` es el de los scripts del
   repo.
2. **Por banco**: el relleno marca `banco: true` los transcripts del banco de pruebas
   (`atribucion.py:336-337`).
3. **A mano, en cada script**: `scripts/medir_enfriamiento.py --excluir INICIO,FIN`
   (`:173`), con comparación de **cadenas** `inicio <= ts < fin` (`:53-58`).

Y la regla 1+2 (`atribucion.excluida`, `atribucion.py:327-338`) **solo la usa el coste**:

| Consumidor | Dónde | Qué hace con `excluida` |
|---|---|---|
| Tramo de la barra de cobertura | `coste.py:259-262` (`tramo`) | la fila va al tramo `excluido` |
| Agregados de N | `recalcular.py:120-129` | la fila no entra en la media de N |
| Bloque de coste del panel | `valoracion.py:189-191` | cuenta `excluidas_por_motivo` |
| Texto del ⓘ de coste | `web/metrics.py:1820-1824` | «excluidas (pruebas (scripts y bancos) y clientes que no son Claude)» |

**Todo lo demás del panel cuenta las pruebas**: `_aggregate` (`web/metrics.py:228-463`, alimenta los
KPIs y las tablas de `/api/stats`, incluido el desglose `by_client`, donde `mcp` sale como una fila
más), `/api/events` (`:466-483`, alimenta gráficos por día y la tabla de eventos), `/api/hooks`
(`:622-653`, lee `config.HOOK_TELEMETRY_LOG`) y `local_status` (`server.py:4439-4469`, que cuenta
eventos y ahorro del mes en curso).

### `excluida` mezcla dos cosas distintas

`excluida` devuelve `"no es Claude"` para Codex y `"pruebas"` para el cliente `mcp` y los bancos. Para
el **coste** las dos se excluyen (no se puede valorar a precio de Claude algo que no pidió Claude).
Para el **panel de uso**, no: lo que delega Codex es uso real y tiene que seguir contando. **Aplicar
`excluida` tal cual a todo el panel borraría las delegaciones de Codex.** La regla común tiene que
separar «es una prueba» (fuera de todo) de «no es Claude» (fuera solo del coste).

### El espejo JS no decide qué filas entran

El panel pide `/api/events`, `/api/stats` y `/api/hooks` con **la misma** `qs` (`web/metrics.py:1687-1702`,
`fetchData`). Los KPIs vienen de `/api/stats` y no se recalculan en el navegador (comentario en
`:1693-1695`). `acct` (`:2470-2508`) es la contabilidad de **una** fila, espejo de `server._accounting`
atado por `tests/test_metrics.py:1122` (`test_paridad_acct_entre_python_y_el_js_del_panel`), y
`agg` (`:2617-2621`) agrupa la lista que ya trae `/api/events`. **Ninguna de las dos elige filas**: el
filtro de rango lo aplica el servidor en `_load` (`:166-187`), que comparten `/api/events` y
`/api/stats`.

Consecuencia de diseño: si el filtro de pruebas va en el servidor, **justo después** de `_load` (que
sigue devolviendo todas las filas, porque también la llaman el coste y `_bloque_cuota` en `:520`, que
necesitan las pruebas para contarlas como excluidas), el JS no necesita una segunda copia de
la regla y la paridad de `acct` no cambia. `/api/stats` reparte las filas a cuatro consumidores
(`:486-500`): `_aggregate` y `valoracion.bloque_imagenes` (`:496`, que no aplica `excluida`,
`valoracion.py:284-297`) son uso; `bloque_coste` y `_bloque_cuota` son coste. La estimación previa («tocar `acct` y `agg`») se descarta:
habría creado una tercera copia de la misma decisión. Lo que sí hay que atar es que **las tres
peticiones lleven el mismo parámetro** (hoy lo garantiza que comparten `qs`) y que `/api/events` y
`/api/stats` cuenten el mismo conjunto (`meta.count == total.calls` por debajo de `MAX_EVENTS`).

### Las marcas de tiempo no se pueden comparar como cadenas

- El log de uso escribe `ts` con segundos y `+00:00`: `"2026-10-01T00:02:51+00:00"` (leído de
  `usage-202610.jsonl` de esta PC).
- Las ventanas de la ola 11 tienen milisegundos y `Z`: `2026-10-08T01:20:05.255Z`
  (`.sdd/changes/daemon-reparte-el-backend/verification.md:929-930`).
- La de P-4 no tiene zona: `2026-09-15T19:31:14` (memoria del proyecto, P-4).

En comparación de cadenas, `"…01:20:05+00:00" < "…01:20:05.255Z"` (`+` va antes que `.`): una fila
escrita en el mismo segundo del inicio quedaría **fuera** de la ventana. Y el `ts` del log está
truncado al segundo, así que una llamada que terminó a las `01:20:05.8` se escribe `01:20:05`. La
regla tiene que parsear a `datetime` UTC y comparar a **segundo entero** (inicio truncado, fin
redondeado hacia arriba, intervalo cerrado). `web/metrics.py:132` (`_parse_ts`) y `coste.py:249-256`
(`_instante`) ya parsean con `fromisoformat` y asumen UTC si falta zona.

### Defecto encontrado: `medir_enfriamiento.py` no arranca

`scripts/medir_enfriamiento.py:179` llama `medir(args.desde, args.hasta, args.exclude, args.tmax)`,
pero el argumento se declara como `--excluir` (`:172-174`), cuyo `dest` es `excluir`. Ejecutado:

```
PYTHONPATH=src .venv/Scripts/python.exe scripts/medir_enfriamiento.py --desde 2030-01-01
AttributeError: 'Namespace' object has no attribute 'exclude'. Did you mean: 'excluir'?
```

Falla **siempre**, con o sin `--excluir`. Lo introdujo `75e1f6d` (#240, `git log -S "args.exclude"`).
Los 20 tests de `tests/test_medir_enfriamiento.py` no llaman a `main()`, por eso la suite está en
verde. Importa: P-4 se mide a los 14, 30 y 90 días desde el 2026-09-15, y la de 30 días cae el
2026-10-15. Este cambio lo arregla de paso (REQ-016) con un test que sí pasa por `main()`.

### Ventanas que ya se conocen

| Origen | Inicio (UTC) | Fin (UTC) | Fuente |
|---|---|---|---|
| Ola 11, paso 5 | `2026-10-08T01:20:05.255Z` | `2026-10-08T01:22:31.544Z` | `daemon-reparte-el-backend/verification.md:929` |
| Ola 11, paso 7 | `2026-10-08T01:24:10.521Z` | `2026-10-08T01:24:39.452Z` | `daemon-reparte-el-backend/verification.md:930` |
| P-4, fallo provocado | `2026-09-15T19:31:14` | `2026-09-15T19:35:14` | memoria del proyecto: `--excluir 2026-09-15T19:31:14,2026-09-15T19:35:14` |

Ojo con la de P-4: es **una** ventana (`INICIO,FIN`, la sintaxis de `--excluir`), no dos instantes.

Hay además un registro anterior y de otro propósito: `benchmarks/ventanas-excluidas.json` (en el
repo), con 5 «ventanas» de tandas (`control-t4` y `experimento-adopcion`, 2026-09-23) y 49
«sesiones» `claude -p` (2026-09-22 y siguientes). Lo escriben `scripts/sesiones_de_prueba.py:26` y
`scripts/_banco_claude.py:243` (`anotar_ventana`), lo cita `scripts/experimento_adopcion.py:53`, y
**ningún medidor lo lee** (búsqueda de `ventanas-excluidas` en `scripts/`, `src/` y `tests/`: solo los
dos escritores). Si se importa o no es una decisión abierta (D5 de la spec).

### Lo que no se toca

- `_last_event` (`web/metrics.py:190-213`) y `/api/inflight`: el indicador EN CURSO / EN VIVO enseña
  actividad, y una prueba en curso **es** actividad.
- `pace.py` (`seed_files`, `:237-270`): la velocidad normal de cada modelo se siembra del log de uso.
  Una prueba en vivo mide el mismo backend a la misma velocidad; el riesgo de que la ensucie es bajo y
  queda fuera (non-goal).
- `/api/backend/stats` (`web/metrics.py:743`): son contadores de llama-swap, no filas del log.

## Impact map

| Fichero | Líneas | Cambio |
|---|---|---|
| `src/local_delegate/test_windows.py` | nuevo | Lectura con caché, escritura atómica con `FileLock`, `contains(ts)`, `start`/`stop`/`add`/`list`. Nombres en inglés |
| `src/local_delegate/atribucion.py` | `:40`, `:327-338` | Regla común: `test_reason(fila, entrada)` («es una prueba»: cliente `mcp`, banco o ventana); `excluida` pasa a ser `CLIENTES_NO_CLAUDE` + `test_reason` |
| `src/local_delegate/coste.py` | `:212-229` (`fundir`), `:259-262` | `fundir` estampa `test_window` en la fila si su `ts` cae en una ventana; `tramo` sin cambios de lógica (usa `excluida`) |
| `src/local_delegate/recalcular.py` | `:129` | sin cambios de código si `fundir` estampa; test nuevo |
| `src/local_delegate/valoracion.py` | `:191` | idem |
| `src/local_delegate/checks.py` | `:1652`, `:1728-1764` (`CHECKS`) | check nuevo `metrics.test_windows` |
| `src/local_delegate/web/metrics.py` | `_load` `:166-187`, `events` `:466`, `stats` `:486`, `hooks` `:622`, `fetchData` `:1687-1702`, controles `:1368-1385`, texto `:1824` | filtro justo después de `_load` (`_split_tests`), parámetro `include_tests`, `meta.excluded_tests`, interruptor en la barra con ⓘ |
| `src/local_delegate/server.py` | `local_status` `:4439-4469` | contar sin pruebas, decir cuántas fuera y si hay ventana abierta |
| `src/local_delegate/cli.py` | `:1103` (subparsers), patrón de `_add_llamaswap_parser` `:1015` | subcomando `test-window` |
| `scripts/medir_enfriamiento.py` | `:53-58`, `:110-158`, `:172-179` | leer ventanas de `LOG_DIR`, arreglar `args.exclude`, `--include-tests` |
| `scripts/medir_adopcion.py` | `:35-40`, `:47-66` | `directorio_de_logs()` pasa a `config.LOG_DIR`; aplicar ventanas a telemetría de hooks y log de uso; `--include-tests` |
| `scripts/dev/capture_dashboard.py` | `:270`, `:306` | el mock de `/api/events` y `/api/stats` acepta `include_tests` y trae `meta.excluded_tests` |
| `tests/` | `test_metrics.py:1122`, `test_dashboard_js.py`, `test_atribucion.py:605`, `test_medir_enfriamiento.py`, `test_medir_adopcion.py`, `test_checks.py`/`test_doctor.py`, `test_dashboard_ui.py` | tests nuevos y ajustados; `tests/test_test_windows.py` nuevo |
| Docs | `CHANGELOG.md`, `README.md`, `docs/wiki/Savings-and-metrics.md`, `docs/wiki/Integration-install.md` (tabla del doctor y número de comprobaciones, guardados por `tests/test_wiki.py:28-243`) | release toca los tres sitios |

## Existing conventions

- **Código en inglés, textos visibles en español** (memoria `cli-nombres-en-ingles.md`, regla del
  2026-10-07). Lo viejo en español (`excluida`, `recalcular-coste`) no se renombra en este cambio.
- **El panel es un dashboard** (memoria `panel-es-un-dashboard.md`): controles sin prosa, la
  explicación va al diálogo `infoDlg` que abre cada ⓘ (`web/metrics.py:1534`; las secciones se eligen por `data-group`, `:2761`); verificación con
  capturas en claro y oscuro.
- **Escritura atómica** con `tempfile.mkstemp` + `os.replace` (`atribucion.py:302-321`) y bloqueo con
  `filelock` (ya dependencia: `daemon.py:20`, `enfriamiento.py:32`, `server.py:33`): no hace falta
  dependencia nueva.
- **Variables de entorno** con los helpers `_env*` (`config.py:39-58`) y guardianes en
  `tests/test_aislamiento_entorno.py`. Este cambio **no** añade variables: el fichero vive en
  `config.LOG_DIR`.
- **Lo que corre el usuario va al CLI** (`local-delegate test-window`); lo que corre el repo, a
  `scripts/` (los medidores). El wheel no empaqueta `scripts/`, así que la regla vive en el paquete y
  los scripts la importan (ya lo hacen: `medir_enfriamiento.py:32` importa `local_delegate.enfriamiento`).
- **Doctor**: cada check nuevo entra en `checks.CHECKS` y en la tabla de la wiki; dos tests comparan
  la tabla con `checks.CHECKS` (regla «una release toca tres sitios»).
- **Paridad Python/JS**: todo dato con dos implementaciones lleva un test que corre el JS con node
  (`tests/test_metrics.py:1265`, `_acct_en_js`).
- **Comandos pesados de uno en uno** con `bash ~/.claude/scripts/pesado.sh`.

## Dependencies and integrations

- `filelock` (ya en el proyecto).
- El daemon y el panel corren en el mismo proceso que lee `config.LOG_DIR`; el CLI escribe en el mismo
  directorio. El panel nunca abre `~/.claude` (REQ-073 de `coste-api-y-cuota`): el fichero nuevo en
  `LOG_DIR` respeta eso.
- **La Mac** (memoria `topologia-mac-contra-la-pc.md`): delega contra el **backend** de la PC con su
  propio daemon y su propio `LOG_DIR`. Sus llamadas se registran en el log de la Mac, no en el de la
  PC. Una prueba lanzada desde la Mac ensucia el panel de la Mac, no el de la PC.

## Risks and unknowns

- **Ventana abierta olvidada**: un `start` sin `stop` excluiría todo lo posterior en silencio. Mitigación:
  `doctor` avisa si una ventana lleva abierta más de 12 h, y `local_status` la nombra.
- **Agentes en paralelo** marcando a la vez: varias ventanas abiertas a la vez, cada una con su id;
  escritura bajo `FileLock`.
- **Excluir trabajo real solapado**: una ventana excluye **todo** lo que cae dentro, también lo que
  hiciera el usuario a la vez. Es el precio de filtrar por tiempo; las ventanas deben ser cortas.
- **Las cifras bajan** a propósito al desplegar (decisión del usuario). El CHANGELOG lo dice.
- **Conflicto con el otro agente** que cambia `web/metrics.py`: T0 del plan rebasa antes de tocarlo.
- **El fichero lo escribe una persona a mano** a veces: entradas ilegibles se ignoran una a una, con
  aviso en `doctor`; un fichero ilegible entero no excluye nada y lo dice.

## Llamadas `local_*`

**0.** Al empezar, `ToolSearch` devolvió `local-delegate (ECONNREFUSED)`. Tras el aviso del
orquestador de que el MCP estaba reconectado, se repitió dos veces (`select:` con los tres nombres y
búsqueda por palabras): esta sesión de agente siguió sin ver las tools `local_*`. `web/metrics.py`
(~160 000 caracteres) no se leyó entero: `grep` para localizar funciones y lectura solo de los rangos
citados.
