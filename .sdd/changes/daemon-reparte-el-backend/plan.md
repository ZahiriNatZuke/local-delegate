# Implementation plan: el daemon no se pelea por el modelo, usa el que ya está cargado, distingue espera de lentitud y la residencia es opcional

Plan sobre `spec.md` (aprobada el 2026-10-06, REQ-001 a REQ-043, con la aclaración de REQ-042 del
mismo día al final de la spec). **Revisión 2**, tras la revisión adversaria del plan (`review.md`,
«Revisión del plan» y «Respuesta a la revisión del plan»). **Aclaraciones del 2026-10-07**, tras la
revisión del código de la ola 3: T7, T8, T10, T11 y T14 llevan la marca «aclarado el 2026-10-07»,
que recoge las aclaraciones de REQ-002, REQ-003, REQ-005 y REQ-007 del final de la spec y las
firmas que fijó el código. Se implementa **después** de
`panel-cuentas-y-estados-honestos` y de `coste-api-y-cuota`, y parte del estado que dejan los dos
mezclados en `main`. Nada de este plan da por hecho el código actual de `server.py`,
`web/metrics.py`, `checks.py`, `cli.py` ni `config.py`: las zonas se nombran **por función**, y el
arranque (T0) lee cómo quedaron. Lo que sí se da por hecho, porque lo fijan contratos ya aprobados:

- el ayudante `_inflight_espera_local(entry_id, motivo)` de `server.py` (commit `b73734d`), que este
  cambio **llama** con `"turno"` sin modificarlo, y la copia de `espera_local` en
  `inflight_snapshot()` (hoy es ahí, en `server.py`, donde se filtra lo que llega a
  `/api/inflight`; T0 confirma dónde quedó tras el panel);
- `estadoModelo` del panel: la fila 3 («en cola local») vale para **cualquier** motivo de
  `espera_local` (spec del panel, REQ-022);
- tras `coste-api-y-cuota`, `checks.CHECKS` tiene **veintidós** checks; este cambio añade dos y deja
  **veinticuatro**.

## Approach

Dieciocho tareas: arranque, enmienda de F3, tres controles previos que no tocan el producto, la
tanda con modelos reales, el juicio del usuario, nueve de código (una de ellas condicionada al
veredicto), documentación y verificación final. Todo en el árbol principal de la rama
`feat/daemon-reparte-el-backend`, **sin worktrees**.

**Regla de paralelo, más estricta que en los dos cambios anteriores.** `import local_delegate`
carga `server.py` (el `__init__` importa `entrypoint`; comprobado el 2026-10-06:
`import local_delegate.config` deja `local_delegate.server` en `sys.modules`). Por tanto **cualquier
test carga `server.py`**, y una tarea que edita `server.py` no puede ir en paralelo con ninguna otra
tarea de código: la otra verificaría contra un fichero a medio editar. Solo van juntas tareas que
no editan `server.py` **ni** ningún fichero de la otra, ni uno que la otra importe mientras lo
escribe.

### Diseño

- **Módulos nuevos, uno por pregunta** (LF, solo stdlib más PyYAML del extra `[llamaswap]`):
  - `huella.py` (T4): lee del `cmd` de un modelo la ruta del GGUF (`-m`), su tamaño, y los flags que
    cambian el modelo cargado (`-ncmoe`/`--n-cpu-moe`, `--ctx-size`/`-c`, `-ctk`/`-ctv` y sus formas
    largas, `--reasoning*`, `--mmproj`), y calcula la huella de REQ-010 (con el `sha256` del prompt
    de sistema de la tool). Es el **único** parser de `cmd` del paquete: lo usan la tanda (T5), la
    topología (T7, para `--mmproj`), el estimador de VRAM (T11) y la matriz (T15). Nace en T4 porque
    la huella se calcula con la config **del momento de la tanda**. La calcula **T5**, que la guarda
    en `huellas.json` junto a los resultados; el veredicto (T4, T6) la **copia** de ahí y no importa
    `local_delegate` (importarlo carga `server.py`, que otras tareas editan mientras corre T6).
  - `benchmarks/afinidad-2026-10/reglas.json` (T4): los **parámetros de la hoja y del veredicto en
    un solo sitio**, que leen `hoja_pares.py` y `analizar_benchmark.py` y ningún otro: el máximo de
    «inventa» del 26B, qué preguntas son opcionales en la hoja, y la regla de formato que calcula el
    programa. Dos valores están **pendientes del usuario** (ver T4.5); el fichero se cierra, y su
    `sha256` se anota, antes de generar la primera hoja.
  - `topologia.py` (T7): REQ-001, REQ-002 (la parte de leer la config), REQ-009 y lo que el CLI
    necesita ver: grupos en las dos sintaxis con los valores por defecto de v255, `(default)`,
    alias → id real, `choca(a, b)`, TTL efectivo (resolviendo `-1` y la ausencia con `globalTTL`),
    `--mmproj`, `hooks.on_startup.preload`, `residentes()` (TTL efectivo 0) y `validar_como_load_go`.
    Caché por `(ruta, mtime, tamaño)`. Devuelve una foto inmutable con un número de versión que sube
    cuando cambia; sin topología, devuelve el motivo (REQ-002).
  - `turno.py` (T8): el estado del turno de REQ-003 a REQ-007 en dos capas. Un **núcleo puro**,
    `evaluar(estado, topo, ahora) -> Decision`, sin hilos ni reloj, que dice a quién se concede, con
    qué reserva y si forzado; y una envoltura con `threading.Condition` que despierta cada espera al
    menos una vez por segundo (REQ-003, punto 6), lleva el contador de llamadas al backend en vuelo
    y el reloj de falta de progreso (REQ-007, con `time.monotonic` inyectable). La compatibilidad
    llega como función (`choca`) desde la foto de topología: `turno.py` no lee la config.
  - `ritmo.py` (T9): la referencia de velocidad de REQ-025 (ventana por modelo, mínimo, tramos si
    T3 los pide, siembra desde el log de uso) y el cálculo de `ritmo_rel`/`lento`. Puro.
  - `residencia.py` (T11): la edición quirúrgica de REQ-033 (marcas de posición de
    `yaml.compose()`), la autocomprobación, las negativas de formato, la copia con fecha y el
    reemplazo atómico con reintentos; `--ninguno`, `--fijar`, `--ttl` y `--restaurar` como
    transformaciones puras «bytes → bytes».
  - `llamaswap_api.py` (T13): las consultas a llama-swap con tope de 1 s (`/running` reducido a id,
    estado y TTL; la foto `inflight` de la carga inicial de `/api/events`; la actividad), y la vigía
    de recarga. **Nunca** devuelve `cmd`, cabeceras ni claves. Lo usan los endpoints del daemon, el
    CLI y, si hay afinidad, la foto de REQ-013 (T15).
  - `matriz.py` (T15, **solo si el veredicto aprueba alguna celda**): la matriz en un solo sitio, la
    huella vigente y `elegir()` (REQ-012), pura.
- **Dónde entra el turno en `server.py`.** Hoy solo hay dos llamadas a `_run_chat` (en `_chat` y en
  `_ModeloVigente.llamar`) y una operación es una llamada a `_chat`, `_chat_chunked` o
  `_chat_map_reduce`. El turno se toma **una vez por operación**, en esas tres, antes de la primera
  plaza, y se suelta en un `finally`. `_run_chat` sigue tomando la plaza por llamada. El salto de
  respaldo sale de dentro de la plaza: `_con_respaldo` se parte en «intento» y «decisión de salto»,
  y el salto vuelve al nivel de la operación, que suelta plaza, sale de `activos`, pide turno al
  final de la cola y vuelve a pedir plaza (REQ-006). Ninguna de las dos funciones pide turno con
  una plaza en la mano (REQ-004): lo comprueba un aserto de depuración en `turno.py` (el hilo que
  pide turno no puede tener plaza; la plaza se apunta en un `threading.local`) que los tests activan.
- **Llamadas en vuelo para la red de seguridad.** El contador vive en `turno.py` y lo mueven el
  inicio y el fin de **cada** `_post_chat`, con turno o sin él (una operación sin topología también
  cuenta, REQ-007).
- **Variables nuevas** por `_env*` en `config.py`, cada una en la tarea que la usa:
  `LOCAL_DELEGATE_TURNO_MAX_S` (T10), `LOCAL_DELEGATE_UMBRAL_LENTO` (T14) y
  `LOCAL_DELEGATE_AFINIDAD_MARGEN_S` (T15, solo si hay afinidad).
- **Comando:** `local-delegate llamaswap residencia` (subparser nuevo `llamaswap` con el
  subcomando `residencia`), con `--config`, `--ninguno`, `--grupo`, `--fijar`, `--ttl`,
  `--restaurar`, `--vram-gb`, `--reserva-gb`, `--vram-modelo`, `--dry-run` y `--ahora`.
  `check-llamaswap` e `init-llamaswap` siguen donde están.
- **Endpoints nuevos del daemon**, tras el token web: `GET /api/llamaswap/estado`,
  `POST /api/llamaswap/vigia` y `GET /api/llamaswap/vigia/<id>`. El panel no los pide, así que
  `tests/test_captura.py` no cambia de lista (solo mira lo que la página hace `fetch`).
- **Checks nuevos de `doctor`:** `backend.residencia` y `backend.topologia`, en el grupo «Backend»,
  detrás de `backend.llamaserver`. Pasan de veintidós a veinticuatro, con sus guardianes de tamaño.

### Olas

| Ola | Tareas | Espera a | Escritor único de `verification.md` |
|---|---|---|---|
| 0 | T0 (arranque) y después T1 (enmienda de F3), el mismo agente | panel y coste mezclados en `main` | agente de T0/T1 |
| 1 | T2 (llama-swap de prueba) ∥ T3 (control de lentitud) ∥ T4 (corpus, hoja y veredicto sin modelos) | ola 0 | agente de integración I1 |
| 2 | T5 (tanda con modelos reales y hoja para el usuario) | ola 1, T1 enviada al usuario, `reglas.json` confirmado por el usuario y una ventana sin otras sesiones que deleguen | agente de T5 |
| — | T6 (juicio del usuario y veredicto de commit), **en paralelo con las olas 3 a 8**; no importa `local_delegate` (lo prueba un test de T4) | T5 | no escribe `verification.md`: deja `evidencias/T6.md` |
| 3 | T7 (topología) ∥ T8 (núcleo del turno) ∥ T9 (referencia de velocidad) | ola 2 | agente de integración I3 |
| 4 | T10 (turno en el daemon) | ola 3 | agente de T10 |
| 5 | T11 (editor y CLI de residencia sobre copias) | ola 4 | agente de T11 |
| 6 | T12 (cadenas sin residente) | ola 5 y gate `spec` de F3 reaprobado o pendiente (ver T1) | agente de T12 |
| 7 | T13 (llama-swap desde el daemon: estado, vigía, negativas y `doctor`) | ola 6 | agente de T13 |
| 8 | T14 (espera frente a lentitud) | ola 7 | agente de T14 |
| 9 | T15 (afinidad, **solo con celdas aprobadas**) | ola 8 y T6 cerrada | agente de T15 |
| 10 | T16 (documentación) | ola 9 | agente de T16 |
| 11 | T17 (verificación final) | ola 10 | agente de T17 (los pasos con el daemon y la config real los lanza la sesión principal) |

**Por qué estas tríadas y no otras.**

- T2 ∥ T3 ∥ T4: ninguna edita `server.py` ni un fichero de las otras. T2 escribe
  `tests/llamaswap_de_prueba.py`, `tests/servidor_falso_llama.py`,
  `tests/test_llamaswap_de_prueba.py` y `scripts/dev/medir_carrera_ttl.py`; T3,
  `scripts/medir_lentitud.py` y su test; T4, `huella.py`, `scripts/construir_corpus.py`,
  `scripts/hoja_pares.py`, `scripts/analizar_benchmark.py`, `benchmarks/afinidad-2026-10/` y sus
  tests. T4 importa `server.py` para capturar los prompts, pero nadie lo edita en la ola.
- T7 ∥ T8 ∥ T9: módulos nuevos que no se importan entre sí (`turno.py` recibe `choca` como función,
  `ritmo.py` no conoce la topología). T7 importa `huella.py`, cerrado en la ola 1.
- T6 corre mientras T10, T12 y T14 editan `server.py`. Por eso sus dos programas
  (`hoja_pares.py` y `analizar_benchmark.py`) no importan `local_delegate`: la huella la copian de
  `huellas.json` (T5). Un test de T4 corre los dos subcomandos con `local_delegate` bloqueado en
  `sys.modules`. Si ese test no pudiera pasar, T6 iría en serie entre dos olas.
- Todas las demás van solas porque editan `server.py` (T10, T12, T14, T15), o porque cargan
  `server.py` al verificar mientras la tarea vecina lo edita (T11 importa `cli.py`, que importa
  `server.py`; T13 edita `web/metrics.py` y `checks.py`, que T12 y T14 también tocan).

**Reglas de las olas en paralelo** (las de `coste-api-y-cuota`, sin cambios):

- Cada agente corre **solo** sus ficheros de test y los existentes que su tarea nombra. La suite
  completa la corre el agente de integración cuando las tres tareas han terminado.
- Los agentes de la ola **no escriben** `verification.md`: cada uno deja su evidencia (salidas de
  pytest, qué assert disparó cada control, mediciones) en `evidencias/T<n>.md`, del que es el único
  escritor. El agente de integración enlaza esos ficheros desde `verification.md` y **no los
  reescribe**: un subagente que transporta texto lo reescribe (jornada del 2026-09-22).
- **Integración Ix** (último paso de la ola, con dueño): suite completa
  `bash ~/.claude/scripts/pesado.sh uv run pytest -q` (con `--group ui` para Playwright),
  `uv run ruff check .`, el `node --check` del JS si la ola tocó `web/metrics.py`, y la
  **comprobación de la config real** (abajo). Un rojo lo
  arregla el agente de integración aunque esté fuera de las listas (ya no hay nadie más en marcha) y
  lo anota en `verification.md` como «tocado por la integración».
- En las olas de una sola tarea, el agente de la tarea es el escritor y el integrador, y también
  hace la comprobación de la config real.

**Comprobación de la config real al cerrar cada ola** (con dueño: el escritor de la ola). T0 anota
el `sha256` de `D:\Projects\llms\llama-swap\config.yaml` y deja una copia
`config.yaml.pre-daemon-reparte-<AAAAMMDD-HHMMSS>.bak` junto a ella. Al cerrar **cada** ola, el
escritor vuelve a calcular el `sha256` y lo anota. Si cambió fuera de T17.6, **se para**: la sesión
principal pregunta al usuario si fue él (cambia los TTL a mano). Si fue él, se anota el `sha256`
nuevo, con una copia nueva, y se sigue. Si no, se restaura desde la copia de T0 con `Copy-Item`, se
comprueba el `sha256`, y la ola no se cierra hasta encontrar qué la escribió.

**Procesos:** solo se comprueban y se terminan los **PID que lanzó la fixture** del llama-swap de
prueba (T2), que los apunta. **Queda prohibido matar procesos por nombre** (`taskkill /IM`,
`Stop-Process -Name`, `pkill`): el llama-swap real usa el mismo binario
(`llama-swap-v255\llama-swap.exe`) y corre siempre. Lo dicen los encargos de T2, T13 y T17.

**Comandos pesados** (pytest, Playwright, `uv tool install`, la tanda, el llama-swap de prueba,
la lectura de los GGUF) **siempre** con `bash ~/.claude/scripts/pesado.sh <comando>`, de uno en uno
en toda la máquina; `jest` no se usa aquí. `ruff` y `node --check` son ligeros.

**Commits:** firmados (lo exige el ruleset de `main`) y **sin** línea de coautoría de Claude (memoria
`no-claude-coauthor`, que anula la instrucción del harness). Un commit por tarea, con el número de
la tarea en el cuerpo.

**Nadie usa las tools `local_*` durante la ola 2** (la tanda): cargarían otro modelo y meterían
latencias falsas en los resultados y filas en `metrics.db`. Cada encargo de esas horas lo dice.

### Propiedad de ficheros

Las zonas se nombran **por función**. EOL medido el 2026-10-06 con `git ls-files --eol`; cada
tarea lo vuelve a medir antes de editar.

| Fichero | EOL | Dueño (en orden) | Zona |
|---|---|---|---|
| `.sdd/changes/delegacion-precisa-y-fiable/spec.md` | comprobar | T1 | solo el punto nuevo de «Cambios respecto al original» |
| `tests/llamaswap_de_prueba.py`, `tests/servidor_falso_llama.py`, `tests/test_llamaswap_de_prueba.py` (nuevos) | LF | T2 | |
| `scripts/dev/medir_carrera_ttl.py` (nuevo) | LF | T2 | |
| `scripts/medir_lentitud.py`, `tests/test_medir_lentitud.py` (nuevos) | LF | T3 → T9 | T9: el script pasa a importar `ritmo.py` (una sola fuente de la regla) |
| `src/local_delegate/huella.py`, `tests/test_huella.py` (nuevos) | LF | T4 | |
| `scripts/construir_corpus.py`, `tests/test_corpus.py` | LF | T4 | subcomando del corpus de afinidad y regla de selección de commits |
| `scripts/hoja_pares.py`, `tests/test_hoja_pares.py` | LF | T4 | subcomandos `generar-commit` y `leer-commit`; lo de F2 no se toca |
| `scripts/analizar_benchmark.py`, `tests/test_analisis_benchmark.py` | LF | T4 | subcomando `veredicto-afinidad` |
| `benchmarks/afinidad-2026-10/` (nuevo: `cases.json`, `trampas.json`, `reglas.json`, `resultados/`, `huellas.json`, `hoja/`, `clave/`, `veredicto.json`) | LF | T4 → T5 → T6 | T4: corpus, trampas y reglas. T5: resultados, huellas, hoja 1 y su clave. T6: respuestas, hojas 2 y 3 si hacen falta, y `veredicto.json`. La clave va en `clave/`, **fuera** de la carpeta `hoja/` que abre el usuario |
| `src/local_delegate/topologia.py`, `tests/test_topologia.py`, `tests/fixtures/topologia/` (nuevos) | LF | T7 | |
| `src/local_delegate/turno.py`, `tests/test_turno.py` (nuevos) | LF | T8 → T10 → T15 | T8: núcleo y envoltura. T10: solo si la integración pide un cambio de interfaz, anotado. T15: nada (las reservas con alternativos ya están en T8) |
| `src/local_delegate/ritmo.py`, `tests/test_ritmo.py` (nuevos) | LF | T9 | |
| `src/local_delegate/server.py` | CRLF | T10 → T12 → T14 → T15 | T10: `_chat`, `_chat_chunked`, `_chat_map_reduce` (turno por operación), `_run_chat` (marca de plaza para el aserto), `_con_respaldo` partido en intento y decisión de salto, `_ModeloVigente` (el salto vuelve a la operación), contador de llamadas en vuelo alrededor de `_post_chat`, ayudante nuevo `_inflight_turno` (escribe y borra `turno_en_uso` y `turno_posicion`), las dos claves en `inflight_snapshot`, `_log_event` (`espera_turno_ms`, `turno`), y en `local_status` el bloque del turno. T12: decisión de salto (paso `cargado`, capacidad), y en `local_status` la línea de cadenas. T14: `ChatResult` (`timings`), `_post_chat`, `_log_event` (campos de D), siembra de `ritmo` al arrancar, y en `local_status` las medianas. T15: cálculo de `A`, elección tras la primera plaza, campos de afinidad de `_log_event` |
| `src/local_delegate/config.py` | LF | T10 → T14 → T15 | una variable cada una |
| `tests/conftest.py` | LF | T10 → T11 | T10: fixture autouse que vacía el estado del turno y la caché de topología. T11: fixture autouse que apunta la consulta al daemon a un puerto muerto |
| `src/local_delegate/web/metrics.py` | CRLF | T10 → T13 → T14 | T10: palabras del motivo `"turno"` en el `title` de `estadoModelo` y en «En curso» (`renderInflight`), con `turno_en_uso`; **no** toca la tabla de estados ni la condición de la fila 3. T13: los tres endpoints de `/api/llamaswap/`. T14: columnas de espera, inferencia y marca «lento» en la tabla de actividad (función JS pura nueva `marcaLento`) |
| `tests/test_panel_estados.py` | LF | T10 → T14 | T10: motivo `"turno"`. T14: `marcaLento` |
| `tests/test_metrics.py` | LF | T10 → T13 → T14 | T10: `/api/inflight` con las claves nuevas. T13: endpoints nuevos. T14: `/api/events` con los campos nuevos |
| `tests/test_dashboard_js.py`, `tests/test_dashboard_ui.py` | LF / CRLF | T14 | solo lo que salga del inventario de T14 |
| `tests/backend_mock.py` | LF | T10 → T14 | T10: modo que cuenta cambios de modelo y serializa como `-np 1`. T14: `timings` en las respuestas |
| `tests/test_turno_daemon.py` (nuevo) | LF | T10 | |
| tests existentes que rompa el turno (inventario de T10: `test_respaldo.py`, `test_map_reduce.py`, `test_chunking.py`, `test_post_chat_caminos.py`, `test_observabilidad_respaldo.py`, los que salgan) | ver EOL | T10 | solo lo que sale del inventario ejecutado |
| `src/local_delegate/residencia.py`, `tests/test_residencia.py`, `tests/fixtures/residencia/` (nuevos) | LF | T11 → T13 | T11: transformaciones y escritura. T13: nada en el módulo; las negativas y la vigía van en `cli.py` |
| `src/local_delegate/llamaswap_config.py`, `tests/test_llamaswap_config.py` | LF | T11 | estimador con `-ncmoe`; `.bak` con fecha de `init-llamaswap`; `--ttl-resident` a 0 |
| `src/local_delegate/cli.py` | CRLF | T11 → T13 | T11: subparser `llamaswap residencia` y su comando con la comprobación previa como interfaz que devuelve «no se sabe»; ayuda de `init-llamaswap`. T13: comprobación previa y vigía de verdad |
| `src/local_delegate/cadenas.py`, `tests/test_cadenas.py` | LF | T12 → T15 | T12: paso `cargado`, cadenas por defecto, sinónimo `residente`, `describir()`. T15: el proveedor de miembros de `cargado` |
| `src/local_delegate/checks.py` | LF | T12 → T13 → T15 | T12: `_probe_fallback` (textos y aviso del sinónimo). T13: `_probe_residencia`, `_probe_topologia`, dos entradas de `CHECKS`, las frases de tamaño del docstring. T15: aviso de huella en `_probe_residencia` |
| `tests/test_checks.py`, `tests/test_wiki.py` | LF | T12 → T13 | T12: textos de `_probe_fallback`. T13: `_NUMERO[23]`, `_NUMERO[24]`, `_NUMERO_DE_CHECKS[23]`, `_NUMERO_DE_CHECKS[24]` y tests de los dos checks |
| `docs/wiki/Integration-install.md` | CRLF | T13 → T16 | T13: las dos filas de la tabla del doctor y «las veinticuatro piezas». T16: el resto |
| tests de respaldo que nombran al residente (`test_respaldo.py`, `test_observabilidad_respaldo.py`, `test_rol_fast_retirado.py`, los que salgan) | LF | T12 | inventario ejecutado; se reescriben, no se borran sin sustituto |
| `src/local_delegate/llamaswap_api.py`, `tests/test_llamaswap_api.py`, `tests/test_residencia_cli.py` (nuevos) | LF | T13 | |
| `src/local_delegate/web/sysinfo.py` | comprobar | T14 | solo si `ram_stats()` necesita una variante que no reviente |
| `src/local_delegate/matriz.py`, `tests/test_afinidad.py` (nuevos) | LF | T15 | |
| `tests/test_aislamiento_entorno.py` | LF | T10 → T14 → T15 | solo si alguna aserción de tamaño lo pide |
| `CHANGELOG.md`, `README.md` | CRLF | T16 | |
| `docs/wiki/Configuration.md`, `Tools.md`, `Architecture.md`, `Backend-versions.md`, `Savings-and-metrics.md`, `Troubleshooting.md`, `Daemon.md`, `docs/recipes/llama-swap-groups.md` | LF | T16 | |
| `scripts/dev/capture_dashboard.py` | LF | T14 | mock de `/api/events` con los campos nuevos |
| `verification.md` | LF | el escritor de la ola (tabla de olas) | |
| `evidencias/T2.md` … `evidencias/T9.md` (nuevos) | LF | el agente de cada tarea en paralelo, y T6 | |

Reglas comunes:

- Antes de editar, `git ls-files --eol <fichero>`; después, el mismo EOL y `git diff --stat` sin
  ficheros ajenos. Editar con la herramienta Edit: el heredoc de Git Bash colapsa barras invertidas
  y `write_text` convierte finales de línea. Nunca medir CRLF con `grep -c $'\r$'` en Git Bash.
- **JS compilable al pasar el turno**: toda tarea que toque `web/metrics.py` termina con la
  extracción de `<script>` de `metrics.HTML` a `<scratchpad>/panel.js` y `node --check` sin errores
  (comando exacto en el plan del panel, «Reglas comunes»).
- **La config real de llama-swap** (`D:\Projects\llms\llama-swap\config.yaml`) **no la escribe
  ninguna tarea** salvo T17.6, que la lanza la sesión principal con permiso del usuario.
  `LLAMASWAP_CONFIG` está definida a nivel de usuario y apunta a ella, y el CLI resuelve la ruta con
  `--config`, después `LLAMASWAP_CONFIG` y, por último, la que da el daemon. Por eso:
  - **toda orden de `llamaswap residencia`** que escriba un plan, un encargo o un test lleva
    `--config <copia>` explícito, escrito literal;
  - una fixture **autouse** de `tests/conftest.py` (T11) apunta la consulta al daemon a un puerto
    muerto, y `conftest` ya aísla `LLAMASWAP_CONFIG`; un test de T11 demuestra que, sin `--config`
    ni la variable, el CLI dice «no se sabe» y no abre ningún fichero;
  - el `sha256` de la config real se compara al cerrar cada ola (arriba).

  Los tests y las pruebas usan copias en `tmp_path` o en el scratchpad, **con las claves
  sustituidas** por valores falsos (`clave-falsa-1`…): toda lista `apiKeys` y todo `--api-key` de
  un `cmd`. Ningún fixture del repo lleva una clave real; T11 lo comprueba con un test.
- Ningún paso lee ni pide `LOCAL_DELEGATE_API_KEY`. Lo que necesita la key va por el daemon
  (memoria «verificación contra el backend real»).
- No se retira ningún hook: `_SCRIPTS_RETIRADOS` no cambia.

### Cómo se escribe el control positivo de cada test

Los tres tipos de los dos planes anteriores, sin cambios: **(a)** contra el código de antes, **(b)**
mutante nombrado que muta de verdad (cada uno dice por qué muta), **(c)** contra un corte
intermedio solo de interfaz. La tarea anota en su evidencia **qué assert disparó**, copiado de la
salida de pytest. Nunca vale un fallo por `KeyError`, `AttributeError`, `ImportError`,
`FileNotFoundError` o `ValueError` de desempaquetado: los campos nuevos se leen con `.get(...)`,
una función que aún no existe pide un corte (c), y un test que espera de verdad (hilos) lleva un
tope propio y falla con un mensaje propio, nunca por el timeout del runner. **Todo
`pytest.raises` lleva `match=`** con el texto que distingue la causa: sin él, otra excepción del
mismo tipo hace pasar el mutante. Y si un mutante puede hacer que el código lance antes del
assert, el test captura esa excepción y la convierte en un `assert` con mensaje.

Los controles marcados **«comprobado»** se ejecutaron el 2026-10-06 con reimplementaciones
desechables (`scratchpad/controles-plan/controles.py`): la huella con la forma corta y la larga,
las claves duplicadas, las respuestas de otra hoja y la línea corrupta de la siembra.

Además, para los tests de concurrencia: **un test que no puede ver la diferencia no es un
control.** Los del turno llevan una guarda que demuestra que el guion discrimina (por ejemplo, el
mismo guion sin turno da varios cambios de modelo) antes del assert principal.

## Ordered tasks

### T0 — Arranque y comprobaciones previas (ola 0)

- **Ficheros:** ninguno del código. Escribe `verification.md` (entorno y hallazgos).
- **Qué se hace:**
  1. **Precondición**: `panel-cuentas-y-estados-honestos` y `coste-api-y-cuota` mezclados en `main`
     (PR mezclado y gate `conformance` aprobado en su `state.json`). Si no, se para y se avisa. Rama
     nueva `feat/daemon-reparte-el-backend` desde `main` al día.
  2. **Leer cómo quedaron los contratos**, sin dar nada por hecho, y anotar `fichero:línea`:
     `_inflight_espera_local`, dónde se filtra lo que llega a `/api/inflight` (hoy
     `inflight_snapshot`), `estadoModelo` y su fila 3, `renderInflight`, `ChatResult`, `_post_chat`,
     `_log_event` y sus llamadas, `_run_chat`, `_con_respaldo`, `_ModeloVigente`, el bloque de
     `local_status`, `checks.CHECKS` (tienen que ser 22) y las frases de tamaño de `checks.py`,
     `_NUMERO` y `_NUMERO_DE_CHECKS`. Si el ayudante de `espera_local` cambió de firma o la fila 3 ya
     no vale para cualquier motivo, **se para** y se lleva a la sesión principal: este plan no
     redefine el contrato del panel.
  3. Línea base: `bash ~/.claude/scripts/pesado.sh uv run pytest -q` en verde, con el conteo.
  4. **llama-swap de prueba disponible**: `D:\Projects\llms\llama-swap-v255\llama-swap.exe`
     existe y `--version` dice v255. Si no, se para (T2 lo necesita).
  5. **Plazo de una tool MCP en los clientes** (caso límite «Plazos de los clientes MCP»): con la
     documentación oficial (agente `claude-code-guide` para Claude Code; la documentación de Codex
     para Codex), qué plazo aplica cada uno a una llamada de tool y cómo se sube (en Claude Code,
     `MCP_TOOL_TIMEOUT`; en Codex, `tool_timeout_sec` por servidor). Se anota con la fuente; T16 lo
     documenta. No se cambia ninguna configuración.
  6. **Hilos de anyio** (REQ-007, «Cancelación»): leer en el SDK instalado qué limitador usa
     `anyio.to_thread.run_sync` para las tools síncronas (`func_metadata.py:164`) y su tamaño (40
     por defecto), y qué más lo comparte en el daemon: el MCP y el panel van en la misma app
     (`daemon.py:211-216`) y los endpoints `def` del panel (`/api/inflight`, `/api/events`…) también
     piden hilo. **Pico de operaciones simultáneas** de los logs de uso de los últimos 60 días (máximo
     de eventos que se solapan en el tiempo, de cualquier tool). Se anota; T10 lo usa como umbral.
  7. **Ventanas de medición abiertas**: anotar las de P-4 y F1 (memoria del repo) para que la tanda
     (T5) y la verificación (T17) las registren como excluidas.
  8. **Config real**: `sha256` de `D:\Projects\llms\llama-swap\config.yaml` y la copia
     `config.yaml.pre-daemon-reparte-<AAAAMMDD-HHMMSS>.bak` junto a ella (ver «Comprobación de la
     config real al cerrar cada ola»). La lectura del fichero no imprime su contenido.
- **Rollback:** nada que revertir (la copia de la config se conserva).

### T1 — Enmienda de F3 (ola 0, mismo agente que T0)

- **Ficheros:** `.sdd/changes/delegacion-precisa-y-fiable/spec.md` (solo el punto nuevo).
- **Requisitos:** REQ-037.
- **Qué se hace:**
  1. Añadir a «Cambios respecto al original» de la spec de F3 el punto «Enmienda del 2026-10-06
     (`daemon-reparte-el-backend`, decisión del usuario)», con la tabla de REQ-037 copiada **sin
     cambios** y el enlace a `../daemon-reparte-el-backend/spec.md`. El texto heredado de F3 no se
     reescribe. Antes, comprobar que las líneas que cita la tabla (`:283-296`, `:351-355`,
     `:528-533`, `:234-235`, `:505-507`, `:376`, `:384`, `:435`) siguen diciendo lo que la tabla dice
     que dicen; si alguna se movió, se corrige la referencia en la enmienda, no el texto de F3.
  2. Anotar en `verification.md` la **hora de la enmienda** (ISO 8601 en UTC, la de la escritura
     del punto) y el `sha256` del fichero de F3 después de escribirlo.
  3. **Sin transiciones.** El harness no deja retroceder F3 (`implementing → specifying` no está
     permitida, `src/core/sdd.js:58-67`), las transiciones no tocan los gates y no hay `reject`: el
     gate `spec` de F3 **sigue `approved`** con la aprobación vieja, que no dice nada de la
     enmienda. El control se apoya en otra cosa: un evento de aprobación **nuevo**, como el
     precedente del 2026-09-15 (el historial de F3 tiene una reaprobación de `spec` estando en
     `implementing`).
  4. **Pregunta explícita al usuario** (la hace la sesión principal, en llano): «Para quitar el
     residente y que el código y el largo no caigan nunca al mecánico, hay que enmendar F3. La
     enmienda está escrita en su spec (tabla de qué cambia). ¿Apruebas de nuevo la spec de F3 con
     esa enmienda?». Con su sí, y solo entonces:
     `personal-harness sdd approve delegacion-precisa-y-fiable spec --evidence "Enmienda del 2026-10-06 (daemon-reparte-el-backend): sin residente; cargado en lugar de residente; código y largo nunca al mecánico; capacidad solo a cargado; el salto suelta la plaza. Aprobada por el usuario el <fecha>, en respuesta a la pregunta explícita de la sesión principal: <su respuesta literal>"`.
     Con un no, se para y se lleva a la sesión principal: el bloque C no puede seguir como está.
- **Control (lo ejecuta T17.2):** en el `history` de
  `.sdd/changes/delegacion-precisa-y-fiable/state.json` existe un evento `type: "gate"`,
  `gate: "spec"`, `status: "approved"`, con `at` **posterior** a la hora de la enmienda del paso 2.
  Se comprueba con un script de lectura, no a ojo. Sin ese evento, **el PR no se mezcla**. Puede dar
  otro resultado: hoy el último evento así es del 2026-09-15, anterior a cualquier enmienda.
- **Bloqueo explícito:** T12 (bloque C) puede implementarse antes de la respuesta, pero la mezcla
  espera al control.
- **Rollback:** quitar el punto añadido de la spec de F3. El harness no se toca: un evento de
  aprobación que ya existe no se borra a mano.

### T2 — llama-swap v255 de prueba: TTL, carrera, alias y recarga (ola 1)

- **Ficheros:** `tests/servidor_falso_llama.py` (servidor OpenAI mínimo en Python que responde
  `/v1/chat/completions` y `/health` con un retraso configurable y apunta la hora de llegada de
  cada petición), `tests/llamaswap_de_prueba.py` (fixture y ayudante: lanza
  `llama-swap-v255\llama-swap.exe` en un puerto libre con una config en `tmp_path` cuyos `cmd`
  arrancan el servidor falso con `${PORT}`, su **propio** `store` en `tmp_path`, `-watch-config`
  activable; lo para siempre en el `finally`), `tests/test_llamaswap_de_prueba.py`,
  `scripts/dev/medir_carrera_ttl.py`.
- **Requisitos:** controles «Carrera real y semántica del TTL» y «Recarga con `-watch-config`».
  Produce el insumo de REQ-013 (margen), de REQ-034 (cuatro salidas y si se cortan las peticiones)
  y el ayudante que usan T13 y T15.
- **Qué se hace y qué puede salir distinto:**
  - (a) Un modelo con `ttl: 2` y una petición de 3 s: no se descarga mientras dura (`/running` lo
    da `ready` a 1, 2 y 3 s) y sí entre 2 y 4 s después de terminar. **Si no**, la lectura de
    `process_command.go` está mal: se para, y REQ-013 se reescribe antes de T15 (spec reabierta).
  - (b) `medir_carrera_ttl.py`: 200 decisiones simuladas (las tres consultas de REQ-013 con tope de
    1 s y, al acabar, la petición), y el p99 entre el fin del cálculo y la llegada al servidor falso.
    **Si p99 + 1 s > 5 s**, el margen se sube antes de T15 y se avisa a la sesión principal.
  - (c) Una petición por alias aparece en `/api/metrics/activity` con el id real. Si aparece con el
    alias, T15 aplica el caso límite «Alias» (la consulta pide el id real y sus alias).
  - (d) Las cuatro salidas de la recarga, escribiendo el fichero **directamente** (el CLI aún no
    existe): recarga válida → «configuration reloaded» en `/api/events`; YAML que `load.go` rechaza
    → «failed to reload config» y la config vieja sigue sirviendo; sin `-watch-config` → nada en
    10 s; llama-swap apagado → conexión rechazada. Y una petición de 8 s en curso al escribir: ¿se
    corta? Se anota tal cual; T13 decide con eso si el aviso de REQ-034 se suaviza.
  - (e) La foto `inflight` de la carga inicial de `/api/events` llega en menos de 1 s con el
    historial de logs lleno (forzar 100 KB de log con peticiones previas), y trae las peticiones de
    otro cliente (un segundo proceso que manda una petición larga).
- **Tests:** los de (a), (c), (d) y (e) en `tests/test_llamaswap_de_prueba.py` con el marcador
  `llamaswap_real`. Si el binario no está, se saltan con `skip`, **pero** T2, T13 y T17 exigen en
  esta PC `pytest -rs` sin ningún salto en ese fichero (guarda de «esto llegó a comprobar algo»).
  Control de cada uno: (b) **mutante del ayudante**: la fixture sin `-watch-config` → el test de
  recarga válida falla en `assert salida == "recargó"`; con `ttl: 0` en vez de `2` → falla
  `assert not cargado_a_los_4s`.
- **Verificación:** `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_llamaswap_de_prueba.py -rs -q`
  y `bash ~/.claude/scripts/pesado.sh uv run python scripts/dev/medir_carrera_ttl.py`, con salida
  en `evidencias/T2.md`. **Procesos:** la fixture apunta el PID de cada proceso que lanza
  (llama-swap de prueba y servidores falsos, que son sus hijos) y, al terminar, comprueba que
  **esos PID** ya no existen; si alguno sigue, lo termina **por PID** (y su árbol, con
  `taskkill /PID <pid> /T /F`) y el test falla con «la fixture dejó vivo el PID …». Nunca por
  nombre: el llama-swap real es el mismo ejecutable. Un test de la fixture lo comprueba: el PID del
  llama-swap real (buscado **antes** de lanzar, en la lista de procesos, por su línea de órdenes
  con `--listen 127.0.0.1:9292`; solo se lee, nunca se toca) sigue vivo y con el mismo PID al
  terminar. Si no hay llama-swap real en marcha, ese test lo anota y no comprueba nada más.
- **Rollback:** borrar los ficheros nuevos.

### T3 — Control de lentitud con datos reales (ola 1)

- **Ficheros:** `scripts/medir_lentitud.py`, `tests/test_medir_lentitud.py` (nuevos). Sustituye a
  `scratchpad/sdd-daemon/umbral_lento.py`.
- **Requisitos:** controles «Umbral de lentitud: la regla exacta» y «Lentitud y tamaño de la
  entrada»; decide la forma de REQ-025 **antes** de T9.
- **Qué se hace:**
  1. Copia de solo lectura de `metrics.db` (con `-wal` y `-shm`) al scratchpad, y lectura de los
     `usage-*.jsonl` de `config.LOG_DIR`. El script implementa la **regla exacta** de la spec: por
     modelo, eventos en orden temporal, ventana de los 50 últimos correctos con `tokens_out ≥ 8`,
     mínimo 10, mediana de `tok_s` de generación, `lento` si `ritmo_rel < 0,5`. Las filas se cruzan
     con el log como en el insumo y se agrupan por evento.
  2. (a) Sobre las filas **de la PC**: porcentaje de eventos marcados. **Si pasa del 5 %**, se para y
     el umbral se revisa con el usuario antes de T9/T14.
  3. (b) **Control positivo de la regla**: la misma regla sobre las filas de Qwen3.6 de todos los
     orígenes marca las 570, 571 y 573. **Si no las marca, la regla está mal**: se corrige el script,
     no el umbral.
  4. Mediana de generación por tramos de entrada (`< 2k`, `2k–10k`, `> 10k` tokens). **Si el tramo
     de más de 10k es menor que 0,75 × el de menos de 2k**, la referencia va por tramos; si no, una
     sola. Se cuentan los falsos positivos con entradas de más de 10k tokens con la regla elegida.
  5. La decisión («una referencia» o «por tramos») y las cifras van a `evidencias/T3.md` con las
     ventanas de fechas usadas.
- **Tests (`tests/test_medir_lentitud.py`, datos sintéticos):**

  | Test | Control | Debe fallar con el mutante en |
  |---|---|---|
  | Ventana de 50: con 60 eventos, la mediana usa los 50 últimos | (b) | Mutante: mediana de toda la historia → falla `assert ref == 40.0` (el guion pone 10 eventos viejos a 100 tok/s: muta porque entran en la mediana) |
  | Mínimo de 10: el evento 10.º no tiene referencia, el 11.º sí | (b) | Mutante: mínimo 9 → falla `assert eventos[9].get("ritmo_rel") is None` |
  | `tokens_out < 8` no entra en la ventana | (b) | Mutante: sin el filtro → falla `assert ref == …` (el guion mete eventos de 3 tokens a 5 tok/s) |
  | La referencia no mira el futuro (orden temporal) | (b) | Mutante: ordenar por `tok_s` → falla `assert marcados == [12]` |
  | Por tramos: un evento de 12k tokens a 25 tok/s con mediana corta 40 y larga 26 no es lento | (b) | Mutante: una sola referencia → falla `assert not lento` |
- **Verificación:** `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_medir_lentitud.py -q`
  y la corrida real, con salida en `evidencias/T3.md`.
- **Rollback:** borrar los ficheros nuevos.

### T4 — Corpus, puntuadores, trampas, reglas, hoja y veredicto, sin cargar modelos (ola 1)

- **Ficheros:** `src/local_delegate/huella.py`, `tests/test_huella.py`, `scripts/construir_corpus.py`
  (subcomando `afinidad`), `tests/test_corpus.py`, `scripts/hoja_pares.py` (subcomandos
  `generar-commit` y `leer-commit`), `tests/test_hoja_pares.py`, `scripts/analizar_benchmark.py`
  (subcomando `veredicto-afinidad`), `tests/test_analisis_benchmark.py`,
  `benchmarks/afinidad-2026-10/cases.json`, `trampas.json` y `reglas.json`.
- **Requisitos:** REQ-040, REQ-042 con su aclaración del 2026-10-06 (final de `spec.md`), REQ-043
  (programa del veredicto), y la huella de REQ-010. **Todo el criterio queda escrito en código y
  probado con datos sintéticos antes de que exista un solo resultado real.**
- **Qué se hace:**
  1. `huella.py`: `flags_del_cmd(cmd) -> dict` (los flags de REQ-010 y la ruta `-m`, en sus formas
     corta y larga, con el `cmd` plegado en varias líneas como en la config de hoy) y
     `huella(modelo_cfg, prompt_sistema) -> dict` (ruta, tamaño del GGUF, flags y `sha256` del
     prompt). En la config real de hoy, el 26B lleva `-ncmoe 12` y Qwen3.6 `-ncmoe 20`, **los dos en
     la forma corta**; ningún `cmd` real usa `--n-cpu-moe` (leído el 2026-10-06).
  2. **Corpus** (REQ-040) con `construir_corpus.py afinidad`, que **captura** rol, prompts y número
     de llamadas llamando a la tool real con el backend interceptado, como el de F2:
     - `local_classify` 8, `local_extract` 8, `local_translate` 4, `local_lint_summary` 4 (tamaño
       mecánico), `local_delegate` sin modelo 4, cada uno con su procedencia, `reference_ok`,
       `reference_bad` y el conjunto de respuestas aceptables declarado **antes** de medir, con las
       condiciones de la spec (etiquetas en inglés y texto en español, un `null`, números, una línea
       de log, Markdown con código…);
     - `local_commit_msg`: `commit-diff-19k` más 29 diffs elegidos por la **regla escrita** de
       REQ-040, aplicada por código (`git log` de `main` antes del 2026-10-06, sin merges, sin
       Dependabot ni `chore(deps)`, sin `chore: release`, diff de 2 000 a 20 000 chars, los más
       recientes; ampliaciones en el orden de la spec). La lista de hashes sale de la regla, nunca a
       mano, y queda en `cases.json`;
     - **9 casos `trampa`** (tres por juego, para la hoja 1 y para dos repeticiones posibles): los
       **9 commits siguientes** que da la misma regla después de los 30, marcados
       `"rol_en_hoja": "trampa"`. T5 corre los dos modelos sobre ellos. Nunca cuentan para los
       criterios 1 y 2, y ninguno coincide con un caso real: así **ningún diff ni mensaje sale dos
       veces en la hoja**;
     - `techo-commit-156k` y los 5 casos mecánicos de F2 como regresión, marcados como no
       discriminantes.
  3. **Puntuadores** de las tools mecánicas: exacto contra el conjunto aceptable (`classify`), JSON
     estricto con claves exactas (`extract`), conteo de títulos, listas y bloques y código byte a
     byte (`translate`), conteos contra la fuente (`lint_summary`), formato exacto (`delegate`).
  4. **Trampas, preparadas antes de la tanda** (REQ-042 aclarado): una por caso `trampa`, con los
     tres tipos en cada juego (*misma zona*, *lo secundario*, *genérico*). Cada una se escribe en dos
     formas en `trampas.json`, porque su forma tiene que copiar la del mensaje con el que se empareja,
     que solo se conoce tras la tanda:
     - **asunto** (una línea, ≤ 72 caracteres, prefijo convencional, sin adornos). El de *misma zona*
       es el asunto real de otro commit (fuera de los 30 y de los 9) que toca el fichero más cambiado
       del caso trampa, elegido por código **entre los asuntos de ≤ 72 caracteres**; si no hay
       ninguno, el siguiente fichero más cambiado. Los de *lo secundario* y *genérico* los redacta el
       agente con la regla escrita en `trampas.json` (qué cambio secundario nombra y por qué es
       secundario);
     - **cuerpo** de reserva: hasta 5 líneas, con la misma regla de cada tipo (el de *misma zona*,
       con el cuerpo real de ese commit si lo tiene; si no, lo secundario del diff dicho sin
       inventar).

     **Regla de forma, escrita antes de la tanda y aplicada por el programa:** si el mensaje del
     modelo emparejado tiene cuerpo, la trampa lleva el asunto más tantas líneas de su cuerpo como
     líneas de cuerpo tenga ese mensaje (como mucho 5); si no lo tiene, solo el asunto. Mismo
     idioma que las salidas de los modelos con el prompt de producción (comprobado con las de F2 en
     `benchmarks/catalogo-2026-09/resultados/`). El `sha256` de `trampas.json` va a
     `evidencias/T4.md` **antes** de que empiece T5.
  5. **`reglas.json`, parámetros en un solo sitio** (los leen `hoja_pares.py` y
     `analizar_benchmark.py`; ningún otro sitio tiene estos números):
     - `max_inventa_26b`: el máximo de mensajes del 26B con «inventa = sí» que todavía aprueba. La
       spec dice «menos del 10 %», es decir, **2**. **Pendiente del usuario**: la propuesta más
       estricta, «se descarta si inventa en más de 1 de los 30», es **1**;
     - `preguntas_opcionales`: lista de preguntas que la hoja pliega como «si te apetece» y el
       lector no exige. Hoy `[]`. **Pendiente del usuario**: la propuesta es
       `["principal", "especifico"]` (no deciden). «Inventa» no puede ser opcional: el lector lo
       rechaza;
     - `formato`: la regla con la que el **programa** calcula «formato» (primera línea ≤ 72
       caracteres; prefijo convencional `^(feat|fix|docs|refactor|perf|test|build|ci|chore|style|revert)(\([^)]+\))?!?: `;
       sin adornos: ni vallas de código, ni comillas que envuelvan el mensaje, ni encabezados
       Markdown, ni frases de presentación). «Formato» ya no se le pregunta al usuario: no decide y
       es mecánico;
     - `parada_anticipada`: `true`.

     Los dos valores pendientes **no los fija este plan**. La sesión principal los confirma con el
     usuario; T4 los escribe tal como lleguen y, antes de que T5 genere la hoja 1, se anota el
     `sha256` de `reglas.json`. Desde ahí, el fichero no cambia: cambiar una regla después de ver
     datos invalida la hoja.
  6. **Hoja a ciegas** (`hoja_pares.py generar-commit`), para el usuario (cómo se le presenta: T6):
     - 30 pares reales (26B contra Qwen3.6, lados al azar) y 3 pares trampa (cada uno, la trampa
       contra el mensaje de un modelo elegido al azar **para el mismo diff trampa**), en posiciones
       al azar, con la semilla registrada en la clave; los pares se numeran **después** de barajar;
     - salida: `hoja/hoja-<n>.html` (una sola página, sin red ni recursos externos: CSS y JS en
       línea), `hoja/hoja-<n>.md` (la misma hoja en texto, de respaldo) y `clave/clave-<n>.json`,
       **en otra carpeta** que el usuario no abre; solo la lee el veredicto;
     - por par: el diff completo (plegable, monoespaciado, con «N ficheros, +X −Y»), y los mensajes
       A y B **tal como los devuelve la tool**, en monoespaciado y con los saltos de línea visibles.
       Sin contador de caracteres: «formato» lo calcula el programa;
     - por mensaje, **«inventa»** (sí/no: «¿dice algo que el diff no hace?»; lo que se deja fuera no
       se marca aquí), en los dos mensajes aunque solo cuente el del 26B (preguntarlo en uno solo
       rompería la ceguera); y «lo principal» (sí/parcial/no) y «específico» (sí/no), plegadas como
       opcionales si `reglas.json` lo dice. Por par, **preferencia** A, B o empate, **después** de
       las marcas;
     - arriba, las instrucciones con los criterios literales, el tiempo estimado (solo con
       «inventa» y la preferencia, unos 45–60 minutos; con «lo principal» y «específico»
       obligatorias, 60–90) y que se puede hacer en varias sentadas;
     - el progreso se guarda en el navegador (`localStorage`, con el id de la hoja) para retomarlo;
       un contador «faltan N respuestas»; el botón **«Descargar respuestas»** genera
       `respuestas-<n>.json` (con el `sha256` de la hoja), y el mismo JSON en un cuadro de texto
       para copiarlo si el navegador no deja descargar. En la hoja `.md`, las mismas preguntas como
       líneas `Inventa A (s/n):` … `Mejor (A/B/=):` que el lector también entiende;
     - **parada anticipada**: el botón «¿Puedo parar ya?» descarga las respuestas parciales. La
       página no sabe nada (no lleva la clave); es `leer-commit --parcial` el que responde **solo**
       «puedes parar» o «sigue», sin decir hacia dónde va. Responde «puedes parar» si se cumplen las
       dos cosas: las 3 trampas están contestadas y la hoja vale (criterio 0), **y** el desenlace ya
       no puede cambiar con los pares que faltan (el 26B ya pasa de `max_inventa_26b`, o `v − c` es
       mayor que los pares reales sin contestar). Si no, «sigue»;
     - **la hoja no contiene** ningún id de modelo, etiqueta de configuración, latencia, ni número
       de tokens, y los mensajes trampa no llevan ninguna marca.
  7. **Lector** (`hoja_pares.py leer-commit`): valida que las respuestas son de **esa** hoja
     (`sha256`), que no falta ninguna de las obligatorias según `reglas.json` (o, con `--parcial`,
     solo lo que pide la parada) y que los valores son válidos. Si falta algo, lista qué y no produce
     nada.
  8. **Veredicto** (`analizar_benchmark.py veredicto-afinidad`): aplica «Criterio de aceptación de
     las celdas» **literalmente**, con el orden de desenlaces escrito (mecánicas: 1 → `sin base`;
     2–6 → `rechazada`; commit: 0 → `sin base`, 1–3 → `rechazada`), con `max_inventa_26b` de
     `reglas.json`, las trampas solo para el criterio 0 y excluidas de los criterios 1 y 2, la carga
     en frío mediana de una copia de `metrics.db` para el criterio 6, y «formato» calculado con la
     regla de `reglas.json` (se publica, no decide). Copia la **huella** de cada celda de
     `huellas.json` (T5). Escribe `veredicto.json` y la tabla Markdown para `verification.md`.
     Ninguna celda se aprueba a mano: no hay opción para forzar un estado. **Ni `hoja_pares.py` ni
     `analizar_benchmark.py` importan `local_delegate`.**
- **Tests:**

  | Test | Control | Debe fallar con el mutante en |
  |---|---|---|
  | `test_huella.py::test_lee_la_forma_corta_de_la_config_real`: sobre una copia de los `cmd` plegados de hoy (claves falsas), el 26B da `n_cpu_moe == 12` y Qwen3.6 `20`, `--ctx-size 38400` y `16384`, la ruta `-m`, y `--mmproj` en el 12B | (b) | Mutante «solo la forma larga `--n-cpu-moe`» → falla `assert f["n_cpu_moe"] == 12` en el 26B (da `None`). **Comprobado** |
  | `test_huella.py::test_lee_la_forma_larga`: un `cmd` **sintético** con `--n-cpu-moe 20` | (b) | Mutante «solo la forma corta `-ncmoe`» → falla `assert f["n_cpu_moe"] == 20` (da `None`). **Comprobado**. Con los `cmd` reales este mutante no muta (todos usan la forma corta): por eso hace falta el sintético |
  | `test_huella.py`: dos huellas que solo difieren en `-ncmoe` son distintas | (b) | Mutante: la huella sin flags → falla `assert h1 != h2` |
  | `test_corpus.py`: la regla de selección de commits sobre un repo git sintético en `tmp_path` (merges, Dependabot, `chore(deps)`, `chore: release`, diffs fuera de rango y fechas) elige exactamente los 30 esperados, en orden, y los 9 siguientes como `trampa` | (b) | Mutante: sin el filtro de `chore: release` → falla `assert elegidos == [...]` |
  | `test_corpus.py`: ningún caso `trampa` coincide con un caso real (hash ni diff) | (b) | Mutante: las trampas salen de los 30 → falla `assert not reales & trampas` |
  | `test_corpus.py`: cada caso mecánico tiene `reference_ok` con puntuación 1 y `reference_bad` con menos de 1 con **su** puntuador | guarda (criterio 1 en su parte del corpus) | Si falla, el caso está mal construido: se corrige el caso |
  | `test_corpus.py`: la trampa *misma zona* elegida tiene asunto de ≤ 72 caracteres, y con un fichero cuyo único commit candidato tiene 89 se pasa al siguiente fichero | (b) | Mutante: sin el filtro de longitud → falla `assert len(asunto) <= 72` |
  | `test_hoja_pares.py::test_la_hoja_no_delata_a_nadie`: ni el HTML ni el `.md` contienen ningún id de modelo del catálogo ni los `label`; la clave sí (control positivo de la búsqueda); **ningún diff ni mensaje aparece dos veces**; y la proporción de «tiene cuerpo» de las trampas es la de sus pares | (b) | Mutante 1: el título del par lleva el `label` → falla `assert not delatores`. Mutante 2: la trampa siempre de una línea → falla `assert forma(trampa) == forma(pareja)` con una pareja con cuerpo. Mutante 3: el par trampa con el diff de un caso real → falla `assert not repetidos` |
  | `test_hoja_pares.py::test_la_clave_no_esta_junto_a_la_hoja` | (b) | Mutante: clave en `hoja/` → falla `assert not (hoja_dir / "clave-1.json").exists()` |
  | `test_hoja_pares.py`: con la misma semilla, la misma hoja; las trampas caen en las posiciones de la clave y no siempre en las mismas con semillas distintas | (b) | Mutante: trampas siempre al final → falla `assert posiciones != [31, 32, 33]` |
  | `test_hoja_pares.py`: el JS de la hoja, extraído y corrido con node (como `test_dashboard_js.py`), genera un JSON que `leer-commit` acepta; con una respuesta obligatoria menos, `leer-commit` dice cuál falta | (b) | Mutante: el exportador omite «inventa» de B → falla `assert faltan == []` |
  | `test_hoja_pares.py`: con `preguntas_opcionales = ["principal", "especifico"]`, una hoja sin esas respuestas se acepta; con `[]`, no; y con `["inventa"]`, `reglas.json` se rechaza | (b) | Mutante: el lector ignora `reglas.json` → falla `assert aceptada` en el primer caso |
  | `test_hoja_pares.py::test_respuestas_de_otra_hoja`: respuestas **completas** de una hoja con los mismos pares y otra semilla → `pytest.raises(SystemExit, match="sha256")` | (b) | Mutante: sin comprobar el `sha256` → el lector acepta (los pares están todos) y falla el `raises`. **Comprobado** (con pares que faltan, el mutante también saldría, por la completitud: por eso las respuestas de prueba están completas) |
  | `test_hoja_pares.py::test_parada_anticipada`: un caso decidido (trampas válidas y el 26B con `max_inventa_26b + 1` «inventa») → «puedes parar»; uno sin decidir (trampas válidas, `v − c` = pares que faltan) → «sigue»; trampas sin contestar → «sigue»; y la salida nunca contiene «26B», «Qwen» ni «aprob» | (b) | Mutante 1: `v − c >= faltan` → falla `assert salida == "sigue"` en el caso sin decidir. Mutante 2: no exigir las trampas → falla en el tercero |
  | `test_analisis_benchmark.py`: celda mecánica: criterio 1 falla y el 2 también → `sin base`, nunca `rechazada` | (b) | Mutante: evaluar en otro orden → falla `assert estado == "sin base"` |
  | `test_analisis_benchmark.py`: commit, con `max_inventa_26b` del fichero de prueba: con 2 y 2 «inventa» pasa el 1, con 3 `rechazada`; con 1 y 2 «inventa», `rechazada` | (b) | Mutante: número fijo `<= 2` en el código en vez de leer `reglas.json` → falla `assert estado == "rechazada"` con `max = 1` y 2 «inventa» |
  | `test_analisis_benchmark.py`: `c = v` → no pierde; empates par a par no suman | (b) | Mutante: `c > v` → falla `assert estado == "aprobada"` con 12/12/6 |
  | `test_analisis_benchmark.py`: el «inventa» del mensaje real dentro de un par trampa no cuenta para el criterio 1 | (b) | Mutante: contar los 33 → falla `assert criterios["inventa"]["n"] == 30` |
  | `test_analisis_benchmark.py`: 1 de 3 trampas marcadas como peores → `sin base` y el informe dice «repetir hoja» | (b) | Mutante: umbral 1 → falla `assert estado == "sin base"` |
  | `test_analisis_benchmark.py`: criterio 3a (una de las 3 corridas del techo falla) y 3b (un `length` del 26B donde Qwen3.6 terminó) → `rechazada` aunque gane la hoja | (b) | Mutante: sin el 3b → falla `assert estado == "rechazada"` |
  | `test_analisis_benchmark.py`: «formato» calculado: `feat: x` sí; asunto de 73 caracteres no; mensaje entre vallas de código no; y no cambia el estado de la celda | (b) | Mutante: sin la comprobación de vallas → falla `assert not formato(m)` |
  | `test_analisis_benchmark.py`: `veredicto.json` copia la huella de `huellas.json` | (b) | Mutante: huella vacía → falla `assert celda["huella"] == esperada` |
  | `test_analisis_benchmark.py::test_no_importa_el_paquete` y su gemelo en `test_hoja_pares.py`: los subcomandos corren en un subproceso con `sys.modules["local_delegate"] = None` antes de cargar el script (cualquier `import local_delegate` lanza `ImportError`) | (b) | Mutante: `from local_delegate import huella` en el script → falla `assert proc.returncode == 0, proc.stderr` |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_huella.py tests/test_corpus.py tests/test_hoja_pares.py tests/test_analisis_benchmark.py -q`.
  Se genera una hoja de prueba con resultados **sintéticos** y se abre con Playwright (bajo
  `pesado.sh`) para comprobar que se puede contestar entera con el teclado y el ratón, que el
  progreso sobrevive a recargar la página, que «Descargar respuestas» y «¿Puedo parar ya?» producen
  el fichero, y cuánto se tarda en contestar un par (para la estimación de tiempo); captura en
  `evidencias/T4.md`. La hoja sintética se borra.
- **Rollback:** borrar los subcomandos y los ficheros nuevos; lo de F2 no cambia.

### T5 — Tanda con modelos reales y hoja para el usuario (ola 2)

- **Ficheros:** `benchmarks/afinidad-2026-10/resultados/*.jsonl`, `huellas.json`,
  `hoja/hoja-1.*`, `clave/clave-1.json`, `evidencias/T5.md`; escribe `verification.md`.
- **Requisitos:** REQ-041; criterios mecánicos de REQ-043; hoja 1 de REQ-042.
- **Condiciones previas** (se comprueban y se anotan; si alguna falla, no se empieza):
  1. **ventana elegida con el usuario**: la sesión principal le pide un hueco de unas horas en el
     que no vaya a usar la GPU (jugar, video) **ni otras sesiones que deleguen** (Codex, otro Claude
     Code, la Mac contra esta PC), y la tanda solo arranca dentro de ese hueco;
  2. `reglas.json` cerrado, con los dos valores pendientes ya confirmados por el usuario, y su
     `sha256` anotado; `trampas.json` con su `sha256` anotado en T4;
  3. ningún otro agente corre comandos pesados ni usa tools `local_*`;
  4. el daemon sin delegaciones en curso (`/api/inflight` vacío) y `/running` sin peticiones;
  5. cerradas las apps pesadas: el 26B ocupa ~11,7 GB de RAM del sistema.
- **Qué se hace:**
  1. **Huellas, primero**: con la config de ese momento y los prompts de producción,
     `huella.huella` para cada modelo y tool de la tanda, en `huellas.json`. Es el único paso de la
     evaluación que importa `local_delegate`, y en esta ola nadie edita `server.py`.
  2. `benchmark.py` con los flags de producción (el `cmd` de `config.yaml`), la temperatura de
     producción de cada tool, **una corrida por caso y modelo** con la semilla registrada (3 en el
     techo), cada modelo calentado con una llamada descartada; modelos y celdas de REQ-041, más los
     **9 casos `trampa`** con los dos modelos de commit. Cada petición se apunta con su hora de
     salida y de llegada. Se lanza **como proceso independiente** (no como comando en segundo plano
     de Claude Code, que lo mata: memoria del repo), dentro del cerrojo:
     `bash ~/.claude/scripts/pesado.sh <lanzador que arranca la tanda y espera a que termine>`, con
     la salida a un fichero; el agente sondea el fichero.
  3. **Delegaciones ajenas en la ventana**: al terminar, sobre una copia de `metrics.db` y el log de
     uso del daemon, se buscan peticiones a llama-swap dentro de la ventana que no son de la tanda
     (no casan con ninguna petición apuntada en el paso 2, por modelo y hora). Cada caso cuya
     petición se solapó con una ajena **se repite** con la misma semilla antes del veredicto. Se
     anota cuántas peticiones ajenas hubo y cuántos casos se repitieron. Si la repetición vuelve a
     solaparse, se para y se pide al usuario otra ventana.
  4. Ventana de la tanda (inicio y fin en UTC, incluidas las repeticiones) en `verification.md`,
     como **excluida** de P-4 y F1.
  5. `veredicto-afinidad --solo-mecanicas`: estado de cada celda mecánica con sus criterios; tabla
     en `verification.md`. Esto no necesita al usuario.
  6. `hoja_pares.py generar-commit` → hoja 1, con el primer juego de trampas y la regla de forma de
     T4.4.
  7. Comprobación de que la hoja no delata (el test de T4, sobre la hoja real) y su `sha256` en
     `evidencias/T5.md`.
- **Si la tanda falla a mitad** (un OOM, el daemon interfiere): se anota, se reanuda por los casos
  que faltan con la misma semilla, y la ventana se amplía. No se descarta ningún resultado ya
  escrito.
- **Rollback:** los resultados se conservan; nada del producto cambia.

### T5b — Idioma del mensaje de commit (entre T5 y T6)

Insertada el 2026-10-07 tras la parada de T5 antes de la hoja (decisión del usuario: «Fijar el idioma y
repetir»). No sustituye nada de T5: las celdas mecánicas siguen como están.

- **Ficheros:** `src/local_delegate/config.py` (`commit_idioma()`), `src/local_delegate/server.py`
  (`_orden_de_idioma_de_commit`, usada en `local_commit_msg`), `scripts/construir_corpus.py` (la captura
  conserva la variable), `tests/test_commit_idioma.py`, `tests/test_corpus.py`,
  `benchmarks/afinidad-2026-10/cases.json`, `benchmarks/catalogo-2026-09/cases.json` (solo el `system` de
  sus 2 casos de commit), `benchmarks/afinidad-2026-10/resultados/` y `resultados-sin-idioma/`,
  `README.md`, `docs/wiki/Configuration.md`, `docs/wiki/Tools.md`, `examples/.env.example`,
  `CHANGELOG.md`; `evidencias/T5b.md`.
- **Requisitos:** REQ-044. No cambia REQ-040 a REQ-043 (el corpus conserva sus 30 reales, sus 9 trampas
  y el techo; solo cambia su `system`).
- **Qué se hace:**
  1. Variable por `_env*` y orden en el prompt de la llamada que redacta el mensaje (única o reduce).
  2. Tests y mutantes: con `es`, la orden de español (mutante: no leer la variable); sin variable, la
     del idioma del diff (mutante: quitar la rama); el reduce del map-reduce la lleva y el map no
     (mutantes: reduce sin la orden; map con ella); traducción del código (mutante: sin traducir).
  3. Corpus reconstruido **con `LOCAL_DELEGATE_COMMIT_IDIOMA=es`**; `afinidad --comprobar` con la misma
     variable da `ok`, y sin ella da diferencia (control). Solo cambia el `system` de los 40 casos de
     commit; `trampas.json` y `reglas.json` no cambian. El corpus de F2 (`catalogo-2026-09`), que
     recaptura los mismos dos casos de commit sin la variable, se regenera con el entorno limpio.
  4. Las filas de commit de `resultados/` (30 reales, 9 trampas y el techo) se mueven, sin borrar, a
     `resultados-sin-idioma/`. `tanda_afinidad.py --seco` tiene que dar 39 + 39 + 3 pendientes y 0 en
     las mecánicas.
- **Repetición de las celdas de commit:** la hace la sesión principal con el lanzador de la tanda, que
  debe llevar `LOCAL_DELEGATE_COMMIT_IDIOMA=es` y `--rehacer-huellas` (cambia solo `prompt_sha256` de
  `local_commit_msg` en los dos modelos). El techo hereda el entorno. Después siguen los pasos 3 a 7 de T5
  (delegaciones ajenas, ventana, hoja y su comprobación).
- **Rollback:** quitar la variable devuelve el prompt de «idioma del diff»; los resultados sin idioma se
  conservan donde están.

### T6 — Juicio del usuario y veredicto de commit (asíncrona, en paralelo con las olas 3 a 8)

No toca código ni `verification.md`: escribe en `benchmarks/afinidad-2026-10/` y en
`evidencias/T6.md`. No importa `local_delegate`: sus dos programas leen la huella de
`huellas.json` (lo garantiza `test_no_importa_el_paquete`, de T4). **T15 no empieza hasta que T6
cierra.**

- **Cómo se le presenta** (lo hace la sesión principal, en un mensaje corto y en llano):
  - qué es: «33 pares de mensajes de commit; en cada uno, dos mensajes para el mismo cambio, sin
    saber de qué modelo es cada uno»;
  - dónde: la ruta de `hoja/hoja-1.html`, que se abre con doble clic en el navegador (no necesita
    red);
  - qué marcar, con los criterios de REQ-042 y la regla ya confirmada, con el valor de
    `max_inventa_26b` que haya fijado («… y si inventa algo en N de 30 como mucho»);
  - **qué puede y qué no puede decir la hoja**: la tabla de potencia de la revisión del plan
    (con 30 pares y un 20 % de empates, un 26B «claramente peor» pasa con probabilidad 0,04; uno
    «igual», 0,54; uno «algo peor», 0,30), para que «aprobada» se lea como «no claramente peor».
    La misma tabla va a `verification.md`;
  - que puede parar antes con «¿Puedo parar ya?» si el resultado ya está decidido (la respuesta es
    solo «puedes parar» o «sigue»), y que puede hacerlo en varias sentadas (se guarda el progreso);
    unos 45–60 minutos si «lo principal» y «específico» quedan opcionales, 60–90 si no;
  - que **no** abra la carpeta `clave/`;
  - un límite conocido: aunque la hoja no lleve nombres, a lo largo de 30 pares se puede reconocer
    el estilo de cada modelo. No se puede ocultar sin cambiar lo que se juzga (la salida tal como
    llega). También va a `verification.md`;
  - cómo entregarlo: «Descargar respuestas» y dejar `respuestas-1.json` en
    `benchmarks/afinidad-2026-10/hoja/` (o decir dónde quedó); si el navegador no deja descargar,
    copiar el cuadro de texto en un mensaje.
- **Cómo se recogen:** un agente corre `hoja_pares.py leer-commit` (con `--parcial` si el usuario
  pidió parar; si falta algo, se le dice exactamente qué pares, sin repetir la hoja) y
  `veredicto-afinidad`:
  1. **criterio 0**: si el usuario marcó como peor la trampa en menos de 2 de 3 pares, la hoja no
     vale: se genera `hoja-2` con otro orden y el **segundo juego** de trampas (ya preparado en T4 y
     corrido en T5) y se repite el paso; como mucho dos repeticiones (hoja 3, tercer juego). Si
     tampoco vale, la celda queda `sin base`;
  2. con la hoja válida, el veredicto completo escribe `veredicto.json` y la tabla, con «formato»
     (calculado) y, si se contestaron, «lo principal» y «específico», publicados aunque no decidan;
  3. `evidencias/T6.md` con la tabla, las cifras y los `sha256` de hoja, respuestas, clave y
     `reglas.json`.
- **Si la hoja no se termina.** Al cerrar la ola 8, si T6 sigue abierta, la sesión principal le
  pregunta al usuario si quiere terminarla ahora. Si no, la celda de commit queda **no aprobada**
  (`sin base`, «hoja sin terminar»), `local_commit_msg` sigue como hoy, T15 lo deja escrito en
  `verification.md` y **el PR se cierra igual** con las celdas mecánicas que haya. Las respuestas
  parciales y la hoja se conservan; una evaluación posterior iría en un cambio aparte, con la huella
  recalculada.
- **Qué decide:** si la celda de commit no queda `aprobada`, **la afinidad de `local_commit_msg` no
  se implementa**; con las celdas mecánicas de T5, el conjunto de celdas aprobadas decide el alcance
  de T15 (REQ-018).
- **Rollback:** no aplica; si el usuario quiere rehacer la hoja, se usa un juego de trampas sin
  usar o, si no queda, se preparan otras (con sus casos, corridos por los dos modelos) **antes** de
  generar la hoja nueva.

### T7 — Lector de topología (ola 3)

- **Ficheros:** `src/local_delegate/topologia.py`, `tests/test_topologia.py`,
  `tests/fixtures/topologia/*.yaml` (nuevos).
- **Requisitos:** REQ-001, REQ-002 (lectura y motivos), REQ-009 (relectura), y la parte de lectura
  de REQ-023 y REQ-029 (`residentes()`, TTL efectivo).
- **Qué se hace:** `leer(ruta) -> Foto | SinTopologia(motivo)` con los motivos de REQ-002 (sin
  `LLAMASWAP_CONFIG`, sin PyYAML, ilegible, `matrix`, las dos sintaxis a la vez); la `Foto` lleva
  grupos con los valores por defecto de v255, `(default)`, alias → id, `choca(a, b)` según
  `EvictionFor` en los dos sentidos, `ttl_efectivo(m)`, `mmproj(m)` (vía `huella.flags_del_cmd`),
  `precargados()`, `residentes()` y `version`. `validar_como_load_go(datos)` con las reglas de
  REQ-033. `foto()` lee `config.llamaswap_config_path()` en caliente y cachea por `(ruta, mtime,
  tamaño)`. Un modelo que no está en la config: `choca` responde «compatible con todos» (REQ-002).
  *(Aclarado el 2026-10-07, tras la revisión de la ola 3: la fuente de `EvictionFor` es
  `internal/router/group.go:70-104` de llama-swap v255, commit `7761aa1`, no `src_group.go`; la ruta
  sale de `config.llamaswap_config_path()`, no de `config.LLAMASWAP_CONFIG`; y los motivos son los
  seis de la aclaración de REQ-002 en la spec, con «no cumple load.go» y forma inesperada incluidos.)*
- **Tests:**

  | Test | Control | Debe fallar con el mutante en |
  |---|---|---|
  | Tabla de casos contra `EvictionFor` (copiada de `internal/router/group.go:70-104` de v255, commit `7761aa1`, en el docstring): mismo grupo con `swap` y sin él; grupos distintos con `exclusive` en el de A y `persistent` en el de B; los dos sentidos; un modelo consigo mismo | (b) | Mutante 1: ignorar el defecto `exclusive: true` (grupo sin la clave) → falla el caso «grupo sin claves desaloja a otro grupo» (`assert choca(a, b)`). Mutante 2: solo un sentido → falla el caso con `exclusive` solo en B |
  | Modelos sin grupo en `(default)` chocan con todo lo no persistente | (b) | Mutante: sin `(default)` → falla `assert foto.choca("suelto", "gemma4-26b-a4b")` |
  | Las dos sintaxis: `groups` arriba y `routing.router.settings.groups`; las dos a la vez → `SinTopologia("dos sintaxis")`; `use: matrix` → `SinTopologia("matrix")` | (b) | Mutante (el 4 de `evidencias/T7.md`): solo `groups` arriba → falla **`assert not f.choca(...)`** con la sintaxis `routing` (`a` en un grupo `persistent` no exclusivo; `b` y `c` en otro). *Aclarado el 2026-10-07:* la forma original, `assert foto.choca(...)`, no tiene datos que la hagan mutar: si se ignora `routing.router.settings.groups`, todo cae en `(default)` y todos los pares chocan, igual que con la lectura correcta de un grupo exclusivo |
  | Alias: `choca("alias-del-26b", "qwen36-35b-a3b")` igual que con el id real | (b) | Mutante: sin resolver alias → falla el assert (un id desconocido es compatible) |
  | TTL efectivo: `-1` y ausencia → `globalTTL`; `residentes()` con la config de hoy está vacío y con la del 2026-09-15 también (TTL 600), y con `ttl: 0` contiene el modelo | (b) | Mutante: `-1` como infinito → falla `assert ttl_efectivo == 120` |
  | Relectura por `mtime`/tamaño: cambiar el fichero sube `version`; no tocarlo no relee (contador de lecturas) | (b) | Mutante: caché solo por ruta → falla `assert f2.version > f1.version` |
  | Copias de la config de hoy y de `config.yaml.pre-sin-residente-20261006.bak` con las claves sustituidas: un solo grupo `swap` en la primera; en la segunda, el 4B en un grupo `persistent` que no choca con el 26B | guarda de regresión | lo que dice la tabla de casos sobre ficheros reales |
- **Verificación:** `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_topologia.py tests/test_huella.py -q`,
  salida en `evidencias/T7.md`.
- **Rollback:** borrar el módulo; nadie lo usa hasta T10.

### T8 — Núcleo del turno (ola 3)

- **Ficheros:** `src/local_delegate/turno.py`, `tests/test_turno.py` (nuevos).
- **Requisitos:** REQ-003 a REQ-007 en su parte pura y de hilos, sin `server.py`.
- **Qué se hace:**
  1. **Núcleo puro**: `Estado(activos, cola)`, `Peticion(id, A, rol, orden_cadena,
     directos=frozenset())`,
     `evaluar(estado, choca, ahora, sin_progreso_desde, turno_max_s) -> Decision`: concesión de la
     cabeza con `A'` (REQ-003), E-1 (REQ-005), forzada (REQ-007, modelo del rol si está en `A`; si
     no, el primero de `A` en el orden de la cadena; nunca con alternativos), y «vuelve a la cabeza»
     cuando la elección no cabe (REQ-003, «Elección»). `directos` son los modelos de `A` que entran
     en `A'` por ser compatibles, como el rol (el destino de un salto); el rol, si está en `A`,
     siempre lo es. Elección atómica:
     `elegir(estado, op_id, candidatos, choca) -> tuple[Estado, str | None]` reduce la reserva al
     primer candidato, en orden, que esté en ella y no choque con los demás de `activos`; `None`
     quiere decir que volvió a la cabeza; `ValueError` si ningún candidato está en la reserva.
     `compatibles`, `reducir` y `volver` siguen existiendo como piezas, pero el daemon no las usa
     sueltas.
  2. **Envoltura**: `Turno` con `threading.Condition`; `pedir(peticion, al_esperar, al_conceder)`
     bloquea con `wait(timeout=1.0)` y reevalúa al despertar; `reducir(op, modelo)`, `soltar(op)`
     y la salida de la cola por abandono hacen `notify_all` (puntos 2 a 4 de REQ-003);
     `elegir(op_id, candidatos, al_esperar=None, al_conceder=None) -> str` hace la elección
     atómica bajo **un solo** cerrojo: reduce al primer candidato que cabe o, si ninguno cabe, vuelve
     a la cabeza, espera otra concesión y repite; puede lanzar `EsperaAbandonada`. Es la entrada que
     usa T10, no `reducir` suelto;
     `cambio_topologia(choca)` también notifica (punto 5); `en_vuelo()` es un gestor de contexto que mueve el
     contador y pone a cero el reloj de falta de progreso. Los ganchos `al_esperar` (posición, modelos
     en uso) y `al_conceder` los pone T10; aquí son funciones de prueba. El reloj es inyectable.
  3. Aserto de orden de adquisición: `pedir` lanza `AssertionError` si el hilo tiene plaza (marca en
     `threading.local` que pondrá `_run_chat`; aquí la ponen los tests).
  4. *(Aclarado el 2026-10-07, tras la revisión de la ola 3, con la spec, «Aclaraciones posteriores a
     la aprobación»):* `A'` incluye el destino de un salto vía `directos`, y los demás de `A` solo si
     ya están elegidos en `activos` y son compatibles con ellos; E-1 se mira al llegar y en cada
     evaluación posterior; una forzada pone a cero el reloj de falta de progreso y hay como mucho una
     por evaluación.
- **Tests (`tests/test_turno.py`):** los del núcleo con reloj simulado, sin dormir; los de la
  envoltura con hilos y latencias de milisegundos y un tope propio de 2 s.

  | Test | Control | Debe fallar con el mutante en |
  |---|---|---|
  | Escenario «nadie se queda esperando para siempre»: 26B en `activos`, Qwen3.6 en cola, llegan tres del 26B → orden de servicio 26B, Qwen3.6, tres del 26B | (b) | Mutante: el 26B compatible con `activos` se cuela → falla `assert orden == [...]` |
  | Escenario «la afinidad no se cuela si alguien espera» (con `A` sintético {4B, 26B}) | (b) | Mutante: un alternativo ya en uso entra aunque haya cola → falla `assert concedida is None` |
  | Escenario «la afinidad se une si nadie espera» | guarda: el mutante anterior no debe romperlo | `assert concedida.reserva == {"gemma4-26b-a4b"}` |
  | Escenario «un residente compatible no espera (E-1)» con la topología del escenario | (b) | Mutante: sin E-1 → falla `assert concedida.id == "classify"` |
  | E-1 no se aplica si choca con lo que pide alguien de la cola | (b) | Mutante: E-1 mira solo `activos` → falla `assert concedida is None` |
  | Escenario «sin progreso»: forzada a los 600 s sin nadie que llegue ni salga | (b) | Mutante 1 (sin la comprobación periódica: `wait()` sin tope) → con la envoltura y reloj inyectado, falla `assert decision.forzada` tras 600 s simulados (se avanza el reloj y se deja despertar). Mutante 2 (mide la espera total, no la falta de progreso): con una llamada que termina en el 599, falla `assert not decision.forzada` a los 600 |
  | Escenario «llamada larga con plazo HTTP mayor que 600 s»: una llamada en vuelo de 700 s | (b) | Mutante: el reloj corre también con llamadas en vuelo → falla `assert not decision.forzada` a los 650 |
  | Forzada de un salto con `A = {destino}` → el destino; con el conjunto de `cargado` → el primero en el orden de la cadena | (b) | Mutante: siempre el rol → falla `assert decision.modelo == "gemma4-26b-a4b"` |
  | Escenario «cuando una reserva se reduce, la cola se vuelve a mirar» (W1 con {4B, 26B, Qwen3.6}, W2 del 26B) | (b) | Mutante: `reducir` sin `notify_all` → falla `assert w2_empezo < w1_termino` (con hilos; W1 hace 3 trozos de 50 ms) |
  | Una espera que sale de la cola por abandono deja pasar a la siguiente compatible | (b) | Mutante: el abandono sin `notify_all` → falla `assert concedida_a_tiempo` (la siguiente se concede en menos de 0,2 s; sin la notificación espera al tic, así que el test construye el `Turno` con `tic=5.0` —parámetro del constructor, 1 s por defecto— para que el mutante mute) |
  | `cambio_topologia()` concede a una espera que la topología nueva permite | (b) | Mutante: sin `notify_all` en el cambio → falla igual que el anterior |
  | Elección tras una forzada: si ningún modelo de `A'` es compatible sin contar la propia operación, vuelve a la **cabeza** | (b) | Mutante: vuelve al final → falla `assert estado.cola[0].id == op.id` |
  | Orden de adquisición: pedir turno con la marca de plaza puesta lanza `AssertionError` | (b) | Mutante: sin el aserto → falla `pytest.raises(AssertionError)` |
- **Verificación:** `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_turno.py -q`, salida
  en `evidencias/T8.md`. El fichero entero tarda menos de 10 s.
- **Rollback:** borrar el módulo; nadie lo usa hasta T10.

### T9 — Referencia de velocidad (ola 3)

- **Ficheros:** `src/local_delegate/ritmo.py`, `tests/test_ritmo.py` (nuevos).
- **Requisitos:** REQ-025 con la forma que decidió T3 (una referencia o por tramos), REQ-028 en su
  parte pura.
- **Qué se hace:** `Referencias` con una ventana por modelo (y por tramo, si toca) de los últimos 50
  `tok_s` de eventos correctos con `tokens_out ≥ 8`; `sembrar(lineas)` con el log del mes en curso y
  del anterior; `registrar(evento)`; `medir(modelo, tok_s, tokens_in) -> {ritmo_rel, lento} | {}`
  con el mínimo de 10, `round(…, 2)` y el umbral como argumento. Nunca lanza: entrada rara → `{}`.
  **Misma regla que `scripts/medir_lentitud.py`**: el script de T3 pasa a importar `ritmo.py` y el
  test de T3 se queda como guarda de las dos (una sola fuente).
- **Tests:** los cinco de T3 repetidos contra `ritmo.py` (mismo control (b), mismos mutantes), más:

  | Test | Control | Debe fallar con el mutante en |
  |---|---|---|
  | Escenario «una llamada lenta se distingue de una espera» (parte pura): 20 eventos con mediana 40,5 y una respuesta a 15 tok/s → `ritmo_rel == 0.37`, `lento is True` | (b) | Mutante: compara el prefill → falla `assert r["ritmo_rel"] == 0.37` (el guion pone `prefill_tok_s` alto) |
  | Con 9 muestras, `{}` | (b) | Mutante: mínimo 0 → falla `assert r == {}` |
  | `sembrar` lee el mes en curso y el anterior, no otros | (b) | Mutante: solo el mes en curso → falla `assert len(ventana) == 50` a día 2 del mes |
  | Una línea de log corrupta no rompe la siembra (12 líneas buenas y una rota) | (b) | El test envuelve `sembrar` en `try/except Exception as e` y convierte la excepción en el valor que mira el assert: `assert n == 12, f"la siembra no tolera una línea corrupta: {n}"`. Mutante: sin el `try` dentro de `sembrar` → falla ese `assert` con «excepcion JSONDecodeError», no con la excepción suelta. **Comprobado** |
- **Verificación:** `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_ritmo.py tests/test_medir_lentitud.py -q`,
  salida en `evidencias/T9.md`.
- **Rollback:** borrar el módulo; nadie lo usa hasta T14.

**Integración I3** (fin de la ola 3): suite completa, `ruff`, enlaces a `evidencias/T7.md`,
`T8.md` y `T9.md` desde `verification.md`.

### T10 — Turno en el daemon (ola 4)

- **Ficheros:** zona T10 de `server.py`, `config.py` (`TURNO_MAX_S`), `tests/conftest.py`, zona
  T10 de `web/metrics.py`, `tests/backend_mock.py` (modo que cuenta cambios), `tests/test_turno_daemon.py`
  (nuevo), `tests/test_panel_estados.py` (zona T10), `tests/test_metrics.py` (zona T10), y los
  tests existentes del inventario.
- **Requisitos:** REQ-002 a REQ-009 conectados al daemon, REQ-027 (palabras del motivo `"turno"`).
- **Qué se hace, en este orden:**
  1. **Inventario por ejecución** (antes de editar): con un corte que activa el turno en todas las
     operaciones sin cambiar nada más, correr la suite y anotar qué tests caen y por qué. Los que
     prueban que el salto ocupa la misma plaza (REQ-017 de F3) se reescriben para REQ-006 con el
     escenario equivalente; ninguno se borra sin sustituto. La lista va a `verification.md`.
  2. `config.TURNO_MAX_S = _env_float("LOCAL_DELEGATE_TURNO_MAX_S", 600.0)`.
  3. `_turno` global de `turno.Turno` y un `_topologia()` que devuelve la foto o el motivo (sin
     `LLAMASWAP_CONFIG`, sin extra, ilegible, `matrix`, dos sintaxis, no cumple load.go, backend no
     loopback → sin turno, REQ-002 con su aclaración del 2026-10-07).
  4. **Turno por operación** en `_chat`, `_chat_chunked` y `_chat_map_reduce` (y en la de imagen,
     que pasa por `_chat`): `A = {rol}` (sin bloque B), o `{model}` si es explícito; espera con
     `_inflight_espera_local(entry_id, "turno")` y el ayudante nuevo `_inflight_turno(entry_id,
     en_uso, posicion)`, que escribe y borra `turno_en_uso` y `turno_posicion`; al conceder, borra
     las tres claves. `inflight_snapshot` copia `turno_en_uso` y `turno_posicion` cuando están.
  5. `_run_chat` pone la marca de plaza en `threading.local` mientras la tiene (para el aserto), y el
     contador de llamadas en vuelo envuelve cada `_post_chat` (también sin turno).
  6. **Salto fuera de la plaza** (REQ-006): `_con_respaldo` se parte en `_intentar` (una llamada y su
     reintento sin schema, dentro de la plaza) y `_siguiente_salto` (la decisión, fuera); la
     operación suelta plaza y turno, pide turno con `A = {destino}` al final de la cola, y pide plaza.
     El tope de `MAX_CONCURRENT_REQUESTS` se mantiene porque la plaza es el mismo semáforo.
     *(Aclarado el 2026-10-07, tras la revisión de la ola 3):* el salto pide turno con
     `Peticion(A={destino}, directos={destino}, rol=<rol original>)`, y el paso `cargado` con
     `directos` vacío (su conjunto de REQ-019 solo entra si ya está elegido en `activos`). Con varios
     modelos en `A'`, la elección usa `Turno.elegir(op_id, candidatos, al_esperar, al_conceder)`, no
     `reducir` suelto. Cuando sube `topologia.foto().version`, el daemon llama a
     `Turno.cambio_topologia(foto.choca)` (REQ-009). Cualquier `SinTopologia`, sea cual sea su
     motivo, se trata como «sin turno» (REQ-002).
  7. `_log_event`: `espera_turno_ms` si es mayor que 0 y `turno: "forzado"` si lo fue.
  8. `local_status`: «Turno: sí (choques: …; en uso: …; esperan: N)» o «Turno: no (<motivo>)».
  9. `web/metrics.py`: en `estadoModelo`, el `title` con motivo `"turno"` dice «esperando turno del
     daemon (en uso: <modelos>)» con `turno_en_uso`; lo mismo en «En curso». **No** cambia la
     condición de la fila 3 ni la tabla de estados.
  10. **Hilos de anyio** (REQ-007). Hoy la espera de plaza ya bloquea un hilo
      (`_chat_slots.acquire()`), y `local_status`, `/api/inflight` y `/api/events` comparten el mismo
      limitador de 40 (el MCP y el panel van en la misma app). Con 40 esperas, nada contesta **por
      construcción**: por eso el umbral no es «40», sino la **línea base medida**. Medición, con la
      app del daemon en proceso (el MCP con el arnés de `test_clients.py` y el panel con
      `TestClient`, montados como en `daemon.py`), el mismo guion dos veces:
      - **línea base**: sin topología (sin turno), N operaciones que esperan **plaza** (el backend
        simulado retiene las dos plazas);
      - **con turno**: N operaciones que esperan **turno** (una operación del 26B retiene el turno y
        las N piden Qwen3.6).

      Para cada guion, el menor N con el que `local_status` **o** `GET /api/inflight` dejan de
      contestar en 2 s, subiendo N de 1 en 1 hasta 45. **Criterio, escrito antes de medir:** se para
      y se lleva a la sesión principal (con la propuesta de subir el limitador al arrancar el daemon,
      que no está en la spec) **solo si** el N con turno es **menor** que el de la línea base, **o**
      menor que 3 veces el pico de operaciones simultáneas que midió T0.6. Si no, se anotan los dos N
      y el pico. Además se deja escrito, y lo prueba T13: con el limitador agotado,
      `/api/llamaswap/estado` (también síncrono) no contesta a tiempo y el CLI responde «no se sabe»,
      que es la negativa segura.
- **Tests (`tests/test_turno_daemon.py` salvo que se diga otra cosa):** el `backend_mock` en modo
  «cuenta cambios» procesa una petición a la vez (como `-np 1` y el FIFO de llama-swap) y cuenta un
  cambio cada vez que el modelo servido difiere del anterior.

  | Test | Control | Debe fallar hoy / con el mutante en |
  |---|---|---|
  | Escenario «dos tools en paralelo ya no se quitan el modelo» (`local_commit_msg` de 3 trozos y `local_lint_summary` de 3 trozos, a la vez) | guarda + (a) | Guarda: el mismo guion **sin** topología da `cambios >= 3` (si no, el guion no discrimina y el test falla con «el guion no intercala»). Control (a): con la topología de hoy, hoy falla `assert cambios == 1`; después `linea_segunda.get("espera_turno_ms", 0) > 0` |
  | Escenario «el mismo modelo no se serializa de más» (dos `local_summarize` largos) | guarda + (b) | Guarda: el `backend_mock` tiene una barrera que solo deja contestar cuando las **dos** peticiones han llegado (con tope de 2 s y mensaje «no se solaparon»): demuestra que entraron en las dos plazas a la vez. Mutante: un turno exclusivo por operación (sin compartir modelo) → la segunda no llega hasta que acaba la primera, y falla la guarda con «no se solaparon» y, si se quita la guarda, `assert "espera_turno_ms" not in linea` en la segunda |
  | Escenario «dos saltos a la vez no bloquean» (`MAX_CONCURRENT_REQUESTS = 2`, `TURNO_MAX_S = 60`) | (b) | Mutante: el salto pide turno **sin** soltar la plaza (se desactiva el aserto para el mutante) → falla `assert c_termino.wait(2), "sin progreso: bloqueo turno/plaza"`. Muta porque A y B retienen las dos plazas y C no puede pedir la suya |
  | El salto suelta la plaza antes de pedir turno (orden de eventos registrado por espías en el semáforo y en `Turno.pedir`) | (b) | Mutante: soltar después → falla `assert eventos.index("soltar_plaza") < eventos.index("pedir_turno")` |
  | El turno y la plaza se liberan con una excepción inesperada del backend | (b) | Mutante: sin el `finally` del turno → falla `assert _turno.activos() == []` |
  | Escenario «la espera de turno se ve en el panel como espera local»: una operación esperando; se lee `/api/inflight` con `TestClient` y se pasa la entrada a `estadoModelo` con node (`tests/test_panel_estados.py`) | (b) | Mutante 1: escribir una clave propia (`esperando_turno: true`) en vez de `espera_local` → falla `assert fila.texto == "en cola local"` (da «procesando» con el modelo `ready`). Mutante 2: `inflight_snapshot` sin copiar `turno_en_uso` → falla `assert "en uso: gemma4-26b-a4b" in fila.title` |
  | Tras conceder, la entrada ya no lleva `espera_local` ni `turno_*`; si después espera plaza, lleva `"plaza"` | (a) | `assert entrada.get("espera_local") == "turno"` mientras espera (hoy nunca) |
  | Escenario «sin topología o con backend remoto, como hoy» (sin `LLAMASWAP_CONFIG`, con `matrix`, con `BASE_URL` no loopback), lanzando **dos operaciones que chocan a la vez**, como en el escenario de la spec | guarda + (b) | Guarda: el mismo guion con `BASE_URL` loopback y la topología de hoy **sí** da `espera_turno_ms > 0` en una de las dos (si no, el guion no puede ver la diferencia). Mutante: no mirar el origen → falla `assert "espera_turno_ms" not in linea` en las dos líneas con backend remoto |
  | `local_status` dice el turno y, sin topología, el motivo | (a) | `assert "Turno: no (sin LLAMASWAP_CONFIG)" in texto` |
  | Topología nueva en la siguiente concesión (cambiar el fichero con una operación en curso) | (b) | Mutante: `_topologia()` cacheada para siempre → falla `assert concedida_con_la_nueva` |
  | Un evento forzado lleva `turno: "forzado"` (con `TURNO_MAX_S` bajo y una operación con turno que no llama al backend) | (b) | Mutante: no pasar el campo → falla `assert linea.get("turno") == "forzado"` |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_turno_daemon.py tests/test_turno.py tests/test_panel_estados.py tests/test_metrics.py tests/test_respaldo.py tests/test_map_reduce.py tests/test_chunking.py tests/test_post_chat_caminos.py tests/test_observabilidad_respaldo.py -q`,
  `node --check` del JS y, después, la suite completa.
- **Rollback:** revertir; sin topología el daemon ya se comporta como hoy, así que una salida de
  emergencia es dejar `LLAMASWAP_CONFIG` vacío en el lanzador.

### T11 — Editor y CLI de residencia sobre copias (ola 5)

- **Ficheros:** `src/local_delegate/residencia.py`, `tests/test_residencia.py`,
  `tests/fixtures/residencia/` (nuevos), `src/local_delegate/llamaswap_config.py`,
  `tests/test_llamaswap_config.py`, `src/local_delegate/cli.py` (zona T11), `tests/conftest.py`
  (zona T11: la fixture que corta la consulta al daemon real).
- **Requisitos:** REQ-029 a REQ-033, REQ-035, REQ-038 (la parte de ficheros). La comprobación
  previa de REQ-034 y la vigía son de T13: aquí son una interfaz que devuelve «no se sabe», así que
  **toda escritura de T11 exige `--ahora`** (corte (c) para los tests de T13).
- **Qué se hace:**
  1. **Fixtures**: copias de la config de hoy, de `config.yaml.pre-sin-residente-20261006.bak` y de
     `config.yaml.pre-b10909-20260915.bak` (la del fin de línea mixto), con toda clave sustituida, y
     los YAML sintéticos de la tabla del control «Edición quirúrgica». Un test recorre los fixtures y
     falla si encuentra una cadena con forma de clave que no sea `clave-falsa-N`.
  2. `residencia.py`: `editar(bytes, cambios) -> bytes` con las marcas de `yaml.compose()`
     (reemplaza tramos de escalares, inserta líneas con la sangría y el fin de línea de la anterior,
     borra bloques), negativas de formato (flujo, anclas, alias, `<<:`, claves duplicadas, `matrix`,
     dos sintaxis), autocomprobación (`safe_load(resultado) == original + cambio` y
     `topologia.validar_como_load_go`), copia `<config>.<AAAAMMDD-HHMMSS>.bak` sin pisar (sufijo si
     existe), reemplazo atómico con temporal en la misma carpeta y `os.replace` con 5 reintentos a
     200 ms ante violación de compartición; `ninguno`, `fijar`, `ttl` y `restaurar`.
     *(Aclarado el 2026-10-07, tras la revisión de la ola 3):* el grupo que escribe `fijar` lleva
     `exclusive: false` **explícito**: el defecto de v255 es `exclusive: true`, y un grupo residente
     sin la clave desalojaría a los demás grupos al cargar. Y, para `residencia` y `--ninguno`, se
     documenta (en la ayuda y en la wiki de T16) que **sin `globalTTL` ni `ttl` todos los modelos
     tienen TTL efectivo 0** (`load.go`: `ttl` ausente o `-1` vale `globalTTL`, que por defecto es 0)
     y por eso salen como residentes (REQ-029); `--ninguno` exige entonces `--ttl` para todos
     (REQ-030) y, como no queda ningún TTL distinto de 0 que sugerir, el mensaje lo dice en vez de
     proponer uno (decisión del usuario, 2026-10-07).
  3. **Estimador** (`llamaswap_config.estimate_model_vram`): con `-ncmoe N`, resta los bytes de los
     tensores `blk.<i>.ffn_*_exps.*` de las capas `i < N` (diferencia entre offsets consecutivos de
     la tabla de tensores del GGUF) y suma el `--mmproj`. **Control con los GGUF reales** (solo la
     cabecera, bajo `pesado.sh`): las cuatro estimaciones entre −3 % y +10 % de lo medido en F2
     (`insumos/llamaswap-grupos.md` §2: 4B 3 270, 12B con mmproj 9 060, 26B `-ncmoe 12` 10 534,
     Qwen3.6 `-ncmoe 20` 10 120 MiB). Las cifras se calculan con los `-ncmoe` **medidos**, no con los
     de la config de hoy. El resultado fija la constante `ESTIMADOR_NCMOE_VALIDADO` (con el motivo y
     las cifras en su comentario): si una falla, `False`, y `--fijar` exige `--vram-modelo` para
     todos los implicados.
  4. `cli.py`: subparser `llamaswap` con `residencia` y sus opciones; la vista de REQ-029 con
     `topologia`; `init-llamaswap` con `--ttl-resident` 0, ayuda que presenta `--resident` como
     opt-in, y `.bak` con fecha (REQ-035).
  5. **Primero la fixture** (antes de cualquier test del CLI): en `tests/conftest.py`, una fixture
     **autouse** que apunta la consulta al daemon (puerto y token web que usa `doctor`) a un puerto
     local recién liberado, sin nadie escuchando. **Todo test del CLI** pasa `--config <tmp_path>`
     explícito, salvo `test_sin_config_no_se_sabe`, que prueba justo la ausencia.
- **Tests:**

  | Test | Control | Debe fallar con el mutante en |
  |---|---|---|
  | Tabla «Edición quirúrgica» (secuencias sangradas y sin sangrar, comentarios en línea y entre miembros, `ttl` insertado tras un `cmd` plegado entre comillas y tras `\|` y `>`, grupo al final sin salto final, fin de línea mixto, BOM, claves entre comillas, sintaxis `routing`): o el `diff` son solo las líneas pedidas, o una negativa con mensaje | (b) | Mutante: reescribir con `yaml.safe_dump` → falla `assert lineas_cambiadas == esperadas` (pierde los comentarios de la cabecera y cambia las comillas de `apiKeys`; el número exacto lo da el test) |
  | Anclas, alias, `<<:`, claves duplicadas, flujo → negativa con su motivo, fichero intacto (`sha256` igual); para las duplicadas, `pytest.raises(ErrorResidencia, match="clave duplicada")` | (b) | Mutante: sin la negativa de duplicadas → el editor cambia la **primera** aparición, `safe_load` se queda con la última y la autocomprobación lanza `ErrorResidencia` con **otro** mensaje («la autocomprobación no cuadra»): sin `match=` el mutante pasaría; con él, falla el `raises`. **Comprobado** |
  | `test_sin_config_no_se_sabe`: sin `--config`, con `LLAMASWAP_CONFIG` vacía y la consulta al daemon apuntada a un puerto muerto (fixture autouse), el CLI dice «no se sabe» y **no abre ningún fichero** (espía sobre `open`, `Path.read_bytes` y `Path.read_text` dentro de `residencia` y `cli`) | (b) | Mutante: caer a una ruta por defecto (`config.yaml` del directorio actual) → falla `assert abiertos == []` |
  | `test_la_fixture_corta_el_daemon_real`: con la fixture, la URL que usa el CLI para preguntar al daemon apunta a un puerto sin nadie escuchando | (b) | Mutante: fixture sin `autouse` → falla `assert puerto == puerto_muerto` |
  | Escenario «volver a "ningún residente" desde la config del 2026-09-15» | (a) contra el corte | `assert diff == esperado` (borra el grupo `resident`, añade `- gemma3-4b` a `swap`, no toca el TTL 600) |
  | `--ninguno` sin grupo `swap: true` → error con `--grupo`; con la config de hoy → «nada que cambiar» y `mtime` intacta | (b) | Mutante: escribir aunque no cambie nada → falla `assert os.stat(ruta).st_mtime_ns == antes` |
  | `--ttl 0` → remite a `--fijar`; `-1` solo con `globalTTL > 0` | (b) | Mutante: aceptar 0 → falla `pytest.raises(...)` |
  | Escenario «fijar un residente que no cabe» (`--vram-modelo` del escenario) | (b) | Mutante: sin la reserva → falla `assert "faltan 6,17 GiB" in salida` (sin reserva faltarían 4,17) |
  | Escenario «fijar el 4B con la config de hoy se acepta», y con el estimador si `ESTIMADOR_NCMOE_VALIDADO` | (b) | Mutante: `max` por la suma de los demás → falla `assert aceptado` |
  | `--fijar` escribe `exclusive: false` **explícito** en el grupo residente: el YAML resultante, leído con `safe_load`, tiene la clave en ese grupo con valor `False`, y `topologia` lo da como no exclusivo *(aclarado el 2026-10-07)* | (b) | Mutante: no escribir la clave (dejar el defecto de v255, `true`) → falla `assert grupo.get("exclusive") is False` y, con la foto, `assert not foto.choca(residente, "gemma4-26b-a4b")` |
  | `residencia` con una config sin `globalTTL` ni `ttl`: todos los modelos con TTL efectivo 0 y como residentes, y el texto lo explica *(aclarado el 2026-10-07)* | guarda | `assert set(vista.residentes) == set(modelos)` |
  | Escenario «ver la residencia»: «sin residente (recomendado)», 5 modelos con TTL 120 (el 12B, 30), sin claves ni `cmd` (busca `clave-falsa`, `--port` y `llama-server` en la salida) | (b) | Mutante: imprimir el `cmd` → falla `assert "llama-server" not in salida` |
  | Copia con fecha sin pisar: dos escrituras en el mismo segundo dan dos `.bak` | (b) | Mutante: sin sufijo → falla `assert len(baks) == 2` |
  | Reemplazo atómico: `os.replace` falla con `PermissionError(winerror=32)` dos veces y luego funciona → escrito; cinco veces → original intacto y sin temporal | (b) | Mutante: sin reintentos → falla `assert escrito` |
  | Escenario «restaurar una copia» (parte de ficheros) y un lector en bucle durante una restauración lenta | (b) | Mutante: copiar en dos pasos (truncar y escribir) → el lector ve un YAML a medias y falla `assert not vistos_rotos` |
  | `--dry-run` imprime solo las líneas cambiadas y oculta los valores de cualquier línea con `key` | (b) | Mutante: sin ocultar → falla `assert "clave-falsa" not in salida` |
  | Toda escritura sin `--ahora` se niega con «no se sabe si hay delegaciones en curso» (corte de T11) | (c) | Lo usa T13: tras T13, este test se reescribe con el escenario «sin credencial no se escribe a ciegas» |
  | Estimador: tabla de tensores sintética con expertos en las capas 0–3 y `-ncmoe 2` resta solo las capas 0 y 1 | (b) | Mutante: `i <= N` → falla `assert restado == bytes_capas_0_1` |
  | Ningún fixture lleva una clave real | guarda | descrito en el paso 1 |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_residencia.py tests/test_llamaswap_config.py tests/test_topologia.py -q`,
  el control del estimador con los GGUF reales (cifras a `verification.md`) y la suite completa.
- **Rollback:** revertir; el comando es nuevo y `init-llamaswap` solo cambia su valor por defecto y
  el nombre de su copia.

### T12 — Cadenas sin residente (ola 6)

- **Ficheros:** `cadenas.py`, zona T12 de `server.py`, zona T12 de `checks.py`,
  `tests/test_cadenas.py`, `tests/test_checks.py` (zona T12) y los tests del inventario.
- **Requisitos:** REQ-019 a REQ-023, y lo de REQ-037 que vive en el código.
- **Precondición:** T1 hecha (la enmienda está escrita). El gate de F3 puede estar pendiente; la
  mezcla espera (T17).
- **Qué se hace:**
  1. **Inventario por ejecución**: `rg -n "residente|resident|cadenas\.residente|defecto: el modelo del rol" tests/ src/`
     y, tras el cambio, la suite; cada test que caiga se reescribe al escenario de C que lo
     sustituye (tabla de REQ-037: «el modelo largo falla y responde el mecánico», «la entrada no cabe
     en el respaldo», «el modelo no cabe en la VRAM»). Lista en `verification.md`.
  2. `cadenas.py`: paso `CARGADO = "cargado"`; `residente`/`resident` en las variables como
     sinónimo, con la marca para el aviso; cadenas por defecto `code → cargado → long`,
     `long → cargado → code`, `mechanical → cargado → long`; `miembros_cargado(tool, fallido,
     propios, nadie_mas)` que **sin proveedor registrado devuelve `()`** sin tocar la red (el
     proveedor lo pone T15, si hay afinidad); `describir()` con «sin residente» o «residente: X»
     según `topologia.residentes()`.
  3. `server.py` (decisión de salto de T10): el paso `cargado` se resuelve en el momento del salto;
     vacío → se salta **sin gastar salto**; un fallo de capacidad solo salta a `cargado` y sin segundo
     salto; sin `cargado`, devuelve el error de siempre.
  4. `checks._probe_fallback`: «cadenas válidas; sin residente» (o «residente: X» con TTL 0), aviso
     si una variable usa `residente`, y el texto «usa roles (mechanical, long, code, cargado)».
- **Tests:**

  | Test | Control | Debe fallar hoy / con el mutante en |
  |---|---|---|
  | Escenario «código nunca cae al mecánico» (`backend_mock`: Qwen3.6 da error del modelo; el 4B «cargado» no importa porque no hay celdas) | (a) | `assert intentos[1].modelo == "gemma4-26b-a4b"` (hoy `gemma3-4b`, el residente) |
  | `long` que falla salta a `code`, nunca al mecánico; `mechanical` que falla salta a `long` | (a) | `assert "gemma3-4b" not in [i.modelo for i in intentos]` en el de `long` |
  | Escenario «fallo de capacidad sin nada cargado» (`local_explain_code`) | (a) | `assert [i.modelo for i in intentos] == ["qwen36-35b-a3b"]` (hoy salta al 4B) |
  | `cargado` vacío no gasta salto: con `FALLBACK_MAX_HOPS = 1`, `code → cargado → long` llega a `long` | (b) | Mutante: contar el salto vacío → falla `assert intentos[-1].modelo == "gemma4-26b-a4b"` |
  | `miembros_cargado` sin proveedor no consulta la red (un `backend_mock` sin rutas registradas haría fallar el test si la consultara) | (b) | Mutante: llamar a `/running` → falla por ruta no registrada; el test lo comprueba con `assert rutas_pedidas == []` |
  | `LOCAL_DELEGATE_FALLBACK_CODE=residente,long` funciona como `cargado,long` y `doctor` avisa del nombre | (a) | `assert "renombra" in (r.hint or "")` |
  | Escenario «el estado ya no habla de un residente fantasma» (`local_status` y `doctor` con la config de hoy) | (a) | `assert "residente gemma3-4b" not in texto` (hoy sale «cadenas válidas; residente gemma3-4b (defecto: el modelo del rol mecánico)») y `assert "sin residente" in texto` |
  | Con una config con `ttl: 0` en el 4B dentro de un grupo `persistent`, `describir()` dice «residente: gemma3-4b» | (b) | Mutante: decir siempre «sin residente» → falla el assert |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_cadenas.py tests/test_respaldo.py tests/test_observabilidad_respaldo.py tests/test_rol_fast_retirado.py tests/test_checks.py tests/test_turno_daemon.py -q`
  y la suite completa.
- **Rollback:** revertir; las variables con `residente` siguen funcionando en los dos sentidos.

### T13 — llama-swap desde el daemon: estado, vigía, negativas y `doctor` (ola 7)

- **Ficheros:** `src/local_delegate/llamaswap_api.py`, `tests/test_llamaswap_api.py`,
  `tests/test_residencia_cli.py` (nuevos), zona T13 de `web/metrics.py`, `cli.py`, `checks.py`,
  `tests/test_metrics.py`, `tests/test_checks.py`, `tests/test_wiki.py`, y las filas de la tabla del
  doctor en `docs/wiki/Integration-install.md`.
- **Requisitos:** REQ-034, REQ-036, REQ-038 (negativas y confirmación), REQ-039, REQ-002 (lo que
  dice `doctor`).
- **Qué se hace:**
  1. `llamaswap_api.py`: `running()` → lista de `{id, estado, ttl}` (descarta todo lo demás, `cmd`
     incluido); `en_vuelo()` → lee `/api/events` hasta el primer mensaje `inflight` con tope de 1 s,
     cierra, y devuelve `{modelo: n}` (sin cabeceras); `actividad(modelo)`; `Vigia` (se suscribe,
     consume la carga inicial y clasifica las líneas siguientes en las cuatro salidas de REQ-034,
     con 10 s para «no vigila» y 45 s en total). Con la key del daemon o, en el CLI sin daemon, la del
     shell; sin key, «no se sabe».
  2. Endpoints del daemon tras el token web: `GET /api/llamaswap/estado` (estado, TTL, en vuelo por
     modelo, delegaciones propias vivas, ruta de la config que usa el daemon),
     `POST /api/llamaswap/vigia` y `GET /api/llamaswap/vigia/<id>`.
  3. `cli.py`: la comprobación previa de verdad (daemon con `web_auth_headers()` → directo con la
     key del shell → «no se sabe») y las negativas de REQ-034 (delegaciones propias, peticiones de
     cualquier cliente o modelos en `/running`), salvo `--ahora`; la vigía abierta **antes** de
     escribir; las cuatro salidas con su mensaje; con «rechazó», restaurar la copia por el camino de
     REQ-038 y mostrar el error de llama-swap; con «no vigila», decir que falta
     `LLAMASWAP_WATCH_CONFIG=1` si el daemon arrancó llama-swap. El aviso de «descargará todos los
     modelos» se suaviza o no según lo que midió T2 (d). Si T2 vio que las peticiones en curso se
     cortan, la negativa se mantiene.
  4. `checks.py`, **en este orden**: primero `_NUMERO[23] = "veintitrés"`,
     `_NUMERO[24] = "veinticuatro"`, `_NUMERO_DE_CHECKS[23] = "veintitrés"` y
     `_NUMERO_DE_CHECKS[24] = "veinticuatro"` (si se registran antes los checks, los guardianes caen
     por `KeyError`, que no vale como control); después `Check("backend.residencia", …)` y
     `Check("backend.topologia", …)` tras `backend.llamaserver`, los textos de REQ-036, las frases de
     tamaño del docstring con «veinticuatro»/«veintitrés», y las dos filas de la tabla del doctor y
     «las veinticuatro piezas» en `Integration-install.md` (CRLF).
  5. Los tests que usan el llama-swap de prueba reutilizan la fixture de T2, con su control de
     PID: **nunca** se mata llama-swap por nombre. Toda orden del CLI en los tests lleva `--config`.
- **Tests:**

  | Test | Control | Debe fallar con el mutante en |
  |---|---|---|
  | `GET /api/llamaswap/estado` con `/running` simulado que trae `cmd` con `--api-key clave-falsa-1` y `/api/events` con cabeceras: ninguna de las dos cosas sale | (b) | Mutante: devolver la fila de `/running` entera → falla `assert "clave-falsa-1" not in r.text` |
  | Los endpoints exigen el token web | (b) | Mutante: sin la dependencia del token → falla `assert r.status_code == 401` |
  | Con el limitador de hilos agotado, la consulta previa del CLI no espera: `/api/llamaswap/estado` simulado que no contesta en su plazo → el CLI dice «no se sabe» y no escribe | (b) | Mutante: consulta sin plazo → falla `assert transcurrido < 5` (con tope propio del test) |
  | `en_vuelo()` con una carga inicial de 100 KB de log antes del `inflight` (contra el llama-swap de prueba de T2) | guarda | `assert foto["gemma4-26b-a4b"] == 1` en menos de 1 s |
  | Escenario «no escribir con delegaciones en curso» (entrada viva en `inflight.json`; y, aparte, una petición de otro cliente en la foto) | (c) tras T11 | `assert "descargaría" in salida` y fichero intacto (en el corte de T11 sale «no se sabe»); con `--ahora`, escribe |
  | Escenario «sin credencial no se escribe a ciegas» (daemon simulado apagado, shell sin key) | (b) | Mutante: pedir la key → falla `assert "LOCAL_DELEGATE_API_KEY" not in salida`; y `assert "no se sabe si hay delegaciones en curso" in salida` |
  | Escenario «llama-swap rechaza la config» (llama-swap de prueba con `-watch-config`; el fichero se escribe por la función interna sin autocomprobación) | (b) | Mutante: sin restaurar → falla `assert sha256(fichero) == sha256(copia)`. Salida «rechazó» con el mensaje de llama-swap |
  | Escenario «llama-swap no vigila el fichero» | (b) | Mutante: tope de «no vigila» de 60 s → falla `assert transcurrido < 15` |
  | Recarga válida → «recargó»; llama-swap apagado → «caído» | (b) | Mutante: confundir «caído» con «no vigila» (sin la comprobación de conexión) → falla `assert salida == "caído"` |
  | Escenario «restaurar una copia» completo: byte a byte, copia del actual y la recarga informada | (a) contra el corte de T11 | `assert "recargó" in salida` (en el corte no hay vigía) |
  | `doctor`: `backend.residencia` OK con «sin residente» en la config de hoy; aviso informativo con un residente; aviso con `persistent` y TTL > 0 (la config del 2026-09-15) | (c) | Corte: los dos checks ya registrados (con sus guardianes de tamaño en verde) y sus probes devolviendo `UNKNOWN`. Falla `assert r.status == WARN` con la config del 2026-09-15. Un test que buscara el check por id fallaría por `None`, que no vale como control |
  | `doctor`: `backend.topologia` dice «turno activo» o el motivo (sin `LLAMASWAP_CONFIG`, `matrix`, backend remoto) | (c) | Mismo corte: falla `assert "matrix" in r.message` |
  | Guardianes de tamaño: `test_el_docstring_dice_cuantos_checks_hay_de_verdad` y el de `test_wiki.py` con 24 | guarda existente | Fallan si falta una frase o una fila: es lo que tienen que hacer |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_llamaswap_api.py tests/test_residencia_cli.py tests/test_residencia.py tests/test_llamaswap_de_prueba.py tests/test_metrics.py tests/test_checks.py tests/test_doctor.py tests/test_wiki.py -rs -q`
  (sin saltos en los ficheros del llama-swap de prueba), `node --check` del JS y la suite completa.
- **Rollback:** revertir; los endpoints y checks son nuevos.

### T14 — Espera frente a lentitud (ola 8)

- **Ficheros:** zona T14 de `server.py`, `config.py` (`UMBRAL_LENTO`), zona T14 de
  `web/metrics.py`, `tests/backend_mock.py` (`timings`), `tests/test_panel_estados.py` (zona T14),
  `tests/test_metrics.py` (zona T14), `scripts/dev/capture_dashboard.py`, `web/sysinfo.py` si hace
  falta, tests nuevos en `tests/test_lentitud.py`, y lo que salga del inventario.
- **Requisitos:** REQ-024 a REQ-028.
- **Qué se hace:**
  1. `config.UMBRAL_LENTO = _env_float("LOCAL_DELEGATE_UMBRAL_LENTO", 0.5)`.
  2. `ChatResult` gana `timings: dict | None`; `_post_chat` copia `timings` de la respuesta si viene.
  3. `_log_event` suma sobre las llamadas **reales** de la operación (los `intentos`): `inferencia_ms`,
     `espera_ms` (`latency_ms − inferencia_ms`, mínimo 0), `tok_s`, `prefill_tok_s`; con referencia,
     `ritmo_rel` y `lento`; con `lento` y backend local, `ram_libre_mb` (`sysinfo.ram_stats()`).
     Todo dentro de un `try` que, si falla, registra el evento sin esos campos (REQ-028). Sin
     `timings`, los campos se omiten, nunca 0.
  4. `ritmo.Referencias` sembrada al arrancar el servidor (log del mes y del anterior) y alimentada
     con cada evento propio. *(Aclarado el 2026-10-07, tras la revisión de la ola 3):* se crea con
     `Referencias()`, sin `por_tramos` (T3 decidió una sola referencia), y se siembra con
     `ritmo.sembrar_desde_log(referencias, directorio, ahora)`, que nunca lanza, no con `sembrar`
     suelto. En cada evento propio se **mide antes de registrar**: `medir(...)` con la ventana sin
     ese evento y después `registrar(evento)`, para que una llamada no se compare consigo misma.
  5. `local_status`: «Ritmo de referencia: gemma4-26b-a4b 40,5 tok/s (50 muestras)…».
  6. Panel: en la tabla de actividad, espera e inferencia por separado y la marca «lento ×0,37» con
     una función pura `marcaLento(e)` (devuelve `""` sin `lento`); formato con los ayudantes del
     panel (`fmtNum`).
  7. `backend_mock` devuelve `timings` cuando el test lo pide; `capture_dashboard.py` añade los
     campos nuevos a unos eventos del mock.
- **Tests:**

  | Test | Control | Debe fallar hoy / con el mutante en |
  |---|---|---|
  | Escenario «una llamada lenta se distingue de una espera» de punta a punta (`backend_mock` con `timings` y 47 s simulados de espera vía reloj inyectado; 20 eventos previos en el log de `tmp_path`) | (a) | `assert linea.get("ritmo_rel") == 0.37` (hoy `None`); después `espera_ms ≈ 47000`, `lento is True` y `ram_libre_mb` con backend local |
  | Sin `timings`, ningún campo de D en el evento | (b) | Mutante: poner 0 → falla `assert "tok_s" not in linea` |
  | Con backend remoto, `lento` sin `ram_libre_mb` | (b) | Mutante: sin mirar el origen → falla `assert "ram_libre_mb" not in linea` |
  | Operación troceada: `inferencia_ms` es la suma de las llamadas reales, incluido un salto | (b) | Mutante: solo la última llamada → falla `assert linea["inferencia_ms"] == 300` |
  | REQ-028: `ritmo.medir` sustituida por una que lanza → el evento se registra igual, sin `ritmo_rel` | (b) | Mutante: sin el `try` → falla `assert linea.get("ok") is True` (el test captura la excepción del `_chat` y la convierte en fallo de assert) |
  | `marcaLento` con node: `{lento:true, ritmo_rel:0.37}` → «lento ×0,37»; sin `lento` → `""` | (b) | Mutante: punto decimal → falla `assert txt == "lento ×0,37"` |
  | `local_status` muestra la referencia y las muestras | (a) | `assert "Ritmo de referencia" in texto` |
  | `test_captura.py` sigue en verde con el mock ampliado | guarda existente | |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_lentitud.py tests/test_ritmo.py tests/test_panel_estados.py tests/test_metrics.py tests/test_dashboard_js.py tests/test_captura.py -q`,
  `node --check` y la suite completa.
- **Rollback:** revertir; los campos son aditivos y los lectores los ignoran.

### T15 — Afinidad (ola 9, solo con celdas aprobadas)

**Puerta:** `veredicto.json` de T6. Tres salidas:

- **Ninguna celda aprobada:** REQ-010 a REQ-017 **no se implementan** (REQ-018). T15 se reduce a
  dejarlo escrito en `verification.md` con la tabla del veredicto, comprobar que `cargado` sigue sin
  miembros y que ningún texto (wiki, `doctor`, `local_status`) promete afinidad. No hay código.
- **Algunas aprobadas:** se implementa con **esas** celdas y solo esas. Si la hoja de commit no se
  terminó (T6, «Si la hoja no se termina»), la celda de commit cuenta como no aprobada y se deja
  escrito así en `verification.md`; el PR se cierra igual.
- **Todas:** igual.

- **Ficheros (si hay celdas):** `src/local_delegate/matriz.py`, `tests/test_afinidad.py` (nuevos),
  zona T15 de `server.py`, `config.py` (`AFINIDAD_MARGEN_S`), zona T15 de `cadenas.py` (proveedor) y
  de `checks.py` (aviso de huella).
- **Requisitos:** REQ-010 a REQ-017 para las celdas aprobadas; los miembros de `cargado` de REQ-019.
- **Qué se hace:**
  1. `matriz.py`: las celdas aprobadas **escritas en el código** (una tupla de
     `Celda(tool, alternativo, rol_comparado, huella)`; `veredicto.json` no viaja en el paquete), y
     un test que las compara con `veredicto.json` (REQ-043). `vigente(celda)` compara la huella con la
     config y el prompt actuales vía `huella.huella`; una celda con huella distinta cuenta como
     `sin base`. Direcciones de REQ-011 como guarda (una celda fuera de ellas no se acepta).
  2. `elegir(A', rol, observado, propios)` pura, con el desempate de REQ-012.
  3. Foto de REQ-013 con `llamaswap_api` (la consulta de actividad, la última), solo cuando hace
     falta; `ahora = time.time()`; margen `config.AFINIDAD_MARGEN_S` (5, o lo que subió T2 (b)); si
     T2 (c) vio alias en la actividad, la consulta pide el id real y sus alias.
  4. En la operación: `A` con los alternativos aprobados y vigentes (y que admiten el tamaño,
     REQ-014: `max_chars_for(alternativo)`, conservando el tope y los prompts del rol); la elección
     después de la primera plaza y la reserva reducida con `turno.reducir`; sin afinidad con backend
     remoto o modelo explícito; REQ-015 (primero el rol y luego su cadena).
     *(Aclarado el 2026-10-07, tras la revisión de la ola 4):* `Turno.elegir` no sirve tal cual
     para REQ-003, porque comprueba que no hay plaza (el aserto de REQ-004) y, si nada cabe, espera
     dentro la nueva concesión. Antes de conectar la afinidad hay que partirlo en
     `elegir_sin_esperar(op_id, candidatos) -> str | None` (atómica y válida con plaza; si nada
     cabe deja la operación en la cabeza de la cola y devuelve `None`) y
     `esperar_concesion(op_id, …)` (pública, con el aserto de REQ-004). El daemon elige con la
     plaza de su primera llamada en la mano y, si sale `None`, suelta la plaza antes de
     `esperar_concesion`. En T10 no se conectó: allí `A` tiene siempre un solo modelo.
  5. `_log_event`: `routing: "afinidad"`, `model_requested`, `afinidad_vuelo_ajeno` y, sin vuelo
     ajeno y con espera de backend ≥ 3 000 ms, `afinidad_fallida: true`. El panel **no** la cuenta
     como respaldo y la respuesta no lleva aviso.
  6. Proveedor de `miembros_cargado` registrado en `cadenas` (REQ-019).
  7. `_probe_residencia`: aviso de una celda con la huella cambiada.
- **Tests (solo con celdas aprobadas; los escenarios de la celda de la spec usan `local_classify`;
  si esa celda no se aprobó, se usa una que sí, y se anota):**

  | Test | Control | Debe fallar hoy / con el mutante en |
  |---|---|---|
  | Escenario «la tarea mecánica usa el 26B cargado» (`/running`, `/api/events` y actividad simulados) | (a) | `assert linea.get("routing") == "afinidad"` (hoy no existe); después `model_requested == "gemma3-4b"` y la respuesta sin aviso |
  | Escenarios «al cargado le quedan 3 s» (→ 4B) y «le quedan 40 s» (→ 26B) | (b) | Mutante: sin margen → falla `assert modelo == "gemma3-4b"` con 3 s |
  | Escenario «el cargado está trabajando para otro cliente» | (b) | Mutante: ignorar el vuelo → falla `assert modelo == "gemma4-26b-a4b"` |
  | Escenario «otro cliente tiene un cambio de modelo pendiente» | (b) | Mutante: ignorar el cambio pendiente → falla `assert modelo == "gemma3-4b"` |
  | Escenario «una celda no aprobada no se usa» (`local_explain_code`) | (b) | Mutante: celdas en cualquier dirección → falla `assert modelo == "qwen36-35b-a3b"` |
  | Escenario «la huella cambió»: celda aprobada con la huella de `-ncmoe 12` (el valor real de hoy) y una config **sintética** en `tmp_path` con `-ncmoe 16` | (b) | Mutante: `vigente` sin comparar flags → falla `assert modelo == "gemma3-4b"`; y `doctor` avisa |
  | Escenarios «la afinidad no se cuela» y «se une si nadie espera» de punta a punta, y el de «la reserva se reduce» con dos celdas | (b) | Los mutantes de T8 aplicados en la integración, con los mismos asserts |
  | `matriz` = `veredicto.json` | (b) | Mutante: añadir a mano una celda `rechazada` como aprobada → falla `assert celdas_codigo == celdas_aprobadas_veredicto` |
  | Camino feliz sin red: con el rol en `propios`, ninguna consulta (rutas sin registrar) | (b) | Mutante: pedir la foto siempre → falla `assert rutas_pedidas == []` |
  | Backend remoto o `model` explícito: sin afinidad | (b) | Mutante: sin mirar el origen → falla `assert linea.get("routing") is None` |
  | Fallo del alternativo: el primer candidato es el rol | (b) | Mutante: seguir la cadena del alternativo → falla `assert intentos[1].modelo == "gemma3-4b"` |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_afinidad.py tests/test_turno.py tests/test_turno_daemon.py tests/test_cadenas.py tests/test_checks.py -q`
  y la suite completa.
- **Rollback:** vaciar la tupla de celdas: el código queda inerte y el comportamiento es el de T14.

### T16 — Documentación (ola 10)

- **Ficheros:** `CHANGELOG.md` y `README.md` (CRLF), `docs/wiki/Configuration.md`, `Tools.md`,
  `Architecture.md`, `Backend-versions.md`, `Savings-and-metrics.md`, `Troubleshooting.md`,
  `Daemon.md`, `Integration-install.md` (zona T16, CRLF), `docs/recipes/llama-swap-groups.md`.
- **Requisitos:** «Release» y «Variables nuevas» de los no funcionales, REQ-023 (la wiki solo habla
  de «residente» con TTL 0), REQ-035 (README), el caso límite «Plazos de los clientes MCP».
- **Qué se hace:**
  - CHANGELOG `[Unreleased]` (editando el bloque propio, nunca reescribiendo la sección): `Added`
    turno por modelos que chocan, espera de turno en el panel, espera e inferencia por separado y
    «lento», `llamaswap residencia`, dos checks; `Changed` cadenas sin residente y código/largo
    nunca al mecánico, un fallo de capacidad sin `cargado` ya no tiene respaldo (consecuencia
    aceptada en REQ-021), `init-llamaswap` sin residente por defecto; y, si hubo celdas, la
    afinidad con la tabla del veredicto. Sin versión ni fecha.
  - README (`:257-264` y la mención de `init-llamaswap`) y la receta de grupos: «ningún residente»
    como recomendado; la residencia como opt-in con su coste de VRAM.
  - Wiki: `Configuration.md` con las variables nuevas; `Tools.md` y `Architecture.md` con el turno,
    `cargado` y, si la hay, la matriz; `Savings-and-metrics.md` con los campos nuevos del log y del
    panel; `Troubleshooting.md` con «una delegación espera turno» y los cuatro mensajes de la
    recarga; `Daemon.md` con los endpoints; `Backend-versions.md` con lo que se usa de v255;
    `Integration-install.md` con el comando; y los plazos de Claude Code y Codex medidos en T0.5
    con cómo subirlos.
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_wiki.py tests/test_captura.py tests/test_release_metadata.py -q`,
  `git ls-files --eol` igual que antes en cada fichero, `rg -n "residente" docs/wiki README.md docs/recipes`
  revisado línea a línea (solo puede quedar con TTL 0 o como opt-in), y la suite completa.
- **Rollback:** revertir los Markdown.

### T17 — Verificación final (ola 11)

Cada paso tiene su criterio de fallo; un fallo se investiga antes de seguir, sin ajustar la cifra
esperada.

1. `uv run ruff check .`, `uv run ruff format --check .`, suite completa con Playwright bajo
   `pesado.sh` y con `-rs` (**falla** si se salta algún test del llama-swap de prueba), `node --check`.
   Conteo en `verification.md`.
2. **Gate de F3** (control de T1): un script de lectura sobre
   `.sdd/changes/delegacion-precisa-y-fiable/state.json` busca en `history` un evento
   `type: "gate"`, `gate: "spec"`, `status: "approved"` con `at` **posterior** a la hora de la
   enmienda que anotó T1. **Falla** (y el PR no se mezcla) si no lo hay. Que el gate figure como
   `approved` no basta: lo está desde el 2026-09-12.
3. **CLI sobre una COPIA de la config real** (con las claves sustituidas, en
   `<scratchpad>/t17/config.yaml`; **cada orden con `--config`**, literal):
   - `local-delegate llamaswap residencia --config <scratchpad>/t17/config.yaml`
   - `local-delegate llamaswap residencia --config <scratchpad>/t17/config.yaml --dry-run --ttl gemma4-12b=60`
   - `local-delegate llamaswap residencia --config <scratchpad>/t17/config.yaml --ttl gemma4-12b=60 --ahora`
   - `local-delegate llamaswap residencia --config <scratchpad>/t17/config.yaml --restaurar <scratchpad>/t17/config.yaml.<fecha>.bak --ahora`
   - `local-delegate llamaswap residencia --config <scratchpad>/t17/config.yaml --ninguno` (dice
     «nada que cambiar»)
   - `local-delegate llamaswap residencia --config <scratchpad>/t17/config.yaml --fijar gemma4-26b-a4b --vram-gb 16 --reserva-gb 2 --vram-modelo gemma4-26b-a4b=10.29 --vram-modelo qwen36-35b-a3b=9.88 --vram-modelo gemma3-4b=3.19 --vram-modelo gemma4-12b=8.85 --vram-modelo qwen35-2b=3.5`
     (se niega)

   **Falla** si el `diff` de cada escritura no es exactamente la línea pedida, si la restauración
   no deja el `sha256` de la copia original, o si el `sha256` de la config **real** cambió durante
   el paso (se compara antes y después). Con `--ahora` sobre la copia, la vigía mira el llama-swap
   real, que no vigila ese fichero: la salida esperada es «no vigila el fichero», y se anota.
4. **Daemon real con la versión del repo** (lo lanza la sesión principal, con el permiso del
   usuario; reinicia el daemon):
   `bash ~/.claude/scripts/pesado.sh uv tool install --force --reinstall --no-cache ".[llamaswap]"`
   y `schtasks /Run` de la tarea del daemon. Después:
   - `local_status` por MCP: «Turno: sí», «sin residente» y ninguna mención a «residente
     gemma3-4b». **Falla** si no.
   - `uv run local-delegate doctor`: `backend.topologia` OK con turno y `backend.residencia` OK con
     «sin residente». **Falla** con `UNKNOWN` o `WARN`.
5. **Dos tools en paralelo contra el backend real** (carga modelos: bajo `pesado.sh`, el usuario
   avisado, ventana anotada como excluida de P-4 y F1, nadie más usando `local_*`): desde un
   subagente, `local_commit_msg` de un diff de 3 trozos y `local_lint_summary` de 3 trozos lanzados
   a la vez. Antes, en `9393`, un `setInterval` de 500 ms dentro de la página (`browser_evaluate`)
   que guarda el texto y el `title` de las filas de los dos modelos. Se lee el log de uso y
   `/api/metrics/activity` de la ventana.
   - **Falla** si en la secuencia de modelos que sirvió llama-swap hay más de **un** cambio entre
     los dos modelos (alternancia).
   - **Falla** si ninguna de las dos líneas del log lleva `espera_turno_ms > 0`.
   - **Falla** si ninguna lectura del panel dice «en cola local» con un `title` que contiene
     «esperando turno del daemon».
   - **Falla** si alguna línea con `timings` no trae `inferencia_ms` y `espera_ms`; `ritmo_rel` se
     anota si hay referencia (con menos de 10 muestras no sale, y no es fallo).
6. **Config real, solo ida y vuelta** (lo lanza la sesión principal **con el permiso explícito del
   usuario**, avisándole de que la recarga descarga los modelos):
   1. copia de seguridad manual `config.yaml.pre-daemon-reparte-t17-<AAAAMMDD-HHMMSS>.bak` y su
      `sha256`, que tiene que coincidir con el último anotado al cerrar la ola 10;
   2. `local-delegate llamaswap residencia --config D:\Projects\llms\llama-swap\config.yaml`
      (solo lectura): «sin residente (recomendado)»;
   3. **sin modelos cargados**: el paso 5 deja modelos (TTL 120, el 12B 30). Se sondea `/running`
      (por `doctor` o `/api/llamaswap/estado` del daemon) cada 10 s hasta que quede vacío, con un
      tope de 3 minutos, sin delegar nada mientras. Si en 3 minutos no queda vacío, se mira quién lo
      usa (`/api/inflight`, la foto de llama-swap) y se espera otro TTL; si tampoco, se para y se
      anota. **Nunca** con `--ahora` aquí: el paso tiene que probar también la negativa y la
      consulta previa reales;
   4. `local-delegate llamaswap residencia --config D:\Projects\llms\llama-swap\config.yaml --ttl gemma4-12b=31`
      → la consulta previa dice que no hay trabajo en curso y la vigía dice «recargó»;
   5. `local-delegate llamaswap residencia --config D:\Projects\llms\llama-swap\config.yaml --restaurar <la copia con fecha que dejó el paso 4>`
      → «recargó»;
   6. `sha256` del fichero igual al del paso 1. **Falla** si difiere: se restaura **en el acto**
      desde la copia manual con `Copy-Item` y se avisa al usuario. Si la vigía no dijo «recargó» en
      algún paso, se anota la salida y se comprueba `/running` antes de seguir;
   7. se listan los `.bak` que quedaron junto a la config (la manual y los dos con fecha de los
      pasos 4 y 5) y se **conservan**: tienen las mismas claves y permisos que la config, y son la
      vuelta atrás. Se anotan sus nombres en `verification.md`.
7. **Afinidad en vivo** (solo si T15 implementó alguna celda): con el 26B cargado por un
   `local_summarize`, una llamada a la tool de una celda aprobada dentro del margen. **Falla** si la
   línea no lleva `routing: "afinidad"` o si `/running` muestra que se cargó el modelo del rol.
8. **Devolver el daemon a la versión publicada** (sesión principal), salvo que el usuario diga
   otra cosa: el panel de uso diario no enseña código sin publicar.
9. `personal-sdd-review` del resultado contra la spec y `personal-security-check` sobre el diff
   (sin claves en fixtures, endpoints sin `cmd` ni cabeceras).

## Test strategy

- **Unit:** huella, puntuadores, hoja y veredicto con datos sintéticos (T4); topología contra la
  tabla de `EvictionFor` (T7); núcleo del turno con reloj simulado (T8); ritmo (T3, T9); editor
  quirúrgico, estimador y transformaciones (T11); `elegir` y matriz (T15).
- **Integración:** turno de punta a punta con `backend_mock` que serializa y cuenta cambios,
  `inflight.json` → `/api/inflight` → `estadoModelo` con node (T10); cadenas con `backend_mock`
  (T12); endpoints, vigía y CLI contra el llama-swap de prueba (T13); log y panel con `timings`
  (T14); afinidad con endpoints simulados (T15). Suite completa al final de cada ola.
- **Contra un llama-swap v255 de verdad, sin modelos:** TTL, carrera, alias, recarga y foto en
  vuelo (T2), recarga y restauración del CLI (T13). Exigidos sin saltos en esta PC.
- **Con datos reales:** control de lentitud sobre la copia de `metrics.db` y el log (T3);
  estimador contra los GGUF y lo medido en F2 (T11).
- **Con modelos reales:** la tanda (T5) y dos tools en paralelo contra el backend real (T17.5).
- **Con el usuario:** la hoja a ciegas de commit (T6).
- **De extremo a extremo:** daemon reinstalado, `doctor`, `local_status`, panel en vivo y la ida y
  vuelta sobre la config real (T17).
- **Guardianes del repo que este plan toca a propósito:** paridad Python/JS (este cambio no añade
  reglas en las dos copias: `marcaLento` solo pinta lo que calcula Python, y lo dice su test);
  `test_captura.py` (endpoints nuevos que el panel no pide; mock ampliado en T14);
  `test_aislamiento_entorno.py` (tres variables por `_env*`); tamaño del doctor (`_NUMERO`,
  `_NUMERO_DE_CHECKS`, frases y tabla de la wiki, en T13); `test_wiki.py` (T13, T16); LF/CRLF por
  fichero (todas); `_SCRIPTS_RETIRADOS` sin cambios (no se retira ningún hook).
- **Seguridad y secretos:** fixtures sin claves reales (test de T11); endpoints y CLI sin `cmd`,
  cabeceras ni claves (T11, T13); ningún paso lee ni pide `LOCAL_DELEGATE_API_KEY`; copias de la
  config junto a ella con los mismos permisos; `personal-security-check` sobre el diff (T17.9).

## Migration and compatibility

- **Log de uso:** campos aditivos y omitidos sin dato (`espera_turno_ms`, `turno`, `inferencia_ms`,
  `espera_ms`, `tok_s`, `prefill_tok_s`, `ritmo_rel`, `lento`, `ram_libre_mb`, y con afinidad
  `routing`, `afinidad_vuelo_ajeno`, `afinidad_fallida`). El histórico se lee igual.
- **`inflight.json` y `/api/inflight`:** `espera_local` gana el motivo `"turno"`; claves nuevas
  `turno_en_uso` y `turno_posicion`. El panel de antes pinta el motivo nuevo en la fila 3 (vale
  para cualquier motivo).
- **Variables:** `residente` en `LOCAL_DELEGATE_FALLBACK_<ROL>` sigue valiendo (con aviso). Tres
  variables nuevas con valores por defecto.
- **Comportamiento visible:** dos operaciones que chocan ya no se intercalan (una espera); un fallo
  de capacidad sin `cargado` ya no tiene respaldo; código y largo nunca caen al mecánico. Sin
  topología o con backend remoto, todo sigue como hoy (salida de emergencia: `LLAMASWAP_CONFIG`
  vacío en el lanzador).
- **`init-llamaswap`:** `--ttl-resident` pasa a 0 y su copia lleva fecha.
- **Otras máquinas:** la Mac (backend remoto) no tiene turno ni afinidad; Claude Desktop en stdio y
  `benchmark.py` no pasan por el turno, pero sus peticiones se ven en la foto.
- **Interfaces internas:** `_con_respaldo` se parte en dos; `ChatResult` gana `timings`;
  `cadenas.residente()` desaparece en favor de `miembros_cargado` y de `topologia.residentes()`
  (T12 busca y actualiza a todos sus llamadores).
- **Release:** fuera de este plan; T16 deja listos CHANGELOG, README y `docs/wiki/`.

## Riesgos principales

- **El juicio del usuario es el camino crítico de la afinidad.** La hoja sale en la ola 2 y las
  olas 3 a 8 no la esperan. Si al cerrar la ola 8 no ha llegado, la sesión principal pregunta al
  usuario: o espera, o la celda de commit queda no aprobada y el PR se cierra igual (T6, «Si la hoja
  no se termina»). Con «formato» calculado por el programa, «lo principal» y «específico» quizá
  opcionales (pendiente del usuario) y la parada anticipada, la hoja baja a unos 45–60 minutos. Si la
  sesión principal quiere acortar el camino, las olas 1, 2 y T6 pueden adelantarse **antes** de
  que se mezclen el panel y el coste, en una rama propia que solo añade `huella.py`, `scripts/`,
  `benchmarks/` y sus tests (ninguno de esos ficheros lo tocan los otros dos cambios). Condición:
  T15 recalcula la huella contra el código final, y si el prompt de una tool cambió entretanto, su
  celda queda `sin base` y `doctor` lo dice. Es una decisión de la sesión principal, no el orden
  por defecto.
- **La tanda y la PC compartida:** carga modelos durante un buen rato, ocupa ~11,7 GB de RAM con el
  26B y Claude Code mata los comandos largos en segundo plano. Mitigación: proceso independiente,
  cerrojo, usuario avisado, nadie usando `local_*`, ventana excluida de P-4 y F1.
- **Delegaciones ajenas durante la tanda** (Codex, otro Claude Code, la Mac): la ventana se elige
  con el usuario, y al terminar se detectan las peticiones ajenas y se repiten los casos que se
  solaparon (T5.3).
- **Trampas que se delatan:** con diffs propios fuera de los 30, la misma forma que su pareja y
  asuntos de ≤ 72 caracteres (T4.4); el test de la hoja lo comprueba. Queda un límite conocido: el
  estilo de cada modelo se puede reconocer a lo largo de 30 pares.
- **Lo que la hoja puede decir:** filtra bien lo claramente peor, pero un 26B algo peor pasa en 3 de
  cada 10 tandas (tabla de potencia de la revisión). Va a `verification.md` y al mensaje de T6.
- **La config real**: `LLAMASWAP_CONFIG` del usuario apunta a ella. `--config` explícito en toda
  orden y test, fixture que corta la consulta al daemon, y `sha256` comparado al cerrar cada ola.
- **Hilos de anyio:** cada espera de turno ocupa un hilo de los 40, que también usan
  `local_status`, el panel y la espera de plaza de hoy. T10 lo mide contra la línea base de hoy y
  contra el pico real de operaciones simultáneas; si sale peor, la solución (subir el limitador) no
  está en la spec y va a la sesión principal.
- **Plazos de los clientes MCP:** una operación suma espera de turno e inferencia. T0 averigua los
  plazos y T16 documenta cómo subirlos; no se cambia nada.
- **La recarga de llama-swap descarga todos los modelos**, y quizá corta peticiones (T2 lo mide).
  El CLI se niega con trabajo en curso salvo `--ahora`, y la ida y vuelta de T17.6 solo se hace con
  permiso del usuario.
- **La enmienda de F3** necesita una aprobación **nueva** del usuario, posterior a la enmienda; sin
  ese evento en el historial de F3, el PR no se mezcla (T17.2). El harness no permite retroceder F3,
  así que no se usa ninguna transición.
- **Procesos:** el llama-swap de prueba es el mismo ejecutable que el real; solo se terminan los PID
  que lanzó la fixture.
- **Concurrencia difícil de probar:** los tests de hilos llevan topes propios, una guarda de que el
  guion discrimina, y el núcleo se prueba aparte con reloj simulado, sin dormir.

## Plan review

- [x] Cada requisito tiene tarea y verificación (tabla de trazabilidad).
- [x] Nada destructivo sin dueño ni vuelta atrás: la config real solo la toca T17.6, lanzada por la
  sesión principal con permiso del usuario, sin modelos cargados, con copia manual, `sha256` y
  restauración inmediata si algo no cuadra; ningún test ni orden del CLI la puede alcanzar
  (`--config` explícito, fixture que corta el daemon, `sha256` al cerrar cada ola); ningún proceso
  se mata por nombre; reinstalar el daemon y devolver la versión publicada (T17.4, T17.8) los lanza
  la sesión principal.
- [x] Sin dependencias nuevas (PyYAML del extra `[llamaswap]`); tres variables por `_env*`; dos
  checks con sus guardianes de tamaño; ningún hook retirado.
- [x] Sin trabajo ajeno a la spec: la Mac, Claude Desktop, la composición de grupos, los modelos de
  los roles, `local_summarize` en la matriz y los valores de TTL quedan fuera.
- [x] Sin worktrees; solo van en paralelo tareas que no editan `server.py` ni ficheros de las otras;
  cada ola tiene un único escritor de `verification.md` y una integración con dueño.
- [x] Los tests que este cambio rompe tienen dueño, y se encuentran ejecutando: el salto dentro de
  la plaza (T10), el residente (T12), el tamaño del doctor (T13).
- [x] Cada control nombra la tarea que produce su insumo: llama-swap de prueba (T2 → T13, T15);
  forma de la referencia (T3 → T9, T14); corpus, trampas, hoja y criterios (T4 → T5 → T6); veredicto
  (T5, T6 → T15); topología (T7 → T10, T11, T12, T13); núcleo del turno (T8 → T10); ritmo (T9 →
  T14); editor (T11 → T13); `llamaswap_api` (T13 → T15).
- [x] Cada mutante dice por qué muta, y todo `pytest.raises` lleva `match=`. **Comprobados** con
  reimplementaciones desechables (`scratchpad/controles-plan/controles.py`): la huella con la forma
  corta real (`-ncmoe 12`) y la larga sintética, las claves duplicadas con `match`, las respuestas
  de otra hoja completas y la línea corrupta de la siembra convertida en `assert`. La revisión
  comprobó además los de T3, T4 (`<= 3`, `c > v`), T8 (abandono con `tic=5.0`) y T10 (dos saltos).
  Queda por comprobar al ejecutar, y así lo exige su tarea: el número de líneas que cambia
  `safe_dump` (T11).
- [x] Los parámetros que el usuario todavía no ha confirmado («inventa» más estricto, preguntas
  opcionales) están en un solo sitio (`reglas.json`), se cierran antes de la hoja 1 y no los fija
  este plan.

## Traceability

| Requisito | Tarea | Evidencia |
|---|---|---|
| REQ-001, REQ-009 | T7, T10 | Tabla contra `EvictionFor`, alias, dos sintaxis, relectura; topología nueva en la siguiente concesión |
| REQ-002 | T7, T10, T13 | Motivos de «sin topología»; sin turno con backend remoto; `local_status` y `backend.topologia` |
| REQ-003, REQ-004, REQ-005 | T8, T10 | Orden, E-1, reserva que se reduce, abandono, cambio de topología, aserto de orden de adquisición |
| REQ-006 | T10 | Dos saltos a la vez no bloquean; el salto suelta la plaza antes de pedir turno |
| REQ-007 | T8, T10 | Forzada por falta de progreso, comprobación periódica, plazo HTTP de 900; liberación con excepción; hilos de anyio |
| REQ-008 | T10 | `espera_local: "turno"`, `turno_en_uso`, `turno_posicion`, fila 3 y `title` con node; `espera_turno_ms`, `turno: "forzado"` |
| REQ-010 a REQ-017 | T15 (si hay celdas), T2 (margen y alias) | Escenarios de afinidad, matriz = veredicto, huella, camino feliz sin red; T17.7 en vivo |
| REQ-018 | T6, T15 | `veredicto.json`; sin celdas, nada implementado y anotado |
| REQ-019 a REQ-023 | T12, T15 (proveedor) | Código nunca al mecánico; capacidad sin `cargado`; salto vacío sin gastar; sinónimo; «sin residente» |
| REQ-024 a REQ-028 | T3, T9, T14 | Control de lentitud con datos reales; ventana; evento lento de punta a punta; sin `timings`; robustez; `marcaLento` |
| REQ-029 a REQ-033, REQ-035, REQ-038 | T11, T13 | Tabla de edición; escenarios de `--ninguno`, `--fijar`, `--ttl`, restaurar; estimador contra F2 |
| REQ-034, REQ-039 | T2, T13 | Cuatro salidas con el llama-swap de prueba; negativas; sin credencial; endpoints sin secretos |
| REQ-036 | T13, T15 | Dos checks y guardianes de tamaño; aviso de huella |
| REQ-037 | T1, T12, T17.2 | Punto en la spec de F3, evento del harness, gate reaprobado; tests de F3 reescritos |
| REQ-040 a REQ-043 | T4, T5, T6 | Corpus, puntuadores, trampas preregistradas, tanda, hoja válida, `veredicto.json` y tabla |
| REQ-044 | T5b | Orden de idioma con mutantes; corpus reconstruido con `es` y `--comprobar`; `--seco` con solo las celdas de commit pendientes |
| Caso límite «Plazos de los clientes MCP» | T0, T16 | Plazos con su fuente, en la wiki |

## Llamadas `local_*` al escribir este plan

**0**, también en la revisión 2 (los controles se comprobaron con un script desechable, sin
modelos). Se cargaron `local_summarize`, `local_extract` y `local_explain_code`, pero no se usaron:
sin modelo residente, cada llamada habría descargado el modelo cargado y añadido filas a
`metrics.db`, que se está midiendo (P-4, F1); y el plan necesitaba el texto literal de la spec, de
los dos planes de referencia y de las funciones de `server.py` que se citan, que se leyeron por
franjas y con `grep`.
