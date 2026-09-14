# Changelog

Todos los cambios notables de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

### Added
- **`local-delegate benchmark` mide la memoria del proceso, y no la del sistema**
  (`--probe-process`, `--gpu-luid`, solo Windows). El canary de julio descartó un modelo midiendo
  la RAM de toda la máquina, que daba 27-29 GiB con el modelo entero en GPU. La sonda lee por
  proceso la RAM privada **y** el working set —los dos siempre, porque con los pesos mapeados lo
  mapeado no cuenta como privado y los expertos de un MoE desaparecerían de la cuenta— y la VRAM
  dedicada y compartida del adaptador correcto. Sin dependencias nuevas: `ctypes` y `typeperf`.

  Cada supuesto se comprobó ejecutándolo antes de escribir el código, y tres salieron distintos
  de lo previsto: la instancia de GPU va por adaptador y hay que filtrarla por LUID o se suma la
  VRAM de la gráfica integrada; `typeperf` no se cierra cuando el proceso muere, sino que emite
  `-1` cada segundo; y un lanzador intermedio tiene otro PID que el proceso medido, así que el
  proceso se busca por nombre. Una corrida sin muestras, con dos `llama-server` vivos o con cambio
  de proceso a mitad lleva `annul` en el JSONL y se repite; no se publica vacía.

- **La regla puede rechazar una lectura, y no solo sugerirla.** Cuatro mediciones seguidas dieron
  adopción cero —la última ya con el aviso acertando el tipo de fichero, `.md` 49 y `.txt` 15 de
  85 avisos—, así que el problema dejó de ser la puntería: sugerir no cambia la conducta. El hook
  de lectura puede ahora bloquear con `permissionDecision: deny`, nombrando la tool que sirve, el
  `path` para llamarla y la salida de emergencia (leer por franjas con `offset`/`limit`, que nunca
  se bloquean).

  **Nace apagado** (`LD_HOOK_READ_BLOQUEAR=0`) y se enciende cuando esté escrito el criterio de la
  quinta medición, incluido el resultado que lo retira. Se apaga **sin reiniciar la sesión**: la
  variable se consulta en cada invocación, porque está medido que una sesión abierta hereda el
  entorno del lanzador y un freno que exige reiniciar no frena nada.

  El caso es estrecho a propósito. Solo `.md` y `.txt` leídos enteros y por encima del umbral:
  `.json`, `.csv`, `.log` y `.yaml` **se avisan pero no se bloquean**, porque ahí se busca un valor
  exacto —un `package.json`, la línea del error— y un resumen no sustituye a la lectura. De `.csv`
  y `.log` no hubo **ni un aviso** en el periodo medido, así que bloquearlos habría sido inventar
  el caso.

- **Un hook nuevo para la otra mitad de la superficie de lectura** (`suggest_delegate_shell.py`,
  matcher `Bash|PowerShell`). Cerrar la tool `Read` y dejar `cat informe.md` abierto no cambia la
  conducta: la muda de sitio, y entonces la adopción medida sube sin que se ahorre un token. Se
  registra **todo** comando, se bloquee o no, porque sin denominador no se sabe cuánta lectura se
  va por ahí.

  Reconoce solo formas simples e inequívocas —`cat`, `type`, `more`, `Get-Content`, `gc`,
  `rtk read`, `head`— sobre una única ruta. Con una tubería, una redirección, dos comandos
  encadenados, una sustitución o un flag que ya acota, **no bloquea**: un comando mal parseado que
  se rechaza no es un consejo malo, es impedir algo que el usuario pidió.

- **El bloqueo se cae solo cuando no hay a dónde delegar.** Si el backend local no responde, la
  lectura pasa. El dato no sale de las delegaciones anteriores —sería un círculo cerrado: sin
  delegaciones no hay marca fresca, sin marca fresca no se bloquea, y sin bloqueo no hay
  delegaciones—, sino de un sondeo propio cacheado un minuto, con 300 ms de plazo. Marca ausente,
  vieja, corrupta o ilegible significan **no bloquear**.

- **«Ofrecido» y «aceptado» ya son dos números comparables.** Cada aviso y cada bloqueo llevan un
  identificador, la sesión que lo provocó y la **huella del script que corrió** —un sha256 del
  fichero, no una constante que alguien tenga que acordarse de subir—. El hook deja una nota con
  ese identificador y una huella de la ruta, y la tool que recibe ese mismo `path` se queda con él
  en su evento (`bloqueo_id`). El identificador no viaja por el agente a propósito: pedirle que lo
  pase sería depender de que obedezca, que es justo lo que se quiere medir.

### Added
- **`scripts/medir_adopcion.py`**, que responde por fin «de los avisos dados, cuantos acabaron
  en delegacion». Las cuatro mediciones anteriores ataron los dos logs a mano y esa pregunta se
  quedo sin respuesta. Da el denominador por motivo y por camino, la tasa de aceptacion, y
  cuantas delegaciones fueron espontaneas —esas no se las puede apuntar la regla—. Avisa si la
  ventana mezcla dos versiones de script, porque una sesion abierta hereda el entorno del
  lanzador y entonces la muestra junta dos politicas sin decirlo.

- **Los eventos de lectura llevan la huella de la ruta** (nunca la ruta). Sin ella no se podia
  agrupar por fichero, y esa es justo la pregunta pendiente de la guarda de «lectura acotada»:
  de las 252 lecturas por franjas registradas, cuantas eran de un fichero que acabo leyendose
  entero de todas formas.

### Fixed
- **`content: null` reventaba la tool entera.** `choice["message"]["content"].strip()` lanzaba
  `AttributeError`, y ese tipo no estaba en el `except` que lo rodeaba: la excepción se escapaba de
  `_post_chat`. Ahora es un fallo clasificado con mensaje legible. Y si el motivo de parada fue
  `length` con razonamiento no vacío, el error lo dice en claro —el modelo gastó `max_tokens`
  pensando—, que es configuración y no avería: taparlo haría que nadie lo arreglara.

- **`ConnectTimeout` no ofrecía arrancar el backend.** Caía en el `except HTTPError` genérico y se
  clasificaba como `http_error`, porque **no es subclase de `ConnectError`**: son ramas hermanas de
  `TransportError`. Resultado: un backend apagado que agotaba el plazo de conexión no disparaba el
  autoarranque, que era exactamente lo que lo habría arreglado.

- **`ReadTimeout` se confundía con un backend caído.** Ahí el backend **sí** aceptó la conexión, así
  que lo más probable es que llama-swap esté montando el modelo: arrancar otro no arregla nada. Pasa
  a tener clase propia y mensaje propio.

### Changed
- **La clasificación de fallos sale de `server.py` a un módulo puro** (`fallos.py`): recibe el
  resultado o la excepción y devuelve la clase, sin red, sin estado y sin decidir reintentos. Es la
  primera de las tres capas que el respaldo entre modelos necesita, y las siete clases de la tabla
  ya existen aunque algunas todavía no tengan quien las consuma.

  Lo desconocido va a `sin_clasificar`, **nunca** a «del modelo»: esa es la única clase que
  disparará el respaldo, así que leer mal una variante nueva provocaría saltos de modelo y
  expulsiones de VRAM por un fallo que quizá era de la petición.

### Removed
- **Retirado el `retry_exhausted` del final de `_post_chat`**, que no se alcanzaba nunca. No se
  dedujo leyendo: se enumeraron las **16 formas** de terminar el `try` y se ejecutaron todas, y
  ninguna llegaba hasta ahí. Con control positivo, además —quitando la guarda del número de intento,
  dos de esos caminos sí la alcanzaban—, porque un no-resultado no es evidencia si no se comprueba
  que el experimento podía encontrar algo. Lo que esa línea prometía lo garantiza ahora
  `tests/test_post_chat_caminos.py`, que enumera los mismos 16 caminos y **sí se ejecuta**.

- **Retiradas `LD_HOOK_OUTPUT_STATS`, `LD_HOOK_OUTPUT_UMBRAL_KB`, `LD_HOOK_OUTPUT_MIN_MUESTRAS` y
  `LD_HOOK_OUTPUT_PROPORCION`.** Se quedaron **sin un solo consumidor** cuando la 0.27.0 retiró
  `output_policy.py` y `output_stats.py`, y su comentario seguía explicando por qué las leía un
  hook que ya no existe. Comprobado por búsqueda antes de tocarlas, no a ojo.

### Fixed
- **El check `hooks copiados` contaba `__pycache__` como si fuera un script.** Decía «4 script(s)»
  donde había 3, porque contaba las entradas del directorio y Python deja ahí su caché en cuanto
  los hooks se ejecutan una vez. No es cosmético: **ese número es justo el que se mira para
  confirmar que un script retirado desapareció** —así se verificó la retirada de `output_policy.py`
  y compañía en la 0.27.0—, así que un directorio de más hacía que el check afirmara lo contrario
  de lo que había pasado.

  Se cuentan los `.py`. Medido antes de tocar nada sobre los **tres** probes que listan un
  directorio: `scaffold.hook_orphans` y `scaffold.skill` no tenían el defecto —usan la lista para
  saber si el directorio existe, no para contar—, así que el arreglo es de un solo sitio y no de
  tres. Dos tests nuevos, uno de ellos el control que impide que el otro pase en vacío.

### Changed
- **El hook de lectura empieza a avisar a los 8 KB y no a los 32, porque el aviso no se ignoraba:
  no llegaba.** La pregunta era por qué el asistente no delega cuando toca, y la respuesta que
  parecía obvia —se salta la sugerencia— resultó falsa al medirla: el hook `PreToolUse/Read` está
  encendido, pero con el umbral en 32 KB **se callaba** ante los ficheros que se estaban leyendo
  (`9,5 KB` y `14,2 KB`). Los avisos que sí aparecían eran del hook de `UserPromptSubmit`, que
  dispara por el texto del prompt y no sabe qué fichero viene.

  El número nuevo sale de la telemetría, no de una estimación: sobre las **96 lecturas** registradas
  desde que el log guarda la extensión, el hook callaba por tamaño **24 veces y las 24 eran `.md`,
  `.json` o `.txt`** —ni una de código—, con **17 entre 8 y 16 KB**. Con 8 KB, **20 de esas 24**
  pasan a avisar. La banda `strong` se queda en 100 KB **a propósito**: se cambia una sola cosa,
  para que la próxima medición sepa a qué atribuir la diferencia.

  **Lo que este cambio NO hace, y por qué:** no bloquea la lectura. Que el asistente obedezca el
  aviso *cuando llega* sigue sin estar medido —en los casos observados no llegó—, así que construir
  el bloqueo ahora sería pagar su coste sin saber si hace falta. El criterio de decisión está
  escrito **antes** de ver el resultado en `.sdd/changes/read-obliga-a-delegar/research.md`.

- **El umbral vivía en cuatro sitios y nada los ataba** (`config.py`, el literal del hook, su
  docstring y la tabla de la recipe). El hook no puede importar `config` —es stdlib pura porque se
  copia al HOME—, así que la duplicación no se elimina: se ata.
  `test_el_umbral_del_hook_de_lectura_no_tiene_dos_valores` compara los tres valores configurables
  y falla si alguno se separa, para que nadie configure un número creyendo otro.

### Added
- **La wiki tiene por fin una página de catálogo de tools** (`docs/wiki/Tools.md`). Hasta ahora las
  once tools `local_*` solo estaban en la tabla resumen del README y en la skill: la wiki no las
  nombraba en ningún sitio, así que `local_boilerplate` no aparecía en toda la documentación
  extendida. La página lleva, por tool, la firma exacta, qué devuelve, qué modelo la atiende y qué
  pasa cuando la entrada no cabe, más la letra pequeña que solo estaba en el código:

  - que **map-reduce y troceado no son lo mismo** —el primero reduce (`local_summarize`,
    `local_lint_summary`, `local_commit_msg`) y el segundo transforma trozo a trozo
    (`local_delegate`, `local_translate`), porque fundir una traducción perdería contenido—;
  - que `local_extract` **trunca** y lo dice dentro del propio objeto, con la clave reservada
    `_local_delegate`;
  - que `local_status` no llama al backend de chat, así que **no** prueba que la credencial sirva;
  - y que un diff que no cabe da un mensaje de commit que solo describe el principio del cambio.

  El catálogo sale de `server.mcp.list_tools()`, o sea de lo que el cliente MCP ve de verdad. Tres
  tests nuevos en `tests/test_wiki.py` lo mantienen así: uno compara las secciones con el servidor
  en los dos sentidos, otro la tabla índice, y otro el número escrito con letra. Añadir una tool
  sin documentarla pone el CI en rojo en el mismo PR que la introduce.

### Fixed
- **La wiki llevaba cuatro versiones sin actualizarse, y ahora hay quien lo note.** `docs/wiki/`
  no se tocaba desde la 0.23.0: la tabla de comprobaciones de `doctor` tenía **diecisiete** filas
  con dieciocho checks en el registro —faltaba `service.daemon_auth`, el «token del puerto del
  daemon» que nació en la 0.26.0— y el texto seguía prometiendo «las dieciséis piezas». La fila de
  la skill también describía solo la de Claude Code, cuando desde la 0.19.0 se escribe también en
  opencode.

  Lo que lo dejó pasar es que `checks.py` **sí** tenía guardián (sus frases de tamaño estaban al
  día) y la wiki no. Ahora `tests/test_wiki.py` compara la tabla contra `checks.CHECKS` fila por
  fila y comprueba el número escrito con letra: añadir un check sin documentarlo pone el CI en
  rojo en el mismo PR que lo introduce.

- **Una justificación medida también caduca, y esta caducó.** El código, la wiki y el docstring de
  su test decían que una clave de primer nivel desconocida hace que opencode **no arranque**
  (`ConfigInvalidError`). Medido el 2026-09-08 con los dos binarios el mismo día: `1.18.11`
  rechaza el config entero (`Unrecognized key`, exit 1) y **`1.18.29` ya la tolera**. La medición
  original era correcta; el cliente relajó la validación.

  **No cambia el comportamiento del paquete**: se sigue escribiendo solo dentro de `mcp`, ahora
  por prudencia —la versión la elige el usuario— y porque lo que **no** ha cambiado en ninguna de
  las dos versiones es que una entrada mal formada *dentro* de `mcp` (sin `type`, sin `command`, o
  con `command` que no sea un array) sí impide arrancar. Tampoco cambia la ausencia de
  `--force-mcp-opencode`, que se sostiene por el otro motivo, intacto: sin marcadores no hay forma
  de distinguir nuestra entrada de una escrita a mano.

## [0.27.0] - 2026-09-08

### Changed
- **BREAKING — `local_boilerplate` escribe el código en disco y ya no lo devuelve.** La firma pasa
  a `local_boilerplate(spec, language, target, overwrite=False)`: `target` es obligatorio y debe
  ser una ruta **absoluta**. La tool devuelve un recibo de dos líneas —ruta, líneas, chars y los
  tokens que no entraron al contexto— y el código generado viaja al archivo, no de vuelta.

  El proyecto existe para que el contenido voluminoso no pase por el contexto caro, y esta era la
  única tool que aún lo mandaba entero de vuelta. `target` es obligatorio a propósito: como
  parámetro opcional, el ahorro habría dependido otra vez de que el modelo se acordara de usarlo,
  y de eso ya hay tres mediciones seguidas con cero adopción. Esta es la vía que ahorra **sin
  depender de que nadie obedezca un aviso**.

  Detalles del contrato nuevo:

  - **Se valida antes de gastar backend.** Ruta relativa, destino que ya existe sin
    `overwrite=True`, `target` vacío o fuera de `LOCAL_DELEGATE_ALLOWED_DIRS` fallan sin llamar al
    modelo. Generar código para tirarlo es el peor de los dos errores posibles.
  - **No pisa nada por defecto**; `overwrite=True` es explícito.
  - **Un fallo del backend no deja archivo.** El mensaje de error se devuelve como en cualquier
    otra tool, en vez de quedarse en disco con nombre de código fuente.
  - Los directorios que falten se crean, se escribe siempre con `\n` (el separador no depende de
    en qué sistema corra el daemon) y se garantiza el salto de línea final.
  - Sus anotaciones MCP dejan de decir `read_only_hint: true`, que en esta tool ya sería mentira:
    ahora declara `read_only_hint: false` con `destructive_hint: false` (por defecto solo crea) e
    `idempotent_hint: false`. El resto de las tools no cambia.

- **El panel cuenta el ahorro de salida.** Los eventos que escriben su resultado a un archivo
  llevan `output_to_file` en el log, y la contabilidad suma esos tokens al «contexto conservado»
  —usando el token real que reportó el backend, no una estimación por caracteres—. Es un ahorro
  distinto del de leer la entrada server-side (`source=path`) y se suma, porque una misma llamada
  puede ahorrar por los dos lados. La regla se actualizó en sus **dos** copias, la de Python y el
  espejo JavaScript del dashboard, y el test de paridad que las compara ejercita ya el caso nuevo.

### Removed
- **Retirados `output_policy.py`, `output_stats.py` y `emit_updated_input()`.** Eran las piezas del
  mecanismo que reescribía un comando para mandar su salida a un fichero, y se quedaron sin
  consumidor cuando ese mecanismo se descartó: el cliente ya persiste la salida grande por su
  cuenta, y `updatedInput` se salta el allowlist de permisos —el permiso se evalúa sobre el
  comando original, medido—.

  La última puerta que les quedaba la cerró la medición de `PostToolUseFailure`, el evento que
  faltaba por probar. **Sí existe y sí se dispara** cuando un comando Bash termina con código
  distinto de cero (`PostToolUse` no lo hace), y su payload trae el error y admite inyectar
  contexto. Pero no habilita ningún ahorro: cuando dispara, la salida truncada ya entró al
  contexto, y lo que sobraba no está en ninguna parte —a diferencia de los comandos que
  terminan bien, los que fallan **no** persisten su salida en disco ni traen
  `persistedOutputPath`—. Medido con control positivo y negativo: cinco comandos fallidos de
  18 900 bytes y ni un archivo persistido, frente al de código 0 que sí lo dejó entero.

  Eran 590 líneas de módulos y 475 de tests. Nunca llegaron a PyPI —se crearon después de la
  0.26.0, así que esta habría sido la primera release en empaquetarlos— pero sí estaban copiados
  en `~/.claude/hooks/`, puestos ahí por una instalación desde el repo. Quedan declarados en la
  lista de **scripts retirados** de `install`, para que esas copias se limpien en vez de volverse
  inmortales.

- **Retirado el hook `suggest_lint_summary.py`.** Decidía con una regex sobre el comando, antes de
  ejecutarlo, y la medición de 21 días de uso real le dio **366 disparos y 1 acierto** (0,3 %), con
  la mediana de salida en 402 bytes: lo que de verdad lo activaba eran las palabras `test` y
  `build` dentro de rutas. Un aviso que casi nunca tiene razón enseña a ignorar todos los avisos,
  incluidos los que la tienen. Ampliarle la lista de comandos no lo salvaba — ningún ejecutable del
  corpus superaba el umbral de tamaño en más del 9 % de sus ejecuciones.

  `install` retira la entrada de `settings.json` y borra el fichero de las instalaciones que lo
  tuvieran. Para que eso sea posible existe una lista de **scripts retirados**: sin ella, un script
  que deja de empaquetarse se vuelve inmortal, porque la limpieza de huérfanos se deriva de lo que
  hay en el directorio del paquete.

  Con esto, por defecto no queda registrado ningún hook `PreToolUse`.

### Fixed
- **El reintento del map-reduce reconoce el desborde de contexto venga como venga.** La detección
  comparaba contra tres literales de un proveedor y no cubría el `500` con
  `Context size has been exceeded.`, así que en ese caso el troceado se rendía en el primer trozo
  sin reintentar. Ahora se compara sin distinguir mayúsculas, por códigos de error conocidos o por
  la presencia de una palabra de «contexto» junto a una de «exceso». Y cuando el reintento se agota
  de verdad, el mensaje dice qué modelo se quedó corto y qué se puede tocar, en vez de devolver el
  error crudo del backend.

## [0.26.0] - 2026-08-18

### Added
- **`doctor` ve cuando una entrada MCP no puede autenticarse contra el daemon.** Check nuevo
  `service.daemon_auth`: si el puerto del daemon exige token, comprueba que las entradas en modo
  HTTP de los tres clientes lleven con qué entrar.

  Sale de una avería real. `install` sin `--web-token-env` escribe la entrada **sin** cabecera
  `Authorization` —y de paso borra la que hubiera—, así que contra un daemon con token Claude Code
  cae al flujo OAuth y responde «Dynamic Client Registration rejected (HTTP 401)»: las once tools
  desaparecen. Y `doctor` decía **todo a punto**, porque el check de andamiaje sólo comprueba que
  la entrada exista.

  Es la tercera vez que el mismo patrón muerde —2026-07-31, 2026-08-06 y ahora— y las tres el
  diagnóstico miraba por un camino distinto del roto. El check nuevo es hermano de
  `service.credential` un piso más arriba: aquel mira la puerta del **backend** y este la del
  **daemon**, que se cierran por separado.

  Reconoce las tres formas en que `install` escribe la autenticación (`headers.Authorization` en
  Claude Code y opencode, `bearer_token_env_var` en Codex), no cuenta las entradas `stdio` —de
  esas ya avisa `service.credential`— y avisa aparte, redactado como sospecha y no como veredicto,
  cuando la cabecera referencia una variable que este proceso no ve: el entorno de `doctor` es un
  testigo del que verá el cliente, no una prueba.

## [0.25.0] - 2026-08-18

### Added
- **El panel dice quién delegó.** Cada línea del log de uso lleva ahora el nombre del cliente MCP
  que pidió la llamada, y `/api/stats` trae el desglose por cliente. El KPI de ahorro es
  acumulativo y no distinguía un mes de smoke tests de un mes de trabajo real: en la medición del
  3-ago las 20 líneas de una prueba sólo se separaron cruzando a mano contra los transcripts de
  Claude Code, algo que el panel no puede hacer. Las líneas anteriores a este cambio, y las que no
  vienen de una sesión MCP, caen en «desconocido» —casilla propia, ni repartidas ni descartadas—.

  La identidad viaja en un `ContextVar` que el middleware fija antes de ceder el paso al handler.
  Que sobreviva al salto al threadpool (las tools son síncronas y el SDK las corre allí) se midió
  antes de diseñarlo, y que llegue con el SDK real por medio se comprueba levantando el daemon y
  mirando la línea que queda en disco.

- **La tarjeta de hooks muestra la puntería del hook de lectura**: de todas las lecturas que vio,
  en cuántas avisó y por qué se calló en el resto (`codigo`, `acotada`, `pequeno`). Es lo que
  faltaba para que el defecto que costó tres semanas —el hook apuntando a código— fuera visible
  desde la interfaz y no sólo desde un script. Los eventos anteriores al PR #146, que no traen el
  motivo, cuentan como «sin registrar» en vez de recibir una razón que nunca tuvieron.

  Sigue sin mostrarse ninguna tasa de conversión: nada enlaza una sugerencia con la delegación que
  vino después, y presentarlo como un dato sería inventar la correlación.

### Security
- **`cryptography` sube de 49.0.0 a 50.0.0**, que cierra la alerta `high` de Dependabot: un
  oráculo de Bleichenbacher distinguible por errores y por tiempos al descifrar PKCS#7
  `EnvelopedData`. Entra como transitiva por `pyjwt[crypto]` y el paquete no descifra PKCS#7, así
  que la vía no era explotable aquí; se actualiza igual.

### Changed
- **Dependencias al día**: `uvicorn` 0.52.0 → 0.52.3, `platformdirs` 4.11.0 → 4.11.3, `filelock`
  3.32.2 → 3.32.3, y en desarrollo `ruff` 0.16.1 → 0.16.3 y `pre-commit` 4.6.1 → 4.6.2. Los seis
  bumps van en un solo cambio y no en cinco PRs encadenados, porque cada uno toca `uv.lock` y
  mezclarlos de uno en uno hace que los demás conflicten. Auditados con Socket: todos los
  `depscore` por encima de 93.
- **El hook de lectura sólo avisa de lo que de verdad se puede delegar.** Medido sobre 14 días de
  uso real (49 sesiones, 1 579 lecturas, 10 153 eventos de telemetría): el hook avisaba en 572 de
  852 lecturas y **sólo 29 apuntaban a una transformación global**. Las otras eran código que hay
  que leer literal para editarlo (562 lecturas), franjas pedidas a propósito con `offset`/`limit`
  (542) y archivos medianos. La conversión de esas 1 409 sugerencias fue **cero**, y no por la
  redacción del aviso: un control con `claude -p` mostró que el modelo delega solo cuando la tarea
  es una transformación global, con hook y sin él. El problema era el ruido — un aviso que acierta
  el 5 % enseña a ignorarlo y se lleva por delante los casos en que tenía razón.

  Ahora se calla ante código, ante lecturas acotadas, y los umbrales por defecto suben de 8/32 KB
  a **32/100 KB**. Sobre las mismas 852 lecturas reales: de 572 avisos a **29**.

- **La telemetría registra la extensión del archivo (`ext`) y el motivo del descarte.** Sin ese
  dato nadie podía ver que el hook llevaba tres semanas apuntando a código: el log guardaba
  tamaño y banda, pero no qué se estaba leyendo. La extensión se acota a 12 caracteres
  alfanuméricos y se descarta si no lo es; el log sigue sin guardar rutas ni nombres de archivo.
  Los descartes se registran en vez de callarse, porque sin denominador no hay puntería que medir.

## [0.24.0] - 2026-08-04

### Fixed
- **`local_commit_msg` deja de redactar el mensaje sobre el principio del diff.** Era la única tool
  de reducción que seguía truncando la entrada: por encima de 20 000 caracteres, el resto se
  descartaba con un aviso de apariencia inocua. Medido sobre un diff de 164 585 chars y 44
  archivos, el modelo veía 20 027 —siete archivos, todos de `.sdd/`— y devolvía `chore: update
  GitHub Actions pages artifact version`, o sea el primer archivo por orden alfabético de rutas.
  Como `git diff` sale ordenado por ruta, lo que se perdía era justo `src/` y `tests/`.

  Ahora el diff entra entero: se parte **por archivo** —un splitter nuevo, porque un diff no tiene
  headers Markdown y caía a párrafos, cortando hunks por la mitad—, cada trozo produce sus notas y
  el mensaje se redacta sobre ellas más el **inventario completo** del diff, que se calcula sin
  modelo porque es un conteo y no un juicio. La salida dice sobre cuántos archivos y cuántos
  caracteres se redactó, para que procesar de menos no vuelva a ser invisible.

- **Un trozo que no cabe en el contexto del modelo ya no aborta la operación.** Los presupuestos de
  troceado están en caracteres y el límite del modelo en tokens, y la relación entre los dos
  depende del contenido: la prosa de un `.md` da 3,12 chars/token y `uv.lock` —hashes y URLs— da
  1,57. El mismo presupuesto que sirve para un documento revienta con otro. Cuando el backend
  responde `exceed_context_size`, el trozo se parte y se reintenta, así que el presupuesto en
  caracteres pasa a ser una estimación inicial y quien manda es el límite real. Afecta también a
  `local_summarize` y `local_lint_summary`, donde el defecto estaba latente desde su migración.

## [0.23.0] - 2026-08-03

### Added
- **El dashboard ya no pide el token en cada visita.** Con `LOCAL_DELEGATE_WEB_TOKEN` puesto, la
  única credencial que un navegador sabe mandar sin una pantalla de login es Basic, y Basic solo lo
  recuerda mientras la ventana vive y por origen exacto: el panel volvía a pedir el secreto al
  reabrir el navegador, y otra vez al entrar por `localhost` en lugar de por `127.0.0.1`. Eso no es
  una molestia sin consecuencias — una protección que hay que teclear varias veces al día es una
  protección que se acaba quitando.

  Ahora, al entrar con Basic el daemon devuelve una **cookie de sesión** de un año que se renueva
  sola en cada visita. Sin estado en el servidor y sin fichero de sesiones que mantener: la cookie
  lleva su propia caducidad firmada con HMAC-SHA256 **usando el token como clave**, de donde salen
  tres propiedades gratis — no se puede fabricar sin conocer el token, no se puede alargar a mano
  porque la fecha va dentro de lo firmado, y **rotar el token invalida todas las sesiones vivas**.

  Es `HttpOnly` y `SameSite=Lax`, que es lo que aquí hace de protección CSRF, y no lleva `Secure` a
  propósito: el daemon habla HTTP plano aunque el TLS lo ponga un proxy delante (`tailscale
  serve`), y con `Secure` se rompería el acceso directo por `http://<ip>`. Solo la recibe quien
  entra por Basic; un cliente MCP o el CLI mandan Bearer en cada llamada y no tienen dónde
  guardarla.

  `LOCAL_DELEGATE_WEB_SESSION_DAYS` cambia la duración y `0` la desactiva, dejando la puerta como
  estaba. Quien no tenga token configurado no nota nada: sin token no hay middleware.

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

