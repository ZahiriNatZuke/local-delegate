# Verification: Panel: coste equivalente a precio de API y % de cuota sin calibrar

## Environment

- Revisión: rama `feat/coste-api-y-cuota` en `4d56a9f` (igual que `main`: #231 mezclado).
- Herramientas: Python 3.11.15 (`uv run`), uv 0.10.12, gh 2.101.0. Windows 11.
- MCP `local-delegate` desconectado en la sesión de T0: 0 llamadas `local_*`.

## T0 — Arranque y comprobaciones previas (ola 0)

Fecha: 2026-10-06. Escritor: agente de T0.

### 1. Precondición de orden

| Comprobación | Resultado |
|---|---|
| PR #231 (`feat/panel-honesto`) | `MERGED` el 2026-10-06T17:50:09Z, commit `4d56a9f` |
| Gate `conformance` de `panel-cuentas-y-estados-honestos` | `approved` (2026-10-06T17:28:25Z); su `state.json` en `closing`, falta el gate `memory` |
| `daemon-reparte-el-backend` | sin mezclar: `state.json` en `plan-review`, gates `quality`/`conformance` pendientes, sin rama ni PR |
| Rama | `feat/coste-api-y-cuota`, `HEAD` = `main` = `4d56a9f` |

Pasa.

### 2. Contrato del panel, leído del código (no de la spec)

| Pieza | Dónde | Coincide con «Campos por evento» y la firma |
|---|---|---|
| `tokens_claude(cantidad: int, *, tipo: str, evento: dict) -> int` | `server.py:621` | sí; tipos `text`, `returned`, `output`, `image`; regla de hoy (÷4, `tokens_out`, `tokens_in` o 0) |
| `_accounting(row)` | `server.py:648` | sí: devuelve `chars_saved_text`, `bytes_saved_image`, `chars_saved_output`, `chars_returned`, `saved`, `returned`, `net`, `failed`, `tool`, `model`, `source`, `unit` y los de coste local (`backend_calls`, `tokens_in`, `tokens_out`, `estimated`, `fallback`, `cause`) |
| Lector del log de `local_status` | `server.py:3347-3368` | lee `_current_log_path()` línea a línea y suma `_accounting(rec)` (`backend_calls`, `saved`, `net`) |
| `metrics._load` | `web/metrics.py:151` | recorre `_log_files()`, `_read_file_cached(path)` y filtra por `ts` dentro del bucle por fichero: el punto de fusión de REQ-006 está donde lo pone el plan |
| `metrics._aggregate` | `web/metrics.py:210` | usa `_accounting = server._accounting`; totales `tokens_context_saved`, `tokens_returned`, `tokens_context_net`, `chars_saved_text`, `bytes_saved_image`, `chars_saved_output`, `chars_returned`; `tokens_net` en `by_tool`, `by_backend` y `by_client` |
| JS `tokensClaude(cantidad,tipo,e)` | `web/metrics.py:1959` | sí, espejo de la regla de hoy |
| JS `acct(e)` | `web/metrics.py:1973` | sí: `charsSavedText`, `bytesSavedImage`, `charsSavedOutput`, `charsReturned`, `saved`, `returned`, `net`, `failed`, `tool`, `model`, `source`, `unit`, `calls`, `tokensIn`, `tokensOut`, `estimated`, `fallback`, `cause` |
| JS `CPT` y `tok` | `web/metrics.py:1318` (`const CPT = 4`) y `:1348` (`const tok = c => Math.floor(c/CPT)`) | sí |

Ningún nombre ni firma difiere. Pasa.

### 3. Tamaños de los registros

`len(checks.CHECKS) == 21` y `len(install._HOOK_EVENTS) == 1`
(`('suggest_delegate_prompt.py', 'UserPromptSubmit', None)`). Pasa.

### 4. Línea base de la suite

`bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q -p no:cacheprovider`:
**1598 passed, 2 skipped, 1 warning in 58.18s**, código de salida 0. El aviso es una
`DeprecationWarning` de `starlette.testclient` (alias `anyio.abc.BlockingPortal`), ajena al
cambio. Es la misma cifra que el gate `quality` del panel. Pasa.

### 5. GitHub, solo lectura

- `actions/permissions/workflow`: `default_workflow_permissions: read`,
  **`can_approve_pull_request_reviews: false`**. Con este valor un workflow **no puede abrir PRs** con
  `GITHUB_TOKEN`: el vigilante (REQ-021, REQ-023) no podrá abrir su PR en GitHub hasta que el usuario
  active «Allow GitHub Actions to create and approve pull requests» (Settings → Actions → General).
  Es una decisión de seguridad del repo: **no se ha cambiado**; queda para el usuario. T3 se
  implementa igual; T11 (ensayo real) depende de ella.
- `rulesets/19859628` (`protect-main`, `active`, rama por defecto): checks `ci-gate`, `lint`,
  `test (ubuntu-latest)`, `test (macos-latest)`, `secrets`, `Analyze (python)`;
  `strict_required_status_checks_policy: true`; regla `code_scanning` de CodeQL con
  `alerts_threshold: errors` y `security_alerts_threshold: high_or_higher`. Además, `pull_request`
  con squash, `required_review_thread_resolution` y `require_extra_approval_for_unattributed_changes`.
  **Coincide con REQ-025.**

### 6. Plazo de borrado en vigor (solo fechas y conteos)

- `H` = `cleanupPeriodDays` de `~/.claude/settings.json` = **90** (fichero modificado el
  2026-10-06 a las 12:00 -03:00).
- Transcripts `*.jsonl` bajo `~/.claude/projects`: 444. El más antiguo, `mtime`
  2026-09-03T19:18Z (32,9 días). **3** tienen más de 30 días (2026-09-03 y dos del 2026-09-05);
  desde el 2026-09-08 hay transcripts todos los días (32 ese día).
- Lectura: que sobrevivan 3 ficheros de más de 30 días es coherente con el plazo de 90 en vigor,
  pero es un **indicio débil** (son pocos y dependen de cuándo corrió la última limpieza). La
  prueba firme llega cuando haya transcripts de más de ~33 días que sigan ahí en los próximos días.
- **El log es rellenable desde el 2026-09-03** (un transcript suelto), y de forma continua desde el
  **2026-09-08**. Lo anterior (julio, agosto y los primeros días de septiembre) ya no tiene
  transcript: irá sin atribución.

### 7. Directorio temporal compartido (evidencia del hook al daemon)

Líneas del log de uso con `"bloqueo_id"` (`grep -c`): **31** (27 en `usage-202609.jsonl`, 4 en
`usage-202610.jsonl`); la última, `2026-10-06T14:27:09Z` con `client: claude-code`. Coincide con
la cifra de la revisión: el daemon lee notas que los hooks dejan en `tempfile.gettempdir()`.

### Desviaciones del plan

- Ninguna en los pasos. El plan no cita `doctor.detect_*` ni `doctor.backend_probe` (desde #231
  viven en `sondas.py`: `detect_llamaswap_version`, `detect_llamaserver_version`, `backend_probe`),
  así que no hay nada que reescribir.
- La rama ya existía al empezar T0 (la creó la sesión principal); no se creó de nuevo.

### Lo que bloquea olas siguientes

- Nada bloquea las olas 1 a 8.
- T11 (después de mezclar) queda bloqueada hasta que el usuario active la creación de PRs desde
  Actions (`can_approve_pull_request_reviews`).

## T1 — Tablas del paquete y cotejo puro (ola 1)

Fecha: 2026-10-06. Escritor: agente de T1. MCP `local-delegate` desconectado: 0 llamadas `local_*`.

Ficheros nuevos (todos LF, 0 bytes `\r`): `src/local_delegate/resources/datos/precios.json`,
`src/local_delegate/resources/datos/densidad.json`, `src/local_delegate/precios.py`,
`tests/test_precios.py`. Ningún fichero existente tocado.

### 1. `admite_esfuerzo` comprobado en la página de cada modelo

Consultado el 2026-10-06. Criterio: la fila «Default effort» de la tabla *Capabilities* de cada
página («Models without a value don't support the parameter») y la lista `supportedModels` de
<https://platform.claude.com/docs/en/build-with-claude/effort>.

| Modelo | Página | «Default effort» | En `supportedModels` | `admite_esfuerzo` |
|---|---|---|---|---|
| `claude-fable-5` | <https://platform.claude.com/docs/en/models/fable-5/overview> | `high` | sí | `true` |
| `claude-opus-5` | <https://platform.claude.com/docs/en/models/opus-5/overview> | `high` | sí | `true` |
| `claude-opus-4-8` | <https://platform.claude.com/docs/en/models/opus-4-8/overview> | `high` | sí | `true` |
| `claude-opus-4-7` | <https://platform.claude.com/docs/en/models/opus-4-7/overview> | `high` | sí | `true` |
| `claude-opus-4-6` | <https://platform.claude.com/docs/en/models/opus-4-6/overview> | `high` | sí | `true` |
| `claude-opus-4-5` | <https://platform.claude.com/docs/en/models/opus-4-5/overview> | `high` | sí (`claude-opus-4-5-20251101`) | `true` |
| `claude-sonnet-5` | <https://platform.claude.com/docs/en/models/sonnet-5/overview> | `high` | sí | `true` |
| `claude-sonnet-4-6` | <https://platform.claude.com/docs/en/models/sonnet-4-6/overview> | `high` | sí | `true` |
| `claude-sonnet-4-5` | <https://platform.claude.com/docs/en/models/sonnet-4-5/overview> | **Not supported** | **no** | **`false`** (el prototipo decía `true`) |
| `claude-haiku-4-5` | <https://platform.claude.com/docs/en/models/overview> | Not supported | no | `false` (ya lo era) |

Los actuales (`claude-fable-5-1`, `claude-opus-5-5`, `claude-sonnet-5-5`) salen en «Models
overview» con `high`/`medium`/`high` y en `supportedModels`: `true`. **Hallazgo:** Sonnet 4.5 no
admite esfuerzo; se corrige en la tabla del paquete y la `_nota` ya no habla de supuesto. La página
de Sonnet 4.5 lo da por **deprecado** (2026-09-30) con retirada el 2026-11-30: sigue entre los 13
ids de REQ-010 porque aún no está retirado. Los precios de las páginas de los modelos heredados
coinciden con la tabla.

### 2. Tablas

- `precios.json`: los 13 ids de REQ-010 en el orden del prototipo (`claude-opus-5-5` antes que
  `claude-opus-5` y `claude-fable-5-1` antes que `claude-fable-5`, lo que hace discriminar el
  mutante de prefijo), `consultado` = `2026-10-06` (fecha del último cambio: la corrección de
  Sonnet 4.5), `fuente`, `busqueda_web_por_1000` = 10.
- `densidad.json`: los valores del prototipo (REQ-030) y `medido_con` dentro de cada familia:
  `nueva` = `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-opus-5`, `claude-fable-5-1`;
  `anterior` = `claude-haiku-4-5`.

### 3. `precios.py`

`cargar_precios()` y `cargar_densidad()` (`importlib.resources`, `functools.cache`),
`normalizar_id`, `entrada(mid, tabla=None)`, `familia(mid, tabla=None)`, `cotejar(filas, tabla)` y
`veredicto(resultados)`, más las constantes `CAMPOS_COTEJO` y `COSTE_MINIMO_JUZGABLE`. Una fila del
cotejo es un dict con `modelo` y los seis campos de `cost-state` con sus nombres de Claude Code.
`entrada` y `familia` aceptan una tabla opcional para que `cotejar` trabaje con tablas mutadas.

### 4. Filas literales del fixture

Sacadas con `scratchpad/t1/elegir_filas.py` (solo lectura, imprime solo números e id de modelo),
con la regla de `cotejo.py` como filtro: una de `claude-opus-5`; una de `claude-opus-5-5[1m]` con
mucha lectura de caché que cae `fuera` con lectura ×0,8 y `dentro` con salida ×0,8; una de
`claude-opus-5-5` con mucha salida que cae `fuera` con salida ×0,8; una de
`claude-haiku-4-5-20251001` con 4 búsquedas web, `dentro` con ellas y `fuera` sin ellas ($0,051
frente a $0,091 cobrados); y una de Haiku de $0,020 (no juzgada).

### 5. Tests y control positivo

`bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_precios.py -q`: **8 passed**.

Mutantes aplicados con `scratchpad/t1/mutantes.py` (sustituye un texto que aparece una sola vez,
comprueba que el fichero cambia, corre el test y restaura). Ninguno falla por `KeyError`,
`ImportError` ni similares:

| Mutante | Test | Assert que dispara (salida de pytest) |
|---|---|---|
| No quitar la fecha | `test_normaliza_fecha_y_1m` | `test_precios.py:92: AssertionError: assert None is not None` |
| Primera clave que empieza por el id | `test_busqueda_exacta_en_los_pares` | `test_precios.py:99: assert 0.2 == 0.5` |
| `.get(id, {})` | `test_un_id_sin_entrada_no_tiene_precio` | `test_precios.py:106: AssertionError: assert {} is None` |
| `cotejar` sin la búsqueda web | `test_el_cotejo_cuenta_la_busqueda_web` | `test_precios.py:177: AssertionError: assert 'falla' == 'pasa'` |
| El cargador hace `urllib.request.urlopen(tabla["fuente"])` | `test_cargar_las_tablas_no_abre_sockets` | `test_precios.py:203: AssertionError: assert ['create_connection'] == []` |
| `veredicto` siempre `pasa` | `test_cotejo_con_filas_literales` | `test_precios.py:159: AssertionError: assert 'pasa' == 'falla'` (tabla sin `claude-opus-5`) |
| Fixture: la fila de Opus 5 cambiada por otra de Opus 5.5 | `test_cotejo_con_filas_literales` | `test_precios.py:159: AssertionError: assert 'pasa' == 'falla'` (el mutante de tabla sin Opus 5 ya no caza nada) |
| Fixture: la fila de mucha salida cambiada por la de mucha lectura | `test_cotejo_con_filas_literales` | `test_precios.py:172: AssertionError: assert 'pasa' == 'falla'` (salida ×0,8 ya no caza nada) |

Los tres mutantes de datos de REQ-013 (sin `claude-opus-5`, lectura ×0,8, salida ×0,8) viven dentro
del test y salen `falla` por el assert del veredicto; el primero nombra `claude-opus-5` entre las
`sin_precio`. La guarda (`r == ["dentro", "dentro", "dentro", "dentro", None]` y `pasa`) pasa con la
tabla sin mutar. Las dos últimas filas de la tabla muestran que cada fila elegida es la que hace
discriminar a su mutante.

### 6. Cotejo real con las tablas del paquete

- `python -I insumos/scripts/cotejo.py --precios src/local_delegate/resources/datos/precios.json`:
  206 líneas `cost-state`, 153 claves, 212 filas; **142 de 142 juzgables dentro, 0 fuera, 0 sin
  precio, veredicto `pasa`** (70 sin juzgar, < $0,05). Sin la búsqueda web, 138 de 142 (las 4 de
  Haiku). Mutantes: sin `claude-opus-5`, lectura ×0,8 y salida ×0,8 de Opus 5.5 dan `falla`.
- El mismo cotejo con `local_delegate.precios.cotejar` sobre las mismas filas
  (`scratchpad/t1/cotejo_modulo.py`, solo conteos): 212 filas, 142 `dentro`, 70 `None`, `pasa`.
  El port da lo mismo que el prototipo.

### 7. Empaquetado

`[tool.hatch.build.targets.wheel] packages = ["src/local_delegate"]` mete todo lo que cuelga del
paquete (como `resources/vendor/vendor.json`); no hace falta tocar `pyproject.toml`.
`pesado.sh uv build --wheel --out-dir <scratchpad>` contiene
`local_delegate/resources/datos/precios.json`, `local_delegate/resources/datos/densidad.json` y
`local_delegate/precios.py`. Instalado aislado (`uv run --isolated --no-project --with <wheel>`),
`cargar_precios()` devuelve 13 modelos y `cargar_densidad()` las familias `anterior` y `nueva`.

### 8. Integración de la ola 1

- `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q -p no:cacheprovider`:
  **1606 passed, 2 skipped, 1 warning in 56.48s** (línea base 1598 + 8 nuevos; el aviso es la
  `DeprecationWarning` de `starlette.testclient` de T0).
- `uv run ruff check .`: limpio. `uv run ruff format --check .`: 134 ficheros ya formateados.

### Desviaciones de T1

- **`claude-sonnet-4-5` pasa a `admite_esfuerzo: false`** por lo que dice su página (aviso a la
  sesión principal: cambia el prototipo; REQ-003 lo tratará como Haiku, `n/a`).
- Un test más de los que nombra el plan, `test_la_tabla_de_densidad_dice_con_que_modelos_se_midio`
  (guarda de `medido_con` y de que cada modelo listado es de esa familia en la tabla de precios).
- La forma de la fila del cotejo (dict con `modelo` y los seis campos) la fija esta tarea; el plan
  no la decía. T5 la construye desde `cost-state`.

## I2 — Integración de la ola 2 (T2 y T3), con la prueba de humo del `_meta`

Fecha: 2026-10-06. Escritor: agente de integración I2. MCP `local-delegate` desconectado en la
sesión del integrador: 0 llamadas `local_*`. Las evidencias de cada tarea están en sus ficheros y no
se copian aquí: [T2 — atribución en vivo](evidencias/T2.md) y
[T3 — vigilante de precios y límites](evidencias/T3.md).

### 1. Lint y formato

- `uv run ruff check .`: **limpio** (los cuatro `ISC004` de `scripts/vigilante_precios.py` que T2 vio
  ya no están: los arregló T3). `uv run ruff format --check .`: **139 ficheros ya formateados**.
- Nada mecánico que arreglar; ningún rojo de comportamiento que devolver.

### 2. Índice de git (preparado, sin commit)

- Añadidos con rutas explícitas los ficheros de T2 (`clients.py`, `install.py`, `server.py`,
  `hook_common.py`, `anotar_llamada.py`, `atribucion.py`, `test_clients.py`, `test_install.py`,
  `test_atribucion.py`) y de T3 (`ci.yml`, `codeql.yml`, `vigilante-precios.yml`,
  `.github/vigilante/limites-de-uso.txt`, `scripts/vigilante_precios.py`,
  `tests/fixtures/vigilante/*`, `test_vigilante.py`), más `evidencias/T2.md`, `evidencias/T3.md` y
  este fichero. Los `state.json` quedan fuera (los actualiza la sesión principal).
- Modos: `anotar_llamada.py` en `100755`; `scripts/vigilante_precios.py` en `100644` (sin shebang).
  Finales de línea de los nuevos: `i/lf w/lf`.
- `scripts/check_install_e2e.py` no necesitó cambio: usa `len(install._HOOK_EVENTS)`, que ahora es 2.
- Tras el `git add`: `uv run pytest tests/test_wiki.py -k shebang` → **1 passed**.

### 3. Suite completa

- `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q -p no:cacheprovider`:
  **1668 passed, 2 skipped, 1 warning in 60.73s** (ola 1: 1606 + 62 nuevos de T2 y T3). Los dos
  `skipped` son los de siempre: `test_dashboard_ui.py:517` (solo CI) y `test_checks.py:462` (no aplica
  en Windows). Playwright corrió (los otros 14 de `test_dashboard_ui.py` pasan). El aviso es la
  `DeprecationWarning` de `starlette.testclient` de T0.

### 4. Prueba de humo del `_meta` con Claude Code de verdad

**Desviación del plan:** el plan pedía el servidor del repo en un puerto libre sin tocar el daemon y
sin hook. Por instrucción de la sesión principal se hizo contra el **daemon reinstalado con esta
rama** y con los hooks instalados, así que también se comprobó la nota del hook (adelanta parte de
T10.3, que sigue siendo necesaria con sus tres llamadas desde un subagente).

1. Daemon parado (`schtasks /End` y `Stop-Process` de los `pythonw.exe -m local_delegate serve`),
   `bash ~/.claude/scripts/pesado.sh uv tool install --force --reinstall --no-cache ".[llamaswap]"`,
   `local-delegate install --mcp-mode http --web-token-env --enable-read-hook --agents`. El
   instalador levantó el daemon por la tarea programada (0.32.0, arriba a las 18:15:39Z). `doctor`
   tras escribir: `hooks copiados` **5 scripts** y `hooks registrados` **5** en `OK`, con
   `PreToolUse/mcp__local-delegate__.*` → `anotar_llamada.py`.
2. Primera sesión, `claude -p --model claude-haiku-4-5-20251001` desde un directorio vacío del
   scratchpad, que llama a `local_status`: el hook escribió su nota
   (`toolu_01WA….json` en `%TEMP%\local-delegate-llamadas`, mismo id que el
   transcript), pero **`local_status` no escribe línea en el log de uso** (no pasa por `_log_event`),
   así que no sirve para casar.
3. Segunda sesión, igual, que llama a `local_summarize` con `path` a un fichero de tres líneas del
   scratchpad. Línea del log (`usage-202610.jsonl`, sin `path`):

   ```
   ts 2026-10-06T18:16:40+00:00, tool local_summarize, ok True, client claude-code,
   tool_use_id toolu_01NT…, caller_kind main, caller_src hook+transcript,
   caller_model claude-haiku-4-5, caller_effort n/a
   ```

   La nota del hook se llama `toolu_01NT….json` y el `tool_use` del transcript de
   esa sesión tiene el mismo id.

**Resultado: PASA.** La línea trae `tool_use_id` con forma `toolu_…`, se casa con la nota del hook
(`caller_src: hook+transcript`) y con el transcript. `caller_effort: n/a` es lo esperado en Haiku 4.5
(no admite esfuerzo, T1). La ola 3 puede seguir.

**Ventana a excluir de las mediciones de adopción:** **2026-10-06T18:15:39Z – 18:16:42Z**
(reinstalación del daemon y las dos sesiones `claude -p`). Además, esas dos llamadas con `claude -p`
marcan la ventana de 5 h en curso como `contaminado` (REQ-052, paso 6). Hooks nuevos instalados
desde 2026-10-06T18:15Z: abre un tramo de versión de hook para las mediciones.

## T4 — Densidad, conversión única y fusión (ola 3)

Fecha: 2026-10-06. Escritor: agente de T4. MCP `local-delegate` desconectado en la sesión: 0
llamadas `local_*`.

### 1. Ficheros

| Fichero | EOL | Qué |
|---|---|---|
| `src/local_delegate/coste.py` (nuevo) | LF | `clase_de_contenido`, `respaldo()`, `familia_y_marcas`, `resolver(evento)` y `resolver_densidad(evento)`, `fundir_fila`, `fundir(filas, *, log_dir)`, `fila_en_vuelo(...)`, `tramo(fila, *, ahora, plazo_dias)`, `es_imagen` |
| `src/local_delegate/config.py` | LF | `COSTE_RESPALDO` (`LOCAL_DELEGATE_COSTE_RESPALDO`, con `_env`); comentario de `CHARS_PER_TOKEN`: solo modelo local |
| `src/local_delegate/server.py` | CRLF (3473/3473) | cuerpo de `tokens_claude`; `_escribir_destino(p, contenido, *, evento)`; `_savings_feedback(chars_in, label, *, evento)` y sus llamadas (la de `_chat`, que también usa `local_describe_image`, y las dos de las tools troceadas); el parámetro `feedback_char_estimate` de `_chat` desaparece (sin uso); `tokens_aprox` de `local_extract`; el lector del log de `local_status` funde con `coste.fundir` |
| `src/local_delegate/web/metrics.py` | CRLF (2303/2303) | `_load` funde por fichero antes de filtrar; JS `tokensClaude` (solo divide); pie «tokens de Claude por familia y tipo de contenido; modelo local ~4 chars/token»; la línea `.frm` de la ayuda y el *tip* del KPI «Coste local» (decían que el coste local supera al contexto conservado, que ya no es cierto: unidades distintas) |
| `tests/test_densidad.py` (nuevo) | LF | 16 tests |
| `tests/test_metrics.py`, `test_core.py`, `test_vision.py`, `test_boilerplate_salida.py` | LF | inventario y tests nuevos |
| `tests/test_dashboard_ui.py` | CRLF (533/533) | inventario (constantes del KPI) |

`node --check` del `<script>` de `metrics.HTML` (extraído a `scratchpad/panel.js`): sin errores.
`uv run ruff check .`: limpio. `uv run ruff format --check .`: 141 ficheros ya formateados.

### 2. Forma de la fila fundida (lo que consumen T5, T6 y T7)

`coste.fundir` devuelve **copias** con, además de los campos del log: `caller_model`,
`caller_kind`, `caller_effort`, `n`, `caducidades`, `cruce`, `banco` (por campo: línea > relleno >
respaldo; el respaldo solo pone modelo e hilo), `caller_origen` (`linea` | `relleno` | `respaldo`),
`respaldo_invalido: true` si la variable no se entiende, `densidad` (`{"text"|"returned"|"output":
[c100, origen] | null}`), `familia` y `marcas` (lista: `familia supuesta`, `densidad de la
familia`). El relleno de cada línea se busca en `atribucion-AAAAMM.json` del **mes de su `ts`**, con
la clave de `atribucion.claves_del_fichero` sobre el fichero entero. `tramo` devuelve
`excluido`, `al_momento`, `por_relleno`, `pendiente` o `supuesto`.

### 3. Inventario (suite completa con el cuerpo nuevo de Python y de JS)

`bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q -p no:cacheprovider`:
**24 failed, 1662 passed, 2 skipped** (`scratchpad/t4/inventario1.txt`). Todos son **(i) cambios de
cifra esperados** o de entrada; ningún defecto del código. Regla aplicada: número nuevo **literal**
con su derivación en un comentario, ningún `==` relajado. Las filas sin `path` de `_ev` caen en la
clase `otro` (formato `Read` → respaldo (3), c = 2,41), lo devuelto es prosa sin numerar (2,23) y el
respaldo es Opus 5.5 (familia nueva).

Además de la cifra, los tests que llaman a `_accounting`/`_aggregate` **directamente** pasan a
recibir la fila como la entrega `_load` en producción (`coste.fundir_fila`, ayudante `_resuelta` en
`test_metrics.py`): sin fundir, la regla nueva da 0 a propósito (REQ-033). Los que pasan por
`/api/stats` o `local_status` escriben el log crudo y ya funden solos.

| Test | Antes | Ahora | Por qué |
|---|---|---|---|
| `test_metrics::test_accounting_una_llamada_sin_trocear` | saved 1000, returned 100, net 900 | 1659, 179, 1480 | 4000×100//241; 400×100//223 |
| `test_metrics::test_accounting_troceado_separa_ahorro_de_coste` | saved 21044; `tokens_in > saved` | saved 34928; `tokens_in > 21044` | 84178×100//241. El `>` comparaba coste local con `saved`, que ahora está en otra unidad: se compara con una pasada del documento en tokens **locales** (84178÷4), que es lo que el assert quería decir. No se afloja: sigue siendo la misma desigualdad estricta sobre el mismo `tokens_in` |
| `test_metrics::test_accounting_imagen_usa_el_token_real_y_no_los_bytes` | saved 2758 | saved 0, `tokens_in` 2758, `bytes_saved_image` 504780 | REQ-038: la imagen sale del neto; el token real queda en el coste local |
| `test_metrics::test_accounting_imagen_historica_sin_marca_se_reconoce_por_la_tool` | saved 2758 | saved 0 y `(unit, bytes_saved_image) == ("bytes", 504780)` | REQ-038; el assert añadido conserva lo que el test prueba (que se reconoce por la tool) |
| `test_metrics::test_accounting_neto_resta_lo_devuelto` | 100, 1000, 900 | 179, 1659, 1480 | ídem |
| `test_metrics::test_accounting_salida_a_fichero_no_descuenta_el_recibo` | net = saved = 950 (`tokens_out` local) | 1793 | 4000 de salida × 100 // 223 (prosa sin numerar) |
| `test_metrics::test_accounting_el_neto_puede_ser_negativo` | net −100; (100, 200) | −193; (165, 358) | 400×100//241; 800×100//223 |
| `test_metrics::test_accounting_desglosa_en_caracteres` (imagen) | (1200, 200, 1000) | (0, 0, 0) | REQ-038; los campos en bytes y caracteres no cambian |
| `test_metrics::test_stats_distingue_delegaciones_de_llamadas_al_backend` | `tokens_context_saved` 22044 | 36587 | 1659 + 34928 |
| `test_metrics::test_stats_el_log_sintetico_de_la_mac_no_infla_nada` | 4×1000; devuelto 4×100 | 4×1659; 4×179 | ídem |
| `test_metrics::test_stats_expone_el_desglose_en_caracteres` | devuelto 300; bruto 3150; neto 2850 | 179; 3452; 3273 | texto 1659−179, salida 1793, imagen 0 |
| `test_metrics::test_stats_quien_delego_trae_el_neto` | 900 | 1480 | ídem; filas pasadas por `_resuelta` |
| `test_metrics::test_stats_separates_local_and_remote_compute` | 1000 / 2000 | 1659 / 3319 | 4000 y 8000 × 100 // 241 |
| `test_metrics::test_accounting_el_historico_sin_campos_nuevos_se_lee_igual` | saved 21044 | 34928 | 84178×100//241 |
| `test_metrics::test_local_status_y_el_dashboard_cuentan_igual` | (comparación) | sin cambio de assert; `_aggregate` recibe `coste.fundir(filas)` y se añade la guarda `tokens_context_saved == 34928` | el panel agrega filas fundidas; sin fundir daba 0 contra la cifra de `local_status` |
| `test_metrics::test_local_status_cuenta_el_neto_como_el_panel` | (comparación) | ídem, guarda `tokens_context_net == 1287` | ídem |
| `test_metrics::test_stats_ok_null_no_cuenta_como_error` | (pasaba) | filas por `_resuelta` | consistencia con producción; mismos asserts |
| `test_core::test_local_status_reports_log_stats` | `"~100 tokens"` | `"~165 tokens"` | 400×100//241 |
| `test_core::test_chat_appends_feedback_when_source_path` | `"500 tokens"` (el `tokens_in` **local**) | `"2,000 chars ≈ 829 tokens de Claude que no entraron a tu contexto)"` y `"500" not in text` | REQ-035; 2000×100//241 |
| `test_boilerplate_salida::test_accounting_suma_la_salida_escrita_al_ahorro` | 950 (`tokens_out` local) | 1659 | código sin numerar, 4000×100//241 |
| `test_boilerplate_salida::test_accounting_suma_los_dos_ahorros_cuando_los_hay` | `8000 // CHARS_PER_TOKEN + 950` | `3319 + 1659` | entrada `otro` (2,41) + salida `codigo` (2,41) |
| `test_vision::test_describe_image_feedback_uses_real_tokens` | `"… ≈ 300 tokens"` | `"(leído server-side: 68 bytes imagen que no entraron a tu contexto)"` | REQ-035: solo los bytes |
| `test_vision::test_describe_image_omits_feedback_when_no_usage` | `"leído server-side" not in text` | la coletilla de bytes está y `"≈" not in text` | la coletilla ya no depende de los tokens, así que sale siempre (REQ-035) |
| `test_dashboard_ui::test_el_KPI_hero_…` y `test_quien_delego_ensena_el_neto_del_cliente` | `_BRUTO, _DEVUELTO, _NETO = 10_000, 1_000, 9_000` | `16_597, 1_793, 14_804`; los caracteres del log quedan literales (40 000 y 4 000) | 40000×100//241 y 4000×100//223 |

**Segundo inventario (JS): 0 rojos en `tests/test_dashboard_js.py`.** El plan esperaba 8, pero sus
tests de `byDay`/`acct` solo miran `calls` y fechas, no tokens (el que mira tokens sustituye
`tokensClaude` por un doble), así que no hay nada que reescribir y no se tocó el fichero.

`test_resumen_estructurado.py:332` (la cola «que no entraron a tu contexto)») pasa sin cambio: la
cola se conserva.

### 4. Tests nuevos y control positivo

Mutantes con `scratchpad/t4/mutantes.py` (sustituye un texto que aparece una vez, comprueba que el
fichero cambia, corre el test, restaura byte a byte; `git diff --stat` idéntico antes y después).
Ninguno falla por `KeyError`, `ImportError` ni similares.

| Test | Control | Assert que dispara (salida de pytest) |
|---|---|---|
| `test_metrics::test_paridad_acct_entre_python_y_el_js_del_panel` (20 casos existentes + 6 de REQ-037, todos por `coste.fundir`) | (c) corte real: Python cambiado y JS con `÷ 4`, antes del paso 4 de JS; repetido después como mutante M17b | `test_metrics.py:1203`/`:1230`: `('returned', caso 0) assert 100 == 179` — caso 0 de los existentes, el de la revisión del plan |
| ídem, guarda | M18: el respaldo (3) devuelve origen `sin_numerar` | `test_metrics.py:1243: assert {'medida', 'sin_numerar'} >= {'conservador...'` |
| `test_metrics::test_el_js_sigue_a_python` | (b) M17: el JS divide la prosa por 200 fijo; también el corte (c) | `test_metrics.py:1292: assert 2000 == ((4000 * 100) // 250)` (con `÷ 4`: `assert 1000 == …`) |
| `test_densidad::test_sin_densidad_las_dos_dan_cero` | (b) M1: Python resuelve si falta | `test_densidad.py:87: assert 2000 == 0` en `server.tokens_claude(4000, tipo="text", evento=fila) == 0` |
| `test_densidad::test_el_mismo_py_con_haiku_da_menos_tokens` | (b) M2: sin respaldo (2) | `test_densidad.py:105: assert [312, 'conservadora'] == [312, 'sin_numerar']` |
| `test_densidad::test_la_tool_manda_sobre_la_extension` | (b) M3: extensión primero | `test_densidad.py:115: assert 'codigo' == 'log'` |
| `test_densidad::test_respaldo_por_variable` | (b) M4: ignorar la variable | `test_densidad.py:144: assert 'nueva' == 'anterior'` |
| `test_densidad::test_una_imagen_no_resta_del_neto` | (c) M5: `image` con la regla de hoy | `test_densidad.py:196: assert 1200 == 0` |
| `test_densidad::test_la_fusion_respeta_el_orden` | (b) M6: el relleno pisa a la línea | `test_densidad.py:237: assert 'claude-haiku-4-5' == 'claude-opus-5'` |
| `test_densidad::test_la_fusion_no_toca_la_cache` | (b) M7: `nueva = fila` | `test_densidad.py:266: assert 'densidad' not in {…}` |
| `test_densidad::test_tramos` | (b) M8: `ambiguo` cuenta como pendiente; M9: 30 días fijos | `:301: assert 'pendiente' == 'supuesto'`; `:297: assert 'supuesto' == 'pendiente'` (`f60` con `plazo_dias=90`) |
| `test_densidad::test_ningun_chars_per_token_en_la_conversion` | (a) M10a/b/c: `CHARS_PER_TOKEN` de vuelta en `tokens_claude`, en el recibo y en `tokens_aprox` | `test_densidad.py:324: AssertionError: tokens_claude` / `_escribir_destino` / `tokens_aprox` |
| `test_densidad::test_la_coletilla_usa_tokens_de_claude` | (a) M12: los mensajes en vuelo sin fundir | `test_densidad.py:355: assert '≈ 2,000 tokens de Claude' in '… ≈ 0 tokens de Claude …'` |
| `test_densidad::test_el_recibo_de_salida_usa_tokens_de_claude` (nuevo, no estaba en el plan) | (a) M10b; M12 | `test_densidad.py:368`: `…≈150 tokens…` y `…≈0 tokens…` en vez de `≈248` |
| `test_densidad::test_tokens_aprox_de_extract_es_de_claude` (nuevo) | (a) M10c | `test_densidad.py:382: assert 1000 == 2127` |
| `test_densidad::test_la_coletilla_usa_el_modelo_de_la_nota_si_ya_esta` (nuevo) | (b) `fila_en_vuelo` no mira `llamada_actual` | `test_densidad.py:399: assert '≈ 1,328 tokens de Claude' in '… ≈ 2,000 tokens …'` |
| `test_densidad::test_las_columnas_de_devuelto_y_salida` (nuevo) | (b) M20: lo devuelto por `local_extract` como prosa | `test_densidad.py:132: assert [223, 'medida'] == [188, 'medida']` |
| `test_densidad::test_marcas_de_familia` (nuevo) | (b) M21: sin marca | `test_densidad.py:174: assert ('anterior', []) == ('anterior', … la familia'])` |
| `test_vision::test_la_coletilla_de_imagen_no_tiene_tokens` (nuevo) y el reescrito de la línea 146 | (a) M11: la imagen pasa por `tokens_claude` | `test_vision.py:169: assert 'tokens' not in ': 68 bytes …'`; `test_vision.py:148` (`≈ 0 tokens de Claude`) |
| `test_metrics::test_local_status_funde_como_el_panel` | (b) M15: `local_status` sin fundir | `test_metrics.py:1375: assert 0 == 1196` |
| `test_metrics::test_las_filas_de_api_events_vienen_resueltas` | (a) M16: `_load` sin fundir | `test_metrics.py:1392: assert False` en `all("densidad" in e …)` |

Salidas completas en `scratchpad/t4/mutantes.txt`, `mutantes2.txt` y `mutantes3.txt`. Los números de
línea son los del momento del control.

### 5. Suite

- Verificación del plan (`test_densidad`, `test_metrics`, `test_dashboard_js`, `test_core`,
  `test_vision`, `test_boilerplate_salida`, `test_resumen_estructurado`, `test_aislamiento_entorno`):
  **256 passed**.
- Suite completa con Playwright:
  `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q -p no:cacheprovider -rs` →
  **1688 passed, 2 skipped, 1 warning in 59.55s** (ola 2: 1668 + 20 nuevos: 16 de
  `test_densidad.py`, 3 de `test_metrics.py` y 1 de `test_vision.py`). Los dos `skipped` son los de
  siempre (`test_checks.py:462`, `test_dashboard_ui.py:521`); Playwright corrió. El aviso es la
  `DeprecationWarning` de `starlette.testclient` de T0. Después: `ruff check` limpio y
  `ruff format --check` con 141 ficheros formateados.

### 6. Desviaciones de T4

- **El corte de interfaz (paso 1) no se dejó como estado intermedio en verde**: se escribieron
  directamente las reglas. Los dos controles (c) que dependían del corte se ejecutaron igual: el de la
  paridad contra el estado real «Python nuevo, JS con `÷ 4`» (antes de tocar el JS) y, los dos, como
  mutantes que reponen la regla de hoy (M5, M17b). Por lo mismo, los dos inventarios del plan son uno
  solo (Python y JS ya cambiados); se separan por fichero en la tabla.
- **Casos existentes de la paridad: 20**, no 22 como dice el plan (12 de REQ-001, 5 de antes y 3 de
  F3). Se añadieron los 6 de REQ-037.
- **El caso «la misma inline»** de REQ-037 se escribe a fichero (`output_to_file`): una lectura
  inline no reclama ahorro ni devuelto, así que daría 0 con las dos reglas y no discriminaría. Escrito
  a fichero ejercita la columna `sin_numerar` (la de lo que escribe la tool), que sí cambia.
- **`test_dashboard_js.py` sin rojos** (el plan esperaba 8): no se tocó.
- **`test_dashboard_ui.py`** (zona de T6 en la tabla de propiedad) entra por el inventario: solo sus
  constantes del KPI.
- **`_chat` pierde `feedback_char_estimate`**: con la firma nueva de `_savings_feedback` no tenía uso.
- **Coletilla de imagen**: sale siempre, con los bytes (antes se omitía sin `usage`): REQ-035 no la
  condiciona a los tokens.
- **Textos de la ayuda del panel**: la línea `.frm` y el *tip* de «Coste local» se ajustaron porque
  decían algo que con la densidad ya es falso (que el coste local supera al contexto conservado). La
  frase «es cuota que no gastaste» de la ayuda **sigue ahí**: es de T6 (REQ-045).
- Un mutante (el de `fila_en_vuelo` sin `llamada_actual`) corrió un `pytest` de 0,3 s fuera del
  cerrojo `pesado.sh`.

### Lo que T5 tiene que saber

- El mes del relleno de una línea es el de su `ts` (`AAAAMM`), y la clave se calcula con
  `atribucion.claves_del_fichero` sobre **todas** las líneas del fichero, en orden (como hace
  `coste.fundir`). Si T5 filtra antes de calcular las claves, no casarán.
- `coste.tramo` espera una fila **fundida** (`caller_origen`, `cruce`, `banco`); para el aviso de
  `doctor` (T7) basta `coste.fundir(filas, log_dir=...)` y luego `tramo`.
- Los agregados de `N` sin excluidas: `atribucion.excluida(fila, entrada)`; `coste` no los toca.

## T5 — Comando `recalcular-coste` (ola 4)

Fecha: 2026-10-06. Escritor: agente de T5. MCP `local-delegate` desconectado en la sesión: 0
llamadas `local_*`. Sin commit (lo hace la sesión principal); índice preparado.

### 1. Ficheros

| Fichero | EOL | Qué |
|---|---|---|
| `src/local_delegate/transcripts.py` (nuevo) | LF | `leer(raiz) -> Indice` (una pasada por `*.jsonl`), `casar(lineas, indice, desde=)`, `n_y_caducidades`, `percentil`/`mediana`, `cost_state`, `coste_de_peticion`; cuenta líneas rotas y ficheros ilegibles |
| `src/local_delegate/cuota.py` (nuevo) | LF | `puntos_de_rechazo`, `sanear`, `puntos_del_statusline`, `quitar_solapados`, `vigentes`, `dispersion`, `deriva`, `criterio`, `estado(agregados, ahora)` |
| `src/local_delegate/recalcular.py` (nuevo) | LF | `ejecutar(claude_dir, log_dir, *, ahora, reiniciar) -> resumen`, `leer_agregados`, `escribir_agregados` (atómica), `texto_del_resumen` |
| `src/local_delegate/cli.py` | CRLF (956/956) | subparser `recalcular-coste` (`--reiniciar-calibracion five_hour\|seven_day`, `--claude-dir`) y `cmd_recalcular_coste` |
| `tests/test_transcripts.py`, `tests/test_cuota.py`, `tests/test_recalcular.py` (nuevos) | LF | 7 + 9 + 8 tests; los constructores de transcripts sintéticos viven en `test_transcripts.py` y los importan los otros dos (como `test_panel_estados.py` importa de `test_dashboard_js.py`) |

`uv run ruff check .` limpio; `uv run ruff format --check .`: 147 ficheros formateados. La ayuda
(`local-delegate --help` y `recalcular-coste --help`) lista el subcomando;
`test_smoke.py::test_los_subcomandos_estan_definidos_una_sola_vez` lo despacha sin tocar nada más.

### 2. Lo que consumen T6, T7 y T8

- **`coste-agregados.json`** sigue el formato del plan. `puntos` guarda **solo** los válidos (los
  descartados van a `descartes`, por tipo y motivo: `delta_pequeno`, `sin_uso_local`, `contaminado`,
  `solapado`, `fuera_de_rango`, `linea_corrupta`). Las fechas van en ISO UTC. `peticiones_sin_precio`
  es `null` en los puntos del statusline (su Δ$ sale de `cost_usd`, no de la tabla). Las marcas son
  textos: `cota baja`, `solo comprobación`, `cota baja si hubo uso en otras superficies`, `reinicio`.
- **`n_por_mes`**: grupos `"<modelo>|main"` y `"<modelo>|subagent"` (el vocabulario de
  `caller_kind`, no `principal`/`subagente`), con los valores ordenados. Se calcula **sobre las filas
  fundidas** (`coste.fundir`) después de escribir el relleno: cuenta las líneas `ok` no excluidas
  con `n` del relleno (no las del respaldo). Por eso un mes conserva sus casos aunque el transcript
  ya no exista: salen del `atribucion-AAAAMM.json`, que no se borra.
- **`cuota.estado(agregados, ahora)`** devuelve por tipo: `estado`, `puntos` (tras la deriva),
  `dispersion` (si hay 2 o más), `deriva`, `motivo` («faltan k puntos del statusline» o «dispersión
  X % ≥ 25 %»), `mediana_C` si calibra, `puntos_rechazo`, `descartes` (con `caducado` y `reinicio`
  añadidos al leer) y `aviso` (REQ-058). Con `agregados=None` o sin fuentes, el motivo es
  `cuota.SIN_DATOS` («no hay datos de calibración en esta máquina»); sin registro del statusline,
  `cuota.SIN_STATUSLINE`. Aplica la vigencia de 60 días **al leer** (REQ-054).
- **`recalcular.leer_agregados(log_dir)`** devuelve `None` si el fichero falta o no se lee (nunca
  lanza): es lo que deben usar T6 y T7.
- **Relleno**: una entrada por línea del log de los últimos `H` días; las casadas llevan
  `caller_model`, `caller_kind`, `caller_effort` (`n/a` en un modelo sin esfuerzo), `n`,
  `caducidades`, `cruce` y `banco`; las `ambiguo`/`sin_cruce`, solo `cruce` y `banco: false`.

### 3. Tests y control positivo

Mutantes con `scratchpad/t5/mutantes.py` (sustituye un texto que aparece una vez, comprueba que el
fichero cambia, corre el test con `pytest -x`, saca el assert y restaura byte a byte; `git diff --stat`
idéntico antes y después). Ninguno falla por `KeyError`, `ImportError`, `JSONDecodeError` ni
similares: las dos excepciones que un mutante deja escapar se capturan en `escapo`. Los números de
línea son los del momento del control (antes de `ruff format`).

| Test | Mutante | Assert que dispara (salida de pytest) |
|---|---|---|
| `test_transcripts::test_n_y_caducidades_conocidos` (N = 3, 1 caducidad, escritos a mano) | M1 contar `<synthetic>`; M2 contar por línea; M3 sin `compact_boundary` | los tres: `test_transcripts.py:170: assert 4 == 3` (`n == N_CONOCIDO`) |
| `test_transcripts::test_el_ttl_depende_del_hilo` | M4 TTL de 300 s en los dos hilos | `:190: assert 1 == 0` |
| `test_transcripts::test_percentil_par` | M5 mediana = elemento central inferior | `:194: assert 2 == 2.5` |
| `test_transcripts::test_cruce_exacto_ventana_y_path` | M6 desempatar también por cercanía del `ts` | `:250: assert ['ventana', 'ventana'] == ['ambiguo', 'ambiguo']` |
| `test_transcripts::test_el_relleno_usa_el_plazo_leido` (90 días, línea de 45) | M7 ventana de 30 días fija | `:269: assert 'toolu_p' in {}` (la línea queda sin entrada) |
| `test_transcripts::test_sin_cruce_y_banco` | guarda | pasa |
| `test_transcripts::test_cost_state_toma_la_ultima_por_posicion` | M8 la primera | `:322: assert 1.0 == 2.5` |
| `test_cuota::test_cinco_filas_son_un_punto` | C1 un punto por par consecutivo | `test_cuota.py:73: assert 4 == 1` |
| `test_cuota::test_sesiones_en_paralelo` | C2 Δ$ solo de la sesión elegida | `:93: assert 4.0 == 6.0` |
| `test_cuota::test_descartes` | C3a sin mirar sesiones ajenas; C3b umbral de Δ% en 1; C3c `dolar < 0`; C3d sin marca `reinicio`; C3e sin solapes | `:109` `None == 1` (`contaminado`); `:99` `None == 1` (`delta_pequeno`); `:102` `None == 1` (`sin_uso_local`); `:118: assert 'reinicio' in [...]`; `:130` `None == 1` (`solapado`) |
| `test_cuota::test_sanear_y_lineas_corruptas` | C4a sin saneado; C4b sin `try` en la línea del registro; C4c sin `try` en la del transcript | `:147` `None == 1` (`fuera_de_rango`); `:146: assert not JSONDecodeError(...)`; `:160: assert not JSONDecodeError(...)` |
| `test_cuota::test_rechazos_duplicados_son_un_punto` (11 registros; Δ$ = $12 a mano) | C5 un punto por registro | `:197: assert 11 == 1` |
| `test_cuota::test_criterio_de_la_spec` (los seis escenarios de `criterio.py`) | C6 deriva sin «mismo sentido» | `:223: assert 'sin calibrar' == 'calibrado'` (con `{…, 230, 100}`) |
| `test_cuota::test_un_punto_de_61_dias_no_cuenta` | C7 sin vigencia | `:242: assert 'calibrado' == 'sin calibrar'` |
| `test_cuota::test_reinicio_a_mano` | C8 ignorar el reinicio | `:252: assert [{...}] == []` |
| `test_cuota::test_sin_fuentes_lo_dice` (nuevo, REQ-061) | C9 sin el motivo de fuentes | `:266: assert 'faltan 3 pun...' == 'no hay datos...'` |
| `test_recalcular::test_la_privacidad` | R1 guardar el `path` en la entrada | `test_recalcular.py:103: assert 'MARCADORA-7f3a' not in '{"entradas"...'` |
| `test_recalcular::test_idempotente_y_solo_lectura` | R2 dejar una caché en `claude_dir` | `:156: assert [('.cache-rec...')] == [...]` (`despues == antes`) |
| `test_recalcular::test_los_agregados_de_n_no_cuentan_excluidas` | R3 sin `atribucion.excluida` | `:186: assert [40, 60, 70] == [40]` |
| `test_recalcular::test_un_punto_sobrevive_al_transcript_borrado` | R4 sobrescribir en vez de fundir | `:211: assert {...} in []` |
| `test_recalcular::test_un_mes_viejo_no_se_recalcula` (con guarda: sin lo previo sale `[7]`) | R5 recalcular todos los meses | `:231: assert {'claude-opus...ubagent': [7]} == {'claude-opus-5\|main': [127]}` |
| `test_recalcular::test_guarda_el_plazo` | R6 no guardarlo | `:245: assert None == 90` |
| `test_recalcular::test_sin_transcripts_no_rellena` (nuevo) | R7 rellenar sin transcripts | `:254: assert [WindowsPath(...202610.json')] == []` |
| `test_recalcular::test_el_cli_lo_lanza` | (a) `cli.py` de `HEAD` | `:273: assert 2 == 0` (subcomando desconocido, `SystemExit(2)` capturado) |

Salidas completas en `scratchpad/t5/mutantes.txt` y `mutantes2.txt`. El primer intento de C3b
(umbral 0) fallaba por `ZeroDivisionError` (el semanal con Δ% = 0 llegaba a la división): no valía
como control y se cambió a umbral 1, que falla por su assert.

### 4. Suite

- Verificación del plan (`test_transcripts`, `test_cuota`, `test_recalcular`, `test_atribucion`,
  `test_precios`, `test_aislamiento_entorno`, más `test_smoke`): **79 passed**.
- Suite completa con Playwright:
  `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q -p no:cacheprovider -rs` →
  **1712 passed, 2 skipped, 1 warning in 61.17s** (T4: 1688 + 24 nuevos). Los dos `skipped` y el
  aviso son los de siempre.

### 5. Sobre los datos reales (solo agregados)

Una ejecución de `recalcular.ejecutar(~/.claude, <copia de los usage-*.jsonl en el scratchpad>)`:
lee los transcripts reales y escribe **solo** en esa copia, que se borró después. El sitio real
(`%LOCALAPPDATA%\local-delegate`) no se tocó; la ejecución oficial es la de T8.

- **2,39 s** (452 transcripts; 0 líneas ilegibles). `plazo_dias` = **90**.
- Relleno: 417 líneas en plazo: `ventana` 177, `ventana+path` 57, `exacto` 1, `ambiguo` 7,
  `sin_cruce` 175 (incluye las de cliente `mcp`, que nunca aparecen en un transcript).
- `n_por_mes`: 202608 `opus-5|main` 3 casos; 202609 `opus-5-5|subagent` 20 y `opus-5|main` 23;
  202610 `opus-5-5|subagent` 132 (178 en total).
- Cotejo: **pasa**, 144 filas juzgadas, 0 fuera, 0 sin precio (tabla `2026-10-06`).
- Cuota: los dos tipos `sin calibrar`, 0 puntos del statusline. Rechazos: uno de 5 h con
  **Δ$ = $125,71** y uno semanal con **$397,68** (los de REQ-051). Descartes: 5 h `contaminado` 2 y
  `fuera_de_rango` 1; semanal `contaminado` 1 (el registro creció desde el 2026-10-06 a las 15:00).
- Privacidad de lo escrito (solo conteos): rutas de unidad, `/Users/`, `/home/`, nombre de cada
  carpeta de `projects`, usuario del sistema y UUID → **0** en los cinco JSON; `toolu_` → 0 en
  `coste-agregados.json` (1 en `atribucion-202610.json`, la clave de la línea con `tool_use_id`,
  permitida por REQ-072).

### 6. Desviaciones de T5

- **Sin transcripts no se escribe relleno.** Si no existe `claude_dir/projects` (otra máquina), el
  comando no marca las líneas `sin_cruce`: dejarlas sin entrada las mantiene en `pendiente` mientras
  estén en plazo, que es lo que pide el escenario «otra máquina sin datos». Test propio
  (`test_sin_transcripts_no_rellena`).
- **Un `tool_use_id` que no está en los transcripts** da `sin_cruce` (no se intenta la ventana): el
  transcript de esa llamada no existe, así que la ventana tampoco lo encontraría.
- **El cotejo se conserva** si esta ejecución no encuentra ninguna línea `cost-state` (transcripts
  borrados): `doctor` lee «el último cotejo guardado».
- **`linea_corrupta`**: una línea rota del registro, o de un transcript, o un fichero ilegible, cuenta
  en **los dos** tipos (no se sabe a cuál habría aportado). Una fila del registro sin `ts` legible
  también es `linea_corrupta`. `calibracion.py` llama a esos motivos `pct_invalido`, `sin_ts` y
  `linea_corrupta` y los cuenta en global: **T8, paso 6**, tiene que comparar con esa traducción.
- **Solapes**: se aplican por (fuente, tipo), después de fundir con los puntos del JSON anterior; así
  un punto de una ventana que siguió creciendo sustituye al de la ejecución previa.
- **Reinicio**: un punto con `fin` anterior a la fecha de `--reiniciar-calibracion` deja de contar
  (`fin` igual a la fecha, cuenta).
- **El log legado** (`LOCAL_DELEGATE_LOG`, sin rotación) no se rellena: el comando lee los
  `usage-AAAAMM.jsonl` de `config.LOG_DIR`, que es donde `coste.fundir` busca el relleno.
- **Tests de más**: `test_sin_fuentes_lo_dice` y `test_sin_transcripts_no_rellena`, con su mutante.
- `cuota.estado` y `recalcular.leer_agregados` quedan escritos para T6/T7 (el plan los nombra en T5).

### Lo que T6, T7 y T8 tienen que saber

- **T6**: `cuota.estado(recalcular.leer_agregados(config.LOG_DIR), ahora)` ya aplica vigencia,
  reinicio, deriva, aviso de REQ-058 y los dos motivos sin fuentes. `plazo_dias` está en el JSON
  (30 si falta). Para el origen de `N` (REQ-042 (2)) los grupos son `"<modelo>|<main|subagent>"`.
  `test_origen_de_N` puede escribir los agregados con `recalcular.escribir_agregados`.
- **T7**: `recalcular.leer_agregados(log_dir)` nunca lanza; `cotejo` puede ser `null` (sin datos)
  y trae `veredicto` y `sin_precio` (lista de ids normalizados).
- **T8**: la ejecución oficial es `uv run local-delegate recalcular-coste`; aquí tardó 2,4 s. Para el
  paso 6, ver la traducción de motivos de arriba.

## I5 — Integración de la ola 5 (T6 y T7)

Fecha: 2026-10-06. Escritor: agente de integración I5. MCP `local-delegate` desconectado en la
sesión del integrador: 0 llamadas `local_*`. Las evidencias de cada tarea están en sus ficheros y no
se copian aquí: [T6 — coste y cuota en la API y el panel](evidencias/T6.md) y
[T7 — check `config.coste` de `doctor`](evidencias/T7.md).

### 1. Lint y formato

- `uv run ruff check .`: **limpio**. `uv run ruff format --check .`: **151 ficheros ya formateados**.
- `node --check` del `<script>` de `metrics.HTML` (extraído al scratchpad): **sin errores**.
- Finales de línea conservados: `metrics.py`, `test_dashboard_ui.py` y
  `docs/wiki/Integration-install.md` en `i/crlf w/crlf`; `checks.py`, `test_checks.py`,
  `test_doctor.py` y `test_wiki.py` en `i/lf w/lf`; los seis ficheros nuevos, solo LF.
- Nada mecánico que arreglar; ningún rojo de comportamiento que devolver.

### 2. Lo que se cruzó entre las dos tareas

- **Cotejo sembrado por T7** en `test_checks.py::test_complete_home_is_all_ok` y
  `test_doctor.py::test_run_doctor_exit_0_when_everything_is_in_place`: solo se añade un
  `coste-agregados.json` con `veredicto: pasa` en un `LOG_DIR` sin log de uso (el aviso de relleno no
  puede saltar). Las aserciones no cambian: los dos siguen exigiendo `ok` en **todos** los checks,
  ahora veintidós, igual que ya hacían con `clients.jsonl`. Siguen probando lo mismo.
- **Número de checks**: `len(checks.CHECKS)` = 22; el docstring y las frases de `checks.py`
  («veintidós», «ver los otros veintiún») y la wiki («las veintidós piezas», fila «coste y relleno»)
  cuadran, y los guardianes de `test_checks.py` y `test_wiki.py` pasan. Ni el README ni el CHANGELOG
  dan la cifra.
- **Textos del panel**: `test_frases_prohibidas` pasa sobre `metrics.HTML` y `/api/stats`; en `src/`
  y `docs/` no queda «cuota que no gastaste» ni «ahorro de cuota».

### 3. Suite completa

- `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q -p no:cacheprovider`:
  **1739 passed, 2 skipped, 1 warning in 60.10s** (T5: 1712 + 21 de T6 + 6 de T7). Playwright corrió:
  `test_dashboard_ui.py`, `test_captura.py` y `test_panel_coste.py` dan 29 passed y el único salto es
  `test_dashboard_ui.py:596` («solo aplica al CI»). El otro salto y el aviso son los de siempre.

### 4. Índice de git (preparado, sin commit)

- Añadidos con rutas explícitas los ficheros de T6 (`valoracion.py`, `web/metrics.py`,
  `test_valoracion.py`, `test_panel_coste.py`, `test_dashboard_ui.py`) y de T7 (`checks.py`,
  `test_coste_doctor.py`, `test_checks.py`, `test_doctor.py`, `test_wiki.py`,
  `docs/wiki/Integration-install.md`), más `evidencias/T6.md`, `evidencias/T7.md` y este fichero.
  Los `state.json` quedan fuera (los actualiza la sesión principal).

### Lo que T9 tiene que saber

- **El mock de `scripts/dev/capture_dashboard.py`** no trae `coste`, `cuota`, `imagenes` ni
  `densidad_tabla`. El panel esconde las tres tarjetas si faltan, así que la captura sale como antes;
  para que aparezcan en la captura del README hay que añadir esas claves al mock.
- **`README.md:30`** todavía dice «vuelve el resultado corto — cuota que no gastaste», la frase que
  T6 quitó del panel (REQ-045). Es documentación: la reescribe T9.

## T8 — Medición con los datos reales de esta PC (ola 6)

Fecha: 2026-10-06, de 19:11Z a 19:15Z. Escritor: agente de T8. MCP `local-delegate` desconectado en
la sesión: 0 llamadas `local_*`. Versión del **repo** (`uv run`); el daemon no se tocó (sigue con la
rama de la ola 2; su reinstalación es de T10). Sin commit. Solo agregados.

**Lo escrito en el `LOG_DIR` real** (`%LOCALAPPDATA%\local-delegate`): `atribucion-202607.json`,
`-202608`, `-202609`, `-202610` y `coste-agregados.json`, los cinco **nuevos** (antes del paso 1 no
existía ninguno). Los `usage-*.jsonl` no se modifican, pero se copiaron antes a
`%LOCALAPPDATA%\local-delegate-respaldo-t8-2026-10-06\` (los cuatro, con su fecha). Para volver al
estado previo basta borrar los cinco JSON. El comando se lanzó cuatro veces (pasos 1, 1 repetido
para cronometrar, 5 y 6); la salida fue idéntica todas las veces (idempotente).

Scripts de referencia: `atribucion_n.py`, `calibracion.py`, `criterio.py` y `clave_relleno.py`
**copiados al scratchpad** junto con `precios.json` y `densidad.json` **del paquete**, porque los
de `insumos/` difieren (paso 5). Los insumos no se editaron.

### 1. El comando sobre los datos reales

`bash ~/.claude/scripts/pesado.sh uv run local-delegate recalcular-coste`: código de salida 0,
**3,34 s** de pared con el arranque de `uv` (`time`; criterio: < 30 s). `plazo_dias` guardado =
**90**. Resumen: 456 transcripts (0 líneas ilegibles); 417 líneas rellenadas (`ventana` 177,
`ventana+path` 57, `exacto` 1, `ambiguo` 7, `sin_cruce` 175); 178 casos de `N`
(202608 `opus-5|main` 3; 202609 `opus-5-5|subagent` 20 y `opus-5|main` 23; 202610
`opus-5-5|subagent` 132). Las mismas cifras que T5 sobre la copia. **Pasa.**

### 2. Privacidad de lo escrito (solo conteos)

Script de solo lectura en el scratchpad que cuenta coincidencias por patrón, sin imprimir texto.
Patrones: `[A-Za-z]:[\\/]`, `/Users/`, `/home/`, el nombre de cada una de las **33** carpetas de
`~/.claude/projects` leídas en ese momento, el usuario del sistema, UUID y `toolu_`.

| Fichero | unidad | `/Users/` | `/home/` | carpetas | usuario | UUID | `toolu_` |
|---|---|---|---|---|---|---|---|
| `atribucion-202607.json` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `atribucion-202608.json` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `atribucion-202609.json` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `atribucion-202610.json` | 0 | 0 | 0 | 0 | 0 | 0 | 1 (permitido) |
| `coste-agregados.json` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

El `toolu_` de `atribucion-202610.json` es la clave de la única línea con `tool_use_id` (REQ-072
lo permite fuera de `coste-agregados.json`). **Control positivo**: un fichero sintético con una
muestra de cada patrón da al menos 1 en todas las columnas, y `usage-202610.jsonl` (que sí lleva
rutas) da 134 en unidad, 117 en carpetas, 68 UUID. El primer intento del control dio 1 en unidad
donde había 2: el heredoc se había comido una barra del patrón (`[\/]` solo veía `D:/`); se
corrigió con `chr(92)` y se repitieron el control y la búsqueda real (la tabla es la corregida).
**Pasa.**

### 3. Cotejo real

Resumen del comando: **pasa**, **144 filas juzgadas**, 0 `fuera`, 0 `sin_precio`, tabla
`2026-10-06`; fecha del cotejo guardado `2026-10-06T19:11:37+00:00`.
`uv run local-delegate doctor` (código 0): `[ OK ] coste y relleno: el último cotejo
(2026-10-06T19:11:37+00:00) cuadra: 144 fila(s) juzgadas con la tabla de precios del 2026-10-06`.
El `warn` por relleno pendiente que dejó T7 desaparece al lanzar el comando. **Pasa.**

### 4. Septiembre en tokens (REQ-036)

`metrics._load` sobre el mes `202609` (`_month_span`, fin exclusivo) → 143 filas, solo de
`usage-202609.jsonl`; después `_aggregate` y `valoracion.bloque_coste` con los agregados del paso 1.

| Cifra | Panel (hermano) | Ahora | |
|---|---|---|---|
| `chars_saved_text` | 3 463 739 | 3 463 739 | idéntica |
| `bytes_saved_image` | 1 489 047 | 1 489 047 | idéntica |
| `chars_saved_output` | 5 237 | 5 237 | idéntica |
| `chars_returned` | 289 554 | 289 554 | idéntica |
| `tokens_context_saved` | 873 270 (`÷ 4`) | **1 718 328** | nueva |
| `tokens_returned` | 72 342 (`÷ 4`) | **128 776** | nueva |
| `tokens_context_net` | 800 928 (`÷ 4`) | **1 589 552** | nueva (×1,98) |
| `estimated_events` | 0 | 0 | igual |

Cobertura (los cinco tramos, sobre las 121 filas de la base de coste): `excluido` **91** (todas
`pruebas`: 51 de bancos de `claude-code` y 40 de cliente `mcp`), `al_momento` 0, `por_relleno`
**30**, `pendiente` 0, `supuesto` 0. Densidad de las 30: `medida` 23, `sin_numerar` 7,
`conservadora` 0; familia `nueva` 30. `N`: `relleno` 30. Coste de septiembre: cota baja $5,41,
estimación $67,12 (`T` = 619 241); fuera de la base, 5 imágenes y 3 salidas a fichero.

Lo esperado por el plan era «casi todo `por relleno`; los días 1 y 2, sin transcript, en
`supuesto`». **No hay ninguna delegación el 1 ni el 2 de septiembre** (desglose por fecha: 0 filas
con `ts` ≤ 2026-09-02), así que el tramo `supuesto` queda en 0 con razón, no por defecto del
cálculo. Las 4 filas `ambiguo` y la de `sin_cruce` de septiembre caen fuera de la base (fallidas o
no textuales). **Pasa** (las cuatro de caracteres, idénticas).

### 5. Cifra de referencia (REQ-048)

Tablas: `insumos/scripts/precios.json` difiere del paquete solo en `claude-sonnet-4-5.admite_esfuerzo`
(`true` en el insumo; T1 lo corrigió a `false`) y `densidad.json` solo en el campo `medido_con`
(nuevo en el paquete); ningún valor de precio ni de densidad cambia. Aun así, como manda el plan, se
corrió la copia con las tablas del paquete. A la copia se le añadió una línea que imprime `T` sin
redondear (`T_tokens_exacto`); el resto, intacto.

Ventana del plan: `--desde 2026-09-06T19:13:22+00:00 --hasta 2026-10-06T19:13:22+00:00`, la misma en
`/api/stats?from=…&to=…` (`TestClient` sobre `metrics.app` del repo), justo después de relanzar el
comando.

| Magnitud | `atribucion_n.py` | `/api/stats` | |
|---|---|---|---|
| Delegaciones | 159 (156 `relleno` + 3 `supuesto`) | 159 (`por_relleno` 156, `supuesto` 3) | igual |
| `T` (tokens netos) | 1 899 016 | 1 899 016 | igual |
| Cota baja | $11,81 | $11,81 | igual |
| Estimación | $94,13 | $94,13 | igual |
| Opus 5, principal | $62,20 | $62,20 (14 casos, `high`) | igual |
| Opus 5.5, subagente | $31,93 | $31,62 + $0,21 + $0,10 = $31,93 | igual |
| Excluidas | 93 `pruebas` | 93 `pruebas` | igual |
| Densidad | `medida` 115, `sin_numerar` 44 | `medida` 115, `sin_numerar` 44 | igual |

Además, la **ventana por defecto del script** (`2026-09-06T00:00Z` a `2026-10-06T14:30Z`), la de las
cifras de la spec, en los dos:

| Cifra de la spec | Script hoy | Panel hoy | |
|---|---|---|---|
| 229 líneas de `claude-code`: 166 solas, 55 tras `path`, 7 ambiguas, 1 sin aparecer; **96,5 %** | 166 / 55 / 7 / 1; 96,5 % | — | cuadra |
| `T` = 1,84 MTok (0,91 con `chars/4`) | 1 837 820 (0,91) | 1 837 820 | cuadra |
| Cota baja $11,50, estimación $92,69 | $11,50 / $92,69 | $11,50 / $92,69 | cuadra |
| Opus 5 principal $62,20 (14 casos) | $62,20 (`N` mediana 127, 14) | $62,20 (14) | cuadra |
| Opus 5.5 subagente $30,49 (135) | $30,49 (`N` mediana 40, 135 casos) | $30,28 (135 `high`) + $0,21 (3 `sin dato`, los `supuesto`) = $30,49 | cuadra |
| Spec anterior: cota $8,28, estimación $25,84 | $8,28 / $25,84 | — | cuadra |
| Opus 5 con precio de Opus 5.5: $27,07 | $27,07 | — | cuadra |
| Insumo: $38,51 y $19,84 del supuesto viejo | $38,51 / $19,84 (159 casos) | — | cuadra |

Los «135» de la spec son los casos con `N` medido; el grupo tiene además 3 eventos `supuesto` (sin
transcript) que el panel enseña aparte como esfuerzo «sin dato». **Pasa.**

### 6. Cuota real

Comando relanzado y, al terminar, `calibracion.py --hasta 2026-10-06T19:14:06+00:00` (copia).

| Tipo | Comando: estado / motivo | Script: estado / motivo | Descartes comando | Descartes script (traducidos) | Δ$ rechazo comando / script |
|---|---|---|---|---|---|
| 5 h | `sin calibrar` / faltan 3 puntos del statusline | igual | `contaminado` 2, `fuera_de_rango` 1 | `contaminado` 2, `pct_invalido`→`fuera_de_rango` 1 | $125,71 / $125,71 |
| semanal | `sin calibrar` / faltan 3 puntos del statusline | igual | `contaminado` 1 | `contaminado` 1 | $397,68 / $397,68 |

Puntos del statusline válidos: 0 en los dos (el script ve 364 filas del registro, 1 sesión, y los
tres puntos que forma salen `contaminado`). Los dos rechazos coinciden también en inicio, fin,
`C` y marcas (`cota baja`, `solo comprobación`). Lo esperado era `sin calibrar` en los dos tipos.
**Pasa.**

### 7. Clave del relleno

`clave_relleno.py` (copia) sobre los cuatro `usage-*.jsonl` reales: 416 líneas sin `tool_use_id`,
1 con él, 0 `tool_use_id` repetidos; `(ts, tool)` 3 claves repetidas (6 líneas),
`(ts, tool, chars_in, chars_out)` 1 (2 líneas), **`(ts, tool, ordinal)` 0**. **Pasa.**

### 8. Rendimiento del panel

`/api/stats` sin rango (últimos 30 días, con la fusión, el coste y la cuota) con `TestClient`,
tres veces bajo el cerrojo de comandos pesados: **0,021 s, 0,008 s y 0,009 s** (criterio: < 2 s);
las tres con 159 eventos, $11,81 / $94,13 y cuota `sin calibrar` en los dos tipos. **Pasa.**

### Lo que T9 tiene que citar

- **Septiembre en tokens** (CHANGELOG `### Changed`): contexto conservado neto **1 589 552** tokens
  de Claude (antes 800 928 con `÷ 4`; bruto 1 718 328, devuelto 128 776). Las de caracteres no
  cambian.
- **Cifra de referencia**: en la ventana de la spec, cota baja **$11,50** y estimación **$92,69**
  (`T` = 1,84 MTok), reproducida al céntimo por el panel y por el script.
- **Comando**: 3,3 s sobre 456 transcripts, plazo 90 días; cotejo 144/144.
- La cuota sigue `sin calibrar` en los dos tipos (faltan 3 puntos del statusline).

### Desviaciones de T8

- Ninguna cifra se separa de la spec ni de los scripts.
- El tramo `supuesto` de septiembre sale 0 y no «los días 1 y 2»: esos días no hubo delegaciones.
- Se añadió la comprobación en la ventana por defecto del script (no la pedía el paso 5) para
  contrastar directamente las cifras de la spec.

## T9 — Documentación (ola 7)

Fecha: 2026-10-06. Escritor: agente de T9. MCP `local-delegate` desconectado en la sesión: 0
llamadas `local_*`. Sin commit, sin tocar `state.json` ni el daemon. Sin publicar versión.

### 1. Ficheros

| Fichero | EOL (antes = después) | Qué cambia |
|---|---|---|
| `CHANGELOG.md` | CRLF | Se **quita** la nota «No publicar versión hasta mezclar `coste-api-y-cuota`». `### Added` nuevo: equivalente a precio de API (con la nota de tarifa plana, supuestos y la cifra de referencia $11,50 / $92,69 con `T` = 1,84 MTok), bloque de cuota «sin calibrar», bloque «Imágenes», `recalcular-coste` (3,3 s, 456 transcripts), check `config.coste` (22 checks), hook `anotar_llamada.py`, vigilante semanal. `### Changed`: «Contexto conservado» en tokens de Claude por densidad (septiembre 800 928 → 1 589 552; caracteres sin cambio); la entrada del neto del hermano se ajusta para decir que su 800 928 era con `÷ 4` |
| `README.md` | CRLF | Línea 30 sin «cuota que no gastaste»; línea 118 sin «ahorro real de cuota»; «La métrica de ahorro» explica la densidad, las imágenes fuera del neto, el equivalente a precio de API («no es dinero que hayas ahorrado»), la cuota sin calibrar y `recalcular-coste`; fila `LOCAL_DELEGATE_COSTE_RESPALDO`; hooks: `anotar_llamada.py` se instala siempre |
| `docs/wiki/Savings-and-metrics.md` | LF | Campos nuevos del log (`tool_use_id`, `caller_*`); tabla de ejemplo de septiembre con `÷ 4` y por densidad; secciones nuevas: «De caracteres a tokens de Claude» (tabla, familias, clase, columna, respaldo de celda), «Coste equivalente a precio de API» (fórmula, contrafactual, relecturas, cobertura y respaldo, `N` y su origen, lo que enseña el bloque, cifra de referencia, tabla de precios y cotejo), «Cuota» (puntos, rechazos, criterio, deriva, reinicio), «Imágenes» y «`local-delegate recalcular-coste`» (qué escribe, privacidad, cuándo lanzarlo: `H` − 10 días); APIs con `coste`, `cuota`, `imagenes`, `densidad_tabla` y filas fundidas |
| `docs/wiki/Configuration.md` | LF | Sección «Coste equivalente»: `LOCAL_DELEGATE_COSTE_RESPALDO` y que el plazo sale de `cleanupPeriodDays` |
| `docs/wiki/Troubleshooting.md` | LF | `[WARN] coste y relleno` (sus dos motivos y el `unknown`) y «El bloque de cuota dice sin calibrar» |
| `docs/wiki/Repo-hardening.md` | LF | Fila del workflow y sección «Vigilante de precios y límites»: jobs, fallo en voz alta, permisos y por qué, commits firmados por la API, la salida de REQ-025 (cerrar y reabrir a mano) y el ensayo |
| `docs/wiki/Integration-install.md` | CRLF | Fila «Hooks» (zona T9): `anotar_llamada.py` siempre, qué hace. La fila del doctor ya la dejó T7 |
| `docs/recipes/claude-code-hooks.md` | LF | Sección del hook nuevo y «por defecto quedan registrados dos» |
| `docs/recipes/claude-code-integration.md` | LF | Fuera de la lista del plan: decía «ahorro real de cuota», se reescribe |
| `scripts/dev/capture_dashboard.py` | LF | Mock: eventos con `familia` y `densidad` (valores de la tabla del paquete, leída del fichero); KPIs por densidad e imágenes fuera del neto; `/api/stats` con `coste` y `cuota` (salidos de correr `bloque_coste` y `cuota.estado` reales sobre un log sintético), `imagenes` derivado de los eventos y `densidad_tabla` del paquete |

`Architecture.md` no lista los hooks: sin cambio.

### 2. Verificación

- `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_wiki.py tests/test_captura.py tests/test_release_metadata.py -q`: **24 passed**.
- `uv run ruff check .`: limpio. `uv run ruff format --check .`: 151 ficheros ya formateados.
- Suite completa, `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q`: **1739 passed, 2 skipped**.
- `git ls-files --eol` de los diez ficheros: igual que antes (CRLF los tres de arriba, LF el resto).
- Frases prohibidas (REQ-045) en README, CHANGELOG y `docs/`: `grep` sin coincidencias, salvo la
  negación «no es dinero que hayas ahorrado» y las entradas de versiones ya publicadas.
- La nota del panel ya no está en `[Unreleased]`.
- **Captura de control, no la del README**: con la app de métricas del repo en el 9494 y
  `capture_dashboard.py --out` al scratchpad (bajo el cerrojo), el panel pinta los tres bloques
  nuevos con los datos de ejemplo («Equivalente estimado a precio de API: entre $6,87 y ~$27,40»,
  cuota «sin calibrar» en los dos tipos, 25 imágenes) y 6 gráficos. `docs/assets/` no se tocó: la
  imagen del README se regenera al publicar versión (`test_captura.py` lo exige con el bump).

### Desviaciones de T9

- Se tocó `docs/recipes/claude-code-integration.md`, fuera de la lista del plan, por la frase
  «ahorro real de cuota».
- El pie de la captura del README (`README.md:22`) no se cambió: describe la imagen actual, que no
  se regenera hasta la release.

## T10 — Verificación final, con el daemon y el panel en vivo (ola 8)

Fecha: 2026-10-06, de 19:20Z a 19:36Z. Escritor: agente de T10, sobre `09a9182`. MCP
`local-delegate` desconectado en la sesión del agente: 0 llamadas `local_*` (las delegaciones de
prueba van por `claude -p`, que es otra sesión). Sin commit y sin tocar `state.json` ni el lanzador.

### 1. Lint, formato, suite y JS

- `uv run ruff check .`: limpio. `uv run ruff format --check .`: 151 ficheros ya formateados.
- `bash ~/.claude/scripts/pesado.sh uv run --group ui pytest -q`: **1739 passed, 2 skipped** en
  60 s (igual que T9).
- `node --check` del único `<script>` de `metrics.HTML` (67 017 bytes, extraído al scratchpad):
  sin errores.

### 2. Instalación real

Daemon parado (`schtasks /End` y `Stop-Process` de los dos `pythonw.exe -m local_delegate serve`)
a las **19:29:11Z**; `bash ~/.claude/scripts/pesado.sh uv tool install --force --reinstall
--no-cache ".[llamaswap]"` (19:29:26Z) y `local-delegate install --mcp-mode http --web-token-env
--enable-read-hook --agents`. El instalador levantó el daemon por la tarea programada (0.32.0,
pid nuevo, arriba a las 19:29:39Z), así que no hizo falta `schtasks /Run`. El paquete instalado trae
`coste.py`, `cuota.py`, `valoracion.py` y `recalcular.py`.

`local-delegate doctor` en consola: **22 checks, los 22 en `OK`**, «Resultado: todo a punto».
`hooks copiados` 5 scripts, `hooks huérfanos` ninguno, `hooks registrados` 5 con
`PreToolUse/mcp__local-delegate__.*` (el hook `anotar_llamada.py`) entre ellos. **Pasa.**

### 3. Atribución de verdad

`claude -p --model claude-haiku-4-5-20251001` desde un directorio vacío del scratchpad
(19:30:18Z – 19:30:50Z): el principal lanza un subagente `general-purpose` con `model: sonnet`, que
hace tres `local_summarize` con `path` a tres ficheros de cuatro líneas. Últimas líneas del log
(`usage-202610.jsonl`, sin `path` y con el id recortado):

| ts | tool_use_id | caller_kind | caller_src | caller_model | caller_effort | caller_agent_type |
|---|---|---|---|---|---|---|
| 19:30:33Z | `toolu_…` | subagent | hook+transcript | claude-sonnet-5-5 | medium | general-purpose |
| 19:30:37Z | `toolu_…` | subagent | hook+transcript | claude-sonnet-5-5 | medium | general-purpose |
| 19:30:39Z | `toolu_…` | subagent | hook+transcript | claude-sonnet-5-5 | medium | general-purpose |

Las tres traen `tool_use_id`, las tres `caller_*` y las tres `hook+transcript` (el criterio pedía dos
de tres). El transcript del subagente (`subagents/agent-….jsonl`) dice `model: claude-sonnet-5-5` y
`effort: medium` en sus cuatro mensajes: el modelo y el esfuerzo del log son los del subagente, no
los del principal (Haiku 4.5, `n/a`), así que el dato discrimina. **Pasa.** Estas llamadas marcan la
ventana de 5 h en curso como `contaminado` (REQ-052, paso 6).

### 4. Mensajes

- Coletilla de las tres `local_summarize`: «(leído server-side: 123 chars ≈ 61 tokens de Claude que
  no entraron a tu contexto)».
- `local_describe_image` (otra sesión `claude -p`, 19:31:10Z – 19:31:33Z, la imagen
  `docs/assets/dashboard.png` copiada al scratchpad): «(leído server-side: 710,204 bytes imagen que
  no entraron a tu contexto)», sin tokens. Su línea trae `caller_src: hook+transcript`,
  `input_unit: bytes`. **Pasa.**

### 5. `doctor`

`config.coste` («coste y relleno») en **`ok`**: «el último cotejo (2026-10-06T19:14:04+00:00)
cuadra: 144 fila(s) juzgadas con la tabla de precios del 2026-10-06». **Pasa.**

### 6. Panel en vivo

El 9393 responde 401 sin token (el daemon está vivo). Por la vía del plan, una copia sin token en el
**9494** con el código **instalado** (`<uv tools>/local-delegate-mcp/Scripts/python.exe -I -m uvicorn
local_delegate.web.metrics:app`), mismo `LOG_DIR` (el lanzador no define variables que cambien el
coste: solo credenciales, token del panel y `RESUMEN_ESTRUCTURADO`). Playwright bajo `pesado.sh`
(`scratchpad/t10_panel.py`), que guarda la petición exacta que hizo el panel y la vuelve a pedir en
el mismo momento. Rango por defecto del panel: hoy (`from=2026-10-06T03:00Z`).

- **Coste**: «Equivalente estimado a precio de API: entre $0,76 y ~$2,45» (`0 < X ≤ Y`), con «No es
  dinero que hayas ahorrado: tu suscripción es de tarifa plana.», cota baja explicada, cobertura,
  relecturas `N` (17 del relleno, 3 declarado: principal 127, subagente 40), densidad por familia,
  fuera de la cifra (1 imagen, 0 salidas a fichero), contrafactual y fecha de la tabla: el bloque de
  supuestos está entero.
- **Barra de cobertura**: 3 al momento · 17 por relleno · 0 pendientes · 0 supuestas = **20** =
  casos del desglose (15 + 2 + 3) = `valoradas`; 2 excluidas (pruebas). Nombra el respaldo: «0 de 20
  con modelo supuesto: Opus 5.5 en subagente».
- **Cuota**: cabecera `sin calibrar`; 5 h y semanal «sin calibrar (faltan 3 puntos del
  statusline)», con descartes (5 h: `contaminado` 2, `fuera_de_rango` 1; semanal: `contaminado` 1).
  Ningún `%` en el bloque.
- **Imágenes**: «1 imagen · 710.204 bytes leídos server-side · 289 caracteres devueltos a Claude»,
  sin tokens de Claude.
- **Frases prohibidas** (las seis de REQ-045 y «% de una ventana») en el texto y en el HTML de la
  página: ninguna.
- **Cifras contra `/api/stats`**: la respuesta que pintó el panel y la pedida otra vez en el mismo
  momento son iguales en `coste`, `cuota`, `imagenes` y los tres campos de tokens; las cifras
  pintadas coinciden con ellas.
- **«Contexto conservado» usa la densidad nueva**: KPI 163 871 tok (bruto 183 613 − devuelto
  19 742); con `÷ 4` el bruto sería 91 918. En los últimos 30 días, bruto 3 097 807 frente a
  1 560 963 con `÷ 4`. La tabla `densidad_tabla` que sirve la API es la del paquete (2026-10-06).
- **`local_status` coincide con el panel** (otra sesión `claude -p`, 19:33:38Z – 19:33:51Z):
  «eventos: 143 (201 llamadas al backend) — contexto conservado: ~1292708 tokens netos (bruto
  ~1379479)»; `/api/stats?from=2026-10-01T00:00:00Z` da 143 llamadas, bruto 1 379 479 y neto
  1 292 708.
- `/api/stats` de los últimos 30 días: entre $11,81 y ~$94,13, 162 eventos (los 159 de T8 más los
  tres de este paso), cuota `sin calibrar` en los dos tipos, 7 imágenes.

**Resultado: pasa, con una observación.** La fila «Sonnet 5.5 · subagente · medium · 3 casos» del
desglose tiene `T` = −404 (los tres ficheros de prueba eran tan cortos que la respuesta pesó más que
la entrada) y pinta **«$0,00 $0,00»** (la API da `-0.0`). La spec admite el `T` negativo
(«Un `T` negativo resta») y sus «nunca $0» se refieren al modelo sin precio y al periodo sin
delegaciones, así que no es ese defecto; pero la letra del criterio de fallo («aparece "$0"») lo
atrapa. Queda para la sesión principal decidir si se acepta o si una fila con importe redondeado a
cero (o negativo) debe pintarse distinto (por ejemplo «−$0,00» o «< $0,01»). Captura en
`scratchpad/t10-panel.png`.

### 7. Daemon a la versión publicada: no se hace

Por instrucción de la sesión principal, el daemon queda **corriendo con esta rama** (0.32.0 de
`feat/coste-api-y-cuota`, `doctor` 22/22 en `OK`). La copia del 9494 se paró.

### 8. Seguridad y privacidad del diff `main...HEAD`

- `gitleaks git --log-opts="main..HEAD"`: 8 commits, **sin fugas**.
- Rutas personales en las líneas añadidas: ninguna (`C--Users-x-…` en dos tests es sintético; las
  menciones del usuario en `CHANGELOG.md`, `install.py` y `test_install.py` ya estaban en `main`).
- IPs: `192.0.2.1` (red de documentación, en un test de «no abre sockets» y en `evidencias/T6.md`);
  las otras dos coincidencias son coordenadas de un SVG del fixture.
- Validación del `transcript_path` (`atribucion.py:_ruta_segura`): se resuelve la ruta y se exige
  `.jsonl` dentro de `~/.claude/projects`, también para el `agent-<id>.jsonl` del subagente; el
  nombre de la nota pasa antes por `PATRON_TOOL_USE_ID`. Correcto.
- **Hallazgos para la sesión principal** (no se tocaron):
  1. `tests/fixtures/vigilante/precios.html` guarda identificadores de visitante de la página
     descargada: `anonymousId`, `stableId` y un `_setSessionId` con UUID. No son de Claude Code ni
     del usuario, pero son un id de sesión de quien bajó la página; conviene sustituirlos por un
     valor fijo (el resto de UUID del fichero son configuración pública del sitio).
  2. Este mismo `verification.md` (sección I2, 4) guarda tres `tool_use_id` reales completos de las
     sesiones de prueba. No son tokens ni ids de sesión, pero T8.2 trata `toolu_` como patrón
     privado; se pueden recortar como en esta sección.

**Ventana a excluir de las mediciones de adopción:** **2026-10-06T19:29:11Z – 19:33:51Z**
(reinstalación del daemon y las tres sesiones `claude -p`: subagente con tres `local_summarize`, una
`local_describe_image` y una `local_status`). Hooks reinstalados a las 19:29Z con los mismos cinco
scripts que el tramo abierto en I2 (18:15Z).

### Desviaciones de T10

- Paso 7 no se hizo: el daemon queda con la rama por instrucción de la sesión principal.
- El panel se leyó en una copia sin token en el 9494 (la vía del plan), no en el 9393.
- Paso 8: la revisión `personal-sdd-review` completa contra la spec no se corrió aquí; se hizo la
  revisión de seguridad y privacidad del diff.

### Arreglos tras T10

Fecha: 2026-10-06. Sin commit; `git add` hecho. MCP `local-delegate` desconectado: 0 llamadas `local_*`.

1. **Fila del desglose con `T` ≤ 0.** Decisión de la sesión principal: la fila dice «sin ahorro» en
   vez de dos importes, y la API no devuelve un cero con signo. La fórmula no cambia (un `T` negativo
   sigue restando en el total). `valoracion._dinero` suma `0.0` tras redondear (`-0.0` → `0.0`; un
   negativo de verdad sigue negativo). En `web/metrics.py` (CRLF conservado) la función pura nueva
   `celdasCoste(g)` pinta las dos celdas en dólares, o una sola de dos columnas con «sin ahorro» si
   `T` ≤ 0; `renderCoste` la usa. Tests: `test_valoracion::test_un_negativo_diminuto_no_es_un_cero_con_signo`
   (`T` = −174; con `_dinero` sin el `+ 0.0` falla en `assert "-0.0" not in salida`, también en la
   cifra del periodo) y `test_panel_coste::test_una_fila_sin_ahorro_no_pinta_dolares` (node sobre las
   filas reales de `/api/stats`; con el mutante `if(false)` falla en `assert "sin ahorro" in sin`
   frente a `$0,00 $0,00`).
2. **Privacidad de `tests/fixtures/vigilante/`.** Script reproducible e idempotente
   `scripts/limpiar_fixtures_vigilante.py` (escribe en bytes: LF conservado). Sustituye en
   `precios.html` el `anonymousId`/`stableId` y el `_setSessionId` (UUID cero), el `nonce` de la CSP
   (`nonce-neutro`) y `data-consent-ip-country` (`ZZ`, solo en su atributo); en `limites.html`, su
   `nonce`. Los demás UUID son configuración pública del sitio y se dejan; no hay cookies ni tokens
   de la visita. La extracción da lo mismo antes y después: `extraer_tabla_precios` (JSON idéntico
   byte a byte) y `extraer_texto_limites` (idéntico). Guardián:
   `test_vigilante::test_las_copias_no_guardan_datos_de_la_visita`, con control positivo sobre las
   cuatro formas de la descarga.
3. **`toolu_` de la sección I2 recortados** a `toolu_01WA…` y `toolu_01NT…` (tres apariciones); no
   queda ningún `toolu_` completo en el repo.

Verificación: `ruff check` y `ruff format --check` limpios; suite completa con el cerrojo
`pesado.sh`: **1742 passed, 2 skipped**.

### Arreglos tras la conformidad

Fecha: 2026-10-06. Sin commit; `git add` hecho. MCP `local-delegate` desconectado: 0 llamadas `local_*`.

1. **Shebang sin bit de ejecución.** `scripts/limpiar_fixtures_vigilante.py` pasa a 100755 con
   `git update-index --chmod=+x`, como el resto de scripts de `scripts/` con shebang.
   `test_wiki::test_un_script_con_shebang_esta_marcado_ejecutable_en_git` pasa.
2. **Datos de la visita.** El limpiador ya no mira formas concretas: por cada clave vigilada
   (`anonymousId`, `stableId`, `_setSessionId`/`sessionId`, `nonce`, y cualquier `…ip-country`,
   `ipCountry`, `ip_country`) acepta comillas simples o dobles, escapadas o no, u omitidas; con o
   sin espacios; separador `:`, `=` o `,` (atributo, JSON, JSON escapado, argumento de llamada), y
   cualquier valor distinto del neutro. Ejecutado sobre las dos páginas: `precios.html` cambia
   `\"ipCountry\":\"UY\"` por `ZZ` (1 valor); `limites.html`, 0; una segunda pasada, 0 y 0
   (idempotente). El guardián ya no lleva valores reales: `test_las_copias_no_guardan_datos_de_la_visita`
   solo comprueba las dos copias del repo; el control positivo
   (`test_el_guardian_detecta_datos_sinteticos_sembrados_en_una_copia`) siembra en una copia
   temporal de cada página nueve valores SINTÉTICOS (UUID y `nonce` generados en cada ejecución,
   países de uso privado `QM`/`XA`/`QN`) en las formas citadas, comprueba que `restos()` los ve
   todos, que `main()` los quita y que fuera de la siembra la página queda igual byte a byte; y
   `test_el_guardian_no_depende_de_valores_concretos` comprueba que el neutro no sale y un UUID
   cualquiera sí. Grep en todo el árbol (sin `.git`/`.venv`) de los dos ids de la descarga (sus ocho primeros caracteres y sus otros
   tramos) y de los dos `nonce` de la descarga: vacío. Las tres menciones de los prefijos en `review.md`
   se cambiaron por «(id omitido)». Los únicos UUID que la descarga original (`8ad8309`) tenía y hoy
   no están son esos dos. **Queda en el historial**: `8ad8309` (fixture) y `a6bced7` (test) aún los
   contienen; quitarlos exige reescribir la rama, decisión que no toma este arreglo.
3. **Punto mal formado en `coste-agregados.json`.** `cuota.bien_formado` y
   `cuota.separar_mal_formados`: un punto sin `fuente`/`tipo` válidos, con `inicio`/`fin` ilegibles,
   o con `delta_pct`/`C` no numéricos (o `C` ≤ 0 en el statusline, que divide en la dispersión) se
   salta y cuenta como `linea_corrupta` en su tipo, o en los dos si el tipo no se lee (la convención
   de `sanear`, T5). Lo usan `cuota.estado` (panel) y `recalcular._puntos` (puntos previos del
   comando); `estado` también tolera `descartes` que no sea un dict. Tests nuevos, los dos fallan con
   el código anterior: `test_panel_coste::test_un_punto_mal_formado_se_descarta_sin_tumbar_la_respuesta`
   (antes: `assert 500 == 200`) y `test_cuota::test_un_punto_previo_mal_formado_no_rompe_el_comando`
   (antes: `KeyError: 'delta_pct'` en `quitar_solapados`).
4. **Menores.** «veintiún» → «veintiuno» en el comentario de `checks.run_all`; el guardián
   `test_checks::test_el_docstring_dice_cuantos_checks_hay_de_verdad` exigía la forma apocopada
   también sin sustantivo detrás, así que se le añade `_NUMERO_SIN_SUSTANTIVO` para esa frase.
5. **Aviso de `doctor` con fallidas e imágenes: no se toca.** REQ-075 dice literalmente «al menos
   una delegación `pendiente` (REQ-007)», y `coste.tramo` da `pendiente` también a fallidas e
   imágenes: el código cumple la letra de la spec. Excluirlas cambiaría la regla; queda anotado
   para decidir en la spec.

Verificación: `ruff check` y `ruff format --check` limpios; `gitleaks dir` solo señala ficheros de
`.venv` (ninguno del repo) y `gitleaks git` sobre `main..HEAD`, sin fugas; suite completa con el
cerrojo `pesado.sh`: **1746 passed, 2 skipped**.

## T11 — Ensayo real del vigilante en GitHub (tras mezclar #232)

Fecha: 2026-10-06, ~20:11 UTC. `main` en `8c2ff9b`. Prerrequisito cumplido: el usuario activó
«Allow GitHub Actions to create and approve pull requests»; permisos por defecto de los workflows
en `read`. 0 llamadas `local_*`: el MCP `local-delegate` estaba desconectado.

### Primer intento: el ensayo no puede correr el mismo día en que se tocó la tabla

- Lanzado con `gh workflow run vigilante-precios.yml -f ensayo=true` →
  run [37524585928](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/37524585928)
  (primera ejecución del workflow en el repo).
- **Job `limites`: verde**, `Límites: sin cambios.` Descargó y extrajo el artículo desde el runner
  de GitHub sin error: el `User-Agent` también funciona desde fuera de esta PC. No abrió PR ni issue
  (con cambios abriría un PR, `cuerpo_pr_limites`; no hay rama de aviso por issue).
- **Job `precios`: rojo** en 1 s, con `FALLO: el ensayo no produce diff: \`consultado\` ya es hoy`
  (`scripts/vigilante_precios.py:742`). La descarga y la extracción de la tabla pasaron (el fallo
  es posterior a `comparar`, y no hubo ningún `AVISO` de modelos desaparecidos).
- **Causa:** el diff forzado del ensayo es `consultado = hoy` (UTC), y `precios.json` del paquete
  ya tiene `"consultado": "2026-10-06"`, la fecha de hoy, porque la tabla se midió y se mezcló hoy.
  El guardia que evita un PR vacío funciona como se diseñó; lo que falla es la elección del diff
  inocuo: **el ensayo no sirve el día en que se actualizó la tabla**. Defecto menor de diseño de
  T3 (ningún test lo cubría: los tests del ensayo usan un `hoy` distinto de `consultado`).
- **Sin restos:** no se creó la rama `vigilante/ensayo` (`gh api .../branches/vigilante%2Fensayo`
  → 404) ni ningún PR.

### Lo que queda sin comprobar

Nada de REQ-025 llegó a ejercitarse: ni el PR «[ensayo]», ni la firma de los commits del bot, ni
el lanzamiento de `ci.yml`/`codeql.yml` por `workflow_dispatch`, ni los seis checks del ruleset, ni
la regla `code_scanning`, ni el comentario de PR bloqueado. **La incógnita [I] sigue abierta.**

### Cómo seguir (sin tocar `main`, el ruleset ni los permisos)

- **Opción A (sin código):** relanzar el mismo comando a partir de las 00:00 UTC del 2026-10-07
  (20:00 en Cuba). Entonces `consultado` ≠ hoy y el diff existe.
- **Opción B (arreglo pequeño, por PR):** que el ensayo fuerce un diff que no dependa de la fecha
  (por ejemplo, otro valor de marca si `consultado` ya es hoy), con un test donde `hoy ==
  consultado`. Evita que el ensayo vuelva a quedar inútil tras cada actualización de la tabla.

Estado de T11: **no concluyente, bloqueada por el defecto del ensayo**; se repite con la opción A
o tras la B. La ejecución programada (lunes 07:17 UTC) no se ve afectada: sin `ensayo`, solo abre
PR si la página cambia.

**Opción B aplicada** (rama `fix/vigilante-ensayo`): el ensayo ya no toca `consultado`; añade una
marca `_ensayo` con el id del run (`GITHUB_RUN_ID`), que cambia en cada ejecución. Test
`test_el_ensayo_tiene_diff_aunque_consultado_ya_sea_hoy` con la tabla real del paquete y
`hoy == consultado`: falla con el código de `main` (`assert 1 == 0`) y con los mutantes «vuelve a
forzar `consultado`» y «la marca sin id del run». T11 se repite tras mezclar ese PR.

### Segundo intento (2026-10-06, ~20:28 UTC, `main` en `de3aa56`, tras mezclar #233)

- Run del vigilante
  [37526624930](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/37526624930):
  `limites` verde («sin cambios»); `precios` abrió el PR
  [#234](https://github.com/ZahiriNatZuke/local-delegate/pull/234) «[ensayo]» (rama
  `vigilante/ensayo`, solo `precios.json` con `"_ensayo": "PR de prueba del vigilante (run
  37526624930): no mezclar"`), esperó a los checks y salió en rojo con
  `FALLO: checks del PR sin éxito: {'ci.yml': 'failure'}`.
- **Firma: cumple.** El único commit (`59bc397`, autor `github-actions[bot]`, committer `GitHub`)
  sale `verified: true`, `reason: valid`.
- **Lanzamiento por `workflow_dispatch`: cumple.** `ci.yml`
  ([37526655426](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/37526655426)) y
  `codeql.yml` ([37526658419](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/37526658419))
  corrieron sobre `vigilante/ensayo` con evento `workflow_dispatch`, y sus check-runs quedaron en
  el `head_sha`. Los runs `pull_request` del bot quedaron en `action_required` (0 s): GitHub los
  retiene, como se esperaba; por eso existe el relanzamiento.
- **CodeQL y code scanning: verdes.** `Analyze (python)` success; el check `CodeQL`
  (`github-advanced-security`, el resultado de code scanning) success y visible en
  `gh pr checks 234`.
- **CI: rojo por un defecto nuevo de #233, no del entorno.** `lint`, `secrets` e `install-smoke`
  verdes; los tres `test` y por tanto `ci-gate` en rojo, con un solo fallo:
  `test_el_ensayo_tiene_diff_aunque_consultado_ya_sea_hoy` (`assert 1 == 0`, «la tabla propuesta
  es idéntica a la del paquete»). Causa: el test lee el `precios.json` **del checkout**, y en la
  rama de ensayo ese fichero ya trae `_ensayo`; en `scripts/vigilante_precios.py:748`,
  `{CLAVE_ENSAYO: marca_de_ensayo(id_run), **copy.deepcopy(paquete)}` deja que la marca vieja del
  paquete pise a la nueva, así que no hay diff. Consecuencia: **un PR de ensayo nunca puede tener
  el CI en verde**. Arreglo pequeño (por PR, no hecho aquí): que la marca nueva gane
  (`{**paquete, CLAVE_ENSAYO: marca}` o quitar `_ensayo` del paquete antes) y que el test no
  dependa de que la tabla real esté limpia (o que la limpie él). La ejecución programada no se ve
  afectada: sin `ensayo` no toca `_ensayo`.
- **`gh pr checks` y `statusCheckRollup` NO enseñan los checks del `workflow_dispatch`**: solo
  `CodeQL`, GitGuardian y los dos de Socket. Los seis checks del ruleset existen en el commit
  (`gh api .../commits/<sha>/check-runs`), pero no se ven asociados al PR. Si el ruleset los cuenta
  o no, no se pudo distinguir en este ensayo porque tres de ellos estaban en rojo.
- **`mergeStateStatus`: `BLOCKED`** (`mergeable: MERGEABLE`, `reviewDecision` vacío). Explicado de
  sobra por el CI rojo; **no es el caso «todo verde y bloqueado»** que prevé la spec, así que la
  regla `code_scanning` no se puede dar por cumplida ni por incumplida con esta evidencia (el
  indicio es favorable: su check está presente y en verde).
- **Comentario de REQ-025: no se ejercitó.** El vigilante abortó por el CI rojo antes de la rama
  «checks verdes y PR bloqueado»; el PR no tiene comentarios del bot.
- **Limpieza:** PR #234 cerrado sin mezclar y rama `vigilante/ensayo` borrada (`.../branches/
  vigilante%2Fensayo` → 404).

Estado de T11: **no concluyente otra vez**. Firma y relanzamiento por `workflow_dispatch`
comprobados en real; la incógnita [I] (`code_scanning` y si el ruleset acepta los checks del
`workflow_dispatch`) y el comentario de bloqueo siguen abiertos. Se repite tras arreglar la marca
de ensayo.

Arreglo (rama `fix/vigilante-marca-ensayo`): la marca nueva gana siempre (se descarta la `_ensayo`
que ya traiga el paquete) y los tests de `test_vigilante.py` que leen la tabla real trabajan
sobre una copia sin marcas de ensayo, así que dan lo mismo en `main` que en `vigilante/ensayo`.
Test nuevo `test_el_ensayo_pisa_la_marca_que_ya_trae_la_tabla`: falla con el código de #233
(mutante «la marca del paquete pisa a la nueva» → `assert 1 == 0` en `codigo == 0`).
`test_precios.py` gana `test_una_marca_de_ensayo_en_la_tabla_no_cambia_nada`. Comprobado en
local con `_ensayo` sembrado en `precios.json`: `test_vigilante.py` y `test_precios.py` en verde.

### Tercer intento (2026-10-06, ~20:48 UTC, `main` en `250be89`, tras mezclar #235)

0 llamadas `local_*`: el MCP `local-delegate` estaba desconectado.

- Run del vigilante
  [37529183674](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/37529183674): los dos
  jobs en verde. `limites` («sin cambios»); `precios` abrió el PR
  [#236](https://github.com/ZahiriNatZuke/local-delegate/pull/236) «[ensayo]» (rama
  `vigilante/ensayo`, head `4f15075`), esperó a los checks y escribió
  `Checks en verde; estado del PR: blocked`.
- **Firma: cumple.** Único commit `4f15075`, autor `github-actions[bot]`, committer `GitHub`,
  `verified: true`, `reason: valid`.
- **`workflow_dispatch`: cumple, y todo en verde.** `CI`
  ([37529208728](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/37529208728)) y
  `CodeQL` ([37529210917](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/37529210917))
  con evento `workflow_dispatch`, `success`. En el `head_sha`: `test` ×3, `ci-gate`, `lint`,
  `secrets`, `install-smoke` y `Analyze (python)` en `success`; también `CodeQL` (code scanning),
  GitGuardian y los dos de Socket. Los tres runs `pull_request` del bot (`CI`, `CodeQL`,
  `Vendor audit`) quedaron en `action_required`, como en el segundo intento.
- **`mergeStateStatus`: `BLOCKED`** con todo en verde (`mergeable: MERGEABLE`, `reviewDecision`
  vacío, `viewerCanMergeAsAdmin: false`). Es el caso «todo verde y bloqueado» que prevé la spec.
- **Qué ve GitHub de los checks del `workflow_dispatch`:**
  - Por REST, sus check-runs están en el `head_sha` y llevan `pull_requests: [236]`; sus check
    suites también.
  - Por GraphQL, `isRequired(pullRequestNumber: 236)` da `true` para los seis del ruleset
    (`ci-gate`, `lint`, `test (ubuntu-latest)`, `test (macos-latest)`, `secrets`,
    `Analyze (python)`): el nombre casa y las reglas no fijan app (`required_status_checks` sin
    `integration_id`).
  - Pero **`statusCheckRollup` los excluye**, tanto el del PR como el del commit: solo trae
    `CodeQL`, GitGuardian y Socket. `gh pr checks 236` igual. El rollup es lo que usa la caja de
    mezcla, así que lo más probable es que **el ruleset no cuente los checks lanzados por
    `workflow_dispatch`** y espere los de los runs `pull_request` retenidos.
  - No se pudo aislar del todo la causa sin intentar mezclar (prohibido en el encargo): además de los
    checks requeridos, puede pesar `require_extra_approval_for_unattributed_changes` (regla
    `pull_request` activa; el commit es del bot). `code_scanning`, en cambio, tiene su check
    `CodeQL` presente y en verde: no parece ser la causa. La API de mezcla no da el motivo
    (`mergeRequirements` no existe en el esquema GraphQL).
- **Comentario de REQ-025: cumple.** `github-actions[bot]` comentó en #236: «El vigilante no puede
  dejar este PR listo para mezclar… cierra el PR y reábrelo». La rama «checks verdes y PR
  bloqueado» del código queda probada en real.
- **Limpieza:** PR #236 cerrado sin mezclar y rama `vigilante/ensayo` borrada
  (`.../branches/vigilante%2Fensayo` → 404). Nada tocado del ruleset, permisos ni secretos.

Estado de T11: **concluyente por la rama de «Fallo» del plan**: firma, relanzamiento, checks en
verde y comentario comprobados en real; el PR queda `BLOCKED`. Según el plan, REQ-025 se anota en
`conformance` como «salida alternativa en uso» hasta que el usuario decida (la release no espera).

**Decisión del usuario pendiente** (la que deja abierta la spec):

1. *Cerrar y reabrir a mano cada PR del vigilante.* Pro: cero configuración y cero secretos; el PR
   es raro (solo cuando cambian precios). Contra: trabajo manual cada vez; y si lo que bloquea es
   `require_extra_approval_for_unattributed_changes`, la reapertura dispara el CI normal pero
   puede seguir haciendo falta una aprobación o un commit atribuido a una persona — no está
   comprobado que baste.
2. *Token de una GitHub App guardado como secreto.* Pro: los PR y commits salen a nombre de la App,
   los workflows de `pull_request` corren solos y el circuito queda automático. Contra: crear e
   instalar la App, guardar su clave privada como secreto (superficie nueva que vigilar), y cambiar
   el workflow; tampoco garantiza por sí sola que la regla de «cambios no atribuidos» quede
   satisfecha.
3. *Tercera vía razonable:* un token personal de grano fino del usuario (solo `contents` y
   `pull_requests` sobre este repo) como secreto. Más simple que la App y los commits salen
   atribuidos a una persona, pero caduca, depende de su cuenta y actúa con su identidad. Otra,
   descartada aquí porque toca el ruleset: añadir a GitHub Actions a la lista de bypass.

### Cerrar y reabrir (2026-10-06, ~21:25 UTC, `main` en `250be89`): prueba de la salida 1

El usuario eligió la salida 1. 0 llamadas `local_*`: el MCP `local-delegate` estaba desconectado.

- Run del vigilante
  [37533813652](https://github.com/ZahiriNatZuke/local-delegate/actions/runs/37533813652) en
  modo ensayo: `limites` y `precios` en verde; abrió el PR
  [#237](https://github.com/ZahiriNatZuke/local-delegate/pull/237) (rama `vigilante/ensayo`, head
  `c079b2b`). Igual que en el tercer intento: `CI` y `CodeQL` por `workflow_dispatch` en
  `success`, los tres runs `pull_request` del bot en `action_required`, el PR `BLOCKED` y el
  comentario de REQ-025 publicado.
- **Paso manual único:** `gh pr close 237` y `gh pr reopen 237` con la cuenta del usuario.
- **(a) Los workflows de `pull_request` se lanzan solos, sin aprobación.** El reopen creó `CI`
  (37534363325), `CodeQL` (37534363233) y `Vendor audit` (37534363282) con `actor` y
  `triggering_actor` = `ZahiriNatZuke`; arrancaron en `in_progress`, no en `action_required`. **No
  hizo falta aprobar runs por API.** Los tres runs retenidos del bot pasaron a `failure` en la API
  REST (los deja de lado GitHub; no afectan al rollup).
- **(b) Resultado: `mergeStateStatus: CLEAN`, `mergeable: MERGEABLE`.** `statusCheckRollup` ya
  trae los checks de los runs `pull_request`: `lint`, `test` ×3, `install-smoke`, `secrets`,
  `ci-gate`, `Analyze (python)`, `audit`, más `CodeQL`, GitGuardian y los dos de Socket, todos
  `SUCCESS`. `gh pr checks 237`: todo `pass`. GraphQL: `CLEAN`, `reviewDecision: null`,
  `viewerCanMergeAsAdmin: false` (o sea, no es un bypass de administrador).
- **(c) La causa del `BLOCKED` anterior queda aislada:** eran los checks requeridos ausentes del
  rollup, no `require_extra_approval_for_unattributed_changes`. La regla sigue activa en el
  ruleset (`required_approving_review_count: 0`, `required_review_thread_resolution: true`) y,
  tras el reopen, no impide el `CLEAN`: el commit del bot firmado y verificado no la dispara, o la
  satisface el reopen del usuario. No se intentó mezclar (prohibido), así que la prueba llega hasta
  `CLEAN`, no hasta el botón.
- **Limpieza:** PR #237 cerrado sin mezclar y rama `vigilante/ensayo` borrada (`Branch not
  found`). Nada tocado del ruleset, permisos ni secretos.

Estado: **la salida 1 basta.** El paso manual por cada PR del vigilante es cerrar y reabrir; los
checks normales corren solos y el PR queda `CLEAN`. Si hubiera hilos de revisión abiertos (p. ej.
de CodeQL), `required_review_thread_resolution` exigiría resolverlos aparte; en el ensayo no hubo.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-025 | Ruleset leído por `gh api` (T0, paso 5) | coincide | sección T0 |
| REQ-010 | `test_la_tabla_cubre_los_13_ids`; `admite_esfuerzo` comprobado en la página de cada modelo | pasa; Sonnet 4.5 corregido a `false` | sección T1, 1 y 5 |
| REQ-011 | `test_normaliza_fecha_y_1m`, `test_busqueda_exacta_en_los_pares`, `test_un_id_sin_entrada_no_tiene_precio` con sus mutantes | pasa | sección T1, 5 |
| REQ-012 (cargador) | `test_cargar_las_tablas_no_abre_sockets` con el mutante `urlopen` | pasa | sección T1, 5 |
| REQ-013 | `test_cotejo_con_filas_literales` y `test_el_cotejo_cuenta_la_busqueda_web`; cotejo real con la tabla del paquete 142/142 | pasa | sección T1, 5 y 6 |
| REQ-030 (datos) | `densidad.json` con `medido_con`; test de guarda | pasa | sección T1, 2 y 5 |
| REQ-001 | Prueba de humo con Claude Code real contra el daemon de esta rama; `test_la_tool_ve_el_tool_use_id` | pasa: `tool_use_id` `toolu_…` en el log | sección I2, 4; [T2](evidencias/T2.md) |
| REQ-002, REQ-003, REQ-005 (formato y clave), REQ-007 (exclusión), plazo `H` | Tests y mutantes de T2; en vivo, nota del hook casada (`caller_src: hook+transcript`) | pasa | [T2](evidencias/T2.md); sección I2, 4 |
| REQ-020 a REQ-024, REQ-025 (código) | 34 tests y 17 mutantes de T3; extracción real sin cambios | pasa (la comprobación real de REQ-025 es T11) | [T3](evidencias/T3.md) |
| REQ-006 | `test_la_fusion_respeta_el_orden`, `test_la_fusion_no_toca_la_cache`, `test_las_filas_de_api_events_vienen_resueltas`, `test_local_status_funde_como_el_panel` con sus mutantes | pasa | sección T4, 4 |
| REQ-007 (tramo) | `test_tramos` con dos mutantes | pasa | sección T4, 4 |
| REQ-008 | `test_respaldo_por_variable` (variable, solo `modelo`, inválido) | pasa | sección T4, 4 |
| REQ-031 a REQ-033 | paridad sobre filas fundidas con los casos de REQ-037 y su guarda; `test_el_js_sigue_a_python`; `test_sin_densidad_las_dos_dan_cero`; `test_el_mismo_py_con_haiku_da_menos_tokens`; `test_la_tool_manda_sobre_la_extension` | pasa | sección T4, 4 |
| REQ-034, REQ-035 | `test_ningun_chars_per_token_en_la_conversion`; coletilla, recibo y `tokens_aprox` en tokens de Claude; coletilla de imagen sin tokens | pasa | sección T4, 3 y 4 |
| REQ-037 | paridad ampliada, control (c) del corte real y guarda | pasa | sección T4, 4 |
| REQ-038 (cuentas) | `test_una_imagen_no_resta_del_neto` (Python y JS) | pasa; el bloque «Imágenes» es de T6 | sección T4, 4 |
| REQ-004 (con `H`), REQ-005 (escritura) | `test_cruce_exacto_ventana_y_path`, `test_el_relleno_usa_el_plazo_leido`, `test_sin_cruce_y_banco` con sus mutantes; en real, 417 líneas rellenadas con `H` = 90 | pasa | sección T5, 3 y 5 |
| REQ-014 | `test_cost_state_toma_la_ultima_por_posicion`; cotejo real: 144 juzgadas, 0 fuera, 0 sin precio | pasa | sección T5, 3 y 5 |
| REQ-043 | `test_n_y_caducidades_conocidos` (tres mutantes), `test_el_ttl_depende_del_hilo`, `test_percentil_par` | pasa | sección T5, 3 |
| REQ-051 a REQ-057 | tests de `test_cuota.py` con sus mutantes; en real, Δ$ de los rechazos $125,71 y $397,68 | pasa; los dos tipos `sin calibrar` | sección T5, 3 y 5 |
| REQ-061 (comando) | `test_sanear_y_lineas_corruptas` (registro y transcript), `test_sin_fuentes_lo_dice` | pasa | sección T5, 3 |
| REQ-070 a REQ-074 | `test_recalcular.py` (privacidad, solo lectura e idempotencia, excluidas, fusión de puntos, mes viejo, plazo, CLI); en real, 0 coincidencias privadas en lo escrito | pasa | sección T5, 3 y 5 |
| REQ-007 (barra), REQ-008 (rótulo), REQ-009, REQ-012 (`/api/stats`), REQ-016, REQ-038 (bloque), REQ-040 a REQ-048, REQ-050, REQ-054 (al leer), REQ-055, REQ-058 a REQ-061, REQ-073 | 10 tests de `test_valoracion.py`, 10 de `test_panel_coste.py` (dos con node) y el de Playwright, con 18 mutantes y el assert que disparó cada uno | pasa | [T6](evidencias/T6.md); sección I5, 3 |
| REQ-015, REQ-075 (con `H`) | 6 tests de `test_coste_doctor.py` con 7 mutantes; guardianes de cifra de `test_checks.py` y `test_wiki.py` | pasa; en esta PC da `warn` por relleno pendiente hasta que T8 lance el comando | [T7](evidencias/T7.md); sección I5, 2 |
| REQ-070 a REQ-072, REQ-014, REQ-015 (datos reales) | `recalcular-coste` sobre el `LOG_DIR` real (3,3 s, `H` = 90); privacidad por conteos con control positivo; cotejo 144/144; `doctor` en `ok` | pasa | sección T8, 1 a 3 |
| REQ-036 | Septiembre con `_load`: caracteres idénticos al hermano; neto 1 589 552 tokens de Claude; cobertura 91/0/30/0/0 | pasa | sección T8, 4 |
| REQ-004, REQ-048 | `atribucion_n.py` (copia con tablas del paquete) contra `/api/stats` en dos ventanas: 159 y 152 delegaciones, `T`, cota baja y estimación iguales; 96,5 %, $11,50 y $92,69 de la spec reproducidos | pasa | sección T8, 5 |
| REQ-051 a REQ-056 (datos reales) | Comando contra `calibracion.py --hasta` la misma hora: estados, descartes por motivo y Δ$ de rechazo iguales | pasa; `sin calibrar` en los dos tipos | sección T8, 6 |
| REQ-005 (clave) | `clave_relleno.py` sobre los logs reales: 0 claves repetidas con `(ts, tool, ordinal)` | pasa | sección T8, 7 |
| Rendimiento del panel | `/api/stats` del último mes, tres veces: 0,021 / 0,008 / 0,009 s | pasa (< 2 s) | sección T8, 8 |
| Documentación (restricción de entrega y non-goal «Publicar versión»), REQ-045 en la doc | CHANGELOG `[Unreleased]`, README y wiki al día; `test_wiki.py`, `test_captura.py`, `test_release_metadata.py`; captura de control con los bloques nuevos | pasa | sección T9 |
| REQ-001 a REQ-003 (instalado), REQ-035, REQ-015, REQ-007, REQ-044, REQ-045, REQ-059, REQ-006 | Daemon reinstalado con la rama; `doctor` 22/22 `OK`; subagente con tres `local_summarize` (3/3 `hook+transcript` con modelo y esfuerzo del subagente); coletillas; panel en vivo contra `/api/stats`; `local_status` contra el panel | pasa, con la observación de la fila a $0,00 | sección T10 |

## Quality checks

- [x] Project-native tests pass. (1746 passed, 2 skipped; «Arreglos tras la conformidad»)
- [x] Lint, formatting, type checking, and build checks pass where applicable. (`ruff check` y
  `ruff format --check`; el repo no tiene paso de tipos ni build propio en la suite)
- [x] Secret scanning passes. (`gitleaks` sobre el árbol y sobre `main..HEAD`; los ids de la visita
  siguen en el historial de `8ad8309`/`a6bced7`, ver arreglo 2)
- [x] No unrelated changes are present.

## Deviations and residual risk

- Ver «Desviaciones del plan» de T0.
