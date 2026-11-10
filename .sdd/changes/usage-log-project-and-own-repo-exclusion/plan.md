# Implementation plan: Log de uso con proyecto (hash y tipo) y mediciones que apartan el propio repo

## Approach

El dato entra por donde ya entra la atribución: `attribution.resolve_call` devuelve dos campos más
y `server._log_event` los copia sin cambiar (`rec.update(attribution.current_call())`). Por eso
`server.py` no se toca para la fila; solo entra por `local_status`.

- **Reglas puras, en `hook_common.py`**, porque también las usan los hooks, que son stdlib y no
  importan el paquete: `project_identity` (nombre del directorio de proyecto → hash con sal y
  tipo), `project_of_session` (id de sesión validado → el único `<raíz>/*/<id>.jsonl`, o nada), la
  lectura, creación y reparación de la sal y la lectura de la lista `self-projects.json`, las dos
  en `LOG_DIR`. `attribution.py` las reexporta, como ya hace con `session_key`. `LOG_DIR` sale de
  `hook_common.log_dir()`, que lee `os.environ` del proceso y no `current_environ()`: dentro de
  `run_with_environ` con el entorno que manda el mod sigue viendo el del daemon (D12). Los scripts
  y `recompute-cost` pasan `config.LOG_DIR`, que se resuelve con la misma regla.
- **Por qué un fichero y no una variable** (D12): el proyecto lo resuelven el daemon, el servidor
  stdio, cada hook, el respaldo de `record-read`, `recompute-cost` y los dos scripts, con tres
  entornos distintos (daemon, lanzador de Claude Code, terminal). Todos resuelven ya el mismo
  `LOG_DIR` para el log, la sal y el interruptor `read-hook.json`; un fichero ahí se lee igual en
  todos, una variable no. No queda ningún camino que no pueda leerlo: el único caso de discrepancia
  es un `LOG_DIR` distinto entre procesos, que ya rompe el log y queda documentado (REQ-025).
- **Dos reglas únicas más en `attribution.py`**, junto a `test_reason` e `is_mod_call`:
  `project_kind(row)` (`self`, `other`, `unknown`) y `caller_column(row)` (`mod`, `main`,
  `subagent`, `unknown`). Panel, `local_status` y scripts las llaman; nadie decide por su cuenta.
  La regla de proyecto va en su propio `try` dentro de `resolve_call`: el `try` general de
  `_log_event` (`server.py:1417-1428`) salvaría la fila, pero perdería todos los `caller_*`.
- **El relleno** lleva el proyecto en `transcripts.Delegation` y `entry_for` para todo cruce real,
  `cost.BACKFILL_FIELDS` crece con los dos campos, y `attribution.write_backfill` gana la regla
  «mismo rango: añadir los campos de proyecto que falten, sin tocar ningún otro». Además,
  `transcripts.read` construye, con los transcripts principales que ya recorre, un índice
  `clave de sesión → directorio de proyecto` que marca como ambigua la clave que aparece en más de
  un directorio; `match_lines` da proyecto con él a toda fila con `caller_session_key`, también a
  las `no_match` (el mod), y no lo da si la clave es ambigua o si su proyecto y el del cruce no
  coinciden (D10, D14).
- **El panel** filtra en la costura que ya aparta las pruebas (`_usage_rows`), con el interruptor
  «Pruebas» como molde: parámetro `include_self`, contadores, estado en `localStorage`, las tres
  peticiones con el mismo conjunto. Con `session=` el filtro no se aplica. El coste recibe las
  filas ya sin `self`, sin tocar `valuation.py`.
- **La telemetría de hooks** gana el dato en `context_of`, que reciben todos los eventos de los
  hooks con la entrada completa: sale del `transcript_path`, nunca del `cwd`. La línea del mod no
  trae `transcript_path`: `record_decision` llama a `context_of` solo con `session_id`
  (`suggest_delegate_read.py:463-467`, `suggest_delegate_shell.py:160-165`) y esos dos scripts no
  se tocan. Por eso `hook_entry.record_read` resuelve el proyecto con `project_of_session` sobre el
  `session_id` de la entrada (`mod/read.js:643`) y lo pasa por una variable de contexto de
  `hook_common`, como ya se hace con `_RECORD_STRICT` (`hook_common.py:288-304`); `context_of` lo
  añade cuando su entrada no trae `transcript_path`. El mod no cambia.
- **Camino descartado para el mod** (D13): añadir `project` a la respuesta de `hook classify`
  desde el `cwd`. Esa respuesta tiene que ser idéntica por el daemon y por el proceso de respaldo
  (`tests/test_hook_classify_endpoint.py:177-198` lanza el CLI con otro `LOCAL_DELEGATE_LOG_DIR`
  que el del daemon de test y compara los bytes); con la sal de cada proceso el hash saldría
  distinto según quién contestara. Tomar la sal del `LOCAL_DELEGATE_LOG_DIR` de la petición
  permitiría crear `project-salt` en cualquier directorio, la clase de fallo cerrada en la 0.41.1
  (`web/metrics.py:1207-1212`). Y el hash del `cwd` difiere del de la fila con un subdirectorio o
  un worktree. `classify_text` no se toca (REQ-032).
- **Los scripts** aplican las mismas reglas; `measure_adoption.py` resuelve los eventos viejos con
  `project_of_session`, con un índice hecho una vez sobre la raíz de proyectos.

Tests nuevos en ficheros nuevos: ningún fichero existente de `tests/` se edita (REQ-030).

## Ordered tasks

Orden: T1 y T2 a la vez; después T3 y T8 a la vez; después, con T1 cerrada, T4, T5, T6, T7 y T9 a
la vez; T10 y, al final, T11. Los comandos pesados (pytest, `ruff`, build, navegador, el relleno)
van de uno en uno en toda la máquina, con el cerrojo de comandos pesados, y `pytest` con `-n 2`.

- [x] T1 — Instantánea y línea base de cifras, con `main` (REQ-027)
  - Files or modules: `.sdd/changes/usage-log-project-and-own-repo-exclusion/verification.md` (tabla antes/después; solo recuentos, sin rutas ni contenido). La instantánea vive en un directorio temporal fuera del repo y se borra en T11
  - Verification: copiar `LOG_DIR` y el fichero de telemetría de hooks a un directorio temporal; fijar y anotar un instante `now` y un rango `from`/`to` que acabe antes de `now`; con el código de `main` y `LOCAL_DELEGATE_LOG_DIR` y `LD_HOOK_TELEMETRY_LOG` apuntando a la copia, llamar a `recompute.run(claude_dir, copia, now=now)` (el comando `recompute-cost` no tiene `--now`, la función sí) y anotar las cifras de «Tabla antes/después». El log real no se toca
  - Depends on: none
- [x] T2 — Reglas puras de proyecto, sal y lista de extras (REQ-001, REQ-002, REQ-003)
  - Files or modules: `src/local_delegate/resources/hooks/hook_common.py` (sección nueva: `project_identity`, `project_of_session`, sal y lista; no toca `context_of`), `tests/test_project_identity.py` (nuevo)
  - Verification: tests unitarios de hash, tipo y lista (ausente, rota, con otra forma, de más de 64 KiB, entradas cortas). Regla por tramos: `app` no marca `webapp` ni `happy` y sí `D--work-app`; una entrada con ruta casa con su directorio, un subdirectorio y un worktree; un nombre con `ñ` (`Diseño`) se normaliza a `dise-o` en las dos partes. Sal: creación atómica con contenido (temporal en el mismo directorio y enlace al nombre final, que falla si ya existe), reparación bajo cerrojo de un fichero vacío o inválido, y caché con clave por ruta para la sal y para la lista, porque la suite cambia `LOCAL_DELEGATE_LOG_DIR` en cada test (`tests/conftest.py:62`). La carrera se prueba de forma determinista: el fichero ya existe con contenido válido, la función lo devuelve y no lo pisa; sin procesos reales. `project_of_session`: id con forma de UUID, id con separadores o `..`, sesión en dos directorios, sesión inexistente; raíz de proyectos sacada de `Path.home()` del proceso (como `attribution._projects_root`), nunca de `current_environ()`; tope de 50 ms con un recorrido doblado que tarda; caché por `session_id` del resultado encontrado o ambiguo, no del «no encontrado» ni del tope agotado. Importar `hook_common` como módulo suelto, sin el paquete. Anotar en `verification.md` que todos los nombres de transcript principal de esta máquina tienen forma de UUID (solo recuento)
  - Depends on: none
- [x] T3 — Atribución: campos al momento, reglas de tipo y de columna, enriquecimiento del relleno (REQ-004, REQ-006, REQ-007, REQ-008, REQ-023)
  - Files or modules: `src/local_delegate/attribution.py`, `tests/test_usage_log_project.py` (nuevo), `tests/test_caller_column.py` (nuevo)
  - Verification: filas escritas con nota de principal, de subagente y de mod por los cuatro caminos de `_log_event`; regla que lanza (la fila conserva los demás `caller_*`); espía sobre `builtins.open`, `os.stat`, `os.scandir` y `os.listdir` durante `resolve_call` (`Path.exists` e `is_dir` acaban en `os.stat`), con la sal y la lista ya en caché, que compara las rutas tocadas con las de hoy; nota con el formato de hoy; `write_backfill` del mismo rango para `exact`, `window` y `no_match`, y rango menor contra mayor
  - Depends on: T2
- [x] T4 — Proyecto en el relleno, por cruce y por clave de sesión (REQ-007, REQ-031)
  - Files or modules: `src/local_delegate/transcripts.py`, `src/local_delegate/cost.py`, `src/local_delegate/recompute.py`, `tests/test_backfill_project.py` (nuevo)
  - Verification: `recompute.run` sobre un mundo de test deja el proyecto en entradas `exact`, `window` y `window+path`, y en una fila del mod `no_match` con clave de sesión; no lo deja con la sesión en dos directorios ni con cruce y clave en proyectos distintos; `cost.merge` lo pone en la fila; la segunda pasada enriquece sin perder campos. Datos fijados: la entrada vieja trae un `n` distinto del que recalcula la pasada nueva (si no, «sustituir» y «añadir» dan lo mismo). Los tests de `recompute`, `transcripts`, `density` y `valuation` pasan sin tocar. Anotar en `verification.md` cuántas filas del mod de la instantánea recuperan proyecto
  - Depends on: T1, T3
- [x] T5 — Panel entero, Python y JS, un solo dueño (REQ-009, REQ-010, REQ-011, REQ-012, REQ-013, REQ-014, REQ-015)
  - Files or modules: `src/local_delegate/web/metrics.py` (sin tocar los endpoints `/api/hook/*`), `src/local_delegate/resources/i18n/es/panel.json`, `src/local_delegate/resources/i18n/en/panel.json`, `scripts/dev/capture_dashboard.py`, `tests/test_metrics_own_repo.py` (nuevo), `tests/test_dashboard_own_repo.py` (nuevo: `buildQuery` con node y el interruptor en navegador). `tests/panel_server.py` se usa tal cual, no se edita
  - Verification: tests de API y de navegador; `buildQuery` gana un cuarto parámetro opcional, así que los tests de hoy con tres argumentos siguen valiendo; capturas en claro y oscuro. Datos fijados: el test del coste lleva una fila `self` valorable (cliente Claude Code, con modelo y agregados), para que haya algo que baje; el de los contadores lleva una fila que es a la vez prueba y `self`, para que `excluded_self` y `self_in_range` puedan diferir
  - Depends on: T1, T3
- [x] T6 — `measure_adoption.py`: filtro, eventos viejos y columnas (REQ-017, REQ-018)
  - Files or modules: `scripts/measure_adoption.py`, `tests/test_measure_adoption_own_repo.py` (nuevo)
  - Verification: mundo de test con una sesión `self` y otra ajena, eventos con y sin `project_kind`, filas de uso de los tres hilos, y `--include-self`; los 16 tests de hoy pasan sin tocar. Opción nueva: `--projects`. No hace falta tope superior ni `--log-dir`: el script lee `LOCAL_DELEGATE_LOG_DIR` y `LD_HOOK_TELEMETRY_LOG`, y para la tabla antes/después se mide sobre la instantánea, que no crece
  - Depends on: T1, T3
- [x] T7 — `measure_plugin_adoption.py`: sesiones del propio repo y tres columnas (REQ-019, REQ-020)
  - Files or modules: `scripts/measure_plugin_adoption.py`, `tests/test_measure_plugin_adoption_own_repo.py` (nuevo)
  - Verification: `pct` 0,0 por defecto y 50,0 con `--include-self`; columnas de subagentes y mod; los 7 tests de hoy pasan sin tocar
  - Depends on: T1, T3
- [x] T8 — Proyecto en la telemetría de hooks y en la línea del mod (REQ-016, REQ-032)
  - Files or modules: `src/local_delegate/resources/hooks/hook_common.py` (solo `context_of` y la variable de contexto; mismo fichero que T2, por eso va después), `src/local_delegate/hook_entry.py` (solo `record_read`), `tests/test_hook_project.py` (nuevo). En el daemon `hook_common` está cargado dos veces, como módulo suelto (`hook_entry._load_hook_module`, el que importan los scripts) y como módulo del paquete (el de `attribution`), cada uno con su variable de contexto y su caché: `record_read` pone la variable en la instancia suelta, la misma que devuelve `_load_hook_module("hook_common")` y que leen `record_decision` y `context_of`. No toca `classify_text`, `suggest_delegate_read.py`, `suggest_delegate_shell.py`, `suggest_delegate_prompt.py`, `read_classifier.py`, el mod (`mod/*.js`), `CLASSIFY_ENV`, `RECORD_ENV` ni `web/metrics.py`
  - Verification: evento de cada hook con `transcript_path`, y sin él (con `cwd`) sale sin campos; línea del mod por `record_read` con la raíz de proyectos de un mundo de test: mismo `project` que la fila de esa sesión; `session_id` inválido, ausente o en dos directorios: sin campos; regla que lanza en `context_of` y en `record_read`; `record_read` dentro de `run_with_environ` con un `LOCAL_DELEGATE_LOG_DIR` de la petición distinto: no crea nada ahí y usa la sal del proceso; con un `HOME` y un `USERPROFILE` de la petición que apuntan a otra raíz con la misma sesión: recorre la raíz del proceso y el hash es el de la fila; por `POST /api/hook/record-read`, el campo escrito en la línea demuestra que la variable llegó a la instancia suelta; anotar en `verification.md` el tiempo medido de la búsqueda sobre la raíz real (solo la cifra). `tests/test_hook_boundaries.py`, `tests/test_hook_common.py`, `tests/test_hook_classify_endpoint.py`, `tests/test_hook_record_read_endpoint.py`, `tests/test_telemetry_concurrent_writes.py` y `tests/test_mod_static.py` pasan sin tocar
  - Depends on: T2
- [x] T9 — `local_status`: recuento del propio repo (REQ-021)
  - Files or modules: `src/local_delegate/server.py` (solo `local_status`), `src/local_delegate/resources/i18n/es/mcp.json`, `src/local_delegate/resources/i18n/en/mcp.json`, `tests/test_status_own_repo.py` (nuevo)
  - Verification: mes con filas `self`, `other` y sin tipo: las cifras de hoy no cambian y aparece la línea; mes sin `self`: no aparece
  - Depends on: T1, T3
- [x] T10 — Documentación y guardianes compartidos (REQ-024, REQ-025, REQ-029)
  - Files or modules: `CHANGELOG.md`, `README.md`, `docs/wiki/Savings-and-metrics.md`, `docs/wiki/Configuration.md`, `scripts/data/spanish_lexicon.json`
  - Verification: guardianes de texto y de catálogos; revisión de los tres sitios contra la lista de REQ-025 y el aviso del corte de 90 días de REQ-029. Las demás tareas no tocan estos ficheros: entregan a T10 las palabras y los textos que necesitan. Todo texto nuevo va al catálogo; `tests/data/uncatalogued_exceptions.json` no se toca. Si una excepción resultara inevitable, se escala con su motivo y se declara una a una como excepción de REQ-030
  - Depends on: T4, T5, T6, T7, T8, T9
- [x] T11 — Integración y verificación de conjunto (REQ-005, REQ-015, REQ-022, REQ-026, REQ-027, REQ-028, REQ-030, REQ-032)
  - Files or modules: `tests/test_project_privacy.py` (nuevo), `.sdd/changes/usage-log-project-and-own-repo-exclusion/verification.md`
  - Verification: test de privacidad de punta a punta; suite completa; `tests/test_hook_classify_endpoint.py` sin tocar; `git diff --diff-filter=MDR --name-only main -- tests/` vacío; mutantes; tabla «después» sobre la instantánea de T1, con el mismo `now` y el mismo rango; prueba en vivo; capturas; borrar la instantánea
  - Depends on: T1, T10

## Test strategy

- Unit: `project_identity` (hash, tipo, lista, sal), `project_of_session`, `project_kind`,
  `caller_column`, `write_backfill` del mismo rango, `buildQuery` con node.
- Integration: filas reales por `_log_event` con notas en un directorio temporal; `recompute.run`
  y `cost.merge` sobre un mundo de test; `/api/stats`, `/api/events` y `/api/hooks` con el servidor
  de test del panel; los dos scripts sobre mundos de test con raíz de proyectos y logs temporales;
  `record_read` por el CLI y por `POST /api/hook/record-read` con una raíz de proyectos de test.
  Todo con `LOG_DIR` y log temporales y los helpers de aislamiento de entorno de la suite: ninguna
  prueba escribe en el log real.
- End-to-end or manual: navegador para el interruptor (como
  `test_the_tests_switch_requests_all_three_with_the_parameter`); capturas del panel en claro y
  oscuro; prueba en vivo con el daemon instalado, que hace la sesión principal.
- Security and secret scanning: `personal-security-check` antes de cada commit; el test de
  privacidad con nombre marcador; ningún nombre de usuario ni ruta personal en tests, fixtures ni
  documentación; test de privacidad con una entrada marcadora en `self-projects.json` (REQ-005).

### Control positivo (REQ-028)

Un mutante por criterio. Cada uno se aplica solo, se comprueba que cambia el comportamiento con
los datos de su test y se anota en `verification.md` qué aserción dispara. Si falla por otra
aserción, o no falla, el test se corrige. Ficheros: PI `tests/test_project_identity.py`, UL
`tests/test_usage_log_project.py`, PP `tests/test_project_privacy.py`, CC
`tests/test_caller_column.py`, BP `tests/test_backfill_project.py`, MO
`tests/test_metrics_own_repo.py`, DO `tests/test_dashboard_own_repo.py`, HP
`tests/test_hook_project.py`, HC `tests/test_hook_classify_endpoint.py` (existente, sin tocar),
MA `tests/test_measure_adoption_own_repo.py`, MP `tests/test_measure_plugin_adoption_own_repo.py`,
ST `tests/test_status_own_repo.py`, NT `tests/test_no_uncatalogued_text.py`.

| N.º | Requisito | Mutante | Test | Aserción que debe disparar |
| ---: | --- | --- | --- | --- |
| 1 | REQ-001 | El hash ignora la sal | PI | dos sales dan hashes distintos |
| 2 | REQ-001 | El hash ignora el nombre | PI | dos nombres dan hashes distintos |
| 3 | REQ-001 | Se acepta una ruta fuera de la raíz de proyectos | PI | una ruta no válida no da ningún campo |
| 4 | REQ-002 | El tipo devuelve siempre `other` | PI | el repo y su worktree dan `self` |
| 5 | REQ-002 | La lista de extras no se lee | PI | un clon con otro nombre da `self` con la lista |
| 6 | REQ-002 | No se ignoran las entradas cortas | PI | una entrada de menos de 3 caracteres no marca nada como `self` |
| 7 | REQ-002 | Una lista rota lanza | PI | con el fichero roto el repo sigue dando `self` y no hay excepción |
| 7a | REQ-002 | La coincidencia vuelve a ser por subcadena | PI | la entrada `app` no marca `webapp` |
| 7b | REQ-002 | Una entrada con ruta no casa con lo que cuelga de ella | PI | el worktree y el subdirectorio de la ruta dan `self` |
| 7c | REQ-002 | La normalización conserva `ñ` y tildes | PI | `Diseño` en la lista casa con el directorio `D--dise-o` |
| 7d | REQ-002 | Sin tope de tamaño | PI | un fichero de más de 64 KiB no marca nada como `self` |
| 8 | REQ-003 | La creación sobrescribe una sal válida | PI | el contenido que ya había no cambia y es el que se devuelve |
| 9 | REQ-003 | Sin sal se escribe un hash sin sal | PI | sin sal no hay `caller_project` y sí `caller_project_kind` |
| 10 | REQ-003 | Un fichero de sal vacío no se repara | PI | tras la llamada hay una sal válida y un hash |
| 11 | REQ-003 | La sal se lee en cada llamada | PI | la segunda llamada no abre el fichero |
| 12 | REQ-003 | La caché no va por ruta | PI | dos `LOG_DIR` dan sales distintas |
| 13 | REQ-004 | `resolve_call` no añade los campos | UL | la fila lleva los dos campos |
| 14 | REQ-004 | El subagente usa su propio directorio | UL | el hash es el de la sesión principal |
| 15 | REQ-004 | Se sella aunque la nota esté caducada | UL | con la nota caducada no hay ningún campo |
| 16 | REQ-005 | El campo guarda el nombre en claro | PP | el marcador no aparece en `json.dumps` |
| 16a | REQ-005 | La fila o la respuesta guarda la entrada de la lista que coincidió | PP | la entrada marcadora no aparece en la fila, el relleno, el evento, `local_status` ni `/api/*` |
| 17 | REQ-006 | Se quita el `try` propio de la regla | UL | la fila conserva los demás `caller_*` |
| 18 | REQ-006 | La regla comprueba en disco que el directorio del proyecto existe (`Path.exists`) | UL | el espía de `open`, `os.stat`, `os.scandir` y `os.listdir` no ve rutas nuevas |
| 19 | REQ-007 | `write_backfill` no enriquece el mismo rango | BP | la entrada previa `exact` y la `window` acaban con proyecto |
| 20 | REQ-007 | `write_backfill` sustituye en vez de añadir | BP | el `n` de la entrada vieja sigue intacto |
| 21 | REQ-007 | `BACKFILL_FIELDS` sin los campos nuevos | BP | la fila fundida trae el tipo |
| 22 | REQ-007 | `entry_for` solo da proyecto a `exact` | BP | una entrada `window` nueva trae proyecto |
| 23 | REQ-007 | Un rango menor enriquece a uno mayor | BP | la `exact` no cambia ante una `window` |
| 24 | REQ-031 | No se usa la clave de sesión | BP | la fila del mod `no_match` acaba con proyecto |
| 25 | REQ-031 | La clave de sesión reescribe el `match` | BP | el `match` sigue siendo `no_match` |
| 26 | REQ-031 | Con cruce y clave en proyectos distintos gana uno | BP | la entrada sale sin proyecto |
| 27 | REQ-031 | El índice se queda con el primer directorio de una sesión repetida | BP | la fila de esa sesión sale sin proyecto |
| 28 | REQ-008 | `caller_column` mira `caller_kind` antes que el mod | CC | la fila del mod da `mod` |
| 29 | REQ-008 | `caller_column` da por bueno el respaldo | CC | la fila con hilo de respaldo da `unknown` |
| 30 | REQ-009 | `/api/events` no aplica el filtro | MO | las dos respuestas cuentan el mismo conjunto |
| 31 | REQ-009 | `excluded_self` cuenta también las pruebas ya apartadas | MO | `mostradas + excluded_tests + excluded_self` es el total del rango |
| 32 | REQ-009 | `unknown_project` cuenta también las `other` | MO | `unknown_project` es el número de filas sin tipo |
| 33 | REQ-009 | `include_self=1` se ignora | MO | con el parámetro vuelven todas las filas |
| 34 | REQ-009 | `self_in_range` no cuenta las que son prueba | MO | `self_in_range` incluye la fila `self` que es prueba |
| 35 | REQ-010 | El filtro se aplica también con `session=` | MO | `total.calls == 1` para la sesión `self` |
| 36 | REQ-011 | El coste recibe las filas sin filtrar | MO | el coste baja sin `include_self` |
| 37 | REQ-012 | `/api/hooks` no filtra | MO | por defecto el evento `self` no cuenta |
| 38 | REQ-012 | `/api/hooks` aparta los eventos sin campo | MO | el evento sin `project_kind` se queda |
| 39 | REQ-012 | `/api/hooks` ignora `include_self=1` | MO | con el parámetro el evento `self` cuenta |
| 40 | REQ-013 | `buildQuery` no añade el parámetro | DO | las tres peticiones llevan `include_self=1` |
| 41 | REQ-013 | El estado del interruptor no se guarda | DO | tras recargar sigue encendido |
| 42 | REQ-014 | Una columna no se cuenta | MO | la suma de las cuatro es `calls` |
| 43 | REQ-016 | `context_of` sin proyecto | HP | el evento del hook lleva `project_kind` |
| 44 | REQ-016 | `context_of` deriva el proyecto del `cwd` | HP | el evento sin `transcript_path` y con `cwd` sale sin los dos campos |
| 45 | REQ-016 | `record_read` no resuelve por `session_id` | HP | la línea del mod lleva el mismo `project` que la fila de su sesión |
| 46 | REQ-016 | `project_of_session` no valida el id | HP | un id con `..` o separadores no da proyecto ni toca rutas fuera de la raíz |
| 47 | REQ-016 | `project_of_session` se queda con el primero de dos directorios | HP | la línea de esa sesión sale sin proyecto |
| 48 | REQ-016 | Se quita el `try` de `context_of` y de `record_read` | HP | el evento y la línea se escriben aunque la regla lance |
| 49 | REQ-016 | La sal y la lista salen del `LOG_DIR` de la petición | HP | no se crea ningún fichero en el directorio de la petición y el hash es el de la fila |
| 49a | REQ-016 | La raíz de proyectos sale de `current_environ()` | HP | con otro `HOME` y `USERPROFILE` en la petición, se recorre la raíz del proceso y el hash es el de la fila |
| 49b | REQ-016 | La variable de contexto se pone en la instancia del paquete | HP | la línea escrita por `POST /api/hook/record-read` lleva `project_kind` |
| 49c | REQ-016 | La búsqueda no tiene tope | HP | con un recorrido doblado que tarda más de 50 ms, la línea sale sin proyecto dentro del tope |
| 49d | REQ-016 | Sin caché por `session_id` | HP | la segunda decisión de la misma sesión no vuelve a recorrer la raíz |
| 49e | REQ-016 | La caché guarda también el «no encontrado» | HP | una sesión que aparece después de la primera búsqueda se encuentra en la segunda |
| 50 | REQ-032 | `classify_text` añade `project` a su respuesta | HC | `test_classify_matches_the_real_cli_process`: `response.content == expected` |
| 51 | REQ-017 | No se filtran los eventos de hooks | MA | las lecturas son solo las de la sesión ajena |
| 52 | REQ-017 | No se filtran las filas del log de uso | MA | `total_delegations` solo cuenta la ajena |
| 53 | REQ-017 | No se resuelven los eventos viejos | MA | el evento viejo de la sesión `self` se aparta |
| 54 | REQ-017 | `--include-self` se ignora | MA | con la opción cuentan las dos sesiones |
| 55 | REQ-018 | `delegations_by_caller` sin el mod primero | MA | la fila del mod suma en `mod` y la suma es `total_delegations` |
| 56 | REQ-018 | `delegations_by_project_kind` cuenta lo desconocido como `other` | MA | la fila sin tipo suma en `unknown` |
| 57 | REQ-019 | No se excluyen las sesiones `self` | MP | `pct` es 0,0 por defecto |
| 58 | REQ-019 | `--include-self` se ignora | MP | `pct` es 50,0 con la opción |
| 59 | REQ-020 | No se miran los transcripts de subagentes | MP | `with_subagent_delegation` es 1 |
| 60 | REQ-020 | El mod no se atribuye por clave de sesión | MP | `with_mod_delegation` es 1 |
| 61 | REQ-020 | `pct` cuenta subagentes o mod | MP | `pct` sale solo del hilo principal |
| 62 | REQ-021 | `local_status` no cuenta el propio repo | ST | aparece la línea con el recuento |
| 63 | REQ-021 | `local_status` resta lo `self` de la cifra | ST | eventos y ahorro son los de hoy |
| 64 | REQ-021 | La línea sale con recuento cero | ST | sin filas `self` no hay línea |
| 65 | REQ-023 | `resolve_call` exige un campo nuevo en la nota | UL | una nota con el formato de hoy basta |
| 66 | REQ-024 | Un texto nuevo del panel sin catalogar | NT | el guardián de textos sin catalogar lo señala |

### Tabla antes/después (REQ-027)

Todo se mide sobre la instantánea de T1, nunca sobre el log vivo: así los eventos que genera la
propia jornada no mueven las cifras entre T1 y T11. Las dos mediciones usan lo mismo:

- **Rango fijo**: `from` y `to` anotados en T1, pasados explícitos a `/api/stats`, `/api/events` y
  `/api/hooks` (sin ellos el panel toma «los últimos 30 días hasta ahora», `web/metrics.py:183-194`).
- **Mismo `now` para el relleno**: `recompute.run(..., now=now)` con el instante de T1; así la
  ventana de retención es la misma en las dos. `measure_plugin_adoption.py` con `--now` igual.
- **`local_status`**: cuenta el mes en curso; se mide con `LOCAL_DELEGATE_LOG` apuntando al
  fichero mensual de la copia que eligió T1, para que T11 lea el mismo fichero aunque caiga en otro
  mes.
- **Entorno**: `LOCAL_DELEGATE_LOG_DIR` y `LD_HOOK_TELEMETRY_LOG` apuntando a la copia; el panel se
  pide a su app en proceso, sin abrir puerto.

1. **Antes (T1)**: código de `main`, relleno sobre la copia, anotar.
2. **Después (T11)**: código nuevo, relleno sobre la misma copia, anotar dos columnas: con el
   propio repo incluido (`include_self=1`, `--include-self`) y por defecto.

Criterios: (a) antes y después-incluido son iguales en toda cifra que ya existía; (b) la columna
por defecto difiere solo en lo que `excluded_self` explica; (c) `excluded_self > 0` en el panel y
en los dos scripts, y el reparto `self` / `other` / `unknown` queda anotado; (d) las cuatro
columnas de hilo suman `calls`. Fuente de diferencia admitida: el relleno lee los transcripts
vivos, que pueden cambiar entre T1 y T11 (sesiones nuevas, limpieza de Claude Code). Si (a) falla
en el coste o en `N`, se repite el relleno de `main` con el mismo `now` sobre una segunda copia de
la instantánea; lo que difiera también ahí es deriva de los transcripts, no del cambio.

| Cifra | Fuente |
| --- | --- |
| `total.calls`, ahorro neto, `mod_calls`, filas de `by_client` | `/api/stats` |
| `count` | `/api/events` |
| lecturas, avisos y bloqueos | `/api/hooks` |
| coste equivalente | `/api/stats` → `cost` |
| eventos y ahorro del mes | `local_status` |
| `reads`, `offered`, `blocks`, `accepted`, `total_delegations`, `sessions` | `scripts/measure_adoption.py --json` |
| `sessions`, `with_delegation`, `pct`, `excluded_rows` | `scripts/measure_plugin_adoption.py` |

### Prueba en vivo (REQ-026)

La hace la sesión principal, con el paquete instalado desde el árbol de trabajo y el daemon
reiniciado (después hay que reconectar el MCP en el cliente). Condición: durante la ventana nadie
más delega (ni otros agentes ni el mod); cada una de las dos sesiones hace una sola delegación, con
`text`, sin leer ficheros grandes.

1. `local-delegate test-window start --label own-repo-live`; anotar el id y el instante de inicio.
2. Una delegación desde una sesión abierta en el repo y otra desde una sesión abierta en otro
   directorio.
3. En el log, las dos filas: `caller_project_kind` `self` y `other`, hashes distintos de 16
   hexadecimales, y ningún campo nuevo con una ruta.
4. `/api/stats` con `from` en el inicio de la ventana e `include_tests=1`: `excluded_self == 1` y
   `total.calls == 1`; con `include_self=1` además, `total.calls == 2`.
5. `/api/stats?session=<id de la sesión del repo>&include_tests=1`: `total.calls >= 1` y
   `excluded_self == 0`. Es lo que pediría la barra del mod; la barra misma no sirve de prueba
   aquí, porque no manda `include_tests` y dentro de una ventana de prueba da 0 por esa regla.
6. Si el mod de lectura registró alguna decisión en la sesión del repo, su línea de telemetría
   lleva `project_kind: "self"` y el mismo `project` que la fila del paso 3.
7. `local-delegate test-window stop <id>`; no queda ningún proceso ni espera en marcha.

Si no se puede garantizar la condición, los pasos 4 y 5 se hacen solo con `session=` para cada una
de las dos sesiones y se anota por qué.

## Migration and compatibility

- **Filas viejas sin los campos**: no se migran ni se reescriben; se leen como hoy y cuentan como
  `unknown`. El proyecto les llega por el relleno, **solo al correr `recompute-cost` con la versión
  nueva** (no se lanza solo; hacerlo automático queda fuera de alcance). Cifras de la revisión 1
  sobre esta máquina, de 1.593 filas que no son prueba (cota alta: el recuento no apartó las
  ventanas de prueba): reciben proyecto como mucho 1.413 (986 con id y sin entrada todavía, 71
  `exact`, 187 `window` o `window+path`, 169 del mod por clave de sesión) y se quedan `unknown` al
  menos 180 (8 de Claude Code sin cruce, 11 del chat, 161 de otros clientes sin id). **La causa no
  es la retención** (90 días aquí): es no tener ni cruce ni clave de sesión. Esas 180 siguen
  dentro de los totales por defecto (D11).
- **Corte de 90 días de la medición en curso (2026-12-14)**: se saca con las dos cifras,
  `--include-self` y por defecto. La comparable con los cortes de 14 y 30 días es la primera.
- **Lectores existentes**: todos leen con `dict.get`; los campos son aditivos y
  `legacy_names.normalize` conserva las claves que no conoce. `attribution-AAAAMM.json` sigue en
  versión 1. La respuesta de `hook classify` no cambia. `doctor`, `test-window`, ritmo, lentitud,
  corpus y fronteras de medición no cambian.
- **Versiones cruzadas**: la nota del hook no cambia de formato, así que un hook instalado de una
  versión anterior ya sirve al servidor nuevo. El mod no cambia: uno viejo manda el mismo
  `session_id` a `record-read` y pide `/api/stats?session=` sin parámetros nuevos. Un panel
  abierto con el JS viejo no manda `include_self` y ve el propio repo apartado, con el recuento en
  la respuesta.
- **Mac contra PC**: cada máquina crea su sal y tiene su lista en su `LOG_DIR`; los hashes no se
  comparan entre máquinas. La regla por nombre vale en las dos. La Mac registra en su propio log
  aunque la inferencia corra en la PC. Supuesto sin medir: que Claude Code en macOS nombre sus
  directorios de proyecto y sus transcripts con la misma regla (directorio del `cwd`, id de sesión
  con forma de UUID); se comprueba al actualizar la Mac y, si no se cumple, la línea del mod sale
  sin proyecto, sin error.
- **Cambio visible al actualizar**: los KPI del panel y los porcentajes de los scripts bajan en
  esta máquina, porque el propio repo es la mayoría del uso. Va en el CHANGELOG como cambio de
  comportamiento, con la forma de recuperar la cifra anterior (el interruptor, `--include-self`).
- **Configuración nueva**: el fichero opcional `LOG_DIR/self-projects.json`, documentado en
  `docs/wiki/Configuration.md`; no hay variable de entorno nueva. Sin dependencias nuevas de
  terceros.
- **Riesgos y salvaguardas**:
  - `hook_common.py` lo cargan todos los hooks: un fallo de importación los apaga todos. T2 y T8
    prueban el módulo suelto, y toda la lógica nueva va dentro de `try`.
  - La sal creada a la vez por el daemon y un proceso stdio: creación atómica sin sobrescribir.
  - Tocar `BACKFILL_FIELDS` y `match_lines` alcanza al coste, a los agregados y a `doctor`: los
    tests de hoy de esos módulos pasan sin tocar, y la tabla antes/después incluye el coste.
  - `record_read` forma una ruta con un dato del cliente (`session_id`): se valida con forma de
    UUID antes de usarlo, y la raíz de proyectos es la del proceso.
  - Procesos con un `LOG_DIR` distinto: sal y lista distintas; el filtro mira solo el tipo y la
    documentación dice que todos tienen que resolver el mismo `LOG_DIR`.
  - Un proyecto hermano con el nombre del repo en su ruta saldría `self`: documentado como límite.
- **Vuelta atrás**: revertir el PR. Los campos ya escritos quedan en el log y en el relleno como
  claves que nadie lee; los ficheros `project-salt` y `self-projects.json` se pueden borrar sin
  efecto.

## Plan review

- [ ] Every requirement maps to at least one task and verification step.
- [ ] Risky or destructive operations have safeguards and rollback.
- [ ] Dependencies and configuration changes are explicit.
- [ ] The plan does not include unrelated work.
