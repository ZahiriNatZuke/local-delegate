# Specification: Las pruebas fuera de las métricas: ventanas de prueba y una sola regla de exclusión en todo el panel

## Summary

Las pruebas en vivo contra el MCP o el daemon escriben en el mismo log de uso que el trabajo real y
ensucian el panel, `local_status` y las mediciones (P-4, F1). Después de este cambio:

- Hay un fichero `test-windows.json` con **ventanas de prueba** (intervalos UTC), que se gestiona con
  el subcomando `local-delegate test-window` (`start`, `stop`, `add`, `list`).
- Hay **una sola regla** de «esto es una prueba»: cliente `mcp` de los scripts, transcript de banco, o
  `ts` dentro de una ventana. La aplican el panel entero, `local_status`, el coste, el recálculo y los
  medidores de `scripts/`.
- El panel excluye las pruebas por defecto y tiene un interruptor para verlas.
- El log **no se reescribe**: se filtra al leer. Las cifras bajan a propósito.
- El fichero se siembra con las ventanas que ya se conocen.

Decisión ya tomada por el usuario (encargo del 2026-10-08): regla común `atribucion` en todo el panel +
fichero de ventanas + subcomando. Las decisiones que siguen abiertas están en «Decisiones abiertas»
con su recomendación; la spec está escrita con la recomendación y marca qué requisito cambia si el
usuario elige otra cosa.

## Requirements

### A. El fichero y la regla

- **REQ-001: Dónde y con qué forma.** Las ventanas viven en `config.LOG_DIR / "test-windows.json"`
  (D1). Forma:

  ```json
  {"version": 1, "windows": [
    {"id": "w-20261008T012005Z", "start": "2026-10-08T01:20:05.255Z",
     "end": "2026-10-08T01:22:31.544Z", "label": "ola 11, paso 5", "created_at": "…Z"}
  ]}
  ```

  `start`, `end` y `created_at` en ISO 8601 UTC con `Z`; `end: null` = ventana **abierta**; `label`
  texto libre (puede ser vacío); `id` único dentro del fichero, derivado del inicio
  (`w-AAAAMMDDTHHMMSSZ`, con sufijo `-2`, `-3`… si se repite). Claves y nombres en inglés.
- **REQ-002: Cuándo una marca de tiempo cae dentro.** Una marca `t` está en la ventana `[s, e]` si
  `floor_s(s) <= t <= floor_s(e)`, comparando `datetime` UTC truncados al segundo (`floor_s` quita
  las fracciones). Intervalo **cerrado**. Es la regla exacta para el log, que escribe
  `isoformat(timespec="seconds")` (`server.py:709`) y por tanto **trunca**: una fila con `ts`
  `01:22:32` ocurrió entre 32,0 y 33,0 s, siempre después de un fin a las `01:22:31.544`, y una con
  `01:20:05` pudo ocurrir a las `01:20:05.8`, dentro de una ventana que empieza a las `01:20:05.255`.
  Una ventana abierta usa como `e` el instante de la lectura. Una marca sin zona se toma como UTC; una
  ilegible no está en ninguna ventana. **Nunca** se comparan cadenas.
- **REQ-003: Lectura tolerante.** Fichero ausente = sin ventanas, sin aviso. Fichero ilegible
  entero (JSON roto, `version` desconocida) = sin ventanas, y el motivo queda disponible para
  `doctor` (REQ-019). Una entrada ilegible (falta `start`, fecha no parseable, `end < start`) se
  ignora sola y se cuenta como «ignorada». La lectura se cachea por `(mtime, size)`, como
  `_read_file_cached`. Leer nunca lanza.
- **REQ-004: Una sola regla de «es una prueba».** `atribucion.test_reason(fila, entrada_relleno)`
  devuelve `"pruebas"` si la fila es del cliente `mcp`, si está marcada `banco` (en `entrada_relleno`
  o, si no se pasa, en la propia fila fundida: `fila.get("banco")`, que es como lo pasan hoy
  `coste.py:262`, `recalcular.py:129` y `valoracion.py:191`), o si lleva `test_window`; si no, `None`. `atribucion.excluida` queda como «no es Claude» (cliente
  `codex-mcp-client`) **o** `test_reason`, con los mismos motivos que hoy. Las delegaciones de Codex
  **siguen contando** en el panel de uso; solo el coste las deja fuera, como hoy.
- **REQ-005: Se estampa al fundir, no se reescribe.** `coste.fundir(filas, log_dir=…)` añade
  `test_window: <id>` a la **copia** de cada fila cuyo `ts` cae en una ventana del fichero de ese
  `log_dir` (la primera por `start`). Todo consumidor que ya funde (`_load` del panel,
  `local_status`, `recalcular`, `checks`) la recibe sin código propio. El fichero de log no cambia ni
  un byte.

### B. El subcomando `local-delegate test-window`

- **REQ-006: `start [--label TEXTO]`.** Crea una ventana abierta con `start` = ahora (UTC, con
  milisegundos) e imprime su `id`. Puede haber **varias abiertas** a la vez (agentes en paralelo).
- **REQ-007: `stop [ID]`.** Cierra la ventana `ID` con `end` = ahora. Sin `ID`: si hay exactamente
  una abierta, la cierra; si no hay ninguna, sale con código 2 y lo dice; si hay varias, sale con
  código 2 y lista sus ids. Cerrar una ya cerrada o un id que no existe: código 2.
- **REQ-008: `add INICIO FIN [--label TEXTO]`.** Añade una ventana cerrada. Acepta ISO con o sin
  zona (sin zona = UTC) y con o sin milisegundos, y guarda con `Z`. `INICIO >= FIN` o una fecha
  ilegible: código 2. Si ya existe una ventana con el mismo `start` y `end` (tras normalizar), no
  añade nada, lo dice y sale con 0 (la siembra se puede repetir).
- **REQ-009: `list [--json]`.** Lista las ventanas por `start`, con id, inicio, fin (o «abierta»),
  etiqueta y **cuántas filas del log de uso caen dentro**; al final, las entradas ignoradas si las
  hay. `--json` da la misma información en JSON con claves en inglés.
- **REQ-010: Escritura segura.** Toda escritura relee, cambia y reemplaza el fichero de forma atómica
  (`tempfile` + `os.replace`) bajo un `FileLock` en `LOG_DIR`. Si el cerrojo no llega en 10 s:
  código 2 y mensaje. Si el fichero existente es ilegible, `start`/`stop`/`add` **no lo pisan**:
  código 2 y el motivo (el usuario lo arregla o lo borra).

### C. El panel

- **REQ-011: Filtro único en el servidor.** `_load` del panel sigue devolviendo **todas** las filas
  del rango; una sola función, `_split_tests(rows) -> (kept, tests)`, las separa con
  `atribucion.test_reason(fila)`. `/api/events` y `/api/stats` llaman a las dos igual y, salvo con
  `include_tests=1`, solo usan `kept` para lo que es **uso**: la lista de eventos, `_aggregate` y
  `bloque_imagenes` (`metrics.py:496`; las imágenes son uso, no coste). Así cuentan **el mismo
  conjunto**: con menos de `MAX_EVENTS` filas,
  `events.meta.count == stats.total.calls` con y sin `include_tests`. El JS no decide qué filas
  entran: `acct` y `agg` no cambian.
- **REQ-012: Cuántas se quitaron.** `/api/events` lleva `meta.excluded_tests` y `/api/stats` lleva
  `excluded_tests`: filas del rango que el filtro quitó (0 con `include_tests=1`, y entonces
  `tests_in_range` dice cuántas de las mostradas son pruebas). Los dos números salen de la misma
  pasada de `_load`.
- **REQ-013: `/api/hooks` igual.** La telemetría de hooks se filtra por ventana (REQ-002) con el mismo
  `include_tests`, y la respuesta lleva `excluded_tests`. (La telemetría no tiene `client`: solo
  aplican las ventanas.)
- **REQ-014: El coste y la cuota no dependen del interruptor.** El bloque `coste` de `/api/stats` se
  calcula siempre sobre **todas** las filas del rango (las pruebas incluidas), y las deja fuera con
  `excluida` como hoy: su resultado es idéntico con `include_tests` en 0 o en 1. Lo mismo el bloque
  `cuota`: `_bloque_cuota` llama a `_load` por su cuenta (`metrics.py:520`) y pasa sus filas, todas,
  a `bloque_coste`; no se filtra ahí. La cuenta
  `excluidas_por_motivo["pruebas"]` incluye las de las ventanas.
- **REQ-015: El recálculo también.** `recalcular-coste` no mete en los agregados de N las filas en
  ventana (llega solo, por REQ-004 y REQ-005; hace falta un test que lo pruebe).
- **REQ-016: El interruptor.** Un botón en la barra de controles (`.controls`), junto al selector de
  rango, con el texto «Pruebas» y estado visual encendido/apagado como el botón «Auto». Apagado
  (por defecto, D2) = excluye. Encendido = `include_tests=1` en **las tres** peticiones de
  `fetchData` (comparten `qs`). Sin prosa en la barra: el `title` dice «Incluir pruebas»; justo
  detrás va un botón ⓘ con `data-group="tests"` que abre su sección del diálogo `infoDlg`
  (`metrics.py:1534`; las secciones se eligen por `data-group`, `:2761`). El texto de esa sección,
  con el número de filas fuera en el rango (REQ-012), lo arma una función pura `textoPruebas(stats)`
  que prueba node, como `textoCoste`. El estado se recuerda por navegador en `localStorage` (`ld-tests`), como el tema, con
  `try/catch`. El texto del ⓘ de coste (`web/metrics.py:1824`) nombra también las ventanas de prueba.
- **REQ-017: Lo vivo no se filtra.** El indicador EN CURSO/EN VIVO (`_last_event`) y `/api/inflight`
  enseñan lo que pasa, pruebas incluidas.

### D. `local_status` y `doctor`

- **REQ-018: `local_status`** (D3). Cuenta eventos, llamadas y ahorro del mes **sin** pruebas, y la
  línea añade «(N de pruebas fuera)» cuando N > 0. Si hay ventanas abiertas, una línea más:
  «Ventana de prueba abierta: <id> desde <inicio>» (una por ventana).
- **REQ-019: `doctor`** (D3). Check nuevo `metrics.test_windows`, grupo `entorno`, título «ventanas
  de prueba». Correcto: «N ventanas, ninguna abierta» (o «sin ventanas»). **Aviso** si: el fichero es
  ilegible (con el motivo), hay entradas ignoradas (cuántas), o una ventana lleva abierta más de
  12 h (D6), con la orden para cerrarla. Nunca es un fallo: una ventana mal puesta no rompe el MCP.
  Entra en `checks.CHECKS` y en la tabla del doctor de la wiki.

### E. Los medidores de `scripts/`

- **REQ-020: `medir_enfriamiento.py`.** (a) Arranca: el `main()` usa `args.excluir` (hoy revienta
  siempre con `AttributeError`, ver research). (b) Aplica las ventanas de `LOG_DIR/test-windows.json`
  a las filas del log y a los episodios, **además** de los `--excluir` a mano. (c) `--include-tests`
  desactiva las del fichero (no las de `--excluir`). (d) Los tramos de `--excluir` se comparan con la
  regla de REQ-002, no como cadenas. (e) La salida lista las ventanas aplicadas y cuántas filas quitó
  cada fuente; `--json` lleva `excluded_tests` y `test_windows`.
- **REQ-021: `medir_adopcion.py`.** Aplica las ventanas a la telemetría de hooks y al log de uso; con
  `--include-tests`, no. La salida (y `--json`) dice cuántos eventos de cada lado quitó.
- **REQ-022: Una sola implementación y un solo directorio.** Los dos scripts importan la regla de
  `local_delegate.test_windows` (y, para el log de uso, `atribucion.test_reason`): no hay una copia
  en `scripts/`. `medir_adopcion.directorio_de_logs()` (`:35-40`, hoy con su propia resolución) pasa
  a devolver `config.LOG_DIR`, de modo que panel y scripts leen el **mismo** `test-windows.json`; los
  dos scripts se corren con `uv run python` (dejan de ser solo stdlib).

### F. Siembra, documentación y convenciones

- **REQ-023: Siembra en esta PC.** Tras instalar la versión nueva, el `test-windows.json` del
  `LOG_DIR` de la PC contiene, por `test-window add`:
  - `2026-10-08T01:20:05.255Z` → `2026-10-08T01:22:31.544Z`, «daemon-reparte-el-backend ola 11 paso 5»;
  - `2026-10-08T01:24:10.521Z` → `2026-10-08T01:24:39.452Z`, «daemon-reparte-el-backend ola 11 paso 7»;
  - `2026-09-15T19:31:14Z` → `2026-09-15T19:35:14Z`, «P-4 fallo provocado»;
  - y, según D5, las 5 tandas y las 49 sesiones de `benchmarks/ventanas-excluidas.json`.
  La siembra **no** va en el paquete (esas fechas solo valen en esta PC; en la Mac excluirían trabajo
  real).
- **REQ-024: Documentación.** CHANGELOG (con la advertencia de que las cifras bajan y por qué),
  README (el subcomando y el interruptor), `docs/wiki/Savings-and-metrics.md` (qué es una prueba,
  ventanas, cómo marcar una prueba en vivo, el interruptor, los medidores) y la tabla del doctor de la
  wiki (REQ-019). La wiki y la memoria enseñan a **guardar el id** que imprime `start` y cerrar con
  `stop <id>` (con agentes en paralelo, `stop` sin id sale con código 2, REQ-007). El CHANGELOG avisa
  también de que `--excluir` de `medir_enfriamiento.py` pasa de semiabierto (`inicio <= ts < fin`,
  comparando cadenas) a la regla de REQ-002, y que las cifras de P-4 pueden moverse un poco.
- **REQ-025: Convenciones.** Nombres de módulo, funciones, campos JSON, fichero, endpoint,
  parámetros y subcomando en **inglés**; textos que ve el usuario (CLI, panel, doctor,
  `local_status`) en **español**. **Ninguna** variable de entorno nueva. Ninguna dependencia nueva.

- **REQ-026 (condicionado a D7): aviso de ventana abierta en el panel.** `/api/stats` lleva
  `open_test_windows` (ids e inicio) y el botón «Pruebas» muestra un punto de aviso, sin texto, si
  hay alguna; la sección del ⓘ la nombra con la orden `local-delegate test-window stop <id>`.

## Acceptance scenarios

### Scenario: una prueba marcada no cuenta en el panel

- **Given** un log con 10 filas reales y 3 filas de prueba: una con `client: "claude-code"` cuyo `ts`
  cae en una ventana cerrada del fichero, una del cliente `mcp` y una marcada `banco`
- **When** se piden `/api/stats` y `/api/events` sin `include_tests`
- **Then** `total.calls == 10`, `meta.count == 10`, `excluded_tests == 3` en los dos, y el fichero de
  log tiene los mismos bytes que antes

### Scenario: el interruptor las enseña

- **Given** el mismo log
- **When** se piden con `include_tests=1`
- **Then** `total.calls == 13`, `meta.count == 13`, `excluded_tests == 0`, `tests_in_range == 3`; los
  bloques `coste` y `cuota` son iguales, campo a campo, a los de la petición sin `include_tests`; y
  `imagenes` cambia si alguna de las 3 filas es de `local_describe_image`

### Scenario: Codex sigue contando en el uso

- **Given** 2 filas de `codex-mcp-client` fuera de toda ventana
- **When** se pide `/api/stats` sin `include_tests`
- **Then** cuentan en `total.calls` y en `by_client`, y en el coste siguen en `excluidas_por_motivo["no es Claude"]`

### Scenario: el segundo del borde

- **Given** una ventana `2026-10-08T01:20:05.255Z` → `2026-10-08T01:22:31.544Z`
- **When** se evalúan filas con `ts` `01:20:04+00:00`, `01:20:05+00:00`, `01:22:31+00:00`,
  `01:22:32+00:00` y `01:22:33+00:00`
- **Then** dentro: `01:20:05` y `01:22:31`; fuera: `01:20:04`, `01:22:32` y `01:22:33`

### Scenario: dos agentes marcan a la vez

- **Given** ninguna ventana abierta
- **When** dos procesos ejecutan `test-window start` a la vez, y después `test-window stop` sin id
- **Then** el fichero tiene dos ventanas abiertas con ids distintos, y `stop` sale con código 2
  listando los dos ids

### Scenario: una ventana olvidada

- **Given** una ventana abierta hace 13 h
- **When** se corre `local-delegate doctor`
- **Then** `metrics.test_windows` da aviso con el id y la orden `local-delegate test-window stop <id>`,
  y `local_status` nombra la ventana abierta

### Scenario: la siembra se repite sin duplicar

- **Given** el fichero ya sembrado
- **When** se vuelven a ejecutar los mismos `test-window add`
- **Then** cada uno dice que ya existía, sale con 0, y el número de ventanas no cambia

### Scenario: P-4 se puede volver a medir

- **Given** `test-windows.json` con la ventana de P-4
- **When** se corre `medir_enfriamiento.py --desde 2026-09-15T19:26:41` sin `--excluir`
- **Then** termina con código 0 y el resultado coincide con el de `--include-tests --excluir 2026-09-15T19:31:14,2026-09-15T19:35:14`

## Edge cases and failure behavior

- Fichero ausente: todo como hoy (sin ventanas).
- Fichero ilegible: el panel no excluye por ventana (sí por cliente y banco), `doctor` avisa, y las
  escrituras se niegan (REQ-010).
- Entrada con `end < start` o fechas rotas: se ignora sola, `doctor` la cuenta.
- Ventanas solapadas: una fila dentro de las dos cuenta **una** vez como excluida (se estampa la
  primera).
- Ventana en el futuro (`add` con fechas posteriores): se acepta; no excluye nada hasta que haya filas.
- `LOCAL_DELEGATE_LOG` fijo (sin rotación): el fichero va igual en `config.LOG_DIR`.
- Fila sin `ts` o con `ts` ilegible: no está en ninguna ventana (y `_load` ya la descarta por rango).
- `include_tests` con un valor que no sea `1`/`true`: se trata como apagado.
- `localStorage` bloqueado: el interruptor empieza apagado y funciona sin recordar.

## Non-functional requirements

- **Coste de lectura**: comprobar una fila contra las ventanas no puede subir más de un 10 % el tiempo
  de `/api/stats` sobre el log real del mes (medido en T7). Con decenas de ventanas basta un recorrido
  lineal sobre una lista ordenada; si hay más de 200, búsqueda binaria.
- **Nunca lanza** desde la lectura (REQ-003): observar no puede romper una tool ni el panel.
- **Sin datos privados en el fichero**: solo fechas, ids y la etiqueta que escriba quien marca.
  Ni rutas ni contenido.

## Non-goals

- Reescribir o borrar filas del log.
- Sincronizar ventanas entre máquinas (D4).
- Filtrar la referencia de velocidad (`pace.py`), `/api/backend/stats` o el indicador en vivo.
- Aplicar las ventanas a `scripts/measure_slowness.py` (`:157-159`): fue el control de T3 del SDD
  `daemon-reparte-el-backend`, ya cerrado, y mide la velocidad real del backend, que una prueba en vivo
  no falsea (corre el mismo modelo a la misma velocidad). Si se vuelve a usar para decidir algo, se
  le añade entonces.
- Aplicar las ventanas a `scripts/construir_corpus.py` (`:1092`) y `scripts/medir_resumen_estructurado.py`
  (`:183`): leen el log para recuperar **entradas** reales (rutas y tamaños), no para contar uso; una
  prueba no cambia qué ficheros existen.
- Marcar pruebas automáticamente (por `session_id`, `entrypoint: sdk-cli`, etc.): eso sería otro
  cambio; aquí la marca es explícita.
- Renombrar al inglés lo que ya existe en español (`excluida`, `recalcular-coste`).
- Retirar `benchmarks/ventanas-excluidas.json` ni sus escritores.

## Decisiones abiertas

Están escritas con la recomendación; si el usuario elige otra cosa, cambian los requisitos citados.

| # | Pregunta | Recomendación | Por qué | Si se elige otra cosa |
|---|---|---|---|---|
| D1 | ¿Dónde vive `test-windows.json`? | En `config.LOG_DIR`, junto a `usage-*.jsonl`, `atribucion-*.json` y `enfriamiento.json` | Es el único directorio que leen a la vez el daemon, el panel (que no abre `~/.claude`, REQ-073 de `coste-api-y-cuota`) y los scripts (`directorio_de_logs()`, que pasa a devolver `config.LOG_DIR`, REQ-022); y las ventanas describen **ese** log | Otra ruta exigiría una variable de entorno nueva (contra REQ-025) y cambia REQ-001 |
| D2 | ¿El interruptor excluye por defecto? | Sí: apagado = sin pruebas | Es lo que pidió el usuario («las pruebas ensucian»); el número de filas fuera queda a un clic en el ⓘ | Cambia REQ-016 y el escenario por defecto |
| D3 | ¿`local_status` y `doctor` dicen cuántas filas se excluyen? | Sí: `local_status` dice cuántas y qué ventanas siguen abiertas; `doctor` avisa solo de problemas (ilegible, ignoradas, abierta > 12 h) | Sin eso, una ventana olvidada se come datos en silencio, que es justo el defecto que este cambio corrige | Se quitan REQ-018 y REQ-019 |
| D4 | ¿Cómo se marca una prueba desde la Mac? | Cada máquina marca en **su** `LOG_DIR` con su CLI (`local-delegate test-window start` en la Mac). Sin sincronizar | La Mac delega contra el backend de la PC con su propio daemon y su propio log: sus pruebas ensucian el panel de la Mac, no el de la PC. Una prueba en la PC que se lanza desde la Mac por SSH se marca en la PC | Marcar a distancia pediría un endpoint con escritura y token en el daemon: otro cambio |
| D5 | ¿Se importan las 5 tandas y las 49 sesiones de `benchmarks/ventanas-excluidas.json`? | Sí, las dos, en la siembra de esta PC (REQ-023), con su motivo como etiqueta, y T9 anota en `verification.md` las cifras de `medir_adopcion.py` (tramos desde 2026-09-12 y 2026-09-23) **antes y después** de sembrar | Son pruebas ya identificadas que hoy cuentan en el panel; las sesiones duran menos de un minuto cada una, así que el riesgo de tapar trabajo real es pequeño. **Efecto hacia atrás**: como REQ-021 aplica las ventanas a `medir_adopcion.py`, las cifras de F1 ya anotadas en la memoria y el vault cambiarán al volver a medir (deberían ser más limpias: las tandas pedían delegar) | Sin importarlas, siguen contando en el panel de septiembre y en F1; las cifras ya anotadas no se mueven |
| D7 | ¿El panel avisa de una ventana abierta? | Sí: un punto en el botón «Pruebas», sin texto, y la orden en el ⓘ (REQ-026) | El panel es donde se ven bajar las cifras; `doctor` y `local_status` no se miran a diario | Se quita REQ-026 |
| D6 | ¿A partir de cuántas horas avisa `doctor` de una ventana abierta? | 12 h, fijo en el código | Una prueba en vivo dura minutos; 12 h cubre una jornada sin dar falsos avisos | Otro número cambia REQ-019 |

## Traceability

| Requisito | Tarea del plan | Prueba |
|---|---|---|
| REQ-001, REQ-002, REQ-003 | T1 | `tests/test_test_windows.py` |
| REQ-004, REQ-005 | T2 | `tests/test_atribucion.py`, `tests/test_valoracion.py` (fundir y tramo) |
| REQ-006 a REQ-010 | T3 | `tests/test_test_windows_cli.py` |
| REQ-011 a REQ-014, REQ-017 | T4 | `tests/test_metrics.py` |
| REQ-015 | T2 | `tests/test_recalcular.py` |
| REQ-016 | T5 | `tests/test_dashboard_js.py`, `tests/test_dashboard_ui.py`, capturas |
| REQ-018, REQ-019 | T6 | `tests/test_core.py` (local_status), `tests/test_checks.py`, `tests/test_doctor.py` |
| REQ-020 a REQ-022 | T7 | `tests/test_medir_enfriamiento.py`, `tests/test_medir_adopcion.py` |
| REQ-023 | T9 | evidencia `test-window list` en esta PC |
| REQ-024, REQ-025 | T8 | `tests/test_wiki.py`, `tests/test_aislamiento_entorno.py`, revisión |
| REQ-026 (si D7) | T4 (dato), T5 (punto) | `tests/test_metrics.py`, `tests/test_dashboard_ui.py` |
