# Implementation plan: Panel: coste equivalente a precio de API y % de cuota sin calibrar

Plan sobre `spec.md` v2.1 (58 REQ, aprobada el 2026-10-06) con la **enmienda 1** posterior a la
aprobación (plazo de borrado `H` leído de `cleanupPeriodDays`; ver el final de la spec). Versión 2 del
plan: corrige la «Revisión del plan» de `review.md` (respuestas al final de ese fichero).

Se implementa **después** de `panel-cuentas-y-estados-honestos`: parte del estado que deja ese
cambio mezclado en `main` y de su «Contrato con `coste-api-y-cuota`». Nada de este plan da por hecho
el código actual de `server.py` ni de `web/metrics.py`: las zonas se nombran por función y el
primer paso (T0) lee cómo quedaron.

## Approach

Doce tareas: una de arranque, siete de código, una de medición con datos reales, una de
documentación, una de verificación final y una que solo puede hacerse en GitHub después de
mezclar. Todo en el árbol principal de una rama nueva, **sin worktrees**. Dos olas tienen dos
tareas en paralelo porque no comparten **ningún** fichero, ni de código ni de tests, y ninguna
importa ni prueba lo que la otra está escribiendo (ver «Por qué estas parejas y no otras»). El resto
va en serie.

### Orden entre cambios

**`panel-cuentas-y-estados-honestos` → `coste-api-y-cuota` → `daemon-reparte-el-backend`**
(decisión de la sesión principal, 2026-10-06). Este plan cuenta lo que hay **sin** los cambios de
`daemon-reparte-el-backend`: `doctor` pasa de veintiuno a **veintidós** checks (aquel añade dos
después, de veintidós a veinticuatro) y `_HOOK_EVENTS` pasa de uno a dos. T0 lee
`len(checks.CHECKS)` y `len(install._HOOK_EVENTS)` reales; si no son 21 y 1, el orden no se cumplió
y se para.

`daemon-reparte-el-backend` es el **siguiente** y rebasa sobre este. Ficheros que los dos tocan, para
que su plan los recalcule:

| Fichero | Este cambio | Aquel |
|---|---|---|
| `server.py` | `_log_event` (`tool_use_id`, `caller_*`), `tokens_claude`, mensajes de ahorro, lector de `local_status` | `_log_event` (campos nuevos), `_run_chat`, `_chat*`, `_post_chat`, `local_status` |
| `config.py` | `COSTE_RESPALDO` | tres variables |
| `cli.py` | subcomando `recalcular-coste` | su subcomando |
| `checks.py`, `tests/test_checks.py`, `tests/test_wiki.py`, `docs/wiki/Integration-install.md` | un check (`config.coste`), «veintidós» | dos checks, «veinticuatro» |
| `web/metrics.py` y su JS | `_load` (fusión), `tokensClaude`, `/api/stats`, bloques de coste, cuota e imágenes | `/api/inflight`, tabla de actividad, endpoints de su REQ-039 |
| `tests/test_metrics.py`, `tests/test_dashboard_js.py`, `tests/test_dashboard_ui.py`, `tests/test_aislamiento_entorno.py` | ver tareas | ver su spec |
| `scripts/dev/capture_dashboard.py`, `CHANGELOG.md`, `docs/wiki/*.md` | T9 | su tarea de docs |

### Diseño

- **Módulos nuevos, uno por pregunta** (todos LF, solo stdlib):
  - `precios.py`: carga las dos tablas del paquete (`resources/datos/precios.json` y
    `resources/datos/densidad.json`), normaliza ids (REQ-011), busca por id exacto y hace el cotejo
    puro de REQ-013. No abre sockets (REQ-012).
  - `atribucion.py`: la nota del hook, la resolución de quien llama con su presupuesto (REQ-003),
    la memoria por petición, y las reglas que **varios** consumidores necesitan, en un solo sitio:
    la clave de cada línea (`tool_use_id` o `ts|tool|ordinal`, REQ-005); leer y escribir
    `atribucion-AAAAMM.json` con «solo se sustituye por un cruce mejor»; la **exclusión** de REQ-007
    (`CLIENTES_EXCLUIDOS = {"codex-mcp-client": "no es Claude", "mcp": "pruebas"}` y
    `excluida(fila, entrada_relleno) -> str | None`, que también marca `banco`); y
    `plazo_de_borrado(claude_dir) -> int` (`H` de la enmienda 1). Lo usan T4 (fusión y tramos), T5
    (comando y agregados de `N` sin excluidas) y T7 (`doctor`): por eso vive en T2, antes que todos.
  - `coste.py`: clase de contenido, respaldo de modelo, `resolver_densidad` (REQ-031 a REQ-033),
    la fusión de REQ-006 y el tramo de cobertura de REQ-007 (`tramo(fila, *, ahora, plazo_dias)`).
  - `transcripts.py`: lectura de transcripts, **solo** para el comando: cruce (REQ-004), `N` y
    caducidades (REQ-043), `cost-state` (REQ-014), peticiones por intervalo (REQ-051, REQ-052).
  - `cuota.py`: puntos de rechazo y del statusline, solapes, saneado, vigencia, criterio y deriva
    (REQ-051 a REQ-057), todo puro. Lo usan el comando y el panel.
  - `recalcular.py`: el comando; escribe `coste-agregados.json` y los `atribucion-AAAAMM.json`
    (REQ-070 a REQ-074) y es el **único** lector y escritor del formato de `coste-agregados.json`.
  - `valoracion.py`: precio por evento, origen de `N`, coste por evento y por periodo, bloque de
    imágenes y bloque de coste (REQ-016, REQ-038, REQ-040 a REQ-048).
- **Decisiones que la spec deja al plan:**
  - Comando del CLI: **`local-delegate recalcular-coste`**, con `--reiniciar-calibracion
    five_hour|seven_day` (REQ-057) y `--claude-dir` (por defecto `~/.claude`; existe para que los
    tests usen un HOME sintético). El punto de entrada es `cli.run(argv)`.
  - Variable del respaldo (REQ-008): **`LOCAL_DELEGATE_COSTE_RESPALDO`**, leída en `config.py` con
    `_env` (ningún otro módulo lee el entorno: lo vigila `test_config_solo_lee_el_entorno_por_la_puerta_registrada`).
  - **Plazo de borrado `H`** (enmienda 1): `atribucion.plazo_de_borrado` lee `cleanupPeriodDays` de
    `claude_dir/"settings.json"` (30 si falta o no es un entero positivo). El comando lo usa para la
    ventana del relleno y lo guarda en `coste-agregados.json` (`plazo_dias`); el panel lo toma de ese
    JSON (30 sin JSON; nunca lee `~/.claude`, REQ-073); `doctor` lo lee de `settings.json`, que ya
    lee para los hooks.
  - Hook nuevo: `resources/hooks/anotar_llamada.py`, registrado **al final** de
    `install._HOOK_EVENTS` como `("anotar_llamada.py", "PreToolUse", "mcp__local-delegate__.*")` y
    añadido a `install._SCRIPT_NAMES`. Va siempre, no detrás de `--enable-read-hook`: no avisa ni
    bloquea.
  - **Notas del hook, una por llamada** (seguras con subagentes en paralelo): cada nota es un
    fichero `tempfile.gettempdir()/local-delegate-llamadas/<tool_use_id>.json`, escrito en un
    temporal del mismo directorio y movido con `os.replace` (atómico: el daemon nunca lee una nota a
    medias, y dos hooks a la vez no se pisan porque no comparten fichero). El `tool_use_id` se valida
    con `^toolu_[A-Za-z0-9_-]{1,64}$` antes de construir la ruta (si no casa, no hay nota). El hook
    borra, best-effort, las notas de más de 10 min, que ya no cuentan (REQ-003). La nota guarda
    `transcript_path` porque lo pide REQ-002, aunque `hook_common` no escriba rutas en la
    telemetría: no es telemetría, vive en el temporal y caduca a los 10 min.
  - **Seguridad del `transcript_path`**: el daemon lo lee de un fichero que cualquier proceso local
    puede escribir, así que antes de abrirlo comprueba que, resuelto, cuelga de
    `Path.home()/".claude"/"projects"` y acaba en `.jsonl`. Si no, `caller_src: hook` sin modelo.
  - Transcript del subagente: `Path(nota.transcript_path).with_suffix("") / "subagents" /
    f"agent-{agent_id}.jsonl"` (la nota de un subagente trae el `transcript_path` **del principal**:
    insumo de atribución, tabla de la entrada del hook).
  - **Memoria por petición**: `observar_cliente` pone en un `ContextVar` un dict vacío por petición;
    `atribucion.llamada_actual()` guarda ahí la resolución. Nada vive en un dict del módulo, que en
    el daemon crecería sin límite.
  - Check de `doctor`: `Check("config.coste", "entorno", "coste y relleno", _probe_coste)`. El
    registro pasa de veintiuno a **veintidós**, con sus guardianes de tamaño.
  - **Ningún endpoint nuevo.** `/api/stats` gana `coste`, `imagenes`, `cuota` y `densidad_tabla`;
    `/api/events` entrega las filas fundidas. `tests/test_captura.py` no cambia de lista.
  - **El coste solo lo calcula Python.** El JS pinta lo que trae `/api/stats`; la única regla que
    vive en las dos copias es la conversión a tokens de Claude, y ahí las dos solo dividen (REQ-033).
  - **Dónde se funde** (REQ-006): en `metrics._load`, **por fichero y antes de filtrar por rango**
    (el ordinal de la clave depende del fichero entero), y en el lector propio de `local_status`.
    No en `_read_file_cached`, que también lee la telemetría de hooks. La fusión **copia** cada
    fila: nunca muta las de la caché de `_read_file_cached`.
  - **`tokens_claude` y `tokensClaude` hacen lo mismo**: imagen o sin `densidad[tipo]` → 0; si no,
    la división. Ninguna resuelve nada. Son los tres mensajes en vuelo de REQ-035 los que llaman a
    `resolver_densidad` sobre la fila en curso antes de convertir. Una fusión olvidada en cualquier
    camino de Python da un 0 visible, no una cifra con el respaldo.
  - Techo del comando (requisito no funcional): **30 s** en esta PC, medido en T8.
  - El vigilante: `scripts/vigilante_precios.py` y `.github/workflows/vigilante-precios.yml`, con el
    texto guardado de límites en `.github/vigilante/limites-de-uso.txt`; ramas fijas
    `vigilante/precios` y `vigilante/limites`.

### Formato de `coste-agregados.json` (lo escribe y lo lee solo `recalcular.py`)

```
{"version": 1, "generado": "<ISO>", "plazo_dias": H,
 "cotejo": {"fecha", "version_tabla", "juzgadas", "fuera", "sin_precio": [ids], "veredicto": "pasa"|"falla"} | null,
 "n_por_mes": {"AAAAMM": {"<modelo>|<hilo>": [N, ...]}},      # REQ-042 (2) y REQ-071
 "puntos": [{"fuente": "statusline"|"rechazo", "tipo", "inicio", "fin", "delta_pct", "delta_usd",
             "C", "marcas": [...], "peticiones_sin_precio"}],
 "descartes": {"five_hour": {"<motivo>": k}, "seven_day": {...}},
 "reinicios": {"five_hour": "<ISO>"|null, "seven_day": "<ISO>"|null},
 "fuentes": {"transcripts": bool, "statusline": bool}}
```

`n_por_mes` guarda los valores, no la mediana, para que la mediana de varios meses sea exacta; son
números, sin claves de línea (REQ-072). `atribucion-AAAAMM.json` es `{"version": 1, "entradas":
{"<clave>": {caller_model, caller_kind, caller_effort, n, caducidades, cruce, banco}}}`.

### Olas

| Ola | Tareas | Espera a | Escritor único de `verification.md` |
|---|---|---|---|
| 0 | T0 (arranque y comprobaciones previas) | panel mezclado en `main` | agente de T0 |
| 1 | T1 (tablas y cotejo puro) | ola 0 | agente de T1 |
| 2 | T2 (atribución en vivo) ∥ T3 (vigilante), e integración I2 con la prueba de humo del `_meta` | ola 1 | agente de integración I2 |
| 3 | T4 (densidad, conversión y fusión) | ola 2 | agente de T4 |
| 4 | T5 (comando del CLI) | ola 3 | agente de T5 |
| 5 | T6 (coste y cuota en la API y el panel) ∥ T7 (check de `doctor`), e integración I5 | ola 4 | agente de integración I5 |
| 6 | T8 (medición con los datos reales de esta PC) | ola 5 | agente de T8 |
| 7 | T9 (documentación) | ola 6 | agente de T9 |
| 8 | T10 (verificación final, daemon y panel en vivo) | ola 7 | agente de T10 |
| tras mezclar | T11 (ensayo real del vigilante en GitHub, REQ-025) | mezcla en `main` | sesión principal |

**Por qué estas parejas y no otras.** Dos tareas van juntas solo si no comparten ningún fichero,
ninguna importa un módulo que la otra está escribiendo y ninguna corre un test que lea lo que la
otra edita.

- T2 ∥ T3: T2 toca `clients.py`, `install.py`, `server.py` (`_log_event`), el hook, `hook_common.py`,
  `atribucion.py` y sus tests; T3 toca `scripts/`, `.github/` y `tests/test_vigilante.py`. T3 solo
  **lee** `resources/datos/precios.json`, que cerró T1. Ningún test de T2 lee `.github/`.
- T6 ∥ T7: T6 toca `valoracion.py`, `web/metrics.py` y sus tests; T7 toca `checks.py`,
  `docs/wiki/Integration-install.md`, `tests/test_checks.py`, `tests/test_wiki.py` y su test nuevo.
  T7 importa `coste`, `atribucion` y `recalcular`, ya cerrados; no importa `valoracion`. Ningún test
  de `test_metrics.py`, `test_dashboard_*` o `test_captura.py` importa `checks`.
- **T4 y T5 van en serie** (revisión del plan, importante 4): la suite de T4 importa `cli.py`
  (`test_smoke.py`, `test_clients.py`, `test_daemon.py`, `test_install_*`) y la de T5 lee `config.py`
  (`test_aislamiento_entorno.py`), los ficheros que la otra estaría editando. En serie, el
  inventario de T4 corre la suite entera sin `--ignore`.
- El resto, en serie y por qué: T1 antes de todo (los demás importan `precios`); T2 antes de T4
  (`server.py`, la memoria por petición que usan los mensajes de REQ-035) y de T5 (formato del
  relleno, exclusión y plazo); T4 y T5 antes de T6 y T7 (fusión, tramos y agregados); T8 necesita
  todo el código; T9 cita las cifras de T8; T10 verifica lo que documenta T9.

**Reglas de las olas en paralelo.**

- Cada agente corre **solo** los ficheros de test de su tarea más los existentes que su tarea nombra.
  La suite completa la corre el agente de integración, cuando las dos tareas han terminado.
- Los agentes de la pareja **no escriben** `verification.md`. Cada uno deja su evidencia (salidas de
  pytest, el assert que disparó cada control, el inventario) en un fichero propio,
  `evidencias/T<n>.md` dentro de la carpeta del cambio, del que es el único escritor. El agente de
  integración enlaza esos ficheros desde `verification.md` y **no los reescribe** (un subagente que
  transporta texto lo reescribe: memoria del repo, jornada del 2026-09-22).
- La regla «sin ficheros ajenos» se comprueba con `git diff --stat -- <ficheros de la tarea>`: en una
  ola en paralelo el árbol también tiene los de la pareja.

**Integración al final de cada ola** (paso con dueño): en las olas de una tarea, el agente de la
tarea; en las parejas, un agente de integración (I2, I5). Corre
`bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q` (la suite completa con Playwright),
`uv run ruff check .`, `uv run ruff format --check .` y el `node --check` del JS si la ola tocó
`web/metrics.py`. **Quién arregla un rojo:**

- El integrador arregla **solo lo mecánico**: `ruff`, imports, finales de línea, el bit de ejecución.
- Un rojo **de comportamiento** (una cifra, un control, un test que cambia de significado) vuelve al
  agente dueño de la tarea, retomado con su contexto (`SendMessage`), que lo arregla, vuelve a correr
  el control afectado y lo anota en su `evidencias/T<n>.md` (o en `verification.md`, si la ola es
  suya). La ola no se cierra hasta que la suite está en verde.

**Commits y estado.** Un commit **firmado** por tarea, con rutas explícitas (`git add <ficheros>`,
nunca `git add .`) y sin coautoría de Claude (regla del repo). En las olas de una tarea lo hace el
agente de la tarea al cerrar su integración; en las parejas, el integrador al cerrar la ola, uno por
tarea. `state.json` lo actualiza solo la sesión principal.

Comandos pesados (pytest, Playwright, `uv tool install`, el comando sobre los transcripts reales)
**siempre** con `bash ~/.claude/scripts/pesado.sh <comando>`. `ruff` y `node --check` son ligeros.

### Propiedad de ficheros

| Fichero | EOL | Dueño (en orden) | Zona |
|---|---|---|---|
| `src/local_delegate/resources/datos/precios.json`, `densidad.json` (nuevos) | LF | T1 | |
| `src/local_delegate/precios.py` (nuevo), `tests/test_precios.py` (nuevo) | LF | T1 | |
| `src/local_delegate/clients.py` | CRLF | T2 | dos `ContextVar` nuevos (`tool_use_id` y memoria por petición), `tool_use_id_actual()`, `observar_cliente` |
| `src/local_delegate/resources/hooks/anotar_llamada.py` (nuevo) | LF | T2 | |
| `src/local_delegate/resources/hooks/hook_common.py` | LF | T2 | `directorio_de_notas_de_llamadas`, `anotar_llamada` |
| `src/local_delegate/install.py` | CRLF | T2 | `_HOOK_EVENTS`, `_SCRIPT_NAMES` |
| `src/local_delegate/atribucion.py` (nuevo), `tests/test_atribucion.py` (nuevo) | LF | T2 | |
| `src/local_delegate/server.py` | CRLF | T2 → T4 | T2: `_log_event` (campos `tool_use_id` y `caller_*`). T4: cuerpo de `tokens_claude`, `_escribir_destino` (recibo), `_savings_feedback` y sus cuatro llamadas, `tokens_aprox` de `local_extract`, lector del log de `local_status` |
| `tests/test_clients.py` | CRLF | T2 | tests del `tool_use_id` con el arnés que ya existe (`_firmar`) |
| `tests/test_install.py`, y lo que salga del inventario de T2 | LF / comprobar | T2 | |
| `scripts/vigilante_precios.py` (nuevo) | LF | T3 | |
| `.github/workflows/vigilante-precios.yml` (nuevo) | LF | T3 | |
| `.github/workflows/ci.yml`, `.github/workflows/codeql.yml` | LF | T3 | solo `workflow_dispatch:` en `on:` |
| `.github/vigilante/limites-de-uso.txt` (nuevo) | LF | T3 | |
| `tests/fixtures/vigilante/` (nuevo), `tests/test_vigilante.py` (nuevo) | LF | T3 | |
| `src/local_delegate/config.py` | LF | T4 | solo `COSTE_RESPALDO` |
| `src/local_delegate/coste.py` (nuevo), `tests/test_densidad.py` (nuevo) | LF | T4 | |
| `src/local_delegate/web/metrics.py` | CRLF | T4 → T6 | T4: `_load` (fusión), JS `tokensClaude` (cuerpo), `CPT`/`tok` solo para el coste local, pie «~4 chars/token». T6: `/api/stats` (claves nuevas y ventanas móviles de la cuota), HTML y JS de los bloques de coste, cuota e imágenes, `<meta name="description">` y la frase «cuota que no gastaste» |
| `tests/test_metrics.py` | LF | T4 → T6 | T4: paridad y tests del inventario. T6: tests de `/api/stats` que comparan el JSON entero |
| `tests/test_dashboard_js.py` | LF | T4 | tests de `byDay`/`acct` del inventario (filas resueltas) |
| `tests/test_core.py`, `tests/test_vision.py`, `tests/test_boilerplate_salida.py`, `tests/test_resumen_estructurado.py` | LF | T4 | solo lo que salga del inventario |
| `src/local_delegate/transcripts.py`, `cuota.py`, `recalcular.py` (nuevos) | LF | T5 | |
| `src/local_delegate/cli.py` | CRLF | T5 | subparser y `cmd_recalcular_coste` |
| `tests/test_transcripts.py`, `tests/test_cuota.py`, `tests/test_recalcular.py` (nuevos) | LF | T5 | |
| `src/local_delegate/valoracion.py` (nuevo), `tests/test_valoracion.py`, `tests/test_panel_coste.py` (nuevos) | LF | T6 | |
| `tests/test_dashboard_ui.py` | CRLF | T6 | un test de los bloques nuevos |
| `src/local_delegate/checks.py` | LF | T7 | `Context.log_dir`, `_probe_coste`, entrada de `CHECKS`, las frases de tamaño |
| `tests/test_checks.py`, `tests/test_wiki.py` | LF | T7 | solo `_NUMERO[22]` y `_NUMERO_DE_CHECKS[22]` |
| `tests/test_coste_doctor.py` (nuevo) | LF | T7 | |
| `docs/wiki/Integration-install.md` | CRLF | T7 → T9 | T7: fila de la tabla del doctor y «las veintidós piezas». T9: el hook nuevo en la lista de hooks |
| `CHANGELOG.md`, `README.md` | CRLF | T9 | |
| `docs/wiki/Savings-and-metrics.md`, `Configuration.md`, `Troubleshooting.md`, `Repo-hardening.md`, `Architecture.md`, `docs/recipes/claude-code-hooks.md` | LF / comprobar | T9 | |
| `scripts/dev/capture_dashboard.py` | LF | T9 | mock de `/api/stats` y `/api/events` |
| `verification.md` | LF | el escritor de la ola (tabla de olas) | |
| `evidencias/T2.md`, `T3.md`, `T6.md`, `T7.md` (nuevos) | LF | el agente de cada tarea en paralelo | |

Reglas comunes (las del panel, que siguen valiendo):

- Antes de editar, `git ls-files --eol <fichero>`; después, el mismo EOL y
  `git diff --stat -- <ficheros de la tarea>`. Editar con la herramienta Edit: el heredoc de Git
  Bash colapsa barras invertidas y `write_text` convierte finales de línea.
- **JS compilable al pasar el turno**: toda tarea que toque `web/metrics.py` termina con la
  extracción de `<script>` de `metrics.HTML` a `<scratchpad>/panel.js` y `node --check`, sin errores
  (comando exacto en el plan del panel, «Reglas comunes»).
- **Scripts nuevos con `#!`**: `test_wiki.py::test_un_script_con_shebang_esta_marcado_ejecutable_en_git`
  solo ve ficheros añadidos a git. T2 y T3 corren ese test después de `git add` y, si el script lleva
  `#!`, `git update-index --chmod=+x`.
- **Datos privados**: los transcripts reales solo los lee `local-delegate recalcular-coste` (T8 y
  T10) o los scripts de solo lectura de `insumos/scripts/`. Los tests construyen transcripts,
  registros del statusline y logs **sintéticos** en `tmp_path`. Ningún fixture lleva un id de
  sesión, una ruta o un texto real. Los tests que lanzan el hook ponen `TEMP`, `TMP` y `TMPDIR` del
  subproceso en `tmp_path`, para no escribir en el temporal real que lee el daemon en vivo.

### Cómo se escribe el control positivo de cada test

Los tres tipos del plan del panel, sin cambios: **(a)** contra el código de antes, **(b)** mutante
nombrado que muta de verdad (cada uno dice por qué muta), **(c)** contra un corte intermedio solo de
interfaz. La tarea anota **qué assert disparó**, copiado de la salida de pytest. Nunca vale un fallo
por `KeyError`, `AttributeError`, `ImportError`, `FileNotFoundError`, `JSONDecodeError` o
`ValueError` de desempaquetado: los campos nuevos se leen con `.get(...)`, un fichero que aún no
existe se comprueba antes con `assert ruta.is_file()`, una función que aún no existe pide un corte
(c), una excepción que el mutante dejaría escapar se captura en el test y se convierte en un assert
(`escapo`), y los `TestClient` de los tests de errores del servidor van con
`raise_server_exceptions=False`.

Los controles marcados **«comprobado»** se ejecutaron el 2026-10-06 contra el código de
`feat/panel-honesto` con `scratchpad/controles/comprobar.py` (reimplementaciones desechables, sin
tocar el producto):

- `cli.run(["recalcular-coste"])` hoy sale con `SystemExit(2)` (subcomando desconocido), y
  `cli.main` **no existe**.
- `TestClient(metrics.app)` con un `JSONDecodeError` dentro de `/api/stats` lanza el
  `JSONDecodeError` en el test; con `raise_server_exceptions=False` devuelve **500**.
- Una `RuntimeError` dentro de `_log_event` **sale** de la función (su `try` general solo atrapa
  `OSError`).
- `urllib.request.urlopen` pasa por `socket.create_connection` tanto con un nombre
  (`platform.claude.com`) como con una IP literal (`192.0.2.1`): registrando `getaddrinfo`,
  `create_connection` y `connect`, el mutante deja un intento en los dos casos, sin red. Registrando
  solo `connect`, con IP literal también deja uno.
- Notas una por fichero: dos escrituras seguidas (`toolu_a`, `toolu_b`) dejan las dos legibles; con
  un nombre de fichero fijo, la primera se pierde.

## Ordered tasks

### T0 — Arranque y comprobaciones previas (ola 0)

- **Ficheros:** ninguno del código. Escribe `verification.md` (entorno y hallazgos).
- **Qué se hace:**
  1. **Precondición**: `panel-cuentas-y-estados-honestos` mezclado en `main` (su PR cerrado como
     mezclado y su gate `conformance` aprobado en su `state.json`) y `daemon-reparte-el-backend`
     **sin** mezclar. Si no, se para y se avisa. Rama nueva `feat/coste-api-y-cuota` desde `main`.
  2. **Leer cómo quedó el contrato**, sin dar nada por hecho: `server.tokens_claude`,
     `server._accounting`, el lector del log de `local_status`, `metrics._load`, `metrics._aggregate`,
     y en el JS `acct`, `tokensClaude`, `tok` y `CPT`. Comparar con la tabla «Campos por evento» y la
     firma del contrato. Si un nombre o una firma difiere, **se para** y se lleva a la sesión
     principal: este plan no redefine el contrato.
  3. `len(checks.CHECKS) == 21` y `len(install._HOOK_EVENTS) == 1`; si no, se para («Orden entre
     cambios»).
  4. Línea base: `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q` en verde, con el
     conteo.
  5. **GitHub, solo lectura** (para T3 y T11):
     `gh api repos/ZahiriNatZuke/local-delegate/actions/permissions/workflow` (si
     `can_approve_pull_request_reviews` es `false`, un workflow **no puede abrir PRs** con
     `GITHUB_TOKEN`; cambiarlo es una decisión de seguridad del repo y va al usuario **ya**, aunque
     T3 se implemente igual) y `gh api repos/ZahiriNatZuke/local-delegate/rulesets/19859628` (los
     seis checks y la regla `code_scanning` siguen como dice REQ-025; si no, se avisa).
  6. **Plazo de borrado en vigor** (solo fechas y conteos, sin abrir contenido): `H` leído de
     `~/.claude/settings.json`, la `mtime` del transcript más antiguo bajo `~/.claude/projects` y si
     hay alguno de más de 30 días (prueba de que el plazo de 90 está en vigor). Anotar desde qué día
     es rellenable el log.
  7. **Evidencia del directorio temporal compartido**: contar las líneas del log de uso con
     `bloqueo_id` (`grep -c`): solo existen si el daemon leyó una nota que dejó un hook en
     `tempfile.gettempdir()`. La revisión contó 31 (la última, del 2026-10-06, con
     `client: claude-code`).
- **Rollback:** nada que revertir.

### T1 — Tablas del paquete y cotejo puro (ola 1)

- **Ficheros:** `resources/datos/precios.json`, `resources/datos/densidad.json`, `precios.py`,
  `tests/test_precios.py`.
- **Requisitos:** REQ-010, REQ-011, REQ-012 (cargador), REQ-013, REQ-030 (datos).
- **Qué se hace:**
  1. **Comprobar `admite_esfuerzo`** de los modelos heredados en la página oficial de cada uno
     (WebFetch; es la «tarea del plan» que pide la traza de REQ-010–012). Se anota en
     `verification.md` URL, fecha y lo que dice cada página. Si una página no lo dice, queda `true`
     con la marca de supuesto en `_nota` y se avisa a la sesión principal.
  2. Las dos tablas desde los prototipos `insumos/scripts/precios.json` y `densidad.json`, con
     `consultado` = fecha del último cambio, y en la de densidad la lista `medido_con` por familia
     (`nueva`: Opus 5.5, Sonnet 5.5, Opus 5, Fable 5.1; `anterior`: Haiku 4.5), que el prototipo no
     trae y REQ-030 pide.
  3. `precios.py`: `cargar_precios()`, `cargar_densidad()` (con `importlib.resources`, en caché);
     `normalizar_id(mid)`; `entrada(mid) -> dict | None` (búsqueda **exacta** tras normalizar);
     `familia(mid) -> str | None`; `cotejar(filas, tabla) -> list[str]` (`dentro` | `fuera` |
     `sin_precio` | `None` para las de menos de $0,05) y `veredicto(resultados) -> "pasa" | "falla"`.
     Port de `insumos/scripts/cotejo.py:juzga` con la búsqueda web incluida.
- **Tests (`tests/test_precios.py`):**

  | Test | Control | Debe fallar con el mutante en |
  |---|---|---|
  | `test_normaliza_fecha_y_1m`: `entrada("claude-haiku-4-5-20251001")` y `entrada("claude-opus-5-5[1m]")` no son `None` | (b) | Mutante: no quitar la fecha → falla `assert entrada("claude-haiku-4-5-20251001") is not None` (muta: el id con fecha no es clave de la tabla) |
  | `test_busqueda_exacta_en_los_pares`: lectura de `claude-opus-5` = 0,50 y de `claude-opus-5-5` = 0,20; lectura de `claude-fable-5` = 1,0 y de `claude-fable-5-1` = 0,25 | (b) | Mutante: «primera clave que empieza por el id» → falla `assert entrada("claude-opus-5")["lectura"] == 0.50` (da 0,20: en la tabla `claude-opus-5-5` va antes que `claude-opus-5`, comprobado por la revisión) |
  | `test_un_id_sin_entrada_no_tiene_precio` (`claude-opus-9`) | (b) | Mutante: `.get(id, {})` → falla `assert entrada("claude-opus-9") is None` |
  | `test_la_tabla_cubre_los_13_ids` | guarda | `assert sorted(tabla["modelos"]) == sorted(IDS_DE_LA_SPEC)` |
  | `test_cotejo_con_filas_literales` (escenario de la spec): filas **literales** de `cost-state` reducidas a sus seis campos y congeladas en el test, sacadas una vez con un script de solo lectura del scratchpad (solo números e id de modelo). Tienen que incluir una de `claude-opus-5`, una de `claude-opus-5-5` con mucha lectura de caché, otra de Opus 5.5 con mucha salida, una de Haiku con `webSearchRequests > 0` que solo cae `dentro` contando la búsqueda web, y una de menos de $0,05 | guarda y datos mutados | Guarda: con la tabla sin mutar, `assert veredicto(r) == "pasa"` y todas `dentro` salvo la de < $0,05 (`None`). Tabla sin `claude-opus-5` → `assert veredicto(r) == "falla"` y `"claude-opus-5"` en las `sin_precio`; lectura de Opus 5.5 ×0,8 → `assert veredicto(r) == "falla"`; salida de Opus 5.5 ×0,8 → ídem. El agente comprueba con `cotejo.py` que cada fila elegida cae `fuera` con su mutación antes de congelarla |
  | `test_el_cotejo_cuenta_la_busqueda_web` | (b) | Mutante: `cotejar` sin la búsqueda web → falla la guarda `assert veredicto(r) == "pasa"` por la fila de Haiku (muta: research §2, 4 de 142 filas reales de Haiku salen `fuera` sin ella) |
  | `test_cargar_las_tablas_no_abre_sockets` (`socket.getaddrinfo`, `socket.create_connection` y `socket.socket.connect` sustituidos por registradores que lanzan `OSError`; la carga va en `try`) | (b) | Mutante: el cargador hace `urllib.request.urlopen(tabla["fuente"])` → falla `assert intentos == []` (**comprobado**: `urlopen` pasa por `create_connection` también sin red) |
- **Verificación:** `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_precios.py -q`; después la
  integración de la ola.
- **Rollback:** borrar los ficheros nuevos; nadie los usa hasta la ola 2.

### T2 — Atribución en vivo: `tool_use_id`, hook, resolución y reglas comunes (ola 2, en paralelo con T3)

- **Ficheros:** zona T2 de `clients.py`, `server.py` y `install.py`; `anotar_llamada.py`,
  `hook_common.py`, `atribucion.py`; `tests/test_atribucion.py`, `tests/test_clients.py`,
  `tests/test_install.py` y lo que salga del inventario (paso 1). Evidencia en `evidencias/T2.md`.
- **Requisitos:** REQ-001, REQ-002, REQ-003; el formato y la clave de REQ-005; la exclusión de
  REQ-007; el plazo `H` de la enmienda 1.
- **Qué se hace, en este orden:**
  0. **Medir antes de diseñar el control de REQ-001**: con el arnés de `tests/test_clients.py`
     (`_firmar`), un script del scratchpad manda un `tools/call` con
     `_meta = {"claudecode/toolUseId": "toolu_prueba"}` y anota por qué atributo del contexto del
     middleware llega (`ctx.meta`, según el insumo, sin ejecutar) y si `ClientSession.call_tool`
     acepta `meta` o hace falta mandar la petición a mano. Si no llega por ningún sitio, se para y
     se avisa: REQ-001 depende de eso.
  1. **Inventario de lo que depende de la lista de hooks**: `rg -n "_HOOK_EVENTS|_SCRIPT_NAMES|HOOKS_ESPERADOS|PreToolUse" tests/ scripts/`.
     Cuando se escribió el plan: `tests/conftest.py:116`, `tests/test_checks.py:574`,
     `tests/test_install.py:289` y `:459`, `tests/test_update.py:800` y
     `scripts/check_install_e2e.py:38` (que usa `len(install._HOOK_EVENTS)`, así que sigue
     cuadrando); el `rg` manda. El hook nuevo va **al final** de `_HOOK_EVENTS` para que
     `_HOOK_EVENTS[0]` siga siendo el de `UserPromptSubmit`.
  2. **Corte de interfaz**: `clients.tool_use_id_actual()` (devuelve `None`), `atribucion.py` con
     sus firmas (`leer_nota`, `resolver_llamada`, `llamada_actual`, `claves_del_fichero`,
     `leer_relleno`, `escribir_relleno`, `excluida`, `plazo_de_borrado`) y comportamiento vacío.
     Suite de T2 en verde.
  3. Tests de la tabla; comprobar cada control.
  4. `observar_cliente` lee `claudecode/toolUseId` del `_meta` y lo pone en su `ContextVar`, y pone
     un dict vacío en el `ContextVar` de la memoria, antes de `call_next` y dentro del mismo `try`
     que traga todo.
  5. Hook: lee stdin, valida el `tool_use_id`, escribe `{tool_use_id, ts, agent_id, agent_type,
     effort, transcript_path}` en su fichero (temporal + `os.replace`), con `effort` =
     `entrada["effort"]["level"]` (nunca `CLAUDE_EFFORT`), borra best-effort las notas de más de
     10 min, no imprime nada y sale con 0 **siempre**, también con stdin roto.
  6. `atribucion.resolver_llamada(tool_use_id, *, notas=None, ahora=None, reloj=time.monotonic,
     abrir=open)`: nota de menos de 10 min (una nota ilegible o a medias = sin nota); ruta del
     transcript validada (bajo `~/.claude/projects`, `.jsonl`); transcript del subagente o del
     principal; lectura de la **cola** de 256 KB como máximo, buscando la línea con ese
     `tool_use_id` de atrás adelante, con 50 ms de presupuesto medidos con `reloj`;
     `caller_agent_type` **solo** si hay `agent_id`; `caller_effort = "n/a"` si falta y el modelo
     tiene `admite_esfuerzo: false` en la tabla de T1. `llamada_actual()` memoriza el resultado en
     el `ContextVar` de la petición.
  7. `_log_event` escribe `tool_use_id` y los `caller_*` en **su propio** `try ... except
     Exception`, para que un fallo de la resolución no se lleve la línea ni salga de la función.
  8. `atribucion.claves_del_fichero(filas)`: `tool_use_id` si lo hay; si no, `ts|tool|ordinal`.
     `escribir_relleno(log_dir, mes, entradas)` funde con lo que hay: una entrada solo se sustituye
     por otra de cruce mejor (`exacto` > `ventana` = `ventana+path` > `ambiguo` = `sin_cruce`).
     `excluida(fila, entrada)` y `plazo_de_borrado(claude_dir)`.
  9. `install.py`: el hook en `_HOOK_EVENTS` y `_SCRIPT_NAMES`.
- **Tests (`tests/test_atribucion.py` salvo que se diga otra cosa):**

  | Test | Control | Debe fallar con el mutante / en el corte en |
  |---|---|---|
  | `test_clients.py::test_la_tool_ve_el_tool_use_id` (arnés `_firmar` con `_meta`) | (c) tras el paso 2 | `assert visto == "toolu_prueba"` (en el corte, `None`) |
  | `test_clients.py::test_sin_meta_no_hay_tool_use_id` | guarda | `assert visto is None` |
  | `test_ida_y_vuelta_hook_servidor` (el hook se lanza como proceso con su JSON por stdin, `CLAUDE_EFFORT=high` y `TEMP`/`TMP`/`TMPDIR` = `tmp_path` en su entorno; la nota se lee con `atribucion.leer_nota`) | (b) | Mutante: el hook toma `os.environ.get("CLAUDE_EFFORT")` → falla `assert nota.get("effort") == "low"` (muta: el entorno dice `high` y el campo `low`) |
  | `test_el_hook_calla_y_sale_con_0` (con stdin válido, con stdin roto y con un `tool_use_id` que no casa con el patrón) | (b) | Mutante: el hook imprime la nota → falla `assert proc.stdout == ""`. Con el id malo, `assert list(dir_notas.iterdir()) == []` |
  | `test_dos_llamadas_no_se_pisan` (dos notas seguidas, `toolu_a` y `toolu_b`) | (b) | Mutante: nombre de fichero fijo → falla `assert leer_nota("toolu_a") is not None` (**comprobado**: con nombre fijo la primera se pierde) |
  | `test_ocho_hooks_a_la_vez` (8 procesos del hook lanzados juntos) | guarda | `assert sum(leer_nota(i) is not None for i in ids) == 8` |
  | `test_una_nota_a_medias_es_sin_nota` (fichero con `{"tool_use_id": `) | (b) | Mutante: `leer_nota` sin `try` → el test captura la excepción en `escapo` y falla `assert not escapo` |
  | `test_resuelve_el_modelo_del_subagente` (transcripts sintéticos bajo un `~/.claude/projects` de `tmp_path`: principal `s1.jsonl` **sin** ese `tool_use_id`, subagente `s1/subagents/agent-a1.jsonl` con la línea `assistant` de `claude-opus-5-5`; nota con `agent_id: a1`, `agent_type`, `effort: low`) | (b) | Mutante: buscar en el `transcript_path` de la nota en vez del del subagente → falla `assert r.get("caller_model") == "claude-opus-5-5"` (da `None`). Después `caller_kind == "subagent"`, `caller_agent_type == AGENTE`, `caller_effort == "low"`, `caller_src == "hook+transcript"` |
  | `test_en_el_principal_no_hay_agent_type` (nota sin `agent_id`) | (b) | Mutante: copiar siempre `agent_type` → falla `assert "caller_agent_type" not in r` |
  | `test_una_ruta_fuera_de_projects_no_se_abre` (`transcript_path` = un `.jsonl` fuera de `~/.claude/projects`, con la línea buena dentro) | (b) | Mutante: sin la validación → falla `assert r.get("caller_model") is None` (muta: el fichero tiene la línea) |
  | `test_la_carrera_deja_caller_src_hook` (nota sí, línea no) | guarda | `assert r.get("caller_src") == "hook"` y `"caller_model" not in r` |
  | `test_una_nota_vieja_no_cuenta` (11 min) | (b) | Mutante: sin el filtro de edad → falla `assert "caller_kind" not in r` |
  | `test_haiku_sin_esfuerzo_es_na_y_opus_sin_esfuerzo_falta` | (b) | Mutante: `n/a` para todo esfuerzo que falte → falla `assert "caller_effort" not in r_opus` |
  | `test_no_lee_mas_de_256_kb` (transcript de 50 MB con la línea fuera de la cola; `abrir` envuelto en un espía que suma los bytes leídos) | (b) | Mutante: leer el fichero entero → falla `assert leidos <= 256 * 1024` (muta: el fichero pesa 50 MB) |
  | `test_el_presupuesto_de_50_ms_corta` (`reloj` que avanza 60 ms por llamada; la línea **dentro** de la cola) | (b) | Mutante: ignorar el reloj → falla `assert r.get("caller_model") is None` (muta: sin el corte la línea se encuentra) |
  | `test_log_event_escribe_la_atribucion_y_ningun_id_de_sesion` (log en `tmp_path`, `tool_use_id_actual` fijado, nota y transcript sintéticos con un `session_id` marcador) | (c) tras el paso 2 | `assert linea.get("tool_use_id") == "toolu_x"` (en el corte, `None`); después `assert "session_id" not in linea` y `assert marcador not in json.dumps(linea)` |
  | `test_una_resolucion_rota_no_se_lleva_la_linea` (`resolver_llamada` sustituido por uno que lanza `RuntimeError`; la llamada a `_log_event` va en un `try` del test que anota `escapo`) | (b) | Mutante: la resolución sin su `try` propio → falla `assert not escapo` (**comprobado**: una `RuntimeError` sale de `_log_event`, cuyo `try` general solo atrapa `OSError`). Después `assert len(lineas) == 1` |
  | `test_la_resolucion_se_hace_una_vez_por_peticion` (espía sobre `resolver_llamada`; se pide desde `_log_event` y desde `llamada_actual()` dentro de la misma petición, con el arnés de `test_clients.py`) | (b) | Mutante: sin memoria → falla `assert espia.llamadas == 1` |
  | `test_la_memoria_no_cruza_peticiones` (dos peticiones seguidas con el arnés) | (b) | Mutante: memoria en un dict del módulo → falla `assert len(memoria_de_la_segunda) == 1` (muta: en el módulo se acumulan las dos) |
  | `test_dos_lineas_del_mismo_segundo_no_comparten_clave` (escenario de la spec; después se añade una tercera) | (b) | Mutante: clave `ts|tool` → falla `assert len(set(claves)) == 2`. Y `assert claves[:2] == claves_antes` tras añadir la tercera |
  | `test_el_relleno_solo_mejora` (`ventana` sobre `exacto` no sustituye; `ventana` sobre `ambiguo` sí) | (b) | Mutante: escribir siempre la nueva → falla `assert entradas[clave]["cruce"] == "exacto"` |
  | `test_excluida` (`codex-mcp-client`, `mcp`, entrada `banco`, `claude-code`) | (b) | Mutante: sin la rama de `banco` → falla `assert excluida(f, {"banco": True}) == "pruebas"` |
  | `test_plazo_de_borrado` (sin `settings.json` → 30; `cleanupPeriodDays: 90` → 90; `"abc"`, `0` y `-5` → 30) | (b) | Mutante: devolver 30 siempre → falla `assert plazo_de_borrado(d) == 90` |
  | `test_install.py::test_el_hook_de_atribucion_se_registra` (HOME temporal) | (a) | `assert ("PreToolUse", "mcp__local-delegate__.*") in registrados` |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_atribucion.py tests/test_clients.py tests/test_install.py tests/test_correlacion.py tests/test_hook_common.py tests/test_checks.py tests/test_update.py tests/test_aislamiento_entorno.py -q`
  (`test_aislamiento_entorno.py` cubre que el hook no lea variables sin declarar), y tras `git add`,
  el test del shebang. Después, la integración I2.
- **Rollback:** revertir; `tool_use_id` y `caller_*` son claves opcionales del log, y el hook se
  retira añadiéndolo a `_SCRIPTS_RETIRADOS` (si no, su copia en `~/.claude/hooks/` se vuelve
  inmortal).

### T3 — Vigilante semanal de precios y límites (ola 2, en paralelo con T2)

- **Ficheros:** `scripts/vigilante_precios.py`, `.github/workflows/vigilante-precios.yml`,
  `workflow_dispatch:` en `ci.yml` y `codeql.yml`, `.github/vigilante/limites-de-uso.txt`,
  `tests/fixtures/vigilante/` (`precios.html`, `limites.html`, `limites-esperado.txt`),
  `tests/test_vigilante.py`. Evidencia en `evidencias/T3.md`.
- **Requisitos:** REQ-020 a REQ-024, y el código de REQ-025 (su comprobación real es T11).
- **Qué se hace:**
  1. Las dos páginas se descargan **una vez** a `tests/fixtures/vigilante/` (datos de test, nunca se
     ejecutan; el vigilante no las toca). `limites-esperado.txt` es el texto que el test espera,
     **distinto** del `limites-de-uso.txt` que actualiza el PR de límites.
  2. Script, solo stdlib, con funciones puras y la E/S aparte:
     `extraer_tabla_precios(html) -> dict` (falla en voz alta: sin cabecera «Model pricing», menos de
     5 filas, una celda que no es número; ignora «retired» y «limited availability»; quita
     `<sup>…</sup>` y paréntesis); `nombre_a_id(nombre)` (regla de REQ-021); `comparar(nueva,
     paquete) -> cambios` (un modelo que desaparece **no** se borra y se lista aparte; los ids
     nuevos, también aparte); `cuerpo_pr_precios(cambios)` y `cuerpo_pr_limites()` (con el comando
     de reinicio de REQ-057); `extraer_texto_limites(html) -> str` (falla con menos de 500
     caracteres o sin título); y `main()` con un cliente HTTP inyectable `api(metodo, ruta, cuerpo)`
     sobre `GITHUB_TOKEN`.
  3. Flujo de GitHub en `main()`: rama fija; commits por la **API de contenidos**
     (`PUT /repos/{o}/{r}/contents/{ruta}`), nunca `git push`; abrir el PR o, si ya hay uno abierto
     de esa rama, actualizarlo; si la rama va por detrás de `main`, `PUT /pulls/{n}/update-branch`;
     lanzar `POST /actions/workflows/ci.yml/dispatches` y `.../codeql.yml/dispatches` con `ref` = la
     rama; esperar a que terminen los dos (sondeo de los runs por `head_sha`, techo de 45 min) y, si
     el PR queda `blocked` con los checks en verde, comentar en el PR la salida de REQ-025 (cerrar y
     reabrir a mano). Entrada `ensayo` del `workflow_dispatch`: fuerza un diff inocuo
     (`consultado` = hoy) en la rama `vigilante/ensayo`, con «[ensayo]» en el título; es lo que usa
     T11.
  4. Workflow: cron semanal y `workflow_dispatch` (con la entrada `ensayo`); `permissions:`
     **solo** `contents: write`, `pull-requests: write`, `actions: write`; `timeout-minutes: 60`;
     sin instalar nada, `python3 scripts/vigilante_precios.py`. `ci.yml` y `codeql.yml` ganan
     `workflow_dispatch:` y nada más (sus `permissions` siguen en `contents: read`).
- **Tests (`tests/test_vigilante.py`):**

  | Test | Control | Debe fallar con el mutante / hoy en |
  |---|---|---|
  | `test_la_pagina_intacta_da_la_tabla_congelada` (la esperada va **escrita en el test**) | (b) | Mutante: no quitar `<sup>…</sup>` → falla `assert tabla == ESPERADA` (muta solo si la copia guardada tiene notas al pie en los nombres: el agente lo comprueba; si no las tiene, el mutante es «no ignorar las filas retired» y comprueba que la copia tiene una) |
  | `test_un_precio_cambiado_da_ese_diff` (lectura de `claude-opus-5-5` alterada en la copia) | (b) | Mutante: `comparar` solo mira entrada y salida → falla `assert cambios == [("claude-opus-5-5", "lectura", 0.20, NUEVO)]` |
  | `test_un_modelo_nuevo_sale_listado_en_el_pr` (fila nueva en la copia) | (b) | Mutante: el cuerpo no lista ids nuevos → falla `assert "claude-nuevo-9" in cuerpo` |
  | `test_sin_cabecera_falla` / `test_menos_de_5_filas_falla` / `test_una_celda_que_no_es_numero_falla` | (b) | Mutante: devolver `{}` sin cabecera → falla `pytest.raises(ErrorDelVigilante)`. Mutante: saltar la celda ilegible → falla el tercero |
  | `test_un_modelo_que_desaparece_no_se_borra` | (b) | Mutante: la tabla nueva sustituye a la del paquete → falla `assert "claude-opus-4-5" in resultado["modelos"]` |
  | `test_limites_intacta_da_el_texto_esperado` / `_con_un_parrafo_cambiado_da_diff` / `_vaciada_falla` | (b) | Mutante: sin el umbral de 500 caracteres → falla `pytest.raises(ErrorDelVigilante)` con la página vaciada |
  | `test_el_pr_de_limites_dice_como_reiniciar` | (b) | Mutante: cuerpo sin el comando → falla `assert "recalcular-coste --reiniciar-calibracion" in cuerpo` |
  | `test_el_pr_se_hace_por_la_api_y_lanza_los_dos_checks` (cliente `api` falso que registra las llamadas; `main` con la página alterada) | (b) | Mutante: lanzar solo `ci.yml` → falla `assert {"ci.yml", "codeql.yml"} <= despachados`. Y `assert ("PUT", RUTA_CONTENIDOS_PRECIOS) in llamadas`, con `RUTA_CONTENIDOS_PRECIOS` = `/repos/{o}/{r}/contents/src/local_delegate/resources/datos/precios.json` (el commit va por la API de contenidos, que lo firma, y no por `git push`) |
  | `test_si_ya_hay_pr_lo_actualiza` (el falso devuelve un PR abierto de la rama) | (b) | Mutante: abrir siempre uno nuevo → falla `assert not any(m == "POST" and r.endswith("/pulls") for m, r in llamadas)` |
  | `test_si_main_avanzo_actualiza_la_rama_y_relanza` (el falso dice `behind`) | (b) | Mutante: no llamar a `update-branch` → falla `assert ("PUT", f"/pulls/{n}/update-branch") in llamadas` |
  | `test_si_queda_blocked_lo_dice_en_el_pr` (checks en verde y `mergeable_state: blocked`) | (b) | Mutante: no comentar → falla `assert any(r.endswith("/comments") for _m, r in llamadas)` |
  | `test_el_workflow_tiene_lo_justo` (PyYAML del grupo dev; ojo: PyYAML lee la clave `on:` como `True`, así que se lee `datos.get("on", datos.get(True))`) | (a) | Primero `assert WORKFLOW.is_file()` (hoy no existe); después cron y `workflow_dispatch`, y `permissions == {"contents": "write", "pull-requests": "write", "actions": "write"}` |
  | `test_ci_y_codeql_aceptan_workflow_dispatch` (y siguen con `permissions: contents: read`) | (a) | `assert "workflow_dispatch" in on_de("ci.yml")` (hoy no) |
  | `test_el_script_es_solo_stdlib` (los `import` del AST contra `sys.stdlib_module_names`) | (b) | Mutante: `import requests` → falla `assert ajenos == []` |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_vigilante.py tests/test_ci_gate.py -q`
  (`test_ci_gate.py` lee `ci.yml` y tiene que seguir en verde con el disparador nuevo), y tras
  `git add`, el test del shebang. Después, la integración I2.
- **Rollback:** borrar el workflow y el script; quitar `workflow_dispatch:` de los dos workflows.

### I2 — Integración de la ola 2, con la prueba de humo del `_meta`

Dueño: un agente de integración, escritor único de `verification.md` en la ola. Las reglas de la
integración (arriba) y además, **antes de construir nada encima** (revisión del plan, importante 8):

- **Prueba de humo del `_meta` con Claude Code de verdad**: el servidor del repo en HTTP en un
  puerto libre (`uv run local-delegate serve` con el modo HTTP y `LOCAL_DELEGATE_LOG_DIR` en el
  scratchpad, sin tocar el daemon), y **una** llamada real desde Claude Code con
  `claude -p --mcp-config <fichero del scratchpad>` que pida un `local_summarize` con `path`. **Éxito**:
  la línea del log trae `tool_use_id` con forma `toolu_…`. **Fallo**: sin `tool_use_id`, se para la
  ola 3 y se lleva a la sesión principal (REQ-001 no se cumple con el cliente real). Se anota que esa
  llamada con `claude -p` marca la ventana de 5 h en curso como `contaminado` (REQ-052, paso 6). Las
  notas del hook no se prueban aquí (el hook no está instalado); eso es T10.3.
- Enlaza `evidencias/T2.md` y `evidencias/T3.md`; commits de T2 y T3.

### T4 — Densidad, conversión única y fusión (ola 3)

- **Ficheros:** zona T4 de `server.py`, `web/metrics.py`, `config.py`, `tests/test_metrics.py` y
  `tests/test_dashboard_js.py`; `coste.py`, `tests/test_densidad.py`; y los tests del inventario
  (pasos 3 y 5).
- **Requisitos:** REQ-006, REQ-007 (función de tramo), REQ-008 (respaldo y su variable), REQ-030 a
  REQ-038 (salvo el bloque «Imágenes» del panel, que es de T6).
- **Qué se hace, en este orden:**
  1. **Corte de interfaz**: `config.COSTE_RESPALDO`; `coste.py` con `clase_de_contenido`,
     `respaldo()`, `resolver_densidad(evento)` (todavía devuelve `{"text": [400, "hoy"],
     "returned": [400, "hoy"], "output": [400, "hoy"]}` y `null` en imagen), `fundir(filas, *,
     log_dir)` y `tramo(fila, *, ahora, plazo_dias)` (con `atribucion.excluida`); `_load` y el lector
     de `local_status` ya llaman a `fundir`; `tokens_claude` y `tokensClaude` sin cambiar. Suite en
     verde.
  2. `resolver_densidad` con las reglas de REQ-031/032 (familia, columna, clase, respaldo de celda
     en su único orden, marcas `familia supuesta` y `densidad de la familia`); `fundir` con el orden
     línea > relleno > respaldo, leyendo el relleno con `atribucion.leer_relleno`.
  3. **Primer inventario** (Python): con el cuerpo nuevo de `tokens_claude` puesto,
     `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q`, y anotar **cada** rojo en
     `verification.md`. Lista de partida, para no depender solo de la ejecución (revisión del plan,
     menor 14): `tests/test_metrics.py` (29 coincidencias, entre ellas
     `test_accounting_una_llamada_sin_trocear` y las de `local_status` hacia `:1018` y `:1040`),
     `tests/test_boilerplate_salida.py:295` (`8000 // config.CHARS_PER_TOKEN + 950`),
     `tests/test_vision.py:146` («68 bytes imagen ≈ 300 tokens»), `tests/test_core.py:493-494`
     (`"500 tokens"` es el `tokens_in` local de la coletilla, que REQ-035 quita) y
     `tests/test_resumen_estructurado.py:332` (la cola, que se conserva). Cada rojo es **(i)** un
     cambio de cifra esperado, que se reescribe con el número nuevo **literal** y su derivación en un
     comentario (nunca llamando a la función que se prueba, nunca relajando un `==` a una
     desigualdad); o **(ii)** un defecto, que se arregla en el código.
  4. `tokens_claude` (Python): imagen o `densidad[tipo]` ausente o nulo → 0; si no,
     `cantidad * 100 // c100`. `tokensClaude` (JS): lo mismo con
     `Math.floor(cantidad * 100 / c100)`. Primero Python (para el control (c) de la paridad) y
     después JS. `CPT` y `tok` quedan **solo** para el coste local; el pie dice «tokens de Claude por
     familia y tipo de contenido; modelo local ~4 chars/token».
  5. **Segundo inventario** (JS), después del paso 4: la misma suite. Se esperan los 8 de
     `tests/test_dashboard_js.py` que dependen de `acct` (sus eventos no traen `densidad`, así que el
     JS da 0). Esos tests pasan a recibir **filas resueltas**, con un ayudante de test que las
     construye con `coste.fundir`, como llegan en producción.
  6. Mensajes (REQ-034/035): el recibo de `_escribir_destino`, `_savings_feedback` (nueva firma con
     `evento`, sus cuatro llamadas) y `tokens_aprox` funden la fila en curso
     (`atribucion.llamada_actual()` y, sin nota, el respaldo), llaman a `resolver_densidad` y dicen
     los caracteres y «≈ N tokens de Claude», con `N` de `tokens_claude`. `local_describe_image` dice
     solo los bytes. La cola «que no entraron a tu contexto)» se conserva.
- **Tests:**

  | Test | Control | Debe fallar con el mutante / en el corte en |
  |---|---|---|
  | `test_metrics.py::test_paridad_acct_entre_python_y_el_js_del_panel` ampliado: **los 22 casos que ya existen y los nuevos pasan antes por `coste.fundir`** (si no, en el estado final Python resolvería y el JS daría 0). Casos nuevos de REQ-037 **en este orden**: prosa por `path` de Opus 5.5 (nueva, `formato_read`, `medida`); la misma inline (`sin_numerar`); `.md` por `path` de Haiku (anterior, respaldo (2), `sin_numerar`); `.bin` por `path` (clase `otro`, respaldo (3), `conservadora`); imagen con `chars_returned > 0`; modelo fuera de la tabla (`familia supuesta`). Se comparan `saved`, `returned`, `net` y los campos del contrato con `js.get(...)`. Guarda: orígenes `{medida, sin_numerar, conservadora}`, familias `{nueva, anterior}` y una imagen entre los resultados de Python | (c) y guarda | (c): corte = Python ya cambiado y JS todavía con ÷ 4 → falla `assert js.get("returned") == py["returned"]` en el **caso 0 de los que ya existen** (`_ev(tokens_in=1100, tokens_out=90)` por `path` sin extensión, clase `otro`: Python 179, JS 100), el primero de `_CAMPOS_PARIDAD` (cifras de la revisión del plan; el agente copia las que salgan). La guarda falla si falta un origen, una familia o la imagen |
  | `test_metrics.py::test_el_js_sigue_a_python` (escenario de la spec: fila resuelta con `densidad.text = [200, "medida"]`, cambiada a mano a `[250, "medida"]`) | (b) | Mutante: el JS divide la prosa por 200 fijo (regla propia) → falla `assert js["saved"] == chars * 100 // 250` (muta porque 200 ≠ 250) |
  | `test_densidad.py::test_sin_densidad_las_dos_dan_cero` (fila sin fundir, en Python y en JS) | (b) | Mutante: Python resuelve la densidad si falta → falla `assert server.tokens_claude(4000, tipo="text", evento=fila) == 0` |
  | `test_densidad.py::test_el_mismo_py_con_haiku_da_menos_tokens` (escenario de la spec) | (b) | Mutante: saltarse el respaldo (2) → falla `assert d_haiku["text"] == [312, "sin_numerar"]` (da `[312, "conservadora"]`: el valor coincide porque `codigo` es la mayor `c` de la familia, así que el control es el **origen**). Y `assert d_opus["text"] == [203, "medida"]` |
  | `test_densidad.py::test_la_tool_manda_sobre_la_extension` (`local_lint_summary` con un `.py`) | (b) | Mutante: extensión primero → falla `assert clase == "log"` (da `codigo`) |
  | `test_densidad.py::test_respaldo_por_variable` (`claude-haiku-4-5`; `claude-opus-5:main`; `xyz`) | (b) | Mutante: ignorar la variable → falla `assert r["familia"] == "anterior"` con Haiku. Con `xyz`: `assert r.get("respaldo_invalido") is True` y el declarado (`claude-opus-5-5`, `subagent`) |
  | `test_densidad.py::test_una_imagen_no_resta_del_neto` (escenario de la spec, evento del hermano) | (c) tras el paso 1 | `assert a["saved"] == 0` (en el corte, 1200 = `tokens_in` reportado, la regla de hoy); después `returned == net == 0`, `bytes_saved_image == 250000`, `chars_returned == 800` |
  | `test_densidad.py::test_la_fusion_respeta_el_orden` (línea con `caller_model` y relleno con otro; línea sin él y relleno; ninguna) | (b) | Mutante: el relleno pisa a la línea → falla `assert fila["caller_model"] == DE_LA_LINEA` |
  | `test_densidad.py::test_la_fusion_no_toca_la_cache` (dos `_load` seguidos con el mismo fichero) | (b) | Mutante: fundir sobre los dicts de `_read_file_cached` → falla `assert "densidad" not in metrics._read_file_cached(ruta)[0]` |
  | `test_densidad.py::test_tramos` (excluido por cliente `codex-mcp-client`, por `mcp` y por `banco`; al momento; por relleno; con `plazo_dias=30`, pendiente con 29 días y supuesto con 31; con `plazo_dias=90`, pendiente con 60; supuesto con `ambiguo`) | (b) | Mutante: `ambiguo` cuenta como pendiente → falla `assert tramo(f, ahora=t, plazo_dias=30) == "supuesto"`. Mutante: 30 fijos → falla `assert tramo(f60, ahora=t, plazo_dias=90) == "pendiente"` |
  | `test_densidad.py::test_ningun_chars_per_token_en_la_conversion` (`inspect.getsource` de `tokens_claude`, `_savings_feedback`, `_escribir_destino` y del bloque de `tokens_aprox`) | (a) | `assert "CHARS_PER_TOKEN" not in fuente` (hoy está en `tokens_claude`) |
  | `test_vision.py` (reescrito, línea 146) y uno nuevo: la coletilla de imagen no tiene tokens | (a) | `assert "tokens" not in coletilla` (hoy «≈ 300 tokens») |
  | `test_densidad.py::test_la_coletilla_usa_tokens_de_claude` (`local_summarize` con `path` a un `.md` de 4000 caracteres, `backend_mock` con `prompt_tokens: 9999`) | (a) | `assert "≈ 2,000 tokens de Claude" in texto` (hoy usa el `tokens_in` local: 9,999) |
  | `test_metrics.py::test_local_status_funde_como_el_panel` (log con una línea de Haiku por relleno) | (b) | Mutante: `local_status` lee sin `fundir` → falla `assert neto_status == j["tokens_context_net"]` (muta: sin fusión la línea no trae `densidad` y da 0) |
  | `test_metrics.py::test_las_filas_de_api_events_vienen_resueltas` | (a) | `assert all("densidad" in e for e in eventos)` (hoy ninguna) |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_densidad.py tests/test_metrics.py tests/test_dashboard_js.py tests/test_core.py tests/test_vision.py tests/test_boilerplate_salida.py tests/test_resumen_estructurado.py tests/test_aislamiento_entorno.py -q`
  y `node --check` del JS. Después, la integración de la ola (suite completa) y el commit.
- **Rollback:** revertir; la fusión solo añade claves a las filas leídas, nunca escribe el log.

### T5 — Comando `recalcular-coste`: relleno, `N`, cotejo real y puntos de cuota (ola 4)

- **Ficheros:** `transcripts.py`, `cuota.py`, `recalcular.py`, zona T5 de `cli.py`;
  `tests/test_transcripts.py`, `tests/test_cuota.py`, `tests/test_recalcular.py`.
- **Requisitos:** REQ-004 (con `H`), REQ-005 (lo escribe con `atribucion.escribir_relleno`),
  REQ-014, REQ-043, REQ-051 a REQ-057, REQ-061 (en el comando), REQ-070 a REQ-074.
- **Qué se hace:**
  1. `transcripts.py`, port de `insumos/scripts/atribucion_n.py`: índice de `tool_use`/`tool_result`
     por hilo; `casar(lineas_log, indice) -> {clave: entrada}` con las reglas de REQ-004 (exacto;
     ventana [`tool_use` − 1 s, `tool_result` + 2 s] o `tool_use` + 15 min; desempate **solo** por
     `path` normalizado en memoria), sobre las líneas de los últimos `H` días
     (`atribucion.plazo_de_borrado`); `n_y_caducidades(hilo, t0)` (REQ-043); percentiles con
     interpolación lineal; `banco` si la carpeta del proyecto contiene `Temp`; `cost_state(...)` con
     la última por posición por `(sessionId, startTime)`. Una línea JSON rota se salta y cuenta
     (REQ-061).
  2. `cuota.py`, port de `calibracion.py` y `criterio.py`: `puntos_de_rechazo` (uno por
     `(rateLimitType, resetsAt)`, marcas «cota baja» y «solo comprobación»); `puntos_del_statusline`
     (los siete pasos de REQ-052); `quitar_solapados`; `vigentes(puntos, ahora)` (60 días,
     reinicios); `sanear` (% fuera de [0, 100] o no numérico → descarte `fuera_de_rango`; línea
     ilegible → descarte `linea_corrupta`); `criterio(capacidades)` y `deriva` (REQ-055/056);
     `estado(agregados, ahora) -> dict` por tipo, que es lo que pinta el panel (T6).
  3. `recalcular.py`: `ejecutar(claude_dir, log_dir, *, ahora, reiniciar=None) -> resumen`; los
     agregados de `N` excluyen lo que dice `atribucion.excluida`; `leer_agregados(log_dir)` y
     `escribir_agregados(...)` con `plazo_dias` y la fusión de REQ-071 (puntos por
     `(fuente, tipo, inicio, fin)`; meses de más de 30 días sin recalcular); escritura atómica
     (fichero temporal y `os.replace`) **solo** en `log_dir`. `cli.py`: `recalcular-coste` con
     `--reiniciar-calibracion` y `--claude-dir`; imprime el resumen (conteos, sin rutas).
- **Tests:**

  | Test | Control | Debe fallar con el mutante en |
  |---|---|---|
  | `test_transcripts.py::test_n_y_caducidades_conocidos` (transcript sintético con una línea `<synthetic>`, un `message.id` repetido, un `compact_boundary` y huecos de 301 s y de 299 s en un subagente; `N` y caducidades escritos a mano en el test) | (b) ×3 | Mutante 1: contar `<synthetic>` → falla `assert n == N_CONOCIDO`. Mutante 2: contar por línea y no por `message.id` → ídem. Mutante 3: no cortar en `compact_boundary` → ídem (los tres mutan por construcción del transcript) |
  | `test_transcripts.py::test_el_ttl_depende_del_hilo` (hueco de 3 599 s en el principal) | (b) | Mutante: TTL de 300 s en los dos hilos → falla `assert caducidades == 0` |
  | `test_transcripts.py::test_percentil_par` | (b) | Mutante: mediana = elemento central inferior → falla `assert mediana([1, 2, 3, 4]) == 2.5` |
  | `test_transcripts.py::test_cruce_exacto_ventana_y_path` (escenario de los dos subagentes con `path` distintos) | (b) | Mutante: desempatar también por cercanía del `ts` → con los dos `path` iguales falla `assert cruces == ["ambiguo", "ambiguo"]` |
  | `test_transcripts.py::test_el_relleno_usa_el_plazo_leido` (`settings.json` con `cleanupPeriodDays: 90`, línea de 45 días con su transcript) | (b) | Mutante: ventana de 30 días fija → falla `assert entradas[clave]["cruce"] == "exacto"` (la línea queda sin entrada) |
  | `test_transcripts.py::test_sin_cruce_y_banco` | guarda | `assert e["cruce"] == "sin_cruce"`; `assert e_banco["banco"] is True` |
  | `test_transcripts.py::test_cost_state_toma_la_ultima_por_posicion` | (b) | Mutante: la primera → falla `assert fila["costUSD"] == ULTIMO` |
  | `test_cuota.py::test_cinco_filas_son_un_punto` (escenario de la spec) | (b) | Mutante: un punto por par consecutivo → falla `assert len(puntos) == 1`; después `delta_pct == 40` |
  | `test_cuota.py::test_sesiones_en_paralelo` (dos sesiones en la misma ventana; se elige la de mayor Δ%; Δ$ suma las dos) | (b) | Mutante: Δ$ solo de la sesión elegida → falla `assert p["delta_usd"] == SUMA` |
  | `test_cuota.py::test_descartes` (`delta_pequeno`, `sin_uso_local`, `contaminado` con un transcript de una sesión ausente del registro, `reinicio` con `cost_usd` que baja, `solapado`) | (b) uno por motivo | Mutante: no mirar las sesiones ajenas → falla `assert descartes["five_hour"].get("contaminado") == 1` (y uno por motivo, cada uno con su assert) |
  | `test_cuota.py::test_sanear_y_lineas_corruptas` (REQ-054 y REQ-061: fila con 120 %, fila con `"abc"`, línea JSON rota en el registro y en un transcript) | (b) uno por rama | Mutante «sin saneado» → falla `assert descartes["five_hour"].get("fuera_de_rango") == 1`. Mutante «sin `try` en la línea del registro» → el test captura en `escapo` y falla `assert not escapo`; después `assert descartes["five_hour"].get("linea_corrupta") == 1`. Ídem con el transcript roto |
  | `test_cuota.py::test_rechazos_duplicados_son_un_punto` (11 registros, mismo `resetsAt`, en principal y subagentes) | (b) | Mutante: uno por registro → falla `assert len(rechazos) == 1`; y el tipo sigue `sin calibrar`; `delta_usd` es la suma de las peticiones del intervalo |
  | `test_cuota.py::test_criterio_de_la_spec` (los seis escenarios con las cifras de `criterio.py`: 7,8 %, 7,2 %, 51,2 %, deriva, sentidos opuestos, recuperación con mediana 235) | (b) | Mutante: deriva sin «mismo sentido» → falla `assert r["estado"] == "calibrado"` con `{150, 160, 170, 175, 230, 100}` |
  | `test_cuota.py::test_un_punto_de_61_dias_no_cuenta` | (b) | Mutante: sin vigencia → falla `assert r["estado"] == "sin calibrar"` |
  | `test_cuota.py::test_reinicio_a_mano` | (b) | Mutante: ignorar el reinicio → falla `assert vigentes == []` |
  | `test_recalcular.py::test_la_privacidad` (escenario de la spec: marcadora en un prompt, un `tool_result` y una ruta; `session_id` marcador) | (b) | Mutante: guardar el `path` en la entrada del relleno → falla `assert MARCADORA not in texto_de_todos_los_json`. Y `assert TOOL_USE_ID not in texto_de_coste_agregados` |
  | `test_recalcular.py::test_idempotente_y_solo_lectura` (lista de ficheros del `~/.claude` sintético con tamaño, `mtime` y `sha256` antes y después; dos ejecuciones) | (b) | Mutante: el comando deja una caché en `claude_dir` → falla `assert despues == antes`. Y los JSON salen iguales salvo `generado` |
  | `test_recalcular.py::test_los_agregados_de_n_no_cuentan_excluidas` (un cliente `mcp` y un `banco` con `N` enormes) | (b) | Mutante: sin `atribucion.excluida` → falla `assert agregados["n_por_mes"][MES]["claude-opus-5-5|subagent"] == [40]` |
  | `test_recalcular.py::test_un_punto_sobrevive_al_transcript_borrado` (JSON previo con un punto; transcript borrado; segunda ejecución) | (b) | Mutante: sobrescribir en vez de fundir → falla `assert punto in agregados["puntos"]` |
  | `test_recalcular.py::test_un_mes_viejo_no_se_recalcula` | (b) | Mutante: recalcular todos los meses → falla `assert agregados["n_por_mes"]["202608"] == PREVIO` |
  | `test_recalcular.py::test_guarda_el_plazo` (`cleanupPeriodDays: 90`) | (b) | Mutante: no guardarlo → falla `assert agregados.get("plazo_dias") == 90` |
  | `test_recalcular.py::test_el_cli_lo_lanza` (`cli.run(["recalcular-coste", "--claude-dir", ...])`, `config.LOG_DIR` a `tmp_path`; el test captura `SystemExit` y lo convierte en código) | (a) | `assert codigo == 0` (**comprobado**: hoy `cli.run` sale con `SystemExit(2)`, subcomando desconocido) |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_transcripts.py tests/test_cuota.py tests/test_recalcular.py tests/test_atribucion.py tests/test_precios.py tests/test_aislamiento_entorno.py -q`.
  Después, la integración de la ola (suite completa) y el commit.
- **Rollback:** borrar los módulos nuevos y el subcomando; los JSON que haya escrito se borran a
  mano del directorio de logs (nadie más los escribe).

### T6 — Coste y cuota en `/api/stats` y en el panel (ola 5, en paralelo con T7)

- **Ficheros:** `valoracion.py`; zona T6 de `web/metrics.py` y de `tests/test_metrics.py`;
  `tests/test_valoracion.py`, `tests/test_panel_coste.py`, `tests/test_dashboard_ui.py` (zona T6).
  Evidencia en `evidencias/T6.md`.
- **Requisitos:** REQ-007 (barra), REQ-008 (rótulo), REQ-009, REQ-012 (`/api/stats`), REQ-016,
  REQ-038 (bloque), REQ-040 a REQ-048, REQ-050, REQ-054 (al leer), REQ-055, REQ-058 a REQ-061,
  REQ-073.
- **Qué se hace:**
  1. `valoracion.py`: `precio(m, hilo)`; `n_de(fila, agregados)` en el orden único de REQ-042;
     `coste_evento(fila)` (REQ-041); `bloque_coste(filas, agregados)` con la base de REQ-040,
     `sin_precio` (REQ-016), barra (REQ-007, con `plazo_dias` del JSON o 30), respaldo (REQ-008),
     orígenes de `N`, densidad y marcas (REQ-044), desglose por (modelo, hilo, esfuerzo) (REQ-047) y
     `motivo` cuando no hay cifra (REQ-046); `bloque_imagenes(filas)` (REQ-038).
  2. `/api/stats` añade `coste`, `imagenes`, `densidad_tabla` y `cuota`. La cuota usa **sus propias
     ventanas** (últimas 5 h y últimos 7 días que terminan ahora, con un `_load` aparte),
     independientes del rango del panel (REQ-060), y `cuota.estado` (T5) para la vigencia al leer
     (REQ-054). Sin `coste-agregados.json`: respaldo, `N` declarado y «no hay datos de calibración en
     esta máquina» con el comando que los genera (REQ-061, REQ-073).
  3. JS: funciones puras `textoCoste(j)`, `textoCuota(j)` y `textoImagenes(j)` (probadas con node,
     como las del panel) y su pintado. Rótulo y nota de REQ-045; supuestos de REQ-044; ningún %
     de cuota en `sin calibrar`. Se reescriben el `<meta name="description">` y la frase «es cuota
     que no gastaste».
- **Tests:**

  | Test | Control | Debe fallar con el mutante / hoy en |
  |---|---|---|
  | `test_valoracion.py::test_un_millon_de_caracteres` (escenario de la spec: prosa por `path`, Opus 5.5, subagente, `N` = 40, 0 caducidades) | (b) | Mutante: escritura a 1 h en el subagente → falla `assert c["cota_baja"] == 2.50` (da 4,00; muta porque 5 ≠ 8 USD/MTok). Después `estimacion == 6.50` y `T == 500000` |
  | `test_valoracion.py::test_cada_caducidad_es_una_reescritura` (`cad` = 2) | (b) | Mutante: sin el `(1 + cad)` → falla `assert c["estimacion"] == ESPERADA` |
  | `test_valoracion.py::test_un_T_negativo_resta` | guarda | `assert c["cota_baja"] < 0` |
  | `test_valoracion.py::test_origen_de_N` (relleno; grupo con 10 casos; grupo con 9 → declarado del hilo) | (b) | Mutante: umbral 1 → falla `assert origen == "declarado"` con 9 casos. Los agregados se escriben con `recalcular.escribir_agregados` (T5): es también el cruce de formato entre el escritor y el lector |
  | `test_valoracion.py::test_un_modelo_sin_precio_no_da_cero` (escenario de la spec) | (b) | Mutante: precio que falta = 0 → con los dos sin precio falla `assert b["cifra"] is None`. Con uno: `assert b["sin_precio"]["n"] == 1` |
  | `test_valoracion.py::test_sin_tabla_y_sin_delegaciones` | (b) | Mutante: devolver `{cota_baja: 0, estimacion: 0}` sin delegaciones → falla `assert b["motivo"] == "sin delegaciones en el periodo"` |
  | `test_valoracion.py::test_desglose_por_esfuerzo` (dos niveles en el log sintético) | (b) | Mutante: agrupar sin esfuerzo → falla `assert len(b["desglose"]) == 2` |
  | `test_valoracion.py::test_imagenes_y_salida_a_fichero_fuera_de_la_base` | (b) | Mutante: la base incluye `chars_saved_output` → falla `assert b["fuera_de_la_base"]["salida_a_fichero"] == 1` y la cifra cambia |
  | `test_panel_coste.py::test_la_carrera_la_cierra_el_relleno` (escenario de la spec: línea con `caller_src: hook`; después `atribucion.escribir_relleno` de T2) | (b) | Mutante: el relleno no se funde → falla `assert barra["por_relleno"] == 1` (da `pendiente` = 1) |
  | `test_panel_coste.py::test_api_stats_trae_coste_cuota_e_imagenes` | (a) | `assert j.get("coste") is not None` (hoy `None`); después `imagenes == {"n": 1, "bytes": 250000, "chars_devueltos": 800}` con el evento de imagen del hermano |
  | `test_panel_coste.py::test_la_cuota_no_depende_del_rango` (tres puntos que calibran; delegaciones de hace 3 h; rango del panel = el mes pasado) | (b) | Mutante: la cuota usa las filas del rango → falla `assert c["five_hour"]["a_pct"] > 0` |
  | `test_panel_coste.py::test_un_punto_viejo_caduca_sin_regenerar` (escenario de la spec) | (b) | Mutante: el panel no aplica la vigencia → falla `assert c["five_hour"]["estado"] == "sin calibrar"`; y `"faltan 1 puntos"` en el texto |
  | `test_panel_coste.py::test_aviso_contra_un_rechazo` (REQ-058) | (b) | Mutante: sin la comparación → falla `assert "probable uso en otras superficies" in texto` |
  | `test_panel_coste.py::test_home_vacio` (escenario «otra máquina sin datos») y un `coste-agregados.json` corrupto, con `TestClient(metrics.app, raise_server_exceptions=False)` | (b) | Mutante: el JSON corrupto se lee sin `try` → falla `assert r.status_code == 200` (da 500; **comprobado** que con `raise_server_exceptions=False` un `JSONDecodeError` del servidor llega como 500 y no como excepción en el test) |
  | `test_panel_coste.py::test_el_panel_no_lee_claude` (espía sobre `open` y `Path.open` durante `/api/stats` y `/api/events`, con `~/.claude` sintético con transcripts y registro) | (b) | Mutante: `/api/stats` lee el registro del statusline → falla `assert lecturas_en_claude == []` |
  | `test_panel_coste.py::test_api_stats_no_abre_sockets` (registradores en `getaddrinfo`, `create_connection` y `connect`) | (b) | Mutante: cargar la tabla desde su `fuente` → falla `assert intentos == []` (**comprobado** sin red, como en T1) |
  | `test_panel_coste.py::test_frases_prohibidas` (sobre `metrics.HTML`, la respuesta de `/api/stats` y los tres mensajes de T4) | (a) | `assert "cuota que no gastaste" not in html` (hoy está) y uno por frase de REQ-045 |
  | node: `textoCuota` con `sin calibrar` y con `calibrado` | (b) | Mutante: pintar el % también sin calibrar → falla `assert "de una ventana de 5 h" not in texto_sin_calibrar` |
  | node: `textoCoste` con la barra y el respaldo | (b) | Mutante: sin la barra → falla `assert "con modelo supuesto: Opus 5.5 en subagente" in texto` |
  | Playwright: el bloque de coste dice «Equivalente estimado a precio de API: entre $» y la nota de tarifa plana; el de cuota, «sin calibrar»; el de imágenes, su número | (a) | `assert "Equivalente estimado a precio de API" in texto` (hoy no existe) |

  Se actualizan a propósito los tests de `tests/test_metrics.py` que comparan el JSON entero de
  `/api/stats` con `==` (ganan claves); el agente los lista con `rg -n "api/stats" tests/` antes
  de tocar nada.
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest tests/test_valoracion.py tests/test_panel_coste.py tests/test_metrics.py tests/test_dashboard_js.py tests/test_dashboard_ui.py tests/test_captura.py -q`
  y `node --check` del JS. Después, la integración I5.
- **Rollback:** revertir la zona; las claves de `/api/stats` son aditivas.

### T7 — Check `config.coste` de `doctor` (ola 5, en paralelo con T6)

- **Ficheros:** `checks.py`, `tests/test_coste_doctor.py`, `_NUMERO[22]` en `tests/test_checks.py`,
  `_NUMERO_DE_CHECKS[22]` en `tests/test_wiki.py`, la tabla del doctor y «las veintidós piezas» en
  `docs/wiki/Integration-install.md` (CRLF). Evidencia en `evidencias/T7.md`.
- **Requisitos:** REQ-015, REQ-075 (con `H`).
- **Qué se hace:** `Context.log_dir: Path | None = None` (`None` = `config.LOG_DIR`; un campo
  simple, no un colaborador con `default_factory`, que es lo que confundió a CodeQL en el PR #204).
  `_probe_coste` lee **solo** `coste-agregados.json` (con `recalcular.leer_agregados`), el log de
  uso, los `atribucion-*.json` (con `atribucion.leer_relleno` y `coste.tramo`) y `H` de
  `settings.json` (con `atribucion.plazo_de_borrado`), en el orden de REQ-015: relleno pendiente con
  más de `H` − 10 días si existe `claude_dir/"projects"` → `warn` («lanza `local-delegate
  recalcular-coste` antes de que Claude Code borre sus transcripts»); cotejo fallido → `warn` con
  los modelos; cotejo bueno → `ok`; sin cotejo → `unknown`; nunca `missing`. Las frases de tamaño de
  `checks.py` pasan a «veintidós» / «ver los otros veintiún». Fila nueva en la tabla del doctor,
  grupo «Entorno».
- **Tests (`tests/test_coste_doctor.py`):**

  | Test | Control | Debe fallar con el mutante / hoy en |
  |---|---|---|
  | `test_comando_nunca_lanzado_y_pendientes_de_21_dias` (escenario de la spec, `H` = 30; con 10 días da `unknown`) | (b) | Mutante: la regla 1 exige que exista `coste-agregados.json` → falla `assert r.status == WARN` |
  | `test_el_aviso_sigue_al_plazo` (`cleanupPeriodDays: 90`: 21 días → `unknown`; 81 días → `warn`) | (b) | Mutante: umbral de 20 días fijo → falla `assert r.status == UNKNOWN` con 21 días |
  | `test_las_dos_cosas_a_la_vez` (pendiente y cotejo fallido) | (b) | Mutante: devolver solo la primera → falla `assert "claude-opus-5" in r.message` |
  | `test_cotejo_bueno_ok_y_sin_cotejo_unknown`; HOME sin `projects` no aplica el aviso | (b) | Mutante: sin cotejo → `missing` → falla `assert r.status == UNKNOWN` |
  | `test_doctor_no_lee_transcripts` (espía sobre `open` con transcripts sintéticos presentes) | (b) | Mutante: el probe recorre `projects/` → falla `assert lecturas_en_projects == []` |
  | `test_checks.py::test_el_docstring_dice_cuantos_checks_hay_de_verdad` y `test_wiki.py::test_la_tabla_del_doctor_lista_todas_las_comprobaciones`, `test_la_wiki_dice_cuantas_comprobaciones_hay_de_verdad` | guardianes existentes | Con el check añadido y sin tocar las frases: fallan por su assert (`el docstring de checks.py quedó desfasado`, `comprobaciones sin fila en la wiki`). Sin añadir antes `22` a `_NUMERO` y a `_NUMERO_DE_CHECKS` fallarían por `KeyError`, así que esas dos entradas se añaden **primero** |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_coste_doctor.py tests/test_checks.py tests/test_doctor.py tests/test_wiki.py -q`;
  `git ls-files --eol docs/wiki/Integration-install.md` sigue en CRLF. Después, la integración I5.
- **Rollback:** quitar la entrada de `CHECKS` y devolver las frases a «veintiún».

### I5 — Integración de la ola 5

Dueño: agente de integración, escritor único de `verification.md`. Las reglas de la integración;
enlaza `evidencias/T6.md` y `evidencias/T7.md`; commits de T6 y T7.

### T8 — Medición con los datos reales de esta PC (ola 6)

Lo corre un agente con la versión del **repo** (`uv run`), sin tocar el daemon. Solo agregados en
`verification.md`. Cada paso tiene su criterio de fallo; un fallo se investiga antes de seguir, sin
ajustar la cifra esperada.

1. **El comando sobre los datos reales**:
   `bash ~/.claude/scripts/pesado.sh uv run local-delegate recalcular-coste`, cronometrado.
   **Falla** si tarda más de 30 s o termina con error. Se anota el `plazo_dias` guardado.
2. **Privacidad de lo escrito**: buscar en `coste-agregados.json` y en los `atribucion-*.json`
   (solo conteos de coincidencias, nunca el texto): rutas de **cualquier** unidad
   (`[A-Za-z]:[\\/]`, que cubre `C:` y `D:`), `/Users/` y `/home/`, el nombre de **cada** carpeta
   de `~/.claude/projects` leído en ese momento (llevan la ruta codificada, como `D--Projects-…`),
   el nombre de usuario del sistema, UUID de sesión y `toolu_` (este último solo en
   `coste-agregados.json`). **Falla** con una sola coincidencia.
3. **Cotejo real** (primer escenario): el resumen da todas las juzgables `dentro`, 0 `fuera` y 0
   `sin_precio`; se anotan filas y fecha. `uv run local-delegate doctor` da `config.coste` en `ok`
   (o `warn` solo por relleno pendiente, que se anota con su motivo). **Falla** si hay una fila
   `fuera` o `sin_precio`: la tabla del paquete está mal o falta un modelo.
4. **Septiembre en tokens** (REQ-036; insumo: `usage-202609.jsonl`, que produjo el uso real): el
   comando del paso 3 del T7 del plan del panel, con `_load` en vez de leer el fichero a mano para
   que funda. Las cuatro cifras en caracteres tienen que salir **idénticas** a las del panel
   (`3463739 1489047 5237 289554`); las de tokens nuevas y la cobertura (los cinco tramos) se
   anotan. Con `H` = 90 y transcripts desde el 2026-09-03 (revisión del plan), lo esperable es casi
   todo septiembre `por relleno`; los días 1 y 2, sin transcript, en `supuesto`. **Falla** si cambia
   una cifra en caracteres.
5. **Cifra de referencia** (REQ-048): primero, comparar los valores de
   `insumos/scripts/precios.json` y `densidad.json` con los del paquete; si difieren (por T1 o por un
   PR del vigilante), copiar el script y las tablas del paquete al scratchpad y correr la copia, sin
   editar los insumos. Después, el mismo día y con la misma ventana (`--desde` = hace 30 días,
   `--hasta` = ahora, los dos en el comando y en `/api/stats?from=…&to=…`):
   `python insumos/scripts/atribucion_n.py --desde … --hasta …` contra el bloque `coste` de
   `/api/stats` servido con `metrics.app` del repo. **Falla** si difieren el número de delegaciones,
   `T`, la cota baja o la estimación en más de **un céntimo**; cualquier diferencia es un defecto de
   uno de los dos.
6. **Cuota real**: el estado de cada tipo, sus descartes por motivo y el Δ$ de cada punto de rechazo,
   comparados con `insumos/scripts/calibracion.py --hasta <la misma hora>`. **Falla** si los conteos
   por motivo difieren o un Δ$ de rechazo se separa en más de un céntimo. Lo esperado con los datos
   del 2026-10-06 es `sin calibrar` en los dos tipos.
7. **Clave del relleno**: `insumos/scripts/clave_relleno.py` sobre los logs reales sigue dando 0
   claves repetidas con `(ts, tool, ordinal)`.
8. **Rendimiento del panel**: `/api/stats` del último mes con la fusión y el coste, medido con
   `TestClient` tres veces; se anota el tiempo. **Falla** si pasa de 2 s.

### T9 — Documentación (ola 7)

- **Ficheros:** `CHANGELOG.md` (`[Unreleased]`, CRLF), `README.md` (CRLF),
  `docs/wiki/Savings-and-metrics.md`, `Configuration.md`, `Troubleshooting.md`, `Repo-hardening.md`,
  `Architecture.md` (si lista los hooks), `Integration-install.md` (zona T9: el hook nuevo),
  `docs/recipes/claude-code-hooks.md` (lista los hooks), `scripts/dev/capture_dashboard.py`.
- **Requisitos:** la restricción de entrega del panel y el non-goal «Publicar versión» de la spec:
  una release toca CHANGELOG, README y `docs/wiki/`, y este cambio deja los tres listos.
- **Qué se hace:**
  - CHANGELOG: **se quita** la nota «No publicar versión hasta mezclar `coste-api-y-cuota`» que
    dejó el panel (este cambio es esa condición). `### Added`: coste equivalente a precio de API
    (cota baja y estimación, con supuestos), bloque de cuota «sin calibrar», bloque de imágenes,
    `local-delegate recalcular-coste`, check `config.coste`, hook `anotar_llamada.py`, vigilante
    semanal. `### Changed`: «Contexto conservado» pasa a tokens de Claude por familia y tipo de
    contenido, **la cifra sube** (septiembre, con las cifras de T8.4); las imágenes salen del neto.
    Sin versión ni fecha. Se edita con Edit sobre el bloque propio.
  - Wiki `Savings-and-metrics.md`: densidad (tabla y respaldos), atribución y barra de cobertura,
    fórmula de coste con sus supuestos y la frase de las relecturas, `N` y su origen, la cuota y su
    criterio, el comando y cuándo lanzarlo (el plazo `H` y el aviso a `H` − 10 días), y lo que
    **no** es la cifra. `Configuration.md`: `LOCAL_DELEGATE_COSTE_RESPALDO` y que el plazo sale de
    `cleanupPeriodDays`. `Troubleshooting.md`: el `warn` de `config.coste`. `Repo-hardening.md`: el
    vigilante, sus permisos, los commits firmados por la API y la salida de REQ-025.
    `docs/recipes/claude-code-hooks.md` e `Integration-install.md`: el hook nuevo y qué hace.
  - README: la línea de «cuota que no gastaste» (línea 30) y la de «ahorro real de cuota» (118) se
    revisan para que no contradigan al panel; la explicación de tokens de Claude.
  - `capture_dashboard.py`: el mock de `/api/stats` y `/api/events` con las claves nuevas (filas con
    `densidad`).
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_wiki.py tests/test_captura.py tests/test_release_metadata.py -q`;
  `git ls-files --eol` de cada fichero igual que antes; la nota del panel ya no está en
  `[Unreleased]`. Después, la integración de la ola (suite completa) y el commit.
- **Rollback:** revertir los Markdown y el mock.

### T10 — Verificación final, con el daemon y el panel en vivo (ola 8)

1. `uv run ruff check .`, `uv run ruff format --check .`,
   `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q`, `node --check` del JS. Conteo en
   `verification.md`.
2. **Instalación real** (la lanza la sesión principal: reinstala el daemon y escribe en
   `~/.claude/settings.json`):
   `bash ~/.claude/scripts/pesado.sh uv tool install --force --reinstall --no-cache ".[llamaswap]"`,
   `local-delegate install --mcp-mode http --web-token-env --enable-read-hook --agents` (los cuatro
   flags de esta PC) y `schtasks /Run` de la tarea del daemon. **Falla** si `doctor` no da
   `scaffold.hook_files` y `scaffold.hook_settings` en `OK` con el hook nuevo entre los registrados.
3. **Atribución de verdad** (un hook no está bien hasta que corre instalado): con `claude -p` desde
   el principio, que es una sesión nueva y recoge el hook sin pedirle nada al usuario, un subagente
   hace tres `local_summarize` con `path`. Se anota que esas llamadas marcan la ventana de 5 h en
   curso como `contaminado` (REQ-052, paso 6). La última línea del log de cada una se lee y se anota
   sin `path`.
   - **Falla** si alguna línea no trae `tool_use_id`: el daemon real no recibe el `_meta` (I2 lo
     vio con el servidor del repo; aquí es el daemon instalado); se para y se lleva a la sesión
     principal.
   - **Falla** si ninguna trae `caller_*`: el daemon no ve las notas del hook. T0.7 dio evidencia
     de que comparten temporal (`bloqueo_id`); si aun así falla, se anota el directorio temporal de
     cada proceso.
   - **Falla** si menos de dos de las tres traen `caller_src: hook+transcript` con el
     `caller_model` del subagente y su `caller_effort`. Una con `hook` sola es la carrera medida, y
     se acepta.
4. **Mensajes**: la coletilla de esas llamadas dice «≈ N tokens de Claude» y la de una
   `local_describe_image` no dice tokens.
5. **`doctor` en una consola**: `config.coste` sale `ok` o `warn` por relleno pendiente, nunca
   `unknown` en esta PC (hay transcripts y el comando corrió en T8).
6. **Panel de `9393` en vivo** (Playwright bajo `pesado.sh`): el bloque de coste dice «entre $X y
   ~$Y» con `0 < X ≤ Y`, la barra suma las delegaciones atribuibles del periodo y nombra el
   respaldo, y el bloque de supuestos está entero (REQ-044); la cuota dice `sin calibrar` en los dos
   tipos, sin «% de una ventana», salvo que T8.6 haya dado `calibrado`; el bloque «Imágenes» enseña
   el número de imágenes. **Falla** si aparece «$0», un % de cuota sin calibrar, o una cifra que no
   coincide con la de `/api/stats` de ese momento.
7. **Devolver el daemon a la versión publicada** (sesión principal), salvo que el usuario diga otra
   cosa: hasta la release, el panel de uso diario no enseña código sin publicar. El hook nuevo queda
   instalado y deja notas que nadie lee (caducan a los 10 min). Después se corre `doctor` y se anota
   qué dice de ese hook (lo esperable: `scaffold.hook_files` o `hook_orphans` lo ven como ajeno a la
   0.32.0).
8. `personal-sdd-review` del resultado contra la spec y `personal-security-check` sobre el diff
   (incluida la validación del `transcript_path`).

### T11 — Ensayo real del vigilante en GitHub (después de mezclar; REQ-025)

Solo se puede hacer con el workflow en `main`: GitHub exige que un workflow con `workflow_dispatch`
esté en la rama por defecto para lanzarlo. Lo hace la sesión principal, **antes de la release**.

- **Prerrequisito:** T0.5 dio que Actions puede crear PRs. Si no, la decisión del usuario sobre ese
  ajuste va antes.
- **Pasos:** `gh workflow run vigilante-precios.yml -f ensayo=true`; esperar al PR «[ensayo]»; leer
  `gh pr checks <n>` (es el único que enseña también code scanning, Socket y GitGuardian) y
  `gh pr view <n> --json mergeStateStatus,reviewDecision,statusCheckRollup`.
- **Éxito:** los seis checks del ruleset (`ci-gate`, `lint`, `test (ubuntu-latest)`,
  `test (macos-latest)`, `secrets`, `Analyze (python)`) en verde sobre el `head_sha` del PR, el
  resultado de code scanning presente y en verde, y `mergeStateStatus` distinto de `BLOCKED`, o
  `BLOCKED` solo por revisiones que pida el ruleset (se distingue con `reviewDecision`). Además,
  el job de límites terminó sin error («sin cambios»).
- **Fallo:** el PR queda `BLOCKED` con los checks en verde (la regla `code_scanning` o
  `require_extra_approval_for_unattributed_changes`). Se comprueba que el vigilante dejó el
  comentario de REQ-025 (esa rama del código también queda probada) y se lleva al usuario la
  decisión que la spec deja abierta: cerrar y reabrir a mano cada PR del vigilante, o un token de una
  GitHub App guardado como secreto. La release no espera a esa decisión: el vigilante no afecta al
  paquete; el gate `conformance` anota REQ-025 como «salida alternativa en uso» hasta que se decida.
- **Limpieza:** cerrar el PR de ensayo sin mezclar y borrar la rama `vigilante/ensayo`.
- **Después:** a la semana, comprobar que la ejecución programada corrió (`gh run list
  --workflow vigilante-precios.yml`) y salió «sin cambios» o con su PR.

## Test strategy

- **Unit:** tablas, normalización y cotejo (T1); hook, notas, resolución, clave, relleno, exclusión
  y plazo (T2); extracción y comparación del vigilante (T3); densidad, clase, respaldo, fusión y
  tramos (T4); `N`, cruce, puntos, saneado, criterio y deriva (T5); coste por evento y bloques (T6);
  el probe (T7). Todo con transcripts, registros y logs **sintéticos** en `tmp_path`.
- **Integración:** el `_meta` a través del SDK real con el arnés de `test_clients.py` (T2); hook
  como proceso ↔ servidor, también con ocho a la vez (T2); `_log_event` con log en `tmp_path` (T2);
  paridad Python/JS con node sobre filas fundidas (T4); `/api/stats` y `/api/events` con
  `TestClient` (T4, T6); el escritor de `recalcular` leído por la valoración (T6) y por `doctor`
  (T7), y el de `atribucion` leído por la fusión (T4, T6): son los cruces de formato entre tareas;
  el flujo de GitHub del vigilante con un cliente falso (T3); el CLI con un HOME sintético (T5);
  `doctor` con un HOME sintético (T7). Suite completa al final de cada ola.
- **Con Claude Code de verdad, antes de construir encima:** la prueba de humo del `_meta` (I2).
- **Con datos reales:** el comando, el cotejo, septiembre, la cifra de referencia y la cuota (T8).
- **De extremo a extremo:** daemon reinstalado con el hook instalado, una sesión real con
  subagente, `doctor` y el panel de `9393` (T10); el vigilante en GitHub (T11).
- **Navegador:** Playwright para los bloques nuevos (T6) y el panel en vivo (T10).
- **Guardianes del repo que este plan toca a propósito:** paridad Python/JS (T4);
  `test_captura.py` (sin endpoints nuevos; T6 y T9 lo corren); `test_aislamiento_entorno.py` (la
  variable nueva por `_env`, el hook sin variables propias; T2, T4, T5); tabla y tamaño del doctor
  (T7); `test_wiki.py`, incluido el del shebang (T2, T3, T7, T9); `test_ci_gate.py` (T3); LF/CRLF
  por fichero (todas).
- **Seguridad y privacidad:** test de la marcadora (T5); búsqueda de rutas de cualquier unidad,
  carpetas de proyecto, usuario, UUID y `toolu_` en los JSON reales (T8.2); el panel y `doctor` no
  leen `~/.claude/projects` (T6, T7); la ruta del transcript se valida antes de abrirla (T2); los
  tests del hook no escriben en el temporal real (T2); ningún paso lee ni pide
  `LOCAL_DELEGATE_API_KEY`; el vigilante usa solo `GITHUB_TOKEN` con permisos de su workflow;
  `personal-security-check` sobre el diff (T10). Si code scanning abre una alerta sobre el código
  nuevo, **se arregla**, no se descarta, y se resuelven sus hilos en el PR.

## Migration and compatibility

- **Log de uso:** solo se añaden `tool_use_id` y `caller_*`. El histórico se funde al leerlo con los
  `atribucion-AAAAMM.json`; sin ellos, respaldo declarado y barra a la vista.
- **Cifras:** «Contexto conservado» en tokens de Claude **sube** (la densidad real es ~2 chars por
  token, no 4) y las imágenes salen del neto; el CHANGELOG lo dice con septiembre como ejemplo.
- **API:** claves nuevas en `/api/stats` (`coste`, `imagenes`, `cuota`, `densidad_tabla`) y en las
  filas de `/api/events` (`densidad`, `familia`, marcas y los `caller_*` fundidos); ninguna cambia de
  nombre. `chars_per_token` de `/api/stats` conserva su significado (modelo local).
- **Hooks:** uno nuevo. Las máquinas que actualicen sin reinstalar verán `scaffold.hook_files` en
  `warn` hasta `install` (o `update`, que repone los hooks desde la 0.31.2).
- **Plazo de borrado:** cada máquina usa su `cleanupPeriodDays`. Esta PC tiene 90 desde el
  2026-10-06; la Mac, si no lo cambia, 30.
- **Otras máquinas** (la Mac, un CI): sin transcripts ni registro, el coste sale con el respaldo y el
  `N` declarado, la barra en `supuesto`/`pendiente`, la cuota «no hay datos de calibración» y
  `config.coste` en `unknown`.
- **Interfaces internas:** `_savings_feedback` cambia de firma (sus cuatro llamadas están en
  `server.py`, zona T4); `Context` gana `log_dir` con valor por defecto.
- **Siguiente cambio:** `daemon-reparte-el-backend` rebasa sobre este (tabla de «Orden entre
  cambios»).
- **Release:** este cambio levanta la restricción de entrega del panel. La release (fuera de este
  plan) toca CHANGELOG, README y `docs/wiki/`, que T9 deja listos, y va después de T11.

## Riesgos principales

- **Plazo de los transcripts.** En esta PC `cleanupPeriodDays` es 90 desde el 2026-10-06 y el
  transcript más antiguo es del 2026-09-03: lo de antes de esa fecha ya no se puede rellenar, y lo de
  después se pierde si el cambio no se mezcla y el comando no se lanza antes de primeros de
  diciembre. La Mac sigue con 30 si nadie lo cambia. T0.6 lo comprueba y `doctor` avisa a `H` − 10
  días.
- **El `_meta` con el cliente real** está verificado en el código del SDK pero no ejecutado. T2.0 lo
  mide con el SDK, I2 con Claude Code y el servidor del repo **antes** de las olas 3 a 8, y T10.3 con
  el daemon instalado.
- **Las notas del hook y el daemon en procesos distintos**: casi retirado (31 líneas con
  `bloqueo_id` prueban que comparten temporal); T0.7 lo recuenta y T10.3 lo confirma.
- **Tests existentes con cifras de ÷ 4**: muchos, en varios ficheros. T4 los inventaría ejecutando
  dos veces (tras Python y tras JS), con lista de partida, y cada uno tiene dueño y una regla para
  reescribirlo sin aflojarlo.
- **GitHub:** que Actions no pueda abrir PRs (T0.5) o que el CodeQL lanzado por `workflow_dispatch`
  no cumpla `code_scanning` (T11). Los dos acaban en una decisión del usuario, ya prevista en la
  spec, y ninguno bloquea la release.
- **Choque con `daemon-reparte-el-backend`** en `server.py`, `checks.py`, `cli.py`, `config.py` y el
  JS: resuelto por el orden fijado; aquel rebasa y recalcula sus cifras de tamaño.
- **La cifra sube mucho** (estimación $92,69 frente a $25,84 en la misma ventana, sobre todo por
  Opus 5 en el hilo principal): no es un defecto; la verificación la compara contra el script de
  referencia y la documentación lo explica.

## Plan review

- [x] Cada requisito tiene tarea y verificación (tabla de trazabilidad), incluidas las dos mitades
  de REQ-054 y la línea corrupta de REQ-061 en el comando.
- [x] Nada destructivo sin dueño: reinstalar el daemon, `install` y devolver la versión publicada
  (T10.2, T10.7) los lanza la sesión principal; el comando sobre los transcripts reales es de solo
  lectura en `~/.claude` y lo prueba un test de hash antes de correrlo de verdad (T5 antes de T8).
- [x] Sin dependencias nuevas; una variable de entorno nueva por `_env`; un hook nuevo con su ruta de
  retirada; un check nuevo con sus guardianes de tamaño; la enmienda 1 de la spec, anotada.
- [x] Sin trabajo ajeno a la spec: E12, la cuota por modelo, la densidad del modelo local y la
  release quedan fuera.
- [x] Sin worktrees; las parejas en paralelo no comparten ficheros, no se importan ni se prueban;
  T4 y T5 en serie; cada ola tiene un único escritor de `verification.md` y una integración con
  dueño, que solo arregla lo mecánico.
- [x] Los tests que este cambio rompe tienen dueño: los de ÷ 4 y los mensajes (T4, dos inventarios
  ejecutados), los del JSON entero de `/api/stats` (T6), los de la lista de hooks (T2), los de tamaño
  del doctor (T7).
- [x] Cada control nombra la tarea que produce su insumo: tablas (T1), notas, relleno, exclusión y
  plazo (T2), páginas guardadas (T3), filas fundidas (T4), agregados y puntos (T5, leídos por T6 y
  T7 con el lector de T5), datos reales (T8), daemon instalado (T10), GitHub (T11).
- [x] Cada mutante dice por qué muta. Ejecutados: `cli.run` hoy, `TestClient` sin propagar,
  la `RuntimeError` en `_log_event`, los sockets sin red y las notas con nombre fijo. Pendientes de
  comprobar al ejecutar, y así lo exige su tarea: las notas al pie de la página guardada (T3), la
  elección de filas literales del cotejo (T1) y las cifras del corte (c) de la paridad (T4).

## Traceability

| Requisito | Tarea | Verificación |
|---|---|---|
| REQ-001 | T2, I2 | `test_la_tool_ve_el_tool_use_id` (SDK real); prueba de humo con Claude Code (I2); T10.3 (daemon instalado) |
| REQ-002 | T2 | `test_ida_y_vuelta_hook_servidor`, `test_el_hook_calla_y_sale_con_0`, `test_dos_llamadas_no_se_pisan`, `test_ocho_hooks_a_la_vez`, `test_el_hook_de_atribucion_se_registra`; T10.2 |
| REQ-003 | T2 | `test_resuelve_el_modelo_del_subagente`, `test_en_el_principal_no_hay_agent_type`, ruta fuera de `projects`, nota a medias, carrera, nota vieja, esfuerzo `n/a`, 256 KB, 50 ms, `test_log_event_escribe_la_atribucion_y_ningun_id_de_sesion`; T10.3 |
| REQ-004 | T5 | `test_cruce_exacto_ventana_y_path`, `test_el_relleno_usa_el_plazo_leido`, `test_sin_cruce_y_banco` |
| REQ-005 | T2, T5 | `test_dos_lineas_del_mismo_segundo_no_comparten_clave`, `test_el_relleno_solo_mejora`; T8.7 |
| REQ-006 | T4 | `test_la_fusion_respeta_el_orden`, `test_la_fusion_no_toca_la_cache`, `test_las_filas_de_api_events_vienen_resueltas` |
| REQ-007 | T2, T4, T6 | `test_excluida`; `test_tramos`; `test_la_carrera_la_cierra_el_relleno`; node `textoCoste`; T10.6 |
| REQ-008 | T4, T6 | `test_respaldo_por_variable`; node `textoCoste` (rótulo del respaldo) |
| REQ-009 | T2, T6 | `caller_effort` en la línea; `test_desglose_por_esfuerzo` |
| REQ-010 | T1 | `test_la_tabla_cubre_los_13_ids`; `admite_esfuerzo` comprobado (T1.1) |
| REQ-011 | T1 | `test_normaliza_fecha_y_1m`, `test_busqueda_exacta_en_los_pares`, `test_un_id_sin_entrada_no_tiene_precio` |
| REQ-012 | T1, T6 | `test_cargar_las_tablas_no_abre_sockets`, `test_api_stats_no_abre_sockets` |
| REQ-013 | T1 | `test_cotejo_con_filas_literales` (tres tablas mutadas y guarda), `test_el_cotejo_cuenta_la_busqueda_web` |
| REQ-014 | T5, T8 | `test_cost_state_toma_la_ultima_por_posicion`; T8.3 (cotejo real) |
| REQ-015 | T7 | `test_coste_doctor.py` entero; guardianes de la tabla y el tamaño; T8.3, T10.5 |
| REQ-016 | T6 | `test_un_modelo_sin_precio_no_da_cero` |
| REQ-020 | T3 | `test_el_workflow_tiene_lo_justo`, `test_el_script_es_solo_stdlib` |
| REQ-021 | T3 | `test_la_pagina_intacta_da_la_tabla_congelada`, `test_un_precio_cambiado_da_ese_diff`, `test_un_modelo_nuevo_sale_listado_en_el_pr`, `test_un_modelo_que_desaparece_no_se_borra`, `test_el_pr_se_hace_por_la_api_y_lanza_los_dos_checks`, `test_si_ya_hay_pr_lo_actualiza` |
| REQ-022 | T3 | sin cabecera, menos de 5 filas, celda ilegible |
| REQ-023 | T3 | tests de límites (intacta, párrafo cambiado, vaciada), `test_el_pr_de_limites_dice_como_reiniciar` |
| REQ-024 | T3 | tabla y texto esperados congelados en el test, no los del repo |
| REQ-025 | T3, T11 | `test_ci_y_codeql_aceptan_workflow_dispatch`, `test_si_main_avanzo_actualiza_la_rama_y_relanza`, `test_si_queda_blocked_lo_dice_en_el_pr`; ensayo real T11 |
| REQ-030 | T1 | tabla de densidad con `medido_con`; T4 la usa |
| REQ-031 | T4 | paridad ampliada, `test_el_mismo_py_con_haiku_da_menos_tokens` |
| REQ-032 | T4 | `test_la_tool_manda_sobre_la_extension`; caso `.bin` → `conservadora` |
| REQ-033 | T4 | `test_el_js_sigue_a_python`, `test_sin_densidad_las_dos_dan_cero`, paridad sobre filas fundidas |
| REQ-034 | T4 | `test_ningun_chars_per_token_en_la_conversion` |
| REQ-035 | T4 | `test_la_coletilla_usa_tokens_de_claude`, `test_vision.py` (sin tokens); T10.4 |
| REQ-036 | T8 | T8.4 (caracteres idénticos a los del panel, tokens y cobertura anotados) |
| REQ-037 | T4 | paridad con los 22 casos existentes y los seis nuevos, fundidos; guarda de orígenes, familias e imagen |
| REQ-038 | T4, T6 | `test_una_imagen_no_resta_del_neto`; `test_api_stats_trae_coste_cuota_e_imagenes`; Playwright |
| REQ-040 | T6 | `test_imagenes_y_salida_a_fichero_fuera_de_la_base` |
| REQ-041 | T6 | `test_un_millon_de_caracteres`, `test_cada_caducidad_es_una_reescritura`, `test_un_T_negativo_resta` |
| REQ-042 | T5, T6 | `test_los_agregados_de_n_no_cuentan_excluidas`; `test_origen_de_N` |
| REQ-043 | T5 | `test_n_y_caducidades_conocidos`, `test_el_ttl_depende_del_hilo`, `test_percentil_par` |
| REQ-044 | T6 | node `textoCoste`; Playwright; T10.6 |
| REQ-045 | T6 | `test_frases_prohibidas` |
| REQ-046 | T6 | `test_sin_tabla_y_sin_delegaciones`, `test_un_modelo_sin_precio_no_da_cero` |
| REQ-047 | T6 | `test_desglose_por_esfuerzo` |
| REQ-048 | T8 | T8.5 (igual al céntimo que `atribucion_n.py` el mismo día y la misma ventana) |
| REQ-050 | T5, T6 | `cuota.estado` por tipo; node `textoCuota` |
| REQ-051 | T5, T8 | `test_rechazos_duplicados_son_un_punto`; T8.6 (Δ$ contra `calibracion.py`) |
| REQ-052 | T5 | `test_cinco_filas_son_un_punto`, `test_sesiones_en_paralelo`, `test_descartes` |
| REQ-053 | T5 | `test_descartes` (`solapado`) |
| REQ-054 | T5, T6 | `test_un_punto_de_61_dias_no_cuenta`, `test_sanear_y_lineas_corruptas` (saneado), `test_un_punto_viejo_caduca_sin_regenerar` |
| REQ-055 | T5 | `test_criterio_de_la_spec` |
| REQ-056 | T5 | `test_criterio_de_la_spec` (deriva, sentidos opuestos, recuperación) |
| REQ-057 | T5 | `test_reinicio_a_mano` |
| REQ-058 | T6 | `test_aviso_contra_un_rechazo` |
| REQ-059 | T6 | node `textoCuota` sin calibrar; T8.6, T10.6 |
| REQ-060 | T6 | `test_la_cuota_no_depende_del_rango`; node `textoCuota` calibrado |
| REQ-061 | T5, T6 | `test_sanear_y_lineas_corruptas` (registro y transcript); `test_home_vacio` (y JSON corrupto) |
| REQ-070 | T5 | `test_el_cli_lo_lanza`; T8.1 |
| REQ-071 | T5 | `test_un_punto_sobrevive_al_transcript_borrado`, `test_un_mes_viejo_no_se_recalcula` |
| REQ-072 | T5, T8 | `test_la_privacidad`; T8.2 |
| REQ-073 | T6, T7 | `test_el_panel_no_lee_claude`, `test_doctor_no_lee_transcripts` |
| REQ-074 | T5 | `test_idempotente_y_solo_lectura` |
| REQ-075 | T7 | `test_comando_nunca_lanzado_y_pendientes_de_21_dias`, `test_el_aviso_sigue_al_plazo` |
