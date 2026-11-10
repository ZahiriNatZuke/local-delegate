# Research: Log de uso con proyecto (hash y tipo) y mediciones que apartan el propio repo

Fase `researching`, 2026-11-10 (hora de Uruguay). Solo lectura del código en `main` (`da78ce70`,
paquete 0.50.0). Las cifras «de la muestra» son recuentos de presencia de campos en los dos últimos
ficheros mensuales del log real de esta máquina (3487 filas): solo conteos, sin contenido ni rutas.

## Current behavior

### Quién escribe una fila del log de uso

Hay **un solo punto de escritura**: `server._log_event` (`src/local_delegate/server.py:1312`), que
arma el dict y lo añade con `_append_log_line` (`server.py:1595`) al fichero de
`_current_log_path()` (`server.py:967`: `usage-AAAAMM.jsonl` rotado por mes UTC, o el fichero fijo
de `LOCAL_DELEGATE_LOG`). Lo llaman cuatro sitios (contado con Grep: 1 definición + 4 llamadas):

| Llamada | Función | Qué registra |
| --- | --- | --- |
| `server.py:2176` | `_log_stopped` | delegación cancelada o abortada |
| `server.py:4394` | `_chat` | una llamada al backend |
| `server.py:5135` | `_chat_chunked` | operación troceada |
| `server.py:5951` | `_chat_map_reduce` | map/reduce |

No hay un segundo escritor: el daemon (HTTP) y el proceso stdio importan el mismo `server`; el mod
del plugin no escribe en el log, **pide** la tool con `$.mcp.call` (`mod/read.js:841`,
`mod/commands.js:183`) y la fila la escribe el servidor; el hook `record_call.py` tampoco escribe en
el log, deja una nota. `benchmark.py` y los scripts entran por la misma función (cliente `mcp` o sin
cliente).

### Cómo llega hoy `transcript_path`

1. Claude Code lanza el hook `PreToolUse` con matcher `mcp__local-delegate__.*`
   (`resources/claude-plugin/local-delegate/hooks/hooks.json:41-57`; la entrega por `settings.json`
   registra lo mismo desde `install.py`).
2. `record_call.py` → `hook_common.record_call` (`resources/hooks/hook_common.py:1307-1339`) escribe
   **una nota por `tool_use_id`** en el temporal del usuario (`call_notes_dir`, `hook_common.py:1254`)
   con `tool_use_id`, `ts`, `agent_id`, `agent_type`, `effort`, `transcript_path` y `session_key`.
   Caduca a los 10 minutos (`NOTE_TTL_S`, `hook_common.py:1247`). La entrada del hook trae también
   `cwd` (lo usan `read_classifier.py:663` y `suggest_delegate_shell.py:100`), pero la nota **no** lo
   guarda.
3. El middleware saca el `tool_use_id` de `_meta["claudecode/toolUseId"]` (`clients.py:105`,
   `clients.py:186-194`).
4. `_log_event` hace `rec.update(attribution.current_call())` (`server.py:1417-1428`):
   `attribution.resolve_call` (`attribution.py:195-239`) lee la nota, valida que el transcript cuelga
   de `~/.claude/projects` y acaba en `.jsonl` (`_safe_path`, `attribution.py:96-108`), y devuelve
   `caller_kind`, `caller_src`, `caller_agent_type`, `caller_effort`, `caller_session_key` y
   `caller_model`. **Todo lo que devuelva `resolve_call` acaba en la fila sin tocar `server.py`.**
5. La nota de un subagente trae el `transcript_path` del **principal**; el suyo se deduce como
   `<sesión>/subagents/agent-<agent_id>.jsonl` (`attribution.py:111-128`). Por eso el directorio de
   proyecto que se saca de la nota es siempre el de la sesión principal, también para un subagente
   aislado en un worktree (comprobado en la muestra: los transcripts de subagentes llevan su propio
   `cwd`, que en un worktree difiere del principal, pero viven bajo el directorio del principal).

El directorio de proyecto es `Path(transcript_path).parent.name`: el `cwd` de la sesión con cada
carácter no alfanumérico cambiado por `-` (comprobado contra el campo `cwd` del transcript; es una
transformación con pérdida, no se puede invertir).

### Esquema actual de la fila

Siempre: `ts`, `tool`, `model`, `source`, `chars_in`, `chars_out`, `latency_ms`, `ok`, `backend`,
`backend_host`, `v` (`server.py:1376-1393`). Casi siempre: `host` (`concurrency.origin_fields`,
`concurrency.py:424`), `client`, `finish_reason`, `tokens_in/out`, y los de lentitud. Con
`tool_use_id`: `tool_use_id` + los `caller_*`. Con `source: "path"`: **`path` en claro**
(`server.py:1502-1503`) y `block_id`. El resto son opcionales y se omiten cuando no aplican
(`chunks`, `pieces`, `steps`, `concurrency`, `routing`, `error*`, `turn*`, …). No hay hoy ningún
campo de proyecto.

En la muestra: `path` está en 3320 de 3487 filas; `tool_use_id` en 1175; `caller_kind` en 1169;
`caller_session_key` en 528 (es más reciente); quedan claves viejas en filas viejas (`secciones`,
`bloqueo_id`), que `legacy_names.normalize("usage", …)` traduce al leer.

### En qué caminos NO llega `transcript_path`

| Camino | `client` | `tool_use_id` | Nota del hook | Qué queda hoy en la fila |
| --- | --- | --- | --- | --- |
| Claude Code, modelo (hilo principal o subagente) | `claude-code` | sí | sí (1003 de 1009 en la muestra) | `caller_*` completos |
| Claude Code, mod del plugin | `claude-code` | sí (`toolu_plugin_…`) | **sí** (166 de 166) | `caller_kind: main`, `caller_src: hook`, sin modelo |
| Claude Code sin hooks instalados o nota perdida | `claude-code` | sí | no | solo `tool_use_id`; el relleno lo puede casar después |
| Claude Code anterior al 2026-10-08 | `claude-code` | no | no | nada (137 filas; 4 más de una 0.32.0) |
| Codex | `codex-mcp-client` | no | no (sin hooks) | nada |
| opencode u otro cliente MCP | su nombre | no | no | nada (no hay ninguna mención a opencode en `src/`) |
| Claude Desktop / claude.ai (chat) | `claude-ai` | no | no | nada (11 filas) |
| Scripts, benchmark, sondas | `mcp`, `probe`, sin cliente | no | no | nada (2126 filas `mcp`: ya son «pruebas») |
| Petición que entra al daemon desde otra máquina | el del cliente | puede | la nota queda en el temporal de la OTRA máquina | sin `caller_*` (0 filas con `host_via` en la muestra) |

En todos los caminos sin nota la fila se queda **sin** los campos nuevos. La convención del log es
omitir, no inventar («una firma inventada sería peor que ninguna», `server.py:1400-1405`); quien
agrega pone la casilla `unknown` (como `by_client`, `metrics.py:393-394`).

### Cómo se distingue hoy hilo principal, subagente y mod

- **Mod**: `attribution.is_mod_call` (`attribution.py:473-484`): `tool_use_id` empieza por
  `toolu_plugin_`. Regla única, usada por el panel (`metrics.py:396`) y por
  `measure_plugin_adoption.py:98`. Fiabilidad: total para filas con `tool_use_id` (desde el
  2026-10-08). **Trampa**: las 166 filas del mod de la muestra llevan `caller_kind: main`; si la
  columna «hilo principal» no descuenta antes el mod, sale 234 en vez de 68.
- **Hilo principal / subagente al momento**: `caller_kind` de la nota (`agent_id` presente →
  `subagent`; `attribution.py:219-220`). 99,4 % de las filas con `tool_use_id` del modelo.
- **A posteriori**: `recompute-cost` casa la fila con su `tool_use` en los transcripts
  (`transcripts.match_lines`, `transcripts.py:319-360`) y guarda `caller_kind` en
  `attribution-AAAAMM.json` (`transcripts.entry_for`, `transcripts.py:290-303`). `kind` sale de si la
  ruta del transcript contiene `subagents` (`transcripts.py:206`). Exacto con `tool_use_id`; por
  ventana de tiempo sin él; solo mientras vivan los transcripts (`cleanupPeriodDays`, 30 por defecto).
- **Trampa de las filas fundidas**: `cost.merge_row` (`cost.py:178-204`) rellena `caller_kind` con el
  respaldo cuando no hay modelo, y el respaldo por defecto es **`subagent`**
  (`cost.DECLARED_FALLBACK`, `cost.py:29`). El panel, `local_status` y `measure_adoption.py`
  trabajan sobre filas fundidas: contar `caller_kind == "subagent"` ahí infla los subagentes con
  todo lo desconocido. El dato real se reconoce así: la fila trae `caller_src` (vino de la nota) o
  `match` es `exact`, `window` o `window+path` (vino del relleno). `measure_plugin_adoption.py:103`
  lo hace bien porque usa la fila cruda y la entrada del relleno.

### Qué cuentan hoy las dos mediciones

- `scripts/measure_adoption.py`: cruza la **telemetría de hooks** (`telemetry.jsonl`, lecturas,
  avisos, bloqueos; `measure_adoption.py:154`) con las filas fundidas del log
  (`merged_usages`, `:87-99`). Aparta solo las pruebas (`:158-166`, `--include-tests` en `:236-240`).
  «Sesiones» sale de `session_id` de la telemetría (`:201`). **No sabe de proyecto ni de hilo.** La
  telemetría lleva `session_id` en claro y ningún dato de proyecto (`hook_common.context_of`,
  `hook_common.py:147-158`; claves vistas en 3000 eventos: `ts`, `event`, `suggested`, `version`,
  `session_id`, `block`, `category`, `via`, `scope`, `reason`, `route`, `ext`, `path_sha`, …).
- `scripts/measure_plugin_adoption.py`: recorre `~/.claude/projects/*/*.jsonl` (`:155-170`), se
  queda con sesiones interactivas y mira si algún `tool_use_id` «decidido por el modelo» del log
  aparece en el transcript **principal**. Aparta pruebas, otros clientes, mod, filas sin
  `tool_use_id` y subagentes (`exclusion`, `:88-106`). Tiene en la mano el directorio de proyecto de
  cada sesión (`path.parent.name`) y no lo usa. Solo da la columna del hilo principal.

## Impact map

Superficies contadas con Grep (`usage-*.jsonl`, `cost.merge(`, `_read_file_cached(`,
`recompute._read_log(`, `_current_log_path()`): **14 ficheros** de `src/` y `scripts/` leen o
escriben filas del log; **43 ficheros de test** tocan alguna de las funciones afectadas.

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| Nota del hook | Guarda `transcript_path` y la clave de sesión | Ninguno si el proyecto se deriva solo de `transcript_path`; añadir `cwd` solo si se elige reconocer `self` por marcador | `resources/hooks/hook_common.py:1307-1339` |
| Regla de proyecto (nueva) | No existe | Función pura: directorio de proyecto → hash y tipo. Tiene que poder usarla el hook (stdlib, sin importar el paquete): vive en `hook_common.py` y se reexporta, como `session_key` | `hook_common.py:1281-1291`, `attribution.py:31` |
| Atribución al momento | `resolve_call` devuelve los `caller_*` | Añade los dos campos; regla única de columna (`mod` / `main` / `subagent` / `unknown`) | `attribution.py:195-239`, `:473-484` |
| Escritura de la fila | `_log_event` copia lo que devuelve `current_call` | Sin cambio de código | `server.py:1417-1428` |
| Relleno a posteriori | `transcripts.read` conoce el directorio de proyecto (`parts[0]`) y hoy solo lo usa para `bench` | `Delegation` y `entry_for` llevan proyecto; `cost.BACKFILL_FIELDS` crece | `transcripts.py:196-227`, `:290-303`; `cost.py:60-68` |
| Fusión del relleno | Una entrada solo se cambia por otra de cruce MEJOR | Una entrada `exact` ya escrita no recibiría los campos nuevos: hace falta «mismo rango: añadir lo que falta» | `attribution.py:397-446` (regla en `:421-425`) |
| Panel, Python | `_usage_rows` es el único sitio que aparta pruebas; `_aggregate` cuenta `mod_calls` | Filtro del propio repo en la misma costura; tres columnas en `by_client` y en el total; contadores `excluded_self` y `unknown_project` | `web/metrics.py:516-533`, `:259-508`, `:536-598` |
| Panel, `/api/stats?session=` | La barra de estado del mod pide el ahorro de SU sesión | Con `session=` no se aparta el propio repo (si no, la barra da 0 dentro del repo) | `metrics.py:574-577`, `mod/status.js:656` |
| Panel, coste | `cost_block` ve todas las filas y aparta pruebas él mismo | Decidir si sigue el filtro nuevo (pregunta 5) | `metrics.py:585-592`, `valuation.py:155` |
| Panel, tarjeta de hooks | Lee la telemetría; solo aparta ventanas de prueba | Sin dato de proyecto no puede filtrar (pregunta 4) | `metrics.py:727-774` |
| Panel, JS (espejo) | `buildQuery(range, includeTests, lang)`, interruptor «Pruebas» con `ld-tests`, `renderClients` con `mod_calls`; `acct(e)` espejo de `_accounting` | Interruptor nuevo junto a «Pruebas», parámetro en las tres peticiones, tres columnas en «Quién delegó». `acct(e)` no cambia | `metrics.py:1938-1944`, `:2324-2331`, `:2335-2347`, `:2379-2407`, `:3284`, `:3654-3661` |
| Catálogos del panel | Textos es/en | Claves nuevas en los dos | `resources/i18n/{es,en}/panel.json` |
| `local_status` | Cuenta el mes en curso sin pruebas | Decidir si dice aparte lo del propio repo (pregunta 5) | `server.py:9539-9566` |
| `measure_adoption.py` | Cruce avisos ↔ delegaciones | `--exclude-self` (por defecto) con `--include-self`; tres columnas; contadores | `scripts/measure_adoption.py:152-225`, `:228-243` |
| `measure_plugin_adoption.py` | % de sesiones con delegación del modelo | Igual; el tipo de la sesión sale del directorio del transcript; columnas de subagentes y mod | `scripts/measure_plugin_adoption.py:88-106`, `:155-224`, `:254-261` |
| `recompute-cost` | Escribe el relleno y los agregados | Lleva el proyecto al relleno; resumen sin cambio | `recompute.py:330-360` |
| `doctor` (coste) | Cuenta pendientes sobre filas fundidas | Sin impacto (campo aditivo) | `checks.py:2482-2501` |
| `test-window` | Cuenta filas por ventana | Sin impacto | `cli.py:419-444` |
| Lectores que no cambian | Ritmo, lentitud, corpus, resumen estructurado, enfriamiento, fronteras | Sin impacto | `pace.py:238-241`, `scripts/measure_slowness.py:159`, `scripts/build_corpus.py:1204`, `scripts/measure_structured_summary.py:189`, `scripts/measure_cooldown.py`, `scripts/measurement_boundaries.py` |
| Captura del panel | Carga de `/api/stats` simulada | Añadir los contadores nuevos | `scripts/dev/capture_dashboard.py:292` |
| Documentación | El esquema del log está en la wiki | CHANGELOG, README y `docs/wiki/Savings-and-metrics.md` (9 menciones a estos campos), `Configuration.md` si hay variable nueva | regla «una release toca tres sitios» |

## Existing conventions

- **Campos aditivos y omitidos cuando no aplican**; `legacy_names.normalize` conserva las claves que
  no conoce (`legacy_names.py:601-620`). Precedentes sin romper lectores: `caller_session_key`,
  `host`, `pieces`.
- **Nunca el dato en claro, sí una clave de un solo sentido**: `session_key` =
  `sha256("local-delegate-session:" + id)[:32]` (`hook_common.py:1278-1291`); `path_digest` =
  `sha256(ruta normalizada)[:16]` (`hook_common.py:1169-1176`). Ninguna usa sal.
- **Una sola regla por pregunta**, en `attribution.py`, usada por panel, `local_status`, coste y
  scripts: `test_reason`, `is_mod_call`, `exclusion_reason`.
- **El formato de la nota vive en dos sitios** (hook y servidor) y lo ata un test de ida y vuelta
  (`tests/test_attribution.py:117`).
- **El panel nunca abre `~/.claude`** (`metrics.py:585-586`, REQ-073 de `coste-api-y-cuota`); leer
  transcripts es cosa de `recompute-cost` y de los scripts.
- **El interruptor «Pruebas» es el molde** del filtro nuevo: parámetro `include_tests`, las tres
  peticiones con el mismo conjunto, contadores `excluded_tests` y `tests_in_range`, estado en
  `localStorage`.
- **Observar no rompe una tool**: la resolución va en su propio `try` (`server.py:1417-1428`) y
  tiene presupuesto de 50 ms (`attribution.py:38`).
- Código en inglés, textos de salida en español e inglés; panel sin prosa, con la explicación en
  diálogo, y verificado con capturas en claro y oscuro.

## Privacidad

- **Qué se hashea**: el nombre del directorio de proyecto (`Path(transcript_path).parent.name`),
  pasado a minúsculas, con un prefijo propio (`local-delegate-project:`) y, si se aprueba, una sal
  local. 16 hexadecimales, como `path_digest`. Nunca el `cwd` ni la ruta del transcript.
- **Con sal o sin ella**: sin sal, el hash de un nombre corto y adivinable se confirma con un
  diccionario de rutas probables, y el repo es público y la evidencia de los issues sale de este
  log. Con sal local (un fichero aleatorio en `LOG_DIR`, creado una vez con apertura exclusiva y
  permisos del usuario) el hash no sale de la máquina con significado. Coste: un fichero más; si se
  pierde, los grupos por proyecto se parten en dos, el tipo no cambia. Los scripts de la misma
  máquina leen la misma sal. Recomendación: **con sal** (pregunta 2).
- **Que no quede la ruta en claro**: los campos nuevos solo llevan hash y tipo; test con un nombre
  de proyecto marcador que no puede aparecer en `json.dumps(fila)` (mismo patrón que
  `tests/test_attribution.py:448-465`). La nota temporal ya guarda `transcript_path` 10 minutos y
  no cambia.
- **Aviso**: el log **ya guarda rutas en claro** en el campo `path` de casi todas las filas
  (`server.py:1502-1503`). La garantía nueva cubre los campos nuevos, no convierte el log en
  anónimo. Queda fuera de alcance, pero conviene que la spec lo diga.
- **Reconocer `self` sin cablear una ruta personal**: tres caminos posibles (pregunta 1).
  1. *Por nombre* (recomendado): `self` si el nombre del directorio de proyecto contiene el nombre
     público del repo (`local-delegate`, constante del paquete), más una variable opcional con
     nombres o rutas extra (por ejemplo `LOCAL_DELEGATE_SELF_PROJECTS`) que se lee y nunca se
     registra. Sin lectura de disco, vale para el relleno aunque el directorio ya no exista, y
     funciona con los hooks ya instalados. En esta máquina: 16 de 40 directorios de proyecto llevan
     ese nombre (el repo y 15 temporales de bancos); ninguna sesión se lanzó desde dentro de un
     worktree. Falla con un clon con otro nombre (lo cubre la variable) y da `self` a un proyecto
     hermano cuyo nombre contenga el del repo.
  2. *Por marcador*: subir desde el `cwd` hasta un `pyproject.toml` con
     `name = "local-delegate-mcp"`. Exacto para el repo y sus worktrees, pero exige guardar `cwd` en
     la nota, lee disco en el camino de la llamada, no cubre temporales y no sirve para el relleno
     de un directorio borrado.
  3. *Por remoto de git*: leer `.git/config` (o el `commondir` de un worktree). Mismos límites que
     el marcador y más código.
  Para cualquier otra persona que instale el paquete nada casa: todo es `other` y `--exclude-self`
  no quita nada.

## Compatibilidad

- **Filas viejas sin el campo**: casilla `unknown`, nunca `other` ni `self`. Las salidas dicen
  cuántas hay (`unknown_project`) y cuántas se apartaron (`excluded_self`).
- **Histórico**: el relleno puede estampar proyecto en filas ya escritas mientras vivan sus
  transcripts (cruce exacto desde el 2026-10-08). `match_lines` vuelve a pasar por todas las filas
  de la ventana porque `n` nunca está en la fila cruda (`transcripts.py:314-316`), pero
  `write_backfill` no enriquece una entrada del mismo rango: hay que cambiar esa regla o el
  histórico reciente se queda sin proyecto. Lo anterior a la retención se queda `unknown`
  (pregunta 3).
- **Rotación**: campo aditivo; vale igual para el fichero fijo de `LOCAL_DELEGATE_LOG`.
- **Lectores que rompen con un campo nuevo**: ninguno encontrado. Todos leen con `dict.get`; el
  único test de claves exactas es de `clients.jsonl` (`tests/test_clients.py:116`), no del log de
  uso. `/api/events` sirve las filas tal cual: el hash llega al navegador (es un hash).
- **Versiones cruzadas**: derivando solo de `transcript_path`, un hook viejo con un servidor nuevo
  ya funciona (la nota lo trae desde `coste-api-y-cuota`). Un mod viejo contra un daemon nuevo sigue
  pidiendo `/api/stats?session=` sin parámetros nuevos: por eso `session=` no debe apartar nada.
- **Mac contra PC**: cada máquina tiene su `LOG_DIR` y su sal; los hashes no son comparables entre
  máquinas y no hace falta que lo sean. La regla por nombre vale en las dos. La Mac registra en su
  propio log aunque la inferencia corra en la PC. Una petición que entra al daemon desde otra
  máquina no tiene nota legible: `unknown`.
- **Relleno**: `attribution-AAAAMM.json` sigue en versión 1; los campos nuevos de una entrada son
  aditivos.

## Requisitos candidatos

| Id | Requisito | Criterio observable | Verificación |
| --- | --- | --- | --- |
| R1 | Regla única de proyecto: de un `transcript_path` válido salen `caller_project` (hash de 16 hex) y `caller_project_kind` (`self` u `other`); sin ruta válida, nada | Misma entrada → mismo hash; dos nombres distintos → hashes distintos; el nombre del repo y un worktree suyo → `self`; otro → `other`; ruta fuera de `~/.claude/projects` → sin campos | `test` |
| R2 | La fila del log lleva los dos campos cuando hay nota vigente, por los cuatro caminos de `_log_event`, también para el mod y para un subagente (con el proyecto del principal) | Filas escritas en test con nota de principal, de subagente y de mod llevan los campos; sin `tool_use_id` o sin nota no hay ninguno | `test` |
| R3 | Ni la ruta ni el nombre del proyecto quedan en la fila ni en el relleno | Un nombre marcador no aparece en `json.dumps` de la fila ni en `attribution-AAAAMM.json` | `test` |
| R4 | Resolver el proyecto no lee disco ni cuesta más que hoy: la fila se escribe aunque falle | Mutante que lanza dentro de la regla → la fila se escribe sin los campos; sin aperturas de fichero nuevas en `resolve_call` (salvo la sal, cacheada) | `test` |
| R5 | El relleno estampa proyecto en filas ya escritas y enriquece una entrada del mismo rango sin perder nada | Entrada `exact` previa sin proyecto + nueva `exact` con proyecto → fundida con proyecto y con sus demás campos intactos; una `window` nunca pisa una `exact` | `test` |
| R6 | Regla única de columna: `mod`, `main`, `subagent`, `unknown`, con el mod primero y sin contar el respaldo como dato | Fila del mod con `caller_kind: main` → `mod`; fila fundida con hilo de respaldo → `unknown`; fila con `caller_src` o cruce `exact`/`window` → su hilo | `test` |
| R7 | `/api/stats` y `/api/events` apartan el propio repo con el mismo conjunto cuando el panel lo pide, y dicen cuántas filas apartaron y cuántas no tienen proyecto | Las dos respuestas dan el mismo recuento; `excluded_self` y `unknown_project` cuadran con el log de prueba; con el parámetro contrario vuelven todas | `test` |
| R8 | `/api/stats?session=` da las cifras de la sesión aunque sea del propio repo | Sesión `self` con una delegación → `total.calls == 1` sin parámetros nuevos | `test` |
| R9 | El panel abre con el propio repo apartado, con un interruptor junto a «Pruebas» que lo incluye y se recuerda, y las tres peticiones llevan el mismo parámetro | Test de navegador como `test_the_tests_switch_requests_all_three_with_the_parameter`; `buildQuery` probado con node | `test` |
| R10 | «Quién delegó» separa hilo principal, subagentes y mod (y lo desconocido), y la suma da el total | `by_client` y el total traen los cuatro recuentos; suma igual a `calls`; capturas en claro y oscuro | `test` + `manual` |
| R11 | `measure_adoption.py` aparta el propio repo por defecto (`--include-self` lo deja), en el log de uso y en los eventos de hooks, y separa las delegaciones en las tres columnas | Escenario con una sesión `self` y otra ajena: por defecto solo cuenta la ajena; la salida dice lo apartado y lo desconocido | `test` |
| R12 | `measure_plugin_adoption.py` igual: sesiones del propio repo fuera por defecto, y por sesión las tres columnas | Mundo de test con sesión `self` con delegación y sesión ajena sin ella → `pct` 0,0 por defecto y 50,0 con `--include-self` | `test` |
| R13 | Las filas y entradas viejas se leen igual que antes | Los tests actuales de `measure_*`, `metrics`, `recompute`, `transcripts`, `valuation` y `density` pasan sin tocar sus aserciones, salvo donde cambia una firma | `cmd` |
| R14 | Textos nuevos del panel y de los scripts en español e inglés, catalogados | `test_no_uncatalogued_text`, paridad de catálogos | `test` |
| R15 | CHANGELOG, README y wiki describen los campos, el filtro y la variable | Revisión de los tres sitios | `review` |
| R16 | Prueba en vivo con el daemon instalado: una delegación desde el repo y otra desde otro proyecto dejan `self` y `other`, dentro de una ventana de prueba | Dos filas con el tipo esperado; el panel las aparta o no según el interruptor | `manual` |

Si se aprueba llevar el proyecto a la telemetría de hooks (pregunta 4), se añade: **R17** cada
evento de hooks (también los del mod por `record-read`) lleva `project` y `project_kind`, y la
tarjeta de hooks del panel sigue el interruptor (`test`).

## Preguntas abiertas (necesitan decisión del usuario)

1. **Cómo se reconoce `self`**: por nombre del directorio de proyecto más una variable de extras
   (recomendado), por marcador en `pyproject.toml` o por remoto de git.
2. **Sal del hash**: sal local en `LOG_DIR` (recomendado, por ser el repo público) o sin sal, como
   `session_key` y `path_digest`.
3. **Histórico sin transcripts**: se queda en `unknown` y las mediciones lo dicen aparte
   (recomendado), o se estima con el `path` de la fila (aproximado: una lectura de un fichero
   temporal hecha desde el repo saldría como ajena).
4. **Eventos de hooks**: `measure_adoption.py` cuenta sobre todo eventos de hooks, que hoy no saben
   de proyecto. Opciones: (a) estampar proyecto en cada evento de la telemetría de aquí en adelante
   y, para lo viejo, que el script lo resuelva buscando el transcript de la sesión (recomendado;
   toca los hooks y el `record-read` del mod); (b) solo la resolución en el script, y la tarjeta de
   hooks del panel se queda sin filtro; (c) cruzar por la clave de sesión del log de uso, que no
   sirve para las sesiones sin ninguna delegación, justo las que se quieren ver.
5. **Hasta dónde llega el filtro**: ¿el coste equivalente del panel sigue el interruptor
   (recomendado: sí, para que no contradiga los KPI)? ¿`local_status` dice aparte lo del propio
   repo (recomendado: no cambiar la cifra y añadir el recuento)?

## Reparto propuesto

Orden: T1 primero; después T2, T3, T5 y T6 en paralelo y T4 en serie sobre su fichero; T7 al final.

| Tarea | Qué hace | Ficheros dueños | Depende de |
| --- | --- | --- | --- |
| T1 | Regla pura de proyecto (hash, tipo, sal, variable de extras) | `src/local_delegate/resources/hooks/hook_common.py` (sección nueva), `src/local_delegate/config.py`, `tests/test_project_identity.py` (nuevo) | — |
| T2 | Campos al momento, regla de columna y fusión del relleno del mismo rango | `src/local_delegate/attribution.py`, `tests/test_attribution.py`, `tests/test_metrics_session_filter.py` (nota) | T1 |
| T3 | Proyecto en el relleno | `src/local_delegate/transcripts.py`, `src/local_delegate/cost.py`, `src/local_delegate/recompute.py`, `tests/test_transcripts.py`, `tests/test_recompute*.py`, `tests/test_density.py` | T1 |
| T4 | Panel entero, Python y JS (un solo dueño: es un fichero) | `src/local_delegate/web/metrics.py`, `src/local_delegate/resources/i18n/{es,en}/panel.json`, `scripts/dev/capture_dashboard.py`, `tests/test_metrics.py`, `tests/test_dashboard_*.py`, `tests/panel_server.py` | T2 (regla de columna) |
| T5 | `measure_adoption.py` | `scripts/measure_adoption.py`, `tests/test_measure_adoption.py` | T2 |
| T6 | `measure_plugin_adoption.py` | `scripts/measure_plugin_adoption.py`, `tests/test_measure_plugin_adoption.py` | T2 |
| T7 | Documentación y prueba en vivo | `CHANGELOG.md`, `README.md`, `docs/wiki/Savings-and-metrics.md`, `docs/wiki/Configuration.md` | todas |
| T8 (si se aprueba la pregunta 4a) | Proyecto en la telemetría de hooks y `local_status` | `hook_common.py` (`context_of`; mismo dueño que T1, en serie), `src/local_delegate/hook_entry.py`, `mod/read.js`, `src/local_delegate/server.py` (solo `local_status`), sus tests | T1 |

`server.py` no se toca para la fila (ver «Cómo llega hoy»); solo entraría por `local_status`.

## Dependencies and integrations

- Claude Code: entrada del hook `PreToolUse` (`transcript_path`, `cwd`, `session_id`, `agent_id`,
  `tool_use_id`) y `_meta["claudecode/toolUseId"]`; forma de `~/.claude/projects/<proyecto>/<sesión>.jsonl`
  y `<sesión>/subagents/agent-<id>.jsonl`. Es un formato ajeno: si cambia, los campos faltan y la
  fila sigue escribiéndose.
- Mod del plugin: `$.mcp.call` y `/api/stats?session=`; no cambia salvo T8.
- Sin dependencias nuevas de terceros (solo `hashlib`, `os`, `pathlib`).

## Tests existentes que tocaría

- `tests/test_attribution.py` (ida y vuelta de la nota `:117`, fila sin id de sesión `:448`, fila
  sin `caller_*` `:468`, «el relleno solo mejora» `:590`, exacto que no se pierde `:713`).
- `tests/test_metrics_session_filter.py` (5 tests) y `tests/test_inflight_per_session.py` (5).
- `tests/test_measure_adoption.py` (16) y `tests/test_measure_plugin_adoption.py` (7).
- `tests/test_dashboard_states.py:1024` (`test_mod_calls_shown_apart`), `tests/test_metrics.py`
  (`include_tests` `:1971`, paridad Python/JS `:1103`), `tests/test_dashboard_ui.py:1901`,
  `tests/test_dashboard_js.py` (`buildQuery`), `tests/test_dashboard_cost.py`.
- `tests/test_transcripts.py`, `tests/test_recompute.py`, `tests/test_recompute_legacy.py`,
  `tests/test_recompute_no_loss.py`, `tests/test_density.py`, `tests/test_valuation.py`.
- `tests/test_no_uncatalogued_text.py`, `tests/test_scripts_english.py`, `tests/test_f1_conformance.py`
  y, con T8, `tests/test_hook_common.py`, `tests/test_hook_boundaries.py`,
  `tests/test_telemetry_concurrent_writes.py`, `tests/test_mod_static.py`.

## Risks and unknowns

Hechos confirmados:

- El mod deja nota y su fila sale con `caller_kind: main`: sin descontarlo primero, la columna del
  hilo principal se triplica.
- El hilo de respaldo es `subagent`: contar sobre filas fundidas sin mirar el origen infla esa
  columna.
- `write_backfill` no enriquece entradas del mismo rango.
- El filtro puesto por defecto en la API dejaría en cero la barra de estado del mod dentro del
  repo.
- La telemetría de hooks no lleva proyecto, y el panel no puede abrir `~/.claude` para deducirlo.
- El log ya guarda `path` en claro.

Riesgos de regresión:

- Cambiar la firma de `buildQuery` o de `_usage_rows` rompe tests de node y de navegador que hoy
  fijan «las tres peticiones llevan lo mismo».
- Un KPI del panel que baja de golpe al actualizar (el propio repo es la mayoría del uso aquí) se
  leerá como pérdida de datos si el interruptor y su recuento no se ven.
- Tocar `merge_row` o `BACKFILL_FIELDS` afecta al coste, a los agregados de `N` y a `doctor`.
- La sal creada a la vez por el daemon y un proceso stdio: carrera que daría dos hashes para el
  mismo proyecto si no se crea con apertura exclusiva y relectura.
- `hook_common.py` lo cargan todos los hooks: un fallo de importación ahí los apaga todos.

Supuestos por validar:

- Que la entrada del hook para la llamada del mod traiga siempre el `transcript_path` de la sesión
  (la muestra dice que la nota existe en 166 de 166 y trae clave de sesión en 161; no se leyó el
  contenido de ninguna nota).
- Que Claude Code en macOS forme el nombre del directorio de proyecto con la misma regla (medido
  solo en Windows).
- Cuántos días de transcripts hay de verdad en esta máquina para el relleno del histórico.
- Que ninguna sesión real de otro proyecto tenga el nombre del repo en su ruta.
