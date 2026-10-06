# Verification: Panel: los fallos no suman ahorro, los estados dicen la causa real y la presentación es coherente

## Environment

- Revision: `feat/panel-honesto` sobre `849d47a` (cambios de T2 sin commit).
- Revision de T1: `feat/panel-honesto` sobre `d20d4f3` (T2 en commit; cambios de T1 sin commit).
- Revision de T3: `feat/panel-honesto` sobre `9d9c471` (T2 y T1 en commit; cambios de T3 sin commit).
- Revision de T5: `feat/panel-honesto` sobre `c8287fa` (T2, T1 y T3 en commit; cambios de T5 sin
  commit). Node 24 (`C:\nvm4w\nodejs\node.EXE`), Playwright 1.63.0 con Chromium.
- Relevant runtime and tool versions: Windows 11 (esta PC), Python 3.11.15 (venv de `uv`),
  `httpx2` 2.13.0, pytest de `uv run`, `ruff` de `uv run`. Grupo `ui` instalado para la suite
  completa con `uv sync --group ui --frozen` (añade `playwright` 1.63.0, `greenlet`, `pyee`; el lock
  no cambia).

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | Paridad Python/JS con los 12 casos en orden, 18 campos con `.get`, guarda de cinco condiciones | Pasa | Sección T1 |
| REQ-002 | Fallo sin tokens, fallo troceado con tokens, fallo no estimado; log sintético de la Mac | Pasa | Sección T1 |
| REQ-003 | `/api/stats` con `tokens_returned`, `tokens_context_net`, desglose y `tokens_net` por tool, origen y cliente | Pasa | Sección T1 |
| REQ-004 | KPI con el neto y la pista; `agg` con negativos; chispa sin `min:0`; gráficos con `acct(e).net` | Pasa (la prueba en navegador es de T5) | Sección T1 |
| REQ-005 | `local_status` dice `~N tokens netos (bruto ~M)` con `_accounting` | Pasa | Sección T1 |
| REQ-006 | Un solo predicado de fallo en `_aggregate` y en el JS | Pasa | Sección T1 |
| REQ-007 | Desglose en caracteres por evento y en totales; septiembre recalculado a mano | Pasa | Sección T1 |
| REQ-008 | `tokens_claude`/`tokensClaude` sustituidas por un 7 fijo; mutantes en las dos copias | Pasa | Sección T1 |
| REQ-010 | `tests/test_causa_conexion.py`: 28 casos construidos como los crea el socket (incluidos `HTTPStatusError(401)`, `InvalidURL`, `UnsupportedProtocol` y el caso de la Mac), guarda del 2xx, cadena con ciclo y tres fallos de red real sin dobles | Pasa | Sección T2 |
| REQ-011 | Etiquetas y detalles exactos de la tabla, host en todos los detalles salvo `url_invalida`, endpoint en `respuesta_invalida`, nunca «None» | Pasa | Sección T2 |
| REQ-016 (tabla de pistas y `VistaBackend`) | `pista` por origen y fuente; pista genérica sin causa; campos de `VistaBackend` | Pasa (la parte de `doctor` es de T3) | Sección T2 |
| REQ-012 (sondeo) | `sondear_backend`: cuerpo con otra forma (`[]`, `{}`, `data` que no es lista) da `respuesta_invalida`; entradas sueltas toleradas; 401 da `credencial` con `status_http`; nunca lanza | Pasa (los endpoints son de T4) | Sección T3 |
| REQ-013 | Plazo de 3 s y 2 s en `sondear_backend`, `_llamaswap_running` y `doctor.backend_probe`; `local_status` no pide `/running` si `/models` falla; puerto cerrado en la IP de salida, con red real, da `rechazada` (paso 0 medido) | Pasa (`/api/backend` y `/api/metrics/stats` son de T4) | Sección T3 |
| REQ-015 | `local_status`: `SIN ACCESO` con 401, `RESPONDE CON ERROR` con 500, `CAÍDO: no se resuelve…` con `.invalid` (red real) | Pasa | Sección T3 |
| REQ-016 (`doctor`) | Severidad por causa y fuente; pista remota sin «arranca llama-swap»; causa del daemon; 401 del daemon apunta al lanzador con `WARN`; daemon antiguo; 6 s de lectura al daemon | Pasa | Sección T3 |
| REQ-017 | Texto con el detalle y `fallo_conexion` en el log en los caminos simple, map-reduce, por trozos e imagen; `error` sigue siendo `connect_error` | Pasa | Sección T3 |
| REQ-018 | Remoto: ni pregunta ni autoarranque, con `AUTOSTART` en `False` y en `True`; local: como antes; guarda de que el autoarranque sigue cubierto | Pasa | Sección T3 |
| REQ-019 | Cliente con conexión de 10 s y lectura `HTTP_TIMEOUT`; `min` con un total de 5 s; una delegación real a `192.0.2.1` se rinde en 10,0 s (antes 21,1 s) | Pasa | Sección T3 |
| REQ-021 (servidor) | Lista guardada por `BASE_URL`, con `status: None` y `models_stale` | Pasa (el panel es de T4) | Sección T3 |
| REQ-022 (servidor) | `espera_local: "plaza"` mientras espera plaza, borrada al conseguirla; nada de más con plaza libre; `inflight_snapshot` la copia | Pasa (el panel es de T4) | Sección T3 |
| REQ-004 (navegador) | Playwright con un fallo por `path` y una buena con `chars_out > 0`: KPI `9.000`, pista con `10.000` y `1.000`, tooltip con «relecturas»; columna de «Quién delegó» `9.000` | Pasa | Sección T5 |
| REQ-030 | `F.format(8003) == "8.003"` con node, también emulando un navegador sin Intl v3; `F` sigue en `const CPT = 4, F = …, PAGE = 10;` | Pasa | Sección T5 |
| REQ-031 | `F1.format(1718.25) == "1.718,3"`, `F.format(-1234567) == "-1.234.567"`; ningún `toFixed(` en el HTML | Pasa | Sección T5 |
| REQ-032 | `fmtSeg`: `116,9 s`, `0,1 s`, `< 0,1 s`; KPI «Latencia media» `3,0 s` y columna de actividad `2,0 s`/`4,0 s` en navegador | Pasa | Sección T5 |
| REQ-033 | `plural`: «1 estimado», «4 estimados», «1.234 eventos»; ninguno de los cuatro literales con paréntesis | Pasa | Sección T5 |
| REQ-007 (log real) | Septiembre recomputado con `_aggregate` sobre `usage-202609.jsonl`: `3463739 1489047 5237 289554 873270 72342 800928 0` | Pasa | Sección T7, paso 3 |
| REQ-014, REQ-020, REQ-028 (navegador real) | Panel del repo contra llama-swap con 401: «sin acceso» ámbar al 2.º sondeo; con `.invalid`: «caído · no resuelve» rojo, filas «desconocido», tarjeta sin «v236» | Pasa | Sección T7, paso 4 |
| REQ-016 (`doctor` real) | Pista de `dns`; con `192.0.2.1` ninguna pista «arranca llama-swap»; con el daemon, `backend` `OK` sin la clave en la consola | Pasa | Sección T7, pasos 5 y 6 |
| REQ-005, REQ-015 (daemon real) | `local_status` por MCP: «Backend: … — arriba» y `~640858 tokens netos (bruto ~688289)` | Pasa | Sección T7, paso 6 |
| REQ-022, REQ-024 (daemon real) | Delegación larga: fila «cargando» → «procesando»; título «En curso (1)» → «Última delegación» ~2 s tras el final | Pasa | Sección T7, paso 6 |
| REQ-034 (a)–(g) | Playwright: una sola familia en las `thead th`; `.selfchip` = `.mrole`; fila vacía de procesos = `.empty`; nota de hooks en Inter; primera columna de hooks y clientes en mono; botones con la familia del `body`; `JetBrains+Mono:wght@400` en el `href` | Pasa ((h) es de T4) | Sección T5 |

## T2 — Clasificador de la causa de conexión (ola 1)

### Ficheros

- `src/local_delegate/fallos.py` (LF, se conserva): `CausaConexion` (11 causas), `VistaBackend`,
  `causa_conexion(suceso, *, loopback)` con las 12 reglas en el orden de la spec (las 3 a 6
  recorren la cadena con un conjunto de visitados por identidad; un `int` 2xx lanza `ValueError`),
  `etiqueta`, `detalle` y `pista`. No se tocan `Clase`, `clasificar` ni `es_backend_ausente`.
- `tests/test_causa_conexion.py` (nuevo, LF): 45 tests.
- Ningún fichero tocado por la integración (la suite completa salió verde a la primera).

### Comandos y resultados

| Comando | Resultado |
| --- | --- |
| `bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider tests/test_causa_conexion.py tests/test_fallos.py --durations=5` | 87 passed en 4,47 s |
| Tiempos de red real (de `--durations`) | puerto recién liberado 2,01 s; `192.0.2.1` 0,51 s; `.invalid` 0,26 s: **2,78 s en total** (< 5 s) |
| `uv run ruff check src/local_delegate/fallos.py tests/test_causa_conexion.py` | All checks passed |
| `uv run ruff format --check src/local_delegate/fallos.py tests/test_causa_conexion.py` | 2 files already formatted |
| `git ls-files --eol src/local_delegate/fallos.py` antes y después | `i/lf w/lf` las dos veces; el test nuevo no tiene `\r` |
| `bash ~/.claude/scripts/pesado.sh uv sync --group ui --frozen` | instala `playwright`, `greenlet`, `pyee` |
| Integración: `bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider -rfEs` | **1497 passed, 2 skipped, 1 warning en 43,6 s**. Los dos skips: `test_checks.py:460` (chmod en Windows) y `test_dashboard_ui.py:249` (solo CI). El warning es una deprecación de `anyio` dentro de `starlette.testclient`, ajena al cambio |
| `node --check` del JS | No aplica: T2 no toca `web/metrics.py` |

### Control positivo

Control (b), mutante nombrado: la unidad no existía, así que contra el código de antes los tests
fallarían por `ImportError`, que no cuenta. Cada mutante se aplicó a `fallos.py` con un script
desechable (`scratchpad/t2/mutantes.py`, `mutantes2.py`, `mutante_ciclo.py`) que comprueba que el
texto a mutar aparece **una sola vez** (el mutante muta), corre solo los tests que lo deben cazar y
restaura el fichero byte a byte (comprobado con un `assert` al final y con `ruff`/pytest verdes
después).

| Mutante | Test que lo caza | Assert que disparó (copiado de pytest) |
| --- | --- | --- |
| 1. Intercambiar reglas 7 y 8 | `test_cada_suceso_tiene_su_causa[connect-timeout-en-loopback-es-rechazada]` y `[caso-de-la-mac-etimedout-en-loopback]` | `assert <CausaConexion.TIMEOUT_CONEXION: 'timeout_conexion'> is <CausaConexion.RECHAZADA: 'rechazada'>` |
| 2. Quitar la regla 4 | `[gaierror-es-dns]`, `[gaierror-en-loopback-sigue-siendo-dns]` y `test_red_real_un_nombre_que_no_resuelve_es_dns` | `assert <CausaConexion.TRANSPORTE: 'transporte'> is <CausaConexion.DNS: 'dns'>` (cae en la 11, también con la red real) |
| 3. La regla 1 solo mira `int` | `[http-status-401]`, `[http-status-403]` | `assert <CausaConexion.HTTP_ERROR: 'http_error'> is <CausaConexion.CREDENCIAL: 'credencial'>` |
| 4. Quitar la regla 12 (devuelve `None`) | `[attribute-error]`, `[key-error]`, `[propia-que-envuelve-connect-timeout]` | `assert None is <CausaConexion.DESCONOCIDA: 'desconocida'>` |
| 5. `pista` ignora el origen | `test_pista_remota_nunca_manda_a_arrancar_llama_swap_a_secas` | `assert 'arranca llama-swap' not in 'arranca lla...TE_BASE_URL)'` (causa `rechazada`) |
| 6. `pista` ignora la fuente | `test_pista_de_credencial_depende_de_quien_vio_el_401` | `assert 'lanzador' in 'exporta LOCAL_DELEGATE_API_KEY en este entorno'` |
| 7. `detalle` sin host (`host = ''`) | `test_todos_los_detalles_dicen_el_host` | `assert 'pc.tailnet.ts.net:9292' in 'no se resuelve el nombre  (¿VPN o DNS?)'` |
| 8. Sin la guarda del 2xx | `test_un_2xx_no_se_clasifica[200]`, `[204]`, `[299]` | `Failed: DID NOT RAISE ValueError` |
| 9. Etiqueta de `rechazada` cambiada a «caído» | `test_los_textos_son_los_de_la_tabla_de_req_011` | `assert 'caído' == 'nadie escucha'` |
| 10. `detalle` escribe el código sin mirar si es `None` | `test_un_detalle_sin_datos_opcionales_no_escribe_none` | `'None' is contained here: … responde None: está arriba pero rechaza la credencial` |
| 11. `pista(None)` no da la genérica | `test_pista_sin_causa_es_la_generica` | `assert 'arranca llama-swap' == 'revisa el ba...t.ts.net:9292'` |
| 12. `VistaBackend` con `causa` antes que `detalle` | `test_vista_backend_tiene_los_campos_de_req_016` | `At index 1 diff: 'causa' != 'detalle'` |
| 13. Sin el conjunto de visitados en `_cadena` | `test_una_cadena_con_ciclo_termina` | `AssertionError: la cadena con ciclo no terminó` / `assert not True` (el hilo sigue vivo a los 5 s; la prueba tardó 45 s en cerrar por la memoria que acumula el bucle) |

Guardas (no tienen mutante; vigilan el montaje de los demás tests):

- `test_un_oserror_sin_errno_no_es_sin_ruta`: `OSError(10051).errno is None`, con dos argumentos
  es 10051, y la clasificación da `transporte` y `sin_ruta` respectivamente (lo que el plan marcó
  como **comprobado**, ahora contra el código real).
- `test_el_montaje_de_los_casos_es_el_del_socket`: `OSError(ECONNREFUSED, …)` nace como
  `ConnectionRefusedError` y queda en `__cause__` de verdad.

### Desviaciones del plan

1. **`url_invalida` no lleva host en su detalle.** El plan pide que «todos los `detalle` contienen
   el host», pero la tabla de REQ-011 (textos exactos) da para `url_invalida` «la URL del backend
   no es válida (`<TipoDeExcepción>`): revisa LOCAL_DELEGATE_BASE_URL», sin host. Manda la spec:
   el bucle del test salta `url_invalida` y en su lugar comprueba que nombra
   `LOCAL_DELEGATE_BASE_URL`. Si se prefiere el host también ahí, es cambiar una línea del texto y
   la de su test.
2. **«Arranca llama-swap a secas» en remoto.** La pista remota de `rechazada` es, por la tabla de
   REQ-016, «arranca llama-swap en `<host>` o revisa el puerto», que contiene la subcadena
   «arranca llama-swap». El test quita primero «arranca llama-swap en `<host>`» y luego exige que no
   quede «arranca llama-swap». T3 ojo: su `test_doctor_remoto_no_manda_a_arrancar_llama_swap` usa
   `timeout_conexion`, donde el `assert "arranca llama-swap" not in hint` literal sí vale; con
   `rechazada` remoto fallaría.
3. **Comillas de los textos.** Los `` `<host>` ``, `` `<N>` `` y `` `<endpoint>` `` de las tablas se
   leen como marcadores: el texto lleva el valor sin comillas invertidas.
4. **Datos que faltan.** Sin `status`, `credencial` dice «`<host>` responde: está arriba…» y
   `http_error` «`<host>` responde con un error HTTP»; sin `endpoint`, `respuesta_invalida` omite
   «a `<endpoint>`»; sin `excepcion`, se omite el «(`<Tipo>`)». Si falta `status` y la excepción es
   un `HTTPStatusError`, el código se toma de su respuesta.
5. **Tolerancia de `pista`.** Una causa `None` (daemon antiguo) o un texto que no es una causa
   conocida da la pista genérica; solo `origen == "local"` cuenta como local y solo
   `fuente == "daemon"` como daemon, para que un valor raro nunca mande a arrancar llama-swap aquí.
   `etiqueta` y `detalle`, en cambio, lanzan `ValueError` con un texto que no es una causa.
6. **Casos añadidos** a la tabla del plan, sin cambiar ninguno: `EHOSTUNREACH`, Winsock 10065,
   `WriteTimeout`, `JSONDecodeError`, 403 por excepción, el caso de la Mac también en loopback
   (escenario «el caso de la Mac, sin la Mac»), una excepción propia que envuelve un
   `ConnectTimeout` (regla 12 determinista), y un ciclo de dos excepciones.
7. **Tests de red real con `trust_env=False`**, para que un proxy del entorno no cambie el fallo.
   El escenario «un puerto cerrado en otra máquina no parece una VPN» (IP propia no loopback) no
   está en la lista de T2 del plan y no se añadió.

## T1 — Contabilidad: fallos fuera, neto dentro, desglose y conversión única (ola 2)

### Ficheros

- `src/local_delegate/server.py` (CRLF, se conserva): `tokens_claude(cantidad, *, tipo, evento)`
  nueva, con la regla de hoy del contrato (un `tipo` desconocido lanza `ValueError`);
  `_accounting` reescrita según la Regla de contabilidad (devuelve todos los campos del contrato:
  `returned`, `net`, `chars_saved_text`, `bytes_saved_image`, `chars_saved_output`,
  `chars_returned`, `failed`, `tool`, `model`, `source`, `unit`, más los de siempre); bloque de
  ahorro de `local_status` (`contexto conservado: ~N tokens netos (bruto ~M)`).
- `src/local_delegate/web/metrics.py` (CRLF, se conserva): `_aggregate` (predicado
  `acc["failed"]`, totales y desglose, `tokens_returned`, `tokens_context_net`, `tokens_net` en
  `by_tool`/`by_backend`/`by_client`); JS `tokensClaude` nueva, `acct` reescrita, KPI hero con el
  neto y la pista «bruto X − devuelto Y», respaldo de `errs`, `byDay` (clave `net`), `drawSpark`,
  `drawTs`, `agg` (cuarto argumento `opts.conNegativos`), `drawToolDonut`, columna de
  `renderClients` y, en la tabla de actividad, el predicado del punto y el del `title` de la causa.
- `tests/test_metrics.py` (LF): 14 tests nuevos y 3 actualizados (ver abajo).
- `tests/test_dashboard_js.py` (LF): 3 tests nuevos; listas de extracción de los dos de `byDay`
  (+ `function tokensClaude(`) y cabecera de extracción de los dos de `agg`.
- Ningún fichero tocado por la integración (la suite completa salió verde a la primera).

### Comandos y resultados

| Comando | Resultado |
| --- | --- |
| `bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider tests/test_metrics.py tests/test_dashboard_js.py tests/test_boilerplate_salida.py` | **95 passed** |
| `uv run python -c "…write_text(…re.findall(r'<script>(.*?)</script>', m.HTML, re.S)…)" <scratchpad>/t1/panel.js` y `node --check <scratchpad>/t1/panel.js` | sin errores |
| `uv run ruff check` y `uv run ruff format --check` sobre los cuatro ficheros | All checks passed / 4 files already formatted |
| `git ls-files --eol` de los cuatro ficheros, antes y después | `server.py` y `metrics.py` `i/crlf w/crlf` (0 LF sueltos, contado por bytes); los dos tests `i/lf w/lf` sin `\r` |
| Integración: `bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider -rfEs` | **1514 passed, 2 skipped, 1 warning en 41,5 s** (1497 de T2 + 17 nuevos). Skips y warning, los mismos de T2 |

### Control positivo

**(a) contra el código de antes.** Los 15 tests se escribieron y corrieron antes de tocar el
código (`-k` con sus nombres): fallaron los 15, cada uno en el assert indicado.

| Test | Assert que disparó (salida de pytest) |
| --- | --- |
| `test_accounting_un_fallo_no_ahorra_ni_genera` | `assert a["saved"] == 0` → `assert 1000 == 0` |
| `test_accounting_un_fallo_no_es_una_estimacion` | `assert a["estimated"] is False` → `assert True is False` |
| `test_accounting_fallo_troceado_conserva_el_coste_real` | `assert a["saved"] == 0` → `assert 1000 == 0` |
| `test_accounting_neto_resta_lo_devuelto` | `assert a.get("returned") == 100` → `assert None == 100` |
| `test_accounting_salida_a_fichero_no_descuenta_el_recibo` | `assert a.get("net") == 950` → `assert None == 950` |
| `test_accounting_el_neto_puede_ser_negativo` | `assert a.get("net") == -100` → `assert None == -100` |
| `test_accounting_desglosa_en_caracteres` | `assert a.get("chars_saved_text") == 4000` → `assert None == 4000` |
| `test_stats_el_log_sintetico_de_la_mac_no_infla_nada` | `assert j["estimated_events"] == 0` → `assert 4 == 0` |
| `test_stats_ok_null_no_cuenta_como_error` | `assert j["total"]["errors"] == 0` → `assert 1 == 0` |
| `test_stats_expone_el_desglose_en_caracteres` | `assert j.get("chars_saved_text") == 4000` → `assert None == 4000` |
| `test_stats_quien_delego_trae_el_neto` | `assert fila.get("tokens_net") == 900` → `AssertionError: el fallo no suma y el devuelto se resta` |
| `test_el_js_usa_un_solo_predicado_de_fallo` | `assert "!e.ok" not in html` |
| `test_local_status_cuenta_el_neto_como_el_panel` | `assert esperado in texto` → `'~(falta tokens_context_net) tokens netos' in 'local-delegate v0.32.0…'` (sin `TypeError`) |
| `test_dashboard_js.py::test_agg_con_negativos_conserva_las_herramientas_por_debajo_de_cero` | `assert ["b", -100] in resultado` → `['b', -100] in [['a', 500]]` |
| `test_dashboard_js.py::test_la_chispa_admite_negativos` | `assert "min:0" not in fuente` |

**(c) contra el corte intermedio, paridad.** Paso 1 hecho (`tokens_claude` y `tokensClaude` sin
llamadas; los 77 tests de antes de los tres ficheros en verde), `_accounting` ya cambiado y `acct`
sin cambiar: `test_paridad_acct_entre_python_y_el_js_del_panel` falló en
`assert js.get(campo_js) == py[campo_py]` con `('returned', …)` y `assert None == 100`, en el
primer caso (el JS trae `tokensIn: 1100, saved: 1000`: «neto positivo»).

**(b) mutantes nombrados.** Cada uno se aplicó con `scratchpad/t1/mutar.py` (reemplazo exacto y
único, corre el test, restaura el fichero byte a byte y lo comprueba):

| Mutante | Por qué muta | Test y assert que disparó |
| --- | --- | --- |
| JS `const failed = e.ok===false;` → `const failed = !e.ok;` | con `ok: null` el JS pasa a tratarlo como fallo | paridad: `('returned', …)`, `assert 0 == 100`; el JS trae `tokensIn: 0, saved: 0`, o sea el caso `ok: null` (el primero que distingue: los tres anteriores dan lo mismo con los dos predicados) |
| Python: `saved += tokens_claude(chars_saved_text, tipo="text", evento=row)` → `saved += chars_in // config.CHARS_PER_TOKEN` | el ahorro de texto deja de pasar por el doble que devuelve 7 | `test_tokens_claude_es_la_unica_conversion`: `assert a["saved"] == 7` → `assert 1000 == 7` |
| JS: `saved += tokensClaude(charsSavedText,'text',e);` → `saved += tok(ci);` | ídem en el JS | `test_acct_convierte_solo_con_tokensClaude`: `assert r["saved"] == 7` → `assert 1000 == 7` |

**Guarda de la paridad (REQ-001).** Con los 12 casos sale verdadera en sus cinco condiciones
(`net < 0`, fallo con `tokens_in > 0`, caso sin clave `ok`, `bytes_saved_image > 0`,
`chars_saved_output > 0`), más las dos de F3 que ya tenía (`fallback`, `cause == "configuracion"`).

**Trampa de `byDay`, comprobada.** Con `acct` ya llamando a `tokensClaude` y las listas de
extracción sin actualizar, los dos tests de `byDay` fallaron con `CalledProcessError`; node dice
`ReferenceError: tokensClaude is not defined`. Con `function tokensClaude(` en la lista, pasan.

### Tests actualizados a propósito

- `test_accounting_una_llamada_sin_trocear`: el dict entero lleva los campos del contrato.
- `test_paridad_acct_entre_python_y_el_js_del_panel`: los 12 casos de REQ-001 en el orden del plan,
  y detrás los de antes que cubren otras ramas (troceado bueno, estimado, `chars_in` impar, imagen
  histórica sin `input_unit`, `inline`, y los tres de F3). Compara los 18 campos con `js.get(...)`
  empezando por `returned`. El caso de fallo troceado que antes esperaba ahorro (research §8) es
  ahora el tercero de los 12.
- `test_local_status_y_el_dashboard_cuentan_igual`: busca `(bruto ~{tokens_context_saved})`.

### Cifras de septiembre, recomputadas a mano

`uv run python <scratchpad>/t1/septiembre.py`: lee `usage-202609.jsonl` de esta PC (solo lectura,
no imprime rutas) y lo agrega con `metrics._aggregate` y `server._accounting` del árbol de trabajo.
El log no va a los tests.

| Cifra | Spec | Recalculada |
| --- | --- | --- |
| Texto (`chars_saved_text`) | 3 463 739 | 3 463 739 |
| Imagen (`bytes_saved_image`) | 1 489 047 bytes, 5 imágenes | 1 489 047, 5 |
| Salida a fichero (`chars_saved_output`) | 5 237, 3 eventos | 5 237, 3 |
| Devuelto (`chars_returned`) | 289 554 | 289 554 |
| Bruto (`tokens_context_saved`) | 873 270 | 873 270 |
| Devuelto (`tokens_returned`) | 72 342 | 72 342 |
| Neto (`tokens_context_net`) | 800 928 | 800 928 |
| Estimados | 0 | 0 |

143 eventos, 7 fallos; `neto == bruto − devuelto`.

### Desviaciones del plan

1. **Cabecera de extracción de `agg`**: `agg` gana un cuarto argumento (`opts`), así que los dos
   tests de `agg` que ya existían extraen con `"function agg(ev,key,valfn"` (sin `){`), igual que el
   nuevo. Sin eso `_extraer` habría dado `ValueError`. Su comportamiento sin la opción no cambia.
2. **Tabla de actividad**: además del punto, el `title` de la causa usaba `!e.ok`; pasa a
   `e.ok===false` (es el mismo predicado de REQ-006, y `test_el_js_usa_un_solo_predicado_de_fallo`
   prohíbe `!e.ok` en todo el HTML).
3. **Chispa**: se quita `min:0` y se pone `suggestedMin:0`. Con datos positivos el 0 sigue en el
   borde inferior (lo que hacía `min:0`), y con un acumulado negativo el eje baja.
4. **Textos junto a valores que cambian de significado**: la serie de `drawTs` pasa de «tokens
   ahorrados» a «tokens netos» y la cabecera de «Quién delegó» de «Tokens ahorrados» a «Tokens
   netos». La redacción final de cabeceras es de T5.
5. **`tokens_claude` con un `tipo` desconocido** lanza `ValueError` (JS: `throw`). La spec no lo
   dice; protege contra una errata en las llamadas.
6. **`returned`** se calcula como dice la regla, `tokens_claude(chars_returned, tipo="returned")`
   en todo evento bueno, aunque `chars_returned` sea 0. Con la función de hoy da 0; la sustituta de
   `coste-api-y-cuota` (`cantidad × 100 // c100`) también.
7. `test_stats_ok_null_no_cuenta_como_error` y `test_stats_quien_delego_trae_el_neto` llaman a
   `_aggregate` directamente (es lo que `/api/stats` devuelve tal cual); los otros dos de stats van
   por HTTP.

### Para T3 y siguientes

- `server.py`: la zona de T1 queda en `tokens_claude`, `_accounting` y el bloque de ahorro de
  `local_status`. La línea `Backend:` de `local_status` sigue intacta para T3.
- `scripts/dev/capture_dashboard.py` (T6) simula `/api/stats` sin `tokens_context_net`,
  `tokens_returned` ni `tokens_net` en `by_client`: la captura enseñaría el KPI a 0 y «NaN» en la
  columna de «Quién delegó». T6 tiene que añadirlos.
- `docs/wiki/Savings-and-metrics.md:166` (T6) lista las claves de `/api/stats`: faltan las nuevas.
- T5: la pista del KPI usa `F.format` y `<span class="num">`; cuando cambie el formateador, el
  escenario del KPI (`800.928`, `873.270`, `72.342`) es el que lo comprueba en navegador.

## T3 — Sondeo con causa, delegación, plazo de conexión y `doctor` (ola 3)

### Ficheros

- `src/local_delegate/config.py` (LF): `TIMEOUT_SONDA_CONEXION = 3.0`, `TIMEOUT_SONDA_LECTURA = 2.0`,
  `TIMEOUT_CONEXION_DELEGACION = 10.0`, constantes sin variable de entorno.
- `src/local_delegate/server.py` (CRLF, se conserva; 0 LF sueltos): `_get_client` con
  `httpx2.Timeout(HTTP_TIMEOUT, connect=min(10, HTTP_TIMEOUT))`; `ChatResult.fallo_conexion`;
  `_log_event(fallo_conexion=…)`, que escribe la clave solo si no es `None`; `_backend_en_loopback`
  (host real sin puerto); `_post_chat`: con origen remoto ni pregunta ni autoarranque, y el texto
  `no se pudo conectar con el backend: <detalle>` con la causa; `_inflight_espera_local(entry_id,
  motivo)` y `_run_chat(entry_id=…)` con `acquire(blocking=False)`; `_ModeloVigente(entry_id)` y
  `campos_de_log` con `fallo_conexion`; `_con_respaldo` conserva el campo al combinar;
  `EstadoBackend`, `_LISTAS_BUENAS` (por `BASE_URL`), `sondear_backend`, `_sondeo_fallido`,
  `_plazo_sonda`; `_models_with_status` queda como envoltorio; `_llamaswap_running` con el plazo de
  sondeo; `local_status` con `_estado_backend_en_texto` y `/running` solo si `/models` respondió;
  `inflight_snapshot` copia `espera_local` cuando la hay (ver desviación 8).
- `src/local_delegate/doctor.py` (LF): `backend_probe()` devuelve `fallos.VistaBackend` con causa,
  plazo de sondeo y `fuente="directo"`.
- `src/local_delegate/checks.py` (LF): `_default_backend_models` consulta al daemon con
  `httpx2.Timeout(6, connect=1.0)` y usa su `causa`/`detalle` (daemon antiguo: texto de hoy y
  causa `None`); `Context.backend_models` tipado como `VistaBackend`; `_probe_backend_models`
  decide la severidad por causa y fuente, y la pista con `fallos.pista`.
- Tests: `tests/test_sondeo_backend.py` y `tests/test_delegacion_conexion.py` (nuevos, LF);
  `tests/conftest.py` (fixture autouse `sin_lista_de_modelos_guardada`, que lee `server` de
  `sys.modules` sin importarlo); `tests/test_checks.py`, `tests/test_doctor.py` y
  `tests/test_update.py` (dobles a `VistaBackend` y tests nuevos);
  `tests/test_observabilidad_respaldo.py` (la fixture `status_sin_red` dobla `sondear_backend`);
  `tests/test_fallos_integracion.py` y `tests/test_post_chat_caminos.py` (origen fijado y casos
  remotos).
- Ningún fichero tocado por la integración fuera de la lista (la suite completa salió verde a la
  primera). `.sdd/changes/coste-api-y-cuota/plan.md` sale modificado en `git status`, pero no es
  de T3 (otra sesión).

### Paso 0: medición antes de fijar el control de REQ-013

Script `scratchpad/t3/paso0.py`: IP de la interfaz de salida por UDP «conectado» a `192.0.2.1:9`
(`<IP de la LAN>`), un puerto libre en ella (bind y cierre), y `GET /v1/models` con 3 s y 1 s de
conexión, dos veces cada uno, más la clasificación con `fallos.causa_conexion(…, loopback=False)`.

| Plazo de conexión | Tiempo | Excepción | Causa |
| --- | --- | --- | --- |
| 3 s | 2,10 s y 2,02 s | `ConnectError` | `rechazada` |
| 1 s | 1,00 s y 1,01 s | `ConnectTimeout` | `timeout_conexion` |

Con 1 s **sí** sale `ConnectTimeout`, así que el mutante «plazo 1,0» muta y el control de REQ-013
es el del plan, `test_un_puerto_cerrado_remoto_no_parece_una_vpn`. No hizo falta el test sustituto.

### Paso 1: inventario de los tests que REQ-018 deja sin efecto

`rg -n "ArrancarBackend|ensure_backend|ofreció arrancar|ofrecer|preguntas.preguntar|\"preguntar\"|AUTOSTART" tests/`:

- **Ejercitan la pregunta o el autoarranque a través de `_post_chat` con la URL remota de los
  fixtures**: `tests/test_fallos_integracion.py` (fixture `backend`;
  `test_connect_timeout_ofrece_arrancar_el_backend` y
  `test_connect_error_se_comporta_igual_que_siempre` esperan la pregunta;
  `test_read_timeout_no_ofrece_arrancar_nada` y
  `test_un_error_de_transporte_cualquiera_sigue_siendo_del_endpoint` esperan que no) y
  `tests/test_post_chat_caminos.py` (`test_todos_los_caminos_devuelven_un_resultado`). En los dos
  se fija `config.BACKEND_ORIGIN_OVERRIDE = "local"` sin cambiar la URL.
- **No dependen de la pregunta de arranque** (comprobado leyéndolos): `test_respaldo.py:155`
  (`test_el_backend_caido_no_salta_ni_enfria`, dobla la pregunta a `None` y no la comprueba),
  `test_respaldo.py:421`, `test_rol_fast_retirado.py:122,133` y `test_preguntas.py:228-307`
  (elección de modelo y `output_format`), `test_core.py:135` (`connect_error` sin autoarranque, no
  mira la pregunta), y los `AUTOSTART=False` de `test_ctrl_c.py`, `test_daemon.py`,
  `test_sonda_carga.py` y `test_smoke.py` (apagan el autoarranque, no lo prueban).
- `test_la_lista_de_caminos_cubre_todas_las_ramas` sigue pidiendo 7: REQ-018 es una condición
  sobre las ramas existentes, sin `return ChatResult(` nuevo.

### Comandos y resultados

| Comando | Resultado |
| --- | --- |
| Corte de interfaz (paso 2): `bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider tests/test_checks.py tests/test_doctor.py tests/test_update.py tests/test_fallos_integracion.py tests/test_post_chat_caminos.py tests/test_observabilidad_respaldo.py tests/test_metrics.py tests/test_respaldo.py tests/test_aislamiento_entorno.py` | 331 passed, 1 skipped |
| Tests nuevos contra el corte (controles (a) y (c)): `… pytest -q --tb=short tests/test_sondeo_backend.py tests/test_delegacion_conexion.py tests/test_checks.py tests/test_doctor.py tests/test_post_chat_caminos.py tests/test_fallos_integracion.py` | 34 failed, 156 passed, 1 skipped (`scratchpad/t3/antes.txt`); los asserts, abajo |
| Verificación del plan: `bash ~/.claude/scripts/pesado.sh uv run pytest -p no:cacheprovider -q tests/test_sondeo_backend.py tests/test_delegacion_conexion.py tests/test_checks.py tests/test_doctor.py tests/test_fallos_integracion.py tests/test_post_chat_caminos.py tests/test_update.py tests/test_observabilidad_respaldo.py tests/test_respaldo.py tests/test_metrics.py --durations=8` | **365 passed, 1 skipped en 19,5 s**. `tests/test_metrics.py` en verde **sin tocarlo**. Duraciones: delegación sin ruta 10,01 s; puerto cerrado remoto 2,01 s; `.invalid` 0,23 s |
| Mutantes: `bash ~/.claude/scripts/pesado.sh uv run python scratchpad/t3/mutantes.py` | 13 mutantes, los 13 cazados; cada uno comprueba que el texto a mutar aparece una vez y restaura el fichero byte a byte (`assert` al final) |
| `uv run ruff check .` y `uv run ruff format --check .` | All checks passed; 130 files already formatted |
| `git ls-files --eol` de los once ficheros tocados, antes y después | el mismo EOL; `server.py` `i/crlf w/crlf` con 0 LF sueltos; los dos tests nuevos sin `\r` |
| Integración: `bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider -rfEs` | **1553 passed, 2 skipped, 1 warning en 52,8 s** (tras la desviación 8; antes de ella, 1552 en 55,2 s). Skips y warning, los de siempre (`test_checks.py:462` chmod en Windows, `test_dashboard_ui.py:249` solo CI, deprecación de `anyio` en `starlette.testclient`) |
| `node --check` del JS | No aplica: T3 no toca `web/metrics.py` |

### Control positivo

**(a) contra el código de antes** (el del corte de interfaz, que no cambia comportamiento). Assert
que disparó, copiado de `antes.txt`:

| Test | Assert que disparó |
| --- | --- |
| `test_local_status_dice_sin_acceso_con_un_401` | `assert 'SIN ACCESO' in '…Backend: http://test-backend/v1 — CAÍDO…'` |
| `test_local_status_no_llama_caido_a_quien_contesta` | `assert 'CAÍDO' not in 'Backend: ht...d/v1 — CAÍDO'` |
| `test_local_status_dice_que_no_se_resuelve` | `assert 'no se resuelve el nombre no-existe.invalid:9292' in '…— CAÍDO…'` |
| `test_local_status_no_pide_running_si_models_falla` | `assert 1 == 0` (`Ruta.call_count`) |
| `test_sondeo_conserva_la_ultima_lista_buena` (vía `_models_with_status`) | `assert [] == ['a', 'b']` |
| `test_el_plazo_de_conexion_de_las_delegaciones_es_de_10_s` | `assert 180.0 == 10.0` |
| `test_una_delegacion_sin_ruta_se_rinde_en_10_s` | `AssertionError: tardó 21.1 s en rendirse` / `assert 21.06 < 13` |
| `test_delegacion_remota_no_pregunta_ni_arranca[sin-autoarranque]` | `assert ['El backend local no responde en test-backend. ¿Lo arranco?'] == []` |
| `test_delegacion_remota_no_pregunta_ni_arranca[con-autoarranque]` | `assert [30] == []` |
| `test_el_error_de_conexion_dice_la_causa_y_va_al_log` (`simple`, `troceada-map-reduce`, `troceada-por-trozos`, `imagen`) | los cuatro: `assert None == 'timeout_conexion'` (`linea.get('fallo_conexion')`) |
| `test_inflight_marca_la_espera_local` | `assert None == 'plaza'` (`entrada.get('espera_local')`) |
| `test_el_snapshot_de_en_curso_lleva_la_espera_local` | `assert None == 'plaza'` (`por_id[...].get('espera_local')`) |
| `test_todos_los_caminos_devuelven_un_resultado[remoto + ConnectError]` y `[remoto + ConnectTimeout con autoarranque]` | `AssertionError: se ofreció arrancar un backend remoto` / `assert ([30] == [] …` |
| `test_doctor_usa_la_causa_que_da_el_daemon` | `assert 'no se resuelve el nombre pc.lan' in 'http://pc.lan:9292/v1/models no responde (según el daemon, que sí tiene credencial) (backend caído)'` |
| `test_doctor_401_del_daemon_apunta_al_lanzador` | `assert 'lanzador' in 'arranca llama-swap (o revisa LOCAL_DELEGATE_BASE_URL)'` |
| `test_doctor_con_daemon_antiguo_usa_el_texto_de_hoy` | `assert False` (`fix_hint.startswith('revisa el backend en ')`) |
| `test_backend_probe_sin_daemon_dice_dns` | `assert 'no se resuelve' in 'no responde (ConnectError)'` |

**(c) contra el corte intermedio** (paso 2: `VistaBackend` con `causa=None` y el comportamiento de
hoy; las constantes ya existen):

| Test | Assert que disparó |
| --- | --- |
| `test_backend_probe_usa_el_plazo_de_sondeo` | `assert 2.0 == 3.0` (`config.TIMEOUT_SONDA_CONEXION`) |
| `test_doctor_remoto_no_manda_a_arrancar_llama_swap` | `assert 'arranca llama-swap' not in 'arranca lla...TE_BASE_URL)'` |
| `test_doctor_espera_al_daemon_mas_que_su_sondeo` | `assert 1.0 > (3.0 + 2.0)` |

**(b) mutante nombrado** (`scratchpad/t3/mutantes.py`; cada mutante comprueba que su texto aparece
una sola vez, que es como se sabe que muta):

| Mutante | Por qué muta | Test | Assert que disparó |
| --- | --- | --- | --- |
| Quitar el origen fijado de `_preparar_camino` (el montaje que comparten los dos tests de caminos) | la lista entera pasa a origen remoto y REQ-018 cierra las dos ramas | `test_el_autoarranque_sigue_cubierto` | `assert 0 >= 1` (`llamadas_ensure_backend`) |
| La lista guardada en una ranura única (`_LISTAS_BUENAS["unica"]`, escritura y lectura) | la URL deja de importar | `test_la_lista_guardada_es_de_su_url` | `assert [{'id': 'de-a', 'status': None}] == []` |
| Sin validar la forma (`data = cuerpo.get("data", [])`, como antes) | `[]` da `AttributeError` y `{}` da «disponible» | `test_un_cuerpo_con_otra_forma_es_respuesta_invalida` | `[lista]`: `assert 'desconocida' == 'respuesta_invalida'`; `[sin-data]` y `[data-texto]`: `assert True is False` (`available`) |
| `loopback` con `config.backend_host()` (lleva el puerto) | `_is_loopback_host("127.0.0.1:9292")` es `False` | `test_un_connect_timeout_en_loopback_es_rechazada` | `assert 'timeout_conexion' == 'rechazada'` |
| `TIMEOUT_SONDA_CONEXION = 1.0` | el paso 0: con 1 s llega `ConnectTimeout` | `test_un_puerto_cerrado_remoto_no_parece_una_vpn` (red real) | `assert 'timeout_conexion' == 'rechazada'` |
| `_get_client` sin el `min` | 10 > 5 | `test_el_plazo_de_conexion_no_supera_el_total` | `assert 10.0 == 5.0` |
| La consulta al daemon vuelve a `timeout=1.0` | 1 < 6 | `test_doctor_espera_al_daemon_mas_que_su_sondeo` | `assert 1.0 > (3.0 + 2.0)` |
| `_sondeo_fallido` con `models_stale=False` | cambia el campo que mira el assert | `test_el_sondeo_fallido_marca_la_lista_como_vieja` | `assert False is True` (`.models_stale`) |
| El 401 sin `status_http` | cambia el campo que mira el assert | `test_un_401_es_credencial_y_no_disponible` | `assert None == 401` |
| El sondeo solo captura `(HTTPError, ValueError)` | un `RuntimeError` escapa | `test_el_sondeo_nunca_lanza` | `Failed: el sondeo lanzó RuntimeError('inesperado')` |
| Sin el filtro `isinstance(m, dict)` en `data` | `'str'.get` da `AttributeError`, que el sondeo clasifica | `test_las_entradas_sueltas_se_toleran_como_hoy` | `assert False is True` (`available`, causa `desconocida`) |
| `_log_event` escribe `fallo_conexion` siempre | con `None` saldría `null` | `test_un_fallo_que_no_es_de_conexion_no_escribe_la_clave` | `assert 'fallo_conexion' not in {…}` |
| `_run_chat` escribe `espera_local: "plaza"` también con plaza libre | la entrada gana la clave | `test_sin_espera_no_se_escribe_nada_de_mas` | `assert (… and 'espera_local' not in {…})` |

Guardas (pasan antes y después, vigilan el montaje):

- `test_delegacion_local_sigue_preguntando` (REQ-018 con origen local: una pregunta) y los cuatro
  tests de `test_fallos_integracion.py`, ahora con origen local.
- `test_backend_401_is_unknown_not_down` y `test_backend_down_is_warn` con sus dobles en
  `VistaBackend`; el del 401 lleva `causa="credencial"` y el texto de siempre, así que pasa en el
  corte (por el prefijo) y después (por la causa).
- En `_troceada_map_reduce`, un espía exige que el caso pase de verdad por `_chat_map_reduce`.

### Desviaciones del plan

1. **Cuatro caminos en vez de tres** en `test_el_error_de_conexion_dice_la_causa_y_va_al_log`. Las
   llamadas a `_log_event` son tres, pero no las que nombra el plan: `_chat` (simple **e imagen**,
   porque `local_describe_image` pasa por `_chat`), `_chat_chunked` y `_chat_map_reduce`. «Troceada»
   con `local_summarize` va por map-reduce; se añadió `local_translate` para cubrir
   `_chat_chunked`. Las dos troceadas toman `fallo_conexion` de `_ModeloVigente.campos_de_log`.
2. **`Result` no tiene `message` ni `hint`**: los tests usan `r.detail` y `r.fix_hint`, que son
   los campos reales de `checks.Result`.
3. **Detalle del check `service.backend`**: pasa de `<URL>/models <motivo> (backend caído)` a
   `<URL>/models: <detalle>`. El «(backend caído)» era falso para las causas en las que alguien
   contesta. Ningún test ni doc citaba ese texto (buscado en `tests/`, `docs/`, `README.md`).
4. **`doctor.backend_probe` con 401** ya no dice «(¿falta LOCAL_DELEGATE_API_KEY en este
   entorno?)» en el detalle: ese consejo es ahora la pista de `credencial` con fuente `directo`
   («exporta LOCAL_DELEGATE_API_KEY en este entorno»), como pide REQ-011.
5. **La lista de modelos se arma dentro del `try`** de `sondear_backend`. Lo destapó el mutante de
   la tolerancia: armada fuera, un `AttributeError` ahí se escapaba del sondeo, contra el «nunca
   lanza» de REQ-012. El `ValueError` de la forma lleva `# noqa: TRY004`, porque la regla 10 pide
   `ValueError`.
6. **`daemon.query_backend` recibe un `httpx2.Timeout`** aunque su anotación dice `float`
   (`daemon.py` no está en la lista de T3). En tiempo de ejecución `httpx2.Client(timeout=…)`
   acepta las dos cosas; la anotación queda por ajustar.
7. **Tests añadidos** a la tabla del plan, sin cambiar ninguno:
   `test_el_sondeo_fallido_marca_la_lista_como_vieja`, `test_un_401_es_credencial_y_no_disponible`,
   `test_el_sondeo_nunca_lanza`, `test_un_fallo_que_no_es_de_conexion_no_escribe_la_clave`,
   `test_sin_espera_no_se_escribe_nada_de_mas`, `test_doctor_con_daemon_antiguo_usa_el_texto_de_hoy`,
   y en `test_post_chat_caminos.py` el assert de que los dos caminos remotos no preguntan ni
   arrancan. El parametrizado de cuerpo inválido cubre también `{}` y `data` que no es lista.
8. **`inflight_snapshot()` copia `espera_local`**. No está en la zona de T3 del plan, pero es la
   parte de servidor de REQ-022: `/api/inflight` sirve esa función, que copia los campos uno a
   uno, y sin esto el campo se quedaba en `inflight.json` sin llegar nunca al panel. T4 no tiene
   `server.py` en su zona, así que no habría podido arreglarlo. Test nuevo
   `test_el_snapshot_de_en_curso_lleva_la_espera_local`, control (a).

### Para T5 y T4

- **T4**: `server.sondear_backend()` devuelve `EstadoBackend(available, models, models_stale,
  causa, detalle, status_http)`. `/api/backend` y `/api/status` (en `web/metrics.py`, donde llaman
  a `_models_with_status`) siguen con el envoltorio y les faltan `causa`, `detalle`,
  `models_stale` y `running_ok`. Para REQ-013 en `/api/backend`: pedir `/running` solo si
  `available`, y usar `server._plazo_sonda()` en `/running` y en `/api/metrics/stats`, que en
  `metrics.py` llevan hoy sus propios plazos. La lista guardada ya viene con `status: None`; la
  fixture autouse de `conftest.py` la vacía entre tests. `inflight_snapshot()` (lo que sirve
  `/api/inflight`) ya trae `espera_local` cuando la hay, con el motivo como texto (hoy `"plaza"`).
- **T5**: nada de T3 cambia números ni textos del panel. El texto de `connect_error` y la clave
  `fallo_conexion` del log son nuevos; la tabla de actividad puede usarlos para el `title`.
- **T6**: el CHANGELOG debe contar el nuevo texto de `connect_error`, que con origen remoto ya no
  se pregunta ni se autoarranca, el plazo de conexión de 10 s, la línea `Backend:` de
  `local_status` con cuatro estados, y el nuevo detalle y pistas de `doctor`.

## T5 — Presentación: números, latencia, plurales y tipografía (ola 4)

### Ficheros

- `src/local_delegate/web/metrics.py` (CRLF, se conserva; 0 LF sueltos). CSS: `JetBrains+Mono`
  pide `400;500;600;700`; `button,input,select,textarea{font-family:inherit}` tras
  `*{box-sizing:border-box}`; `td.mono` sin `th.mono`; `.selfchip` con `var(--sans)`; clase nueva
  `.nota` (Inter, 12,5 px, `--mut`, alineada a la izquierda) para la nota de hooks y la remota de T4.
  JS: `F = {format: n => fmtNum(n, 0)}` dentro de `const CPT = 4, F = …, PAGE = 10;`, `F1`,
  `fmtNum`, `fmtSeg` y `plural` justo debajo. Aplicados: pie («N eventos», «N archivos leídos»),
  porcentajes de hooks y clientes, cabeceras sin `class="num"`/`"mono"` (hooks, motivos, clientes
  y actividad), primera columna de hooks, motivos y clientes con `class="mono"`, nota de hooks con
  `.nota`, números de `renderBackendStats` (tok/s con `F1`, «–» sin dato), segundos de «En curso»
  y de la última terminada con `fmtSeg`, GiB de `fmtMB` y de los medidores de RAM/VRAM con `F1`,
  celda de proceso `<td class="mono">` sin estilo *inline*, fila vacía de procesos con `.empty`,
  título del indicador («1 delegación / 2 delegaciones»), KPI «Latencia media» con `fmtSeg`, tasa
  de error con `F1`, «N estimados», «1 fallo / N fallos», columna de latencia de la actividad con
  `fmtSeg` y «N llamadas» del contador de actividad.
- `tests/test_dashboard_js.py` (LF): 5 tests de formato (`_formateadores`, `_SIN_INTL_V3`).
- `tests/test_dashboard_ui.py` (CRLF, se conserva; 0 LF sueltos): `_tam_pagina` lee `PAGE` con una
  regex (la marca vieja llevaba la definición de `F` dentro); fixture de módulo `medidas` que pinta
  el panel una vez (log real de dos eventos; hooks y procesos con `page.route`; fuentes de Google
  abortadas) y 10 tests, uno por arreglo.
- **Tocado por la integración**: `tests/test_hooks_telemetry_api.py` (LF, fuera de la lista de
  T5). `test_la_tarjeta_se_esconde_cuando_no_hay_telemetria` ejecuta `renderHooks` con node y solo
  definía `F` con `Intl`; ahora `renderHooks` usa `F1`. Se extrae `fmtNum` del HTML y se definen
  `F` y `F1` igual que el panel. Sus asserts no cambian (`30,0 %`, `25,0 %`).

### Controles positivos

Antes de cambiar el código (`pytest … -k …`, 15 failed): cada test nuevo falló así.

| Test | Control | Assert que disparó |
|---|---|---|
| `test_F_agrupa_los_miles_desde_cuatro_cifras` | (a) | `assert r == "8.003"` → `'8003' == '8.003'` |
| `test_F_agrupa_aunque_el_navegador_no_tenga_Intl_v3` | (a) y (b) | (a) `'8003' == '8.003'`. (b) mutante `F = new Intl.NumberFormat('es',{useGrouping:'always'})`: falla este (`'8003' == '8.003'`) y **pasa** el de arriba sin emulación, que es la prueba de que el mutante muta solo donde dice el plan |
| `test_decimales_con_coma_y_latencia_en_segundos` | (b) | Antes: `CalledProcessError` (no existía `fmtSeg`, esperado en un (b)). Mutante «`F1` sin agrupar»: `assert r["f1"] == "1.718,3"` → `'1718,3'`. Mutante «`fmtSeg` sin el caso de 50 ms»: `assert r["seg"][2] == "< 0,1 s"` → `'0,0 s'` |
| `test_plural_sin_parentesis` | (b) | Antes: `CalledProcessError` (no existía `plural`). Mutante «siempre plural»: `assert r[0] == "1 estimado"` → `'1 estimados'` |
| `test_no_quedan_plurales_con_parentesis_ni_toFixed` | (a) | `assert "estimado(s)" not in html` (el primero de los cinco) |
| `test_todas_las_cabeceras_comparten_familia` | (a) | `assert len(familias) == 1` → `2 == 1` (Inter y JetBrains Mono) |
| `test_la_chip_del_daemon_va_como_sus_gemelas` | (a) | `assert medidas["selfchip"] == medidas["mrole"]` → mono contra Inter |
| `test_la_fila_vacia_de_procesos_va_como_los_demas_vacios` | (a) | `assert medidas["procesosVacia"] == medidas["empty"]` → Inter contra mono |
| `test_la_nota_de_hooks_es_prosa_en_Inter` | (a) | `assert medidas["nota"].startswith("Inter")` → era JetBrains Mono |
| `test_la_primera_columna_de_hooks_y_clientes_va_en_mono` | (a) | `assert "JetBrains Mono" in medidas["hooksPrimera"]` → era Inter |
| `test_los_botones_heredan_la_familia_del_body` | (a) | `assert medidas["cerrarAyuda"] == medidas["body"]` → `'Arial'` (ver desviación 1: el de «Refrescar» pasaba) |
| `test_la_hoja_de_fuentes_pide_JetBrains_Mono_400` | (a) | `assert "JetBrains+Mono:wght@400" in …` → `…JetBrains+Mono:wght@500;600;700…` |
| `test_el_KPI_hero_ensena_el_neto_y_la_pista_el_bruto_y_el_devuelto` | (b) | Antes: `'9000' == '9.000'` (el agrupado). Mutante «hero con `tokens_context_saved`»: `assert medidas["kpi"] == _miles(_NETO)` → `'10.000' == '9.000'`. Mutante «tooltip sin la frase de relecturas»: `assert "relecturas" in medidas["tooltip"]` |
| `test_quien_delego_ensena_el_neto_del_cliente` | (b) | Antes: `'9000' == '9.000'`. Mutante «columna con `c.tokens_saved`»: `assert medidas["columnaNeto"] == _miles(_NETO)` → `'10.000' == '9.000'` |
| `test_la_latencia_va_en_segundos` | (a) | `assert medidas["latencia"].endswith(" s")` → `'3000ms'` |

Los siete mutantes se aplicaron con `scratchpad/mutantes.py`, que reescribe `metrics.py` en bytes,
corre el test y lo restaura (comprobado: `restaurado: True`, fichero idéntico byte a byte).

### Comandos y resultados

- `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_dashboard_js.py tests/test_dashboard_ui.py tests/test_metrics.py tests/test_hooks_telemetry_api.py -q`:
  112 passed, 1 skipped (la guarda de CI).
- Extracción del JS y `node --check`: sin errores.
- `uv run ruff check src tests` y `uv run ruff format --check src tests`: limpios.
- Suite completa, `bash ~/.claude/scripts/pesado.sh uv run pytest -q`: **1568 passed, 2 skipped**.
- `git ls-files --eol`: `metrics.py` y `test_dashboard_ui.py` siguen `crlf` (0 LF sueltos);
  `test_dashboard_js.py` y `test_hooks_telemetry_api.py` siguen `lf` (0 CR).

### Desviaciones del plan

1. **El control (a) del arreglo (g) no podía fallar con «Refrescar»**: el botón es `.btn`, que ya
   fija `var(--sans)`, así que hoy tiene la familia del `body` (comprobado: el assert pasó contra
   el código de antes). El único control sin familia es el cierre de la ayuda (`.help-x`,
   `#helpClose`), que salía en Arial; el test comprueba los dos y el que discrimina es el segundo.
2. **`fmtNum` devuelve «–» con `null`, `undefined` o un no finito** (antes `Intl` pintaba `NaN`), y
   `fmtSeg` también. Con eso, la latencia media sin eventos es «–» y no «< 0,1 s» ni «0 ms».
3. **El KPI «Latencia media» lleva la unidad dentro del valor** (`116,9 s`), sin `unit`: «< 0,1 s» no
   se puede partir en cifra y unidad, y el test pide que el texto acabe en « s».
4. **Plurales de más** que la spec no enumera pero REQ-033 cubre por regla: «1 fallo» en la tasa
   de error y «1 llamada» en el contador de actividad. «1 evento / N eventos» del pie sí está en la
   spec.
5. Las cadenas de `fmtSeg` que van a `innerHTML` pasan por `escHooks` (el «<» de «< 0,1 s»).
6. El mutante «sin tooltip» se aplicó quitando la frase de relecturas, no el tooltip entero: con el
   tooltip entero fuera, la medida devuelve `''` (se leyó con `?.` para que no reviente la fixture)
   y el assert dispara igual.

### Para T4

- La clase `.nota` ya existe (Inter, `--mut`, 12,5 px, `padding:10px 12px`, izquierda): úsala para
  la nota de cómputo remoto de REQ-025 / REQ-034 (h).
- `F`, `F1`, `fmtSeg(ms)` y `plural(n, uno, varios)` son globales; `plural` ya formatea la cifra.
  Lo que pase a `innerHTML` desde `fmtSeg` va con `escHooks`.
- `tests/test_dashboard_ui.py` tiene la fixture de módulo `medidas` (puerto 9497) con hooks y
  procesos simulados por `page.route`; T4 puede seguir el mismo patrón para la nota remota.
- Cualquier test de node que ejecute una función del panel con `F`/`F1` dentro tiene que definirlos
  sobre `fmtNum` extraído (como `_formateadores()` o el preludio de `test_hooks_telemetry_api.py`).
- Las cabeceras ya no llevan clase: no vuelvas a poner `class="num"` en un `<th>`.

## T4 — API y estados del panel (ola 5)

### Ficheros

- `src/local_delegate/web/metrics.py` (CRLF, se conserva; 0 LF sueltos). Python: `/api/backend`
  usa `server.sondear_backend()`, pide `/running` (ayudante nuevo `_running()`, con
  `server._plazo_sonda()`) solo si `available`, y devuelve `running_ok`, `models_stale`, `causa`,
  `etiqueta` y `detalle` (ayudante `_causa_json`). `/api/status` usa el mismo sondeo en su bloque
  `backend`, con las mismas claves menos `running`. `/api/backend/stats` usa `_plazo_sonda()`, y
  sin datos devuelve `causa`, `etiqueta`, `detalle` y `status_http` (`_sin_stats`); toda excepción
  se clasifica, como en el sondeo. `/api/system` añade `platform`, `origin` y `host`.
  `/api/inflight` no cambia: sirve `inflight_snapshot()`, que desde T3 copia `espera_local`. JS:
  `CAUSAS_CONTESTA`, `PALABRAS_RUNNING`, `PALABRAS_ESPERA`, `vistaInicial`, `estadoVisible`,
  `badgeBackend`, `chipEstado`, `ordenModelos`, `estadoModelo`, `textoStats`, `textosSistema`;
  `fetchStatus` (sin `modelStatus`), `renderBackend` (badge y filas desde el estado visible y su
  sondeo de referencia, chip con `chipEstado`, fila `.atenuada`), `renderBackendStats` (con
  `textoStats`), `pollInflight` (solo `/api/inflight`, con guarda y `setTimeout` de 2 s al
  terminar), `pollBackend` y `aplicarBackend` (nuevos), `sondearAhora` (los dos sondeos; lo usan el
  arranque, «Refrescar» y la pestaña visible otra vez), título «Última delegación» en
  `renderInflight`, textos de `pollSystem` y la nota `#procNota` (`.nota`). Fuera el
  `setInterval(pollInflight,2000)`. CSS: `.pill.warn` (ámbar), `.pill.neutral`,
  `.mstatus.neutral` y `.mrow.atenuada`.
- `tests/test_metrics.py` (LF): 10 tests nuevos (`/api/backend` ×4, `/api/status`,
  `/api/backend/stats` ×3, `/api/system`, `/api/inflight`).
- `tests/test_panel_estados.py` (nuevo, LF): 19 tests de node que usan `_extraer`, `_correr` y
  `_formateadores` de `test_dashboard_js.py` sin modificarlo.
- `tests/test_dashboard_ui.py` (CRLF, se conserva; 0 LF sueltos): un test de Playwright de la nota
  remota (puerto 9496, `/api/system` con `page.route`).

### Controles positivos

Controles (a) contra el código de antes (`pytest … -k …` con los tests escritos y el código sin
tocar; el de Playwright, con `metrics.py` de `HEAD` puesto en su sitio y restaurado después,
`cmp` idéntico):

| Test | Assert que disparó |
|---|---|
| `test_api_backend_dice_la_causa_de_un_401` | `assert j.get("causa") == "credencial"` → `None == 'credencial'` |
| `test_api_backend_conserva_la_lista_y_la_marca_vieja` | `assert j.get("models_stale") is True` → `None is True` (es el primer assert; ver desviación 6) |
| `test_api_backend_no_pide_running_si_models_falla` | `assert ruta_running.call_count == 0` → `1 == 0` |
| `test_api_backend_dice_si_running_respondio` | `assert j.get("running_ok") is False` → `None is False` |
| `test_api_status_dice_la_causa_en_el_bloque_backend` | `assert data["backend"].get("causa") == "credencial"` → `None == 'credencial'` |
| `test_api_backend_stats_dice_el_codigo_con_un_404` | `assert j.get("status_http") == 404` → `None == 404` |
| `test_api_backend_stats_dice_la_causa_con_un_nombre_que_no_resuelve` | `assert j.get("causa") == "dns"` → `None == 'dns'` |
| `test_api_backend_stats_usa_el_plazo_de_sondeo` | `assert plazo_conexion == config.TIMEOUT_SONDA_CONEXION` → `1.0 == 3.0` |
| `test_api_system_dice_plataforma_origen_y_host` | `assert j.get("platform") == sys.platform` → `None == 'win32'` |
| `test_pollInflight_no_se_apila` | `assert llamadas_fetch_inflight == 1` → `3 == 1` |
| `test_pollInflight_se_encadena_tras_terminar` | `assert r["retrasos"] == [2000]` → `[] == [2000]` |
| `test_un_backend_lento_no_congela_en_curso` | `assert renders_inflight >= 1` → `0 >= 1` |
| `test_ultima_delegacion_cuando_nada_corre` | `assert head == "Última delegación"` → `'En curso' == …` |
| `test_la_version_de_llama_swap_solo_se_culpa_con_un_404` | (a) `assert "v236" not in html` con `dns` |
| `test_la_nota_de_computo_remoto_sale_en_Inter_y_sin_fila_vacia` (Playwright) | `assert "El backend corre en" in texto` → `… in ''` |

Mutantes (b), con `scratchpad/mutantes_t4.py`, que reescribe `metrics.py` en bytes, corre el test,
anota la primera línea `> assert` de la salida y restaura (`restaurado: True`). Los 16 hacen
fallar su test en el assert que pide el plan:

| Mutante | Test | Assert que disparó |
|---|---|---|
| `/api/inflight` copia una lista blanca sin `espera_local` | `test_api_inflight_deja_pasar_la_espera_local` | `assert e.get("espera_local") == "plaza"` |
| `estadoVisible` con umbral 1 | `test_dos_fallos_antes_de_caido` | `assert vistos[1] == "conectado"` |
| filas con el último `bj` (`vista.ultimo`) y no el sondeo de referencia | `test_las_filas_aguantan_el_primer_fallo` | `assert fila["texto"] == "montado"` (da «frío», regla 5) |
| atenuar por `models_stale` | ídem | `assert fila["atenuada"] is False` (ver desviación 5) |
| regla 9 antes que la 6 | `test_estado_modelo_una_fila_por_regla` | `assert txt[6] == "cargando"` |
| regla 4 antes que la 1 | ídem | `assert txt[0] == "esperando al backend"` |
| sin la regla 3 | ídem | `assert txt[2] == "en cola local"` |
| la regla 3 exige `espera_local === 'plaza'` | `test_la_espera_local_es_un_punto_de_extension` | `assert txt == "en cola local"` |
| el `title` de la fila 9 solo nombra los `ready` | `test_esperando_turno_no_afirma_la_causa` | `assert "qwen35-2b cargando" in title` |
| `ordenModelos` alfabético puro | `test_orden_de_modelos_con_y_sin_conexion` | `assert ids == ["gemma4-26b-a4b", "qwen36-35b-a3b", "gemma4-12b", "qwen35-2b"]` |
| `chipEstado`: lo que no es `loaded` como `unloaded` | `test_chip_de_estado_acepta_cualquier_valor` | `assert r[2] == "neutral"` |
| `textosSistema` sin la rama de `origin` | `test_textos_del_panel_sistema` | `assert "El backend corre en" in nota` |
| badge: `credencial` como caída | `test_el_badge_dice_la_causa` | `assert clase == "warn"` |
| badge: `title` fijo | ídem | `assert title == det_401` |
| `textoStats` nunca menciona v236 | `test_la_version_de_llama_swap_solo_se_culpa_con_un_404` | `assert "v236" in html` |
| sin `fetchStatus()` al pasar a disponible | `test_al_reconectar_se_refresca_todo` | `assert llamadas_status == 1` |

### Tests actualizados a propósito

En `tests/test_metrics.py`: `test_api_backend_unavailable`, `test_api_backend_stats_unavailable_on_404`
y `test_api_status_backend_down` (comparan el JSON entero y ganan las claves nuevas, con sus valores
exactos), y `test_api_system_never_crashes_without_platform_support`, que comparaba `/api/system`
entero y no estaba en la lista del plan: ahora compara solo `ram`, `vram` y `processes`.
`test_api_backend_available` y `test_api_status_reports_version_models_catalog_tools` no cambian.

### Comandos y resultados

- `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_panel_estados.py tests/test_metrics.py tests/test_dashboard_js.py tests/test_dashboard_ui.py tests/test_captura.py tests/test_hooks_telemetry_api.py -q`:
  146 passed, 1 skipped (la guarda de CI).
- Extracción del JS y `node --check`: sin errores.
- `uv run ruff check src tests` y `uv run ruff format --check src tests`: limpios.
- Suite completa, `bash ~/.claude/scripts/pesado.sh uv run pytest -q`: **1598 passed, 2 skipped**.
- `git ls-files --eol`: `metrics.py` y `test_dashboard_ui.py` siguen `crlf` (0 LF sueltos);
  `test_metrics.py` sigue `lf`; `test_panel_estados.py` es LF (0 CR).

### Desviaciones del plan

1. **Clave `etiqueta` de más** en `/api/backend`, en el bloque `backend` de `/api/status` y en
   `/api/backend/stats` sin datos. El badge (REQ-014), el `title` de «desconocido» y «sin datos:
   `<etiqueta corta>`» (REQ-020) necesitan la etiqueta corta, y REQ-011 dice que solo la redacta
   `fallos.py`: o la mandaba el daemon o el JS tenía una copia (las «dos fuentes» de siempre). Va
   con `fallos.etiqueta()`. Un test (`test_el_js_no_redacta_las_etiquetas_de_las_causas`) comprueba
   que el HTML no lleva las etiquetas entre comillas. La lista de causas «en las que alguien
   contesta» sí está en el JS (`CAUSAS_CONTESTA`): es la regla de REQ-014, no un texto.
2. **CSS y HTML mínimos fuera de la zona de T4** (la zona de CSS era de T5): `.pill.warn`,
   `.pill.neutral`, `.mstatus.neutral`, `.mrow.atenuada` y el contenedor `<div class="nota"
   id="procNota">` debajo de la tabla de procesos. Sin ellos la clase `warn`, la chip neutra, la
   atenuación y la nota no se verían.
3. **`badgeBackend(vista, baseUrl)`**: el plan dice `badgeBackend(vista)`; el segundo argumento es
   la URL base para el `title` en verde (REQ-014), que `/api/backend` no trae.
4. **`estadoModelo({modelo, vista, inflight})`** devuelve `{texto, title, atenuada}` como pide el
   plan. «En espera local» = todas las llamadas a ese modelo con `espera_local` distinto de
   `undefined` y de `null` (la spec dice que `null` es «no espera»; el plan, «presente con
   cualquier valor»). Test aparte: con una llamada en espera y otra no, la fila dice «procesando».
5. **El mutante «atenuar por `models_stale`» lee el `models_stale` del último sondeo**
   (`vista.ultimo`). Leído del sondeo de referencia no mutaba nada: tras el primer fallo la
   referencia es el sondeo bueno, con `models_stale: false`.
6. **`test_api_backend_conserva_la_lista_y_la_marca_vieja`**: el assert de control
   (`j.get("models_stale") is True`) va el primero, como pide el plan; el test también mira
   `causa == "transporte"` y que el sondeo bueno trae `models_stale: false`.
7. **`running_ok` exige un 2xx con un objeto JSON** cuya clave `running` sea una lista o falte
   (`null` cuenta como lista vacía). Con un 2xx raro, `running: []` y `running_ok: false`, para que
   el JS nunca reciba algo que no pueda recorrer.
8. **Un fallo de `fetch('/api/backend')`** (el daemon no contesta) no cuenta como sondeo del
   backend: no cambia el estado visible. Solo cuenta lo que el daemon dice del backend.
9. **Las filas antes del primer `/api/backend`** salen del estado inicial («comprobando…»): sin
   sondeo no hay lista, y el cuerpo dice «Consultando el backend…» en vez de pintar el catálogo
   como «desconocido». La lista de `/api/status` ya no alimenta las filas (REQ-021).
10. **`_correr` lee la salida con cp1252 en Windows**: los tests de node imprimen con un `salida()`
    que escapa lo que no es ASCII, sin tocar `test_dashboard_js.py`. Y `_extraer` recorta desde la
    cabecera que se le da, así que las funciones `async` se piden con `async function …(`.

### Para T6 y T7

- **T6 (mock de la captura)**: `/api/backend` del mock no trae `running_ok`, así que con este
  panel las filas caen en la regla 5 («montado»/«frío») y la captura no enseñaría «procesando».
  Hay que añadir `running_ok: true`, `models_stale: false`, `causa: null`, `etiqueta: null` y
  `detalle: null`; en `/api/system`, `platform`, `origin` y `host`. Ningún endpoint nuevo, así que
  `test_captura.py` sigue verde. Para la wiki: el badge tiene cuatro aspectos (verde «conectado»,
  ámbar con la etiqueta, rojo «caído · …», neutro «comprobando…»), dos fallos seguidos antes de
  «caído», y las claves nuevas de los cinco endpoints (incluida `etiqueta`).
- **T7 (panel contra el backend real)**: el badge «sin acceso» en ámbar sale tras **dos** sondeos
  (≈ 4 s más lo que tarde cada uno); con `no-existe.invalid` las filas pasan a «desconocido» solo si
  hubo antes una lista buena de esa URL o un catálogo: sin lista guardada se ven solo los del
  catálogo. La tarjeta de llama-swap dice «sin datos: no resuelve» (sin «v236»). El título «Última
  delegación» depende de `state.lastEvent` (el log real).

## T6 — Documentación (ola 6)

### Ficheros

- `CHANGELOG.md` (CRLF, se conserva; 0 LF sueltos, contado por bytes): en `[Unreleased]`, la nota
  visible «No publicar versión hasta mezclar `coste-api-y-cuota`…» justo debajo del título; tres
  entradas nuevas al principio de `### Changed` (neto y cifras históricas que bajan, con agosto
  −32 % y septiembre 800 928; dos sondeos antes de «caído» y lista estable; presentación) y un
  `### Fixed` nuevo con cinco entradas (los fallos inflaban el ahorro; la causa en badge,
  `local_status` y `doctor`, con `fallo_conexion` y el texto nuevo de `connect_error`; no se ofrece
  arrancar un backend remoto; rendirse a los 10 s; estados del panel). Las entradas de
  `filelock` y Dependabot que ya estaban no se tocan. Sin versión ni fecha.
- `docs/wiki/Savings-and-metrics.md` (LF): campo `fallo_conexion` en «Qué se mide»; el KPI como
  neto en «Cómo se calcula…»; subsección nueva «La regla de contabilidad» (tabla qué cuenta / qué
  no, predicado de fallo, neto negativo, pista del KPI, imagen, desglose en caracteres y
  `tokens_claude`, cifras de septiembre y agosto −32 %); «En curso» con «Última delegación» y los
  sondeos separados; subsección nueva «Estado del backend y de los modelos» (los cuatro aspectos
  del badge, los dos fallos seguidos, la lista guardada por URL, la tabla de textos de fila,
  `espera_local`, el 404 de las métricas); tabla de APIs con las claves nuevas de `/api/stats`,
  `/api/inflight`, `/api/backend` y filas nuevas para `/api/status`, `/api/backend/stats` y
  `/api/system`.
- `docs/wiki/Troubleshooting.md` (LF): «no se pudo conectar al endpoint» pasa a «no se pudo
  conectar con el backend: …», con la tabla de las once causas (badge, detalle y qué hacer), el
  plazo de 10 s, que con origen remoto no se pregunta ni se autoarranca, y los síntomas de la Mac
  con el nombre de su causa; «`doctor` dice que el backend está CAÍDO…» añade el detalle, las dos
  severidades del 401 según quién lo vio, las pistas con backend remoto, la línea `Backend:` de
  `local_status` y el plazo del sondeo (3 s + 2 s).
- `docs/wiki/Remote-backend.md` (LF): en «Verificación», qué dicen `local_status`, el badge, la
  sección de procesos y una delegación con cómputo remoto.
- `docs/wiki/Daemon.md` (LF): en «Qué significa «DAEMON MCP»…», la nota de cómputo remoto debajo
  de la tabla de procesos y el texto de una plataforma sin lista de procesos.
- `scripts/dev/capture_dashboard.py` (LF): `stats` deja fuera los fallos (`ok === false`) y
  calcula `returned` con la regla (`chars_out ÷ 4` en los `path` que reclaman); `/api/stats` lleva
  `tokens_returned`, `tokens_context_net`, `total.returned`/`total.net` y `tokens_net` en
  `by_client`; `/api/backend` lleva `running_ok: true`, `models_stale: false`, `causa`, `etiqueta`
  y `detalle` a `null`, y `state: 'ready'` en `running`; `/api/system` lleva `platform: 'win32'`,
  `origin: 'local'` y `host`.
- README: no se toca (el plan no lo pide para T6). La imagen del README no se regenera (REQ-040:
  «No hay release ni captura nueva»).

### Comandos y resultados

| Comando | Resultado |
| --- | --- |
| `bash ~/.claude/scripts/pesado.sh uv run pytest tests/test_wiki.py tests/test_captura.py -q -p no:cacheprovider` | **19 passed** |
| `uv run ruff check` y `uv run ruff format --check` sobre `capture_dashboard.py` | All checks passed / already formatted |
| `node --check` del `SEED_AND_MOCK` extraído, y ejecutarlo con `window`/`Response` falsos | sintaxis bien; `/api/stats` del mock da bruto 1 809 329, devuelto 53 363, neto 1 755 966, 9 errores en 390 eventos; `/api/backend` trae las claves nuevas |
| `git ls-files --eol` de los seis ficheros, antes y después | `CHANGELOG.md` `i/crlf w/crlf`; las cuatro páginas de la wiki y el script `i/lf w/lf` |
| Integración: `bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider -rfEs` | **1598 passed, 2 skipped, 1 warning en 58 s** (los mismos de T4; T6 no añade tests). Skips y warning, los de siempre |

### Desviaciones del plan

1. **`Daemon.md` sí cambia**, aunque el plan lo condicionaba a «si cambia el texto»: la insignia
   no cambió, pero la tabla de procesos ahora lleva la nota de cómputo remoto (REQ-025) y el texto
   de plataforma sin procesos, que es lo que esa sección describe. Dos frases.
2. **El título de la sección de Troubleshooting cambia** a la frase nueva del error
   (`no se pudo conectar con el backend: …`), porque es lo que el usuario va a buscar. Ningún
   enlace del repo apuntaba al ancla vieja (buscado en `docs/`, `README.md` y `src/`).
3. **`running` del mock lleva `state: 'ready'`**: `estadoModelo` ya lo toma por defecto, pero así
   el mock tiene la forma real de `/running` de llama-swap.
4. Los `tokens_net` de `by_client` del mock son inventados como el resto de esa tarjeta (un poco
   por debajo de `tokens_saved`); no se derivan de los eventos, igual que antes `tokens_saved`.

### Para T7

- La nota de la restricción de entrega está en la primera línea de `[Unreleased]`; quien prepare la
  release tiene que quitarla al mezclar `coste-api-y-cuota`.
- La wiki y el CHANGELOG citan las cifras de septiembre y agosto de la máquina de referencia: si
  T7 las recalcula con otro resultado, hay que corregirlas en los dos sitios.

## T7 — Verificación final (ola 7)

Revisión: `feat/panel-honesto` en `4046a05` (T1–T6 en commit; árbol limpio al empezar). Fecha:
2026-10-06. Las salidas completas se guardaron en el scratchpad de la sesión, fuera del repo.

### Paso 1: lint y formato

| Comando | Resultado | Criterio |
| --- | --- | --- |
| `uv run ruff check .` | All checks passed! | Pasa |
| `uv run ruff format --check .` | 131 files already formatted | Pasa |

### Paso 2: suite completa

`bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider -rfEs` con Playwright
instalado (`import playwright` responde): **1598 passed, 2 skipped, 1 warning en 55,95 s**. Los dos
skips son los de siempre (`test_checks.py:462`, chmod en Windows; `test_dashboard_ui.py:517`, guarda
de CI) y el warning es el `DeprecationWarning` de `anyio.abc.BlockingPortal` en starlette. **Pasa.**

### Paso 3: septiembre a mano

Insumo: `usage-202609.jsonl` de `config.LOG_DIR` (el log real de esta PC, mes cerrado). El comando
exacto del plan imprime:

```
3463739 1489047 5237 289554 873270 72342 800928 0
```

Esperado: `3463739 1489047 5237 289554 873270 72342 800928 0`. **Idéntico, pasa.** El CHANGELOG y la
wiki citan 800 928 para septiembre: no hay que corregirlos.

### Paso 4: panel del repo contra el backend real, sin credencial

`metrics.app` del repo servido en `127.0.0.1:9494` como dice `tests/test_captura.py`
(`uv run python -c "import uvicorn; …port=9494)"`, sin `LOCAL_DELEGATE_WEB_TOKEN` en el entorno), y
un script de Playwright bajo `pesado.sh` que lee `#backendPill` cada 0,5 s durante 25 s y después las
filas (`#modelsBody`) y la tarjeta de llama-swap (`#backendStats`). La consola no tiene
`LOCAL_DELEGATE_API_KEY` (comprobado por nombre de variable, sin leer valores).

**Contra `127.0.0.1:9292` (llama-swap vivo, exige credencial).** `/api/backend` devuelve
`causa: "credencial"`, `etiqueta: "sin acceso"`, `detalle: "127.0.0.1:9292 responde 401: está
arriba pero rechaza la credencial"`.

| Tiempo | Badge | Clase |
| --- | --- | --- |
| 0,1 s | «comprobando…» | `pill neutral` |
| 2,1 s (segundo sondeo) | «sin acceso» | `pill warn`, color `rgb(251, 191, 36)` (ámbar) |

El `title` del badge es el detalle del 401. Filas: los cuatro modelos del catálogo en
«desconocido»; tarjeta: «sin datos: sin acceso». **Pasa.**

**Con `LOCAL_DELEGATE_BASE_URL=http://no-existe.invalid:9292/v1`.** `/api/backend` devuelve
`causa: "dns"`, `etiqueta: "no resuelve"`, `origin: "remote"`.

| Tiempo | Badge | Clase |
| --- | --- | --- |
| 0,1 s | «comprobando…» | `pill neutral` |
| 2,1 s (segundo sondeo) | «caído · no resuelve» | `pill down`, color `rgb(248, 113, 113)` (rojo) |

Filas: `gemma3-4b`, `gemma4-26b-a4b`, `qwen36-35b-a3b`, `gemma4-12b`, todas «desconocido». Tarjeta
de llama-swap: «sin datos: no resuelve», **sin «v236»**. **Pasa.**

### Paso 5: `doctor` sin daemon

Con `LOCAL_DELEGATE_WEB_PORT=9496` (nadie escucha: `doctor` no pregunta al daemon).

- `LOCAL_DELEGATE_BASE_URL=http://no-existe.invalid:9292/v1`: `[WARN] backend: …/models: no se
  resuelve el nombre no-existe.invalid:9292 (¿VPN o DNS?)` y `arréglalo con: revisa el nombre en
  LOCAL_DELEGATE_BASE_URL o usa la IP (p. ej. la 100.x de la tailnet)`, que es la pista de `dns`
  de `fallos.py`. **Pasa.**
- `LOCAL_DELEGATE_BASE_URL=http://192.0.2.1:9292/v1`: `[WARN] backend: …: 192.0.2.1:9292 no
  contesta a la conexión (ruta, cortafuegos o VPN)` y `arréglalo con: revisa la red hacia
  192.0.2.1:9292 (VPN, cortafuegos, Tailscale)`. «arranca llama-swap» aparece **0 veces** en toda la
  salida. **Pasa.** (La única pista con «arranca» es la del daemon: «local-delegate serve (o arranca
  la tarea programada del daemon)», que no habla del backend.)

Las dos corridas salen con código 1 por el `[FALT] daemon`, que es lo esperado en este paso.

### Paso 6: daemon real con la versión del repo

Antes: `pythonw.exe -m local_delegate serve` pid 18032 (lanzador) y 18052 (hijo), del 2026-10-03,
con `local-delegate-mcp v0.32.0` publicada. `schtasks /End` deja la tarea parada pero **no** mata
esos dos procesos (los lanza el `.ps1`), así que se pararon con `Stop-Process` antes de instalar
para no chocar con ficheros bloqueados. Después:
`bash ~/.claude/scripts/pesado.sh uv tool install --force --reinstall --no-cache ".[llamaswap]"` →
`local-delegate-mcp==0.32.0 (from file:///D:/Projects/local-delegate)`; el Python de la herramienta
importa `local_delegate.fallos` (módulo que solo existe en el código de la rama).
`schtasks /Run /TN LocalDelegateDaemon` → pids 10952 y 1684 (2026-10-06 14:16:54), escuchando en
`127.0.0.1:9393` al instante.

**`local_status` por MCP.** El cliente MCP de esta sesión perdió la conexión al parar el daemon y no
reconectó (`MCP server "local-delegate" is not connected`), así que se llamó por MCP HTTP con un
cliente del SDK (`streamable_http_client` contra `http://127.0.0.1:9393/mcp`, con el token del
puerto tomado del entorno sin imprimirlo). Líneas que pide el plan:

```
Backend: http://127.0.0.1:9292/v1 — arriba
  eventos: 137 (195 llamadas al backend) — contexto conservado: ~640858 tokens netos (bruto ~688289)
```

**Pasa.**

**`uv run local-delegate doctor` en una consola sin la clave**: `Backend BASE_URL: … — arriba`,
`[ OK ] daemon: local-delegate 0.32.0 · pid 1684`, **`[ OK ] backend: http://127.0.0.1:9292/v1/models
responde`** y `[ OK ] credencial del backend: … las entradas MCP van por el daemon (http)`. La misma
consola contra el backend, sin el daemon (paso 4), recibe el 401, así que el `OK` llega por la vía
del daemon. Código de salida 0. **Pasa** (ni `UNKNOWN` ni `WARN`).

**Panel de `9393` durante una delegación larga.** Script de Playwright bajo `pesado.sh`, con
credencial Basic del token del puerto. Abre el panel (badge «conectado»), instala con
`page.evaluate` un `setInterval` de 500 ms que guarda en `window.__lecturas` el texto de la fila de
`gemma4-26b-a4b` y el de `#inflightHead`, con su hora; lanza `local_summarize` por MCP HTTP sobre
`docs/wiki/Repo-hardening.md` (23 741 caracteres, ruta al rol largo); al volver espera 5 s y lee las
lecturas. Delegación de 17:18:14Z a 17:18:36Z (22,3 s), código 0. Lecturas (57 en total; solo los
cambios):

| Hora (UTC) | Fila de `gemma4-26b-a4b` | Título |
| --- | --- | --- |
| 17:18:13.293 | LARGO · frío · UNLOADED | Última delegación |
| 17:18:15.794 | LARGO · **cargando** · LOADED | En curso (1) |
| 17:18:21.790 | LARGO · **procesando** · LOADED | En curso (1) |
| 17:18:38.292 | LARGO · montado · LOADED | **Última delegación** |

La fila pasa por «cargando» y «procesando», y el título vuelve a «Última delegación» unos 2 s
después del final (dentro de los 5 s). **Pasa.**

### Paso 7: devolver el daemon a la versión publicada — no se hace, por decisión del usuario

El plan lo condiciona a «salvo que el usuario diga otra cosa», y el encargo de esta tarea (2026-10-06)
pide dejar el daemon corriendo con la versión nueva («el entorno local va con todo habilitado»). El
daemon queda con el código de la rama (pids 10952 y 1684). Consecuencia que el usuario asume: el panel
y `local_status` de esta PC enseñan a diario la cifra intermedia en tokens (chars ÷ 4) hasta que
entre `coste-api-y-cuota`. Ojo: se anuncia como `0.32.0`, igual que la publicada, y `doctor` dice
«la última publicada»; para saber qué código corre hay que mirar que exista `local_delegate.fallos`.

### Paso 8: revisión del resultado y seguridad

**Revisión contra la spec (`personal-sdd-review`, gate de resultado).** Veredicto propuesto:
**aprobar**, sin hallazgos bloqueantes.

- Todos los requisitos de la spec (REQ-001 a REQ-008, REQ-010 a REQ-028, REQ-030 a REQ-034 y
  REQ-040) tienen tests o pruebas con control positivo en las secciones de T1–T6, y T7 confirma en
  vivo REQ-007 (septiembre), REQ-014, REQ-015, REQ-016, REQ-020, REQ-021, REQ-022, REQ-024 y REQ-028.
- No bloqueante: la tabla «Evidence» del principio no tenía filas para REQ-014, 020, 023–028,
  034 (h) y 040, aunque su evidencia está en las secciones de T4 y T6 (los tests de
  `test_panel_estados.py` y los mutantes de T4; los ficheros de T6). T7 añade las filas de lo que
  verificó en vivo; REQ-023, 025, 026, 027, 034 (h) y 040 se quedan citados por sección.
- Observación no bloqueante: durante la carga la fila dice «cargando» y la chip ya dice «LOADED»
  (la chip sale de `/v1/models` y el texto de `/running`, que va por detrás). La spec no lo prohíbe
  (REQ-023 solo pide que la chip acepte cualquier valor), pero se lee contradictorio un par de
  segundos.

**Seguridad (`personal-security-check`) sobre `git diff 130afab..HEAD` (11 commits, 65 ficheros).**

- Gitleaks `gitleaks git --redact --log-opts=130afab..HEAD`: 11 commits, ~1,33 MB, **no leaks
  found**.
- Dependencias: `pyproject.toml` y `uv.lock` sin cambios en la rama; no hay nada que pasar por
  Socket.
- Datos personales: **un hallazgo menor** — `research.md` de este cambio, línea 56, cita la IP real
  de Tailscale de esta PC (la 100.x de la tailnet) en la tabla de la medición del paso 0. Es una dirección
  CGNAT privada de la tailnet, no alcanzable desde fuera, pero identifica la máquina en un fichero
  versionado. Remedio: sustituirla por «la IP 100.x de la tailnet» antes de mezclar (dueño:
  `research.md`, no T7). El resto de coincidencias (`pc.tailnet.ts.net`, `100.64.0.2`, `192.0.2.1`)
  son valores de prueba. Fuera de este cambio, `.sdd/changes/check-clientes-observados/research.md`
  trae la ruta `%USERPROFILE%\…`; no es de esta rama.
- Configuración: no se tocó el lanzador del daemon ni `~/.claude/settings.json`. No hubo operaciones
  destructivas salvo parar los dos procesos del daemon viejo (pids concretos, comprobados antes).

### Resultado de T7

Pasos 1–6 y 8: pasan. Paso 7: no se aplica por instrucción del usuario. Ningún fallo que devolver a
una tarea; queda el hallazgo menor de la IP en `research.md`.

## Quality checks

- [x] Project-native tests pass (T2: suite completa 1497 passed, 2 skipped).
- [x] Project-native tests pass (T1: suite completa 1514 passed, 2 skipped).
- [x] Project-native tests pass (T3: suite completa 1553 passed, 2 skipped).
- [x] Project-native tests pass (T5: suite completa 1568 passed, 2 skipped; `node --check` del JS).
- [x] Project-native tests pass (T4: suite completa 1598 passed, 2 skipped; `node --check` del JS).
- [x] Lint, formatting, type checking, and build checks pass where applicable (`ruff` en lo tocado).
- [x] Secret scanning passes (T7: Gitleaks sobre `130afab..HEAD`, sin fugas; hallazgo menor de
  privacidad: la IP de Tailscale de esta PC en `research.md:56`).
- [x] Project-native tests pass (T7: ruff limpio; suite completa 1598 passed, 2 skipped).
- [x] No unrelated changes are present (T2: `git status` solo muestra `fallos.py` y el test nuevo).
- [x] No unrelated changes are present (T1: solo `server.py`, `web/metrics.py`,
  `tests/test_metrics.py`, `tests/test_dashboard_js.py` y este fichero; lo demás que sale en
  `git status` es de otros cambios SDD).
- [x] No unrelated changes are present (T3: solo los once ficheros de su lista, los dos tests
  nuevos y este fichero; `.sdd/changes/coste-api-y-cuota/plan.md` es de otra sesión).
- [x] No unrelated changes are present (T5: `web/metrics.py`, `tests/test_dashboard_js.py`,
  `tests/test_dashboard_ui.py`, `tests/test_hooks_telemetry_api.py` —por la integración— y este
  fichero).
- [x] No unrelated changes are present (T4: `web/metrics.py`, `tests/test_metrics.py`,
  `tests/test_dashboard_ui.py`, `tests/test_panel_estados.py` y este fichero).
- [x] Project-native tests pass (T6: suite completa 1598 passed, 2 skipped; `test_wiki.py` y
  `test_captura.py` 19 passed).
- [x] No unrelated changes are present (T6: `CHANGELOG.md`, las cuatro páginas de la wiki,
  `scripts/dev/capture_dashboard.py` y este fichero).

## Deviations and residual risk

- T2: ver «Desviaciones del plan» de su sección. Riesgo residual: los tests de red real dependen de
  la red del CI (DNS que responda `NXDOMAIN` a `.invalid`, `192.0.2.1` que no conteste o no tenga
  ruta); en esta PC se confirmaron, en Ubuntu y macOS se verá en el primer CI.
- T1: ver «Desviaciones del plan» de su sección. Riesgo residual: hasta que
  `coste-api-y-cuota` sustituya `tokens_claude`, las cifras en tokens son la intermedia
  (chars ÷ 4); no se publica ninguna versión con ellas (Restricciones de entrega de la spec).
- T3: ver «Desviaciones del plan» de su sección. Riesgo residual: los tests de red real
  (`.invalid`, `192.0.2.1`, puerto cerrado en la IP de salida) dependen de la red del CI; el de
  `192.0.2.1` tarda ~10 s en esta PC y puede pasar antes en un CI sin ruta (`sin_ruta`). La
  anotación de `daemon.query_backend` sigue diciendo `float`.
- T5: ver «Desviaciones del plan» de su sección. Riesgo residual: la tipografía se mide con las
  fuentes de Google abortadas (familia declarada, no la cara pintada); la cara 400 de verdad solo se
  ve en el navegador contra el daemon (T7).
- T4: ver «Desviaciones del plan» de su sección. Riesgo residual: la histéresis y los sondeos se
  prueban con node y un `fetch` de mentira; el panel contra el backend real lo ve T7. El mock de la
  captura (T6) todavía no trae `running_ok`.
