# Implementation plan: el panel cuenta bien, dice la causa real y se presenta coherente

## Approach

Cinco tareas de código y dos de cierre, **todas en serie** y en el árbol de `feat/panel-honesto`,
sin worktrees (decisión de la sesión principal, 2026-10-06). El criterio: dos tareas solo van en
paralelo si no comparten **ningún** fichero, ni de código ni de tests, ni uno que la otra cargue al
verificar. En este cambio no queda ningún par así (ver «Por qué todo en serie»), de modo que cada
ola tiene una sola tarea.

- La regla de contabilidad se cambia en sus dos copias a la vez (T1), con la función única de
  conversión `tokens_claude`/`tokensClaude` y el desglose en caracteres del contrato con
  `coste-api-y-cuota`. El test de paridad que ya existe se amplía con la lista de casos de REQ-001:
  es el único sitio donde vive el riesgo de «dos fuentes».
- La clasificación de fallos va en `fallos.py`, que ya es el módulo puro de clasificación (T2),
  junto con `VistaBackend`. Los cuatro consumidores (sondeo del daemon, `local_status`, `doctor`,
  `_post_chat`) la importan; `checks` la recibe hecha a través de `/api/backend` del daemon (T3,
  T4). Nadie más redacta los textos de una causa.
- Los estados del panel se escriben como **funciones JS puras** (`estadoModelo`, `ordenModelos`,
  `estadoVisible`, `chipEstado`, `textoStats`, `textosSistema`, `badgeBackend`) para poder
  ejecutarlas con node, que es como la suite ya prueba el JS (`tests/test_dashboard_js.py`,
  `_extraer`/`_correr`).
- Nada de variables de entorno ni dependencias nuevas; ningún endpoint nuevo (solo claves).
- La carpeta del cambio (`.sdd/changes/panel-cuentas-y-estados-honestos/`) está sin seguimiento
  en git. Como no hay worktrees, todos los agentes la leen en el árbol principal; cada encargo da la
  ruta absoluta de `spec.md` y `plan.md`.

### Olas

| Ola | Tarea | Espera a | Escritor único de `verification.md` en la ola |
|---|---|---|---|
| 1 | T2 (clasificador) | — | agente de T2 |
| 2 | T1 (contabilidad) | ola 1 | agente de T1 |
| 3 | T3 (sondeo, delegación, plazo de conexión, `doctor`) | ola 2 | agente de T3 |
| 4 | T5 (presentación) | ola 3 | agente de T5 |
| 5 | T4 (API y estados del panel) | ola 4 | agente de T4 |
| 6 | T6 (docs) | ola 5 | agente de T6 |
| 7 | T7 (verificación final) | ola 6 | agente de T7 |

**Por qué todo en serie.** T1 verifica con tests que importan `server.py`, que importa `fallos.py`
(T2). T3 edita `server.py` (T1) y verifica con `tests/test_metrics.py`, que importa
`web/metrics.py`. T5 y T4 editan `web/metrics.py`, y su verificación levanta `metrics.app`, que
importa `server.py`. T6 edita `CHANGELOG.md`, `docs/wiki/` y `scripts/dev/capture_dashboard.py`,
que leen `tests/test_captura.py`, `tests/test_core.py`, `tests/test_update.py` y otros que T4
corre. Y cada tarea termina con la suite completa (abajo), que lo lee todo.

**Integración al final de cada ola** (paso explícito, con dueño): el **último paso de cada tarea**
es su integración, y su dueño es el mismo agente de la tarea. Corre la suite completa,
`bash ~/.claude/scripts/pesado.sh uv run pytest -q` (con `--group ui` instalado para que corran
los tests de Playwright), y el `node --check` del JS si la tarea tocó `web/metrics.py`. Un rojo que
aparezca ahí lo **arregla ese agente** antes de cerrar la ola, aunque esté en un fichero fuera de
su lista: como no hay otra tarea en marcha, no hay conflicto. Ese fichero se apunta en
`verification.md` como tocado por la integración. Es lo que habría parado los dos tests de
`test_fallos_integracion.py` que REQ-018 rompía sin dueño (hallazgo F1 de la segunda pasada).

Comandos pesados (pytest, Playwright, `uv tool install`) **siempre** con
`bash ~/.claude/scripts/pesado.sh <comando>`, uno a la vez en toda la máquina. `ruff` y
`node --check` son ligeros.

### Propiedad de ficheros

Las zonas se nombran **por función**, no por línea: las líneas se mueven en cuanto una tarea
anterior edita el fichero.

| Fichero | EOL | Dueño (en orden) | Zona |
|---|---|---|---|
| `src/local_delegate/fallos.py` | LF | T2 | |
| `tests/test_causa_conexion.py` (nuevo) | LF | T2 | |
| `src/local_delegate/server.py` | CRLF | T1 → T3 | T1: `tokens_claude` (nueva), `_accounting`, bloque de ahorro de `local_status`. T3: `_get_client`, `ChatResult`, `_log_event`, `_post_chat`, `_run_chat` (espera local), `_inflight_start` y un ayudante nuevo para `espera_local`, las tres llamadas a `_log_event` (en `_chat`, en la delegación troceada y en la de imagen), `sondear_backend` (nueva), `_models_with_status`, `_llamaswap_running`, y en `local_status` la línea `Backend:` y la forma de sondear |
| `src/local_delegate/web/metrics.py` | CRLF | T1 → T5 → T4 | T1: `_aggregate`; JS `tokensClaude` (nueva), `acct`, `render` (KPI hero y respaldo de `errs`), `byDay`, `drawSpark`, `drawToolDonut`, `agg` (opción de negativos), columna de ahorro de `renderClients`, y en la tabla de actividad **solo** el predicado del punto. T5: CSS, `<link>` de fuentes, `fmtNum`/`F`/`F1`/`fmtSeg`/`plural`, plurales, latencias (incluida la columna de la tabla de actividad), celdas y nota de hooks/clientes, cabeceras, números de `renderBackendStats`/`pollSystem`/`renderInflight`. T4: endpoints `/api/backend`, `/api/backend/stats`, `/api/status`, `/api/system`, `/api/inflight`; JS `fetchStatus`, `renderBackend`, `badgeBackend`, `chipEstado`, `estadoModelo`, `ordenModelos`, `estadoVisible`, `textoStats`, `textosSistema`, textos de `renderBackendStats`, `pollInflight` y el sondeo nuevo de `/api/backend`, título de `renderInflight`, textos de `pollSystem`, arranque de sondeos |
| `src/local_delegate/config.py` | LF | T3 | solo las tres constantes de plazo |
| `src/local_delegate/doctor.py` | LF | T3 | `backend_probe` |
| `src/local_delegate/checks.py` | LF | T3 | `_default_backend_models`, tipo de `Context.backend_models`, `_probe_backend_models` |
| `tests/test_metrics.py` | LF | T1 → T4 | T1: tests de `_accounting`, paridad, `/api/stats`, `local_status` (ahorro). T4: tests de `/api/backend`, `/api/backend/stats` y `/api/status` (`test_api_backend_available`, `test_api_backend_unavailable`, `test_api_status_reports_version_models_catalog_tools`, `test_api_backend_stats_unavailable_on_404`, `test_api_status_backend_down`) |
| `tests/test_dashboard_js.py` | comprobar | T1 → T5 | T1: listas de extracción de los tests de `byDay` (añadir `function tokensClaude(`) y tests nuevos de `agg`/`acct`. T5: tests de formato |
| `tests/test_dashboard_ui.py` | CRLF | T5 → T4 | T5: tipografía, KPI, latencia, columna de «Quién delegó». T4: un test de la nota remota |
| `tests/conftest.py` | comprobar | T3 | fixture autouse que vacía la lista guardada |
| `tests/test_sondeo_backend.py` y `tests/test_delegacion_conexion.py` (nuevos), `tests/test_checks.py`, `tests/test_doctor.py`, `tests/test_update.py` (solo el doble de `backend_models`), `tests/test_observabilidad_respaldo.py` (solo la fixture `status_sin_red`), **`tests/test_fallos_integracion.py`** y **`tests/test_post_chat_caminos.py`** (origen fijado y casos remotos) | comprobar | T3 | |
| `tests/test_panel_estados.py` (nuevo) | LF | T4 | usa `_extraer`/`_correr` de `test_dashboard_js.py` **sin modificarlo** |
| `docs/wiki/*.md`, `CHANGELOG.md` (CRLF), `scripts/dev/capture_dashboard.py` | ver `research.md` §6 | T6 | |
| `verification.md` | LF | el agente de la ola en curso | uno solo por ola (tabla de olas) |

Reglas comunes:

- Antes de editar, `git ls-files --eol <fichero>`; después, el mismo comando y `git diff --stat`
  deben dar el mismo EOL y ningún fichero ajeno. El heredoc de Git Bash colapsa barras invertidas
  y `write_text` convierte finales de línea: editar con la herramienta Edit.
- **JS compilable al pasar el turno**: el CSS y el JS viven en la constante `metrics.HTML`, así que
  toda tarea que toque `web/metrics.py` termina con
  `uv run python -c "import re,pathlib,sys; from local_delegate.web import metrics as m; pathlib.Path(sys.argv[1]).write_text('\n'.join(re.findall(r'<script>(.*?)</script>', m.HTML, re.S)), encoding='utf-8')" <scratchpad>/panel.js`
  y `node --check <scratchpad>/panel.js`, sin errores.

### Cómo se escribe el control positivo de cada test

Cada test nuevo declara uno de estos tres controles, y la tarea anota en `verification.md` **qué
assert disparó** (copiado de la salida de pytest):

- **(a) contra el código actual**: el test se escribe y se corre **antes** de cambiar el código;
  tiene que fallar en el assert indicado. Nunca por `KeyError`, `AttributeError`, `ImportError`,
  `ValueError` de desempaquetado ni un fallo de extracción: por eso los campos nuevos se leen con
  `.get(...)`, ningún test desempaqueta una tupla cuyo tamaño cambia, y un plazo se lee con un
  ayudante (`t.connect if isinstance(t, httpx2.Timeout) else t`) que no revienta con un número.
- **(b) mutante nombrado**, cuando la unidad no existe todavía: tras implementar, se aplica el
  mutante indicado, el test tiene que fallar en el assert indicado, y se revierte. Antes de dar el
  control por bueno se comprueba que el mutante **muta**: que con él cambia el valor que mira el
  assert (cada mutante de este plan lleva al lado por qué muta).
- **(c) contra el corte intermedio**: cuando el test necesita una interfaz nueva para poder
  llamarse sin excepción, la tarea hace primero un paso **solo de interfaz** (tipos, constantes,
  campos nuevos con el comportamiento de hoy), deja la suite en verde, escribe el test, comprueba
  que falla en el assert indicado, y solo entonces cambia el comportamiento.

Los controles marcados «**comprobado**» se ejecutaron el 2026-10-06 con una reimplementación
desechable de la regla nueva (`scratchpad/controles/paridad.py` y
`scratchpad/controles/clasificador.py`), contra el `acct` real de hoy y el `httpx2` instalado.

## Ordered tasks

### T2 — Clasificador de la causa de conexión (ola 1)

- **Ficheros:** `src/local_delegate/fallos.py`, `tests/test_causa_conexion.py` (nuevo).
- **Requisitos:** REQ-010, REQ-011, la tabla de pistas de REQ-016 y el tipo `VistaBackend`.
- **Qué se hace:** en `fallos.py`, sin red ni lectura de configuración (host, loopback, origen,
  fuente, código y endpoint entran como argumentos):
  - `class CausaConexion(str, Enum)` con las once causas de REQ-010;
  - `causa_conexion(suceso: BaseException | int, *, loopback: bool) -> CausaConexion` con las doce
    reglas **en el orden de la spec**: las 3 a 6 recorren la cadena con un conjunto de visitados,
    las demás miran solo el `suceso`; un `int` 2xx lanza `ValueError`; la última línea es
    `return CausaConexion.DESCONOCIDA` (regla 12);
  - `etiqueta(causa)`, `detalle(causa, *, host, status=None, endpoint=None, excepcion=None)` y
    `pista(causa, *, origen, fuente, host)` con los textos exactos de REQ-011 y REQ-016;
  - `class VistaBackend(NamedTuple)`: `sano: bool`, `detalle: str`, `causa: str | None`,
    `fuente: str` (`"daemon"` o `"directo"`).
  - No se toca `Clase`, `clasificar` ni `es_backend_ausente`: responden a otra pregunta (respaldo y
    enfriamiento).
- **Tests (`tests/test_causa_conexion.py`):** las excepciones se construyen **como las crea el
  socket, con errno y mensaje**, y encadenadas con `raise … from …` para que `__cause__` sea real.

  | Test | Control | Debe fallar con el mutante en |
  |---|---|---|
  | Parametrizado: `ConnectError←socket.gaierror(11001, "getaddrinfo failed")` → `dns`; `ConnectError←OSError(errno.ECONNREFUSED, "refused")` (Python lo crea como `ConnectionRefusedError`) → `rechazada`; `ConnectError←OSError(errno.ENETUNREACH, "Network is unreachable")` y `ConnectError←OSError(10051, "red inalcanzable")` → `sin_ruta`; `ConnectTimeout` con `loopback=True` → `rechazada` y con `False` → `timeout_conexion`; **caso de la Mac**: `ConnectTimeout←TimeoutError(errno.ETIMEDOUT, "timed out")` con `loopback=False` → `timeout_conexion`; `ReadTimeout` → `sin_respuesta`; `ValueError` → `respuesta_invalida`; `RemoteProtocolError` → `transporte`; `InvalidURL` y `UnsupportedProtocol` → `url_invalida`; `HTTPStatusError` construido con `request` y una respuesta 401 → `credencial`, y con 500 → `http_error`; `401`, `403` → `credencial`; `404`, `500` → `http_error`; `AttributeError` y `KeyError` → `desconocida`; `ConnectError←gaierror` con `loopback=True` → `dns` (el orden manda); una excepción cuyo `__context__` es ella misma termina | (b) | Mutante 1: intercambiar las reglas 7 y 8 → falla `assert causa is CausaConexion.RECHAZADA` en el `ConnectTimeout` de loopback (muta: la regla 8 lo atrapa primero). Mutante 2: quitar la regla 4 → falla `assert causa is CausaConexion.DNS` (cae en la 11). Mutante 3: la regla 1 solo mira `int` → el `HTTPStatusError(401)` cae en la **regla 2** y da `http_error` → falla `assert causa is CausaConexion.CREDENCIAL` (**comprobado**). Mutante 4: quitar la regla 12 (la función acaba devolviendo `None`) → falla `assert causa is CausaConexion.DESCONOCIDA` con `KeyError` |
  | `test_un_oserror_sin_errno_no_es_sin_ruta` (guarda del montaje de los tests: `OSError(10051)` con **un** argumento deja `errno` en `None`) | guarda | `assert OSError(10051).errno is None` y que la construcción con dos argumentos sí lo fija (**comprobado**: con un argumento da `transporte`, con dos `sin_ruta`) |
  | `test_un_2xx_no_se_clasifica` | (b) | Mutante: quitar la guarda del 2xx → falla `pytest.raises(ValueError)` (la regla 2 lo da como `http_error`) |
  | **Fallos reales**, sin dobles ni `skip`, en los tres sistemas del CI: `http://no-existe.invalid:9292/v1/models` → `dns`; puerto de `127.0.0.1` recién liberado (abrir un socket, leer su puerto, cerrarlo) con 3 s de conexión → `rechazada`; `http://192.0.2.1:9292/v1/models` con 0,5 s → `timeout_conexion` o `sin_ruta`, y nunca `dns` ni `rechazada` | (b) | Mutante 2 → falla el caso `.invalid` (da `transporte`). Medido en esta PC: 0,12 s, 2,05 s y 0,58 s (`research.md` §2) |
  | `pista`: con `origen="remote"` ninguna causa contiene «arranca llama-swap» a secas; con `origen="local"` y `rechazada`, sí; `credencial` con `fuente="daemon"` contiene «lanzador» y con `"directo"` contiene «en este entorno» | (b) | Mutante 5: `pista` ignora el origen → falla `assert "arranca llama-swap" not in …`. Mutante 6: `pista` ignora la fuente → falla `assert "lanzador" in …` |
  | Todos los `detalle` (un bucle sobre `CausaConexion`) contienen el host que se pasa, y el de `respuesta_invalida` contiene el endpoint | (b) | Mutante 7: `detalle` sin host → falla `assert host in texto` |
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_causa_conexion.py tests/test_fallos.py -q`.
  Los tests de red real tienen que tardar < 5 s en total en esta PC. Después, la integración de la
  ola (suite completa).
- **Rollback:** borrar las funciones nuevas; nadie más las usa hasta T3.

### T1 — Contabilidad: fallos fuera, neto dentro, desglose y conversión única (ola 2)

- **Ficheros:** `server.py` (zona T1), `web/metrics.py` (zona T1), `tests/test_metrics.py` (zona
  T1), `tests/test_dashboard_js.py` (zona T1).
- **Requisitos:** REQ-001 a REQ-008 (la prueba del KPI en navegador es de T5).
- **Qué se hace:**
  1. **Corte de interfaz**: `server.tokens_claude(cantidad, *, tipo, evento)` y el JS
     `tokensClaude(cantidad, tipo, e)` con la tabla «regla de hoy» del contrato de la spec, todavía
     sin que nadie las llame. Suite en verde.
  2. `_accounting` y `acct` siguen la Regla de contabilidad de la spec, letra a letra, y devuelven
     todos los campos del contrato. Ninguna de las dos divide por `CHARS_PER_TOKEN`/`CPT` para
     `saved`, `returned` o `net`. Primero `_accounting` (para el control (c) de la paridad) y
     después `acct`.
  3. `_aggregate`: el predicado de error pasa a `row.get("ok") is False`; totales `returned`,
     `net` y las cuatro sumas del desglose; `tokens_returned` y `tokens_context_net` en la
     respuesta; `tokens_net` en `by_tool`, `by_backend` y `by_client`.
  4. JS: KPI hero con `tokens_context_net`, pista «bruto X − devuelto Y», tooltip «no descuenta
     relecturas»; respaldo de `errs` con `e.ok===false`; punto de la tabla de actividad con
     `e.ok===false?'err':'ok'`; `byDay` y los gráficos con `acct(e).net`; `agg(ev,key,valfn,
     {conNegativos:true})` filtra `!== 0` en vez de `> 0` (sin la opción, igual que hoy, para no
     romper `test_agg_descarta_las_categorias_a_cero`); `drawToolDonut` sin el `filter` de
     `source` y con la opción; `drawSpark` sin `min:0`; columna de ahorro de `renderClients` con
     `tokens_net`.
  5. `local_status`: `~N tokens netos (bruto ~M)` con `_accounting`.
- **Tests nuevos** (en `tests/test_metrics.py` salvo que se diga otra cosa):

  | Test | Control | Debe fallar hoy / con el mutante en |
  |---|---|---|
  | `test_accounting_un_fallo_no_ahorra_ni_genera` (primer escenario de la spec) | (a) | `assert a["saved"] == 0` (hoy 1000; **comprobado** por la revisión) |
  | `test_accounting_un_fallo_no_es_una_estimacion` | (a) | `assert a["estimated"] is False` (hoy `True`) |
  | `test_accounting_fallo_troceado_conserva_el_coste_real` | (a) | `assert a["saved"] == 0` (hoy 1000); después `tokens_in == 900`, `tokens_out == 10`, `backend_calls == 3` |
  | `test_accounting_neto_resta_lo_devuelto` | (a) | `assert a.get("returned") == 100` (hoy `None`) |
  | `test_accounting_salida_a_fichero_no_descuenta_el_recibo` | (a) | `assert a.get("net") == 950` |
  | `test_accounting_el_neto_puede_ser_negativo` | (a) | `assert a.get("net") == -100` |
  | `test_accounting_desglosa_en_caracteres` (escenarios «neto resta», «salida a fichero», «imagen por path» y un fallo) | (a) | `assert a.get("chars_saved_text") == 4000` en el primero (hoy `None`); después los demás campos del contrato |
  | `test_tokens_claude_es_la_unica_conversion` (escenario de REQ-008: `monkeypatch.setattr(server, "tokens_claude", lambda cantidad, *, tipo, evento: 7)`) | (b) | Mutante: en `_accounting`, la parte de texto calcula `chars_in // config.CHARS_PER_TOKEN` en vez de llamar a `tokens_claude` → falla `assert a["saved"] == 7` (da 1000). Muta: el valor de `saved` pasa de 7 a 1000 |
  | `test_dashboard_js.py::test_acct_convierte_solo_con_tokensClaude` (node; preludio con `function tokensClaude(){return 7}` y sin extraer la real) | (b) | Mutante: en `acct`, `tok(ci)` en vez de `tokensClaude(...)` para el texto → falla `assert r["saved"] == 7` (da 1000). Muta por lo mismo |
  | `test_paridad_acct_entre_python_y_el_js_del_panel` ampliado: los 12 casos de REQ-001 **en este orden**: neto positivo, fallo sin tokens, fallo troceado con tokens, `ok: null`, sin clave `ok`, `ok: 0`, neto negativo, `output_to_file` con `path`, `output_to_file` inline, imagen con tokens, imagen sin tokens, `chars_in: 3`; los campos del contrato comparados con `js.get(...)` **empezando por `returned`**; y la guarda de REQ-001 | (c) y (b) | (c): corte intermedio = `tokens_claude` y `tokensClaude` ya existen (paso 1, para que la extracción de `function tokensClaude(` no dé `ValueError`), `_accounting` ya cambiado y `acct` **sin cambiar** → falla `assert js.get("returned") == py["returned"]` en el caso **«neto positivo»** (`None != 100`). (b) mutante: en el JS, `e.ok===false` → `!e.ok` → falla `assert js.get("returned") == py["returned"]` en el caso **«`ok: null`»** (`0 != 100`: el JS lo trata como fallo y Python no; `_ev` pone `chars_out: 400`). Los dos **comprobados**. La guarda sale verdadera en sus cinco condiciones con esos casos (**comprobado**). El caso sin `ok` se construye quitando la clave a mano: `_ev` pone `ok: True` por defecto |
  | `test_stats_el_log_sintetico_de_la_mac_no_infla_nada` (4 buenas con `usage` + 4 `connect_error` con `chars_out: 144`) | (a) | `assert j["estimated_events"] == 0` (hoy 4); luego `tokens_context_net == tokens_context_saved − tokens_returned` |
  | `test_stats_ok_null_no_cuenta_como_error` (REQ-006: un evento con `ok: None`) | (a) | `assert j["total"]["errors"] == 0` (hoy 1, por `bool(r.get("ok", True))`) |
  | `test_stats_expone_el_desglose_en_caracteres` | (a) | `assert j.get("chars_saved_text") == …` (hoy `None`) |
  | `test_stats_quien_delego_trae_el_neto` (`by_client` con un fallo y una buena) | (a) | `assert fila.get("tokens_net") == …` (hoy `None`) |
  | `test_el_js_usa_un_solo_predicado_de_fallo` (sobre `metrics.HTML`) | (a) | `assert "!e.ok" not in html` y `assert "e.ok?'ok':'err'" not in html` (hoy están los dos) |
  | `test_local_status_cuenta_el_neto_como_el_panel` | (a) | `assert esperado in texto`, con `esperado = f"~{n} tokens netos"` y `n` el `tokens_context_net` de `_aggregate` formateado como lo formatee `local_status`; si la clave falta (hoy), `esperado = "~(falta tokens_context_net) tokens netos"`, que tampoco está. Así no hay `TypeError` al formatear un `None` |
  | `test_dashboard_js.py::test_agg_con_negativos_conserva_las_herramientas_por_debajo_de_cero` (escenario de la spec) | (a) | `assert ["b", -100] in resultado` (hoy `agg` ignora el cuarto argumento y filtra `> 0`) |
  | `test_dashboard_js.py::test_la_chispa_admite_negativos` (sobre el cuerpo extraído de `drawSpark`) | (a) | `assert "min:0" not in fuente` |

  Se actualizan a propósito: `test_accounting_una_llamada_sin_trocear` (compara el dict entero:
  añade los campos del contrato), el test del fallo troceado que hoy espera ahorro (research §8),
  `test_local_status_y_el_dashboard_cuentan_igual`, y en `tests/test_dashboard_js.py` las listas de
  extracción de `test_byDay_agrupa_por_dia_local_y_sale_en_orden` y
  `test_byDay_ignora_un_ts_ilegible_en_vez_de_reventar`, que extraen `acct` y ahora necesitan
  también `function tokensClaude(` (si no, node da `ReferenceError`).
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_metrics.py tests/test_dashboard_js.py tests/test_boilerplate_salida.py -q`
  y `node --check` del JS. Después, la integración de la ola (suite completa).
- **Rollback:** revertir los ficheros; el log no cambia de formato.

### T3 — Sondeo con causa, delegación, plazo de conexión y `doctor` (ola 3)

- **Ficheros:** zona T3 de `server.py`, `config.py`, `doctor.py`, `checks.py`, `tests/conftest.py`,
  `tests/test_sondeo_backend.py` y `tests/test_delegacion_conexion.py` (nuevos),
  `tests/test_checks.py`, `tests/test_doctor.py`, `tests/test_update.py` (doble),
  `tests/test_observabilidad_respaldo.py` (fixture), `tests/test_fallos_integracion.py` y
  `tests/test_post_chat_caminos.py`.
- **Requisitos:** REQ-012 (sondeo), REQ-013, REQ-015, REQ-016, REQ-017, REQ-018, REQ-019,
  REQ-021 (lista guardada por URL), REQ-022 (`espera_local`).
- **Qué se hace, en este orden:**
  0. **Medir antes de escribir el control de REQ-013**: con un script del scratchpad, la IP de la
     interfaz de salida (socket UDP «conectado» a `192.0.2.1:9` y `getsockname()`, que no envía
     nada) y un puerto libre en ella, medir tiempo y excepción con 3 s y con 1 s de conexión.
     Anotarlo en `verification.md`. Si con 1 s **no** sale `ConnectTimeout`, el mutante de ese
     test no muta: el control de REQ-013 pasa a ser
     `test_el_plazo_de_sondeo_cubre_el_rechazo_lento_de_windows`, que fija
     `config.TIMEOUT_SONDA_CONEXION >= 2.5` con el motivo medido en el docstring (control (b):
     mutante «plazo 1,0» → falla ese assert), y se avisa a la sesión principal.
  1. **Inventario de los tests que REQ-018 deja sin efecto** (hallazgo F1): antes de editar,
     `rg -n "ArrancarBackend|ensure_backend|ofreció arrancar|ofrecer|preguntas.preguntar|\"preguntar\"|AUTOSTART" tests/`
     y anotar en `verification.md` cuáles ejercitan la pregunta o el autoarranque **a través de
     `_post_chat`** con la URL de los fixtures (`http://test-backend/v1`, que es remota). Hoy son
     `tests/test_fallos_integracion.py` (fixture `backend`; los tests `:114` y `:127` fallarían, y
     los `:136` y `:147` pasarían sin probar nada) y `tests/test_post_chat_caminos.py`
     (`test_todos_los_caminos_devuelven_un_resultado`). Las preguntas de `test_respaldo.py` y
     `test_rol_fast_retirado.py` son de elección de modelo, no de arranque: se comprueba y se anota.
     En cada uno de esos tests se **fija el origen**:
     `monkeypatch.setattr(config, "BACKEND_ORIGIN_OVERRIDE", "local")`, sin cambiar la URL (las
     rutas de `backend_mock` están registradas sobre ella). A `CAMINOS` se añaden dos casos remotos:
     «remoto + ConnectError» y «remoto + ConnectTimeout con autoarranque», que no preguntan ni
     arrancan. REQ-018 se implementa como una condición sobre las ramas que ya existen, sin un
     `return ChatResult(` nuevo, así que `test_la_lista_de_caminos_cubre_todas_las_ramas` sigue
     pidiendo 7; si aun así cambia, T3 ajusta el número y añade el camino.
  2. **Corte de interfaz** (sin cambiar comportamiento): en `config.py`,
     `TIMEOUT_SONDA_CONEXION = 3.0`, `TIMEOUT_SONDA_LECTURA = 2.0` y
     `TIMEOUT_CONEXION_DELEGACION = 10.0` (constantes, sin `_env*`); `doctor.backend_probe()` y
     `Context.backend_models` pasan a devolver `fallos.VistaBackend` con `causa=None`, el texto de
     hoy en `detalle` y la `fuente` que corresponda; `_probe_backend_models` lee `vista.sano` y
     `vista.detalle` con la lógica de hoy. Se actualizan a propósito los dobles de `backend_models`
     (`tests/test_checks.py`, los tres que hoy devuelven la tupla de dos; `tests/test_update.py`,
     el suyo) y el de `backend_probe` en `tests/test_doctor.py`. Suite de T3 en verde.
  3. Escribir los tests de la tabla y comprobar cada control.
  4. `server.py`: `sondear_backend()` → dataclass `EstadoBackend(available, models, models_stale,
     causa, detalle, status_http)`; exige un objeto con una lista `data` y convierte otra forma en
     `ValueError`, con la tolerancia de hoy dentro de `data` (REQ-012); captura **toda** excepción y
     la clasifica con `fallos.causa_conexion(…, loopback=config._is_loopback_host(config._split_host_port(config.BASE_URL)[0]))`
     (el host **sin puerto**: con `backend_host()` la regla 7 no se aplicaría nunca, **comprobado**);
     guarda la última lista buena en un dict **por `BASE_URL`** y la devuelve con `status: None` y
     `models_stale=True` cuando falla. `_models_with_status()` queda como envoltorio `(available,
     models)` para no romper a quien lo usa. `_llamaswap_running()` usa el mismo plazo.
     `tests/conftest.py` gana una fixture **autouse** que vacía ese dict antes de cada test.
  5. `local_status`: usa `sondear_backend()`, pide `/running` solo si `available`, y escribe la
     línea `Backend:` según REQ-015 (`arriba`, `SIN ACCESO`, `RESPONDE CON ERROR`, `CAÍDO`). La
     fixture `status_sin_red` de `tests/test_observabilidad_respaldo.py` pasa a doblar
     `sondear_backend` (y deja de doblar `_models_with_status` y `_llamaswap_running`, que ya no
     llama), para que el test no salga a la red.
  6. `_get_client()`: `httpx2.Timeout(config.HTTP_TIMEOUT, connect=min(config.TIMEOUT_CONEXION_DELEGACION, config.HTTP_TIMEOUT))` (REQ-019).
  7. `ChatResult` gana `fallo_conexion: str | None`; `_post_chat` lo rellena en `connect_error` con
     la causa y redacta el texto de REQ-017; las tres llamadas a `_log_event` (simple en `_chat`,
     troceada e imagen) lo pasan, y `_log_event` escribe `fallo_conexion` solo si no es `None`.
  8. `_post_chat`: con `config.backend_origin() == "remote"`, ni pregunta ni autoarranque, con
     `config.AUTOSTART` en `True` o en `False` (REQ-018). Con origen local, igual que hoy.
  9. Espera local (REQ-022): `_run_chat` recibe el `entry_id` de la entrada en vuelo; intenta
     `_chat_slots.acquire(blocking=False)`; si no hay plaza, escribe `espera_local: "plaza"` en la
     entrada, espera con `acquire()` y borra el campo. En el caso normal (hay plaza) no escribe
     nada de más en `inflight.json`. El ayudante que escribe y borra `espera_local` recibe el motivo
     como argumento, para que otra espera local futura (el turno por grupo de
     `daemon-reparte-el-backend`) lo reutilice sin tocar el panel.
  10. `doctor.backend_probe`: plazo de sondeo y causa vía `fallos`, `fuente="directo"`.
      `checks._default_backend_models`: consulta al daemon con
      `httpx2.Timeout(config.TIMEOUT_SONDA_CONEXION + config.TIMEOUT_SONDA_LECTURA + 1, connect=1.0)`;
      usa `causa`/`detalle` del daemon cuando vienen (`fuente="daemon"`; daemon antiguo: texto de
      hoy y causa `None`). `_probe_backend_models` decide la severidad por causa y fuente (REQ-016),
      no por prefijo de texto, y la pista con
      `fallos.pista(causa, origen=config.backend_origin(), fuente=vista.fuente, host=config.backend_host())`.
- **Tests:**

  | Test | Control | Debe fallar hoy / con el mutante en |
  |---|---|---|
  | `test_post_chat_caminos.py::test_el_autoarranque_sigue_cubierto` (recorre los `CAMINOS` locales con espías en `autostart.ensure_backend` y `preguntas.preguntar`) | (b) | Mutante: quitar el origen fijado en `test_todos_los_caminos_devuelven_un_resultado` (vuelve a heredar `http://test-backend/v1`, remota) → tras REQ-018, falla `assert llamadas_ensure_backend >= 1` (da 0; muta porque con origen remoto REQ-018 cierra las dos ramas). Y `assert preguntas_hechas >= 1` |
  | `test_fallos_integracion.py`: los cuatro tests del fichero con el origen fijado en la fixture `backend` | guarda de regresión | Los de `:114` y `:127` tienen que seguir viendo la pregunta (`assert sin_preguntar`), y los de `:136` y `:147` no verla, ahora con origen local, que es lo que prueban |
  | `test_local_status_dice_sin_acceso_con_un_401` (`backend_mock`: `/models` → 401; `/running` registrado, porque una ruta sin registrar hace fallar el test) | (a) | `assert "SIN ACCESO" in texto` (hoy «CAÍDO») |
  | `test_local_status_no_llama_caido_a_quien_contesta` (`/models` → 500) | (a) | `assert "CAÍDO" not in linea_backend` (hoy `CAÍDO`); después empieza por `RESPONDE CON ERROR:` |
  | `test_local_status_dice_que_no_se_resuelve` (`BASE_URL` = `http://no-existe.invalid:9292/v1`, red real) | (a) | `assert "no se resuelve el nombre no-existe.invalid:9292" in texto` |
  | `test_local_status_no_pide_running_si_models_falla` (`/models` → `ConnectError`; `/running` registrado con contador) | (a) | `assert ruta_running.call_count == 0` (hoy 1: `local_status` llama a `_llamaswap_running` siempre) |
  | `test_sondeo_conserva_la_ultima_lista_buena` (primer sondeo 200 con dos modelos, segundo `ConnectError`) | (a) vía `_models_with_status()` | `assert [m["id"] for m in modelos] == ["a", "b"]` (hoy `[]`); después `status is None` en los dos |
  | `test_la_lista_guardada_es_de_su_url` (lista buena guardada para `http://a/v1`; fallo contra `http://b/v1`) | (b) | Mutante: la lista se guarda en una variable global sin clave por URL → falla `assert modelos == []` (devuelve la de A; muta porque con una sola ranura la URL deja de importar) |
  | `test_un_cuerpo_con_otra_forma_es_respuesta_invalida` (`/models` → 200 con `[]`) | (b) | Mutante: quitar la validación de forma → el `AttributeError` lo recoge la regla 12 → falla `assert estado.causa == "respuesta_invalida"` (da `desconocida`; muta y no lanza, porque el sondeo captura todo) |
  | `test_las_entradas_sueltas_se_toleran_como_hoy` (`data` con un texto suelto y un objeto sin `id`) | guarda de regresión | `assert estado.available is True` y un modelo `"?"` |
  | `test_un_connect_timeout_en_loopback_es_rechazada` (`BASE_URL` = `http://127.0.0.1:9292/v1`, `backend_mock` lanza `httpx2.ConnectTimeout`) | (b) | Mutante: derivar `loopback` de `config.backend_host()` (lleva el puerto) → `_is_loopback_host("127.0.0.1:9292")` es `False` (**comprobado**) → falla `assert estado.causa == "rechazada"` (da `timeout_conexion`) |
  | `test_un_puerto_cerrado_remoto_no_parece_una_vpn` (IP de la interfaz de salida, ver paso 0; sin `skip` en ningún sistema) | (b) | Mutante: `TIMEOUT_SONDA_CONEXION = 1.0` → en Windows llega `ConnectTimeout` contra un host no loopback → falla `assert estado.causa == "rechazada"` (da `timeout_conexion`). Solo si el paso 0 confirma que muta; si no, el test sustituto del paso 0 |
  | `test_el_plazo_de_conexion_de_las_delegaciones_es_de_10_s` (`server._client = None` antes y después) | (a) | `assert server._get_client().timeout.connect == 10.0` (hoy 180); después `.read == config.HTTP_TIMEOUT` |
  | `test_el_plazo_de_conexion_no_supera_el_total` (`config.HTTP_TIMEOUT = 5.0`) | (b) | Mutante: sin el `min` → falla `assert …timeout.connect == 5.0` (da 10; muta porque 10 > 5) |
  | `test_backend_probe_usa_el_plazo_de_sondeo` (`httpx2.Client` sustituido por un registrador del `timeout` que lanza `ConnectError`; el plazo se lee con el ayudante de (a)) | (c) tras el paso 2 | `assert plazo_conexion == config.TIMEOUT_SONDA_CONEXION` (en el corte, 2,0 ≠ 3,0) |
  | `test_una_delegacion_sin_ruta_se_rinde_en_10_s` (`BASE_URL` = `http://192.0.2.1:9292/v1`, red real, `preguntas.preguntar` y `autostart.ensure_backend` sustituidos por registradores; tarda ~10 s) | (a) en esta PC | `assert transcurrido < 13` (hoy ~21 s: el plazo del kernel de Windows, `research.md` §2); después `linea.get("fallo_conexion") in {"timeout_conexion", "sin_ruta"}`. En el CI puede pasar antes (red inalcanzable inmediata): el control es el de esta PC |
  | `test_delegacion_remota_no_pregunta_ni_arranca`, parametrizado con `config.AUTOSTART` en `False` y `True` (`BASE_URL` remoto; `backend_mock` lanza `httpx2.ConnectTimeout`) | (a) | Con `False`: `assert preguntas_hechas == []` (hoy 1). Con `True`: `assert arranques == []` (hoy se llama a `ensure_backend`) |
  | `test_el_error_de_conexion_dice_la_causa_y_va_al_log`, parametrizado por los tres caminos: `local_summarize` con texto (simple), `local_summarize` con un texto mayor que el umbral de troceo (troceada; bajar el umbral con `monkeypatch` si hace falta) y `local_describe_image` con un PNG mínimo en `tmp_path` (imagen); log en `tmp_path` | (a) | `assert "no contesta a la conexión" in texto` en el simple; en los tres, `assert linea.get("fallo_conexion") == "timeout_conexion"` (hoy `None`) y `linea["error"] == "connect_error"` |
  | `test_delegacion_local_sigue_preguntando` (origen local fijado, `ConnectError←ConnectionRefusedError`) | guarda de regresión: pasa hoy y tiene que seguir pasando | `assert len(preguntas_hechas) == 1` |
  | `test_inflight_marca_la_espera_local` (el test toma las `MAX_CONCURRENT_REQUESTS` plazas de `_chat_slots`, lanza una delegación en un hilo con `backend_mock`, espera a que aparezca su entrada en `inflight.json` en `tmp_path`, la lee, y libera las plazas) | (a) | `assert entrada.get("espera_local") == "plaza"` (hoy la clave no existe); al liberar, `entrada.get("espera_local") is None` |
  | `test_doctor_remoto_no_manda_a_arrancar_llama_swap` (`Context(backend_models=lambda: VistaBackend(False, "…", "timeout_conexion", "directo"))`, `BASE_URL` remoto) | (c) tras el paso 2 | `assert "arranca llama-swap" not in (r.hint or "")` (en el corte, la pista sigue siendo la de hoy) |
  | `test_doctor_usa_la_causa_que_da_el_daemon` (`daemon.query_backend` sustituido: `{"available": False, "causa": "dns", "detalle": "no se resuelve el nombre pc.lan (¿VPN o DNS?)"}`) | (a) | `assert "no se resuelve el nombre pc.lan" in r.message` (hoy «no responde (según el daemon…)») |
  | `test_doctor_401_del_daemon_apunta_al_lanzador` (mismo montaje con `causa: "credencial"`) | (a) | `assert "lanzador" in (r.hint or "")` (hoy «arranca llama-swap»); después `r.status == WARN` |
  | `test_doctor_espera_al_daemon_mas_que_su_sondeo` (`daemon.query_backend` sustituido por un registrador del `timeout`; se mide el plazo de lectura: `t.read` si es `httpx2.Timeout`, `t` si es un número) | (c) tras el paso 2 | `assert plazo_lectura > config.TIMEOUT_SONDA_CONEXION + config.TIMEOUT_SONDA_LECTURA` (en el corte, 1,0 > 5,0 es falso). Mutante para repetirlo después: «vuelve a 1,0» |
  | `test_backend_probe_sin_daemon_dice_dns` (`BASE_URL` `.invalid`, red real) | (a) | `assert "no se resuelve" in doctor.backend_probe()[1]` (hoy «no responde (ConnectError)»; se lee por índice para no desempaquetar) |

- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_sondeo_backend.py tests/test_delegacion_conexion.py tests/test_checks.py tests/test_doctor.py tests/test_fallos_integracion.py tests/test_post_chat_caminos.py tests/test_update.py tests/test_observabilidad_respaldo.py tests/test_respaldo.py tests/test_metrics.py -q`.
  `tests/test_metrics.py` tiene que salir en verde **sin tocarlo**: la fixture autouse vacía la
  lista guardada, así que `test_api_backend_unavailable` y `test_api_status_backend_down` siguen
  recibiendo `models: []`. Esa salida va a `verification.md`. Después, la integración de la ola
  (suite completa).
- **Rollback:** revertir; `fallo_conexion` es una clave opcional del log, `espera_local` una clave
  opcional de `inflight.json`, y los lectores ignoran las dos.

### T5 — Presentación: números, latencia, plurales y tipografía (ola 4)

- **Ficheros:** zona T5 de `web/metrics.py`, `tests/test_dashboard_js.py` (zona T5),
  `tests/test_dashboard_ui.py` (zona T5).
- **Requisitos:** REQ-030 a REQ-033, REQ-034 (a)–(g), y la prueba en navegador de REQ-004.
- **Qué se hace:**
  1. `fmtNum(n, decimales)` propia (punto de miles, coma decimal, signo); `F` y `F1` como objetos
     `{format}` sobre ella, con `F` dentro de la sentencia `const CPT = 4, F = …, PAGE = 10;`;
     `fmtSeg(ms)` (`< 0,1 s` por debajo de 50 ms); `plural(n, uno, varios)`. Se aplican en todos
     los sitios de REQ-031/032/033 (`research.md` §1, filas 16-18). Los
     `toFixed(1).replace('.', ',')` de las tablas de hooks y clientes pasan a `F1`.
  2. Tipografía, los arreglos (a)–(g) de REQ-034 (`insumos/tipografia-panel.md` §3): cabeceras sin
     `class="num"`/`"mono"` y `th.mono` fuera de su selector; `<td class="mono">` en procesos y sin
     estilo *inline*; `.selfchip` en `var(--sans)`; fila vacía de procesos con `.empty`; nota de
     hooks con clase propia en Inter; primera columna de hooks/clientes en mono; JetBrains Mono 400
     en el `<link>`; `button,input,select,textarea{font-family:inherit}`. Y una clase `.nota` en
     Inter que T4 usará para la nota remota.
- **Tests:**

  | Test | Control | Debe fallar hoy / con el mutante en |
  |---|---|---|
  | node: evaluar `F` (expresión extraída de la sentencia `const CPT = 4, F = …, PAGE = 10;` con una regex no codiciosa hasta `, PAGE`; `function fmtNum(` se añade al programa **solo si** está en `metrics.HTML`, porque `_extraer` lanza `ValueError` con una cabecera que no existe y `_correr` lanza `CalledProcessError` si node da `ReferenceError`) | (a) | `assert F.format(8003) == "8.003"` (hoy `"8003"`: **comprobado** en node 24) |
  | node: el mismo `F` con un preludio que emula un navegador sin `Intl.NumberFormat` v3 (`Intl.NumberFormat` envuelto para **borrar** `useGrouping`) | (b) | Mutante: `F = new Intl.NumberFormat('es',{useGrouping:'always'})` → falla `assert F.format(8003) == "8.003"` (da `"8003"`). **Comprobado** en node 24: con el envoltorio, ese `F` da `8003`, y una `fmtNum` propia da `8.003`. Ojo: envolver poniendo `useGrouping: true` **no** emula nada (en node 24 `true` ya agrupa) |
  | node: `fmtSeg(116948) == "116,9 s"`, `fmtSeg(120) == "0,1 s"`, `fmtSeg(30) == "< 0,1 s"`; `F1.format(1718.25) == "1.718,3"`, `F.format(-1234567) == "-1.234.567"` | (b) | Mutante 1: `F1` sin agrupar → falla `== "1.718,3"` (da `1718,3`). Mutante 2: `fmtSeg` sin el caso de 50 ms → falla `== "< 0,1 s"` (da `0,0 s`) |
  | node: `plural(1,'estimado','estimados') == "1 estimado"` y con 4 | (b) | Mutante: devolver siempre la forma plural → falla el caso 1 |
  | Búsqueda en `metrics.HTML` de los cuatro literales `archivo(s)`, `leído(s)`, `delegación(es)` y `estimado(s)`, y de `toFixed(` | (a) | `assert "estimado(s)" not in html` (y los otros tres, uno por assert). No se busca `(s)` suelto: choca con `renderClients(s)`, `escHooks(s)` y `fmtHace(s)` |
  | Playwright: las `thead th` comparten familia (con datos que pinten hooks, clientes, actividad y procesos) | (a) | `assert len(familias_de_th) == 1` (hoy dos) |
  | Playwright: `.selfchip` con la familia de `.mrole`; fila vacía de procesos con la de `.empty`; nota de hooks en Inter | (a) | `assert fam(".selfchip") == fam(".mrole")` (y uno por arreglo) |
  | Playwright: primera columna de «Sugerencias de los hooks» y «Quién delegó» en mono (arreglo e) | (a) | `assert "JetBrains Mono" in fam(primera_celda_hooks)` |
  | Playwright: el botón «Refrescar» tiene la familia del `body` (arreglo g) | (a) | `assert fam(boton) == fam("body")` (hoy la del agente de usuario) |
  | Playwright: el `<link>` de fuentes (arreglo f; `getComputedStyle` no ve la cara que falta) | (a) | `assert "JetBrains+Mono:wght@400" in href` |
  | Playwright: KPI hero con un log que tiene un fallo con `path` y una buena con `chars_out > 0` → el valor es el neto, la pista contiene bruto y devuelto, y el `title` dice que no descuenta relecturas | (b): T1 ya cambió el hero | Mutante «hero con `tokens_context_saved`» → falla `assert kpi == F(neto)` (muta porque con `chars_out > 0` bruto y neto difieren). Mutante «sin tooltip» → falla `assert "relecturas" in title` |
  | Playwright: la columna de ahorro de «Quién delegó» enseña `tokens_net` (cliente con un fallo y una buena) | (b): T1 ya la cambió | Mutante «columna con el bruto» → falla `assert celda == F(neto_del_cliente)` (muta porque bruto y neto difieren con `chars_out > 0`) |
  | Playwright: «Latencia media» acaba en « s» y no en « ms» | (a) | `assert texto.endswith(" s")` |

  `tests/test_dashboard_ui.py` no se salta en CI; en local, si falta Chromium, se salta con motivo
  visible y T7 lo corre.
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_dashboard_js.py tests/test_dashboard_ui.py tests/test_metrics.py -q`
  y `node --check` del JS. Después, la integración de la ola (suite completa).
- **Rollback:** revertir la zona T5.

### T4 — API y estados del panel (ola 5)

- **Ficheros:** zona T4 de `web/metrics.py`, `tests/test_panel_estados.py` (nuevo),
  `tests/test_metrics.py` (zona T4), `tests/test_dashboard_ui.py` (zona T4).
- **Requisitos:** REQ-012 (endpoints), REQ-014, REQ-020 a REQ-028, y REQ-034 (h).
- **Qué se hace:**
  1. `/api/backend` usa `server.sondear_backend()`; pide `/running` solo si `available`; devuelve
     `causa`, `detalle`, `models_stale` y `running_ok`. `/api/status` usa el mismo sondeo en su
     bloque `backend`. `/api/backend/stats` usa el plazo de sondeo y devuelve `causa`, `detalle` y
     `status_http` cuando no hay datos. `/api/system` añade `platform`, `origin` y `host`.
     `/api/inflight` deja pasar `espera_local`.
  2. JS puro: `badgeBackend(vista)`, `chipEstado(status)`, `ordenModelos(ids, catalog)`,
     `estadoVisible(prev, bj)` (REQ-028: devuelve el estado visible **y el sondeo de referencia**,
     que es el último bueno mientras se conserva «disponible»), `estadoModelo({...})` (tabla de
     REQ-022 en ese orden, con las condiciones **tal cual** las escribe la spec; devuelve
     `{texto, title, atenuada}`, con `atenuada` según el estado visible y nunca según
     `models_stale`; «en espera local» = el campo `espera_local` presente con **cualquier** valor),
     `textoStats(j)`, `textosSistema(j)` (la nota remota con la clase `.nota` de T5).
     `renderBackend` toma la lista del sondeo de referencia.
  3. Sondeos separados: `pollInflight` solo pide `/api/inflight`, y un `pollBackend` nuevo pide
     `/api/backend`; cada uno con su guarda «uno en vuelo» y su `setTimeout` encadenado de 2 s tras
     terminar; las llamadas manuales respetan las guardas. Cuando `estadoVisible` pasa a
     disponible, `fetchStatus()` y `/api/backend/stats` inmediatos.
  4. `renderInflight`: título «Última delegación» cuando pinta la última terminada.
- **Tests:**

  | Test | Control | Debe fallar hoy / con el mutante en |
  |---|---|---|
  | `/api/backend` con `/models` → 401 (`backend_mock`) | (a) | `assert j.get("causa") == "credencial"` |
  | `/api/backend` tras un sondeo bueno y otro con `ConnectError` | (a) | `assert j.get("models_stale") is True` (tras T3, la lista ya se conserva y el `ids == […]` **ya pasaría**: el assert de control es este; los `ids` se comprueban después) |
  | `/api/backend` no pide `/running` si `/models` falla (ruta de `/running` registrada con contador) | (a) | `assert ruta_running.call_count == 0` (hoy 1: se pide antes) |
  | `/api/backend` con `/running` → 404 | (a) | `assert j.get("running_ok") is False` (hoy `None`) |
  | `/api/status` con `/models` → 401 (bloque `backend`, REQ-012) | (a) | `assert data["backend"].get("causa") == "credencial"` |
  | `/api/backend/stats` con 404 y con `.invalid` | (a) | `assert j.get("status_http") == 404`; `assert j.get("causa") == "dns"` |
  | `/api/backend/stats` usa el plazo de sondeo (`httpx2.Client` sustituido por un registrador del `timeout`; ayudante de (a)) | (a) | `assert plazo_conexion == config.TIMEOUT_SONDA_CONEXION` (hoy otro plazo) |
  | `/api/system` | (a) | `assert j.get("platform") == sys.platform`; después `j.get("origin")` y `j.get("host")` |
  | `/api/inflight` con una entrada con `espera_local: "plaza"` en `inflight.json` | (b) | Mutante: el endpoint copia una lista blanca de claves sin `espera_local` → falla `assert e.get("espera_local") == "plaza"` (muta porque la clave deja de llegar al panel) |
  | node: `pollInflight` llamado 3 veces con un `fetch` que no resuelve nunca y `document.visibilityState='visible'` | (a), la función existe hoy | `assert llamadas_fetch_inflight == 1` (hoy 3, más 3 de `/api/backend`) |
  | node: `pollInflight` con `fetch` que resuelve y un `setTimeout` registrador | (a) | `assert retrasos == [2000]` tras resolver (hoy `pollInflight` no programa nada: lo hace un `setInterval` al arrancar) |
  | node: `/api/backend` que no resuelve nunca y `/api/inflight` que resuelve; se llama al sondeo | (a) | `assert renders_inflight >= 1` (hoy `Promise.all` espera a los dos y no pinta) |
  | node: `estadoVisible` con la secuencia bueno, fallido, fallido, bueno; y fallido desde cero | (b) | Mutante: umbral 1 → falla `assert vistos[1] == "conectado"` (da caído; muta porque con un fallo ya cambia). Y `assert vistos_desde_cero[0] == "comprobando"` |
  | node: **las filas aguantan el primer fallo** (escenario de la spec: bueno con `gemma4-26b-a4b` `loaded` y `ready`, después fallido) | (b) | Mutante 1: las filas usan el último `bj` en vez del sondeo de referencia → falla `assert fila.texto == "montado"` tras el primer fallo (da «frío»: el `bj` fallido trae `status: null` y `running_ok: false`, regla 5). Mutante 2: atenuar por `models_stale` → falla `assert fila.atenuada is False`. Tras el segundo fallo, `assert fila.texto == "desconocido"` y `fila.atenuada is True` |
  | node: refresco al reconectar (secuencia fallido, fallido, bueno en el sondeo de `/api/backend`; se cuentan los `fetch('/api/status')`) | (b): el sondeo de `/api/backend` pasa a una función nueva | Mutante: quitar la llamada a `fetchStatus()` al pasar a disponible → falla `assert llamadas_status == 1` (da 0; muta porque es la única vía de ese `fetch` fuera del ciclo de 60 s, que el test no deja correr) |
  | node: `renderInflight` sin llamadas vivas y con `state.lastEvent` | (a), la función existe hoy | `assert head == "Última delegación"` (hoy «En curso») |
  | node: `renderBackendStats({available:false, causa:'dns', detalle:'…'})` y `({available:false, status_http:404})` | (a) y (b) | (a): `assert "v236" not in html` con `dns`. (b) para la rama positiva: mutante «nunca menciona v236» → falla `assert "v236" in html` con 404 |
  | node: `estadoModelo`, una fila por regla de REQ-022, más «`/v1/models` dice loaded y `/running` dice starting» → «cargando» | (b) | Mutante 1: la regla 9 («en vuelo» → esperando turno) antes que la 6 → falla `assert txt == "cargando"` con llamada en vuelo y `starting` (muta porque la condición de la 9 es solo «en vuelo»). Mutante 2: la regla 4 («`running_ok` falso y en vuelo» → en curso) antes que la 1 → falla `assert txt == "esperando al backend"` con el backend no disponible, una llamada en vuelo y `running_ok: false` (muta porque las dos condiciones se cumplen). Mutante 3: quitar la regla 3 → falla `assert txt == "en cola local"` con `espera_local: "plaza"` y `running` `ready` (da «procesando») |
  | node: **punto de extensión** de la espera local: `espera_local: "turno_grupo"` (motivo que el panel no conoce) con `running` `ready` | (b) | Mutante: la regla 3 exige `espera_local === 'plaza'` → falla `assert txt == "en cola local"` (da «procesando»; muta porque el motivo es otro). Y `assert "turno_grupo" in title` |
  | node: `estadoModelo` fila 9, `title` con `/running` = `[gemma4-26b-a4b ready, qwen36-35b-a3b starting]` | (b) | Mutante: el `title` solo nombra los `ready` → falla `assert "qwen36-35b-a3b cargando" in title` |
  | node: `ordenModelos` con y sin conexión (escenario de la spec) | (b) | Mutante: orden alfabético puro → falla `assert ids == ["gemma4-26b-a4b", "qwen36-35b-a3b", "gemma4-12b", "qwen35-2b"]` (alfabético da `gemma4-12b` primero) |
  | node: `chipEstado` con `loaded`, `unloaded`, `starting` y `null` | (b) | Mutante: todo lo que no es `loaded` usa el estilo de `unloaded` → falla `assert chipEstado("starting") == "neutral"` |
  | node: `textosSistema` para `darwin`+`remote`, `win32`+`local` sin procesos, `linux`+`remote` con procesos | (b) | Mutante: sin la rama de `origin` → falla `assert "El backend corre en" in nota` |
  | node: `badgeBackend` para `credencial`, `http_error`, `dns`, y conectado | (b) | Mutante 1: `credencial` como caída → falla `assert clase == "warn"`. Mutante 2: `title` fijo → falla `assert title == detalle`. Y `assert texto == "caído · no resuelve"` con `dns`, `assert "caído" not in texto` con `http_error` |
  | Playwright (`test_dashboard_ui.py`): con `/api/system` interceptado (`page.route`) en `darwin`+`remote` sin procesos, la nota sale, en Inter, y no sale «Ningún proceso del backend detectado» | (a) | `assert "El backend corre en" in texto` (hoy no existe) |

  Se actualizan a propósito, en `tests/test_metrics.py`: `test_api_backend_unavailable`,
  `test_api_backend_stats_unavailable_on_404` y `test_api_status_backend_down` (comparan el JSON
  entero con `==` y ganan claves), y `test_api_backend_available` y
  `test_api_status_reports_version_models_catalog_tools` si cambia el envoltorio.
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_panel_estados.py tests/test_metrics.py tests/test_dashboard_js.py tests/test_dashboard_ui.py tests/test_captura.py -q`
  y `node --check` del JS. Después, la integración de la ola (suite completa).
- **Rollback:** revertir la zona; las claves nuevas son aditivas.

### T6 — Documentación (ola 6)

- **Ficheros:** `docs/wiki/Savings-and-metrics.md` («Qué se mide», «Cómo se calcula el ahorro… y
  el coste», «Delegaciones en curso», «APIs»), `docs/wiki/Troubleshooting.md` («no se pudo
  conectar al endpoint», «`doctor` dice que el backend está CAÍDO…»), `docs/wiki/Daemon.md`
  («Qué significa «DAEMON MCP» en el dashboard», si cambia el texto), `docs/wiki/Remote-backend.md`
  («Verificación»: lo que dice el panel con cómputo remoto), `CHANGELOG.md` (`[Unreleased]`,
  CRLF), `scripts/dev/capture_dashboard.py` (mock de `/api/stats`, `/api/backend` e `/api/system`
  con las claves nuevas).
- **Requisitos:** REQ-040 y la sección «Restricciones de entrega» de la spec.
- **Qué se hace:** la regla de contabilidad con la tabla «qué cuenta / qué no» y el desglose en
  caracteres, con las cifras de septiembre como ejemplo; la tabla de causas con su pista; el plazo
  de conexión de 10 s; la histéresis (badge y filas); la espera local; los estados nuevos.
  CHANGELOG:
  - Al principio de `[Unreleased]`, una nota visible: «**No publicar versión hasta mezclar
    `coste-api-y-cuota`**: las cifras en tokens de Claude de este bloque usan todavía chars ÷ 4».
  - `### Fixed`: los fallos inflaban el ahorro; el badge, `local_status` y `doctor` dicen la causa;
    no se ofrece arrancar un backend remoto; una delegación que no puede conectar se rinde en 10 s;
    estados del panel.
  - `### Changed`: «Contexto conservado» pasa a neto, **las cifras históricas bajan**, con el
    ejemplo de agosto −32 %; dos sondeos fallidos antes de «caído»; presentación.
  - Sin versión ni fecha.
- **Aviso:** el agente de `coste-api-y-cuota` puede tocar también `[Unreleased]` y las mismas
  páginas de la wiki; se edita con Edit sobre el bloque propio, nunca reescribiendo la sección.
- **Verificación:**
  `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_wiki.py tests/test_captura.py -q`;
  `git ls-files --eol` de los ficheros tocados igual que antes; la nota de la restricción está en
  `[Unreleased]`. Después, la integración de la ola (suite completa).
- **Rollback:** revertir los Markdown y el mock.

### T7 — Verificación final (ola 7)

1. `uv run ruff check .` y `uv run ruff format --check .`.
2. Suite completa: `bash ~/.claude/scripts/pesado.sh uv run pytest -q` (con Playwright
   instalado). Resultado y conteo en `verification.md`.
3. **Septiembre a mano** (escenario de la spec; insumo: `usage-202609.jsonl` de `config.LOG_DIR`,
   mes cerrado, lo produjo el uso real; las cifras esperadas las produjeron `research.md` §3 y
   `scratchpad/contrato_chars.py` con reimplementaciones aparte, así que **puede** dar otro
   número): `uv run python -c "import json; from local_delegate import config; from local_delegate.web import metrics as m; f=config.LOG_DIR/'usage-202609.jsonl'; r=[json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip()]; a=m._aggregate(r); print(a['chars_saved_text'], a['bytes_saved_image'], a['chars_saved_output'], a['chars_returned'], a['tokens_context_saved'], a['tokens_returned'], a['tokens_context_net'], a['estimated_events'])"`
   → `3463739 1489047 5237 289554 873270 72342 800928 0`. La salida se copia a `verification.md`.
   Cualquier otra cifra se investiga antes de seguir.
4. **Panel del repo contra el backend real, sin credencial** (insumo: el llama-swap de
   `127.0.0.1:9292`, que exige token; la consola **no** tiene la clave, así que el 401 es el caso a
   ver, sin leerla ni pedirla): servir `metrics.app` del repo en `127.0.0.1:9494` como dice
   `tests/test_captura.py` y comprobar con Playwright, bajo `pesado.sh`, que tras dos sondeos el
   badge dice «sin acceso» en ámbar. Repetir con
   `LOCAL_DELEGATE_BASE_URL=http://no-existe.invalid:9292/v1` → tras dos sondeos, «caído · no
   resuelve», las filas «desconocido», y la tarjeta de llama-swap sin «v236».
5. **`doctor` sin daemon**: `LOCAL_DELEGATE_WEB_PORT` a un puerto libre (para que no pregunte al
   daemon) y `LOCAL_DELEGATE_BASE_URL=http://no-existe.invalid:9292/v1` →
   `uv run local-delegate doctor` da la causa `dns` y la pista de `dns`; con
   `LOCAL_DELEGATE_BASE_URL=http://192.0.2.1:9292/v1` (origen remoto) ninguna pista dice
   «arranca llama-swap».
6. **Daemon real con la versión del repo** (autorizado por el usuario el 2026-10-06; lo lanza la
   sesión principal, porque reinicia el daemon):
   `bash ~/.claude/scripts/pesado.sh uv tool install --force --reinstall --no-cache ".[llamaswap]"`
   y `schtasks /Run` de la tarea del daemon. Después:
   - `local_status` por MCP: «Backend: arriba» y la línea `~N tokens netos (bruto ~M)`.
   - `uv run local-delegate doctor` en una consola **sin** la clave: `service.backend` sale `OK`
     por la vía del daemon (la consola sola daría `UNKNOWN` por el 401). Falla si sale `UNKNOWN` o
     `WARN`.
   - **Panel de `9393` durante una delegación larga.** La llamada MCP bloquea mientras dura, así
     que la lectura va **dentro de la página** y se lanza **antes**: con `browser_evaluate`,
     instalar en `window` un `setInterval` de 500 ms que guarda en `window.__lecturas` el texto de
     la fila del modelo y el título del panel «En curso», con su hora. Lanzar la delegación larga.
     Cuando vuelva, esperar 5 s y leer `window.__lecturas` con otro `browser_evaluate`. La prueba
     **falla** si ninguna lectura de la fila es «cargando», «esperando turno», «en cola local» o
     «procesando», o si el título no pasa a «Última delegación» en los 5 s siguientes al final. Las
     lecturas van a `verification.md`.
7. **Devolver el daemon a la versión publicada**: este cambio no se publica solo («Restricciones
   de entrega»), y un daemon con el código del repo enseñaría a diario la cifra intermedia en
   tokens. La sesión principal reinstala la 0.32.0 publicada
   (`bash ~/.claude/scripts/pesado.sh uv tool install --force --reinstall --no-cache "local-delegate[llamaswap]==0.32.0"`)
   y relanza la tarea del daemon, salvo que el usuario diga otra cosa.
8. Revisar con `personal-sdd-review` el resultado contra la spec; `personal-security-check` sobre
   el diff.

## Test strategy

- **Unit:** `_accounting`/`acct`, `tokens_claude`/`tokensClaude` y su paridad (T1);
  `fallos.causa_conexion`, textos y pistas (T2); funciones JS puras con node (T4, T5).
- **Integración:** `/api/stats`, `/api/backend`, `/api/backend/stats`, `/api/status`,
  `/api/system`, `/api/inflight` con `TestClient` y `backend_mock` (T1, T4); `_post_chat` en los
  tres caminos con `backend_mock` y log en `tmp_path`, con el origen fijado en cada test que mira
  la pregunta o el autoarranque; `local_status`; `checks`/`doctor` con dobles del daemon (T3).
  Suite completa al final de cada ola.
- **Red real**, en los tres sistemas del CI y sin `skip`: el clasificador y el sondeo contra un
  nombre `.invalid`, un puerto local cerrado, TEST-NET-1 y una IP propia no loopback (T2, T3); una
  delegación contra TEST-NET-1 (T3; el control es el de esta PC). El backend real con 401 y el
  daemon real (T7).
- **Navegador:** Playwright para tipografía, KPI neto, columna de «Quién delegó» y latencia (T5),
  la nota remota (T4), y el panel servido contra el backend real y el daemon (T7).
- **Seguridad y secretos:** ningún test ni paso lee o pide `LOCAL_DELEGATE_API_KEY`; el 401 se
  observa sin credencial. `detalle` y `fallo_conexion` no llevan credenciales (`backend_host()` las
  quita). Antes de cerrar, `personal-security-check` sobre el diff.

## Migration and compatibility

- **Log:** solo se añade `fallo_conexion`. Los logs históricos se recalculan al leerlos; las cifras
  de ahorro de meses pasados **bajan** (agosto −32 %, septiembre −11 % de bruto) y el CHANGELOG lo
  dice. `inflight.json` añade `espera_local`.
- **API:** claves nuevas en `/api/stats`, `/api/backend`, `/api/backend/stats`, `/api/status`,
  `/api/system` e `/api/inflight`; ninguna cambia de nombre. `tokens_context_saved` sigue siendo el
  bruto (ahora sin fallos). El contrato con `coste-api-y-cuota` está en la spec: ese cambio
  sustituye `tokens_claude`, y no se publica versión hasta que esté mezclado.
- **Espera local:** `daemon-reparte-el-backend` (turno por grupo `swap`) solo tiene que escribir
  `espera_local` con su motivo, con el mismo ayudante de T3; el panel no cambia.
- **`doctor` con un daemon de versión anterior:** sin `causa` en `/api/backend`, cae al texto de
  hoy y a la pista genérica (REQ-016).
- **Interfaces internas:** `Context.backend_models` y `doctor.backend_probe` pasan a devolver
  `fallos.VistaBackend` (una `NamedTuple`: `[0]` y `[1]` siguen valiendo para quien indexa);
  `_models_with_status` se conserva como envoltorio; `_run_chat` recibe el `entry_id`.
- **Captura del README:** no se regenera aquí; el mock queda listo para la próxima release.

## Plan review

- [x] Cada requisito tiene tarea y verificación (tabla de trazabilidad de la spec).
- [x] Nada destructivo: los pasos que reinstalan y reinician el daemon (T7.6 y T7.7) los lanza la
  sesión principal, con la autorización del usuario del 2026-10-06.
- [x] Sin dependencias ni variables de entorno nuevas; las tres constantes nuevas están en
  `config.py`.
- [x] Sin trabajo ajeno al brief: entran el plazo de conexión de 10 s y la histéresis porque los
  decidió el usuario; quedan fuera la RAM en macOS, la fila del modelo de respaldo y el coste en
  API (Non-goals de la spec).
- [x] Todas las tareas van en serie, en un solo árbol; cada ola tiene un único escritor de
  `verification.md` y un dueño de su integración, que arregla lo que salga.
- [x] Los tests que la tarea rompe son suyos: T3 se queda `test_fallos_integracion.py` y
  `test_post_chat_caminos.py`, con el origen fijado y una guarda de que el autoarranque sigue
  cubierto.
- [x] Cada control nombra la tarea que produce su insumo (T2 → `VistaBackend` y textos que usa T3;
  T1 → contrato y cifras de septiembre; T3 → `causa` del daemon que lee `checks`, probado con doble
  en T3 y de verdad en T7, y el ayudante de `espera_local`; T5 → clase `.nota` que usa T4; T4 →
  claves que pinta el panel; T6 → mock de la captura y nota de la restricción).
- [x] Cada mutante nuevo o cambiado dice por qué muta. Ejecutados: la paridad (control (c) y
  mutante `!e.ok`), el `HTTPStatusError(401)` del mutante 3 de T2, la construcción de los
  `OSError`, `_is_loopback_host` con y sin puerto, y el navegador sin `Intl` v3.
