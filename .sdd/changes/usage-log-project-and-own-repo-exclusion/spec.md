# Specification: Log de uso con proyecto (hash y tipo) y mediciones que apartan el propio repo

## Summary

Cada fila del log de uso que se puede atribuir a una sesión de Claude Code guarda de qué proyecto
salió, como hash de un solo sentido (`caller_project`) y como tipo (`caller_project_kind`: `self`,
el propio repo de `local-delegate`, u `other`). Con ese dato, el panel, `local_status` y los dos
scripts de adopción dejan de mezclar el uso hecho al desarrollar la herramienta con el uso real:
apartan el propio repo por defecto, dicen cuántas filas apartaron y cuántas no tienen proyecto, y
separan las delegaciones en hilo principal, subagentes y mod. La telemetría de hooks lleva el mismo
dato de aquí en adelante. Nada de lo viejo se reescribe: una fila sin el campo es `unknown`.

Las filas ya escritas reciben el proyecto por el relleno, y solo cuando se corre `recompute-cost`
con la versión nueva: **hasta entonces el panel no aparta nada del histórico**.

Nombres fijados por esta spec (todos en inglés):

| Sitio | Nombre |
| --- | --- |
| Fila del log de uso y entrada del relleno | `caller_project`, `caller_project_kind` |
| Evento de la telemetría de hooks | `project`, `project_kind` |
| Lista de proyectos propios extra | `self-projects.json`, dentro de `LOG_DIR` |
| Fichero de la sal | `project-salt`, dentro de `LOG_DIR` |
| Parámetro de `/api/stats`, `/api/events`, `/api/hooks` | `include_self` |
| Contadores de esas respuestas | `excluded_self`, `self_in_range`, `unknown_project` |
| Recuentos por hilo (total y cada fila de `by_client`) | `main_calls`, `subagent_calls`, `mod_calls`, `unknown_caller_calls` |
| Reglas únicas | `hook_common.project_identity`, `hook_common.project_of_session`, `attribution.project_kind`, `attribution.caller_column` |
| Opciones de los scripts | `--exclude-self` (por defecto), `--include-self` |

## Decisions

Quién decidió qué (queda también en el log de `brief.md`): D1 a D5 las tomó la sesión
coordinadora el 2026-11-10, siguiendo la recomendación de la investigación, y se comunicaron al
usuario. D6 a D8 las impuso el encargo, por los hallazgos de la investigación. D9, D11 y D12 las
propuso quien redactó esta spec; la revisión 1 dio D9 por correcta y D11 por defendible. D10 se
invirtió tras la primera pasada de la revisión 1, por decisión de la sesión coordinadora. En la
segunda pasada, D13 (la línea del mod por `session_id`) sigue la propuesta del revisor, aceptada
por la sesión coordinadora, y D12 (la lista en un fichero de `LOG_DIR`, que sustituye a la
variable de entorno de D1) la decidió la sesión coordinadora al pedir que la lista se lea igual en
todos los caminos.

- **D1 — `self` se reconoce por nombre.** El tipo sale del nombre del directorio de proyecto
  (`Path(transcript_path).parent.name`) y de una lista de extras. Motivo: no lee disco en el camino
  de la llamada, sirve para el relleno aunque el directorio ya no exista, funciona con los hooks
  ya instalados y no cablea ninguna ruta personal en el código. Se descartan el marcador en
  `pyproject.toml` y el remoto de git: exigen guardar `cwd` en la nota y leer disco, y no cubren un
  directorio borrado. La lista de extras se decidió como variable de entorno; la segunda pasada la
  movió a un fichero (D12).
- **D2 — El hash lleva sal local.** La sal vive en `LOG_DIR/project-salt` y nunca sale de la
  máquina. Motivo: el repo es público y la evidencia de sus issues sale de este log; sin sal, el
  hash de un nombre corto se confirma con un diccionario de rutas probables. Límite reconocido:
  quien tenga a la vez el log y `project-salt` puede confirmar un nombre por fuerza bruta; por eso
  ese fichero no se comparte junto a un log.
- **D3 — Lo que no se puede atribuir queda `unknown`.** Una fila sin proyecto no se estima con su
  `path`. Motivo: una lectura de un fichero temporal hecha desde el repo saldría como ajena; un
  dato inventado es peor que una casilla `unknown` contada aparte.
- **D4 — La telemetría de hooks lleva proyecto de aquí en adelante.** Los eventos viejos los
  resuelve `measure_adoption.py` buscando el transcript de la sesión. Motivo: esa medición cuenta
  sobre todo eventos de hooks, y cruzar por la clave de sesión del log de uso no sirve para las
  sesiones sin ninguna delegación, que son justo las que se quieren ver.
- **D5 — El coste equivalente sigue el mismo filtro; `local_status` solo añade un recuento.**
  Motivo: un coste que no siguiera el filtro contradiría los KPI de la misma pantalla; la cifra de
  `local_status` es la que ya se cita en issues y no debe moverse sin aviso.
- **D6 — Tres columnas, con el mod primero.** Una fila del mod llega con `caller_kind: main`: si no
  se descuenta antes, la columna del hilo principal sale inflada (234 en vez de 68 en la muestra de
  la investigación).
- **D7 — El respaldo no es un dato.** `cost.merge_row` rellena el hilo con `subagent` cuando no
  sabe: una fila así cuenta como `unknown`, no como subagente.
- **D8 — `session=` no aparta el propio repo.** La barra de estado del mod pide
  `/api/stats?session=` sin parámetros nuevos; si el filtro por defecto le aplicara, daría 0 dentro
  del repo, también con un mod viejo contra un daemon nuevo.
- **D9 — El filtro mira solo el tipo, nunca el hash.** Motivo: así perder la sal, o que dos
  procesos vean un `LOG_DIR` distinto, parte los grupos por proyecto pero no cambia qué se aparta.
- **D10 — El relleno da proyecto a todo cruce real y a toda fila con clave de sesión.** Llevan
  proyecto las entradas `exact`, `window` y `window+path`, nuevas o ya escritas (una entrada del
  mismo rango recibe los campos que le falten), y además toda fila con `caller_session_key` cuya
  sesión tenga vivo su transcript principal en un solo directorio, aunque su cruce sea `no_match`
  (es el caso del mod, cuyo `tool_use` no está en el transcript). Motivo: el mismo cruce ya se da
  por bueno para el hilo, el modelo y `N`; negárselo al proyecto era incoherente con REQ-007 y
  REQ-008. La versión anterior de esta decisión (solo `exact`) se retiró por estas cifras, medidas
  en la revisión 1 sobre el log real de esta máquina (solo recuentos; retención de transcripts de
  90 días aquí, 30 por defecto):

  | Filas que no son prueba (1.593, cota alta) | Recuento | Con esta decisión |
  | --- | ---: | --- |
  | Modelo, con `tool_use_id`, sin entrada de relleno todavía | 986 | proyecto por cruce `exact` al correr `recompute-cost` |
  | Modelo, con `tool_use_id`, entrada `exact` | 71 | proyecto por enriquecimiento |
  | Mod (`toolu_plugin_…`), sin entrada | 169 | proyecto por `caller_session_key` (la mayoría la trae: 161 de 166 en la muestra de la investigación) |
  | Cruce `window` o `window+path` | 187 | proyecto por enriquecimiento |
  | Claude Code sin id, `ambiguous` o `no_match` | 8 | `unknown` |
  | Chat | 11 | `unknown` |
  | Otros clientes sin id y sin cruce | 161 | `unknown` |

  **1.593 es una cota alta**: el recuento apartó las pruebas con `test_reason` sobre la fila cruda,
  sin el sello `test_window` que pone la fusión, así que las filas de ventanas de prueba siguen
  dentro. Tendrían proyecto como mucho 1.413 filas y se quedan `unknown` al menos 180 (11,3 %), más
  las del mod sin clave de sesión y las de sesiones cuyo transcript ya no esté. Con la versión
  retirada se quedaban `unknown` al menos 536 (34 %). **La causa de lo `unknown` no es la
  retención**: casi todo está dentro de ella; es no tener cruce ni clave de sesión. Y 986 filas no
  tienen entrada porque `recompute-cost` solo se lanza a mano.
- **D11 — Lo `unknown` se queda en los totales y se cuenta aparte.** Motivo: Codex, el chat y las
  filas viejas nunca tendrán proyecto; apartarlas borraría uso real. Las salidas dan el recuento
  para que quien lea pueda quedarse solo con lo `other`. Consecuencia en esta máquina, donde casi
  todo lo `unknown` es uso del propio repo: esas 180 filas o más siguen dentro de la cifra por
  defecto.
- **D12 — La lista de extras y la sal viven en `LOG_DIR`, y `LOG_DIR` sale siempre del entorno del
  proceso.** La lista es `LOG_DIR/self-projects.json`, al lado de la sal y como el interruptor
  `read-hook.json`. `LOG_DIR` se resuelve con el `os.environ` del proceso que escribe
  (`hook_common.log_dir()` o `config.LOG_DIR`), nunca con el entorno que manda el mod en una
  petición. Motivo: el proyecto lo resuelven procesos con entornos distintos, y una variable de
  entorno no se ve igual en todos:

  | Camino | Proceso | Entorno |
  | --- | --- | --- |
  | Fila del log (MCP por HTTP) y línea del mod por el daemon | daemon | el del daemon (tarea programada o launchd) |
  | Fila del log (MCP por stdio) | servidor stdio | el del lanzador de Claude Code |
  | Eventos de los hooks | un proceso por evento | el del lanzador de Claude Code |
  | Línea del mod por el respaldo | `hook record-read` lanzado por el mod | el del lanzador de Claude Code |
  | Relleno | `recompute-cost` | el de la terminal |
  | Mediciones | los dos scripts | el de la terminal |

  Con una variable definida en el lanzador y no en el daemon, un clon con otro nombre salía `self`
  en los eventos de hooks y `other` en las filas, y una fila ya sellada `other` no la corrige el
  relleno (`cost.merge_row` solo rellena lo vacío). Todos esos procesos ya resuelven `LOG_DIR` con
  la misma regla para el log, la sal y el interruptor, así que un fichero ahí se lee igual en
  todos. Se añade un fichero porque hace falta para esto; no hay variable de entorno de extras.
  Además, leer `LOG_DIR` del entorno de una petición convertiría un endpoint del daemon en una
  forma de crear ficheros en cualquier directorio, la clase de fallo cerrada en la 0.41.1. Por el
  mismo motivo, la raíz de proyectos de `project_of_session` sale del `os.environ` del proceso
  (`Path.home()`), nunca del `HOME` o `USERPROFILE` de la petición.
- **D13 — La línea del mod saca el proyecto de su `session_id`, no de `classify`.**
  `hook_entry.record_read` valida el `session_id` que ya trae la entrada, busca
  `<raíz de proyectos>/*/<session_id>.jsonl` y aplica `project_identity` sobre esa ruta, en el
  proceso que escribe la línea. Así el hash sale del mismo directorio que el de la fila del log.
  Se descartó añadir `project` a la respuesta de `hook classify` desde el `cwd`: esa respuesta
  tiene que salir idéntica por el daemon y por el proceso de respaldo
  (`tests/test_hook_classify_endpoint.py`), y con la sal de cada proceso saldría distinta; tomar la
  sal del `LOG_DIR` de la petición reabriría el fallo de la 0.41.1; y el hash del `cwd` difiere del
  de la fila cuando el `cwd` es un subdirectorio o un worktree.
- **D14 — Una sesión en dos directorios no tiene proyecto.** Si el id de sesión aparece en más de
  un directorio de proyecto, o si el proyecto de la clave de sesión y el del cruce de la fila no
  coinciden, no se asigna proyecto. Motivo: una sesión reanudada desde otro `cwd` podría dar ese
  caso y el índice elegiría uno por el orden de recorrido; un proyecto sin certeza es peor que
  `unknown`. Medido hoy en esta máquina (solo recuentos): 353 ids de sesión en 40 directorios,
  ninguno repetido.

## Requirements

- **REQ-001** — `hook_common.project_identity` es la única regla de proyecto: de un
  `transcript_path` válido (cuelga de la raíz de proyectos de Claude Code y acaba en `.jsonl`)
  devuelve `caller_project`, 16 hexadecimales de
  `sha256("local-delegate-project:" + sal + ":" + nombre en minúsculas)`, y
  `caller_project_kind`; el mismo nombre da siempre el mismo hash, dos nombres distintos dan hashes
  distintos, dos sales distintas dan hashes distintos, y una ruta que no es válida no da ningún
  campo.
  - Request: "guardar el proyecto en cada fila del log de uso (hash y tipo: el propio repo o ajeno)"
  - Verify: test tests/test_project_identity.py
- **REQ-002** — El tipo sale de comparar tramos, no subcadenas. **Normalización**, igual para el
  nombre del directorio de proyecto y para cada entrada: cada carácter fuera de `[A-Za-z0-9]` (en
  ASCII; también `ñ` y las vocales con tilde) pasa a `-`, y todo a minúsculas (`Diseño` →
  `dise-o`). Normalizar también el nombre del directorio hace que la comparación no dependa de lo
  que Claude Code haga con esas letras, que en esta máquina no se puede medir. **Coincidencia**: el
  nombre normalizado contiene la entrada normalizada como tramo completo, es decir, con un `-` o el
  principio del nombre a la izquierda y un `-` o el final a la derecha. El tipo es `self` si
  coincide el nombre público del repo (`local-delegate`, constante del paquete) o alguna entrada de
  `LOG_DIR/self-projects.json` (un objeto JSON con `names`, lista de textos, nombres o rutas); en
  cualquier otro caso es `other`. Se ignoran las entradas que no son texto y las que, normalizadas,
  tienen menos de 3 caracteres alfanuméricos; un fichero de más de 64 KiB, ausente, ilegible o con
  otra forma equivale a una lista vacía, sin error. El repo, un worktree suyo y un subdirectorio
  dan `self`; un clon con otro nombre da `self` solo con la lista; la entrada `app` no marca
  `webapp` ni `happy`. `LOG_DIR` sale del entorno del proceso (D12). La lista se lee una vez por
  proceso y por ruta: tras editarla, el daemon necesita reiniciarse para verla.
  Motivo de la regla por tramos: Claude Code convierte cada separador de ruta en `-`, así que un
  componente de ruta siempre queda entre guiones. Exigir esos límites impide que una entrada corta
  aparte en silencio uso real de proyectos que solo la contienen. Una entrada con ruta completa
  da el control exacto: casa con ese directorio, sus subdirectorios y sus worktrees. La subcadena
  libre de antes marcaba `self` cualquier nombre que contuviera tres letras.
  - Request: "el propio repo o ajeno"
  - Verify: test tests/test_project_identity.py
- **REQ-003** — La sal es un fichero de 64 hexadecimales aleatorios en `LOG_DIR/project-salt`, con
  permisos solo del usuario. Se crea de forma atómica y con su contenido ya escrito, sin
  sobrescribir uno válido: si ya existe con contenido válido, la función devuelve ese contenido y
  no lo toca. Un fichero de sal vacío o inválido que ya estuviera ahí se repara (se sustituye por
  una sal válida, bajo cerrojo) en vez de dejar el hash perdido para siempre. Se lee una vez por
  proceso y por ruta (la caché va por ruta del fichero). Si no se puede leer, crear ni reparar, se
  omite `caller_project` y se conserva `caller_project_kind`: nunca se escribe un hash sin sal.
  - Request: derived: decisión D2; el repo es público y un hash sin sal de un nombre corto se confirma con un diccionario
  - Verify: test tests/test_project_identity.py
- **REQ-004** — Una fila escrita por `server._log_event` con nota vigente del hook lleva los dos
  campos, por los cuatro caminos que la llaman (`_chat`, `_chat_chunked`, `_chat_map_reduce`,
  `_log_stopped`), también cuando la pide el mod y cuando la pide un subagente (con el proyecto de
  la sesión principal); sin `tool_use_id`, sin nota o con la nota caducada, la fila no lleva
  ninguno de los dos.
  - Request: "guardar el proyecto en cada fila del log de uso"
  - Verify: test tests/test_usage_log_project.py
- **REQ-005** — Ni la ruta ni el nombre del proyecto quedan escritos en los campos nuevos: un
  nombre de proyecto marcador no aparece en `json.dumps` de la fila del log, ni en
  `attribution-AAAAMM.json`, ni en el evento de la telemetría de hooks, ni en la línea del mod. Lo
  mismo para el contenido de `self-projects.json`: una entrada marcadora que coincide con el
  proyecto de la prueba no aparece en la fila, el relleno, el evento, la salida de `local_status`
  ni las respuestas de `/api/stats`, `/api/events` y `/api/hooks`.
  - Request: "hash y tipo"
  - Verify: test tests/test_project_privacy.py
- **REQ-006** — Resolver el proyecto no rompe ni frena una tool: si la regla lanza, la fila se
  escribe igual, sin los dos campos, **y conserva `caller_kind`, `caller_src` y
  `caller_session_key`**; y `attribution.resolve_call` no abre, lista ni consulta en disco ningún
  fichero o directorio que no tocara antes, salvo la sal y la lista, una vez por proceso y por
  ruta.
  - Request: derived: convención del log «observar no rompe una tool»; el `try` general de `_log_event` salvaría la fila pero perdería toda su atribución, así que la regla necesita el suyo
  - Verify: test tests/test_usage_log_project.py
- **REQ-007** — `recompute-cost` lleva el proyecto al relleno: una entrada de
  `attribution-AAAAMM.json` con cruce real (`exact`, `window`, `window+path`) trae
  `caller_project` y `caller_project_kind`, y `cost.merge` los pone en la fila fundida que no los
  traía. Una entrada ya escrita del mismo rango que no los tiene los recibe al volver a pasar, sin
  que cambie ningún otro campo suyo; una entrada de rango menor nunca pisa ni modifica una de
  rango mayor.
  - Request: derived: sin el relleno, las filas ya escritas se quedarían `unknown` y las mediciones del periodo en curso seguirían sesgadas (decisión D10)
  - Verify: test tests/test_backfill_project.py
- **REQ-008** — `attribution.caller_column(row)` es la única regla de columna y devuelve `mod`,
  `main`, `subagent` o `unknown`, en este orden: `mod` si `attribution.is_mod_call(row)`, aunque la
  fila diga `caller_kind: main`; el `caller_kind` de la fila si es un dato real (la fila trae
  `caller_src`, o su `match` es `exact`, `window` o `window+path`); `unknown` en lo demás, incluida
  la fila fundida cuyo hilo puso el respaldo.
  - Request: "separan hilo principal, subagente y mod"
  - Verify: test tests/test_caller_column.py
- **REQ-009** — `/api/stats` y `/api/events` apartan por defecto las filas con
  `caller_project_kind: self`, las dos con el mismo conjunto; `include_self=1` (o `true`) las deja.
  Las dos respuestas traen `excluded_self` (filas que quitó este filtro después del de pruebas),
  `self_in_range` (todas las filas `self` del rango, también las que además son prueba, igual que
  `tests_in_range` cuenta todas las pruebas) y `unknown_project` (filas mostradas sin tipo), y se
  cumple `mostradas + excluded_tests + excluded_self == filas del rango`.
  - Request: "el panel apartan el propio repo por defecto"
  - Verify: test tests/test_metrics_own_repo.py
- **REQ-010** — `/api/stats?session=<id>` da las cifras de esa sesión aunque sea del propio repo y
  sin ningún parámetro nuevo: una sesión `self` con una delegación da `total.calls == 1` y
  `excluded_self == 0`.
  - Request: derived: la barra de estado del mod pide el ahorro de su sesión y daría 0 dentro del repo (decisión D8)
  - Verify: test tests/test_metrics_own_repo.py
- **REQ-011** — El coste equivalente de `/api/stats` (`cost`) sigue el filtro del propio repo: se
  calcula sin las filas `self` por defecto y con ellas con `include_self=1`; sigue sin depender de
  `include_tests`. Los agregados de `recompute-cost` y el bloque de cuota no cambian.
  - Request: derived: decisión D5; un coste que incluyera el propio repo contradiría los KPI de la misma pantalla
  - Verify: test tests/test_metrics_own_repo.py
- **REQ-012** — `/api/hooks` aparta por defecto los eventos con `project_kind: self` y los deja con
  `include_self=1`; trae `excluded_self` y `unknown_project`. Un evento sin el campo no se aparta.
  - Request: "el panel apartan el propio repo por defecto"
  - Verify: test tests/test_metrics_own_repo.py
- **REQ-013** — El panel abre con el propio repo apartado y tiene, junto a «Pruebas», un
  interruptor que lo incluye: su estado se recuerda en `localStorage` (`ld-self`), las tres
  peticiones (`/api/stats`, `/api/events`, `/api/hooks`) llevan `include_self=1` cuando está
  encendido y ninguna lo lleva cuando está apagado, y el recuento de lo apartado se ve junto al
  interruptor.
  - Request: "el panel apartan el propio repo por defecto"
  - Verify: test tests/test_dashboard_own_repo.py
- **REQ-014** — El total de `/api/stats` y cada fila de `by_client` traen `main_calls`,
  `subagent_calls`, `mod_calls` y `unknown_caller_calls`, contados con `caller_column`, y su suma
  es igual a `calls`. `mod_calls` conserva su significado de hoy.
  - Request: "separan hilo principal, subagente y mod"
  - Verify: test tests/test_metrics_own_repo.py
- **REQ-015** — La tarjeta «Quién delegó» del panel muestra las tres columnas (hilo principal,
  subagentes, mod) y lo desconocido solo cuando no es cero, legible en tema claro y en oscuro, sin
  prosa en la tarjeta (la explicación va en el diálogo de información).
  - Request: "separan hilo principal, subagente y mod"
  - Verify: manual capturas del panel en claro y en oscuro, con y sin el interruptor, guardadas en verification.md
- **REQ-016** — Los eventos de telemetría que escriben los hooks (todos pasan por
  `hook_common.context_of`) llevan `project` y `project_kind`, con la misma regla y del mismo
  directorio que la fila: los hooks, del `transcript_path` de su entrada; la línea del mod
  (`hook record-read`), del `session_id` que ya trae su entrada (D13). Para el mod,
  `hook_common.project_of_session` valida el id con forma de UUID (la de los nombres de transcript;
  cualquier otra forma, incluido un id con separadores o `..`, no forma ninguna ruta) y busca
  `<raíz de proyectos>/*/<session_id>.jsonl`; si no lo encuentra, o lo encuentra en más de un
  directorio (D14), la línea sale sin los dos campos. Un hook sin `transcript_path` válido también
  sale sin ellos (nada se deriva del `cwd`). Ni el hook ni `record-read` fallan ni dejan de
  escribir si la regla lanza. La sal y la lista salen del `LOG_DIR` del proceso que escribe (D12),
  también cuando `record-read` corre en el daemon con el entorno que manda el mod. La raíz de
  proyectos que recorre `project_of_session` sale también del `os.environ` del proceso
  (`Path.home()`, como `attribution._projects_root`), nunca del `HOME` o `USERPROFILE` que trae el
  entorno de la petición (están en `RECORD_ENV`): si no, quien llama elegiría qué carpeta se
  recorre y tendría un oráculo de existencia de ficheros, y el hash podría salir de otra raíz que
  la de la fila. La búsqueda tiene un tope de 50 ms, el mismo presupuesto que `attribution`:
  pasado el tope, la línea sale sin proyecto. Cada proceso guarda en caché, por `session_id`, el
  resultado encontrado o ambiguo (no el «no encontrado» ni el tope agotado), así que en el daemon
  las decisiones siguientes de una sesión no vuelven a recorrer la raíz.
  - Request: derived: decisión D4; `measure_adoption.py` cuenta sobre todo eventos de hooks, que hoy no saben de proyecto
  - Verify: test tests/test_hook_project.py
- **REQ-017** — `scripts/measure_adoption.py` aparta el propio repo por defecto (`--exclude-self`)
  y lo deja con `--include-self`, en las filas del log de uso y en los eventos de hooks; el tipo de
  un evento viejo sin `project_kind` lo resuelve con `hook_common.project_of_session` sobre la raíz
  de proyectos (`--projects` para cambiarla), y si no lo encuentra, o lo encuentra en dos
  directorios, es `unknown` y se queda. La salida trae `excluded_self` y `unknown_project`, cada
  uno con `hooks` y `usage`. Con una sesión `self` y otra ajena, por defecto solo cuenta la ajena.
  - Request: "las mediciones de adopcion y el panel apartan el propio repo por defecto"
  - Verify: test tests/test_measure_adoption_own_repo.py
- **REQ-018** — La salida de `scripts/measure_adoption.py` trae `delegations_by_caller` (`main`,
  `subagent`, `mod`, `unknown`, con `caller_column`), cuya suma es `total_delegations`, y
  `delegations_by_project_kind` (`other`, `unknown` y, con `--include-self`, `self`).
  - Request: "separan hilo principal, subagente y mod"
  - Verify: test tests/test_measure_adoption_own_repo.py
- **REQ-019** — `scripts/measure_plugin_adoption.py` deja fuera por defecto las sesiones cuyo
  directorio de transcript es `self` (`--exclude-self`) y las cuenta con `--include-self`; la
  salida de cada periodo trae `excluded_self_sessions`. Con una sesión `self` que delega y una
  ajena que no, `pct` es 0,0 por defecto y 50,0 con `--include-self`.
  - Request: "las mediciones de adopcion y el panel apartan el propio repo por defecto"
  - Verify: test tests/test_measure_plugin_adoption_own_repo.py
- **REQ-020** — `scripts/measure_plugin_adoption.py` da, por periodo, las tres columnas:
  `with_delegation` (hilo principal, con la definición de hoy), `with_subagent_delegation` (el
  `tool_use_id` aparece en un transcript de `<sesión>/subagents/`) y `with_mod_delegation` (fila
  del mod cuya `caller_session_key` es la de la sesión), más `delegations_by_caller`. `pct` sigue
  saliendo solo del hilo principal.
  - Request: "separan hilo principal, subagente y mod"
  - Verify: test tests/test_measure_plugin_adoption_own_repo.py
- **REQ-021** — `local_status` conserva sus cifras del mes (eventos, ahorro neto y bruto) y añade
  una línea, en español e inglés, con cuántos de esos eventos son del propio repo; la línea solo
  aparece cuando el recuento no es cero.
  - Request: derived: decisión D5; la cifra de `local_status` no cambia y solo dice aparte lo del propio repo
  - Verify: test tests/test_status_own_repo.py
- **REQ-022** — Una fila, una entrada del relleno o un evento sin los campos nuevos se lee como
  hoy y cuenta como `unknown`, nunca como `self` ni como `other`, y la suite completa pasa.
  - Request: derived: regla del repo «un fix no rompe otra cosa»; los lectores existentes y las filas viejas no pueden cambiar de resultado
  - Verify: cmd uv run --locked pytest -n 2
- **REQ-023** — El formato de la nota del hook no cambia: una nota con los campos que ya escribe
  un hook instalado de una versión anterior basta para que el servidor nuevo ponga los dos campos
  en la fila.
  - Request: derived: versiones cruzadas; el hook instalado y el servidor se actualizan por separado, también en la Mac
  - Verify: test tests/test_usage_log_project.py
- **REQ-024** — Todo texto nuevo del panel y de `local_status` sale en español e
  inglés y está catalogado: los guardianes de texto sin catalogar y de paridad de catálogos pasan
  sin excepciones nuevas.
  - Request: derived: regla del repo «código en inglés, textos de salida en español e inglés»
  - Enmienda (2026-11-10, revisión de resultado): los scripts de medición de `scripts/` quedan fuera. No van en el paquete, ya imprimían en español sin catálogo antes de este cambio y el guardián no los mira; catalogarlos es un cambio aparte.
  - Verify: test tests/test_no_uncatalogued_text.py
- **REQ-025** — CHANGELOG, README y `docs/wiki/` (`Savings-and-metrics.md` y `Configuration.md`)
  describen: los dos campos de la fila y los dos de la telemetría de hooks; la sal, con el aviso
  de que quien tenga el log y `project-salt` puede confirmar un nombre por fuerza bruta y de que
  ese fichero no se comparte junto a un log; la lista `self-projects.json` (forma, regla por
  tramos con la recomendación de usar rutas, tope de 64 KiB, que vive en `LOG_DIR`, que el daemon necesita reiniciarse para ver un cambio, y que un cambio solo afecta a
  filas y entradas nuevas: una fila ya sellada no cambia de tipo); que todo proceso que escribe
  tiene que resolver el mismo `LOG_DIR` (si `LOCAL_DELEGATE_LOG_DIR` se define en el lanzador y no
  en el daemon, o al revés, la sal y la lista difieren entre filas y eventos); el interruptor, las
  tres columnas y las opciones de los scripts; el aviso de cambio de comportamiento (las cifras
  bajan al actualizar y cómo recuperar la anterior); que hay que correr `recompute-cost` tras
  actualizar para que el histórico se aparte; y que el campo `path` sigue en claro.
  - Request: derived: regla del repo «una release toca tres sitios»
  - Verify: review CHANGELOG.md, README.md, docs/wiki/Savings-and-metrics.md, docs/wiki/Configuration.md
- **REQ-026** — Con el daemon instalado y dentro de una ventana de prueba (`test-window`), una
  delegación hecha desde el repo y otra desde otro proyecto dejan dos filas con
  `caller_project_kind` `self` y `other`; con el rango desde el inicio de la ventana e
  `include_tests=1`, `/api/stats` da `excluded_self == 1` y `total.calls == 1` por defecto y
  `total.calls == 2` con `include_self=1`; y `/api/stats?session=<sesión del repo>&include_tests=1`
  da `total.calls >= 1` y `excluded_self == 0`.
  - Request: derived: regla del repo «probar la pieza no es probar el uso»; el dato depende del hook instalado y del daemon real
  - Verify: manual prueba en vivo anotada en verification.md, con el id de la ventana de prueba
- **REQ-027** — Sobre una instantánea de `LOG_DIR` y de la telemetría de hooks tomada antes del
  cambio, con un rango `from`/`to` fijo y el mismo instante `now` para el relleno en las dos
  mediciones: toda cifra que ya existía (panel, `local_status`, `measure_adoption.py`,
  `measure_plugin_adoption.py`) da lo mismo antes y después cuando se incluye el propio repo; por
  defecto difiere solo en lo que el recuento de lo apartado explica; y `excluded_self > 0`, con el
  reparto `self` / `other` / `unknown` anotado.
  - Request: derived: regla del repo «tabla antes/después y revisión de regresiones antes de mezclar»
  - Verify: review .sdd/changes/usage-log-project-and-own-repo-exclusion/verification.md
- **REQ-028** — Cada criterio de cada requisito verificado con `test` tiene un mutante que hace
  fallar su test por la aserción que nombra el plan, y se comprueba que el mutante cambia de verdad
  el comportamiento con los datos de ese test.
  - Request: derived: regla del repo «el control positivo no es opcional»
  - Verify: review .sdd/changes/usage-log-project-and-own-repo-exclusion/verification.md
- **REQ-029** — El corte de 90 días de la ventana de medición abierta (2026-12-14) se saca con las
  dos cifras, la de `--include-self` y la de por defecto, y la wiki lo dice junto al comando: la
  cifra comparable con los cortes de 14 y 30 días es la de `--include-self`, porque la de por
  defecto mezcla eventos viejos sin transcript (`unknown`, se quedan) con eventos recientes del
  propio repo (se apartan).
  - Request: derived: los cortes anteriores lo incluían todo; sin este aviso la cifra por defecto del corte no tendría población definida
  - Verify: review docs/wiki/Savings-and-metrics.md
- **REQ-030** — El cambio no modifica, borra ni renombra ningún fichero existente de `tests/`:
  `git diff --diff-filter=MDR --name-only main -- tests/` no lista nada, salvo las excepciones que
  el plan declare una a una con su motivo (ninguna prevista).
  - Request: derived: «ningún test existente se debilita»; una aserción relajada sigue pasando la suite, así que hace falta mirar el diff
  - Verify: cmd git diff --diff-filter=MDR --name-only main -- tests/
- **REQ-031** — `recompute-cost` da proyecto a toda fila de la ventana con `caller_session_key`
  cuya sesión tenga su transcript principal vivo en un solo directorio, aunque su cruce sea
  `no_match`: una fila del mod (`toolu_plugin_…`) con clave de sesión acaba con `caller_project` y
  `caller_project_kind` en su entrada, sin que cambie su `match`. Se queda sin ellos una fila sin
  clave, la de una sesión que no se encuentra, la de una sesión que está en más de un directorio,
  y la que tiene a la vez cruce y clave de sesión con proyectos distintos (D14).
  - Request: derived: decisión D10; las filas del mod no tienen `tool_use` en el transcript y sin este camino se quedarían `unknown` (169 en el recuento de la revisión 1)
  - Verify: test tests/test_backfill_project.py
- **REQ-032** — La respuesta de `hook classify` no cambia: ni el daemon ni el proceso añaden
  campos, y `tests/test_hook_classify_endpoint.py`, que exige el mismo JSON byte a byte por los
  dos caminos, pasa sin tocar.
  - Request: derived: decisión D13; la respuesta de `classify` tiene que salir idéntica por el daemon y por el proceso de respaldo
  - Verify: cmd uv run --locked pytest tests/test_hook_classify_endpoint.py

## Acceptance scenarios

### Scenario: delegación desde el propio repo

- **Given** una sesión de Claude Code abierta en el repo, con los hooks instalados
- **When** el modelo llama a una tool `local_*`
- **Then** la fila lleva `caller_project` (16 hexadecimales) y `caller_project_kind: "self"`, el
  panel no la cuenta por defecto y `excluded_self` sube en 1

### Scenario: delegación desde otro proyecto

- **Given** una sesión abierta en un directorio cuyo nombre no contiene el del repo
- **When** un subagente de esa sesión llama a una tool `local_*`
- **Then** la fila lleva `caller_project_kind: "other"` con el hash del proyecto de la sesión
  principal, cuenta en el panel y suma en `subagent_calls`

### Scenario: fila del mod

- **Given** una fila con `tool_use_id` `toolu_plugin_…` y `caller_kind: "main"`
- **When** el panel agrega el rango
- **Then** suma en `mod_calls` y no en `main_calls`

### Scenario: decisión del mod de lectura

- **Given** una sesión abierta en el repo y el mod de lectura que registra una decisión
- **When** `hook record-read` escribe la línea, por el daemon o por el proceso de respaldo
- **Then** la línea lleva `project_kind: "self"` y el mismo `project` que las filas del log de esa
  sesión

### Scenario: fila vieja o de otro cliente

- **Given** una fila sin `caller_project_kind` (anterior al cambio, de Codex o del chat)
- **When** se agrega con el filtro por defecto
- **Then** se cuenta, suma en `unknown_project` y, si su hilo no es un dato real, en
  `unknown_caller_calls`

### Scenario: histórico tras actualizar

- **Given** un log con filas del propio repo escritas antes del cambio
- **When** se abre el panel sin haber corrido `recompute-cost`
- **Then** `excluded_self` es 0 y esas filas cuentan en `unknown_project`; tras correr
  `recompute-cost`, las que tienen cruce real o clave de sesión se apartan

### Scenario: barra de estado del mod dentro del repo

- **Given** una sesión `self` con una delegación
- **When** el mod pide `/api/stats?session=<id>` sin parámetros nuevos
- **Then** `total.calls` es 1

## Edge cases and failure behavior

- `transcript_path` ausente, fuera de la raíz de proyectos o sin `.jsonl`: ningún campo. Nada se
  deriva del `cwd`.
- Sal ilegible o imposible de crear o reparar: solo el tipo; el fallo no se guarda en caché, se
  vuelve a intentar en la siguiente llamada.
- Fichero de sal vacío o inválido que ya existía (un proceso que murió a medias, o una copia
  rota): se repara; no se queda el hash perdido en silencio.
- Otro proceso creó la sal antes: se usa la suya; nunca se pisa una sal válida.
- Sal perdida y creada de nuevo: los grupos por hash se parten en dos; el tipo no cambia.
- `self-projects.json` ausente, ilegible, de más de 64 KiB, con otra forma, con entradas vacías,
  cortas o que no son texto: lo que no vale se ignora y el tipo sale solo por el nombre del repo;
  su contenido nunca se registra, ni en el log ni en un mensaje de error.
- Entrada que casa con un tramo de un proyecto ajeno (`api` con `D--work-api`): ese proyecto sale
  `self`. Es el límite de la regla por tramos; la documentación recomienda entradas con ruta.
- Nombre de directorio con letras fuera de ASCII: las dos partes de la comparación se normalizan
  igual, así que el resultado no depende de cómo las escriba Claude Code; el hash se calcula sobre
  el nombre tal cual, en minúsculas.
- Raíz de proyectos lenta o muy grande: pasado el tope de 50 ms, la línea del mod sale sin
  proyecto; el resultado no se guarda en caché y la siguiente decisión lo vuelve a intentar.
- Lista editada con el daemon en marcha: el daemon sigue con la anterior hasta reiniciarse; los
  hooks, que son un proceso por evento, ven la nueva al momento. Filas y entradas ya selladas no
  cambian de tipo.
- Dos procesos que resuelven `LOG_DIR` distinto (`LOCAL_DELEGATE_LOG_DIR` solo en uno): sal y
  lista distintas; hashes y, para un clon con otro nombre, tipos distintos entre filas y eventos.
  Es el mismo requisito que ya tienen el log y el interruptor; queda documentado (REQ-025).
- Valor de `caller_project_kind` o `project_kind` que no es `self` ni `other`: `unknown`.
- Fila que es prueba y además `self`: la aparta la regla de pruebas, cuenta en `excluded_tests` y
  en `self_in_range`, no en `excluded_self`.
- `include_self` con cualquier valor que no sea `1` o `true`: apagado, como `include_tests`.
- Subagente aislado en un worktree: la fila lleva el proyecto de la sesión principal.
- Petición que entra al daemon desde otra máquina: la nota no es legible aquí; `unknown`.
- `session_id` de la línea del mod con otra forma que UUID, vacío o ausente: la línea sale sin
  proyecto. Si Claude Code cambiara la forma de sus ids, la línea del mod se quedaría sin proyecto
  sin error: T8 comprueba la forma contra los nombres reales de transcript.
- Id de sesión en más de un directorio de proyecto, o cruce y clave de sesión con proyectos
  distintos: sin proyecto (D14).
- Fichero fijo de `LOCAL_DELEGATE_LOG`: mismo comportamiento que con la rotación mensual.

## Non-functional requirements

- Privacidad: los campos nuevos solo llevan hash con sal y tipo. **El log ya guarda rutas en claro
  en el campo `path` de casi todas las filas y eso no cambia**: esta garantía cubre los campos
  nuevos, no vuelve anónimo el log. La nota temporal del hook sigue guardando `transcript_path`
  diez minutos, como hoy. El hash protege frente a quien solo ve el log; quien tenga además
  `project-salt` puede confirmar un nombre por fuerza bruta. `self-projects.json` contiene nombres
  o rutas del usuario: vive en `LOG_DIR`, nunca se copia a un log y no se comparte.
- Seguridad: la sal se crea con permisos solo del usuario; la lista se valida al leerla y tiene
  tope de tamaño; el `session_id` del mod se valida antes de formar una ruta; ni `LOG_DIR` ni la
  raíz de proyectos salen nunca del entorno de una petición; ninguna ruta personal queda cableada en el código ni en los tests.
- Rendimiento: en el servidor, sin lecturas de disco nuevas por llamada (sal y lista, una vez por
  proceso y por ruta) y dentro del presupuesto de 50 ms de `attribution`. En los hooks, cada
  evento es un proceso: una lectura de la sal (64 bytes) y de la lista (64 KiB como mucho) por
  evento. La primera `record-read` de cada sesión en cada proceso recorre los directorios de
  proyecto (unos 40 en esta máquina) con un tope de 50 ms; las siguientes de la misma sesión salen
  de la caché. El tiempo medido se anota en `verification.md`.
- Compatibilidad: campos aditivos y omitidos cuando no aplican; `attribution-AAAAMM.json` sigue en
  versión 1; `/api/events` sirve las filas tal cual, con el hash; la respuesta de `hook classify`
  no cambia; ningún lector existente cambia de resultado con filas viejas. Cada máquina (PC y Mac)
  tiene su `LOG_DIR`, su sal y su lista: los hashes no son comparables entre máquinas y no hace
  falta que lo sean; la regla por nombre vale en las dos.
- Operabilidad: la lista no necesita variable ni que el daemon herede el entorno del lanzador;
  basta con que todos los procesos resuelvan el mismo `LOG_DIR`, como ya exigen el log y el
  interruptor. Para quien instale el paquete sin tener el repo, todo es `other` o `unknown` y el
  filtro no quita nada. El histórico solo se aparta después de correr `recompute-cost`.
- Los scripts de hook con huella de versión (`suggest_delegate_read.py`,
  `suggest_delegate_shell.py`, `suggest_delegate_prompt.py`) y `read_classifier.py` no cambian de
  contenido: no se abre un tramo nuevo de medición.

## Non-goals

- Quitar, hashear o recortar el campo `path` del log.
- Estimar el proyecto de una fila sin cruce ni clave de sesión a partir de su `path`.
- Reescribir filas ya escritas en `usage-AAAAMM.jsonl`, o volver a tipar filas ya selladas cuando
  cambia la lista.
- Lanzar `recompute-cost` de forma automática en `update` o al arrancar el daemon: queda anotado
  como trabajo aparte; aquí solo se documenta que hay que correrlo.
- Un comando para editar `self-projects.json`: se edita a mano, como `read-hook.json`.
- Un desglose por proyecto (por hash) en el panel.
- Proyecto para Codex, opencode, el chat o cualquier cliente sin hooks.
- Hashes comparables entre máquinas, o entre el daemon y un cliente remoto.
- Un chequeo de `doctor` para la sal, la lista o un `LOG_DIR` distinto entre procesos.
- Cambiar los agregados de `recompute-cost`, la cuota o la regla de pruebas.
- Cambiar el mod (JS), su lista de variables, `CLASSIFY_ENV`, `RECORD_ENV` o la respuesta de
  `hook classify`.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
