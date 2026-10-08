# Implementation plan: Las pruebas fuera de las métricas: ventanas de prueba y una sola regla de exclusión en todo el panel

## Approach

### Diseño

1. **Un módulo nuevo, `src/local_delegate/test_windows.py`** (nombres en inglés), solo stdlib +
   `filelock`:
   - `FILE_NAME = "test-windows.json"`, `OPEN_WARN_HOURS = 12`.
   - `load(log_dir) -> Windows`: lectura tolerante y cacheada por `(mtime, size)` (REQ-003). `Windows`
     guarda la lista ordenada por `start` (ya normalizada a `datetime` UTC truncada/redondeada al
     segundo, REQ-002), las entradas ignoradas y el motivo si el fichero es ilegible.
   - `Windows.find(ts) -> str | None`: id de la primera ventana que contiene `ts` (str o `datetime`).
     Recorrido lineal; búsqueda binaria por `start` si hay más de 200.
   - `start`, `stop`, `add`: leer → cambiar → `tempfile` + `os.replace`, todo bajo
     `FileLock(log_dir / "test-windows.lock", timeout=10)` (REQ-010). Lanzan `TestWindowError` con el
     texto en español; el CLI lo convierte en código 2.
   - `parse_instant(texto) -> datetime`: ISO con o sin zona/milisegundos; sin zona = UTC. Lo usan el
     CLI, los scripts (`--excluir`) y la lectura: una sola copia.
2. **La regla común en `atribucion.py`** (REQ-004): `test_reason(fila, entrada_relleno=None)` y
   `CLIENTES_NO_CLAUDE = {"codex-mcp-client": "no es Claude"}`; `excluida` = no-Claude o
   `test_reason`. `test_reason` mira el banco en `entrada_relleno` y, si no se pasa, en la propia fila
   fundida (`fila.get("banco")`): el panel la llama con un solo argumento. `CLIENTES_EXCLUIDOS` se
   conserva como unión de los dos solo por no cambiar más de lo necesario (hoy lo usa únicamente
   `atribucion.py:333`; ningún test lo lee).
3. **El sello en `coste.fundir`** (REQ-005): carga las ventanas de `log_dir` una vez por llamada y
   pone `test_window` en la copia. Como `_load`, `local_status`, `recalcular` y `checks` ya funden, la
   regla llega a todos sin código propio. El test de `tramo` prueba que una fila con `test_window`
   cae en `excluido`.
4. **El filtro del panel en un solo punto** (REQ-011 a REQ-014): `_load` sigue devolviendo **todas**
   las filas del rango; una función nueva `_split_tests(rows) -> (kept, tests)` separa por
   `atribucion.test_reason`. `/api/events` y `/api/stats` llaman a `_load` y a `_split_tests` igual;
   `_aggregate` y `valoracion.bloque_imagenes` reciben `kept` (o todas con `include_tests=1`), y
   `valoracion.bloque_coste` y `_bloque_cuota` (que llama a `_load` por su cuenta, `metrics.py:520`)
   reciben **siempre** todas (REQ-014). El JS no gana lógica de filtrado: `acct` y `agg` no se tocan, y la
   paridad que hay que atar es otra: que `/api/events` y `/api/stats` cuenten el mismo conjunto (test
   en T4) y que las tres peticiones de `fetchData` lleven el mismo parámetro (test node en T5).
5. **El interruptor** (REQ-016): un `<button id="tests" class="btn">` en `.controls`, con el mismo
   estilo on/off que `#auto`, seguido de un botón ⓘ con `data-group="tests"`; un
   `buildQuery(range, includeTests)` puro (lo prueba node) que usa `fetchData` para las tres
   peticiones; una sección nueva en `infoDlg` cuyo texto arma `textoPruebas(stats)` (pura, la prueba
   node) con `excluded_tests`; y, si D7, el punto de aviso con `open_test_windows`.
6. **CLI** `local-delegate test-window {start,stop,add,list}` con el patrón de
   `_add_llamaswap_parser` (`cli.py:1015`).
7. **Scripts**: `medir_enfriamiento.py` y `medir_adopcion.py` importan `test_windows` y
   `atribucion.test_reason`; `--include-tests`; arreglo de `args.exclude`.

Por qué así: la estimación previa proponía tocar `acct` y `agg`; leído el código, ninguna de las dos
elige filas (las elige `_load` en el servidor), así que meter ahí la regla habría creado una tercera
copia de la misma decisión, que es el defecto recurrente del repo («dos fuentes para el mismo dato»).
Con el filtro en `_load` y el sello en `fundir`, la decisión vive en **un** sitio (`test_reason` +
`test_windows.find`) y todo lo demás la consume.

### Olas

| Ola | Tareas | En paralelo | Por qué ese orden |
|---|---|---|---|
| 0 | T0 | — | Decisiones del usuario, rebase sobre el `metrics.py` del otro agente y línea base |
| 1 | T1 | — | Todos dependen del módulo |
| 2 | T2, T3 | sí (ficheros distintos) | Regla común y CLI solo dependen de T1 |
| 3 | T4, T6, T7 | sí (ficheros distintos) | Dependen de T2 |
| 4 | T5 | — | Mismo fichero que T4 (`web/metrics.py`) |
| 5 | T8 | — | Documenta lo construido |
| 6 | T9 | — | Instala y siembra en esta PC (un recurso único: el daemon) |
| 7 | T10 | — | Verificación final |

Los comandos pesados (pytest, Playwright, `uv tool install`) van **siempre** con
`bash ~/.claude/scripts/pesado.sh <comando>`, de uno en uno en toda la máquina, aunque las tareas
corran en paralelo.

### Propiedad de ficheros

| Fichero | Tarea dueña |
|---|---|
| `src/local_delegate/test_windows.py`, `tests/test_test_windows.py` | T1 |
| `src/local_delegate/atribucion.py`, `src/local_delegate/coste.py`, `tests/test_atribucion.py`, `tests/test_valoracion.py`, `tests/test_recalcular.py` | T2 |
| `src/local_delegate/cli.py`, `tests/test_test_windows_cli.py` | T3 |
| `src/local_delegate/web/metrics.py` (parte Python: `_load` a `hooks`) y `tests/test_metrics.py` | T4 |
| `src/local_delegate/web/metrics.py` (parte `HTML`), `tests/test_dashboard_js.py`, `tests/test_dashboard_ui.py`, `scripts/dev/capture_dashboard.py` | T5 |
| `src/local_delegate/server.py` (`local_status`), `src/local_delegate/checks.py`, `tests/test_core.py`, `tests/test_checks.py`, `tests/test_doctor.py`, `tests/test_wiki.py` (`_NUMERO_DE_CHECKS`), tabla del doctor en `docs/wiki/Integration-install.md` | T6 |
| `scripts/medir_enfriamiento.py`, `scripts/medir_adopcion.py`, `tests/test_medir_enfriamiento.py`, `tests/test_medir_adopcion.py` | T7 |
| `CHANGELOG.md`, `README.md`, `docs/wiki/Savings-and-metrics.md` | T8 |
| `test-windows.json` del `LOG_DIR` real de esta PC; `.sdd/changes/test-windows-out-of-metrics/evidencias/T9.md` y capturas | T9 |
| `.sdd/changes/test-windows-out-of-metrics/verification.md`, `review.md`, `handoff.md` | T10 |

Nadie fuera de su fila toca un fichero; si hace falta, se para y se avisa al orquestador.

### Cómo se escribe el control positivo de cada test

Para cada test nuevo que decide un requisito: (1) se introduce a mano el mutante indicado en la
tarea, (2) se corre el test y se anota **qué assert** falla y con qué mensaje, (3) se comprueba que el
mutante muta (el diff no está vacío y cambia el camino que el test ejerce), (4) se revierte. Se anota
en `evidencias/Tn.md`. Un test que no falla con su mutante no cuenta como prueba del requisito.

## Ordered tasks

### T0 — Arranque, decisiones y línea base (ola 0)

- **Insumos**: esta spec y este plan aprobados; el cambio del otro agente en `web/metrics.py`,
  `tests/test_metrics.py`, `tests/test_dashboard_ui.py` y `tests/test_panel_estados.py`.
- **Criterio de parada**: **T4 y T5 no empiezan** hasta que ese cambio esté mezclado en `main`, esta
  rama rebasada sobre él y los números de línea releídos (paso 2). T1, T2, T3, T6 y T7 no tocan esos
  ficheros y pueden avanzar antes; si el rebase les afecta, se repiten sus tests.
- **Pasos**:
  1. El orquestador pregunta al usuario D1 a D6 (spec, «Decisiones abiertas») y anota la respuesta
     literal en `state.json` con `personal-harness sdd approve … spec`. Si alguna cambia, se edita la
     spec antes de seguir.
  2. `git rebase main` (con el cambio del otro agente ya en `main`). Releer y **actualizar en `research.md`** los números de
     línea de `web/metrics.py` que cite el plan (`_load`, `events`, `stats`, `hooks`, `fetchData`,
     `.controls`, texto del coste, `infoDlg`).
  3. Línea base: `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_metrics.py tests/test_dashboard_js.py tests/test_atribucion.py tests/test_valoracion.py tests/test_recalcular.py tests/test_medir_enfriamiento.py tests/test_medir_adopcion.py tests/test_checks.py tests/test_doctor.py tests/test_core.py -q`.
  4. Reproducir el fallo de `medir_enfriamiento.py` (`AttributeError … 'exclude'`) y guardarlo en
     `evidencias/T0.md`: es el insumo del control de T7.
- **Verificación**: línea base verde, o los rojos anotados como preexistentes; decisiones anotadas.
- **Vuelta atrás**: nada que deshacer (no cambia código).

### T1 — Módulo de ventanas (ola 1)

- **Ficheros**: `src/local_delegate/test_windows.py` (nuevo), `tests/test_test_windows.py` (nuevo).
- **Requisitos**: REQ-001, REQ-002, REQ-003, REQ-010 (la parte del módulo), REQ-025.
- **Tests** (todos con `tmp_path` como `log_dir`):
  - Forma del fichero tras `start`/`stop`/`add` (claves, `Z`, `id` con sufijo al repetirse).
  - Los cinco instantes del escenario «el segundo del borde» (dentro/fuera exactos).
  - Ventana abierta: una marca de «ahora + 1 s» no está, «ahora − 1 s» sí (reloj inyectable).
  - Sin fichero; JSON roto; `version: 2`; entrada sin `start`; `end < start`: `find` no lanza,
    `ignored` y `error` dicen lo correcto.
  - Caché: dos `load` sin cambio devuelven el mismo objeto; tras escribir, el nuevo.
  - Escritura sobre un fichero ilegible: `TestWindowError` y el fichero intacto (mismos bytes).
  - Cerrojo ocupado (otro `FileLock` tomado con `timeout` corto inyectado): `TestWindowError`.
  - Dos `start` desde dos procesos (`multiprocessing`): dos ventanas con ids distintos.
  - `add` repetido: no duplica y devuelve «ya existía».
- **Controles positivos**: mutante `<=` → `<` en el fin (debe fallar el caso `01:22:31`); mutante
  que redondea el fin hacia arriba (`ceil_s(e)`) (debe fallar el caso `01:22:32`, que tiene que
  quedar fuera); mutante que compara cadenas (`str(ts) >= start_str`) (debe fallar el caso
  `01:20:05`); mutante sin `FileLock`
  (debe fallar el test de dos procesos o el de cerrojo ocupado: anotar cuál).
- **Verificación**: `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_test_windows.py -q`;
  `uv run ruff check src/local_delegate/test_windows.py tests/test_test_windows.py`.
- **Vuelta atrás**: borrar los dos ficheros nuevos.

### T2 — La regla común y el sello (ola 2, en paralelo con T3)

- **Ficheros**: `src/local_delegate/atribucion.py`, `src/local_delegate/coste.py`,
  `tests/test_atribucion.py`, `tests/test_valoracion.py`, `tests/test_recalcular.py`.
- **Requisitos**: REQ-004, REQ-005, REQ-014 (parte del coste), REQ-015.
- **Pasos**: `test_reason`, `CLIENTES_NO_CLAUDE`, `excluida` reescrita sobre los dos; en `fundir`,
  `ventanas = test_windows.load(log_dir)` una vez y `test_window` en la copia; docstrings en español
  como el resto del módulo, nombres nuevos en inglés.
- **Tests**:
  - `test_reason`: `mcp` → «pruebas»; `banco` en el relleno → «pruebas»; **`{"banco": True}` en la
    fila, sin segundo argumento** → «pruebas»; `test_window` → «pruebas»;
    `codex-mcp-client` → `None`; `claude-code` → `None`.
  - `excluida` conserva los resultados de `tests/test_atribucion.py:605-612` y añade el de ventana.
  - `fundir` con un `test-windows.json` en `tmp_path`: la fila en ventana trae `test_window`, la de
    fuera no; el fichero de log tiene los mismos bytes (hash antes/después).
  - `tramo` de una fila en ventana = `excluido`; `bloque_coste` cuenta
    `excluidas_por_motivo["pruebas"]` con ella.
  - `recalcular`: una fila con `n` y `caller_*` válidos dentro de una ventana no entra en los
    agregados de N; la misma fuera, sí (los dos casos en el mismo test: la guarda de «esto comprobó
    algo»).
- **Controles positivos**: mutante que hace `test_reason` ignorar `test_window` (deben fallar los
  tests de `tramo` y `recalcular`); mutante que mete `codex-mcp-client` en `test_reason` (debe fallar
  el test de Codex).
- **Verificación**: `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_atribucion.py tests/test_valoracion.py tests/test_recalcular.py tests/test_densidad.py tests/test_coste_doctor.py -q`; ruff.
- **Vuelta atrás**: `git revert` del commit de la tarea.

### T3 — Subcomando `test-window` (ola 2, en paralelo con T2)

- **Ficheros**: `src/local_delegate/cli.py`, `tests/test_test_windows_cli.py` (nuevo).
- **Requisitos**: REQ-006 a REQ-010, REQ-025.
- **Pasos**: `_add_test_window_parser(sub)` con `start [--label]`, `stop [id]`, `add start end
  [--label]`, `list [--json]`; ayuda y mensajes en español; `TestWindowError` → stderr y código 2.
  `list` cuenta las filas por ventana leyendo `usage-*.jsonl` de `config.LOG_DIR` con `fundir`
  (mismo sello que el panel).
- **Tests** (con `monkeypatch.setattr(config, "LOG_DIR", tmp_path)` y `cli.main([...])`):
  `start` imprime un id que está en el fichero; `stop` sin id con 0/1/2 abiertas (2/0/2 y los ids en
  stderr); `stop` de id inexistente; `add` con `Z`, con `+00:00`, sin zona y con milisegundos guarda
  lo mismo normalizado; `add` con inicio ≥ fin y con fecha rota da 2; `add` repetido da 0 y «ya
  existía»; `list` cuenta 3 filas en una ventana con un log de 5; `list --json` parsea y tiene claves
  en inglés.
- **Control positivo**: mutante que hace `stop` sin id cerrar la primera abierta aunque haya dos
  (debe fallar el caso de dos abiertas).
- **Verificación**: `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_test_windows_cli.py -q`;
  `uv run local-delegate test-window --help` sale con 0 y el texto en español.
- **Vuelta atrás**: `git revert`.

### T4 — Panel, lado servidor (ola 3, en paralelo con T6 y T7)

- **Ficheros**: `src/local_delegate/web/metrics.py` (solo Python: `_load`, `_split_tests` nuevo,
  `events`, `stats`, `hooks`), `tests/test_metrics.py`.
- **Requisitos**: REQ-011, REQ-012, REQ-013, REQ-014, REQ-017.
- **Pasos**: parámetro `include_tests: str | None = Query(None)` en los tres endpoints
  (`"1"`/`"true"` = encendido); `meta.excluded_tests` / `excluded_tests` / `tests_in_range`;
  `bloque_coste` con todas las filas del rango; en `hooks`, filtro por `test_windows.find`.
- **Tests**:
  - Escenarios «una prueba marcada no cuenta» (con las tres clases de prueba: ventana, `mcp` y
    banco), «el interruptor las enseña» (igualdad campo a campo de `coste` y de `cuota`, con
    `_ahora` fijado y unos agregados de cuota `calibrado` en `tmp_path` para que `_bloque_cuota`
    llegue a llamar a `_load`; e `imagenes` distinto si una prueba es de `local_describe_image`) y
    «Codex sigue contando».
  - Si D7: `open_test_windows` con una ventana abierta y vacío sin ella.
  - **Paridad de conjunto**: con un log mixto (filas `mcp`, de banco, en ventana, Codex y reales),
    `events.meta.count == stats.total.calls` y `excluded_tests` igual en los dos, con y sin
    `include_tests`. Guarda: el log del test tiene al menos una fila de cada tipo y
    `excluded_tests > 0` sin el parámetro (si no, el test no comprueba nada).
  - `/api/hooks` con telemetría en `tmp_path` (`config.HOOK_TELEMETRY_LOG`): las filas en ventana
    salen de los agregados y `excluded_tests` las cuenta.
  - `_last_event` devuelve una fila en ventana si es la última (REQ-017).
  - Fichero de log intacto tras las peticiones (hash).
- **Controles positivos**: mutante que filtra solo en `stats` y no en `events` (debe fallar la
  paridad de conjunto, y anotar que el assert que dispara es el de `meta.count`); mutante que pasa a
  `bloque_coste` las filas filtradas (debe fallar la igualdad del bloque `coste` con `include_tests`);
  mutante en `_bloque_cuota` que filtra (debe fallar la igualdad de `cuota`); mutante que hace
  `test_reason` ignorar el `banco` de la fila (debe fallar la paridad de conjunto: la fila de banco
  se colaría en los dos endpoints y `excluded_tests` bajaría).
- **Medición** (REQ no funcional): tiempo de `stats()` sobre una copia del log real del mes con 0 y
  con 60 ventanas, 5 repeticiones, mediana; anotar en `evidencias/T4.md`. Si sube más de un 10 %,
  búsqueda binaria.
- **Verificación**: `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_metrics.py -q`; ruff.
- **Vuelta atrás**: `git revert`.

### T5 — Panel, interruptor (ola 4)

- **Ficheros**: `src/local_delegate/web/metrics.py` (parte `HTML`), `tests/test_dashboard_js.py`,
  `tests/test_dashboard_ui.py`, `scripts/dev/capture_dashboard.py`.
- **Requisitos**: REQ-016, REQ-012 (presentación).
- **Pasos**: botón `#tests` en `.controls`; `buildQuery(range, includeTests)` puro; `fetchData` usa su
  resultado para las tres peticiones; estado en `localStorage` `ld-tests` con `try/catch`; sección
  del `infoDlg` («Pruebas») con el número de filas fuera; texto del ⓘ de coste con las ventanas; el
  mock de `capture_dashboard.py` acepta `include_tests` y devuelve `excluded_tests`. Antes de tocar
  CSS o HTML, leer la memoria `panel-es-un-dashboard.md`.
- **Tests**:
  - node (`test_dashboard_js.py`): `textoPruebas` con 0 y con N filas fuera (y, si D7, con una
    ventana abierta: nombra la orden `stop <id>`); `buildQuery` con y sin pruebas (`include_tests=1`
    presente o ausente, `from`/`to` intactos); con `fetch` sustituido por un registrador y las funciones de
    pintado por no-ops, `fetchData` llama tres veces y las tres URLs tienen la misma query.
  - Playwright (`test_dashboard_ui.py`): el botón existe, empieza apagado, al pulsarlo las tres
    peticiones llevan `include_tests=1` (interceptadas), el ⓘ con `data-group="tests"` abre la
    sección con el número, y (si D7) el punto aparece con una ventana abierta en el mock.
  - `node --check` del HTML extraído (`scripts/extract_dashboard_js.py`).
- **Control positivo**: mutante en el que `/api/hooks` usa una `qs` propia sin el parámetro (debe
  fallar el test de las tres URLs).
- **Capturas**: panel en claro y oscuro, interruptor apagado y encendido, y el diálogo abierto
  (`scripts/dev/capture_dashboard.py`); van a `evidencias/T5/`.
- **Verificación**: `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_dashboard_js.py -q`;
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_dashboard_ui.py -q`.
- **Vuelta atrás**: `git revert`.

### T6 — `local_status` y `doctor` (ola 3, en paralelo con T4 y T7)

- **Ficheros**: `src/local_delegate/server.py` (`local_status`), `src/local_delegate/checks.py`,
  `tests/test_core.py`, `tests/test_checks.py`, `tests/test_doctor.py`, `tests/test_wiki.py` (solo
  `_NUMERO_DE_CHECKS`, `:35`, si el número nuevo no está), y la tabla del doctor en
  `docs/wiki/Integration-install.md` con la frase del número de comprobaciones: `tests/test_wiki.py`
  (`:28`, `:206-243`) compara la tabla y esa frase con `checks.CHECKS`, así que van juntos. Leer ese
  test antes de editar.
- **Requisitos**: REQ-018, REQ-019.
- **Pasos**: en `local_status`, contar con `test_reason` sobre las filas fundidas, añadir «(N de
  pruebas fuera)» y las ventanas abiertas; `Check("metrics.test_windows", "entorno", "ventanas de
  prueba", _probe_test_windows)`.
- **Tests**: `local_status` con 4 filas reales y 2 en ventana dice 4 eventos y «2 de pruebas fuera»;
  con una ventana abierta la nombra; `doctor`: sin fichero (correcto), con dos cerradas (correcto),
  abierta hace 13 h (aviso con la orden `stop`), abierta hace 1 h (correcto), JSON roto (aviso con el
  motivo), entrada ignorada (aviso con el número); `tests/test_wiki.py` en verde con la fila nueva
  y el número de comprobaciones actualizado.
- **Control positivo**: mutante con umbral de 12 h a 24 h (debe fallar el caso de 13 h).
- **Verificación**: `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_core.py tests/test_checks.py tests/test_doctor.py tests/test_wiki.py -q`.
- **Vuelta atrás**: `git revert`.

### T7 — Medidores de `scripts/` (ola 3, en paralelo con T4 y T6)

- **Ficheros**: `scripts/medir_enfriamiento.py`, `scripts/medir_adopcion.py`,
  `tests/test_medir_enfriamiento.py`, `tests/test_medir_adopcion.py`.
- **Requisitos**: REQ-020, REQ-021, REQ-022.
- **Insumo del control**: el `AttributeError` reproducido en T0 (`evidencias/T0.md`).
- **Pasos**: `args.excluir`; `--include-tests`; ventanas del fichero + `--excluir` parseado con
  `test_windows.parse_instant` y la regla de REQ-002; `medir_adopcion.directorio_de_logs()` devuelve
  `config.LOG_DIR` (REQ-022; lo importa también `medir_enfriamiento`); en `medir_adopcion`, filtro de
  ventana en hooks y log de uso; salida y `--json` con lo excluido. Los dos se corren desde ahora con
  `uv run python` (cambiar el `Uso:` de sus docstrings).
- **Tests**:
  - **`main()` de verdad**: `medir_enfriamiento.main()` con `sys.argv` parcheado y `LOCAL_DELEGATE_LOG_DIR`
    en `tmp_path` sale con 0 (este test falla hoy en `main` con el `AttributeError` de T0).
  - El escenario «P-4 se puede volver a medir»: mismo resultado con la ventana en el fichero que con
    `--include-tests --excluir …`.
  - Un `ts` `…01:20:05+00:00` con `--excluir 2026-10-08T01:20:05.255Z,…` queda **excluido** (con
    comparación de cadenas se colaría: `+` va antes que `.`).
  - `medir_adopcion.main()` con `sys.argv` parcheado y `--json` sale con 0.
  - `directorio_de_logs() == config.LOG_DIR` con `LOCAL_DELEGATE_LOG_DIR` puesto y sin poner (el
    panel y los scripts leen el mismo `test-windows.json`).
  - `medir_adopcion`: un bloqueo y su delegación dentro de una ventana no cuentan; con
    `--include-tests`, sí.
- **Controles positivos**: volver a poner `args.exclude` (debe fallar el test de `main()`); mutante que
  ignora el fichero de ventanas (debe fallar el escenario de P-4); mutante que compara `--excluir`
  como cadenas (debe fallar el caso `01:20:05`; el «antes» no se puede enseñar ejecutando el código
  viejo, porque su `main()` revienta).
- **Verificación**: `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_medir_enfriamiento.py tests/test_medir_adopcion.py -q`;
  `uv run python scripts/medir_enfriamiento.py --help` y `--desde 2030-01-01` salen con 0.
- **Vuelta atrás**: `git revert`.

### T8 — Documentación (ola 5)

- **Ficheros**: `CHANGELOG.md`, `README.md`, `docs/wiki/Savings-and-metrics.md`.
- **Requisitos**: REQ-024.
- **Pasos**: CHANGELOG (sección sin publicar: subcomando, interruptor, regla común, arreglo de
  `medir_enfriamiento`, la advertencia «las cifras del panel bajan: las pruebas ya no cuentan», y que
  `--excluir` pasa de semiabierto por cadenas a la regla de REQ-002);
  README (subcomando e interruptor, sin captura nueva salvo que T5 la cambie); wiki: qué es una prueba
  (las tres fuentes), cómo marcar una prueba en vivo (**guardar el id que imprime `start` y cerrar
  con `stop <id>`**, porque con agentes en paralelo `stop` sin id sale con código 2), la Mac (D4), el
  interruptor y los medidores (con `uv run python`).
- **Verificación**: `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_wiki.py tests/test_release_metadata.py -q`; revisión de que los tres sitios nombran lo mismo.
- **Vuelta atrás**: `git revert`.

### T9 — Instalar, sembrar y comprobar en esta PC (ola 6)

- **Ficheros**: `test-windows.json` del `LOG_DIR` real; `evidencias/T9.md` y `evidencias/T9/` (capturas).
- **Requisitos**: REQ-023, y la comprobación en vivo de REQ-011, REQ-016, REQ-018, REQ-019, REQ-020.
- **Pasos**:
  1. Marcar **esta propia comprobación** como prueba: `local-delegate test-window start --label "T9 test-windows-out-of-metrics"` (con el CLI ya instalado del paso 2; el orden real es 2 → 1).
  2. `bash ~/.claude/scripts/pesado.sh uv tool install --force --reinstall --no-cache ".[llamaswap]"` y reiniciar el daemon con `schtasks /Run` (memoria `daemon-y-uv-tool-trampas.md`).
  3. Antes de sembrar, `uv run python scripts/medir_adopcion.py --desde 2026-09-12 --json` y `--desde
     2026-09-23T01:14 --json`, guardados en la evidencia (insumo del «antes» de D5).
     Copia de seguridad de `test-windows.json` si existe; siembra con los tres `test-window add` de
     REQ-023 y, si D5 = sí, un bucle que lee `benchmarks/ventanas-excluidas.json` y llama
     `test-window add` por cada tanda y cada sesión (con su motivo como etiqueta). Repetir la siembra y
     comprobar que no duplica.
  4. `local-delegate test-window list` (pegar en la evidencia: ventanas y filas por ventana), y las
     dos mediciones del paso 3 otra vez: el «después», con la diferencia en `verification.md`.
  5. `/api/stats?from=2026-10-08T00:00:00Z&to=2026-10-08T23:59:59Z` con y sin `include_tests=1`
     contra el daemon real: `excluded_tests` > 0 sin el parámetro y `total.calls` difiere en ese
     número. (Si el día no tiene filas de prueba, el paso no discrimina: usar el rango de la ola 11.)
  6. Capturas del panel real en claro y oscuro con el interruptor apagado y encendido.
  7. `local_status` (por MCP) y `local-delegate doctor`: la ventana abierta del paso 1 aparece.
  8. `test-window stop <id del paso 1>`; `doctor` ya no la nombra.
  9. `uv run python scripts/medir_enfriamiento.py --desde 2026-09-15T19:26:41` sin `--excluir`: sale
     con 0 y lista la ventana de P-4 como aplicada.
- **Vuelta atrás**: restaurar la copia de `test-windows.json` (o borrarlo si no existía);
  reinstalar la versión publicada.

### T10 — Verificación final (ola 7)

- **Pasos**:
  1. `bash ~/.claude/scripts/pesado.sh uv run pytest -q` (suite completa con Playwright, `-rs`);
     `uv run ruff check .`; `uv run ruff format --check .`; `node --check` del JS extraído del panel y
     del de captura; gitleaks sobre `main..HEAD`.
  2. `tests/test_aislamiento_entorno.py` en verde sin tocarlo (REQ-025: ninguna variable nueva).
  3. Revisión del resultado contra REQ-001 a REQ-025 (`personal-sdd-result-reviewer`), con la tabla
     requisito → tarea → prueba → evidencia en `verification.md`.
  4. `handoff.md` y propuesta de memoria: «antes de una prueba en vivo contra el MCP o el daemon,
     `local-delegate test-window start --label …`, guardar el id que imprime; al acabar,
     `local-delegate test-window stop <id>`».
- **Verificación**: todo lo anterior con salida literal en `verification.md`.

## Test strategy

- **Unit**: `test_windows` (T1), regla y sello (T2), CLI (T3), checks (T6), medidores (T7).
- **Integration**: endpoints del panel con `TestClient` sobre logs en `tmp_path` (T4); paridad de
  conjunto entre `/api/events` y `/api/stats` (T4); JS del panel corrido con node (T5).
- **End-to-end**: Playwright del interruptor (T5); daemon real instalado en esta PC (T9).
- **Controles positivos**: uno o más por tarea, con el assert que dispara anotado.
- **Security and secret scanning**: gitleaks sobre `main..HEAD` (T10); el fichero de ventanas no lleva
  rutas ni contenido (revisión en T9 de lo sembrado: las etiquetas de D5 son los `motivo`/`tanda` del
  JSON del repo, sin rutas).

## Migration and compatibility

- Sin fichero, todo se comporta como hoy salvo una cosa: las filas del cliente `mcp` y de bancos
  **dejan de contar** en los KPIs, tablas y gráficos del panel y en `local_status` (antes solo el coste
  las quitaba). Es el efecto pedido; el CHANGELOG lo dice.
- `excluida` conserva firma y resultados; `CLIENTES_EXCLUIDOS` se conserva.
- Clientes del panel antiguos (pestaña abierta con el HTML viejo) no mandan `include_tests`: reciben
  la vista sin pruebas, que es el nuevo valor por defecto.
- Vuelta atrás completa: revertir los commits y borrar `test-windows.json` (el log no se tocó).

## Riesgos principales

- **Conflicto con el otro agente en `web/metrics.py`**: T0 rebasa y relee líneas antes de T4/T5; T4
  y T5 son serie.
- **Ventana olvidada**: aviso de `doctor` y línea de `local_status` (T6).
- **Cifras que bajan y alguien lo lee como regresión**: CHANGELOG y ⓘ con el número de filas fuera.
- **La siembra de D5 tapa trabajo real solapado**: las sesiones son de menos de un minuto; se anota en
  la evidencia cuántas filas quitó cada una (`list`) para revisarlo.

## Plan review

- [x] Cada requisito tiene tarea y prueba (tabla de trazabilidad de la spec).
- [x] Las operaciones con riesgo (siembra e instalación en la PC real) tienen copia y vuelta atrás.
- [x] Sin dependencias nuevas (`filelock` ya está) ni variables de entorno nuevas.
- [x] Cada control nombra la tarea que produce su insumo (T7 ← T0; T9 ← T2/T3/T4/T5/T6).
- [x] Revisión adversaria del plan: ver abajo.

### Revisión adversaria (2026-10-08, `personal-sdd-plan-reviewer`)

Veredicto: **APROBADO CON CAMBIOS**, sin bloqueantes. Confirmó las referencias principales de la
research y que el JS solo pide datos del log en `fetchData` con una `qs` común. Hallazgos y cómo
quedaron:

| # | Severidad | Hallazgo | Corrección aplicada |
|---|---|---|---|
| 1 | Importante | `test_reason(fila)` sin relleno dejaría pasar las filas de banco | REQ-004 lee `fila.get("banco")`; caso en T2; mutante en T4 |
| 2 | Importante | Spec y plan se contradecían sobre dónde se filtra; faltaba `_bloque_cuota` (`metrics.py:520`) | REQ-011 reescrito (filtro tras `_load`); REQ-014 con la cuota; test de igualdad de `cuota` en T4 |
| 3 | Importante | `bloque_imagenes` sin decidir | REQ-011: recibe las filas de uso; escenario actualizado |
| 4 | Importante | El fin de ventana con `ceil_s` metía un segundo de más (el log trunca, `server.py:709`) | REQ-002 con `floor_s(e)`; escenario del borde y mutantes de T1 |
| 5 | Importante | `measure_slowness.py`, `construir_corpus.py`, `medir_resumen_estructurado.py` sin mencionar | Non-goals con motivo |
| 6 | Importante | D5 no contaba su efecto en F1 | Columna de efecto en D5; T9 mide antes y después |
| 7 | Importante | `medir_adopcion.py` resuelve el directorio a su manera y es solo stdlib | REQ-022: `config.LOG_DIR` y `uv run`; tests en T7 |
| 8 | Importante | `stop` sin id falla con agentes en paralelo y la memoria proponía eso | REQ-024, T8 y T10 enseñan `stop <id>` |
| 9 | Menor | `--excluir` cambia de semántica; el «antes» no se puede ejecutar | CHANGELOG (T8) y control con mutante de cadenas (T7) |
| 10 | Menor | No se decía qué ⓘ abre la sección | REQ-016: ⓘ con `data-group="tests"` y `textoPruebas`; línea `:1534` corregida |
| 11 | Menor | El panel no avisa de una ventana olvidada | Nueva decisión D7 y REQ-026 condicionado |
| 12 | Menor | Motivo falso para conservar `CLIENTES_EXCLUIDOS` | Corregido en el enfoque |
| 13 | Menor | Conflicto con el otro agente sin criterio de parada | Criterio de parada en T0 |
| 14 | Menor | Sin verificar dónde vive la tabla del doctor | Verificado: `docs/wiki/Integration-install.md`, guardada por `tests/test_wiki.py:28-243`; T6 corregida |
