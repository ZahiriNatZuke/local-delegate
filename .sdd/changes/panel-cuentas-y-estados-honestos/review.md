# Result review: Panel: los fallos no suman ahorro, los estados dicen la causa real y la presentación es coherente

## Verdict

Choose one: `conforms`, `conforms-with-notes`, or `does-not-conform`.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | | | |

## Findings

- List correctness, security, maintainability, or scope findings in severity order.

## Required follow-up

- Identify work that must be completed before closure.

## Revisión del plan

Revisor adversario, solo lectura, 2026-10-06. Fuentes: `plan.md`, `spec.md` (leídos enteros),
`research.md` (resumido con `local_summarize`), y el código en `130afab` de `feat/panel-honesto`.

**Veredicto propuesto: aprobable con cambios.** El reparto en olas y las zonas por función son
reales, y la mayoría de los controles positivos que he comprobado fallan de verdad por el assert
que el plan dice. Pero hay un bloqueante (la verificación de T3 se pondrá roja por unos tests que
nadie tiene asignados), un mutante que no muta y varios controles «contra el código actual» que
solo pueden fallar por una excepción. Todo se arregla editando el plan, sin tocar la spec.

### BLOQUEANTE

**1. T3 y T4 rompen tests existentes de `tests/test_metrics.py` que no están en el plan, y la caché
de «última lista buena» los contamina según el orden.**
- Evidencia: tres tests comparan el JSON entero con `==`: `test_api_backend_unavailable`
  (`tests/test_metrics.py:182-193`, espera `"models": []` y cinco claves exactas),
  `test_api_backend_stats_unavailable_on_404` (`:269-277`, espera `{"available": False}`) y
  `test_api_status_backend_down` (`:280-292`). T4 añade claves (`causa`, `detalle`, `models_stale`,
  `running_ok`, `status_http`) y los rompe. Antes de eso, T3 mete en `server.py` una caché global en
  memoria. `test_api_backend_available` (`:163`) y `test_api_status_reports_version_models_catalog_tools`
  (`:198`) se ejecutan antes y dejan guardada una lista buena (`m1`), así que `:182` y `:280`
  recibirán `models: [{"id": "m1", "status": None}]` en vez de `[]`. Y la verificación de T3
  (`plan.md:181`) corre `tests/test_metrics.py`. El plan solo da por actualizados `:519` y `:741`
  (T1) y, en T3, los dobles de `backend_models`. Además, `tests/test_metrics.py` es **solo de T1**
  según la tabla de propiedad (`plan.md:43`), así que T3 y T4 tendrían que editar un fichero que no
  es suyo. `tests/conftest.py` no tiene ningún fixture que limpie estado de `server`.
- Arreglo: (a) añadir a T3 y a T4 la lista de tests que actualizan a propósito (`:182`, `:269`,
  `:280`, y `:228-243` si cambia el envoltorio) y darles en la tabla de propiedad una zona de
  `tests/test_metrics.py` (en serie T1 → T3 → T4, que ya es el orden de las olas); (b) guardar la
  caché **por `BASE_URL`** y añadir un fixture autouse que la vacíe en `tests/conftest.py` (con su
  dueño, T3); (c) añadir un test que lo demuestre: con una lista buena guardada para la URL A, un
  fallo contra la URL B devuelve `[]`. El control es un mutante que quita la clave por URL.

### IMPORTANTE

**2. El mutante de `estadoModelo` no muta.**
- Evidencia: `plan.md:213` propone «intercambiar las reglas 5 y 6». La regla 5 exige `running ==
  starting` y la 6 exige `running == ready`, así que nunca coinciden: cambiar su orden no altera
  ninguna salida, y el caso «en vuelo + `starting`» sigue dando «cargando» con el mutante aplicado.
  Es justo el control que no puede dar un resultado distinto.
- Arreglo: usar como mutante «la regla 8 (en vuelo → esperando turno) antes que la 5». Así, el caso
  «en vuelo + `starting`» da «esperando turno» y falla `assert txt == "cargando"`. Añadir un
  segundo mutante, «la regla 3 antes que la 1», que cambia lo que se ve sin conexión con una llamada
  en vuelo.

**3. Hay controles «(a) contra el código actual» que solo pueden fallar por una excepción, algo que
la regla del propio plan prohíbe (`plan.md:59-61`).**
- Paridad (`plan.md:94`): `assert js.get("returned") == py["returned"]`. Con el código actual,
  `_accounting` no devuelve `returned` (`server.py:633-643`), así que la línea da `KeyError`. Si se
  escribe `py.get(...)`, queda `None == None` y el test pasa. Nunca falla por el assert. Arreglo:
  declarar que el control (a) se hace **con la mitad Python ya cambiada y el JS sin cambiar**. Así
  falla `js.get("returned") == py["returned"]` (`None != 100`) y se comprueba la paridad de verdad.
- `test_doctor_remoto_no_manda_a_arrancar_llama_swap` (`plan.md:174`): el doble devuelve una tupla
  de tres y `_probe_backend_models` desempaqueta dos (`checks.py:1297`, `healthy, reason =
  ctx.backend_models()`), así que hoy falla con `ValueError`, no con `"arranca llama-swap" not in`.
  Arreglo: convertirlo en control (b), con el mutante «`pista` ignora el origen» aplicado en
  `checks`, o correr el control (a) después del paso 7 de T3 (el cambio de tipo) y antes de enchufar
  `fallos.pista`.
- `test_backend_probe_sin_daemon_dice_dns` (`plan.md:176`): si desempaqueta tres valores, hoy da
  `ValueError` (`doctor.py`: `backend_probe` devuelve dos). Arreglo: leer `doctor.backend_probe()[1]`
  en el control, que hoy da «no responde (ConnectError)» y falla por el assert.
- T4, «`/api/backend` tras un sondeo bueno y otro con `ConnectError`» (`plan.md:206`): cuando se
  escribe T4, T3 ya ha metido la lista guardada en `_models_with_status`, que es lo que llama
  `/api/backend` (`web/metrics.py:604`). El primer assert (`ids == [...]`) **ya pasa**. Arreglo:
  nombrar como assert del control `j.get("models_stale") is True`.

**4. `doctor` descarta la causa del daemon justo en los fallos lentos.**
- Evidencia: `_default_backend_models` pregunta al daemon con `daemon.query_backend(host, port,
  timeout=1.0)` (`checks.py`, función en `:138-161`). Con REQ-013, el `/api/backend` del daemon tarda
  hasta 3 s con `timeout_conexion` (el caso de la Mac con VPN) y unos 2 s con `rechazada` en Windows
  (`research.md` §2). La consulta de `doctor` agota su 1 s, `query_backend` devuelve `None` y
  `doctor` sondea por su cuenta. Así, la parte «ya venga del daemon» de REQ-016 solo funciona cuando
  el daemon responde rápido. El test de T3 dobla `query_backend` (`plan.md:175`) y no puede verlo, y
  T7 solo corre `doctor` **sin** daemon (`plan.md:288`).
- Arreglo: en T3 (que ya es dueño de `checks.py`), el plazo de `query_backend` en
  `_default_backend_models` pasa a ser mayor que el techo del sondeo (por ejemplo
  `TIMEOUT_SONDA_CONEXION + TIMEOUT_SONDA_LECTURA + 1`). Se añade un test que fije esa desigualdad,
  con el mutante «vuelve a 1,0» como control, y un paso en T7 (ver el hallazgo 7).

**5. En la ola B, cada tarea verifica sobre los ficheros que la otra está editando.**
- Evidencia: T3 y T5 corren en paralelo en el mismo árbol. La verificación de T3 incluye
  `tests/test_metrics.py`, que importa `web/metrics.py` y extrae su JS (lo edita T5). La de T5
  levanta `metrics.app` con Playwright, y esa app importa `server.py` (lo edita T3). `pesado.sh`
  pone las ejecuciones en fila, pero no evita que una corra con el fichero de la otra a medio
  editar. El resultado son rojos falsos (o verdes falsos) que se anotarían en `verification.md`.
- Arreglo: dar a T3 y T5 un worktree aislado cada una y mezclar al cerrar la ola, o hacer que la
  verificación de cada tarea de la ola B corra solo cuando las dos han terminado de editar. Lo más
  barato: T5 → T3 en serie, porque T3 no necesita a T5.

**6. Requisitos sin una verificación que pueda fallar.** La tabla de trazabilidad de la spec dice
«Tests de API y funciones JS», pero en el plan no hay ningún test para:
- **REQ-006**: hoy `_aggregate` usa `ok = bool(r.get("ok", True))` (`web/metrics.py:280`), así que
  `ok: None` cuenta como error. Ningún test de T1 mira `errors` con `ok: None`. Arreglo: un caso en
  `/api/stats` con `ok: None` que espere `errors == 0` (control (a): hoy da 1).
- **REQ-027** (refresco al reconectar): ningún test. Arreglo: un test con node sobre `pollInflight`
  que pasa de `available:false` a `true` y cuenta un `fetch('/api/status')`.
- **REQ-023** (estado de backend desconocido con estilo neutro, sin estado no se pinta): ninguno.
- **REQ-018 con `LOCAL_DELEGATE_AUTOSTART` encendido**: el test solo cubre el valor por defecto. Con
  autoarranque, hoy se llama a `autostart.ensure_backend` sin preguntar (`server.py`, rama
  `config.AUTOSTART` de `_post_chat`). Arreglo: parametrizar con `config.AUTOSTART` en `True` y en
  `False`.
- **REQ-020, rama positiva**: solo se comprueba que «v236» no sale con `dns`. Si un mutante no
  muestra nunca «v236», pasa. Arreglo: el caso `status_http: 404` tiene que contener «v236».
- **REQ-012, bloque `backend` de `/api/status`**, y **REQ-014, texto «caído · etiqueta» y `title`
  igual al `detalle`**: el test de `badgeBackend` solo mira la clase CSS.

**7. Prueba de extremo a extremo incompleta.**
- No se corre `doctor` contra el daemon reinstalado (T7.6 solo llama a `local_status` y mira el
  panel), y es el único camino de REQ-016 que llega por `/api/backend`.
- La comprobación del panel en vivo con una delegación larga («la fila pasa por cargando o esperando
  turno y procesando») no dice cuándo da por fallida la prueba: es una observación sin criterio.
- Arreglo: en T7.6, `uv run local-delegate doctor` con el daemon nuevo arrancado: `service.backend`
  tiene que salir OK por la vía del daemon, aunque la consola no tenga la clave. El panel se
  comprueba con `browser_evaluate`, leyendo el texto de la fila en un bucle mientras dura la
  delegación. La prueba falla si nunca se lee «cargando», «esperando turno» o «procesando», o si el
  título no pasa a «Última delegación» cuando la delegación termina.

### MENOR

**8. El grep de `(s)` en T5 choca con el código.** En `metrics.HTML` hay `function renderClients(s)`,
`escHooks(s)` y `fmtHace(s)` (`web/metrics.py:1356`, `:1390`, `:1605`). Un grep literal falla
siempre, y uno más laxo acaba sin comprobar nada. Arreglo: buscar los cuatro literales concretos
(`archivo(s)`, `leído(s)`, `delegación(es)`, `estimado(s)`; `:1342`, `:1653`, `:1715`).

**9. El mutante del plazo de 1,0 s supone algo que nadie ha medido.** El retraso de unos 2 s del
rechazo en Windows se midió en loopback (`research.md` §2), no contra la IP propia no loopback que usa
`test_un_puerto_cerrado_remoto_no_parece_una_vpn`. La regla (b) lo detectaría, pero conviene
medirlo antes de escribir el test, y si no se cumple, buscar otro control para REQ-013.

**10. Las zonas por línea de `server.py` envejecen.** He comprobado que `_accounting` (`:579-643`),
`_models_with_status` (`:2982`), `_llamaswap_running` (`:3000`) y `local_status` (`:3042`) están
donde dice el plan. `_post_chat` está en `:836-950`, no en `:868-906` (ese rango es solo su
`except`). Además, T1 desplaza las líneas antes de que llegue T3. Las zonas de `web/metrics.py` son
funciones reales, y las que comparten T1, T5 y T4 (`render`, `renderBackendStats`, `pollSystem`,
`renderInflight`) van en serie, así que no se pisan. Arreglo: nombrar las zonas solo por función.
Y como el CSS y el JS viven en una sola constante, que cada tarea deje el JS compilable antes de
pasar el turno, comprobándolo con `node --check` sobre el `<script>` extraído.

**11. Comportamientos secundarios.** (a) `local_status` llama a `_models_with_status` y después a
`_llamaswap_running`. Con el plazo de 3 s en las dos, un backend caído tarda unos 6 s: hay que
saltarse `/running` si `/models` falló, igual que en `/api/backend`. (b) `tests/test_observabilidad_respaldo.py:136`
dobla `_models_with_status`. Si `local_status` pasa a llamar a `sondear_backend`, ese doble deja de
valer y el test sale a la red. Mejor decidirlo ya: doblar `sondear_backend`. (c) Después de T7.6, el
daemon se queda con código sin publicar. Hay que decir si se reinstala la 0.32.0 al terminar.

### Lo que he comprobado y está bien

- **Controles positivos que fallan por el assert que el plan dice**:
  - `test_accounting_un_fallo_no_ahorra_ni_genera`: hoy da `saved` 1000, porque la unidad por
    defecto es `chars` (`server.py:625-627`).
  - `test_stats_el_log_de_la_mac_no_infla_nada`: hoy da 4 estimados.
  - `/api/backend` hoy pide `/running` antes que `/models` (`web/metrics.py:596-604`).
  - `pollInflight` hace dos `fetch` por llamada (`:1539`): son 6 hoy y 2 con la guarda.
  - `F.format(8003)`: hoy da `8003`, y con `useGrouping:'always'` da `8.003`. Lo he medido en node
    24 en local, y CI usa node 20, que también lo admite.
  - El mutante de `F1` sin agrupar da `1718,3`, y muta.
  - El mutante 1 de T2 (reglas 6 y 7) y el mutante de la paridad (`!e.ok`, con el caso sin clave
    `ok`; `_ev` pone `ok: True` por defecto, así que hay que quitar la clave a mano) mutan.
  - El mutante «hero con `tokens_context_saved`» muta, siempre que el caso bueno tenga
    `chars_out > 0`.
- **Guardianes del repo**:
  - Finales de línea: coinciden con `git ls-files --eol` (`server.py`, `web/metrics.py`,
    `CHANGELOG.md` y `tests/test_dashboard_ui.py` en CRLF; el resto en LF).
  - `test_captura.py`: T4 no crea endpoints nuevos y T6 completa el mock.
  - `test_aislamiento_entorno.py`: las constantes nuevas no leen el entorno, así que no necesitan
    `_env*`.
  - Tabla del doctor: no cambia `checks.CHECKS`.
  - Comandos pesados: todos pasan por `pesado.sh`; `ruff`, que es ligero, va fuera.
- **Alcance**: ninguna tarea hace trabajo que no pida un REQ, y todos los REQ tienen tarea.

### Evidencia que pido para aprobar el gate

El plan corregido con los hallazgos 1 a 7, y en `verification.md`, por cada control, el assert que
de verdad disparó. Y en particular, la salida de la verificación de T3 con los tests de `:182` y
`:280` ya en verde, con la caché limpia entre un test y otro.

Llamadas `local_*` de esta revisión: 1 (`local_summarize(path=research.md)`). La spec y el plan los
leí literalmente por franjas, como pide el encargo.


## Revisión de la spec

Revisor adversario, solo lectura, 2026-10-06. Leídos literalmente: `spec.md` (entera, por
franjas), `brief.md`, `research.md`, `insumos/tipografia-panel.md` (estructura y tabla de
desviaciones) y el código en `130afab` (`server.py`, `web/metrics.py`, `fallos.py`, `config.py`,
`checks.py`, `doctor.py`, `daemon.py`, `tests/test_metrics.py`, `httpcore2/_backends/sync.py`,
`.github/workflows/ci.yml`). `insumos/anomalias-panel.md` resumido con `local_summarize` y
comprobado a mano con `grep` en los puntos citados. Cifras recalculadas con un script de solo
lectura (`scratchpad/revisa_neto.py`) sobre los `usage-*.jsonl` reales.

**Veredicto propuesto: aprobable con cambios.** Las causas de `research.md` son reales y las
líneas citadas cuadran (comprobadas una a una en los puntos de abajo). Las cifras cuadran
exactamente. La regla de contabilidad es determinista e idéntica en las dos copias. Pero el
clasificador de fallos no es exhaustivo y deja ambiguo el caso del 401, que es justo el que la
spec quiere arreglar, y la interfaz con `coste-api-y-cuota` no fija ni la unidad ni el desglose
que el otro cambio necesita. Las dos cosas se arreglan editando el texto de la spec.

### BLOQUEANTE

**1. El clasificador no es exhaustivo y el 401 real no casa literalmente con la regla 1** (REQ-010).
- Evidencia: el 401 de llama-swap llega hoy como `httpx2.HTTPStatusError` lanzado por
  `raise_for_status()` (`server.py:2987`; `research.md` §2, fila «Backend real… sin credencial»).
  La tabla dice «Respuesta 401 o 403», pero la entrada puede ser «una excepción **o** el código».
  Si quien implementa le pasa la excepción, que es lo natural, la regla 1 no aplica en sentido
  literal, y como `HTTPStatusError` es un `httpx2.HTTPError`, cae en la regla 10 (`transporte`).
  El `fallos.py` de hoy sí tiene una rama explícita para eso (`_clasificar_excepcion`,
  `isinstance(exc, httpx2.HTTPStatusError)` → `status_code`).
- Además, hay entradas que no casan con **ninguna** regla: `_models_with_status` hace
  `r.json().get("data", [])` (`server.py:2988`), así que un 2xx cuyo cuerpo es una lista JSON
  lanza `AttributeError`, y un `data` que no es una lista puede lanzar `TypeError`. Ninguno de los
  dos es `ValueError` ni `HTTPError`, así que hoy esa excepción se escapa del `except` y
  `/api/backend` responde 500. La regla 9 promete «cuerpo que… no tiene la forma esperada», pero
  no hay ninguna regla para esos tipos. `httpx2.InvalidURL` (una `LOCAL_DELEGATE_BASE_URL`
  errónea) tampoco es un `HTTPError`. Es el fallo de tipo (c) de la casa: la regla no se puede
  ejecutar para todas las entradas.
- Arreglo: (a) en la regla 1 y la 2, «Respuesta, o `httpx2.HTTPStatusError` (se usa
  `response.status_code`), con 401/403 → `credencial`, otro → `http_error`»; (b) que el sondeo
  valide la forma del cuerpo y convierta un cuerpo inválido en `ValueError` (o que pase la causa
  `respuesta_invalida` directamente), de modo que la regla 9 sea la única puerta; (c) añadir la
  regla 11: «cualquier otra excepción → `transporte`» (o una causa `desconocida` con su texto),
  para que la tabla sea total. Un test con `HTTPStatusError(401)` **construido** debe dar
  `credencial`.

**2. La interfaz con `coste-api-y-cuota` no fija ni la unidad ni el desglose que ese cambio
consume** (REQ-001, REQ-003).
- Evidencia: el otro cambio pide «por evento: el neto en **caracteres** (o, si el otro cambio lo
  deja en tokens `chars/4`, ese valor…)» (`../coste-api-y-cuota/spec.md`, «Dependencia
  declarada»). Su REQ-020 excluye de la base las **imágenes** y el **ahorro de salida a fichero**.
  Esta spec solo expone `net` por evento en tokens con suelo (`÷`), y `net` mezcla las dos cosas
  que el otro excluye: con `source=path` + `output_to_file`, `saved` = entrada + `tokens_out`; con
  una imagen, `saved` son tokens del modelo **local** y `returned` es `chars_out ÷ 4`. Desde `net`
  no se puede reconstruir la base del otro cambio. Y, al revés, el REQ-011 del otro cambio dice
  que «el ahorro de contexto neto del panel y de `/api/stats`» pasará a contarse con
  `c_central = 2,1`: si redefine `tokens_context_net`, las cifras de esta spec (800 928, el
  escenario del KPI) dejan de valer sin que ninguna de las dos specs lo diga.
- Arreglo: declarar en esta spec, como contrato: (a) `tokens_context_net` y `net` están **siempre**
  en unidades de `CHARS_PER_TOKEN` (÷ 4) y el otro cambio añade su propio campo en tokens de
  Claude, en vez de redefinir este; (b) `_accounting`/`acct` devuelven también el desglose que hace
  falta (`saved_in`, `saved_out` y `returned`, o directamente `net_chars` = `chars_in − chars_out`
  para los eventos buenos con `source=path` y unidad `chars`, y 0 en otro caso), con el mismo
  predicado de fallo; (c) el test de paridad cubre esos campos. Que la otra spec cite estos nombres.

### IMPORTANTE

**3. El test de paridad no tiene la lista de casos nuevos, y su guarda no los exige** (REQ-001,
REQ-002; restricción del brief «tiene que cubrir los casos nuevos: fallo, neto»).
- Evidencia: `test_paridad_acct_entre_python_y_el_js_del_panel` compara campo a campo una lista
  fija (`tests/test_metrics.py:728-734`: `calls`, `tokensIn`, `tokensOut`, `saved`, `estimated`,
  `fallback`, `cause`) y solo guarda `fallback` y `configuracion` (`:737-738`). Si `returned` y
  `net` no se añaden a esa lista, la paridad sale verde con el JS roto. La spec solo dice
  «paridad Python/JS» en la trazabilidad.
- Arreglo: que la spec fije los casos mínimos de la paridad: fallo sin tokens, fallo con tokens,
  `ok: null`, evento sin `ok`, neto negativo, `output_to_file` con `source=path` e `inline`, imagen
  por `path` con y sin `tokens_in`, y `chars_in` menor que 4. Que exija comparar `returned` y `net`,
  y una guarda de «esto llegó a comprobar algo» (`any(net < 0)`, `any(fallo con tokens)`). He
  comprobado que Python (`row.get("ok") is False`) y JS (`e.ok === false`) coinciden en `null`,
  en un `ok` ausente y en `0`. Las dos copias usan el mismo `//`/`Math.floor` sobre enteros no
  negativos.

**4. El neto negativo «se enseña tal cual» pero los gráficos lo esconden** (REQ-004, caso
borde «Neto negativo»).
- Evidencia: `agg()` filtra `x[1] > 0` (`web/metrics.py:1797-1800`), así que una herramienta con
  neto negativo **desaparece** de «Ahorro por herramienta» al pasar a `acct(e).net`. La chispa
  fija `y:{min:0}` (`drawSpark`, `:1774`) y recorta un acumulado negativo. Hoy pasa de
  verdad: septiembre tiene un evento con neto negativo (recalculado: 1).
- Arreglo: decir qué hace cada gráfico con negativos. Por ejemplo: «Ahorro por herramienta» filtra
  `!== 0`, el eje admite valores por debajo de 0 y las barras negativas llevan otro color; la
  chispa quita `min:0`. O bien limitar los gráficos a ≥ 0 y decirlo en el tooltip. En los dos casos,
  con un escenario.

**5. Las pruebas de red reales no incluyen el caso que justifica el plazo de 3 s, ni dicen en qué
sistemas corren** (REQ-010, REQ-013).
- Evidencia: el plazo de 3 s existe para que un puerto cerrado **en un host no loopback** (un
  llama-swap apagado en la PC, visto desde otra máquina Windows) llegue como «rechazada» y no como
  timeout: medido 2,14 s contra la IP de Tailscale (`research.md` §2). El escenario real prueba DNS,
  un puerto cerrado **en loopback** (que la regla 6 da por «rechazada» con cualquier plazo, así que
  no discrimina el plazo) y `192.0.2.1` con 0,5 s. Ninguno puede fallar si alguien deja el plazo en
  1 s. Además, el CI corre la suite en `ubuntu-latest`, `windows-latest` y `macos-latest`
  (`ci.yml:120-122`), y la spec dice «esta máquina». No se sabe si el test se salta fuera de
  Windows ni qué se espera en macOS, donde el rechazo es inmediato.
- Arreglo: añadir el caso «puerto cerrado en una IP propia no loopback, con la constante de
  producción → `rechazada`» (en Windows es el control del plazo; en Linux y macOS pasa igual porque
  el rechazo es inmediato). Exigir que los cuatro casos reales corran en los tres sistemas del CI
  sin `skip`, con el resultado esperado por sistema. Añadir un test puro del caso de la Mac:
  `ConnectTimeout` con `TimeoutError(errno.ETIMEDOUT)` en la cadena contra un host remoto →
  `timeout_conexion`, porque los 75 s del kernel de macOS no se pueden reproducir en CI.

**6. `doctor` mezcla el 401 del daemon con el de la consola** (REQ-016).
- Evidencia: hoy, si el **daemon** dice «no disponible», `checks.py:155-160` lo trata como
  diagnóstico firme, y lo comenta adrede: «aquí no cabe el `unknown` del 401», porque el daemon sí
  tiene credencial. La spec hace `UNKNOWN` toda causa `credencial` y da la pista «exporta
  LOCAL_DELEGATE_API_KEY en este entorno», venga de donde venga. Si el 401 lo ve el daemon, lo que
  falla es la clave **del lanzador del daemon**, y esa pista manda a tocar la consola, que no sirve
  de nada.
- Arreglo: que la tabla de REQ-016 distinga la fuente. Con `credencial` vista por el daemon:
  `WARN`, con la pista «la clave del daemon no vale: revisa su lanzador». Con `credencial` del
  sondeo directo: `UNKNOWN` con la pista de hoy. Relacionado: la consulta al daemon tiene un plazo
  de 1 s (`daemon.query_backend(..., timeout=1.0)`, `checks.py:154`) y el daemon tardará hasta 3 s
  con el backend inalcanzable. Lo detalla el hallazgo 4 de la revisión del plan, pero la spec
  debería fijar en REQ-016 que ese plazo supera al del sondeo.

**7. «Esperando turno» también cuenta la cola propia de local-delegate** (REQ-022, fila 8).
- Evidencia: la llamada se registra en vuelo **antes** de pedir plaza en el semáforo propio
  (`_inflight_start` en `server.py:1236`; `with _chat_slots:` en `server.py:1117`,
  `MAX_CONCURRENT_REQUESTS` = 2). Una tercera delegación en paralelo que espera plaza **en
  local-delegate** sale como «esperando turno» con el `title` «ocupa el sitio: <modelo>», y le
  atribuye a llama-swap una espera que es nuestra. El cambio va justamente de dar la causa real.
  Pasa lo mismo con un respaldo: la entrada en vuelo lleva el modelo pedido, no el que responde.
- Arreglo: que la entrada en vuelo marque si ya tiene plaza, para distinguir «en cola de
  local-delegate» de «esperando a llama-swap». O, como mínimo, que el `title` de la fila 8 no
  afirme la causa («puede estar esperando plaza aquí o en llama-swap»). En el mismo `title`,
  nombrar también los modelos en `starting`, no solo los `ready`.

**8. El escenario de septiembre consume un fichero que solo existe en esta PC** (control positivo
con datos reales).
- Evidencia: el escenario parte de «el `usage-202609.jsonl` de esta PC». Ese log guarda `path` de
  ficheros del usuario, así que no puede ir al repo como *fixture*, y en CI no existe. Las cifras sí
  cuadran: con mi script salen bruto hoy 983 871 → 873 270, devuelto 72 342, neto 800 928,
  estimados 7 → 0, coste local 1 283 211 → 1 172 213, y agosto 261 048 → 178 756 (−31,5 %, el
  «−32 %» citado).
- Arreglo: declararlo como **paso manual de verificación** (sin *fixture* en el repo), con el
  comando que lo reproduce y el fichero de salida donde queda la evidencia. Si se quiere en CI, que
  sea con un extracto anonimizado (sin `path`) que dé las mismas sumas.

### MENOR

**9. Cita de `httpcore2` desplazada.** `research.md` §2 cita `sync.py:150-152`, que es
`start_tls`. El mapa de `connect_tcp` está en `:198-200`. El contenido es el mismo
(`socket.timeout → ConnectTimeout`, `OSError → ConnectError`), y también confirma que
`create_connection` aplica el plazo **a cada dirección**, así que `localhost` (::1 y luego
127.0.0.1) no suma 4 s contra el plazo de 3 s.

**10. Los textos por causa piden configuración a un módulo que no la lee.** REQ-011 dice que
`fallos.py` produce el detalle «con el host (`config.backend_host()`)», pero `fallos.py` «no conoce
la configuración» (su docstring; `research.md` §7). Arreglo: el host entra como parámetro.

**11. El detalle de `respuesta_invalida` solo vale para `/models`.** «no con una lista de modelos
válida» también saldría para `/running` y `/api/metrics/stats` (REQ-020). Arreglo: un texto
neutro, o el endpoint como parámetro.

**12. El badge dice «caído» cuando hay alguien contestando.** Con `http_error`,
`respuesta_invalida` y `sin_respuesta`, el backend acepta la conexión. «caído · responde con
error» se contradice. Valorar el ámbar de `credencial` también para estas tres causas (REQ-014).

**13. El predicado de fallo sigue duplicado en el JS.** `render` cuenta con `!e.ok` cuando falta
`total.errors` (`web/metrics.py:1704`) y la tabla de actividad pinta el punto con `e.ok?'ok':'err'`
(`:1893`). Con `ok: null`, el punto saldría rojo y el evento no contaría como error. Que REQ-006
abarque también esos dos sitios (`e.ok === false`).

**14. Faltan los tres caminos del log en REQ-017.** `fallo_conexion` tiene que salir en la
delegación simple, en la troceada y en la de imagen (`server.py:1283`, `:1602`, `:1933`, los
mismos que cita `research.md` §1). Hay que nombrarlos y decir en qué campo de `ChatResult` viaja.

**15. Tipografía: el escenario no ve tres de los siete arreglos** (REQ-034). `getComputedStyle()`
devuelve la familia declarada aunque falte la cara 400, así que el arreglo (f) se comprueba con
`document.fonts` o mirando la URL. Los arreglos (e) y (g) no tienen escenario. Además, falta decidir
la familia de la nota de cómputo remoto de REQ-025: es prosa (Inter), pero ocupa la fila del estado
vacío (mono).

**16. `useGrouping: 'always'` depende del navegador** (REQ-030). Un navegador sin
`Intl.NumberFormat` v3 lo convierte en `true` y vuelve a pintar `8003` sin avisar. El panel se abre
desde la Mac, y Playwright solo prueba Chromium. Arreglo: anotar la versión mínima de Safari o
formatear con una función propia.

**17. Detalles de formato y redacción.** Una latencia menor de 50 ms saldría «0,0 s»: falta decir
el mínimo (p. ej. «< 0,1 s»). El escenario «el log de la Mac» usa 4 fallos y el real tuvo 5: hay
que rotularlo como sintético. La coletilla de ahorro que devuelve cada tool (`_savings_feedback`,
`server.py:1185-1195`) sigue diciendo el **bruto**, con `tokens_in` del modelo local cuando lo
hay, mientras el panel pasa a enseñar el neto. Hay que añadirlo a los no-objetivos para que nadie
lo lea como olvido.

**18. «En curso» se congela mientras el backend no responde.** `pollInflight` pide `/api/inflight`
y `/api/backend` en el mismo `Promise.all` (`web/metrics.py:1539`). Con el backend inalcanzable,
«En curso» se congela hasta 3–5 s por ciclo. Desacoplar las dos peticiones lo evitaría (REQ-026).

### Alcance frente al brief

- **Sobra poco y está justificado:** las delegaciones que no preguntan «¿Lo arranco?» (REQ-018) y
  su texto con la causa (REQ-017) van algo más allá de la letra del brief, que solo nombra
  `doctor`, pero salen de la causa 8 verificada en `research.md`. El refresco al reconectar
  (REQ-027) y la chip que acepta cualquier estado (REQ-023) son pequeños y vienen de los insumos.
- **Plazo de conexión de 180 s de las delegaciones: recomiendo que entre.** Es la causa directa
  de que cada fallo de la Mac bloqueara unos 75–95 s (`anomalias-panel.md`, punto 10: «~95 s de
  media», con hasta 30 s de la pregunta). El cambio es pequeño
  (`httpx2.Timeout(config.HTTP_TIMEOUT, connect=<constante>)`, sin variable nueva), no afecta a la
  carga del modelo (llama-swap acepta la conexión al instante y la espera de carga es de
  **lectura**), y el clasificador nuevo ya cubre su `ConnectTimeout`. Propuesta: un requisito con
  una constante de unos 10 s y un test real contra `192.0.2.1` que termine en ese plazo más un
  margen, con `fallo_conexion: timeout_conexion`. Como el brief no lo incluye, que lo decida Yohan.
- **Histéresis de dos sondeos antes de «CAÍDO»: que quede fuera.** Con el sondeo encadenado
  (REQ-026) y el plazo de 3 s, el parpadeo que la motivaba se reduce mucho, y la histéresis
  retrasaría unos 10 s un «caído» real, que es lo que este cambio quiere decir antes y mejor. Si
  después de mezclar se mide que parpadea, se reabre.
- **No falta nada del brief:** contabilidad, neto, causas compartidas, estados, presentación y docs
  están todos, y las tres preguntas abiertas tienen respuesta con evidencia (`research.md` §4–§5).

### Lo que he comprobado y está bien

- Las cifras de `research.md` §3 para julio, agosto y septiembre salen **exactas** con mi script
  (incluido el coste local). Octubre ha crecido desde la investigación (130 eventos frente a 124),
  como es normal en un mes abierto.
- La regla de contabilidad es total y determinista. El fallo con tokens existe de verdad (agosto,
  1 evento) y la regla lo trata como dice el escenario del troceo.
- La tabla de 10 filas de REQ-022 es exhaustiva y determinista: cada combinación de disponible, en
  vuelo, `running_ok` y estado cae en una sola fila por orden. Mis reparos (hallazgo 7) son de
  significado, no de cobertura.
- Las reglas 3 a 7 del clasificador se ordenan sin ambigüedad. En Windows,
  `errno.ENETUNREACH == 10051` y `EHOSTUNREACH == 10065` (comprobado), así que la regla 5 repite
  los números sin daño y en macOS sigue valiendo por el nombre.
- Las líneas citadas de `web/metrics.py` (1215, 1342, 1463-1466, 1502, 1513-1514, 1541, 1602,
  1626, 1631, 1653, 1715, 1731, 1822, 1892, 1937), `server.py` (579-643, 868-906, 2982-3017,
  3050-3052, 3080-3101), `config.py:68`, `checks.py:1296-1308` y `doctor.py:265-290` dicen lo que
  la investigación afirma.

### Evidencia que pido para aprobar el gate

Spec editada con los arreglos 1 y 2 (tabla total del clasificador, `HTTPStatusError` explícito y
contrato de unidad y desglose firmado también en `coste-api-y-cuota`), la lista de casos de
paridad (3), qué hacen los gráficos con un neto negativo (4), las pruebas de red por sistema (5),
la fuente del 401 en `doctor` (6), y la decisión de Yohan sobre el plazo de conexión de 180 s.

Llamadas `local_*` de esta revisión: 1, `local_summarize(path=insumos/anomalias-panel.md)`. No pasé
por `local_*` la spec, la investigación ni el código: el encargo pide verificar REQ, cifras y
`fichero:línea` literalmente, y un resumen no da líneas. Leí la spec por franjas y el código con
`sed`.


## Respuesta a la revisión

Corrección de spec y plan, 2026-10-06. Entran además las dos decisiones del usuario del brief
(plazo de conexión de 10 s y dos sondeos antes de «caído») y la decisión de arquitectura de la
sesión principal sobre la interfaz con `coste-api-y-cuota` (una sola función de conversión,
desglose en caracteres). Evidencia nueva, de solo lectura: `scratchpad/contrato.py` y
`scratchpad/contrato_chars.py` sobre los cuatro `usage-*.jsonl` reales, `httpx2` instalado (jerarquía
de excepciones) y node 24 (mutante de `Intl`).

### Revisión de la spec

| # | Hallazgo | Resolución | Dónde |
|---|---|---|---|
| S1 (BLOQUEANTE) | Clasificador no exhaustivo; el 401 llega como `HTTPStatusError` | Tabla total de 12 reglas: `HTTPStatusError` explícito en las reglas 1 y 2; `InvalidURL`/`UnsupportedProtocol` → `url_invalida` (regla 3; `InvalidURL` no es `HTTPError`, comprobado); regla 12 «cualquier otra excepción → `desconocida`». El sondeo valida la forma del cuerpo, la convierte en `ValueError` y no lanza nunca. Tests con `HTTPStatusError(401)` construido y con un 200 cuyo cuerpo es `[]` | REQ-010, REQ-011, REQ-012; T2, T3 |
| S2 (BLOQUEANTE) | La interfaz con `coste-api-y-cuota` no fija unidad ni desglose | Sección «Contrato con `coste-api-y-cuota`»: campos por evento con nombre y unidad exactos (`chars_saved_text`, `bytes_saved_image`, `chars_saved_output`, `chars_returned`, `failed`, `tool`, `model`, `source`, `unit`), totales en `/api/stats`, y una sola función `tokens_claude`/`tokensClaude` con la regla de hoy, que el otro cambio sustituye. **Discrepancia con el arreglo (a) propuesto** (dejar `tokens_context_net` siempre en ÷ 4 y que el otro cambio añada su campo): la sesión principal decidió lo contrario, y la consecuencia queda escrita: las cifras en tokens cambiarán con `coste-api-y-cuota`, las de caracteres no, por eso el control de septiembre se fija en las dos. **Desviación del encargo**: el desglose de imagen va en **bytes** (`bytes_saved_image`), no en caracteres, porque el log guarda bytes en `chars_in` para las imágenes; llamarlo «chars» repetiría el defecto que `_accounting` ya documenta. Comprobado que la regla nueva da las mismas cifras en tokens que la primera en julio–octubre. La cita de estos nombres en la spec de `coste-api-y-cuota` queda pendiente: esa carpeta no se toca aquí | REQ-007, REQ-008, Contrato; T1 |
| S3 | La paridad no lista los casos nuevos | Lista de 12 casos mínimos, todos los campos del contrato comparados con `.get`, y guarda con cinco condiciones | REQ-001; T1 |
| S4 | El neto negativo desaparece de los gráficos | «Ahorro por herramienta» enseña neto ≠ 0 (opción de `agg`, sin romper el test de `agg` de hoy); la chispa pierde `min:0`; la serie por día ya admitía negativos. Escenario nuevo | REQ-004; T1 |
| S5 | Las pruebas de red no discriminan el plazo de 3 s ni dicen el sistema | Caso nuevo con la IP propia no loopback y el plazo de producción, en los tres sistemas sin `skip`; test puro del caso de la Mac (`ConnectTimeout` ← `TimeoutError(ETIMEDOUT)`) | REQ-010, REQ-013, escenarios; T2, T3 |
| S6 | `doctor` mezcla el 401 del daemon con el de la consola | `VistaBackend` lleva la `fuente`; `credencial` vista por el daemon es `WARN` con la pista del lanzador, la del sondeo directo `UNKNOWN`; la consulta al daemon lee durante 6 s (más que el techo de su sondeo) | REQ-016; T2, T3 |
| S7 | «Esperando turno» cuenta la cola propia | Campo `esperando_plaza` en la entrada en vuelo (solo se escribe cuando de verdad falta plaza), fila nueva «en cola local», y el `title` de «esperando turno» ya no afirma la causa y nombra también los modelos que cargan. El respaldo queda como limitación anotada | REQ-022, casos borde; T3, T4 |
| S8 | El escenario de septiembre usa un fichero que solo está en esta PC | Paso **manual** de T7 con el comando y la salida a `verification.md`; sin *fixture* en el repo | Escenario de septiembre; T7.3 |
| S9 | Cita de `httpcore2` desplazada | Corregida en `research.md` §2 (`:198-200`) | `research.md` |
| S10 | `fallos.py` no lee configuración | El host, el código y el endpoint entran como parámetros | REQ-011 |
| S11 | El detalle de `respuesta_invalida` solo vale para `/models` | Texto neutro con el endpoint como parámetro | REQ-011 |
| S12 | El badge dice «caído» con alguien contestando | `credencial`, `http_error`, `respuesta_invalida` y `sin_respuesta` van en ámbar y sin «caído» | REQ-014; T4 |
| S13 | Predicado de fallo duplicado en el JS | REQ-006 cubre el respaldo de `render` y el punto de la tabla de actividad; test que busca los dos literales | REQ-006; T1 |
| S14 | Faltan los tres caminos del log | Nombrados (simple, troceada, imagen) y el campo de `ChatResult`; test parametrizado por los tres | REQ-017; T3 |
| S15 | El escenario de tipografía no ve tres arreglos | (f) por la URL del `<link>`; (e) y (g) con su escenario y su test; la nota remota en Inter como arreglo (h) | REQ-034, REQ-025; T5, T4 |
| S16 | `useGrouping: 'always'` depende del navegador | Formateador propio `fmtNum`; test con un `Intl` que emula un navegador sin v3 (mutante ejecutado en node 24: da `8003`) | REQ-030; T5 |
| S17 | Latencia < 50 ms, Mac sintético, coletilla en bruto | «< 0,1 s»; escenario rotulado como sintético; la coletilla de ahorro va a los no-objetivos (la cambia `coste-api-y-cuota`, su REQ-011) | REQ-032, escenarios, Non-goals |
| S18 | «En curso» se congela con el backend caído | `/api/inflight` y `/api/backend` se piden por separado, cada uno con su guarda | REQ-026; T4 |
| Alcance: plazo de 180 s | Recomendaba que entrara | Entra por decisión del usuario: 10 s solo para conectar, con el `min` frente a `HTTP_TIMEOUT`, test de configuración y test real contra TEST-NET-1 (en esta PC hoy tarda ~21 s) | REQ-019; T3 |
| Alcance: histéresis | Recomendaba dejarla fuera | **Discrepancia resuelta por el usuario**: entra. Se acota para no esconder un caído real: un sondeo bueno recupera al instante, el primer fallo conserva lo pintado pero lo dice en el `title`, y `local_status` y `doctor` no tienen histéresis | REQ-028; T4 |

### Revisión del plan

| # | Hallazgo | Resolución | Dónde |
|---|---|---|---|
| P1 (BLOQUEANTE) | T3/T4 rompen tests de `test_metrics.py` que no son suyos, y la caché los contamina | Lista guardada **por `BASE_URL`** y fixture autouse en `tests/conftest.py` (dueño T3) que la vacía; test nuevo con su mutante «sin clave por URL». Con la fixture, T3 no rompe ningún test de `test_metrics.py` y su verificación lo exige en verde sin tocarlo. Los cinco tests de endpoints que comparan el JSON entero los actualiza T4, con zona propia en la tabla de propiedad (T1 → T4). Variante frente al arreglo propuesto: T3 no necesita zona en `test_metrics.py` | Propiedad; T3 pasos 3 y verificación; T4 |
| P2 | El mutante de `estadoModelo` no muta | Tres mutantes, cada uno con su caso y por qué muta: la 9 antes que la 6, la 4 antes que la 1, y quitar la 3. Las condiciones de la tabla se leen tal cual (la de la 9 es solo «en vuelo»), que es lo que hace mutar al primero | REQ-022; T4 |
| P3 | Controles que solo fallan por excepción | Tercer tipo de control, (c) «corte intermedio». Paridad: `tokensClaude` existe antes (si no, la extracción da `ValueError`, trampa nueva que no estaba en la revisión) y el caso y el campo que disparan van primero. `doctor` remoto: (c) tras el cambio de tipo. `backend_probe`: se lee `[1]`. T4: el assert de control es `models_stale`. Revisados además los demás: el test de `F` no extrae `fmtNum` si no existe, el de `local_status` no formatea un `None`, y el del refresco al reconectar pasa a (b) porque llama a una función nueva | Plan, controles; T1, T3, T4, T5 |
| P4 | `doctor` descarta la causa del daemon en los fallos lentos | Lectura de 6 s y conexión de 1 s en la consulta al daemon; test de la desigualdad con control (c) y mutante «vuelve a 1,0»; T7.6 corre `doctor` contra el daemon | REQ-016; T3 paso 9; T7.6 |
| P5 | Ola B verifica sobre ficheros a medio editar | Worktree por tarea en las olas A y B, integración por la sesión principal y verificación de la ola en el árbol integrado. Se aplica también a la ola A, que tenía el mismo defecto (`server.py` importa `fallos.py`). Se prefirió a la serie T5 → T3 para no perder el paralelo | Approach, olas |
| P6 | Requisitos sin verificación que pueda fallar | REQ-006 (`ok: None`), REQ-027 (refresco), REQ-023 (`chipEstado`), REQ-018 con `AUTOSTART` en los dos valores, REQ-020 rama positiva, REQ-012 en `/api/status`, REQ-014 texto y `title`: un test cada uno | T1, T3, T4 |
| P7 | Extremo a extremo incompleto | `doctor` contra el daemon reinstalado, con criterio de fallo; panel leído en bucle con `browser_evaluate` y criterio de fallo explícito | T7.6 |
| P8 | El grep de `(s)` choca con el código | Se buscan los cuatro literales concretos | T5 |
| P9 | El mutante de 1 s supone algo sin medir | Paso 0 de T3: medir antes de escribir, con test sustituto si no muta | T3 paso 0 |
| P10 | Zonas por línea que envejecen | Zonas solo por función; `node --check` del JS al cerrar cada tarea que toca `web/metrics.py` | Propiedad, reglas comunes |
| P11 | `local_status` tarda 6 s; doble de `test_observabilidad_respaldo`; daemon con código sin publicar | `local_status` no pide `/running` si `/models` falló (con test); la fixture dobla `sondear_backend`; T7.7 reinstala la 0.32.0 publicada, porque el daemon enseñaría a diario la cifra intermedia | REQ-013; T3 paso 4; T7.7 |
| Trampa nueva | Los tests de `byDay` de `test_dashboard_js.py` extraen `acct` y, cuando `acct` llame a `tokensClaude`, node daría `ReferenceError` | T1 actualiza sus listas de extracción; por eso `test_dashboard_js.py` pasa a tener zona de T1 antes que de T5 | Propiedad; T1 |

### Lo que queda abierto

- Que la spec de `coste-api-y-cuota` cite los nombres del contrato y la firma de `tokens_claude`
  (no se edita desde aquí).
- El paso 0 de T3 puede cambiar el control de REQ-013 si en esta PC el mutante de 1 s no muta.
- Que las pruebas de red real den lo esperado en los runners de macOS y Ubuntu solo se sabrá en el
  primer CI; si un runner da otra causa, se investiga y se decide, sin `skip` silencioso.


## Segunda pasada

Revisor adversario, solo lectura, 2026-10-06. Leídos literalmente, por franjas: `spec.md`,
`plan.md`, `review.md` y `brief.md` enteros. Lo he contrastado con el código en `130afab`:
`server.py` (`_accounting`, `_models_with_status`, `_run_chat`, `_post_chat`), `web/metrics.py`
(`agg`, `barH`, `drawSpark`, `_aggregate`), `config.py` (`backend_host`, `backend_origin`,
`_is_loopback_host`), `doctor.py`, `daemon.query_backend`, `tests/backend_mock.py`,
`tests/test_metrics.py`, `tests/test_core.py`, `tests/test_fallos_integracion.py`,
`tests/test_post_chat_caminos.py`, `tests/test_doctor.py` y `tests/test_respaldo.py`. Además he
leído `../coste-api-y-cuota/spec.md` (sección «Dependencia declarada»). He ejecutado de nuevo
`scratchpad/contrato.py` y `scratchpad/contrato_chars.py`, `_accounting` de hoy sobre los eventos
de los escenarios, el envoltorio de `Intl` en node 24 y la construcción de `OSError` en Python.

**Veredicto: la spec todavía no es aprobable, y el plan tampoco.** Las dos se arreglan editando
texto, sin investigar nada más. A la spec le falta una corrección importante (la histéresis y las
filas de modelos, F2), y su contrato con el otro cambio sigue sin cerrar por la otra parte. El plan
tiene un bloqueante del mismo tipo que el P1 de la primera pasada (F1) y un fallo importante en la
integración de los worktrees (F3).

### Veredicto por hallazgo (BLOQUEANTES e IMPORTANTES)

Lo he comprobado en `spec.md` y `plan.md`, no en la tabla de respuesta.

| # | Hallazgo | Veredicto | Comprobación |
|---|---|---|---|
| S1 (B) | Clasificador no exhaustivo; el 401 llega como `HTTPStatusError` | **Resuelto** | REQ-010 tiene 12 reglas, ordenadas y con la primera que casa. La 12 cierra la tabla, y en el plan la función acaba en `return DESCONOCIDA`. `HTTPStatusError` va explícito en las reglas 1 y 2, `InvalidURL` va por nombre antes que `HTTPError`, y la cadena se recorre con un conjunto de visitados. En la práctica es determinista. Quedan tres detalles menores (F9, F7 y F8). |
| S2 (B) | Contrato con `coste-api-y-cuota`: unidad y desglose | **Parcial** | En esta spec está bien. Los nombres y las unidades están en las dos copias (Python y JS), `bytes_saved_image` va en bytes y hay una sola `tokens_claude`/`tokensClaude`, con la regla de hoy en tabla. Las cifras cuadran: `contrato.py` da neto viejo = neto nuevo en julio, agosto, septiembre y octubre (227 363 / 177 751 / 800 928 / 615 518), y `contrato_chars.py` da para septiembre 3 463 739 / 1 489 047 (5 imágenes) / 5 237 (3 eventos) / 289 554, lo mismo que esperan la spec y T7.3. Pero el contrato solo lo firma una parte. `../coste-api-y-cuota/spec.md` sigue diciendo que **«no la redefine»**, que pide «el neto en caracteres» por evento y que su orden es «primero aquel, luego este». Y la promesa de «salen en la misma versión» no tiene ningún mecanismo que la haga cumplir (F4). |
| S3 | Casos de la paridad | **Resuelto** | REQ-001 lista los 12 casos, exige comparar todos los campos con `.get` y pone una guarda con cinco condiciones, cada una cubierta por algún caso. |
| S4 | Neto negativo en los gráficos | **Resuelto** | `agg` filtra `!== 0` con la opción y `drawToolDonut` es una barra horizontal (`barH`, con `beginAtZero` y sin `min`). La chispa pierde `min:0`. El control (a) de `agg` falla por el assert, porque hoy ignora el cuarto argumento. |
| S5 | Las pruebas de red real no discriminan el plazo ni dicen el sistema | **Resuelto** | La IP propia no loopback está en T3 con el paso 0 de medición, el caso de la Mac es un test puro y se pide «sin `skip`» en los tres sistemas. El riesgo del CI queda declarado como abierto. |
| S6 | `doctor` mezcla el 401 del daemon con el de la consola | **Resuelto** | La pista depende de causa y fuente, y la severidad es `WARN` o `UNKNOWN` según la fuente. La consulta al daemon usa 1 s para conectar y 6 s para leer, y `query_backend` acepta un `httpx2.Timeout`, porque lo pasa a `httpx2.Client(timeout=…)`. Detalle menor en F15. |
| S7 | «Esperando turno» cuenta la cola propia | **Resuelto** | Se añaden `esperando_plaza` y la fila 3 «en cola local», con su mutante. Las delegaciones troceadas llaman a `_run_chat` en serie (en `server.py` no hay *pool* de hilos), así que marcar y desmarcar la entrada no tiene carrera. |
| S8 | Septiembre depende de un fichero que solo existe en esta PC | **Resuelto** | Queda como paso manual T7.3. He comprobado que `_aggregate(rows)` existe con esa firma y que `tokens_context_saved` y `estimated_events` están en el primer nivel. |
| Alcance: 180 s | Plazo de conexión de las delegaciones | **Resuelto** | REQ-019 y sus tres tests en T3. `respaldo` no salta con `connect_error` (`test_respaldo.py:153`), así que los 10 s no se multiplican. |
| Alcance: histéresis | Recomendaba dejarla fuera | **Discrepancia justificada** (la decidió el usuario), pero introduce F2 | — |
| P1 (B) | Tests de `test_metrics.py` sin dueño y caché que contamina | **Resuelto para `test_metrics.py`** | La fixture autouse y la clave por `BASE_URL` están en T3, el test del mutante «sin clave por URL» muta, y T4 tiene zona propia. **El mismo defecto reaparece en otros ficheros: F1.** |
| P2 | El mutante de `estadoModelo` no muta | **Resuelto** | He comprobado los tres mutantes contra la tabla: «9 antes que 6» da «esperando turno» con algo en vuelo y `starting`; «4 antes que 1» da «en curso» con el backend no disponible, algo en vuelo y `running_ok` falso (el caso normal, porque `/running` no se pide); y quitar la 3 da «procesando». Los tres mutan y fallan por el assert que nombran. |
| P3 | Controles que solo fallan por una excepción | **Resuelto** | Se añade el tipo (c), «corte intermedio». La paridad (c) dispara `js.get("returned") == py["returned"]`, `backend_probe()[1]` se lee por índice, y T4 usa `models_stale`. Pero el control (b) de la paridad nombra mal el assert (F5). |
| P4 | `doctor` descarta la causa del daemon en los fallos lentos | **Resuelto** | Hay un test de la desigualdad con control (c) y el paso T7.6. |
| P5 | Las verificaciones de la ola B corren sobre ficheros a medio editar | **Parcial** | Los ficheros de código de cada ola son disjuntos de verdad (lo he comprobado en la tabla de propiedad), así que fusionarlos es mecánico. Pero la carpeta del cambio está **sin seguimiento** en git, de modo que no existe en ningún worktree, y `verification.md` lo escriben dos tareas a la vez. Tampoco se dice quién arregla un rojo de interacción (F3). |
| P6 | Requisitos sin una verificación que pueda fallar | **Resuelto** | Hay un test para cada uno de los siete puntos. Quedan huecos menores (F13). |
| P7 | La prueba de extremo a extremo estaba incompleta | **Resuelto** | `doctor` contra el daemon, con su criterio de fallo, y el panel leído en bucle. Falta decir cómo se lee el panel mientras corre la delegación (F14). |

**Controles positivos comprobados** (más de tres):

1. `test_accounting_un_fallo_no_ahorra_ni_genera` y `_fallo_troceado_conserva_el_coste_real`:
   ejecutado `_accounting` de hoy. Da `saved: 1000` y `estimated: True` en los dos eventos, así
   que los dos fallan por `assert a["saved"] == 0`. **Correcto.**
2. Envoltorio de `Intl` (T5): ejecutado en node 24. Con el envoltorio, `useGrouping:'always'` da
   `8003`; sin él da `8.003`; y `'es'` a secas da `8003`. El control (a) y el mutante (b) fallan
   por `F.format(8003) == "8.003"`. **Correcto.**
3. Los tres mutantes de `estadoModelo` (T4): **correctos** (ver P2).
4. El mutante (b) de la paridad, `e.ok===false` → `!e.ok`: **muta, pero el assert que nombra está
   mal** (F5).
5. El mutante 3 de T2 («la regla 1 solo mira `int`»): el assert que nombra es correcto, pero el
   recorrido no. El `HTTPStatusError(401)` cae en la **regla 2** (`http_error`), no en la 11 (F6).
6. `test_backend_probe_sin_daemon_dice_dns`: hoy `backend_probe` devuelve
   `"no responde (ConnectError)"` (`doctor.py:279`), así que falla por el assert. **Correcto.**

### Las tres discrepancias declaradas

- **El neto en tokens lo redefine `coste-api-y-cuota`** (es lo contrario del arreglo (a) de la
  primera pasada). **Está justificada**: hay una sola función de conversión, las cifras en
  caracteres no cambian y el control se fija en caracteres y en tokens. Pero esconde dos cosas
  (F4): la otra spec dice hoy lo contrario («no la redefine»), y nada impide que una release
  publique la cifra intermedia.
- **La imagen va en bytes** (`bytes_saved_image`). **Está justificada y no esconde nada**: el log
  guarda bytes en `chars_in` para las imágenes, y `coste-api-y-cuota` las saca de su base
  (REQ-020). Solo un apunte: la unidad se deduce de `input_unit`, así que una herramienta futura con
  otra unidad que no sea `chars` acabaría en `bytes_saved_image`.
- **La histéresis entra en el alcance.** **Está justificada**, porque la decidió el usuario y está
  bien acotada para el badge. Pero esconde F2: las filas de modelos no se conservan durante el
  primer fallo.

También he comprobado las dos variantes del plan frente a los arreglos propuestos. Que T3 no tenga
zona en `test_metrics.py` es correcto, porque la fixture lo cubre y `:228` sigue pasando con la
validación nueva. Los worktrees en lugar de la serie T5 → T3 son una variante válida, salvo por F3.

### Fallos nuevos

**F1 (BLOQUEANTE, plan). REQ-018 rompe tests de `_post_chat` que T3 corre pero que no le
pertenecen.**
- Evidencia: `config.backend_origin()` da `"remote"` para `http://test-backend/v1`, porque
  `test-backend` no es de loopback (`config.py:112-122`). Ese es el `BASE_URL` de
  `tests/conftest.py:62` y de los dos ficheros afectados. Con REQ-018 ya no se pregunta «¿Lo
  arranco?» con origen remoto, así que fallan
  `tests/test_fallos_integracion.py::test_connect_timeout_ofrece_arrancar_el_backend` (`:114`) y
  `::test_connect_error_se_comporta_igual_que_siempre` (`:127`), los dos por `assert sin_preguntar,
  "no se ofreció arrancar el backend"`. Los dos ficheros están en el comando de verificación de T3
  (`plan.md:271`), pero ninguno está en su lista de ficheros ni en la tabla de propiedad.
- Además, en `tests/test_post_chat_caminos.py`, los casos «ConnectError + arranca», «dice que sí y
  arranca», etc. **siguen en verde sin ejercitar el autoarranque**: con origen remoto ya no se llega
  a esas ramas, y la suite pierde esa cobertura sin avisar. Y
  `test_la_lista_de_caminos_cubre_todas_las_ramas` exige exactamente 7 `return ChatResult(` en
  `_post_chat`: si T3 añade una salida para la rama remota, falla.
- Arreglo: dar a T3 `tests/test_fallos_integracion.py` y `tests/test_post_chat_caminos.py`. En los
  tests que comprueban la pregunta o el autoarranque, fijar el origen local con
  `monkeypatch.setattr(config, "BACKEND_ORIGIN_OVERRIDE", "local")` o una URL de loopback, y añadir
  los casos remotos a `CAMINOS`. Antes de editar, buscar `ofrec`, `arranc` y `preguntar` en
  `tests/`, para que la lista sea completa y no a ojo.

**F2 (IMPORTANTE, spec y plan). Con la histéresis, el badge se conserva en el primer fallo, pero
las filas de modelos no.**
- Evidencia: en el primer sondeo fallido, el estado visible sigue siendo «disponible» (REQ-028).
  Pero `/api/backend` ya devuelve `models_stale: true`, `status: null` y `running_ok: false`,
  porque `/running` no se pide (REQ-013). Con la tabla de REQ-022, la regla 5 da «frío» a todos los
  modelos sin nada en vuelo (status `null`, que no es `"loaded"`), y la 4 da «en curso» a los que sí
  tienen algo. Además, T4 atenúa las filas por `models_stale` (`plan.md:337`), mientras que REQ-021
  las atenúa «sin conexión». Resultado: durante un ciclo, el badge dice «conectado» y la lista
  enseña todos los modelos atenuados y en «frío». Es el parpadeo que la histéresis quería evitar,
  con dos señales que se contradicen.
- Arreglo: en REQ-028, decir que mientras el estado visible conserva «disponible» tras un fallo,
  las filas se pintan con el **último sondeo bueno** (`estadoVisible` guarda ese `bj`) y no se
  atenúan. En REQ-021 y T4, atenuar por el estado visible y no por `models_stale`. Y añadir un test
  con node: secuencia bueno → fallido, el modelo `loaded` sigue «montado» y sin atenuar. Su control
  (b): el mutante «las filas usan el último `bj`».

**F3 (IMPORTANTE, plan). Integración de los worktrees: la carpeta del cambio no viaja y
`verification.md` tiene dos dueños en la misma ola.**
- Evidencia: `.sdd/changes/panel-cuentas-y-estados-honestos/` está **sin seguimiento** en git
  (`git status`), aunque `.sdd/` sí se versiona en el repo (489 ficheros). Un worktree creado
  desde `feat/panel-honesto` no tiene ni `spec.md` ni `plan.md` ni `verification.md`. Y el plan
  manda a **cada** tarea anotar en `verification.md` «qué assert disparó». Eso son T1 y T2 a la vez
  en la ola A, y T3 y T5 en la ola B. Si cada una lo crea en su worktree, las dos fusiones chocan
  (*add/add*), en contra de que «la integración es mecánica». Si lo escriben en el árbol principal,
  son dos escritores sobre el mismo fichero. `verification.md` no está en la tabla de propiedad.
  Por último, «un rojo aquí… se resuelve antes de abrir la ola siguiente» no dice **quién** lo
  resuelve, y en modo orquestador la sesión principal no ejecuta.
- Arreglo: (a) antes de lanzar la ola A, confirmar la carpeta del cambio en `feat/panel-honesto`
  (commit firmado), o dar en cada encargo la ruta absoluta del árbol principal para leer `spec.md` y
  `plan.md`; (b) que cada tarea escriba su evidencia en `verification-T<n>.md` (un dueño cada uno) y
  que la sesión principal las una en `verification.md` al integrar; (c) nombrar quién arregla un
  rojo de interacción, por ejemplo el agente de la tarea cuyo fichero falla, relanzado sobre el
  árbol integrado.

**F4 (IMPORTANTE, interfaz entre cambios). El contrato solo está firmado por una parte, y «la
misma versión» no tiene quien la haga cumplir.**
- Evidencia: `../coste-api-y-cuota/spec.md:18-23` dice «consume la cifra neta… y **no la
  redefine**», y pide «por evento: el neto en caracteres». Esta spec dice lo contrario: el otro
  cambio sustituye `tokens_claude`, y `tokens_context_net` cambiará. El plan solo devuelve el
  daemon a la 0.32.0 (T7.7). No dice si `feat/panel-honesto` se fusiona con `main` antes de que
  esté `coste-api-y-cuota`. Si se fusiona, el siguiente PR de release (las releases van por PR, como
  `#222`) publicaría la cifra intermedia.
- Arreglo: no bloquea esta spec, que es la que define, pero sí el gate de la spec del otro cambio,
  que tiene que citar el contrato antes de aprobarse. En el plan, añadir una regla explícita: «no se
  fusiona con `main` hasta que `coste-api-y-cuota` esté listo», o «los dos cambios van en el mismo
  PR». Y una línea en `state.json` o en el handoff que lo recuerde.

**F5 (MENOR, plan). El mutante (b) de la paridad dispara otro assert del que nombra.** Con
`!e.ok`, el primer caso que diverge es `ok: null` (va antes que «sin clave `ok`» en la lista de
REQ-001), y `_ev` pone `chars_out: 400` por defecto (`tests/test_metrics.py:511`). Como `returned`
es el primer campo que se compara, falla `js.get("returned") == py["returned"]` (`0 != 100`) en el
caso `ok: null`, no `saved` en el caso sin `ok`. Arreglo: nombrar ese assert y ese caso.

**F6 (MENOR, plan).** En el mutante 3 de T2, el `HTTPStatusError(401)` cae en la regla 2
(`http_error`), no en la 11. El assert que nombra sigue disparando. Basta con corregir la
explicación.

**F7 (MENOR, plan). `OSError(10051)` y `OSError(errno.ENETUNREACH)`, construidos con un solo
argumento, dejan `errno` en `None`** (comprobado: `OSError(10051).errno is None`). Escritos como
dice la tabla de T2, darían `transporte` y no `sin_ruta`, y el error estaría en el test, no en el
clasificador. Arreglo: construirlos con dos argumentos, `OSError(errno.ENETUNREACH, "…")`, como
los crea el socket.

**F8 (MENOR, plan). `loopback` se puede derivar mal sin que ningún test lo vea.**
`config._is_loopback_host` espera el host **sin puerto**, y `config.backend_host()` devuelve
`host:puerto`: `"127.0.0.1:9292"` da `False`. Si T3 le pasa `backend_host()`, la regla 7 no se
aplica nunca, y ningún test de T3 sondea una URL de loopback con un `ConnectTimeout` doblado.
Arreglo: nombrar `config._split_host_port(config.BASE_URL)[0]` y añadir ese test.

**F9 (MENOR, spec).** REQ-010 dice qué reglas recorren la **cadena** (3 a 6), pero no dice si las
reglas 1, 2 y 7 a 12 miran solo la excepción de arriba (`isinstance`). Si una excepción envuelve un
`ConnectTimeout`, dos implementaciones pueden dar la regla 8 o la 12. Además, «la tabla cubre toda
entrada» deja fuera un `int` 2xx. Arreglo: una frase para cada cosa.

**F10 (MENOR, spec). La validación estricta del cuerpo es un cambio de comportamiento que no se
declara.** Hoy `_models_with_status` tolera entradas que no son `dict`, un `id` ausente (pinta
`"?"`) y la falta de `data` (`server.py:2985-2994`). Con REQ-012, cualquiera de esas cosas da
`available: false` y `respuesta_invalida`. Arreglo: anotarlo en los casos borde o tolerar las
entradas sueltas.

**F11 (MENOR, spec).** REQ-015 deja `CAÍDO: <detalle>` en `local_status` para `http_error`,
`respuesta_invalida` y `sin_respuesta`, que el badge (REQ-014) ya no llama «caído» porque hay
alguien contestando. Arreglo: alinear `local_status` con el criterio del badge.

**F12 (MENOR, trazabilidad).** La tabla de la spec asigna REQ-034 entero a T5 y REQ-012 solo a T3.
El plan da (h) a T4 y los endpoints de REQ-012 también a T4.

**F13 (MENOR, verificación).** Hay partes de requisitos que no tienen ningún test que pueda fallar:
el plazo de sondeo de `doctor.backend_probe` y de `/api/metrics/stats` (REQ-013), la columna
`tokens_net` de «Quién delegó» y el tooltip del KPI (REQ-004), y que el siguiente sondeo salga
«2 s después de que termine» (REQ-026). El test de `/api/inflight` con `esperando_plaza` es una
guarda que puede pasar hoy, así que no es un control.

**F14 (MENOR, T7.6).** No dice cómo se lee el panel mientras corre una delegación que bloquea la
llamada MCP. Arreglo: un bucle dentro de la página (`browser_evaluate` que guarda las lecturas en
`window`) lanzado **antes** de la delegación, y leído al terminar.

**F15 (MENOR, spec).** Los 6 s de lectura cubren un `/models` fallido (5 s), pero no un `/models`
bueno con un `/running` colgado (5 + 5 s), ni un DNS que se cuelga. En esos casos `doctor` vuelve a
sondear por su cuenta y, sin la clave, da `UNKNOWN`. Es un caso raro: basta con anotarlo como
limitación.

### Qué hace falta para aprobar

- **Spec**: F2 (una frase en REQ-028 y otra en REQ-021, con su escenario), más F9, F10 y F11 si se
  quiere cerrar todo. F4 no bloquea esta spec, pero sí la de `coste-api-y-cuota`.
- **Plan**: F1 (dueño y edición de los dos ficheros de test), F3 (carpeta del cambio,
  `verification-T<n>.md` y quién arregla los rojos), la regla de fusión de F4, el test de F2, y
  F5 a F8 en las tablas de control.

Llamadas `local_*` de esta revisión: **0**. El encargo pide comprobar cada arreglo literalmente en
la spec y el plan, con líneas y asserts concretos, y un resumen no da eso. Además, hoy cada llamada
puede descargar el modelo cargado. Leí los ficheros por franjas, el código con `grep` y `sed`, y
ejecuté los scripts de solo lectura.


## Respuesta a la segunda pasada

Corrección del 2026-10-06, con las decisiones de la sesión principal de esa ronda: sin worktrees,
restricción de release, histéresis también en las filas, origen fijado en los tests de REQ-018 y
contrato sin tocar la otra carpeta. Se añade el choque con `daemon-reparte-el-backend` (su
REQ-027), que pidió la sesión principal en la misma ronda. Los controles se ejecutaron con dos
scripts desechables:
- `scratchpad/controles/paridad.py`: la regla nueva reimplementada en Python y en JS, contra el
  `acct` real de `metrics.HTML`, con los 12 casos en el orden del plan.
- `scratchpad/controles/clasificador.py`: la tabla de REQ-010 con el `httpx2` instalado y
  `config` real.

| # | Hallazgo | Resolución | Dónde |
|---|---|---|---|
| F1 (BLOQUEANTE) | REQ-018 rompe tests de `_post_chat` sin dueño y deja el autoarranque sin cubrir | T3 se queda `tests/test_fallos_integracion.py` y `tests/test_post_chat_caminos.py`. Paso 1 de T3: inventario con `rg` antes de editar, y en cada test que mira la pregunta o el autoarranque se fija el origen con `BACKEND_ORIGIN_OVERRIDE = "local"`, sin tocar la URL de las rutas mockeadas. Hay casos remotos nuevos en `CAMINOS`, y REQ-018 va como condición, sin un `return ChatResult(` nuevo (la guarda de 7 se mantiene). Nueva guarda `test_el_autoarranque_sigue_cubierto`, con un mutante que quita el origen fijado. Además, cada tarea termina con la suite completa, que habría cazado este fallo | REQ-018; T3 pasos 1 y 8; tabla de propiedad; olas |
| F2 | Las filas no aguantan el primer fallo | `estadoVisible` devuelve el **sondeo de referencia** (el último bueno mientras se conserva «disponible»). REQ-022 lee running, `status` y `running_ok` de él, la atenuación va por estado visible y no por `models_stale`, y las filas solo pasan a «desconocido» cuando el badge deja de decir «conectado». Escenario nuevo y test con dos mutantes (filas con el último `bj` → «frío»; atenuar por `models_stale`) | REQ-021, REQ-022, REQ-028, escenario «las filas aguantan el primer fallo»; T4 |
| F3 | Worktrees: la carpeta no viaja, `verification.md` con dos dueños, nadie arregla los rojos | **Sin worktrees** (decisión de la sesión principal). Todas las tareas en serie, porque ningún par queda sin ficheros compartidos (el plan dice por qué, caso por caso). Cada ola tiene un único escritor de `verification.md`, y su integración (suite completa) es el último paso de la tarea, con el mismo agente como dueño, que arregla lo que salga aunque esté fuera de su lista | Approach, olas, propiedad |
| F4 | Contrato firmado por una sola parte; «misma versión» sin mecanismo | Nueva sección «Restricciones de entrega» en la spec: no se publica versión hasta mezclar `coste-api-y-cuota`. La mezcla en `main` sí se permite, y no hay guardián en código (decisión de la sesión principal). T6 pone la nota al principio de `[Unreleased]`. La otra carpeta no se toca: la sesión principal dice que su spec se está reescribiendo para consumir este contrato tal cual | Spec «Restricciones de entrega», REQ-040; T6 |
| F5 | El mutante (b) de la paridad dispara otro assert | Ahora se nombra el que dispara: `js.get("returned") == py["returned"]` en el caso `ok: null` (`0 != 100`). El orden de los casos y de los campos queda fijado. **Ejecutado**: el control (c) dispara `returned` en «neto positivo» (`None != 100`) contra el `acct` real de hoy, y el mutante `!e.ok` dispara `returned` en «`ok: null`». La guarda de cinco condiciones sale verdadera | T1 |
| F6 | El 401 del mutante 3 cae en la regla 2, no en la 11 | Explicación corregida. **Ejecutado**: con la regla 1 limitada a `int`, `HTTPStatusError(401)` da `http_error` | T2 |
| F7 | `OSError(10051)` con un argumento deja `errno` en `None` | Todas las excepciones del test se construyen con errno y mensaje. **Ejecutado**: con un argumento sale `transporte` y con dos, `sin_ruta`. `OSError(errno.ECONNREFUSED, "…")` se convierte en `ConnectionRefusedError` y da `rechazada`; `TimeoutError(ETIMEDOUT, "…")` da `timeout_conexion`. Hay una guarda del montaje, y la spec lo explica | REQ-010; T2 |
| F8 | `loopback` derivado con el puerto | La spec y T3 nombran `config._split_host_port(config.BASE_URL)[0]`. Test nuevo con `127.0.0.1:9292` y `ConnectTimeout` → `rechazada`, con el mutante «usar `backend_host()`». **Ejecutado**: `_is_loopback_host("127.0.0.1:9292")` da `False` y con el host sin puerto da `True` | REQ-010; T3 |
| F9 | Alcance de cada regla y el `int` 2xx | Las reglas 3 a 6 buscan en la cadena; las 1, 2 y 7 a 12, solo arriba. Un `int` 2xx lanza `ValueError`, con su test | REQ-010; T2 |
| F10 | La validación estricta del cuerpo cambia el comportamiento | Solo se exige un objeto con una lista `data`; dentro, la tolerancia de hoy. El cambio (un 2xx sin `data` pasa a `respuesta_invalida`) queda declarado y tiene su guarda de regresión | REQ-012, casos borde; T3 |
| F11 | `local_status` dice CAÍDO de quien contesta | `RESPONDE CON ERROR:` para `http_error`, `respuesta_invalida` y `sin_respuesta`, alineado con el badge. Escenario y test (a) | REQ-015; T3 |
| F12 | Trazabilidad desalineada | REQ-012 repartido (sondeo en T3, endpoints en T4) y REQ-034 (h) en T4 | Traceability |
| F13 | Partes sin test que pueda fallar | Plazo de `backend_probe` (c) y de `/api/backend/stats` (a); `tokens_net` en `by_client` (a) y en la columna del panel (b); tooltip del KPI (b); el `setTimeout` de 2 s tras terminar (a). El test de `/api/inflight` pasa a control (b), con el mutante de la lista blanca | T1, T3, T4, T5 |
| F14 | Cómo leer el panel durante una delegación que bloquea | Bucle dentro de la página instalado con `browser_evaluate` **antes** de la delegación, y leído al terminar | T7.6 |
| F15 | Los 6 s no cubren `/running` colgado ni DNS colgado | Anotado como limitación aceptada | REQ-016, casos borde |
| Choque con `daemon-reparte-el-backend` (REQ-027) | «esperando turno» culparía a llama-swap de una espera nuestra (el turno por grupo) | El campo pasa a ser genérico: `espera_local`, con el motivo como texto (hoy `"plaza"`). «En cola local» cubre **cualquier** espera dentro de local-delegate, y «esperando turno» queda solo para lo ya enviado a llama-swap. Punto de extensión escrito: el otro cambio solo escribe `espera_local` con su motivo, con el mismo ayudante de T3, sin tocar la tabla ni `estadoModelo`. Un motivo desconocido se pinta tal cual. Test con `"turno_grupo"` y un mutante que exige `"plaza"`. La carpeta del daemon no se toca | REQ-022, escenario de REQ-022; T3 paso 9; T4 |

Discrepancias: ninguna nueva. Las tres de la primera respuesta siguen igual, y la revisión las dio
por justificadas.

Abierto:
- La reescritura de la spec de `coste-api-y-cuota` para citar este contrato (la hace otra
  sesión).
- El paso 0 de T3 (si el mutante de 1 s muta en esta PC).
- El resultado de las pruebas de red real en los runners de macOS y Ubuntu.
- Que `daemon-reparte-el-backend` adopte `espera_local` (está escrito como punto de extensión;
  esa carpeta no se toca desde aquí).

## Revisión del resultado

Gate: **resultado (conformidad)**. Revisado en solo lectura sobre `feat/panel-honesto` en `4046a05`
(`git diff main...HEAD -- src tests docs CHANGELOG.md scripts`, 27 ficheros), más los dos ficheros
de esta carpeta con cambios sin commit (`research.md`, `verification.md`). Fecha: 2026-10-06.

**Veredicto propuesto: `conforms-with-notes`. Conformidad aprobable: sí.** Ningún hallazgo
bloqueante. Hay tres menores de privacidad y trazabilidad que conviene cerrar antes de mezclar
(sección «Qué hacer antes de mezclar»).

Método: cada REQ se comprobó en el código y en el test que lo vigila, no solo en `verification.md`.
Además se corrieron los ficheros de test centrales:
`bash ~/.claude/scripts/pesado.sh uv run pytest -q -p no:cacheprovider tests/test_metrics.py tests/test_panel_estados.py tests/test_causa_conexion.py tests/test_sondeo_backend.py tests/test_delegacion_conexion.py tests/test_post_chat_caminos.py tests/test_dashboard_js.py tests/test_checks.py tests/test_doctor.py`
→ **335 passed, 1 skipped** (la guarda de CI de siempre). La suite completa (1598 passed, 2 skipped)
y los controles positivos y mutantes se toman de las secciones T1–T7 de `verification.md`; se
comprobó que los tests que citan existen y miran lo que dicen.

Llamadas `local_*`: **0**. Motivo: el MCP `local-delegate` está desconectado en esta sesión
(ECONNREFUSED); los ficheros largos se leyeron por franjas.

### Tabla REQ → veredicto → evidencia

| REQ | Veredicto | Evidencia (código · test) |
| --- | --- | --- |
| REQ-001 regla única y paridad | Cumple | `server._accounting` y JS `acct` siguen la regla línea a línea (`failed` = `ok` exactamente false; `reclama` con `tokens_in` reportado > 0 para imagen; `net` sin recorte). `test_paridad_acct_entre_python_y_el_js_del_panel`: los 12 casos mínimos en orden, 18 campos comparados con `js.get(...)` y las cinco guardas (`net<0`, fallo con `tokens_in>0`, caso sin `ok`, `bytes_saved_image>0`, `chars_saved_output>0`). Control (c) y mutante `!e.ok` documentados en T1 |
| REQ-002 un fallo no ahorra | Cumple | Rama `failed` en las dos copias: tokens solo reportados, `estimated` false, desglose y `saved/returned` a 0, `backend_calls` intactos. `test_accounting_un_fallo_*`, `test_accounting_fallo_troceado_conserva_el_coste_real` |
| REQ-003 neto en `/api/stats` | Cumple | `_aggregate` expone `tokens_returned`, `tokens_context_net`, las cuatro sumas en caracteres y `tokens_net` en `by_tool`, `by_backend` y `by_client`; `tokens_context_saved` sigue siendo el bruto. `test_stats_expone_el_desglose_en_caracteres`, `test_stats_quien_delego_trae_el_neto`, `test_stats_el_log_sintetico_de_la_mac_no_infla_nada` |
| REQ-004 el panel enseña el neto | Cumple | KPI con `tokens_context_net`, pista «bruto X − devuelto Y», tooltip que dice que no descuenta relecturas; `drawToolDonut` usa `acct(e).net` con `conNegativos` (filtro `!==0`, sin `source==='path'`); el resto de `agg` sigue con `>0`; chispa sin `min:0` (`suggestedMin:0`); columna de clientes con `tokens_net`. `test_agg_con_negativos_*`, `test_la_chispa_admite_negativos`, Playwright `test_el_KPI_hero_*` y `test_quien_delego_*` |
| REQ-005 `local_status` cuenta igual | Cumple | Bloque de log con `_accounting`: `~N tokens netos (bruto ~M)`. `test_local_status_cuenta_el_neto_como_el_panel`; en vivo en T7 paso 6 |
| REQ-006 un solo predicado de fallo | Cumple | `_aggregate` usa `acc["failed"]`; en el HTML no queda `!e.ok` ni `e.ok?` (comprobado con grep). `test_stats_ok_null_no_cuenta_como_error`, `test_el_js_usa_un_solo_predicado_de_fallo` |
| REQ-007 desglose por evento | Cumple | Nombres exactos del contrato en Python (`chars_saved_text`, `bytes_saved_image`, `chars_saved_output`, `chars_returned`, `failed`, `tool`, `model`, `source`, `unit`) y en JS (`charsSavedText`, `bytesSavedImage`, `charsSavedOutput`, `charsReturned`…). Septiembre recomputado idéntico (T7 paso 3) |
| REQ-008 una sola conversión | Cumple | `tokens_claude(cantidad, *, tipo, evento)` y `tokensClaude(cantidad, tipo, e)` con la tabla de hoy; ni `_accounting` ni `acct` dividen por CPT para `saved/returned/net` (`tok` solo en `tokensIn/tokensOut`). `test_tokens_claude_es_la_unica_conversion`, `test_acct_convierte_solo_con_tokensClaude` y sus mutantes (T1) |
| REQ-010 clasificador total | Cumple | `fallos.causa_conexion`: las 12 reglas en orden; la 3 a la 6 recorren la cadena sin repetir (visitados por `id`), la 1, la 2 y de la 7 a la 12 miran solo la excepción de arriba; un 2xx lanza `ValueError`. `test_cada_suceso_tiene_su_causa` (las 12 reglas, Winsock 10051/10065, caso de la Mac en las dos variantes), `test_una_cadena_con_ciclo_termina`, `test_un_oserror_sin_errno_no_es_sin_ruta`, tres tests de red real |
| REQ-011 textos únicos | Cumple | `_ETIQUETAS` y `detalle()` reproducen la tabla; `fallos.py` no lee configuración. `test_los_textos_son_los_de_la_tabla_de_req_011`; desviaciones T2-1 (sin host en `url_invalida`, como dice la tabla) y T2-4 (datos opcionales omitidos), aceptables |
| REQ-012 sondeo con causa | Cumple | `sondear_backend()` nunca lanza (todo dentro del `try`), exige objeto con lista `data` y tolera entradas sueltas; `/api/backend` y `/api/status` añaden `causa` y `detalle` (y `etiqueta`, desviación T4-1). `test_un_cuerpo_con_otra_forma_es_respuesta_invalida`, `test_el_sondeo_nunca_lanza`, `test_un_401_es_credencial_y_no_disponible`, `test_api_backend_dice_la_causa_de_un_401` |
| REQ-013 plazo del sondeo | Cumple | `TIMEOUT_SONDA_CONEXION=3.0` y `TIMEOUT_SONDA_LECTURA=2.0` en `config.py`, sin variable de entorno; `_plazo_sonda()` en `/models`, `/running` y `/api/metrics/stats`; `doctor.backend_probe` usa las mismas constantes; `/running` solo si `available`, en `/api/backend` y en `local_status`. `test_api_backend_no_pide_running_si_models_falla`, `test_local_status_no_pide_running_si_models_falla`, `test_api_backend_stats_usa_el_plazo_de_sondeo`, `test_backend_probe_usa_el_plazo_de_sondeo` |
| REQ-014 el badge dice la causa | Cumple | `badgeBackend`: verde «conectado»; ámbar con la etiqueta para `CAUSAS_CONTESTA` (credencial, http_error, respuesta_invalida, sin_respuesta); rojo «caído · …» para el resto; `title` = detalle; pinta el estado visible. `test_el_badge_dice_la_causa` y sus dos mutantes; en vivo en T7 paso 4 |
| REQ-015 `local_status` con el criterio del badge | Cumple | `_estado_backend_en_texto`: arriba / SIN ACCESO / RESPONDE CON ERROR (http_error, respuesta_invalida, sin_respuesta) / CAÍDO. `test_local_status_no_llama_caido_a_quien_contesta`, `test_local_status_dice_sin_acceso_con_un_401` |
| REQ-016 `doctor` | Cumple | `VistaBackend(sano, detalle, causa, fuente)`; UNKNOWN solo con credencial y fuente `directo`; pista de `fallos.pista` según causa, fuente y origen; consulta al daemon con 1 s para conectar y 6 s para leer. `test_doctor_remoto_no_manda_a_arrancar_llama_swap`, `test_doctor_usa_la_causa_que_da_el_daemon`, `test_doctor_401_del_daemon_apunta_al_lanzador`, `test_doctor_con_daemon_antiguo_usa_el_texto_de_hoy`, `test_doctor_espera_al_daemon_mas_que_su_sondeo` |
| REQ-017 el error de una delegación dice la causa | Cumple | `_post_chat` devuelve «no se pudo conectar con el backend: <detalle>», `error="connect_error"` y `fallo_conexion` en `ChatResult`; `_log_event` solo escribe la clave si no es `None`; los tres registradores la pasan. `test_el_error_de_conexion_dice_la_causa_y_va_al_log` (cuatro caminos; desviación T3-1 aceptable: los `_log_event` reales son `_chat`, `_chat_chunked` y `_chat_map_reduce`) |
| REQ-018 no se ofrece arrancar un backend remoto | Cumple | `local = config.backend_origin() == "local"` condiciona el autoarranque y la pregunta, valga `AUTOSTART` lo que valga; la pista remota de `fallos.pista` nunca dice «arranca llama-swap» a secas. `test_delegacion_remota_no_pregunta_ni_arranca` (con y sin autoarranque), `test_delegacion_local_sigue_preguntando`, `test_el_autoarranque_sigue_cubierto`, `test_pista_remota_nunca_manda_a_arrancar_llama_swap_a_secas`. Ver la observación menor 4 sobre el arranque del daemon |
| REQ-019 plazo de conexión de 10 s | Cumple | `_get_client` con `httpx2.Timeout(HTTP_TIMEOUT, connect=min(TIMEOUT_CONEXION_DELEGACION, HTTP_TIMEOUT))`, constante 10.0 sin variable de entorno; lectura, escritura y pool siguen en `HTTP_TIMEOUT`. `test_el_plazo_de_conexion_de_las_delegaciones_es_de_10_s` (comprueba read, write y pool), `test_el_plazo_de_conexion_no_supera_el_total`, `test_una_delegacion_sin_ruta_se_rinde_en_10_s` (red real, menos de 13 s) |
| REQ-020 la versión solo con un 404 | Cumple | `/api/backend/stats` sin datos devuelve `causa`, `etiqueta`, `detalle` y `status_http`; `textoStats` culpa a v236 solo con `status_http===404`. `test_la_version_de_llama_swap_solo_se_culpa_con_un_404` y su mutante; en vivo en T7 |
| REQ-021 la lista de modelos no cambia | Cumple | `_LISTAS_BUENAS` por `BASE_URL`, lista guardada con `status: None` y `models_stale: true`; filas desde el sondeo de 2 s; `ordenModelos` por primer rol y luego alfabético; atenuadas por el estado visible, no por `models_stale`. `test_la_lista_guardada_es_de_su_url`, `test_orden_de_modelos_con_y_sin_conexion`, mutante «atenuar por `models_stale`» |
| REQ-022 estado de cada modelo y `espera_local` | Cumple | `estadoModelo` implementa las 11 filas en orden; la fila 9 lleva un `title` que no afirma la causa; `espera_local` se publica y se borra alrededor del semáforo y lo copia `inflight_snapshot`; un motivo desconocido se pinta tal cual. `test_estado_modelo_una_fila_por_regla` (tres mutantes de orden), `test_la_espera_local_es_un_punto_de_extension`, `test_esperando_turno_no_afirma_la_causa`, `test_inflight_marca_la_espera_local`, `test_el_snapshot_de_en_curso_lleva_la_espera_local` |
| REQ-023 la chip acepta cualquier valor | Cumple | `chipEstado`: `loaded`/`unloaded` con su clase, otro texto `neutral`, nulo sin chip. `test_chip_de_estado_acepta_cualquier_valor` y su mutante |
| REQ-024 «Última delegación» | Cumple | `renderInflight` cambia el título; sin eventos, «En curso» y «Sin delegaciones todavía». `test_ultima_delegacion_cuando_nada_corre`; en vivo en T7 paso 6 |
| REQ-025 panel Sistema | Cumple | `/api/system` añade `platform`, `origin` y `host`; `textosSistema` da la nota remota siempre y sin fila vacía, el texto de plataforma sin lista de procesos y el de macOS para la memoria. `test_api_system_dice_plataforma_origen_y_host`, `test_textos_del_panel_sistema`, Playwright `test_la_nota_de_computo_remoto_sale_en_Inter_y_sin_fila_vacia` |
| REQ-026 el sondeo no se solapa | Cumple | `pollInflight` y `pollBackend` separados, cada uno con su guarda `SONDEO.*` y un `setTimeout` de 2 s en el `finally`; sin `setInterval` para ellos. `test_pollInflight_no_se_apila`, `test_pollInflight_se_encadena_tras_terminar`, `test_un_backend_lento_no_congela_en_curso` |
| REQ-027 al reconectar se refresca todo | Cumple | `aplicarBackend` llama a `fetchStatus()` (que pide `/api/status` y `/api/backend/stats`) al pasar de no disponible a disponible. `test_al_reconectar_se_refresca_todo` y su mutante |
| REQ-028 dos sondeos antes de «caído» | Cumple | `estadoVisible` con umbral 2: un sondeo bueno da disponible al instante; un fallo tras uno bueno conserva y devuelve el bueno como referencia; el segundo fallo da caído; sin sondeo bueno previo, «comprobando…». `test_dos_fallos_antes_de_caido`, `test_las_filas_aguantan_el_primer_fallo`, `test_el_badge_avisa_del_ultimo_sondeo_sin_dejar_de_decir_conectado`; en vivo en T7 paso 4 |
| REQ-030 miles agrupados | Cumple | `fmtNum` propio; `F` dentro de `const CPT = 4, F = …, PAGE = 10;`. `test_F_agrupa_aunque_el_navegador_no_tenga_Intl_v3` con el mutante `useGrouping:'always'` |
| REQ-031 decimales con coma | Cumple | `F1` en tok/s, GiB, porcentajes y segundos. `test_decimales_con_coma_y_latencia_en_segundos` |
| REQ-032 latencia en segundos | Cumple | `fmtSeg`, con «< 0,1 s» por debajo de 50 ms, en el KPI, la actividad y «En curso». `test_decimales_con_coma_y_latencia_en_segundos`, Playwright `test_la_latencia_va_en_segundos` |
| REQ-033 plurales | Cumple | `plural()`; no queda ningún literal con paréntesis. `test_plural_sin_parentesis`, `test_no_quedan_plurales_con_parentesis_ni_toFixed` |
| REQ-034 tipografía por rol | Cumple con desviación aceptable | (a)–(h) medidos con Playwright (diez tests de T5 y el de la nota remota de T4). Desviación T5-1: el control de (g) discrimina con el botón de cierre de la ayuda, porque «Refrescar» ya heredaba la familia; el test comprueba los dos |
| REQ-040 documentación | Cumple | Wiki (`Savings-and-metrics`, `Troubleshooting`, `Remote-backend`, `Daemon`) con la regla, las causas, los 10 s, la histéresis y los estados; `[Unreleased]` con la nota visible de no publicar; mock de la captura con las claves nuevas; sin release ni captura. `test_wiki.py`, `test_captura.py` (T6) |
| Restricciones de entrega | Cumple con desviación aceptable | No hay release ni cambio de versión, y la nota del CHANGELOG está. El segundo punto (reinstalar la 0.32.0 publicada en el daemon) **no se hizo por decisión del usuario** (T7 paso 7); ver el hallazgo menor 3 |
| Contrato con `coste-api-y-cuota` | Cumple | Nombres y unidades por evento y totales tal cual la tabla (Python en snake_case, JS en camelCase, `bytes_saved_image` en bytes, `backend_calls`↔`calls`, `tokens_in`↔`tokensIn`…); firmas `tokens_claude(cantidad, *, tipo, evento)` y `tokensClaude(cantidad, tipo, e)`; un `tipo` desconocido lanza (desviación T1-5, inocua y útil) |

### Hallazgos

**BLOQUEANTES:** ninguno.

**IMPORTANTES:** ninguno.

**MENORES** (no rompen ningún REQ; el 1 y el 2 conviene cerrarlos antes de mezclar):

1. **Datos privados en ficheros versionados de esta carpeta.**
   - `verification.md:311` (sección T3, paso 0, ya en commit) cita la IP de la LAN de esta PC
     (una 192.168.x). Sustituirla por «la IP de la interfaz de salida».
   - `research.md:88` (en commit) cita la ruta del directorio de datos con el nombre de usuario de
     Windows (la carpeta de perfil bajo `Users`, con `AppData`). Sustituirla por `%LOCALAPPDATA%`
     o por `config.LOG_DIR`.
   - La IP de Tailscale de `research.md:56` ya está corregida en el árbol de trabajo, pero **sin
     commit**, y sigue en los commits de la rama. Si la rama se mezcla con merge (no squash), la IP
     llega al historial de `main`. Recomendación: commit de la corrección y mezclar con squash.
   - Fuera de esta carpeta, el diff `main...HEAD` no añade rutas personales, IPs reales ni tokens
     a `src`, `tests`, `docs`, `CHANGELOG.md` ni `scripts`: solo valores de prueba
     (`pc.tailnet.ts.net`, `100.64.0.2`, `192.0.2.1`, `no-existe.invalid`). Las rutas de perfil
     que aparecen en otras carpetas `.sdd/changes/*` (p. ej. `codex-config-local`,
     `coste-api-y-cuota/insumos`) no son de este cambio.
2. **La sección T7 y las filas nuevas de la tabla «Evidence» de `verification.md` están sin
   commit.** Las filas que añadió T7 (REQ-005, 007, 014, 015, 016, 020, 021, 022, 024, 028) solo
   existen en el árbol de trabajo. REQ-023, 025, 026, 027, 034 (h) y 040 se quedan citados por
   sección: es un hueco de **trazabilidad**, no de evidencia. Esta revisión confirma que sus tests
   existen y pasan (tabla de arriba), así que no incumple ningún REQ. Remedio: commit de
   `verification.md` y, si se quiere completar, una fila por cada uno de esos REQ con el test
   citado arriba.
3. **El daemon queda con el código de la rama y anuncia 0.32.0, igual que la publicada.** La
   restricción de entrega pedía devolverlo a la 0.32.0; el usuario decidió dejarlo con el código de
   la rama. Ningún REQ exige distinguir la versión, y la restricción que de verdad protege (no
   publicar ninguna versión con la cifra intermedia) se cumple. Es una desviación aceptada, pero
   hoy solo consta en `verification.md`. Remedio: anotar la decisión en `state.json` (o en las
   decisiones del `brief.md`) para que la siguiente sesión no la tome por un olvido, y tener
   presente que `doctor` dirá «la última publicada» aunque el código no lo sea.
4. **Observación, fuera del alcance de REQ-018:** `daemon.py:292` y `entrypoint.py:73` siguen
   llamando a `autostart.ensure_backend(wait=0)` al **arrancar**, si `LOCAL_DELEGATE_AUTOSTART`
   está activo, sin mirar el origen. REQ-018 habla de «un fallo de conexión» y esto no lo es, así
   que no lo incumple; pero con una `BASE_URL` remota y el autoarranque puesto, el daemon intentaría
   levantar un llama-swap local. Es comportamiento anterior a este cambio; candidato a backlog.
5. **Robustez de la paridad (anterior a este cambio):** el programa de node del test redefine
   `CPT` y `tok` en vez de extraerlos del HTML (hoy son idénticos: `Math.floor(c/CPT)`), y el test
   se salta si no hay `node`. Una guarda que falle en CI si falta `node` cerraría el hueco.
6. **`daemon.query_backend`** recibe un `httpx2.Timeout` aunque su anotación dice `float`
   (desviación T3-6, declarada). Inocuo en ejecución; ajustar la anotación cuando se toque
   `daemon.py`.

### Las desviaciones declaradas en `verification.md`

Todas revisadas contra la spec. **Ninguna rompe un REQ.**

- **T2** (1–7): `url_invalida` sin host es literalmente la tabla de REQ-011; textos con datos
  opcionales omitidos en vez de escribir `None`; `pista` tolerante con valores raros (nunca manda a
  arrancar aquí); casos de test añadidos. Aceptables. La 7 (el escenario de la IP propia no
  loopback no se añadió en T2) la cubrió T3 con `test_un_puerto_cerrado_remoto_no_parece_una_vpn`.
- **T1** (1–7): `agg` con `opts`, el `title` de la causa con el mismo predicado, `suggestedMin:0`
  (cumple «sin `min:0`»: el eje baja con negativos), textos «tokens netos», `ValueError` con un
  `tipo` desconocido, `returned` siempre por `tokens_claude`. Aceptables.
- **T3** (1–8): cuatro caminos en el test de la delegación (más cobertura, no menos); campos reales
  de `checks.Result`; detalle de `service.backend` sin «(backend caído)», que era falso para las
  causas en las que alguien contesta; el consejo del 401 pasa a la pista, como piden REQ-011 y
  REQ-016; lista armada dentro del `try` (necesario para «nunca lanza»); `inflight_snapshot` copia
  `espera_local` (imprescindible para REQ-022). Aceptables.
- **T5** (1–6): control de (g) con otro botón, `fmtNum`/`fmtSeg` con «–» sin dato, unidad dentro
  del valor de la latencia, plurales de más, escape del «<», mutante del tooltip. Aceptables.
- **T4** (1–10): la clave `etiqueta` de más es **la decisión correcta**: mantiene REQ-011 («solo
  `fallos.py` redacta») y la vigila `test_el_js_no_redacta_las_etiquetas_de_las_causas`; CSS mínimo
  fuera de zona; `badgeBackend(vista, baseUrl)`; «en espera local» con `null` = no espera (lo que
  dice la spec); `running_ok` estricto; un fallo del propio daemon no cuenta como sondeo (no
  contradice REQ-028, que habla de sondeos del backend); filas «Consultando el backend…» antes del
  primer `/api/backend`. Aceptables.
- **T6** (1–4): `Daemon.md` sí cambia, título de Troubleshooting con la frase nueva,
  `state:'ready'` en el mock, `tokens_net` del mock inventados como el resto de esa tarjeta.
  Aceptables.

### Los tres detalles no bloqueantes de T7

1. **Fila «cargando» con la chip LOADED.** No incumple: REQ-022 ordena que la fila diga «cargando»
   con `running: starting` **aunque `/v1/models` diga `loaded`** (escenario «cargando, turno y cola
   propia»), y REQ-023 solo pide que la chip pinte el `status` que llegue. Las dos fuentes van
   desfasadas un par de segundos y la spec lo acepta. Si molesta, es una mejora de presentación
   para otro cambio (por ejemplo, esconder la chip mientras la fila dice «cargando»).
2. **Huecos en la tabla de evidencias.** No incumple ningún REQ; es trazabilidad (hallazgo menor 2).
3. **0.32.0 sin distinguir.** No incumple ningún REQ; es la desviación aceptada de la restricción
   de entrega (hallazgo menor 3).

### Qué hacer antes de mezclar

1. Quitar la IP de la LAN de `verification.md:311` y la ruta con el usuario de `research.md:88`.
2. Commit de `research.md` (con la IP de Tailscale ya quitada) y de `verification.md` (sección T7
   y filas de evidencia), y mezclar con squash para que la IP no llegue al historial de `main`.
3. Anotar en `state.json` la decisión del usuario sobre el daemon (paso 7 de T7).

### Evidencia recomendada para el gate

- Esta sección, con la tabla REQ → veredicto → evidencia.
- La corrida de esta revisión: 335 passed, 1 skipped en los nueve ficheros de test centrales.
- `verification.md` T7: ruff limpio, suite completa 1598 passed / 2 skipped, septiembre idéntico
  (`3463739 1489047 5237 289554 873270 72342 800928 0`), panel, `doctor` y `local_status` en vivo.
- Gitleaks sin fugas sobre la rama (T7 paso 8), más los dos datos privados de arriba corregidos.
