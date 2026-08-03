# Changelog

Todos los cambios notables de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

## [0.22.1] - 2026-08-03

### Fixed
- **La captura del README publicaba el log real de quien la regeneraba.** El script promete
  interceptar `/api/*` con datos de ejemplo para no publicar actividad real, pero dos endpoints se
  habían quedado fuera de la lista: `/api/stats`, de donde salen los **cuatro KPIs grandes** de la
  cabecera, y `/api/hooks`, que pinta la tabla de sugerencias. Los dos llegaban al servidor real,
  así que la imagen enseñaba las cuentas y la telemetría de quien capturó.

  No saltó a la vista porque **dependía del entorno**: sin `LD_HOOK_TELEMETRY_LOG` definida la
  tarjeta de hooks se esconde sola, así que para quien no tuviera esa variable el escape era
  invisible. La imagen sí lo delataba, y llevaba varias releases haciéndolo: el pie decía
  «390 eventos» —los de ejemplo— y el KPI de al lado «120 delegaciones», que eran de otro sitio.

  Ahora los dos están mockeados, y el de `/api/stats` **se deriva de los mismos eventos de
  ejemplo** en vez de llevar números a mano, así que la cabecera no puede volver a contradecir al
  resto del panel. `tests/test_captura.py` gana un guardián que compara los `/api/*` que la página
  pide con los que el script intercepta: un endpoint nuevo sin mock rompe el test en vez de
  filtrarse callado.

### Changed
- **Dependencias al día.** Seis actualizaciones de Dependabot, sin cambios de código propio:
  `fastapi` 0.140.7 → 0.141.1, `uvicorn` 0.51.0 → 0.52.0, `filelock` 3.32.0 → 3.32.2 y `ruff`
  0.16.0 → 0.16.1 en el grupo de desarrollo. Las cuatro son bumps de minor o parche dentro de los
  rangos ya declarados —`filelock` sigue bajo su techo `<4`— y ninguna requirió tocar
  `pyproject.toml`.

- **`actions/upload-pages-artifact` y `actions/deploy-pages`, de la v4 a la v5** en
  `pages.yml`. Son bumps de **major**, así que se comprobó qué cambia antes de mezclarlos: el
  `action.yml` de la v5 conserva las dos cosas de las que depende el workflow —el input `path` en
  la primera y el output `page_url` en la segunda—, y el major solo mueve el runtime
  (`deploy-pages` pasa a `node24`; `upload-pages-artifact` usa `upload-artifact` v7 por dentro).
  Ninguna entrada del workflow cambia.

## [0.22.0] - 2026-08-02

### Added
- **opencode como tercer cliente de `install`, `doctor` y `update`.** Hasta ahora el instalador
  conocía dos clientes y la lista estaba repartida en cinco sitios. Quien tuviera **opencode** no
  tenía ningún camino soportado: ni entrada MCP, ni diagnóstico, ni reparación. Y no había herencia
  que salvara el caso — está **medido** que opencode no lee la configuración MCP de Claude Code
  (`~/.claude.json`) ni la de Codex (`~/.codex/config.toml`).

  Ahora `--clients opencode` (y la detección automática) le escriben la entrada MCP —`type: "local"`
  con `uvx`, o `type: "remote"` contra el daemon—, el bloque de memoria en
  `~/.config/opencode/AGENTS.md` y la skill en `~/.config/opencode/skill/delegacion-local/`.
  `doctor` gana la comprobación **nº17**, `scaffold.mcp_opencode`, y las que ya existían —memoria
  global y skill— pasan a mirar los tres clientes en vez de uno; `update` repone lo que falte. Verificado de punta a punta contra el binario real: tras instalar en un HOME
  simulado, `opencode mcp list` responde `✓ local-delegate connected`.

  Todo lo que se afirma sobre opencode está medido contra la **1.18.11** ejecutándolo, no leído de
  su documentación (traza en `.sdd/changes/opencode-tercer-cliente/`). Las cuatro decisiones que
  no se deducen del código:

  - **Dónde vive su configuración es una función, no una ruta.** `XDG_CONFIG_HOME` gana sobre
    `HOME`, así que un `home/.config/opencode` escrito a mano habría hecho que `install` escribiera
    un fichero que el cliente nunca lee y que `doctor` dijera que falta la entrada recién puesta.
    Con `--home` la variable se ignora, para que el árbol simulado siga siendo un sandbox.
  - **Se escribe con `opencode mcp add`, y el camino propio es el de socorro.** Su config es JSONC
    y admite comentarios aunque el fichero se llame `.json`: un `json.dumps` de ida y vuelta los
    borraría **sin que el fichero pareciera roto**. Su CLI los conserva. Cuando no está y el fichero
    tiene comentarios —o no parsea—, la entrada **no se escribe**, se avisa con la ruta y el resto
    de componentes sí se instala. Es la misma regla que ya protege el Codex escrito a mano.
  - **Nunca se escribe una clave que no sea `mcp`.** Una clave de primer nivel desconocida hace que
    opencode **no arranque** (`ConfigInvalidError`): el castigo por una forma mala no es una entrada
    rota, es un cliente inutilizable. Por eso ahí no hay marcadores `local-delegate:begin/end` y la
    entrada se identifica por su nombre, como en Claude Code.
  - **Cada cliente tiene su sintaxis para referenciar un secreto y la del otro no se expande.**
    En opencode es `{env:VAR}`; escribir el `${VAR}` de Claude Code dejaría la variable literal, que
    se ve como un `401` y no como una configuración mala. El secreto sigue sin escribirse nunca.

  Fuera de alcance, y por un motivo medido: **los hooks no portan**. opencode no tiene el mecanismo
  de Claude Code — extiende con plugins en TypeScript y otra superficie de eventos—, y nuestros tres
  hooks son scripts de Python que hablan el protocolo de Claude Code. Tampoco declara
  `elicitation` (solo `roots`), así que las tools que saben preguntar en vez de fallar siguen
  degradando al error de siempre en ese cliente: ya funcionaba así y la documentación ahora lo dice
  en vez de prometer lo contrario.

## [0.21.0] - 2026-08-01

> La tanda del **backlog cerrado entero**: los dos puntos vivos que quedaban, los tres «no
> auditables» resueltos o cerrados como decisión, y **cinco defectos nuevos** que destapó la
> auditoría — entre ellos un ciclo de importación real y una opción del instalador que no hacía
> nada. Cada arreglo verificado **al revés**: neutralizado el cambio, el test se pone rojo por lo
> que dice.

### Added
- **`local-delegate --version`.** Salía con código 2 y un `usage`: el parser raíz exigía subcomando
  y no exponía la bandera, así que la única forma de saber qué versión estaba instalada era
  preguntarle a `pip`/`uv`. El hueco raro estaba en un proyecto donde **dos checks del diagnóstico
  comparan la versión instalada con la publicada**. Sale de `server._get_version()`, la misma
  fuente que el handshake `initialize` y que `__version__`: tres canales públicos y un solo dato.

  Ese dato se muda a **`version.py`, un módulo hoja** que no importa nada del paquete. No es
  cosmética: lo necesitan cuatro sitios que no se conocen entre sí, vivía dentro de `server.py` —el
  módulo más pesado, que arrastra el SDK, httpx2 y filelock— y `cli` importándolo cerraba un
  **ciclo de importación**, porque `server.main()` importa `cli` en cuanto hay argumentos. Diferir
  el import lo escondía sin quitarlo. Un test lo fija **sobre el AST** y no importando el módulo:
  importarlo pasaría igual con un import perezoso dentro de una función, que es justo la forma de
  volver a esconder el ciclo.

- **`main()` sale de `server.py` a `entrypoint.py`, y el ciclo de importación desaparece de
  verdad.** Sacar la versión quitó la mitad (`cli` → `server`); la otra mitad era que `server`
  importaba `cli` para despachar los subcomandos, cerrando `cli` → `daemon` → `server` → `cli`.
  Los imports diferidos lo hacían funcionar, pero el grafo mantenía el ciclo —**seis** alertas del
  analizador— y contradecía lo que el propio docstring de `cli.py` afirmaba: que `server` no
  conoce al CLI.

  La forma correcta es la de siempre: quien despacha va **por encima** de los dos. Un punto de
  entrada puede conocer al CLI y al servidor; el servidor no tiene por qué saber que existe un
  CLI. El import de `cli` sigue siendo diferido, pero ahora por la única razón que siempre debió
  ser: coste de arranque. Un test lo fija sobre el AST **incluyendo los imports dentro de
  funciones**, que es donde estaba escondido.

- **El panel se prueba interactuado, en un navegador de verdad** (`tests/test_dashboard_ui.py`).
  Es la capa que faltaba: `test_metrics.py` prueba lo que sirve el backend, `test_dashboard_js.py`
  ejecuta con node las funciones puras, y ahora se carga la página entera y **se pulsan los
  controles** — lo único que puede ver un `onclick` que no se registró, un id renombrado a medias o
  un botón que no se deshabilita en la última página. Verificado al revés: neutralizado el
  manejador de «siguiente», dos de los tres tests se ponen rojos.

  **Una premisa del pendiente era falsa**: hablaba de «paginación y **filtros de tool/modelo**», y
  esos filtros **no existen** en el panel. Los controles reales son el selector de rango, el pager,
  el tema, el auto-refresco y recargar. Se cubre lo que hay, y el módulo dice que es lo que hay.

  Va dentro del job `lint`, que ya es exigido por el ruleset y ya monta Node: **no se añade ningún
  job**, y por tanto no se toca la protección de la rama — este repo ya pagó una vez el precio de
  un check exigido que nadie reporta. El módulo se salta solo donde no hay navegador, y lleva
  dentro una guarda que **falla si se salta con `CI=true`**: un test que se salta en todas partes
  es verde sobre cero comprobaciones.

- **El instalador se ejercita de punta a punta en los tres sistemas**
  (`scripts/check_install_e2e.py`). El backlog daba el camino de macOS por «no auditable sin un
  Mac». **No hacía falta un Mac, hacía falta un runner** — y `test (macos-latest)` llevaba tiempo
  en la matriz corriendo la suite entera. Lo que nunca se había ejecutado era el *comando*, con su
  parser, su plan y su escritura real.

  Instala dos veces contra un HOME temporal (la idempotencia es lo que más fácil se rompe en un
  instalador y una sola pasada no la vería), comprueba que `--dry-run` no escribe, cuenta los hooks
  registrados y verifica que `uninstall` deja el directorio como estaba — «reversible» está escrito
  en el docstring del módulo y hasta ahora nadie lo ejercía entero.

- **Playwright, por fin declarado** (`[dependency-groups] ui`). Lo necesitan
  `scripts/dev/capture_dashboard.py` y el flujo de la captura del README, y no estaba en ninguna
  parte: por eso `uv sync` lo desinstalaba y las capturas dejaban de funcionar sin que nada
  avisara. Va en su propio grupo y fuera de `dev` porque arrastra un navegador de ~150 MB.

### Changed
- **`clients.jsonl` tiene techo, y el techo no ciega al diagnóstico.** Crecía sin límite. Es un
  crecimiento lentísimo —medido: ~144 B por arranque de proceso MCP, una línea por identidad nueva
  y no por mensaje— pero sin nada que lo pare. Ahora rota a los 256 KB conservando una generación.

  **Se rota por tamaño y no por mes**, y esa decisión es la mitad del cambio: lo que este fichero
  responde es «¿qué clientes se han visto?», y un corte mensual haría desaparecer del diagnóstico a
  un cliente visto en enero por el simple hecho de que llegó febrero.

  Y por lo mismo, `client.observed` ahora lee **todas** las generaciones: leer solo la viva habría
  cambiado un crecimiento sin límite por un diagnóstico que miente, que es peor. Ese riesgo tiene
  su propio test, verificado al revés — reducido el lector al fichero vivo, se pone rojo.

### Fixed
- **`install --enable-read-hook` enciende el hook de verdad.** Registraba el script y ya está: el
  hook seguía exigiendo además `LD_HOOK_READ_ENABLED=1` en el entorno, que nadie ponía. Eran **dos
  puertas y la bandera abría una**, así que la opción no hacía nada — y en silencio, que es lo
  peor: quedaba escrita en `settings.json`, aparecía en el plan del instalador y no sugería jamás.

  Cómo sobrevivió: `test_read_hook_is_opt_in` probaba que el instalador registra y
  `test_read_hook_is_disabled_by_default` probaba que el script obedece la variable. Los dos en
  verde y **ninguno cruzaba las dos piezas** — probar la pieza no es probar el uso. El test nuevo
  coge el comando **tal cual quedó en `settings.json`**, lo ejecuta con el entorno limpio y mira si
  sugiere; y lleva su control negativo, porque sin él pasaría igual un hook que sugiriera siempre.

  Se arregla por argumento (`--enabled` en el registro) y no escribiendo la variable en el
  `settings.json` del usuario: la variable sería global a la sesión y `uninstall` no la retiraría.
  Así **el registro mismo es el interruptor**. La variable sigue valiendo para instalaciones a
  mano.

  Es además lo que tenía bloqueado el brazo B del piloto A/B de hooks.

- **Ctrl+Break ya no mata el proceso por la vía mala, en ninguno de los dos caminos.** Windows
  tiene **dos** eventos de consola y Python solo convierte uno en `KeyboardInterrupt`: con
  `CTRL_BREAK_EVENT`, `local-delegate serve` salía con **3** y el MCP stdio con **`0xC000013A`**
  (`STATUS_CONTROL_C_EXIT`), sin llegar a imprimir nada. Un servicio que cierra bien pero devuelve
  un código distinto de cero hace que un gestor de servicios se apunte una caída.

  El diagnóstico del `3` **no estaba en nuestro código**, y por eso el arreglo no es un `except`
  más. uvicorn captura `SIGINT`, `SIGTERM` y `SIGBREAK`, y al terminar restaura el handler original
  y **vuelve a lanzar la señal** (`Server.capture_signals`). Para `SIGINT` el original es
  `default_int_handler`, así que la re-emisión produce el `KeyboardInterrupt` que `serve` ya cazaba
  —de ahí el comentario que llevaba ahí desde hace tiempo—; para `SIGBREAK` el original era
  `SIG_DFL` y la re-emisión mataba el proceso **a mitad del apagado**. Medido con un envoltorio:
  `serve()` no llegaba a retornar y `atexit` no corría, con el gestor de sesiones del SDK ya
  cerrado.

  Así que el arreglo cambia **cuál es el handler original**: `server.preparar_ctrl_break()` pone
  `default_int_handler` en `SIGBREAK` antes de servir, y Ctrl+Break desemboca en el mismo camino
  que Ctrl+C, que ya estaba probado. Solo pisa `SIG_DFL` —un handler ajeno manda— y fuera del hilo
  principal no hace nada.

  Los tests nuevos lanzan **procesos de verdad** y le piden el código de salida al sistema
  operativo, que es el único sitio donde la diferencia entre los dos eventos existe: los que ya
  había inyectan la excepción ya construida y por eso no podían ver esto. Cada uno lleva su control
  positivo (al stdio se le habla MCP y se espera su `result`; al daemon se le pregunta por
  `/api/daemon`) para que no puedan pasar sobre un proceso que murió por otra cosa.

- **`serve` con el lock ocupado dice dónde está el daemon vivo.** El lock es **uno por usuario**
  (`LOG_DIR/daemon.lock`), no uno por puerto, pero el mensaje hablaba del puerto que se pidió: con
  el daemon en el 9393, `serve --port 9899` respondía «lock ocupado pero no responde un daemon en
  127.0.0.1:9899». Cierto y engañoso a la vez — el daemon existía y estaba en otro sitio, y el
  mensaje mandaba a buscarlo donde no estaba. `daemon.json` tenía el dato y esa rama no lo leía.

  Ahora `daemon_registrado()` mira dónde el daemon dijo estar y **le pregunta por HTTP** antes de
  anunciarlo: un `daemon.json` huérfano no puede convertirse en «tu daemon está en …», que sería
  cambiar un diagnóstico incompleto por uno falso. El docstring de `serve` decía «idempotente por
  usuario/puerto» y ahora dice la verdad: por usuario.

## [0.20.0] - 2026-07-31

> La tanda que **vació el backlog auditado**: los siete puntos que la auditoría del 2026-07-31
> dejó confirmados, más el `Ctrl+C` reportado durante la propia sesión.

### Added
- **Los PNG de la marca quedan atados al `favicon.svg` del que salen.** `icon.src.html` ya cargaba
  el SVG canónico en vez de redibujar la marca, pero **nada obligaba a regenerar los PNG cuando el
  icono cambiaba**: los tests comprobaban que existen, que la cabecera es la de un PNG y que están
  declarados en el HTML, y ninguno miraba si su contenido seguía correspondiéndose. El propio repo
  lo llamaba «riesgo aceptado».

  Se cierra **por procedencia y no rasterizando en el CI**, que era lo que el pendiente daba por
  necesario: `scripts/dev/capture_icons.py` regenera los dos PNG con un comando y escribe
  `site/icons.json` con el **sha256 del SVG** con el que se generaron, más el de cada PNG. Tres
  tests lo comprueban, y entre ellos cubren los tres descuidos posibles: tocar el icono sin
  regenerar, regenerar los PNG por fuera del script, y añadir un icono sin declararlo.

  Mismo trato que el manifiesto de la captura del README: **lo escribe quien captura, nunca se
  toca a mano**. Uno actualizado a mano cumpliría el check sin que nadie regenerara nada.

- **El JavaScript del panel se prueba ejecutándolo, no leyéndolo.** De sus 674 líneas, hasta ahora
  solo una función se ejecutaba en la suite (la paridad de `acct()` con Python); el resto se
  cubría con `node --check` y *grep* sobre el HTML, que comprueba que el fichero parsea y que
  cierto texto está ahí — no lo que hace.

  Nace `tests/test_dashboard_js.py`, que corre con node las funciones donde un fallo **cambia lo
  que ves**: `computeRange` (decide qué periodo se le pide al backend), `localDayKey` y `byDay`
  (agrupan por tu día natural, cruzando la frontera de zona horaria), `agg` (alimenta los donuts)
  y `fmtHace`.

  **Los tests fijan `TZ` a una zona con offset negativo** en vez de confiar en la del que ejecuta:
  con `TZ=UTC` un `localDayKey` escrito con `toISOString()` pasaría en verde, que es exactamente
  cómo sobreviven estos fallos. Se verificó al revés con diez mutantes —día en UTC, off-by-one en
  el preset de 7 días, el rango personalizado cortando el último día a medianoche, `agg` sin
  filtrar los ceros, `fmtHace` pasándose una frontera— y todos caen.

  Se resolvió sin meter Playwright en el CI, que era lo que el pendiente daba por necesario.

### Fixed
- **`Ctrl+C` sobre `local-delegate` ya no escupe un traceback.** Parar el proceso a mano es la
  forma normal de pararlo, no un fallo, y hasta ahora el camino stdio —`local-delegate` a secas,
  que es como lo lanzan los hosts MCP y como se prueba en una terminal— dejaba subir el
  `KeyboardInterrupt` hasta arriba. Lo que salía no era una línea: el SDK corre sobre anyio, así
  que Python imprimía un `ExceptionGroup` anidado con el rastro de las tareas del grupo.

  El defecto no fue no saber qué hacer: **`daemon.serve` capturaba esa interrupción desde hacía
  tiempo**, con su comentario explicando por qué. Eran dos caminos hasta el mismo `Ctrl+C` y solo
  uno estaba preparado. Medido antes de tocar nada: por stdio el `KeyboardInterrupt` salía sin
  capturar y con traceback; por `serve`, cierre limpio y código 0.

  Ahora los dos salen por 0 y en silencio —quien pulsó `Ctrl+C` ya sabe que paró el proceso—, y un
  test los comprueba **juntos en la misma corrida**, que es lo que impide volver a arreglar uno y
  dar el problema por cerrado.
- **El `cancelled` del CI en `main` tenía la causa mal diagnosticada, y ahora tiene firma
  reconocible.** `ci.yml`, `ci_gate.py` y `Repo-hardening.md` sostenían que `timeout-minutes` «no
  dispara» sobre el job colgado de Windows, deducido de verlo más de 10 minutos vivo con el límite
  en 8. **Es falso**: lo que se estaba viendo era el periodo de gracia.

  La medición que lo tumba son los tres runs `cancelled` de `main` del 2026-07-31: los tres
  murieron a los **13:00 exactos** desde el inicio del job, y con **estados internos distintos** —
  dos con `Tests (pytest)` todavía `in_progress` y uno con todos los pasos en `success`,
  `Complete job` incluido. Trece minutos clavados con tres estados distintos solo lo explica un
  temporizador, y **13 = 8 del límite + 5 de gracia**. De ahí que la conclusión sea `cancelled` y
  no `timed_out`.

  Consecuencia práctica, que antes no se podía dar: un `cancelled` en `main` de ~13 minutos **no es
  una avería del repo**, y ahora está escrito dónde se busca.

  Además, la medición enseñó que en dos de los tres casos quien seguía corriendo era **pytest** y
  no el runner, así que el paso `Tests (pytest)` pasa a tener su propio `timeout-minutes: 5`: corta
  ese cuelgue pronto y **con log**, en vez de arrastrar trece minutos que acaban sin log
  (`BlobNotFound`). Dos tests atan los números al texto que los explica — un comentario no falla
  nunca por su cuenta, y este ya estuvo equivocado una vez.

### Added
- **El dashboard ya lee la telemetría de los hooks.** El dato se escribía desde hacía tiempo —1817
  eventos en tres días en la máquina de referencia— y `metrics.py` no mencionaba `telemetry` ni
  `hook` ni una vez. Nace `GET /api/hooks` y una tarjeta en el panel, con el mismo rango temporal
  que el resto de la página.

  **Lo que mide, y lo que deliberadamente no mide:** cuenta las veces que un hook **sugirió**
  delegar. No cuenta cuántas sugerencias se siguieron, porque nada une una sugerencia con una
  delegación posterior —son dos registros sin identificador común— y cruzarlos sería inventar una
  correlación. La propia tarjeta lo dice, y hay un test que falla si ese aviso desaparece.

  Dos decisiones más que salen de lo mismo: la tarjeta **se esconde** cuando no hay telemetría en
  vez de enseñar ceros (un panel a cero se leería como «los hooks no sugieren nada», leyendo un
  fichero que no existe), y el endpoint distingue `enabled: false` de «activada y sin eventos».

  El desglose por categoría resultó más informativo que el total: con 17,0 % global, `bash`
  acumulaba 1396 eventos y **cero** sugerencias mientras `lint` iba 283 de 283.

- **La wiki nativa se sincroniza sola desde `docs/wiki/`.** Era el último fleco manual del release:
  `scripts/release.py` no mencionaba la wiki y ningún workflow la tocaba (`pages.yml` publica
  `site/`, no `docs/`). El resultado, medido: los **once** ficheros divergidos —`Repo-hardening.md`
  291 líneas, `Daemon.md` 154, `Integration-install.md` 142— y la wiki congelada desde el 28 de
  julio, con tres releases publicadas encima.

  El nuevo `wiki.yml` se dispara en cada push a `main` que cambie `docs/wiki/**`, **no en el tag**:
  la wiki documenta lo que está en `main`, y atarla al release la dejaría mintiendo entre versión y
  versión — una forma más lenta del mismo problema.

  De paso se arregla algo que la copia manual venía publicando roto: **18 enlaces en 6 páginas**.
  Los que salen del directorio (`../recipes/…`, `../../README.md`) son un 404 en la wiki, donde los
  `.md` se sirven planos y en otro repositorio, y no se ven rotos en el fuente porque navegando el
  repo funcionan. `scripts/sync_wiki.py` los reescribe a URLs absolutas al publicar, y deja
  relativos los enlaces entre páginas hermanas — convertirlos también sacaría al lector de la wiki
  en cada clic.

  De propina, un test que caza en Windows algo que `ruff` solo ve en Linux: **un script con
  shebang tiene que estar marcado ejecutable en git** (`EXE001`). El bit de ejecución no existe en
  Windows, así que el lint local pasa en verde y el CI falla — la peor forma de enterarse, y pasó
  con este mismo script. El test lee el modo que git registra, que sí es el mismo dato en los tres
  sistemas.
- **El puerto del daemon puede exigir un token, y con él se cierra de una vez el endpoint MCP, el
  dashboard y `/api/*`.** Define `LOCAL_DELEGATE_WEB_TOKEN` en el entorno del daemon y todo el
  puerto lo pide; sin la variable no cambia absolutamente nada, porque exigirlo siempre rompería
  toda instalación existente el día que se actualiza.

  El agujero que cierra, medido y no supuesto: el daemon escucha en `127.0.0.1`, pero **cualquier
  proxy delante lo publica sin tocar `LOCAL_DELEGATE_WEB_HOST`** —un túnel, un nginx, un reenvío de
  puerto de una VPN— y conecta contra loopback igual que el usuario, así que ni esa variable ni la
  IP de origen delatan nada. Y quien alcance ese puerto **puede delegar con la credencial del
  backend que el daemon ya tiene cargada**.

  **La protección anti-DNS-rebinding del SDK no cubría esto**, y merece decirse porque invitaba a
  darlo por resuelto: rechaza con `421` un `Host` que no sea loopback, pero se salta mandando
  `Host: 127.0.0.1:9393` a mano. Es defensa contra un navegador engañado —que no puede fijar esa
  cabecera— y nunca pretendió ser control de acceso.

  El token se acepta como `Bearer` (clientes MCP, CLI) y como `Basic` (el navegador, que no manda
  una cabecera Bearer por escribir una URL; el usuario da igual y el token va de contraseña). Una
  sola puerta envuelve la app raíz **después** de montar el dashboard, así que una ruta nueva queda
  protegida por existir y no por acordarse de protegerla.

  El secreto no se escribe en ningún fichero de configuración: `install --mcp-mode http
  --web-token-env` deja a Claude Code con `${LOCAL_DELEGATE_WEB_TOKEN}` en `headers` —verificado
  contra la 2.1.220, que lo expande— y a Codex con `bearer_token_env_var`, que es su mecanismo para
  esto y además el único posible, porque su validador rechaza un token literal en ese transporte.

### Fixed
- **`doctor` deja de acusar al propio daemon de ser «otro proceso» cuando lo que falta es el
  token.** Con el puerto protegido y sin credencial en el entorno, el check de servicio decía
  «alguien escucha en 127.0.0.1:9393 pero no es nuestro daemon»: cierto hasta que existió una
  segunda causa para el mismo silencio, y falso desde entonces. Los dos diagnósticos llevan a
  acciones opuestas —matar un proceso ajeno, o exportar una variable—, así que ahora se separan.

  La distinción se apoya en el `realm` del `401`, no en el código de estado a secas: cualquier cosa
  escuchando en ese puerto puede responder `401`, y atribuírselo al daemon sería cambiar un
  diagnóstico falso por otro. Y la pregunta se hace **sin** cabecera de autorización, que es la
  única forma de ver lo que encuentra quien no lleva el token — mirar por el camino que sí tiene
  credencial es exactamente lo que ya tapó una avería durante un día entero en este repo.
- **El paquete deja de declarar su versión a mano.** `local_delegate.__version__` estaba clavado
  en `"0.10.0"` y llevaba **nueve releases mintiendo**: `scripts/bump_version.py` sube la versión
  en los cuatro sitios que conoce —`pyproject.toml`, las dos de `server.json` y `uv.lock`— y ese
  atributo no estaba en la lista, así que nadie lo tocaba nunca. Ahora se deriva de la metadata
  del paquete instalado, por la **misma** llamada que el servidor MCP usa para declararse en el
  handshake `initialize`, de modo que los dos canales públicos no pueden discrepar.

  No engañaba a nadie dentro del repo (nadie lo leía), pero es el dato que consulta quien importa
  el paquete. Se descartó añadirlo a `bump_version.py`: eso convertiría cuatro declaraciones
  coordinadas en cinco, o sea un sitio más donde mentir. Un test nuevo lo ata a `pyproject.toml`
  y distingue en su mensaje «alguien clavó un literal» de «el entorno está desincronizado», para
  no mandar a mirar el fichero equivocado.

## [0.19.0] - 2026-07-31

### Added
- **`doctor` mira si el cliente podrá autenticarse contra el backend, y no solo si el backend está
  vivo.** Nace `service.credential`, la comprobación **nº16**. Sale de una avería real que **ningún
  check veía**: en una máquina con el backend exigiendo API key, las entradas MCP registradas en
  modo `stdio` y el secreto viviendo solo en el lanzador del daemon (DPAPI en Windows), **todas las
  tools `local_*` llevaban un día devolviendo `401`** — última llamada con éxito el 2026-07-30 a
  las 09:36— mientras `doctor` daba **todo `[ OK ]`**, backend incluido.

  No es una regresión del arreglo anterior: el proceso `stdio` que lanza el cliente hereda el
  entorno del cliente, no el del lanzador del daemon, así que son dos caminos distintos y solo uno
  tiene credencial. Preguntar por el camino del daemon estaba bien para *diagnosticar el backend* y
  era el camino equivocado para *saber si el cliente puede usarlo*.

  De ahí el diseño: el check pregunta al backend **sin cabecera de autorización**, que es la única
  forma de ver lo que se encontrará quien no lleva la key. Si el backend está abierto, el modo de la
  entrada da igual y sale `ok`; si exige credencial y alguna entrada habla por `stdio` sin tenerla,
  sale `warn` nombrando al cliente y ofreciendo `install --mcp-mode http`, que es el arreglo que
  funciona sin escribir el secreto en ningún fichero. Vive en el grupo `servicio` y no en
  `andamiaje` porque sale a la red, y ese grupo no lo hace por contrato — es lo que permite a
  `install` reportar sin tocar nada externo.

### Changed
- **`--dry-run` enseña el comando literal que va a escribir, no solo cuántos escribe.** Lo pedía el
  incidente de los hooks en Windows del 2026-07-30: el plan decía «registra 2 hook(s)» y el defecto
  vivía en el **string generado** —un comando de shell sin comillas—, así que revisar el plan antes
  de aplicarlo no habría avisado de nada. Ahora, debajo de cada acción que escribe algo *generado*
  (los comandos de los hooks y la entrada MCP de Claude Code y de Codex), el plan imprime el texto
  exacto. Solo en `--dry-run`: al aplicar de verdad, la salida ya la escribe la acción con lo que
  pasó.

## [0.18.1] - 2026-07-31

### Fixed
- **`doctor` ya no se lleva un 401 del backend: le pregunta al daemon, que sí tiene credencial.**
  La clave del backend se lee **del entorno del proceso**, y ahí está la asimetría: el daemon la
  recibe de su lanzador —en Windows, descifrada con DPAPI—, pero un `local-delegate doctor` escrito
  en una consola cualquiera no la tiene. Así que el diagnóstico probaba el backend por su cuenta,
  cobraba un `401` y se quedaba en `[ -- ] está arriba pero rechaza la credencial`… en una máquina
  donde el daemon estaba viendo el backend y sus cinco modelos sin ningún problema.

  El dato existía, autenticado, en el **mismo servicio** que el check de al lado ya consultaba.
  Ahora `service.backend` mira primero `/api/backend` del daemon y solo prueba por su cuenta si no
  hay daemon al que preguntar — que es cuando ese camino sigue siendo el correcto.

  Dos matices deliberados: cuando el daemon dice que el backend **no** está disponible, eso es un
  diagnóstico y no una duda (cuenta como aviso, no como `[ -- ]`), porque él **sí** tiene con qué
  autenticarse; y una respuesta del daemon **sin el campo `available`** se trata como «no se pudo
  preguntar», porque leer su ausencia como una caída sería inventarse un fallo.

  **No se toca la clave en ningún sitio nuevo**: sigue sin salir del proceso que la tiene.

- **`doctor` decía «el daemon sirve la vieja» aunque fuera al revés, y ofrecía un arreglo que no
  arreglaba.** El check comparaba las dos versiones con `!=`, que dice que difieren pero no **cuál**
  está atrasada, y asumía siempre que la vieja era la del daemon. Con una instalación editable —el
  daemon corriendo del repo, por delante del CLI publicado— el mensaje afirmaba lo contrario de lo
  que pasaba y mandaba **reiniciar el daemon**, que ahí no cambia nada.

  Ahora se comparan como números, con la misma función que ya usaba el check de versión publicada, y
  cada sentido dice lo suyo: si el atrasado es el daemon, reiniciar; si es la instalación, el comando
  de actualización que corresponda a **esa** instalación. Y si las dos versiones no se pueden ordenar
  se avisa de la diferencia **sin** ofrecer arreglo, porque cualquiera de los dos podría ser el
  equivocado.

  Encontrado en uso real justo después de publicar la 0.18.0.

## [0.18.0] - 2026-07-31

### Added
- **`doctor` ya enseña con qué clientes MCP se ha hablado de verdad**, que era el dato que el daemon
  aprendió a registrar y que hasta ahora solo se veía por `/api/status`. Es la comprobación **nº15**
  del registro: nombre del cliente, versión, revisión de protocolo negociada y si declara
  `elicitation` — o sea, si las tools pueden preguntarle en vez de fallar seco.

  **Lee `clients.jsonl` y no `/api/status`, y no es un detalle de implementación:** ese endpoint
  expone la memoria del proceso del daemon, y Claude Code y Codex hablan por *stdio*, cada uno con
  su propio proceso. El daemon del 9393 **no los ve**. El fichero es la única fuente que los ve a
  todos, y además no exige que el daemon esté arriba.

  **Es informativo a propósito: nunca `[WARN]` ni `[FALT]`, así que jamás sube el exit code.** Un
  cliente que no declara `elicitation` no está mal configurado —es otro producto, con menos
  capacidades—, no hay ningún comando de local-delegate que lo cambie, y avisar sin poder decir qué
  hacer es ruido. Cuando todavía no ha hablado nadie, sale `[ -- ]`, que es lo que verá cualquier
  máquina hasta que esta versión se publique.

  El registro es histórico y acumula **una línea por cada arranque de proceso**, así que el check
  agrupa por cliente y enseña la observación más reciente de cada uno; si no, el mismo cliente
  saldría repetido tantas veces como se haya lanzado.

- **Una tool que se topa con un problema cuyo arreglo ya conoce ahora lo pregunta, en vez de fallar
  seco.** Tres casos, los tres con la misma forma: el servidor sabía la solución y solo enunciaba el
  error. (1) **Backend caído**: pregunta si arrancarlo, y lo arranca si dices que sí — no cambia el
  «backend opt-in», sigue sin arrancar nada sin permiso, solo que ahora ese permiso se puede dar en
  caliente. (2) **Modelo fuera del catálogo**: ofrece los válidos, que ya iban en el texto del error.
  (3) **`output_format` en blanco** en `local_delegate`: pregunta el formato en vez de dejar que el
  modelo improvise.

  Se apoya en `elicitation` del protocolo MCP, adoptada **después de medir que hace falta**: Claude
  Code y Codex la declaran los dos, cosa que hasta ahora nadie sabía porque el daemon no miraba las
  capabilities de nadie.

  **El plazo no es una precaución, es el requisito que sostiene todo.** Está medido que un cliente
  que declara la capability y no contesta **cuelga la tool para siempre**: el SDK no impone ningún
  timeout. Y la forma intuitiva de ponerlo —`move_on_after` alrededor de la llamada— **ni siquiera
  se puede escribir** desde el hilo en que corren las tools: lanza `NoEventLoopError`. Agotado el
  plazo, la tool sigue como si no hubiera preguntado.

  Preguntar nunca empeora nada: sin la capability, sin canal de vuelta, sin respuesta, con una
  negativa o con un fallo inesperado, el comportamiento es **exactamente** el de antes. Se apaga con
  `LOCAL_DELEGATE_ASK=0` y el plazo se ajusta con `LOCAL_DELEGATE_ASK_TIMEOUT` (30 s por defecto).
  **Lo que sí cambia de verdad:** con respuesta, una llamada con el modelo mal escrito —que hoy
  falla al instante y sin gastar backend— pasa a ejecutar inferencia con el modelo elegido. Sin
  respuesta, sigue fallando igual de rápido y sin tocar el backend.

  Ninguna tool cambia su schema: el contexto de la petición viaja por `ContextVar` desde un
  middleware, no por las firmas.

- **El daemon ya sabe con qué cliente habla: registra qué capabilities declara cada uno y qué
  revisión de protocolo negoció de verdad.** Hasta ahora no había ni una ocurrencia de
  `capabilities` en el paquete, así que preguntas como «¿puede este cliente responder a una
  pregunta de una tool?» no tenían respuesta más que suponiendo. Un `ServerMiddleware` observa cada
  conexión y deja el dato en dos sitios: una línea por cliente en `clients.jsonl` (junto al log de
  uso) y el estado en vivo en `GET /api/status`, bajo la clave `clients`.

  Tres cosas se midieron contra el SDK antes de escribir el código, y las tres cambiaron el diseño.
  **En `initialize` no hay nada que leer**: el middleware corre antes del commit del handshake y ve
  `None` en capabilities y en identidad, así que registrar «en `initialize`» —que era el plan
  original— no habría registrado nada; el primer mensaje útil es `notifications/initialized`. **La
  revisión negociada no la predicen las constantes del SDK**: con `LATEST_PROTOCOL_VERSION` en
  `2026-07-28` y el defecto en `2025-03-26`, lo negociado fue `2025-11-25`, que no es ninguna de las
  dos — motivo suficiente para medirla en vez de deducirla. Y desde la revisión `2026-07-28` **las
  capabilities pueden llegar sin identidad** (el `client_info` es opcional), así que las dos cosas
  se leen por separado y el nombre puede faltar.

  Es un `ServerMiddleware`, **no** el `Extension`/`intercept_tool_call` que este repo descartó: aquel
  se descartó porque la telemetría de coste vive en los caminos al backend y el borde MCP no ve los
  tokens reales; el dato de identidad, al revés, **solo** existe en el borde. Observar nunca altera
  la petición: un fallo del registro no llega al cliente.

- **`ci-gate`: un job que da el veredicto del run mirando los *steps*, para que el «job fantasma» no
  bloquee un merge.** GitHub dejaba `test (windows-latest)` en `in_progress` **para siempre** con
  sus ocho pasos en `success` —incluido el `Complete job` que pone el propio runner— y
  `completed_at: null`; como el ruleset exige los checks por nombre, el merge quedaba bloqueado
  hasta cancelar y relanzar a mano. Pasó **tres veces en dos días** (PRs #77, #86 y #88) y es un
  [problema conocido de GitHub sin solución oficial](https://github.com/orgs/community/discussions/161434).
  Como los pasos **sí** terminan, `scripts/ci_gate.py` consulta la API y aprueba un job cuyo runner
  llegó al final aunque GitHub no lo haya cerrado — y **suspende** si algún paso falló.

  Tres decisiones que lo sostienen: el criterio es **el nombre del último paso** (`Complete job`) y
  no contarlos, porque la numeración salta; los **pasos malos se miran antes** que el fantasma,
  porque cuando un paso falla el `Complete job` sale en `success` igualmente y al revés sería un
  falso verde; y el plazo de espera cubre **cola + ejecución**, que no es lo que mide
  `timeout-minutes`. El patrón habitual —`needs` + `always()`— **no sirve**: `needs` espera a que el
  job termine, que es justo lo que no pasa.

  El gate **solo lee** (`actions: read`): automatizar `cancel` + `rerun` habría pedido
  `actions: write`, y se descartó por eso. **Lo que cambia para quien contribuye:**
  `test (windows-latest)` deja de exigirse por nombre —lo cubre el gate— y, en cambio,
  **`install-smoke` pasa a bloquear un merge**, cosa que antes no hacía; eso último depende de PyPI
  en vivo, así que un índice degradado bloqueará PRs sin que nada esté roto.

### Fixed
- **Dos líneas de la landing competían con la retícula del fondo.** El papel de la página es una
  retícula de 1px de `--hair` cada **64px**, y tanto el borde superior del pie como el separador de
  cada fila de la tabla de tools eran **exactamente eso mismo** —1px sólido de `--hair`— cayendo
  donde la retícula no pasa: se leían como líneas del papel mal alineadas. El pie **pierde el borde**
  y deja que la retícula lo cruce entera; el separador de la tabla pasa a **punteado**, que es el
  recurso que ya usaba `.line .dots` del recibo para un contenido de dos columnas idéntico. La
  textura distinta es lo que desambigua: dice «esto es una tabla», no «esto es el papel».
  Comprobado en el navegador en los dos temas.

- **El botón de idioma activo de la landing dejaba de usar el amarillo de la vía local.** En esa
  paleta el amarillo tiene un solo significado y está escrito en el propio CSS —«la vía que se
  toma»—, y elegir idioma no es tomar una ruta: la misma mezcla que se corrigió en el titular, en
  una superficie que entonces no se contó. Ahora el estado activo se marca **invirtiendo**
  (`--ink` de fondo, `--paper` de texto), que además sube el contraste a **13,90:1** en claro y
  **15,17:1** en oscuro —medido en el navegador— frente a 9,34 y 11,92. De paso desaparece un
  `color` declarado dos veces en la misma regla, que **no era residuo**: `--ink` es casi blanco en
  tema oscuro, así que hacía falta un literal para que el texto no se perdiera sobre el amarillo;
  al invertir, los dos tokens se intercambian juntos y el literal sobra. Se revisaron los **18**
  usos del token antes de tocar uno: los otros 17 se quedan, con el porqué escrito.

### Changed
- **`ci.yml` declara `timeout-minutes` en sus cuatro jobs y `concurrency`.** Sin lo primero regían
  las **6 horas** del default de GitHub para un job que se atasque **ejecutando** (un test que no
  termina, una descarga colgada); ahora son 8 minutos el de los tests —unas 5,5 veces el peor caso
  real de 1 m 23 s— con el valor justificado en el propio fichero. Lo segundo hace que empujar un
  arreglo cancele el run anterior de esa rama; en `main` no, porque ahí el run es el registro de
  que ese estado pasó el CI.

  **Lo que esto NO arregla, dicho para que nadie se confíe:** el «job fantasma» que bloqueó tres
  merges en dos días, con `test (windows-latest)` en `in_progress` y **todos sus pasos terminados
  en `success`** —incluido `Complete job`— mientras GitHub Status decía «All Systems Operational».
  Ahí el cuelgue es **posterior a nuestro código**: el runner acaba en ~86 s y lo que falta es que
  GitHub cierre el job, así que `timeout-minutes` —que lo aplica el runner sobre algo que siga
  ejecutándose— no tiene nada que matar. Medido: más de 10 minutos `in_progress` con el límite en
  8. Se descartó por ejecución la causa clásica en Windows, un proceso huérfano reteniendo
  handles: la suite no deja procesos vivos. Es un
  [problema conocido de GitHub sin solución oficial](https://github.com/orgs/community/discussions/161434);
  el remedio hoy es `gh run cancel` + `gh run rerun`. El síntoma, cómo diagnosticarlo (mirar los
  *steps*, no el reloj) y la vía que queda por explorar quedan en `docs/wiki/Repo-hardening.md`.

### Added
- **La captura del README ya no puede quedarse vieja en silencio.** Junto a la imagen vive ahora
  `docs/assets/dashboard.json`, que declara con qué versión se generó y el hash del PNG, y un test
  falla si esa versión no es la de `pyproject.toml` o si la imagen cambió sin su manifiesto. Hasta
  ahora regenerarla se pedía **solo con palabras** en la wiki y no lo verificaba nadie: de **25
  releases, solo 5** la regeneraron en su commit de tag, y la **0.16.0 se publicó con el badge del
  header diciendo `v0.15.0`**. Dos detalles que hacen que el vigilante no se pueda engañar: el
  manifiesto lo escribe **el script que captura**, no el que sube la versión —si lo actualizara el
  bump, el check se cumpliría sin que nadie regenerara nada—, y la versión que registra es la que
  **sirvió el dashboard capturado** (`/api/status`), así que capturar contra el daemon instalado en
  vez de contra el repo deja constancia en lugar de colar un badge viejo. De paso, la wiki corrige
  el comando que documentaba para arrancar el dashboard, que **no funciona** con el daemon
  ocupando el 9393.
- **`local-delegate install --agents`: mantiene tus subagentes de Claude Code al día con el
  catálogo de tools.** Añade al frontmatter `tools:` las que falten y actualiza un bloque de
  catálogo entre marcadores. Es **opt-in** —sin el flag no se toca ningún agente— y solo actúa
  sobre los que **ya declaran** tools `mcp__local-delegate__*`: los ajenos ni se abren. Cada
  fichero modificado deja su `.bak`, y si no se reconoce dónde va el bloque, no se inserta.
  Sustituye a `docs/recipes/update_agents.py`, que no llegaba a ninguna máquina instalada.
  **El catálogo ya no se escribe a mano: se deriva de la tabla de la skill**, y un test nuevo
  falla si esa tabla y las tools que registra el servidor difieren en un solo nombre — que es lo
  que le pasó a la receta, cuyo texto anunciaba «10 tools» habiendo once.
- **`doctor` detecta los scripts de hooks que dejaron las instalaciones anteriores, e `install`
  los retira.** Las versiones viejas los ponían sueltos en `~/.claude/hooks/`; la actual usa
  `~/.claude/hooks/local-delegate/` y nunca limpiaba los otros, así que se quedaban para siempre.
  El borrado es **quirúrgico**: solo los nombres exactos de los scripts que este paquete instala,
  solo ficheros y solo en la raíz — `telemetry.jsonl`, `__pycache__`, los hooks de terceros y toda
  la instalación buena quedan intactos. Nota sobre lo que **no** hacía falta arreglar: no había
  entradas duplicadas en `settings.json`, porque `merge_hook_settings` ya desregistra las
  versiones anteriores por el nombre del script.
- **`update` avisa de que no actualiza el CLI instalado como `uv tool`, y dice cómo hacerlo.**
  Actualiza el pin, el andamiaje y el daemon, pero el ejecutable de `uv tool` se quedaba donde
  estaba sin que nadie lo dijera. Ahora, cuando hay una versión más nueva publicada, lo detecta
  —por el `uv-receipt.toml` del entorno, sin ejecutar `uv` ni depender de rutas de cada sistema— y
  da el comando exacto. **No lo ejecuta él a propósito:** probado en Windows, reinstalar el
  entorno desde el que corre el proceso falla al borrar `Scripts/` **y deja la instalación rota**,
  porque ya ha borrado el paquete. Como efecto colateral, la pista del `doctor` deja de sugerir
  `uv tool upgrade` a instalaciones que no lo son (`pip`, `pipx`): ahora distingue los tres modos.
- **`update` dice de dónde sacó la versión, y detecta el desfase de justo después de publicar.**
  La línea ahora nombra la fuente (el índice simple de PyPI, que se sirve con caché) y, cuando la
  versión **instalada** es más nueva que la que anuncia PyPI —la firma exacta de una release que
  aún no se ha propagado—, lo dice y recuerda `--version X.Y.Z` con la versión ya sustituida. El
  aviso es informativo: no cambia el plan de acciones ni el exit code. De paso deja de afirmar
  «última versión publicada» cuando la versión la escribió el usuario en `--version`.
- **`doctor` avisa cuando la instalación se quedó atrás de PyPI.** Comprobación nueva del
  registro (grupo *Entorno*): compara la versión instalada con la última publicada y la marca
  `[WARN]` si es más vieja, con el comando que la actualiza —`uv tool upgrade` o, si la
  instalación es editable, el `git pull` + `uv sync` del repo del que se sirve el código—. Hasta
  ahora ese caso pasaba el diagnóstico en silencio: con el CLI en 0.16.0 y la 0.17.0 publicada,
  `doctor` decía «todo a punto». Consulta con un timeout de dos segundos y degrada a `[ -- ]` sin
  red, así que un diagnóstico sin conexión sigue funcionando entero. **Solo la hace `doctor`**:
  ni el reporte de `install` ni el diagnóstico interno de `update` salen a internet por ella.
- **`install` y `uninstall` aceptan `--clients auto|claude|codex`** (repetible). Con `auto`
  —el nuevo valor por defecto— se configuran **solo los clientes que están instalados**,
  mirando si existen `~/.claude` y `~/.codex` con la misma definición que usan `doctor` y
  `update`. Nombrar un cliente sigue siendo una orden: se configura exista o no.
- **`install` termina diciendo el estado real del andamiaje**, con los mismos checks y el mismo
  formato que `doctor`, en vez de un «Listo» que solo contaba acciones aplicadas. El reporte es
  informativo y **no** altera el exit code, porque tras un install correcto quedan avisos
  legítimos (el CLI fuera del PATH si se instaló con `uvx`, un cliente ausente). No mira el
  daemon ni el backend a propósito: instalar unos hooks no es motivo para salir a la red.
- **`install` pregunta antes de reemplazar una entrada MCP de Codex escrita a mano.** Si
  `~/.codex/config.toml` tiene una sección `[mcp_servers.local-delegate]` sin marcadores, la
  escribió el usuario; ahora se pide confirmación en vez de pisarla. Sin terminal —CI, salida
  redirigida— se conserva y se sigue con el resto del plan; `--force-mcp-codex` la reemplaza sin
  preguntar. `uninstall` sí la retira sin preguntar: ahí es justo lo que se pidió.

### Changed
- **Los hooks de ruff en `pre-commit` pasan a ser locales** (solo desarrollo). Ejecutan el ruff
  del entorno del proyecto —el que fija `uv.lock` y el que corre el CI— en vez de descargar el
  suyo. Había **dos** versiones que se separaban en silencio: el hook estaba en 0.6.9 con el
  proyecto en 0.16.0, y formatean distinto un `assert x == y, "mensaje largo"`, así que el hook
  reformateaba, el `ruff format --check` del CI lo deshacía y el commit se abortaba. Subir el
  `rev` habría arreglado ese día y roto el siguiente, que es justo como se llegó a 0.6.9. De paso,
  `gitleaks` sube de `v8.18.4` a `v8.30.1`.
- **Cambio de comportamiento: el default deja de escribir en clientes que no existen.** Antes,
  sin flags, `install` equivalía a `--target all` y creaba `~/.codex/AGENTS.md` y
  `~/.codex/config.toml` en máquinas sin Codex. `--target` se conserva con su semántica exacta
  —incluido `all`, que sigue forzando los dos— y es la vía para el comportamiento anterior; lo
  que no se admite es combinarlo con `--clients`, que termina en error de uso sin escribir nada.

### Fixed
- **El header del dashboard enseñaba el icono anterior a la marca única.** Ahí había un SVG
  dibujado a mano, así que al unificar la marca se actualizó el favicon —el que sirve
  `/favicon.svg` y usa la landing— y el header se quedó con el viejo: el panel enseñaba una marca
  y su propia pestaña otra. Ahora se **inyecta** el mismo fichero (`resources/brand/favicon.svg`)
  y no pueden volver a separarse; hay un test que lo comprueba. La captura del README se regeneró
  en consecuencia.
- **`install --home` y `uninstall --home` ya no escriben fuera del HOME simulado.** El camino
  preferido para registrar el MCP es `claude mcp add-json --scope user`, que escribe **siempre**
  en el `~/.claude.json` del usuario real e ignora `--home`: instalando duplicaba configuración y
  desinstalando la borraba de verdad. `update` ya lo había corregido; `install` arrastraba el
  defecto, y la suite no podía verlo porque todas sus pruebas desactivaban ese camino.

### Removed
- **`docs/recipes/update_agents.py`.** Su trabajo lo hace ahora `local-delegate install --agents`,
  que sí viaja en el paquete y llega a la máquina donde están los subagentes.
- **`scripts/update_to_latest.sh`** (solo desarrollo). Había quedado reducido a un envoltorio de
  tres líneas que delegaba en `local-delegate update`, y mantener una segunda puerta de entrada al
  mismo comando obliga a acordarse de ella. La vía es `local-delegate update`, que además es la
  única que llega a la máquina que hay que actualizar: `scripts/` no viaja en el paquete.

## [0.17.0] - 2026-07-30

### Added
- **`local-delegate update`: un subcomando que revisa, completa, actualiza y deja el daemon
  arriba.** Sustituye a `scripts/update_to_latest.sh`, que solo cambiaba un número de versión y
  que además **nunca llegaba a la máquina que debía actualizar**: el wheel no empaqueta
  `scripts/`. Ahora el diagnóstico es el mismo que ve `doctor` —consume `checks.run_all`, sin una
  segunda definición de «estar a punto»— y lo que aporta el módulo nuevo es decidir qué se repara
  y controlar el ciclo de vida del daemon. Reinicia por el mecanismo registrado en cada sistema
  (tarea programada, LaunchAgent o `systemd --user`) y **verifica que el pid cambió**; si no hay
  ninguno registrado, cae a terminar y relanzar. Acepta `--dry-run`, `--home`, `--version`,
  `--restart-backend` y `--no-restart`.
- **El backend de inferencia no se toca al reiniciar el daemon.** Son dos procesos distintos y
  reiniciar llama-swap descargaría los modelos de la VRAM; hay que pedirlo con
  `--restart-backend`, que además no intenta nada si el backend es remoto y exige que el proceso
  del puerto se llame `llama-swap` antes de mandarle una señal.
- **`install` en modo `http` termina dejando el daemon arriba**, que es coherente con lo que
  acaba de escribir: la entrada MCP apunta a un servicio que tiene que existir.
- **`docs/wiki/Daemon.md` gana las recetas completas de macOS (LaunchAgent) y Linux
  (`systemd --user`)**, con los nombres canónicos que busca `update`. Un test falla si el módulo
  y la wiki se separan.
- **Una sola marca para la landing y el dashboard.** Hasta ahora eran dos iconos distintos —la
  landing con un glifo amarillo, el dashboard con un chip esmeralda—, y encima el amarillo es el
  color que el propio CSS de la landing declara como «de señal, rutas, no marca». Ahora hay un
  icono nuevo (un corchete de terminal abrazando el chevrón de delegación: «lo que entra aquí se
  queda aquí») y vive en **un solo fichero**, `resources/brand/favicon.svg`, que el dashboard
  sirve y la landing copia. Un test compara las dos copias byte a byte.
- **La landing declara Open Graph y Twitter Cards completas.** Antes tenía tres etiquetas `og:*`
  y ninguna de Twitter, así que el enlace compartido salía sin imagen. Ahora van `og:url`,
  `og:site_name`, `og:locale` (+ el inglés como alternativo), la imagen con sus medidas y texto
  alternativo, `canonical`, `theme-color` y `twitter:card=summary_large_image` — sin esa última,
  la imagen se recorta a un cuadrado diminuto.
- **Imagen social propia** (`site/og-image.png`, 1200×630) con el diagrama de conmutación que ya
  es la tesis de la página: la troncal baja entera y la rama a la nube se queda a medias. El PNG
  es un binario que no se puede revisar en un diff, así que **se versiona el HTML que lo genera**
  (`site/og-image.src.html`, con el procedimiento de regeneración dentro) y un test lee la
  cabecera del PNG para comprobar que mide de verdad lo que declaran los metadatos.
- **`build_site.py` ya no publica los ficheros fuente** (`*.src.html`): son la fuente revisable de
  un artefacto, no páginas del sitio. Mismo criterio por el que se publica `site/` y no `docs/`.

- **La landing del proyecto vive en `site/` y se publica sola en GitHub Pages.** Un workflow
  (`pages.yml`) la despliega en cada push a `main` que la toque. Se publica un directorio propio y
  no `docs/`, que guarda la wiki, las recipes y `plans/`: servir esa carpeta entera pondría todo eso
  en una URL pública sin que nadie lo haya decidido.
- **El número de versión de la página no se escribe a mano.** La landing trae un marcador
  `__LD_VERSION__` y `scripts/build_site.py` lo sustituye por lo que declare `pyproject.toml` al
  desplegar. Ya había cuatro copias de ese número en el repo; esta habría sido la quinta, y en el
  prototipo llegó a mentir con la primera release. Un test falla si alguien escribe una versión
  literal en la página.

- **La landing pasa el examen de un checker de OpenGraph, menos en lo que ese checker se
  equivoca.** Siete avisos, seis reales. Ahora sirve `apple-touch-icon.png` (180×180) y
  `favicon-32x32.png` —rasterizaciones del MISMO `favicon.svg` canónico, con su fuente
  revisable en `site/icon.src.html`—, porque iOS no usa el SVG para la pantalla de inicio y
  sin PNG hace una captura de la página. Declara además `twitter:site` y `twitter:creator`,
  un `site.webmanifest` honesto (`display: browser`: esto no es una PWA y el manifest no
  finge que lo sea) y datos estructurados JSON-LD de tipo `SoftwareApplication` —no la
  `WebPage` genérica que sugería el informe—, que es el vocabulario con el que un buscador
  puede hacer algo con un programa gratuito y MIT. La `og:description` baja de 213 a 149
  caracteres reutilizando la de Twitter: por encima de 160 las plataformas truncan, y dos
  textos que dicen lo mismo acaban separándose. **El séptimo aviso se descartó**: decía que
  el `canonical` apunta a otra URL, pero se analizó la dirección sin barra final y GitHub
  Pages responde 301 justo hacia la que el `canonical` ya declara. Ninguna ruta nueva es
  absoluta —los snippets del informe lo eran, y en un Pages *de proyecto* apuntan fuera del
  repo—, y hay un test que lo vigila.

### Fixed
- **`update --home <simulado>` ya no escribe en la configuración real del usuario.** El registro
  del MCP en Claude Code se hace con `claude mcp add-json --scope user`, que escribe siempre en el
  `~/.claude.json` de verdad ignorando el HOME que se le pase. Se descubrió al comprobar la
  idempotencia: la segunda pasada volvía a planificar la misma acción —el probe seguía viendo
  vacío el árbol simulado— mientras la configuración real sí se había reescrito.
- **El registro de comprobaciones decía que tenía once elementos y tiene doce.** `cli.path` entró
  en el PR #61 y el texto quedó desfasado en cuatro sitios; se llegó a planificar sobre ese dato
  falso. Ahora hay un test que compara las cuatro afirmaciones contra `len(CHECKS)`.
- **El titular de la landing ya no resalta «la nube» con el amarillo de la vía local.** En esa
  paleta el amarillo significa una sola cosa —la vía que se toma, tu máquina— y el titular dice
  justo lo contrario de la nube: pintarla de amarillo, y encima subrayarla con un trazo de 6px, la
  señalaba como el camino bueno. Ahora el resalte cae solo sobre «la nube» y va en el gris de la
  vía cara, la misma decisión que ya estaba tomada en la tarjeta social. Un test ata las dos cosas.

### Security
- **El paquete publicado deja de traer un instalador que descargaba código de la red y lo
  ejecutaba.** `scripts/install_claude_code_hooks_macos.sh` bajaba cuatro `.py` de
  `raw.githubusercontent.com` con `curl`, los registraba en `~/.claude/settings.json` y los
  ejecutaba acto seguido, sin verificar hash ni firma. No estaba roto: estaba **congelado en el tag
  `v0.10.0`** y seguía sirviendo hooks de seis versiones atrás. Nadie lo referenciaba, y su función
  ya la cumple `local-delegate install` desde `resources/hooks/`, sin tocar la red. Se borra sin
  sustituto.
- **`scripts/` sale del sdist.** El wheel nunca lo llevó, pero el sdist publicaba el repositorio
  entero —124 entradas— y es lo que analizan los auditores de cadena de suministro. El taller
  (release, bump de versión, canarios, handshake de instalación) no lo ejecuta quien instala el
  paquete. Los dos tests que cargan un script del taller se saltan cuando `scripts/` no está, y la
  condición mira el **directorio** y no el fichero: si el directorio está pero el script no, eso es
  un borrado accidental y la suite tiene que fallar, no callarse.

## [0.16.0] - 2026-07-30

### Fixed
- **`local-delegate --help` arrancaba el servidor MCP y se colgaba.** El despacho del binario
  comparaba el primer argumento contra una lista literal de siete subcomandos, y todo lo que no
  estuviera en ella caía al servidor MCP stdio a esperar por stdin: `--help` no imprimía nada,
  `-h` tampoco, y un subcomando mal escrito (`doctro`) se quedaba clavado en vez de decir «invalid
  choice». Ahora la frontera es una sola: **con argumentos es un CLI, sin argumentos es un servidor
  MCP stdio**, y de los argumentos responde el parser, que es quien sabe qué subcomandos existen.
  La invocación sin argumentos —la que usan Claude Code y Codex— no cambia.
- **La lista de subcomandos estaba escrita tres veces**: la que decidía el despacho, una copia
  muerta que no leía nadie, y las llamadas reales al parser. Queda solo la última, así que añadir
  un subcomando ya no exige darlo de alta en ningún otro sitio.

### Changed
- Escribir `local-delegate` a secas en una terminal avisa **por stderr** de que está arrancando el
  servidor MCP stdio y señala `local-delegate --help`. Solo cuando stdin es una TTY; con una
  tubería —o sea, bajo un host MCP— no se imprime nada. El servidor arranca igual en ambos casos.
- La descripción de `--help` ya no dice que el CLI sea solo para los groups de llama-swap.

## [0.15.0] - 2026-07-30

### Added
- **El `doctor` comprueba que `local-delegate` exista como comando.** Toda la documentación manda
  correr `local-delegate <algo>`, pero la instalación recomendada (`uvx local-delegate-mcp
  install`) **no deja ese comando en ninguna parte**: `uvx` monta un entorno efímero y lo borra al
  terminar. El andamiaje quedaba perfecto y el primer comando de la doc respondía «command not
  found». Ahora sale `[FALT]` con el arreglo (`uv tool install local-delegate-mcp`), y el propio
  `install` lo avisa al terminar en vez de dejar que lo descubras.
- **El `doctor` avisa si el daemon sirve una versión distinta de la instalada.** Un daemon es un
  proceso largo: tras actualizar sigue corriendo el código con el que arrancó, y los clientes
  hablan con la versión vieja sin que nada lo diga — el síntoma es «actualicé y el arreglo no
  está». Ahora es `[WARN]` con la comparación explícita.

## [0.14.0] - 2026-07-30

### Fixed
- **El instalador dejaba los hooks rotos en Windows, y con `UserPromptSubmit` eso bloquea todos los
  prompts del usuario.** El comando se registraba como `python C:\Users\...\hook.py` sin comillas;
  Claude Code lo entrega a un shell, que interpreta cada `\` como escape y lo borra, así que al
  intérprete le llegaba `C:UsersYohan.claudehooks...` y el hook moría con «can't open file». Ahora
  la ruta va **siempre entre comillas y con barras `/`** —Python las acepta en Windows—, que
  funciona en sh, cmd y PowerShell. Si te pasó: borra las entradas de local-delegate de
  `~/.claude/settings.json` y reinstala con esta versión.
- **`doctor` daba por CAÍDO un backend vivo que respondía 401.** Ahora distingue «no responde» de
  «responde 401/403 — está arriba y falta la credencial en este entorno», que se reporta `[ -- ]`
  en vez de mandarte a arrancar un servicio que ya está corriendo.

### Added
- **`doctor` ve por fin el sistema entero, no solo el backend.** Nace un registro único de
  comprobaciones (`checks.py`) con las **once** piezas del andamiaje —clientes, hooks copiados,
  hooks registrados, skill, memoria, entradas MCP de Claude y Codex, daemon, `/models` y las dos
  versiones del backend—, cada una con un `probe` **sin efectos**. Hasta ahora cada subcomando
  sabía un pedazo: `doctor` solo miraba el backend, `install` escribía sin verificar y nadie
  miraba el daemon. Cuatro estados (`[ OK ]`, `[WARN]`, `[FALT]`, `[ -- ]`) y, cuando algo falta,
  la línea de abajo dice qué comando lo arregla. Nuevo flag `--home DIR` para diagnosticar contra
  un HOME simulado.
- **Lo que no se pudo comprobar sale `[ -- ]`, nunca «falta».** Un cliente que no está instalado o
  un archivo sin permisos no son una ausencia: reportarlos como falta llevaría a que un arreglo
  automático sobrescribiera configuración ajena. `[ -- ]` no cuenta para el exit code, que
  conserva su semántica de siempre (0 sin avisos, 1 con al menos uno).
- **El dashboard mide ahora el coste, no solo el ahorro.** Nuevo KPI **Coste local** con los tokens
  de entrada que consumió de verdad el backend sumando **todas** las llamadas, y el KPI de
  delegaciones muestra al lado las **llamadas reales al backend**. Hasta ahora N llamadas se
  registraban como un evento y el panel no distinguía una delegación resuelta en una llamada de una
  que quemó la GPU dieciséis veces: el dato (`chunks`, `tokens_in`) ya estaba en el log y nadie lo
  leía. `/api/stats` expone `backend_calls`, `tokens_local_input` y `estimated_events`.

### Changed
- **Las cuentas usan el token real que reporta el backend**, no la estimación `chars ÷ 4`, que ahora
  es solo el respaldo para cuando el backend no da `usage`. El panel indica cuántos eventos del rango
  hubo que estimar. Medido sobre un log real, la estimación se desviaba entre **+8 %** y **+613 %**
  según la tool.
- **Los KPIs se sirven de `/api/stats` en vez de recalcularse en el navegador**: una sola
  implementación de la contabilidad. De paso cierra una incoherencia latente — el panel los sumaba
  sobre la lista de eventos **topada a 5000** mientras mostraba al lado el total real, así que en
  rangos grandes **subestimaba**.
- El **ahorro de contexto no cambia de definición** para texto: sigue siendo el contenido leído
  server-side contado **una vez** aunque se trocee. El trabajo extra de trocear lo paga la GPU, no
  el contexto de Claude, y por eso vive en el KPI de coste.

### Fixed
- **`local_describe_image` inflaba el ahorro ×46.** Su `chars_in` son **bytes de la imagen**, y el
  dashboard los dividía entre 4 como si fueran caracteres de texto: un solo PNG aportaba más ahorro
  fantasma que todo el resto del log junto. El evento declara ahora `input_unit: "bytes"` y esos
  casos se contabilizan con el token real. **El KPI «Contexto conservado» bajará** al aplicarse la
  corrección: es el arreglo de un defecto, no una regresión.

## [0.13.1] - 2026-07-29

### Changed
- **El panel «En curso» del dashboard ya no se queda en blanco cuando no hay nada corriendo:**
  enseña la **última delegación terminada** con cuánto hace, su tool, su modelo, su duración y el
  tamaño de la entrada, y el contador sube en vivo. Antes solo mostraba lo que se estaba
  ejecutando **en ese instante**, y como una tarea mecánica dura 2-4 segundos, el panel estaba
  vacío casi siempre: se delegaba, terminaba, y quien miraba el dashboard un momento después no
  veía **nada** — parecía que no había pasado. Se comprobó grabando el DOM durante una delegación
  real de 3,4 s. (El refresco al volver a la pestaña ya existía; el problema no era ese.)

### Fixed
- **`local_extract` con `path` devolvía siempre un error en vez de los datos.** La línea de ahorro
  («leído server-side: N chars…») se anexaba al texto del resultado, y como esta tool **parsea** su
  salida, ese sufijo convertía un JSON perfecto en uno imparseable: la respuesta acababa siendo
  `{"_local_delegate": {"error": "respuesta no parseable como JSON", …}}`. Afectaba justo al modo
  que ahorra contexto —el que vale la pena usar— y no al de `text`, que es por donde pasaban
  **todos** los tests de esa tool; de ahí que nadie lo viera. El dato de ahorro no se pierde: pasa a
  `_local_delegate.leido_server_side`, que es donde va lo que no son datos. Se apareció usando el
  propio MCP para revisar esta documentación.

### Changed
- **Revisión completa del README y la wiki.** Lo que estaba mal: el README recomendaba fijar
  `local-delegate-mcp==0.11.0` para el rollout remoto, y ese consejo hoy **rompe la instalación**
  —las versiones anteriores a la 0.12.2 piden `mcp` sin techo y mueren con el SDK 2.x—; había dos
  párrafos seguidos explicando lo mismo del map-reduce; la tabla de versiones probadas seguía en
  0.11.0; los ejemplos de configuración remota fijaban esa misma versión; y dos links internos
  estaban rotos. Lo que faltaba: Python 3.11+ en los requisitos, el subcomando `benchmark` —que no
  estaba documentado en ninguna parte—, y en *Troubleshooting* los tres fallos que este proyecto sí
  ha tenido (`Connection closed` por un major de dependencia y dónde está el traceback de verdad,
  el `421` del SDK 2.x fuera de loopback, y el dashboard enseñando gráficos viejos por la caché de
  24 h). *Publishing* recoge ahora `bump_version.py`, el CI completo con `install-smoke` y
  `vendor-audit`, y el paso de regenerar la captura del README.

## [0.13.0] - 2026-07-29

### Changed
- **Migración al SDK `mcp` 2.x.** El import pasa de `mcp.server.fastmcp.FastMCP` a
  `mcp.server.mcpserver.MCPServer`, y el daemon fija la ruta del MCP con
  `streamable_http_app(streamable_http_path=…)` porque el major sacó los campos de transporte de
  `Settings`. Las 11 tools conservan nombre, firma y salida: **la equivalencia es el criterio de
  éxito**, así que esta entrega no añade ninguna capacidad de las que 2.x trae. El techo se sube a
  `mcp>=2,<3` en vez de quitarse: la lección de la 0.12.1 fue que un rango sin techo es una bomba
  de tiempo, no que ese techo concreto sobrara.
- **Una sola librería HTTP: `httpx` sale y entra `httpx2`.** El SDK 2.x usa `httpx2`, y mantener el
  cliente propio en `httpx` habría dejado las dos instaladas para siempre. `httpx2` es de pydantic
  y marca 100 en las cinco dimensiones de Socket. Como efecto colateral, `respx` sale de las
  dependencias de desarrollo —declara `httpx>=0.25.0` y no soporta `httpx2`—: su sitio lo ocupa
  `tests/backend_mock.py`, construido sobre `httpx2.MockTransport`. Los 233 tests siguen ahí.

- **`local_extract` devuelve un objeto validado, no una cadena con JSON dentro.** Quien llamaba
  tenía que hacer un `json.loads` del resultado —y antes limpiar el aviso de truncamiento, que iba
  como texto **delante** del JSON y lo hacía imparseable—. Ahora las claves son exactamente las
  pedidas, y los dos casos que no son datos viajan bajo la clave reservada `_local_delegate`:
  `{"truncado": true, "aviso": …}` cuando hubo que recortar la entrada, y `{"error": …, "crudo": …}`
  cuando el modelo no devolvió JSON o el backend falló. **Cambio de contrato**: quien parseara la
  salida a mano debe quitar ese paso. Los clientes que no leen salida estructurada siguen recibiendo
  el JSON como texto, así que para ellos no cambia nada.
- **Las 11 tools se declaran como de solo lectura y de dominio cerrado** (`annotations`), y el
  servidor se presenta con `title`, `description` y `website_url`. Las anotaciones son las mismas
  para todas porque todas son de la misma naturaleza: ninguna toca los datos de quien llama —el log
  de uso es contabilidad interna del servidor— y ninguna sale a un mundo abierto, solo al endpoint
  configurado y a los archivos bajo las raíces permitidas.

### Fixed
- **El handshake ya dice qué versión de `local-delegate` corre.** `serverInfo.version` reportaba la
  versión **del SDK**, de modo que un `initialize` no servía para saber qué versión del paquete
  había enfrente. Ahora el server la declara con el `version=` que acepta `MCPServer`.

## [0.12.4] - 2026-07-29

### Changed
- **Chart.js sube de 4.4.1 a 4.5.1**, dos minors de atraso que el vigilante nuevo sacó a la luz en
  su primera corrida. Es el estreno del proceso, y funcionó de punta a punta: el aviso lo dio el CI,
  la copia se bajó del **tarball oficial de npm** —no de un CDN— y se verificó byte a byte, OSV no
  conoce vulnerabilidades para 4.5.1, y el dashboard se comprobó a ojo antes y después (mismos seis
  gráficos, cero errores de consola). Se actualiza también `chart.js-LICENSE.md`: sigue siendo MIT,
  cambia el rango de años del copyright.
  De paso caen **dos sitios que todavía clavaban la versión a mano** —un assert de
  `tests/test_metrics.py` y los tests de versión del vigilante—, que ahora la leen del manifiesto.
  Era exactamente el problema que `vendor.json` vino a resolver, y solo se ve cuando actualizas.

### Added
- **El JavaScript vendorizado deja de estar sin vigilancia.** `resources/vendor/` son 205 KB de
  Chart.js que ninguna herramienta miraba: Dependabot solo ve manifiestos, CodeQL analiza el
  Python y Socket cubre dependencias declaradas. No había ni un hash registrado, así que un cambio
  en ese fichero no dejaba rastro y un CVE publicado mañana no avisaba a nadie. Ahora hay un
  manifiesto (`resources/vendor/vendor.json`, que viaja en el wheel y es la **fuente de verdad de
  la versión**), un `scripts/check_vendor.py` de **solo stdlib** y un workflow propio
  `vendor-audit.yml` que corre en cada PR y en un cron semanal —los CVE se publican cuando les
  toca, no cuando hay PRs—. **Rompen el CI** un hash que no cuadra y una vulnerabilidad confirmada
  por OSV.dev; **solo avisan** que exista una versión más nueva y que OSV o npm no respondan: un CI
  que se pone rojo porque alguien publicó algo, o porque un servicio ajeno está caído, se acaba
  ignorando. El manifiesto documenta además la trampa que hace perder una tarde a quien verifique
  a mano: jsDelivr antepone a veces un banner propio de 274 bytes, así que comparar el hash contra
  su URL puede dar distinto sin que nada esté adulterado. Nada de esto entra en el runtime del
  paquete. El vigilante se estrenó con 4.4.1 —una versión de estado conocido— y su primer encargo
  fue subirla, que es el cambio de arriba.

### Fixed
- **`scripts/bump_version.py` se caía en la consola de Windows.** Imprime un `→` para marcar qué
  archivos cambia, y en una consola cp1252 —lo normal en Windows— eso es un `UnicodeEncodeError`
  que aborta el bump. Se descubrió preparando esta misma versión. Falla imprimiendo y no
  escribiendo, así que nunca dejó un bump a medias, pero un release que se cae con un traceback de
  codificación invita a hacer el bump a mano, que es justo lo que ese script existe para evitar.
- **`.gitattributes` impide que git normalice los finales de línea del contenido vendorizado.** Con
  `core.autocrlf=true` —el valor por defecto de Git for Windows— el checkout convertía los LF del
  blob de Chart.js en CRLF: 205 139 bytes en vez de 205 125. Un wheel construido en esa máquina
  llevaría un JavaScript distinto del que se publica desde Linux, y la comprobación de integridad
  nueva fallaría en cualquier clon de Windows sin que nadie hubiera tocado nada.

## [0.12.3] - 2026-07-29

### Changed
- **`platformdirs` y `filelock` quedan acotadas por debajo del major siguiente** (`<5` y `<4`). Para
  quien instala, el efecto es solo futuro: cuando salga `platformdirs` 5 o `filelock` 4, una
  instalación nueva se quedará en la serie que el proyecto probó en vez de saltar a ciegas. Ninguna
  instalación existente cambia de resolución, porque los techos van por encima de lo que ya se usa.
  Es la misma lección de la 0.12.1, generalizada: el wheel publicado es inmutable y resuelve libre
  **para siempre**, así que `install-smoke` —que corre cuando corre el CI— no puede cubrir un major
  que salga después del release; el techo, que viaja dentro del wheel, sí.
  `fastapi`, `uvicorn` y `httpx` **no** llevan techo, y el porqué de cada una está junto a su línea
  en `pyproject.toml`. El criterio completo, con su alcance y su coste, está en
  `docs/wiki/Repo-hardening.md`.

### Added
- **`scripts/release.py`: un comando para todo el release.** Construye, crea la GitHub Release con
  las notas sacadas de la sección del `CHANGELOG.md`, le adjunta wheel y sdist, y crea el tag que
  dispara `publish.yml`. Antes el tag se hacía a mano y dejaba fuera dos pasos que había que
  recordar cada vez —adjuntar los artefactos y crear la Release, que el workflow **no** crea—; en
  la 0.12.2 se olvidaron los dos. Aborta antes de tocar nada remoto si la versión no está en los
  tres archivos, si `main` no está sincronizada con el remoto, o si el tag o la release ya existen:
  **PyPI es inmutable** y publicar mal no se deshace. Tiene `--dry-run`.

## [0.12.2] - 2026-07-28

### Fixed
- **El paquete dejó de arrancar con el SDK `mcp` 2.0.0.** El SDK publicó un major que elimina
  `mcp.server.fastmcp` (el módulo pasó a `mcp.server.mcpserver`), y `local-delegate-mcp` declaraba
  `mcp>=1.2` **sin techo**: `uvx` resolvía al major nuevo y el proceso moría en el import antes de
  poder hablar MCP. El cliente solo enseña `MCP error -32000: Connection closed`, que es el
  síntoma del proceso muerto, no la causa — **el traceback real está en el `Server stderr`** del
  log del cliente (en macOS, `~/Library/Caches/claude-cli-nodejs/<proyecto>/mcp-logs-local-delegate/`).
  Afectaba a **toda instalación nueva** de la 0.12.1 en cualquier sistema. La dependencia queda
  acotada a `mcp>=1.2,<2`; migrar a la API 2.x es un cambio aparte. Quien aplicara el workaround
  `--with "mcp<2"` puede retirarlo, pero no está obligado.

### Added
- **Job `install-smoke` en el CI: el paquete construido se instala con resolución libre y se le
  exige un handshake MCP real.** Es el único job que **no** usa `uv.lock`, y esa es su razón de
  ser: el lock fija versiones buenas conocidas y por eso el CI estuvo verde mientras el paquete
  publicado estaba roto para todo el mundo. Instala con `--refresh` y `--resolution highest`
  porque un entorno limpio no implica caché limpia, y un check que no puede fallar no vigila nada.
  Cubre también al resto de dependencias: si cualquiera publica un major que rompa el import, este
  job lo detecta antes que un usuario.
- `scripts/check_install_handshake.py`, que hace esa comprobación y devuelve códigos de salida
  distintos para un fallo de import (regresión de dependencia) y uno de red o de arranque.
- **`setup_repo_security.sh` sirve para cualquier repositorio.** Los checks requeridos dejan de
  estar hardcodeados: `--checks "a|b|c"` (separador `|`, porque los nombres de job llevan comas y
  paréntesis) o `--check` repetible, y `--no-code-scanning` para repos sin CodeQL, donde exigir
  esa regla bloquearía los PR. Antes de aplicar **comprueba que alguien reporta cada check** y
  aborta si no: exigir uno que nadie publica deja todos los PR esperando para siempre. La
  comprobación mira la rama por defecto y el PR más reciente, y consulta *check-runs* **y**
  *commit statuses* — Actions publica lo primero, integraciones como Vercel lo segundo, y
  mirando solo check-runs `Vercel` parecía no existir.

### Changed
- `scripts/setup_repo_security.sh` protege **`~DEFAULT_BRANCH`** en vez de la rama literal —la
  regla sigue a la rama por defecto y no se queda protegiendo un nombre viejo si se renombra— y
  añade la regla **`code_scanning`**: que el job de CodeQL termine en verde no basta, puede acabar
  bien habiendo encontrado una alerta. Las dos mejoras vienen de comparar con el ruleset que ya
  tenía `angular-template-project`, al alinear los tres repos.

## [0.12.1] - 2026-07-27

### Fixed
- **Los estados vacíos del dashboard usaban otra tipografía.** `.empty` no declaraba
  `font-family`, así que heredaba la sans del `body` mientras todo su entorno —nombres de
  modelo, badges, chips, tabla, pie— va en monoespaciada. Se veía sobre todo en «sin datos
  (requiere llama-swap ≥ v236)», y el mismo panel llegaba a enseñar **dos** estados vacíos con
  tipografías distintas, porque el de tools usa `.tchip`, que sí la declara. Afectaba a los
  ocho estados vacíos del panel.

### Added
- **`scripts/update_to_latest.sh`**: pone este cliente en la última versión publicada. Pensado
  para la máquina que usa `uvx` con la versión fijada —la Mac que apunta al backend de la PC—,
  donde cada release obligaba a editar el pin a mano en `~/.claude.json` y `~/.codex/config.toml`.
  Consulta PyPI, cambia **solo** el número de versión (con copia `.bak`), precarga la caché de
  `uvx` y comprueba que arranca. Idempotente, con `--dry-run`, y no toca la API key ni ninguna
  otra entrada MCP. Si no hay pin, lo dice y no toca nada: `uvx` ya resuelve la última.

## [0.12.0] - 2026-07-27

### Added
- **`local_summarize` y `local_lint_summary` ya no truncan la entrada: hacen map-reduce.** Un
  documento que no cabe en el modelo se resume por partes y luego se resumen los resúmenes,
  jerárquicamente si hace falta (tope de 3 niveles). Antes se cortaba en
  `max_chars_for(modelo)` con un aviso, o sea que se resumía el principio y el resto se
  descartaba — en un log de CI eso significa perderse justo los errores del final, que suelen
  ser los que importan. El chunking de la 0.11.0 resolvía el caso de *transformar* (traducir,
  reescribir), donde concatenar las salidas es correcto; *reducir* pide otro diseño. Como allí:
  N llamadas, **un** evento de log con `chunks: N` y el progreso visible en «En curso».
  Verificado con un documento de 145.584 caracteres, procesado entero en 16 pasadas.

### Changed
- La documentación del backend remoto fija ya **0.11.0** en vez de 0.10.0: el rollout controlado
  de la Mac pasa a la versión vigente.
- **El CI corre los tests en Linux, Windows y macOS.** El paquete es multiplataforma de verdad
  —rutas, locks entre procesos y llamadas a Win32 por ctypes— y hasta ahora solo se probaba en
  Ubuntu: la fuga de handles que arregló la 0.11.0 era **exclusiva de Windows** y ningún job
  podía verla. El lint, el formato y la validación del JS siguen corriendo una sola vez, en un
  job aparte, porque su veredicto no depende del sistema.

### Added
- **`scripts/dev/`**: los bancos de prueba que la suite automática no cubre — un backend
  OpenAI-compatible falso y lento (para ver el panel «En curso» de verdad y ejercitar el
  chunking sin GPU), un comprobador del dashboard con la zona horaria forzada vía Playwright, y
  el procedimiento del instalador contra un HOME simulado. Se habían montado durante el
  desarrollo de la 0.11.0 y se perdieron al cerrar la sesión; reconstruir un banco de pruebas
  es la forma más fiable de acabar no verificando nada.

### Fixed
- **El instalador reescribía entero el `CLAUDE.md` del usuario en Windows.** `write_text` usa el
  terminador de línea de la plataforma, así que añadir el bloque de la regla de delegación a un
  archivo guardado en LF lo convertía a CRLF: el diff salía completo en rojo y, en un archivo
  compartido entre una Mac y un Windows, generaba conflictos. Ahora se escribe con el
  terminador que el archivo ya tenía, y `uninstall` vuelve a dejarlo **byte a byte** como
  estaba (verificado en Windows, no solo en Linux). Afectaba también a `settings.json` y al
  `config.toml` de Codex.
- Los archivos con `#!` (los tres hooks empaquetados y `scripts/bump_version.py`) no tenían el
  bit de ejecución en git. Solo se nota en sistemas POSIX —en Windows ese bit no existe, así
  que un `ruff check` local no puede verlo— y rompía el lint del CI.
- **ruff 0.16.0** (solo desarrollo). Promueve a estables reglas que sacaban 79 avisos en código
  hoy limpio; se aplican los arreglos que son mejora real (`datetime.UTC`, `re.MULTILINE`,
  `removeprefix`, `typing.Self` en los `__enter__`, `fromisoformat` sin el reemplazo de `Z` que
  3.11 ya no necesita) y se **ignoran con su motivo** las que chocan con decisiones deliberadas:
  `BLE001`/`S110` (diagnóstico, sysinfo e instalador son best-effort y nunca deben lanzar) y
  `PLW1510` (`subprocess.run` comprueba el returncode a mano para dar un mensaje propio). El
  formateador excluye los `.md`: 0.16 formatea los bloques Python embebidos y reescribía
  documentación histórica.

### Fixed
- **El origen del cómputo mentía detrás de un túnel.** `backend_origin()` clasifica por el host
  de `BASE_URL`, así que un `ssh -L 9292:…` o un port-forward de Tailscale —el backend remoto
  visto en `127.0.0.1`— se reportaba como **cómputo local**, justo en la topología Mac→PC que el
  proyecto recomienda. Un túnel es transparente por diseño y no hay forma fiable de detectarlo,
  así que se añade `LOCAL_DELEGATE_BACKEND_ORIGIN=local|remote` para declararlo; `auto` (el
  default) mantiene la heurística de siempre y un valor inválido cae a `auto` en vez de romper
  el arranque.

## [0.11.0] - 2026-07-27

### Added
- **Publicación automática en el registro oficial de MCP.** El tag `vX.Y.Z` ya publicaba en PyPI;
  ahora encadena un job que publica también `server.json` con `mcp-publisher login github-oidc`
  (sin secretos: el registro valida el namespace contra el token OIDC del workflow). Antes de
  tocar nada se comprueba que el tag, `pyproject.toml` y **las dos** versiones de `server.json`
  coinciden, y antes de publicar el descriptor se espera a que PyPI sirva la versión — el
  registro valida que el paquete exista. La coherencia de versiones se comprueba además en cada
  PR (`tests/test_release_metadata.py`).
- **`scripts/bump_version.py`:** sube la versión en los **cuatro** sitios donde vive
  (`pyproject.toml`, las dos de `server.json` y `uv.lock`) de una sola vez, y regenera el lock.
  Los guardarraíles anteriores solo *detectan* un bump a medias —y el histórico dice que pasa:
  en la 0.8.1 el lock se quedó en 0.7.0—; este lo evita. `--check` verifica la coherencia en
  local antes del push (incluido `uv.lock`, que ningún test miraba), `--dry-run` enseña el plan.
  Edita el texto en vez de reserializar, así el diff son cuatro líneas y no un reformateo.
- **`local-delegate install` / `uninstall`:** la instalación deja de ser solo el servidor MCP.
  Un comando registra la entrada MCP (Claude Code y Codex), copia los hooks consultivos a
  `~/.claude/hooks/local-delegate/` y los inscribe en `settings.json`, instala la skill
  `delegacion-local` y escribe un bloque gestionado con la regla de delegación en
  `~/.claude/CLAUDE.md` y `~/.codex/AGENTS.md`. Idempotente (marcadores `begin/end`, hooks
  desregistrados antes de reinscribirse), con `--dry-run`, backups `.bak`, exclusión por
  componente (`--no-hooks`/`--no-skill`/`--no-memory`/`--no-mcp`) y reversión completa. Los
  hooks, la skill y el bloque de memoria ahora viajan **dentro del paquete**
  (`src/local_delegate/resources/`).
- **Chunking de salida** en `local_translate` y `local_delegate`: las entradas largas se parten
  por límites naturales (headers Markdown → párrafos → líneas → corte duro) y se procesa un
  trozo por llamada respetando `max_tokens`, concatenando en orden y reponiendo el separador
  original en cada costura. Un documento de 20 000+ caracteres vuelve **completo** en vez de
  cortado con `[salida truncada]`; si un trozo aun así trunca, se vuelve a partir y se
  reintenta. La operación se registra como **un** evento con `chunks: N` y el panel "En curso"
  muestra el progreso `trozo i/N`. Configurable con `LOCAL_DELEGATE_CHUNK_CHARS`,
  `_CHUNK_MAX_TOKENS` y `_CHUNK_MIN_CHARS`; `local_delegate` acepta `chunk='auto'|'on'|'off'`.
- **Origen del cómputo en el log y el dashboard:** cada evento registra `backend`
  (`local`/`remote`, por el host del endpoint) y `backend_host`. El dashboard lo muestra en un
  donut nuevo, una insignia en el panel de backend, una columna en la actividad y agregados en
  `/api/stats`, así se distingue lo generado por el backend de esta máquina de lo generado con
  la GPU de otra (p. ej. la Mac usando la PC). Los eventos previos se muestran como `n/d`, no
  como locales. `local_status` también lo reporta.

### Security
- El repositorio incorpora CodeQL, Dependabot (dependencias y actions), `SECURITY.md` con canal
  privado de reporte, `CODEOWNERS` y `permissions:` de mínimo privilegio en los workflows.
  `scripts/setup_repo_security.sh` aplica de una vez lo que no puede versionarse: regla sobre
  `main` (PR obligatorio, CI en verde, sin force-push ni borrado), secret scanning con push
  protection, alertas de Dependabot y private vulnerability reporting.

### Changed
- **Chart.js se sirve desde el propio paquete** (`/vendor/chart.umd.min.js`) en vez de un CDN:
  el dashboard de una herramienta local-first ahora funciona sin conexión y no anuncia a un
  tercero que estás mirando tus métricas. La tipografía de marca queda como único recurso
  externo, es cosmética y se desactiva con `LOCAL_DELEGATE_WEB_FONTS=0`.
- El dashboard trabaja en la **zona horaria del equipo**: "Hoy" empieza a tu medianoche, las
  barras agrupan por tu día natural, el rango personalizado interpreta las fechas como locales
  y la tabla muestra tu hora (antes todo se calculaba en UTC, así que las delegaciones de la
  tarde/noche caían en el día equivocado o quedaban fuera de "Hoy"). El log sigue en UTC.
- El indicador de actividad tiene tres estados —`EN CURSO`, `EN VIVO`, `EN REPOSO`— y ya no
  depende del rango elegido ni del auto-refresco: se apoya en las delegaciones vivas y en el
  último evento de todo el histórico, se repinta cada segundo y descuenta el desfase entre el
  reloj del navegador y el del servidor. Los sondeos se refrescan al volver a la pestaña.
- `local_delegate` sube su techo de salida de 1024 a 2048 tokens.

### Fixed
- **Delegaciones en curso perdidas o fantasma:** `inflight.json` se publicaba a través de un
  temporal de nombre **fijo**, así que dos procesos MCP escribiendo a la vez (varias sesiones
  `stdio`, o una sesión y el daemon) se pisaban el temporal. Ahora el temporal lleva el pid.
- El sondeo del panel reescribía `inflight.json` cada 2 s aunque no hubiera cambios,
  compitiendo por el lock con las delegaciones reales; ahora solo se escribe si algo cambió y
  el sondeo nunca escribe sin el lock (una entrada recién registrada por otro proceso ya no
  puede perderse).
- Los hooks documentados usaban `{"type":"command","command":"python","args":[…]}`, formato que
  Claude Code no soporta: quedaban registrados pero **nunca ejecutaban** el script. El
  instalador y la recipe usan un único string de comando, y `install` **retira las entradas
  heredadas** de ese formato en vez de dejarlas como duplicados inertes.
- Si Chart.js no cargaba, el `Chart.register(...)` inicial abortaba el script del dashboard y se
  llevaba por delante KPIs, tabla, panel de backend e indicador de actividad. Ahora degrada a
  "sin gráficos" (además de servirse en local, con lo que el caso es ya improbable).
- `_pid_alive` en Windows llamaba a `OpenProcess` sin `restype`/`argtypes`, con lo que ctypes
  truncaba el HANDLE de 64 bits y `CloseHandle` recibía un handle inválido: el daemon filtraba
  un handle por cada sondeo del dashboard.

## [0.10.0] - 2026-07-23

### Added
- Topología remota recomendada **MCP local en Mac → backend llama-swap en PC**, con recipe de
  Tailscale Serve/HTTPS privado, Keychain/DPAPI, configuración de Claude Code y canary automatizado
  de 20 llamadas que valida auth, concurrencia, reinicio y un `path` exclusivo de macOS.
- `local-delegate benchmark`: runner reproducible para comparar modelos densos/MoE, contexto y
  offload sin promover automáticamente modelos al catálogo estable.
- `UserPromptSubmit` consultivo para intenciones mecánicas explícitas y telemetría metadata-only;
  suite A/B versionada para medir adopción y falsos positivos.
- `doctor --online` reporta edad de releases, compuerta de 7 días y hasta tres issues recientes con
  señales de crash/deadlock/regresión antes de recomendar un canary.

### Changed
- `LOCAL_DELEGATE_API_KEY` se aplica también a `/models`, `/running`, métricas del backend,
  autostart, doctor y benchmark; antes solo protegía `/chat/completions`.
- El piloto de hooks subió la adopción de 5/6 a 6/6 (+20% relativo). `UserPromptSubmit` y el flujo
  de lint quedan recomendados; `PreToolUse/Read` queda experimental y apagado por defecto porque
  avisó en 2/4 tareas negativas.
- Las versiones estables recomendadas continúan en llama-swap v238 y llama-server b9925: las
  releases más nuevas siguen en `HOLD` hasta cumplir soak y canary.

### Fixed
- La suite aísla `LOG_DIR`/`USAGE_LOG` por test para no contaminar la telemetría real del usuario
  con llamadas de fixtures.
- El sdist excluye configuración local de agentes (`.codex`), evidencia interna SDD, entornos y
  builds previos; esos directorios podían colarse aunque no estuvieran trackeados por Git.

## [0.9.0] - 2026-07-23

### Added
- **Daemon singleton HTTP:** `local-delegate serve` publica MCP Streamable HTTP en `/mcp` y el
  dashboard en `/` usando un único proceso persistente y un único puerto (default
  `127.0.0.1:9393`). Un lock por usuario evita daemons duplicados; `/api/daemon` expone estado,
  PID y URLs para diagnóstico. El transporte `stdio` sin argumentos se conserva compatible.

### Changed
- `check-llamaswap` e `init-llamaswap` rechazan por defecto modelos fuera de todos los `groups`,
  porque quedarían fuera del presupuesto de VRAM/RAM. `--allow-ungrouped` permite la exclusión
  deliberada con un aviso explícito.
- El autoarranque acepta `LLAMASWAP_WATCH_CONFIG=1` para añadir `-watch-config` cuando existe
  `LLAMASWAP_CONFIG`, evitando reinicios manuales en cambios futuros del catálogo o los grupos.
- Backpressure configurable con `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS` (default `2`). En el
  daemon singleton el límite se comparte entre todos los clientes HTTP.

### Fixed
- El daemon puede ejecutarse con `pythonw.exe` en Windows sin consola visible: si el runtime no
  define `stdout`/`stderr`, usa `NUL` para que Uvicorn inicialice su logging sin fallar.
- El dashboard identifica el proceso servidor compartido como `DAEMON MCP`, evitando confundirlo
  con un proceso nuevo por cada sesión cliente.

## [0.8.1] - 2026-07-11

### Fixed
- Dashboard, panel «Backend local»: el estado **montado/loaded** de un modelo tardaba hasta 60 s
  en reflejarse porque el status loaded/unloaded (#901) solo se refrescaba vía `/api/status` (cada
  60 s). Ahora `GET /api/backend` incluye también `models: [{id, status}]` y el poll rápido (2 s) lo
  mantiene fresco, así un modelo recién cargado se marca «montado» casi al instante.
- Dashboard, panel «Backend local»: la columna de estado («frío»/«montado») no quedaba alineada
  entre filas — `.mstate` y `.mstatus` tenían ambos `margin-left:auto`, así que flexbox repartía el
  hueco y la posición dependía del ancho (variable) del badge de rol. Ahora la columna de estado y el
  badge tienen ancho fijo y se alinean en todas las filas.

## [0.8.0] - 2026-07-11

### Added
- **`local-delegate doctor`**: nuevo subcomando (opt-in, junto a `check-llamaswap`/
  `init-llamaswap`) que diagnostica la instalación del backend local. Detecta las versiones
  instaladas de `llama-server` (desde el `cmd` del `config.yaml`, con lectura de texto — funciona
  sin el extra `[llamaswap]`) y `llama-swap` (vía `LLAMASWAP_EXE` o el PATH), comprueba si el
  backend responde, y las compara contra las versiones probadas de esta release
  (`RECOMMENDED_VERSIONS` en `doctor.py`). Con `--online` consulta además la última release
  publicada en GitHub. Exit code `1` si hay actualizaciones sugeridas. Nuevo módulo `doctor.py`.
- Dashboard: panel **«Rendimiento del backend»** que muestra las métricas de actividad que
  llama-swap ≥ v236 persiste en SQLite (#898) — total de requests, tokens in/out, y percentiles
  (p50/p95) de tokens/segundo de generación y de prompt. Nuevo endpoint proxy
  `GET /api/backend/stats` (best-effort sobre `/api/metrics/stats` de llama-swap; degrada a «sin
  datos» con otro backend o una versión vieja).
- `init-llamaswap --store-path`: escribe `store.path` en el `config.yaml` para que las métricas
  de #898 sobrevivan a los reinicios de llama-swap (sin ella son in-memory).
- Nueva página de wiki **[Backend versions](docs/wiki/Backend-versions.md)**: versiones probadas
  de llama-server/llama-swap (b9925 / v238), estructura de workspace de referencia y guía de
  `local-delegate doctor`.

### Changed
- Dashboard y `local_status`: los modelos del backend ahora muestran su estado **loaded/unloaded**
  a partir del campo `status` de `/v1/models` (#901 de llama-swap, que lo expone como objeto
  anidado `{value: …}`, verificado en vivo). `GET /api/status` devuelve `backend.models` como
  `[{id, status}]` en vez de `[id]`. Degrada limpio con backends que no exponen `status` (Ollama,
  llama-swap < v236): `status` queda en `null` y simplemente no se muestra el badge.

## [0.7.0] - 2026-07-10

### Fixed
- Dashboard: el panel «En curso» nunca mostraba delegaciones activas si el navegador
  consultaba un proceso MCP distinto del que las ejecutaba (varias sesiones de Claude Code
  abiertas a la vez, o la web arrancada manualmente con
  `python -m local_delegate.web.metrics`) — el estado `inflight` vivía solo en memoria del
  proceso que ganaba el puerto 9393. Ahora `_inflight_start`/`_inflight_end`/
  `inflight_snapshot()` leen y escriben `LOG_DIR/inflight.json` bajo `FileLock`, así
  `/api/inflight` ve las delegaciones de **todas** las sesiones activas en la máquina, no
  solo la del proceso que sirve la web. Autolimpieza de entradas huérfanas (proceso muerto o
  con más de 30 min sin cerrarse) en cada lectura, sin hilo de fondo dedicado.
- Dashboard: el mensaje vacío «Sin delegaciones en curso» heredaba `Inter` en vez de
  `JetBrains Mono` como el resto del panel «Backend local» (badges, nombres de modelo,
  contador de tiempo).

### Added
- Dashboard: el modelo que está procesando una delegación ahora se marca en el panel
  «Backend local» (punto ámbar con pulso, estado «procesando») y la tool en uso se resalta
  en los chips de «Tools MCP disponibles», cruzando el modelo/tool de cada entrada de
  `/api/inflight` contra las filas ya renderizadas.

## [0.6.0] - 2026-07-10

### Added
- Dashboard: endpoint `GET /api/status` (versión del MCP en ejecución, modelos que el backend
  expone de verdad vía `/v1/models` — antes la web solo enseñaba modelos con eventos en el
  log —, catálogo de roles y lista de tools MCP) y `GET /api/system` (RAM y VRAM de sistema
  con uso/total/% + consumo por proceso de los servicios de debajo del MCP: llama-swap,
  llama-server, ollama…, y el propio proceso MCP). Nuevo módulo `web/sysinfo.py`, todo
  best-effort y de solo lectura; la VRAM por proceso en Windows (WDDM) sale de los perf
  counters `GPU Process Memory` muestreados en un hilo de fondo con TTL, porque `nvidia-smi
  --query-compute-apps` no la reporta en ese modo.
- Dashboard: panel «Backend local» (estado del endpoint, los modelos disponibles con su rol
  del catálogo y su estado montado/frío en llama-swap, delegaciones en curso, tools MCP) y
  panel «Sistema» (barras de RAM/VRAM con umbrales de color, utilización de GPU y tabla de
  procesos). Versión del MCP visible en el header.

### Changed
- Dashboard: rango temporal por defecto ahora es **Hoy** (antes: últimos 30 días); la tabla
  de actividad reciente se pagina de 10 en 10 (antes: primeras 30 filas fijas); la
  explicación de «¿cómo se calcula el ahorro?» pasa de un `<details>` al pie a un diálogo
  modal accesible desde el icono «?» del header.
- Dashboard: iconografía rehecha en SVG — botones del header sin glifos de texto ↻/⟳/◐,
  iconos de KPI nuevos (escudo, rayo, chip, gauge) y el icono de información pasa de un
  círculo CSS con letra a un SVG nítido; marca/favicon rediseñados para leerse bien a 16px
  (cuerpo del chip al ~62% del viewBox, solo 2 pines gruesos por lado y doble chevrón » de
  delegación en el núcleo).

### Removed
- Dashboard: filas de chips de filtro Tools/Modelos — redundantes con el panel «Backend
  local» (que ya lista modelos y tools reales) y con el rango temporal server-side; los
  agregados vuelven a computarse sobre todos los eventos del rango.
- README: la imagen del demo apunta por URL absoluta a `raw.githubusercontent.com`, de modo
  que también se renderiza en la página del paquete en PyPI (los links relativos solo
  funcionan dentro de GitHub); captura regenerada con el dashboard nuevo.

## [0.5.0] - 2026-07-09

### Added
- Guardrail de **RAM de sistema** (F7.9), además del de VRAM: `check-llamaswap` e
  `init-llamaswap` ganan flags opcionales `--ram-gb`/`--ram-margin-gb` (default de margen 2.0
  GiB); si no se pasan, el comportamiento es idéntico al de 0.4.0 (compatibilidad hacia
  atrás). Motivo: verificado en vivo durante la aplicación del ritual F7.8 que `llama-server`
  mapea el GGUF también en RAM del sistema (mmap) aunque el cómputo sea 100% GPU — un
  catálogo que cabe holgado en VRAM puede igual agotar la RAM y afectar otras ejecuciones del
  MCP en máquinas con menos de 32 GB. Nuevo `estimate_model_ram()` en `llamaswap_config.py`
  (pesos del GGUF, sin KV — asume offload completo a GPU; documentado como límite inferior si
  el `-ngl` es parcial); la aritmética de peor caso por grupo se generalizó
  (`worst_case_gb()`, con `worst_case_vram_gb` como alias retrocompatible) porque es idéntica
  para VRAM y RAM (llama-swap libera ambos recursos juntos al descargar un modelo).
- `local_status` añade una línea best-effort de RAM de sistema (Windows vía `ctypes`
  `GlobalMemoryStatusEx`, Linux vía `/proc/meminfo`; macOS no implementado, nunca rompe la
  tool). Verificado en vivo: con `qwen25-coder-14b` + `gemma3-4b` cargados a la vez, el
  estimador dio 10.69 GiB de RAM peor-caso vs. ~10.30 GB medidos con `Get-Process` — conforme
  al mismo margen conservador que ya tenía el estimador de VRAM.

## [0.4.0] - 2026-07-09

### Added
- Dos CLIs opt-in (F7): `local-delegate check-llamaswap --config <path> --vram-gb <N>` valida
  el peor caso de VRAM de los `groups` de un config.yaml de llama-swap contra un presupuesto
  con margen de seguridad; `local-delegate init-llamaswap` genera/actualiza `groups` (patrón
  residente + swap) sobre un config existente, corriendo el mismo guardrail internamente antes
  de escribir (nunca escribe si no cabe, nunca sobreescribe sin `--force`, siempre deja `.bak`).
  Requieren el extra opcional `[llamaswap]` (`pip install "local-delegate-mcp[llamaswap]"`,
  dependencia `pyyaml`); sin el extra, el resto del paquete se comporta exactamente igual que
  antes. El paquete nunca toca `config.yaml` de llama-swap por su cuenta — estos comandos son
  100% opt-in.
- Módulo `llamaswap_config.py`: estimador de VRAM por modelo GGUF con dos vías. Cuando el GGUF
  trae metadatos de arquitectura (capas, cabezas KV, dimensión de cabeza) y el `cmd` del modelo
  tiene `--ctx-size` explícito, calcula pesos + KV cache real (respeta `--cache-type-k/v`); si
  falta cualquiera de las dos cosas, cae a una estimación gruesa documentada
  (`tamaño_archivo * 1.2`). Verificado contra los GGUF reales del catálogo de referencia: el
  factor plano por sí solo subestimaba hasta 1.4 GiB en el caso de contexto grande sin
  cuantizar el KV cache — de ahí la vía fina con parser de header GGUF.
- `local_status` añade una línea best-effort con los `groups` activos en `LLAMASWAP_CONFIG`
  (solo si el extra `[llamaswap]` está instalado y el archivo existe; nunca rompe la tool).
- Recipe `docs/recipes/llama-swap-groups.md`: semántica de `groups` verificada contra el
  código real de llama-swap (v235/c59816b), presupuesto de VRAM con ejemplo real, los dos
  comandos, ritual de aplicación, y por qué el paquete no toca `config.yaml` solo.

## [0.3.0] - 2026-07-09

### Added
- Nueva tool `local_describe_image(path, question=None, max_words=200)` (F6): describe una
  imagen o responde una pregunta sobre ella con un modelo local de visión. La imagen se lee
  server-side (respeta `LOCAL_DELEGATE_ALLOWED_DIRS`), valida extensión
  (png/jpg/jpeg/webp/gif) y tamaño (`LOCAL_DELEGATE_MAX_IMAGE_MB`, default 8) antes de leerla
  completa. 11 tools en total. Guardrail de alcance: solo imagen→texto, nunca genera ni edita
  imágenes.
- Rol de modelo `LOCAL_DELEGATE_MODEL_VISION` (default `qwen3-vl-8b`), fuera de
  `ALLOWED_MODELS` (ese set es solo para el escape genérico `local_delegate`, texto→texto).
- `_chat` acepta `content` multimodal (lista de bloques `text`/`image_url` OpenAI-compatible)
  además de `str`, sin duplicar el manejo de inflight/log/feedback.
- `local_status` muestra el rol `vision` en el catálogo.
- Recipe `docs/recipes/llama-swap-vision.md`: entrada de `config.yaml` con `--mmproj`
  (Qwen3-VL-8B-Instruct Q4_K_M + mmproj Q8_0, ~5.78 GB), versión de `llama-server` probada
  pineada (9743/c57607016) con advertencia de multimodal experimental, y MiniCPM-V-4.5 como
  alternativa documentada.

## [0.2.1] - 2026-07-09

### Fixed
- `local_extract`: el schema de `response_format` restringe cada propiedad a tipos
  primitivos (`string`/`number`/`boolean`/`null`) en vez de un sub-schema vacío. Con el
  sub-schema vacío, algunos modelos (verificado con `gemma3-4b`) anidaban el valor en
  vez de devolverlo plano — `{"campo": {"valor": "x"}}` en lugar de `{"campo": "x"}`.
  Encontrado verificando la 0.2.0 en producción contra el backend real.

## [0.2.0] - 2026-07-09

### Added
- Nueva tool `local_status` (solo lectura): estado del backend (`/models`), catálogo de
  roles activo con `max_chars`, stats del log del mes actual, estado de la web de
  métricas, y VRAM (`nvidia-smi`) + modelo montado en llama-swap (`/running`) best-effort.
  10 tools en total.
- `local_extract` pide `response_format` con JSON schema por defecto
  (`LOCAL_DELEGATE_JSON_SCHEMA=auto|on|off`); si el backend responde 400 en modo `auto`,
  reintenta una vez sin schema.
- Feedback de ahorro: `_chat` anexa "leído server-side: N chars ≈ M tokens que no
  entraron a tu contexto" cuando `source=path` (apagable con `LOCAL_DELEGATE_FEEDBACK=0`).
- Log rotado por mes (`usage-YYYYMM.jsonl` en `LOCAL_DELEGATE_LOG_DIR`); el `usage.jsonl`
  legado se sigue leyendo como fuente adicional, sin migrarlo.
- Dashboard: selector de rango real (Hoy/7d/30d/mes anterior/todo/personalizado) que
  refetch server-side (`GET /api/events?from=&to=`, `GET /api/stats?from=&to=`) en vez de
  filtrar client-side; solo abre los archivos de log que tocan el rango pedido.
- Visibilidad de delegaciones en curso: `GET /api/inflight` y `GET /api/backend` (proxy de
  `/running` de llama-swap), con una tarjeta "En curso" en el dashboard.
- `LOCAL_DELEGATE_ALLOWED_DIRS`: restringe opcionalmente el parámetro `path` de todas las
  tools a una lista de raíces permitidas (`;` como separador). Vacío = sin restricción.
- Docstrings de las tools que aceptan `path` indican explícitamente cuándo preferirlas
  sobre leer el archivo con `Read`.
- Recipe de hooks de Claude Code (`docs/recipes/claude-code-hooks.md` +
  `docs/recipes/hooks/`) que sugieren delegar sin bloquear nunca la tool original.
- `update_agents.py` v2: mantiene un bloque de catálogo en prosa en los agentes que
  delegan, además de la línea `tools:`.

### Changed
- `_post_chat` devuelve un `ChatResult` estructurado (`ok`, `error`, `finish_reason`,
  `tokens_in`, `tokens_out`) en vez de codificar el error en el propio texto; el log de
  uso ahora registra tokens reales del backend cuando están disponibles, `finish_reason`,
  `error`, truncados y la versión del paquete.
- Cliente `httpx` module-level con keep-alive entre delegaciones.
- Escritura del log protegida con `filelock` (best-effort: si no consigue el lock en 1s,
  escribe igual, nunca bloquea la tool).

### Fixed
- Salida truncada por `max_tokens` ahora produce un aviso visible en el texto devuelto
  (antes se truncaba en silencio); igual para la entrada truncada al leer un `path`.
- Bloques `<think>`/`<thinking>` de modelos razonadores (Qwen3, R1-distill) se eliminan
  de la salida antes de devolverla.
- `local_commit_msg` valida `style` en vez de caer a `'plain'` en silencio si el valor no
  es reconocido.
- `local_extract` enruta por tamaño de entrada (mecánico/largo) igual que las demás tools
  con `path`, en vez de usar siempre el modelo mecánico.

## [0.1.1] - 2026-07-08

### Fixed
- Dashboard: el sparkline del KPI "Contexto conservado" ya no dibuja una línea sobre el texto
  cuando el ahorro es 0; ahora se ancla al borde inferior (`y.min=0`).

### Added
- Recipes de backends en `docs/recipes/`: llama-swap (RTX 5060 Ti Blackwell) y Ollama.
- Sección *Demo* en el README con screenshot del dashboard de ahorro.
- Wiki en `docs/wiki/` (+ wiki nativa de GitHub): Architecture, Configuration, Savings & metrics, Publishing, Troubleshooting.

### Changed
- `publish.yml`: `uv publish --check-url` para hacer la publicación idempotente ante
  re-ejecuciones sobre un tag existente.

## [0.1.0] - 2026-07-07

### Added
- Servidor MCP stdio con 9 tools texto→texto (`local_summarize`, `local_classify`,
  `local_extract`, `local_boilerplate`, `local_delegate`, `local_lint_summary`,
  `local_commit_msg`, `local_translate`, `local_explain_code`).
- Cliente genérico de cualquier endpoint OpenAI-compatible (llama-swap, Ollama, LM Studio, vLLM),
  configurable por variables de entorno; sin rutas hardcodeadas (`platformdirs` para el log).
- Web de métricas embebida (dashboard de uso/ahorro) en un hilo daemon.
- Logging JSONL por llamada (`usage.jsonl`) para calcular el ahorro de contexto.
- Auto-arranque de llama-swap opcional (opt-in, `LOCAL_DELEGATE_AUTOSTART=0` por defecto).
- Empaquetado para PyPI (`local-delegate-mcp`) ejecutable con `uvx`; `server.json` para el
  registro oficial de MCP.

[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.22.1...HEAD
[0.22.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.22.0...v0.22.1
[0.22.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.18.1...v0.19.0
[0.18.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.18.0...v0.18.1
[0.18.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.13.1...v0.14.0
[0.13.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.13.0...v0.13.1
[0.13.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.12.4...v0.13.0
[0.12.4]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.12.3...v0.12.4
[0.12.3]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.12.2...v0.12.3
[0.12.2]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.12.1...v0.12.2
[0.12.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ZahiriNatZuke/local-delegate/releases/tag/v0.1.0
