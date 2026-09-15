# Implementation plan: Delegacion precisa y fiable: deteccion de fallos, enrutado por reglas, catalogo de modelos y respaldo

## Approach

La spec tiene cuatro fases. **F0, F1 y F2 se detallan tarea a tarea**; **F3 sigue siendo un bloque
con entrada, salida y condicion de replanificacion**, porque detallar sus cadenas ahora seria
inventarlas sobre unos roles que F2 todavia no ha fijado.

**Historial del gate `plan`:** se aprobo primero sobre F0 y F1 (2026-09-12), con F2 como bloque
porque dependia de una accion fisica del usuario —limpiar RAM y activar «Prefer No Sysmem
Fallback» en el panel de NVIDIA— que ya esta hecha. Paso despues con las tareas 12 a 21 de F2 y su
protocolo (`protocolo-f2.md`). **Vuelve ahora (2026-09-15) con F3 detallado en las tareas 22 a 30**,
cerrada la tarea 21.

Tres decisiones de diseno gobiernan el resto:

1. **La clasificacion de fallos sale de `server.py` a un modulo propio y puro** (`fallos.py`, al
   lado de `preguntas.py` y `clients.py`). `server.py` tiene 2 335 lineas y mezcla las tres capas
   que F3 necesita separadas: clasificar, decidir el salto y llevar el estado de salud. F0 entrega
   solo la primera, sin red y sin estado, para que se pueda probar entera con dobles.
2. **El hook no puede preguntarle al backend si esta vivo en cada lectura.** REQ-F1-10 exige que el
   bloqueo se caiga cuando no hay a donde delegar, pero los hooks son stdlib pura, corren en cada
   `Read` y no pueden importar el paquete. Un ping HTTP por lectura es latencia en el camino
   caliente. La via es un **fichero de salud** que escribe el lado del servidor y que el hook lee:
   si falta, esta viejo o dice «caido», **no bloquea**. Sin fichero legible el comportamiento es no
   bloquear, nunca al reves.
3. **Falso negativo antes que falso positivo.** En el hook de shell (REQ-F1-9), solo se bloquean
   formas simples e inequivocas de lectura completa; cualquier comando con tuberia, redireccion,
   sustitucion o varios verbos se deja pasar y se cuenta. Bloquear un comando mal parseado es
   justo el fallo que haria apagar el experimento.

Orden: F0 primero porque no depende de ninguna pregunta abierta y deja la clasificacion que F1
necesita para REQ-F1-10 y F3 para todo. Dentro de F1, la telemetria y el apagado van **antes** que
el bloqueo: encender un bloqueo sin poder medirlo ni apagarlo repite el error de las cuatro
mediciones anteriores.

## Ordered tasks

### F0 - Deteccion de fallos

1. **Modulo puro de clasificacion**
   - Files or modules: `src/local_delegate/fallos.py` (nuevo), `tests/test_fallos.py` (nuevo)
   - Requirements covered: REQ-F0-4, REQ-F0-5, y las clases que consumen REQ-F0-1 y REQ-F0-2
   - Detalle: una funcion que recibe el resultado HTTP o la excepcion y devuelve la clase
     (`endpoint`, `peticion`, `capacidad_o_carga`, `timeout_lectura`, `configuracion`, `modelo`,
     `sin_clasificar`). Sin red, sin estado, sin decidir reintentos. Las dos clases de `ReadTimeout`
     nacen aqui aunque F0 aun no sepa distinguirlas siempre: sin patron aplicable, `capacidad_o_carga`.
   - Verification: un test por clase **con control positivo** (un caso que la produce y otro
     parecido que no), y un test de que una variante desconocida cae en `sin_clasificar`, nunca en
     `modelo`. Antes de dar por bueno cada test, comprobar **que assert dispara**.
   - Rollback or recovery: modulo nuevo sin consumidores hasta la tarea 2; borrarlo no afecta a nada.

2. **`_post_chat` usa el clasificador**
   - Files or modules: `src/local_delegate/server.py:596-663`, `tests/test_core.py` o
     `tests/test_fallos_integracion.py` (nuevo) con `tests/backend_mock.py`
   - Requirements covered: REQ-F0-1, REQ-F0-2, REQ-F0-6
   - Detalle: `choice["message"]["content"]` nulo deja de reventar (hoy `AttributeError` fuera del
     `except (KeyError, IndexError, ValueError)`); `ConnectTimeout` y `ReadTimeout` dejan de caer en
     `http_error`; `ConnectTimeout` entra al camino de `ConnectError`, con autoarranque y pregunta.
   - Verification: test con `{"content": null}` y control positivo con contenido real; test de que
     `ConnectTimeout` ofrece arrancar el backend y sigue siendo opt-in; test de que `ReadTimeout`
     **no** dispara autoarranque. Reproducir primero los tres defectos con el doble de `httpx2` del
     research y ver los tests **rojos** antes de tocar `server.py`.
   - Rollback or recovery: el cambio es local a una funcion; revertir el commit devuelve el
     comportamiento de hoy.

3. **`retry_exhausted`: decidir por ejecucion, no por lectura**
   - Files or modules: `src/local_delegate/server.py:659-663`, `verification.md`
   - Requirements covered: REQ-F0-3
   - Detalle: instrumentar la linea final del bucle `for attempt in (1, 2)` y ejercitar **todos** los
     caminos de salida, no solo el de `ConnectError` que ya se probo. Si ningun camino la alcanza,
     se elimina; si alguno la alcanza, se le pone test y se queda.
   - Verification: la evidencia de cual de las dos cosas procede, anotada en `verification.md` con
     el metodo. Un no-resultado no vale si no se comprueba que la instrumentacion podia disparar.
   - Rollback or recovery: si se elimina y aparece un camino nuevo, el clasificador de la tarea 1 ya
     devuelve `sin_clasificar` por defecto: no hay silencio.

### F1 - Precision de la delegacion

4. **Retirar las variables huerfanas del mecanismo suspendido**
   - Files or modules: `src/local_delegate/config.py:186-195`, `docs/wiki/`, `CHANGELOG.md`
   - Requirements covered: REQ-F1-4 (la parte que si se puede cerrar hoy)
   - Detalle: `LD_HOOK_OUTPUT_STATS`, `LD_HOOK_OUTPUT_UMBRAL_KB`, `LD_HOOK_OUTPUT_MIN_MUESTRAS` y
     `LD_HOOK_OUTPUT_PROPORCION` se quedaron **sin un solo consumidor** cuando la 0.27.0 retiro
     `output_policy.py` y `output_stats.py`; su comentario sigue explicando por que las lee un hook
     que ya no existe. Se retiran con el mismo cuidado de siempre: comprobar `doctor`, la wiki y el
     README antes de dar el paso.
   - Verification: busqueda por programa de consumidores (no a ojo) antes y despues;
     `tests/test_aislamiento_entorno.py` en verde, que es el guardian que se autoalimenta de las
     lecturas de `config.py`.
   - Rollback or recovery: son declaraciones sin efecto; reponerlas es un revert limpio.

5. **`hook_common`: camino que bloquea, identificador de correlacion y procedencia**
   - Files or modules: `src/local_delegate/resources/hooks/hook_common.py`, `tests/test_hook_common.py`
   - Requirements covered: REQ-F1-5, REQ-F1-6, base de REQ-F1-1
   - Detalle: junto a `emit()` (consultivo) nace `deny()`, que devuelve `permissionDecision: "deny"`
     con su motivo en `hookSpecificOutput`. Todo evento pasa a llevar un **identificador propio**,
     la **version del script** y el **momento de arranque de la sesion**. El identificador es lo que
     permitira cruzar `~/.claude/hooks/telemetry.jsonl` con `%LOCALAPPDATA%/local-delegate/usage-*.jsonl`
     sin trabajo manual.
   - Verification: tests del payload de `deny()` y de `emit()`; test de que el identificador que
     emite el hook es el que despues aparece en el evento de la tool (tarea 9). La telemetria sigue
     sin escribir prompts, comandos ni rutas: test de que el payload no los lleva.
   - Rollback or recovery: `deny()` es aditivo; mientras ningun hook lo llame, nada cambia.

6. **Fichero de salud del backend, para que el bloqueo se pueda caer**
   - Files or modules: `src/local_delegate/server.py` o `daemon.py` (escritura),
     `resources/hooks/hook_common.py` (lectura), tests nuevos
   - Requirements covered: REQ-F1-10
   - Detalle: el lado del servidor deja una marca con el estado del backend y su hora. El hook la
     lee con coste de un `stat` mas una linea. **Ausente, vieja o ilegible = no bloquear.** Los
     modelos en enfriamiento de F3 se leeran de la misma marca cuando F3 exista.
   - Verification: test con marca fresca de «sano» (bloquea), marca de «caido» (no bloquea), marca
     vieja (no bloquea), fichero ausente (no bloquea) y fichero corrupto (no bloquea). Medir el
     coste anadido por lectura y anotarlo: si el hook encarece el camino caliente, se nota aqui.
   - Rollback or recovery: sin marca, el sistema se comporta como si el backend estuviera caido, que
     es el lado seguro.

7. **Politica por extension y bloqueo en el hook de `Read`**
   - Files or modules: `src/local_delegate/resources/hooks/suggest_delegate_read.py`,
     `tests/test_hook_recipes.py` y tests nuevos
   - Requirements covered: REQ-F1-1, REQ-F1-2, REQ-F1-3, REQ-F1-11
   - Detalle: tres tratos segun REQ-F1-2 (`.md`/`.txt` bloquean; `.json`/`.csv`/`.log`/`.yaml` e
     imagenes solo avisan; lo demas como hoy, que es lista negra de codigo y no lista blanca). El
     mensaje del bloqueo nombra la tool que si sirve y **el escape** para leer de verdad, y el uso
     del escape se registra. El apagado se lee **en cada invocacion** desde un fichero que el
     usuario pueda tocar sin cerrar la sesion: una variable de entorno no vale, porque esta medido
     que una sesion abierta hereda el entorno del lanzador.
   - Verification: un test por trato (`.md` bloquea, `.json` avisa, imagen avisa, `.py` calla,
     lectura acotada calla); test de que el apagado surte efecto sin relanzar nada; test de que con
     el backend marcado caido no bloquea (tarea 6). El bloqueo nace **apagado por defecto**.
   - Rollback or recovery: apagado en caliente, mas `install` sin el flag correspondiente.

8. **Cerrar la lectura completa por shell, y medir lo que no se cierra**
   - Files or modules: `src/local_delegate/resources/hooks/suggest_delegate_shell.py` (nuevo),
     `src/local_delegate/install.py:58-61` y `:293` (registro, `_SCRIPT_NAMES`), tests nuevos
   - Requirements covered: REQ-F1-9
   - Detalle: hook `PreToolUse` con matcher `Bash` (y PowerShell, que es el shell primario de esta
     maquina) que reconoce **solo** formas simples e inequivocas de lectura completa: `cat X`,
     `head X` sin `-n`, `Get-Content X` sin `-TotalCount`/`-Tail`, `type X`, `rtk read X`. Con
     tuberia, redireccion, sustitucion, varios comandos encadenados o cualquier duda: **no bloquea**
     y cuenta el caso. Las tools de lectura de otros MCP se registran con su propio matcher y **no**
     se bloquean (decision P-6).
   - Verification: tests de forma simple (bloquea), con tuberia (no bloquea, cuenta), acotada
     (`sed -n`, `head -n`, `-TotalCount`: no bloquea), y de tool MCP ajena (cuenta, no bloquea).
     Prueba **end-to-end de `install` en Windows**, con los cuatro flags de esta maquina: la regla
     del repo es no publicar un hook sin verlo dispararse instalado de verdad.
   - Rollback or recovery: `install` desregistra; si el script se retira algun dia, va a
     `_SCRIPTS_RETIRADOS` o su copia en `~/.claude/hooks/` se vuelve inmortal.

9. **Correlacion de punta a punta: ofrecido, aceptado, rechazado**
   - Files or modules: `src/local_delegate/server.py:429-450` (`_log_event`), las tools `local_*`,
     `src/local_delegate/web/` (panel y su espejo JS), tests
   - Requirements covered: REQ-F1-5
   - Detalle: las tools aceptan el identificador que emitio el hook y lo escriben en su evento. El
     panel pasa a poder responder «de N bloqueos, cuantos acabaron en delegacion». Si el dato vive
     en dos sitios (Python y el espejo JS), se cambian **los dos** y lo cubre el test de paridad,
     que es el defecto recurrente de este repo.
   - Verification: test de que el identificador del hook llega al evento de la tool; test del panel
     y test de paridad Python/JS; una consulta reproducible que responde la pregunta de adopcion sin
     cruzar ficheros a mano.
   - Rollback or recovery: campo aditivo en el log; un evento sin identificador se comporta como hoy.

10. **Medir antes de encender: la guarda «acotada» y el criterio de la quinta medicion**
    - Files or modules: `verification.md`, script de consulta en `scripts/`
    - Requirements covered: REQ-F1-8, REQ-F1-12
    - Detalle: con el criterio ya escrito en la spec (mismo fichero leido entero, o en tres o mas
      franjas, dentro de la misma sesion), medir cuantos de los 242 silencios por «acotada»
      convenia delegar. Y dejar escrito **antes** de encender el bloqueo: ventana, denominador y el
      resultado que retira el cambio.
    - Verification: el criterio y la ventana en `verification.md` con fecha **anterior** al
      encendido. Toda medida anota cuando arranco la sesion y con que version (REQ-F1-6): una
      sesion abierta hereda el umbral viejo y contamina la muestra, como ya paso con 14 lecturas.
    - Rollback or recovery: es medicion, no cambia comportamiento.

11. **Cierre de F1: instalacion, doctor y documentacion**
    - Files or modules: `src/local_delegate/install.py`, `checks.py`, `doctor.py`, `CHANGELOG.md`,
      `README.md`, `docs/wiki/`
    - Requirements covered: REQ-F1-7 (dejar escrito que Claude Desktop queda fuera), cierre de las
      demas
    - Detalle: registrar los hooks nuevos, comprobar que `doctor` los ve y que la wiki dice la
      verdad. Una release toca **tres** sitios: CHANGELOG, README y `docs/wiki/`.
    - Verification: `install` end-to-end en Windows; `doctor` en verde; los guardianes de la wiki y
      de la tabla del doctor en verde.
    - Rollback or recovery: `install` es idempotente y reinstalar deja exactamente lo esperado.

### F2 - Catalogo de modelos

Protocolo completo en `protocolo-f2.md` (entorno, controles, corpus, contexto, puntuacion, regla de
decision y bitacora). Aqui van solo las tareas. **Ninguna medida se toma antes de la tarea 18**, y la
18 no empieza hasta que la sesion en curso libere la maquina (decision del usuario, 2026-09-12).

Orden: instrumentacion, corpus, controles y por ultimo la medida. Las cuatro veces que este repo
midio algo sin comprobar antes el instrumento, lo roto era la prueba.

12. **Verificar por ejecucion que la sonda puede existir**
    - Files or modules: ninguno; scratchpad y `protocolo-f2.md` §3.4
    - Requirements covered: prepara REQ-F2-3
    - Detalle: las cuatro hipotesis de §3.4 estan **sin comprobar**: que los contadores
      `\GPU Process Memory(pid_*)\Dedicated Usage` y `Shared Usage` existen con ese nombre y se leen
      sin elevar; que `PrivateMemorySize64` sale por `ctypes` (`GetProcessMemoryInfo` ->
      `PROCESS_MEMORY_COUNTERS_EX.PrivateUsage`) sin dependencias nuevas; que `typeperf` transmite en
      continuo a 1 Hz **y se puede relanzar cuando llama-swap cambia el PID** (un `typeperf` ya
      arrancado enumera instancias al inicio y no ve el PID nuevo); y que `--load-mode none` es
      practicable. En este repo un pendiente es una hipotesis: 7 de 18 cayeron en la ultima
      auditoria, siempre con la observacion correcta y la causa inventada.
    - Verification: las cuatro contrastadas contra procesos reales, con la salida cruda pegada en el
      protocolo. La cuarta con el control de CP-2b: cargar un MoE con `-ncmoe 0` y con `-ncmoe 12` y
      ver **subir** la RAM privada en el segundo. Si no sube, el contador no ve los expertos y el
      metodo se cambia **aqui**, no despues de escribir la sonda encima.
    - Rollback or recovery: no toca el repo; el resultado es una nota en `protocolo-f2.md`.

13. **Sonda de recursos por proceso, dentro del runner**
    - Files or modules: `src/local_delegate/benchmark.py`, `scripts/sonda_recursos.py` (nuevo),
      `tests/test_sonda.py` (nuevo)
    - Requirements covered: REQ-F2-3, y la regla de anulacion de REQ-F2-1
    - Detalle: muestrea de un PID la RAM privada **y el working set** —los dos, siempre, de la misma
      llamada a `GetProcessMemoryInfo` (P-11: H4 quedo sin verificar en la tarea 12 y CP-2b decide
      despues cual se publica, sin tocar codigo)—, la VRAM dedicada y la **VRAM compartida**, filtrando
      la instancia por el LUID de la NVIDIA (`pid_<pid>_luid_<luid>_phys_0`, §3.4). `typeperf` emite
      `-1` cuando el PID muere: eso es «sin muestra» y reresolver, no un cero. Va
      **dentro de `benchmark.py`**, no en un modulo nuevo del paquete: un modulo publicado arrastra
      sus tres sitios de documentacion por una sonda Windows-only de un solo uso. `scripts/` lleva
      solo el envoltorio para medir `llama-bench`, que no pasa por el runner. Lectura **sincrona
      antes y despues de cada peticion** ademas del flujo continuo, para que una corrida de 53
      caracteres no se quede sin ninguna muestra (§3.3). El PID se reresuelve al cambiar de modelo.
    - Verification: test de que el parseo de `typeperf` saca los dos contadores de la instancia
      correcta habiendo varias; test de que un PID que desaparece da «sin muestra» y no una
      excepcion; test de que una corrida con **cero muestras** se marca para anular, no se publica
      vacia; y **control positivo**: numeros distintos para dos procesos de tamano distinto. Marca de
      plataforma declarada: `ctypes` y `typeperf` no existen en Ubuntu ni macOS y el CI corre en los
      tres — este repo ya tuvo un test que fallo **solo en macOS**.
    - Rollback or recovery: el muestreo es aditivo; sin el, el runner escribe los mismos campos vacios.

14. **Congelar las fuentes y construir el corpus v2**
    - Files or modules: `scripts/construir_corpus.py` (nuevo),
      `benchmarks/catalogo-2026-09/{cases.json,fuentes/}` (generado), `tests/test_corpus.py` (nuevo)
    - Requirements covered: REQ-F2-2
    - Detalle: el constructor lee el log real (`%LOCALAPPDATA%\local-delegate\usage-*.jsonl`),
      **emite los conteos** de §4.2 y arma los 17 casos de §4.4. Las fuentes se **copian** a
      `fuentes/` y se hashea la copia: dos casos apuntaban a `CHANGELOG.md` y a
      `docs/wiki/Backend-versions.md`, ficheros que la tarea 16 edita, asi que un hash contra la ruta
      viva se invalida solo. **Descarta toda fuente fuera del repo**: el log guarda rutas del vault y
      de otros proyectos del usuario. Congela tambien la **imagen de control** de CP-3 (`docs/assets/dashboard.png` en `bcbe39f`), que es
      una fuente mas y no un artefacto suelto: con su hash y su `procedencia`, porque un control que
      consume algo que ninguna tarea produce no esta cerrado — ya paso una vez con las referencias de
      CP-4. Marca `procedencia` (`congelado`, `generado`, `reconstruido` o `inventado`): 50 de los
      146 eventos son `inline` y de esos no hay contenido, solo tamano (decia 56: eran de los 152,
      el mismo cruce de denominadores de §11; lo conto el constructor).
    - Verification: test de que un `source_sha256` que no cuadra hace **fallar** la carga en vez de
      correr otro contenido con el mismo id; test de que ninguna ruta del usuario llega al corpus
      versionado; y **las dos comprobaciones que de verdad pueden fallar**, las dos calculadas contra
      el codigo de produccion y no contra la tabla que uno mismo escribio: (a) el `role` de cada caso
      coincide con el modelo que el enrutado real elegiria para ese tamano (`LONG_INPUT_CHARS`,
      `max_chars_for`), y (b) **cada caso de calidad cabe en una sola llamada** segun la tabla de
      troceado de §4.3 —`local_translate` trocea siempre a 3 500, `summarize`/`lint`/`commit_msg`
      por encima del `MAX_CHARS` de su modelo—. La (b) es la que habria cazado el `traducir-14k` que
      se colo en la version anterior. Los conteos del log los emite el programa: contar a mano mezclo
      dos denominadores (152 contra 146) y de ahi salio una decision equivocada sobre el rol `fast`.
    - Rollback or recovery: corpus y fuentes son ficheros generados y versionados; se regeneran.

15. **Las diez respuestas de referencia de CP-4**
    - Files or modules: `benchmarks/catalogo-2026-09/cases.json` (campos `reference_ok` /
      `reference_bad`), `protocolo-f2.md` §CP-4
    - Requirements covered: habilita CP-4, que valida la puntuacion de REQ-F2-2
    - Detalle: cinco casos elegidos para cubrir cada senal del puntuador **que se pueda ejercitar con
      texto** —cobertura, termino prohibido, formato JSON y normalizacion Unicode—, con una respuesta
      correcta y una deliberadamente mala de la misma longitud y los hechos cambiados. Cinco y no
      diecisiete: el control valida el puntuador, no el corpus. **`truncado` no entra**: no es una
      propiedad del texto sino del `finish_reason` del backend, y ninguna pareja escrita a mano lo
      dispara; se prueba inyectandolo en un test del puntuador (tarea 16). Tarea propia porque la
      version anterior del plan las consumia en CP-4 sin que ninguna tarea las produjera.
    - Verification: que las cuatro senales de texto queden cubiertas lo comprueba un test, no yo
      leyendo la tabla; y que cada pareja se diferencie **solo** en la senal que quiere ejercitar, o
      CP-4 no podra decir por que separo.
    - Rollback or recovery: son datos del corpus; se reescriben.

16. **Runner: corpus v2, puntuacion, multimodal y estado termico**
    - Files or modules: `src/local_delegate/benchmark.py`, `tests/test_benchmark.py`,
      `docs/wiki/Backend-versions.md`, `README.md`, `CHANGELOG.md`
    - Requirements covered: REQ-F2-1, REQ-F2-2, REQ-F2-3
    - Detalle: cargar `schema_version: 2` y **dejar de aceptar el 1** (ningun REQ-F2 pide repetir la
      prueba de julio; su corpus se conserva y el cargador viejo esta en git); contenido literal
      desde `fuentes/` en vez de `materialize_case()`; los cinco cambios de puntuacion de §4.7,
      incluido **guardar que componente puso la calidad a 0**, sin lo cual CP-4 no se puede evaluar;
      **payload multimodal con `image_url`**, porque hoy el mensaje es texto puro
      (`benchmark.py:214-227`) y sin eso **el rol `vision` no se puede medir en absoluto**;
      `reasoning_effort` con valor **«apagado»** —el CLI solo acepta `low|medium|high`— y con
      precedencia caso > modelo; `rechazo_por_contexto` como clase propia (§3.5); y corregir
      `thermal_state`, que hoy marca fria la primera corrida **de cada caso**
      (`benchmark.py:269`) cuando solo lo es la primera tras cargar el modelo — mal etiquetado infla
      la banda de ruido y vuelve la regla de decision imposible de superar por un artefacto.
    - Verification: test de que una respuesta con acentos correctos ya **no** pierde cobertura (el
      defecto literal de julio, reproducido en rojo antes de arreglarlo); test de que un termino
      prohibido pone la calidad a 0 aunque la cobertura sea 1, con control positivo; test de que una
      corrida truncada no cuenta como mala calidad; test de que un caso `media_type: imagen` produce
      un payload con `image_url` y uno de texto no; test de que `rechazo_por_contexto` no se confunde
      con un fallo de calidad ni con `descartada`; test de que `truncado` se ejercita **inyectando
      `finish_reason: "length"`**, que es la senal que CP-4 no puede cubrir con texto; test de que
      «apagado» llega de verdad al payload y de que la precedencia caso > modelo se respeta. En cada
      uno, comprobar **que assert dispara**.
    - Rollback or recovery: superficie publicada — la release toca **tres** sitios (CHANGELOG, README
      y `docs/wiki/`), y `Backend-versions.md` es justo la pagina del runner. Retirar el schema v1 es
      el unico cambio que rompe: se anota como breaking en el CHANGELOG.

17. **Agregacion, regla de decision y hoja de revision a ciegas**
    - Files or modules: `scripts/analizar_benchmark.py` (nuevo), `scripts/hoja_revision.py` (nuevo),
      `tests/test_analisis_benchmark.py` (nuevo)
    - Requirements covered: REQ-F2-1 (mediana), REQ-F2-4, REQ-F2-6
    - Detalle: medianas y dispersiones por caso, banda de ruido por rol, el criterio de tanda no
      concluyente de §6, y las tres condiciones de §7 aplicadas por el programa. La hoja de revision
      saca las respuestas **barajadas y con el modelo oculto**: una revision que sabe de quien es la
      respuesta puntua la expectativa. En `scripts/` y no en el CLI porque son analisis de un solo uso
      de este SDD, y el wheel no empaqueta `scripts/`.
    - Verification: cuatro pruebas de la regla — un candidato que gana por encima de la banda; uno que
      gana **dentro** de la banda (no sustituye); uno que empata (decide la velocidad); y **ninguno
      mejora**, con la salida diciendolo como resultado, no como error. Mas la **precedencia** de los
      dos desempates: candidato que pierde el sondeo de techo pero es mas rapido — manda el techo. Mas las dos condiciones que
      la version anterior no probaba: corrida anulada u OOM, y latencia un 50 % peor. Y la que de
      verdad importa: que con la granularidad real de la puntuacion —cobertura sobre pocos terminos,
      pasos de 1/N— la regla **pueda** declarar un ganador alguna vez. Un fixture con valores
      continuos y dispersion cero no discrimina ninguna regla de ruido, asi que esa comprobacion se
      corre **tambien sobre la salida real de CP-3** (tarea 19), que ya existe antes de la tanda: es
      la unica forma de saber si la regla puede disparar con los numeros de verdad.
    - Rollback or recovery: scripts sin consumidores en el producto.

18. **Entorno de medicion, CP-1, CP-2 y CP-2b**
    - Files or modules: `benchmarks/catalogo-2026-09/llama-swap-pruebas.yaml` (nuevo),
      `protocolo-f2.md` §1, §2 y §10
    - Requirements covered: REQ-F2-1
    - Detalle: b10909 en `D:\Projects\llms\llamacpp-b10909` y llama-swap v255 con config y puerto
      propios (`--cache-ram 1024 -np 1`); produccion no se toca. **El perfil «Prefer No Sysmem
      Fallback» se anade a la ruta nueva**: se guarda por ejecutable y el de b10909 no hereda nada.
      `%APPDATA%\llama.cpp\config.ini` lo lee b10909 **de forma global**, asi que se mira que tiene
      hoy —esta sin comprobar—, **se respalda** y se vacia. Se para el daemon, se comprueba que hay un
      solo `llama-server.exe` vivo y se anota la hora UTC de inicio y la duracion estimada.
    - Verification: **CP-1 tiene veto**: un modelo que no quepa debe dar error de memoria en segundos
      y uno que quepa debe cargar normal — sin la segunda mitad, un CP-1 «pasado» podria ser solo un
      build roto. **CP-2**: la sonda da numeros distintos con un 2B y con un 14B y se mueven al
      descargar; en la misma pasada se averigua **que mide** `llamaswap_memory_used_bytes`, el
      candidato a repetir el error de julio. **CP-2b**: con un MoE, `-ncmoe 12` sube la RAM privada
      frente a `-ncmoe 0`; si no sube, el contador privado no ve los expertos y se publica el working
      set junto al privado diciendo cual es cual (o se cambia el `--load-mode`); la sonda ya guarda
      los dos desde la tarea 13, asi que el resultado no reabre codigo (P-11).
    - Rollback or recovery: al cerrar se **restaura** el `config.ini` respaldado y se **retira** el
      perfil del driver anadido a la ruta nueva; borrar `llamacpp-b10909` y la config de pruebas
      devuelve la maquina a como estaba. Produccion se reanuda arrancando `LocalDelegateDaemon`.

19. **CP-3 y CP-4: que el corpus discrimine y el puntuador separe**
    - Files or modules: `benchmarks/catalogo-2026-09/cases.json`, `protocolo-f2.md` §2
    - Requirements covered: REQ-F2-2, y el escenario «el caso no discrimina»
    - Detalle: CP-3 con `qwen35-2b` y `qwen25-coder-14b`, **3 corridas por caso** y no una: sin
      dispersion no hay con que separar una diferencia real del ruido que el propio protocolo da por
      existente. **`vision` no se pilota asi**: ninguno de los dos modelos es multimodal, asi que sus
      **dos** casos usan un **control de entrada** con `qwen3-vl-8b` —la imagen correcta contra
      `dashboard.png` del commit `bcbe39f`, el mismo dashboard con otras cifras—, que ademas ejercita
      el payload multimodal de punta a punta. Pasa si **los dos casos bajan** por encima de su banda;
      y que bajen **no** prueba que el caso separe dos modelos, cosa que se escribe junto al veredicto
      del rol. CP-4 con las diez referencias de la tarea 15.
    - Verification: CP-3 pasa si en cada rol con mas de un caso **al menos uno separa por encima de
      su banda de ruido**, y ademas **informa por rol si separa el agregado**, que es lo que la §7
      usa para decidir: `mechanical` tiene tres de sus cinco casos en 42-56 caracteres, donde dos
      modelos competentes daran 1,0 los dos, y un agregado dominado por casos en techo produciria
      «nadie mejora al vigente» por composicion del corpus, indistinguible del hallazgo legitimo. Los
      casos en techo quedan fuera del promedio de su rol y se anota cuantos entraron. No se exige que ningun caso empate: dos modelos competentes daran
      cobertura 1,0 en los faciles, y eso es techo, no falta de discriminacion. Si un rol no separa,
      **hay que mirar las salidas** y decidir cual de las dos causas es —el corpus no lo recoge, o la
      premisa de cual modelo es mejor era falsa, que en traducir o clasificar es muy posible—; solo
      la primera justifica reescribir el caso. CP-4 pasa si separa cada pareja **y por la senal
      correcta**: si la mala cae por `json_valid` cuando el defecto plantado era un hecho falso,
      acierta por la razon equivocada.
    - Rollback or recovery: solo cambia el corpus, que se regenera con la tarea 14.
    - Estado (2026-09-15): **hecha**, tras cuatro pilotos y P-15 (`protocolo-f2.md` §2 y §10.1). Lo
      que obligo a cambiar respecto a este texto: 5 corridas y no 3, banda por caso, temperatura de
      produccion, sonda que relanza `typeperf`, y **cada caso con su juez**: metricas objetivas donde
      las hay y comparacion por pares a ciegas en el texto abierto, porque la cobertura de terminos
      no coincidio con el juicio humano (6 de 13).

20. **La tanda: contexto, linea base, barrido, calidad y techo**
    - Files or modules: `benchmarks/catalogo-2026-09/resultados/*.jsonl`, `protocolo-f2.md` §10
    - Requirements covered: REQ-F2-1, REQ-F2-2, REQ-F2-3, REQ-F2-6
    - Detalle: en este orden — fijar `n_ctx` y el presupuesto de KV por modelo y anotarlos en el
      registro de §5.2; linea base del catalogo **vigente sobre b10909** y en la misma tanda
      (REQ-F2-6: comparar sobre motores distintos no es comparar); barrido del punto de operacion
      **hasta la profundidad del caso mayor de cada rol** y con `-ncmoe` en 0/4/8/12/16 en los MoE,
      porque julio fijo `-ncmoe 12` sin barrer y perdio un 60 % de velocidad; tanda de calidad con
      **cada modelo corriendo solo los casos de su rol**, 3 corridas; y los dos sondeos de techo **solo
      con los modelos de `long` y `code`**, que son los roles cuyas tools trocean de verdad. `fast`
      sale de la tanda: cero casos y cero carga real (§4.4). Son ~214 peticiones al backend en total,
      y la duracion estimada se escribe en la bitacora **antes** de empezar.
    - Verification: el criterio de tanda no concluyente de §6 se aplica **antes** de agregar nada: mas
      de una corrida anulada de cada tres en un rol, un caso sin ninguna puntuacion valida, o
      `n_ctx`/`--load-mode` distintos entre vigente y candidato invalidan ese rol y obligan a
      repetirlo. Si `Shared Usage` crece, lo que se cae no es la corrida sino **CP-1 y todo el tramo
      desde el ultimo CP-1 en verde** (§3.2). Las corridas anuladas se anotan con su motivo: un
      descarte silencioso es indistinguible de un caso que no se corrio.
    - Rollback or recovery: la tanda no modifica el producto; solo escribe JSONL.
    - Preparacion (2026-09-14): P-13 y P-14 resueltas por el usuario y §1.1 y §1.4 del protocolo
      rehechos con lo medido (32 GB de RAM, no 62; RAM libre >= 17 GB; VRAM del adaptador en reposo
      <= 1 024 MiB). La tanda corre con `--load-mode none` y el runner guarda el pico de
      `privada − VRAM dedicada` por muestra; el presupuesto de uso diario (2 GB de VRAM y 8 GB de RAM
      de reserva) es solo informativo. Tras CP-3 son **5 corridas y ~350 peticiones**, no 3 y ~214
      (§5.2 del protocolo manda).
    - Estado (2026-09-15): **hecha** (`protocolo-f2.md` §7, «Resultado de la tarea 20»). `long` y
      `code` sustituyen (pares 15 a 0 cada uno, y los candidatos van al doble de velocidad),
      `mechanical` no cambia (todo en techo), `vision` caso a caso a favor de Gemma 4 12B. Lo que la
      tanda obligo a cambiar respecto a este texto: 5 corridas; techo en config aparte con la misma
      `--label`; razonamiento apagado en los candidatos; umbral de `Shared Usage` 1 024 MiB; latencia
      sobre casos comunes; perfil del driver tambien para `llama-bench.exe`; y el LUID de la GPU
      resuelto en cada invocacion porque un reinicio lo reasigna.

21. **Asignacion de roles, y que se transfiere a produccion**
    - Files or modules: `verification.md`, `protocolo-f2.md` §9 y §10
    - Requirements covered: REQ-F2-4, REQ-F2-5, REQ-F2-6
    - Detalle: revision humana a ciegas, y despues la asignacion de rol con el dato que la sostiene.
      Dos salidas ya previstas que **son resultados, no fracasos**: un rol sin candidato ganador se
      queda como esta (REQ-F2-6), y el rol `fast` **ya esta decidido antes de medir** —2 usos reales
      en tres meses, ninguna tool lo elige, cero casos en el corpus—: no se mide, no se cambia, y la
      pregunta que de verdad plantea (si ese rol debe existir) va al backlog, no a un modelo.
      `vision` se decide sobre dos casos y **una sola imagen**, uno de ellos inventado, y eso se
      escribe junto al veredicto.
    - Verification: las cuatro tablas de §9 pegadas en `verification.md`, incluidas las corridas
      anuladas, las de `rechazo_por_contexto` y si la tanda fue concluyente. Y una decision explicita
      que la version anterior del plan no tenia: **la medida es sobre b10909 y produccion corre
      b9925**, asi que o se migra produccion antes de que F3 aplique el catalogo, o se escribe que la
      eleccion se transfiere sin verificar. Sin escribirlo, F3 pondria en `config.py` modelos
      elegidos sobre un motor en el que no corren.
    - Rollback or recovery: no se toca `config.py`; el catalogo vigente sigue vivo hasta que F3
      escriba las cadenas sobre los roles resultantes (REQ-F2-5).
    - Decisiones del usuario tras la tarea 20 (2026-09-15), que sustituyen dos puntos de este texto:
      (1) **la revision humana a ciegas de §4.8 queda cubierta por los 30 pares de P-15** (15 en
      `long`, 15 en `code`, comprobados letra a letra); no se genera la hoja 0/1/2. (2) **Produccion
      migra a b10909 antes de que F3 toque el catalogo**: la eleccion no se transfiere sin verificar.
    - Dato previo, medido por ejecucion (2026-09-15 13:20-13:22 UTC, `protocolo-f2.md` §10 sesion 6):
      **los tres candidatos cargan y generan en b9925** (`D:\Projects\llms\llamacpp`, `9925
      ed8c26150`) con el perfil del driver de produccion activo y las configs de la tanda (`--fit off
      -ngl 99`; b9925 no tiene `--load-mode`, asi que carga con `mmap`). Gemma 4 26B-A4B `-ncmoe 0`
      `-c 36736`: sano en 7,7 s, VRAM 14 917 MiB, 72 tok/s. Qwen3.6-35B-A3B `-ncmoe 8` `-c 7168`: 8,1
      s, 14 847 MiB, 58 tok/s. Gemma 4 12B con `mmproj` y `ubatch 2048`: 4,6 s, 9 549 MiB, describe la
      imagen de control. `Shared Usage` del adaptador sube como mucho 174 MiB, bajo el umbral de 1 024.
      Consecuencia: **la migracion no la fuerza una incompatibilidad**, la fuerza REQ-F2-6 —la calidad y
      la velocidad se midieron sobre b10909, y en b9925 solo esta comprobado que cargan—. Por eso la
      decision (2) se mantiene, y la tarea de migrar es de F3, antes de su primera tarea de catalogo.
    - Asignacion de roles que escribe esta tarea en `verification.md`, con el dato de cada una:

      | Rol | Modelo | Criterio | Dato |
      | --- | --- | --- | --- |
      | `mechanical` | `gemma3-4b` (no cambia) | empate en techo, decide la velocidad | 5 casos en 1,0 los dos; 516 contra 561 ms, dentro de la banda |
      | `long` | **Gemma 4 26B-A4B** | calidad por pares | 15 a 0; 1,8 s contra 3,0 s; techo igual |
      | `code` | **Qwen3.6-35B-A3B** | calidad por pares | 15 a 0; techo 157 873 contra 20 171 bytes; 4,6 s contra 9,3 s |
      | `vision` | **Gemma 4 12B** (decision del usuario, 2026-09-15) | sin agregado; caso a caso | separa en `leer-cifras-dashboard` (1,0 contra 0,67); ver abajo |
      | `fast` | `qwen35-2b` (no cambia, no se mide) | decidido antes de medir | 2 usos en tres meses, ninguna tool lo enruta |

      `vision` no la decide la regla: §7 no da agregado con dos casos. Caso a caso, Gemma 4 12B separa
      **solo en `leer-cifras-dashboard`** (1,0 contra 0,67, banda 0); en `describir-dashboard` la
      diferencia (1,0 contra 0,75) **es igual a la banda (0,25), no la supera**. Va mas lenta (6,1 s y
      1,2 s contra 4,4 s y 0,5 s) y todo sale de **una sola imagen**, con un caso inventado. **El
      usuario eligio Gemma 4 12B con este dato delante (2026-09-15)**; queda escrito como decision
      suya sobre un caso que separa, no como resultado de la regla.
    - **P-5 (un modelo para varios roles): no aplica con lo medido.** Cada rol sale con un modelo
      distinto y ninguno se midio fuera de su rol. Que Gemma 4 26B-A4B pudiera cubrir tambien `vision`
      es una hipotesis sin un solo dato, y se escribe asi en `verification.md`, no como descartada.
    - **Lo que hereda F3, escrito aqui para que la condicion de replanificacion sea comprobable:**
      migrar produccion a b10909 (con el perfil del driver movido y medido, porque es por ejecutable) y
      repetir en b10909 la prueba de carga de estos tres; decidir `-ncmoe 0` o `4` para Gemma 4
      26B-A4B (15,1 GB pico contra 14 GB de presupuesto diario; §7, salvedades); subir los candidatos
      con el razonamiento apagado; fijar el `n_ctx` de produccion; y **`fast` queda fuera de las
      cadenas de respaldo** —no hay dato con que declarar nada sobre el—, con la pregunta de si el rol
      debe existir en el backlog del vault.
    - Verification (ademas de la de arriba): las cuatro tablas de §9 pegadas desde
      `resultados/decidir-final.md`, generadas y no copiadas a mano; la tabla de roles; y la condicion de replanificacion de F3
      comprobada frase a frase contra este bloque.

### F3 - Respaldo y enfriamiento

**Condicion de replanificacion, comprobada frase a frase (2026-09-15):** tarea 21 cerrada (PR #185)
con los roles en `verification.md`; migracion a b10909 decidida (antes de tocar el catalogo); y
`fast` fuera de las cadenas. Esa ultima **no exige enmendar REQ-004**: a `fast` solo se llega con
`model` explicito, y REQ-005 le quita el respaldo, asi que la fila «rapido -> residente -> largo» es
inalcanzable hoy. Se deja escrita y un test asevera que no se ejecuta.

**Mapa de impacto** (investigacion del 2026-09-15, con fichero:linea): el salto va en `_run_chat`
(`server.py:813-823`, tras el reintento de schema y dentro de `with _chat_slots`); `_chat_chunked` y
`_chat_map_reduce` fijan `model` por cierre (1150, 1314) y map-reduce calcula el `budget` una vez
(1301); `fallos.PATRONES_DE_CAPACIDAD` esta vacio (60) y `_post_chat` llama a `clasificar` **sin**
`modelo_cargado` (695), asi que hoy todo 5xx es `MODELO` y todo `ReadTimeout` es `CAPACIDAD`;
`config.MAX_CHARS` se indexa por **nombre de modelo** (209-214); el patron de estado entre procesos
es `inflight.json` (`server.py:114-266`: `FileLock` de 2 s, escritura atomica, degradacion); y
`_llamaswap_groups` lee `LLAMASWAP_CONFIG` con `os.environ.get` directo (2242), fuera de
`VARIABLES_DE_ENTORNO`.

**Tres hallazgos que ordenan el bloque:**

1. **El residente y los modelos nuevos pueden no caber juntos.** Produccion tiene `gemma3-4b` en un
   grupo `persistent`, siempre cargado, y la tanda midio cada modelo **solo** (llama-swap de pruebas
   sin grupos, §1.4). Gemma 4 26B-A4B y Qwen3.6 ocupan ~14 GB por encima del reposo en b9925
   (§10 sesion 6); con el residente al lado se pasa de 16 GB, y con el perfil del driver eso es OOM
   al cargar, no lentitud. REQ-004 y D-3/D-4 **presuponen** que el primer salto al residente no
   fuerza swap. Se mide en la tarea 24 antes de escribir una sola cadena.
2. **Encender el salto antes de REQ-020 es peligroso, no solo incompleto.** Con los patrones vacios
   un OOM real se lee como fallo del modelo y salta al siguiente modelo grande: la cascada de swaps
   que la clase de capacidad existe para evitar. La tarea 23 va antes que la 28 sin excepcion.
3. **`MAX_CHARS` por modelo es incompatible con REQ-004**, que preve dos roles con el mismo modelo:
   el literal del dict hace que el ultimo pise al primero. Se arregla antes de las cadenas (tarea 25).

Orden: primero la maquina (22-24), porque las capturas de REQ-020 se toman sobre la version que
correra en produccion y el catalogo decide que cadenas tienen sentido; despues el codigo (25-29).
**Las tareas 25 a 27 no dependen de la maquina** y pueden avanzar mientras 22-24 esperan una ventana
libre: la 27 implementa las cadenas **por defecto de REQ-004** y el mecanismo para sobrescribirlas,
no una cadena elegida para esta maquina. **Dos frenos con dueno, no con prosa:** la 28 (el salto)
no se mezcla sin la 23 cerrada; y ni la 28 se mezcla ni la 30 activa nada sin la tabla de
coexistencia de la 24 con resultado «cabe» (1 o 2), **o** una decision escrita del usuario si dio
«no cabe». D-1 trae el mecanismo encendido por defecto, asi que el freno tiene que estar antes de
mezclar, no antes de encender. La 30 activa y publica.

**Sobre el non-goal «tocar la configuracion de llama-swap»:** se refiere al paquete —ningun codigo
de F3 escribe esa config—. Las tareas 22 y 24 editan la config de produccion de **esta maquina**
(`D:\Projects\llms\llama-swap\config.yaml`), fuera del repo, como operacion con respaldo y rollback.

22. **Migrar produccion a b10909 y llama-swap v255, con el catalogo vigente**
    - Files or modules: fuera del repo `D:\Projects\llms\llama-swap\config.yaml` (respaldo con fecha);
      en el repo `src/local_delegate/doctor.py` (`RECOMMENDED_VERSIONS`, 33-37),
      `docs/wiki/Backend-versions.md`, `README.md`, `CHANGELOG.md`, `verification.md`
    - Requirements covered: prepara REQ-020 (version de produccion) y la decision de la tarea 21
    - Detalle: **motor y catalogo no cambian a la vez**: aqui solo el motor, con los cinco modelos de
      hoy y sus flags, para que una regresion tenga un unico sospechoso. El perfil «Prefer No Sysmem
      Fallback» lo mueve el usuario a `llamacpp-b10909\llama-server.exe` (es por nombre de fichero y
      la NVIDIA App admite una entrada por nombre). Anadir `--fit off -ngl 99`, que b10909 trae con
      `--fit on` por defecto y reduciria capas en silencio. Comprobar que v255 sigue expandiendo
      `${env.LOCAL_DELEGATE_REMOTE_API_KEY}` en `apiKeys`: la Mac delega contra este backend.
      `--load-mode` queda en el defecto (`mmap`): `none` se eligio para que la sonda viera la RAM
      (P-13), no por rendimiento. Ventana escrita en §10 antes de empezar, con el daemon parado.
    - Verification: perfil medido por su efecto (b10909 da OOM con la carga de CP-1, b9925 desborda);
      los cinco modelos cargan y responden por el **daemon**, no por `curl` a mano; `local_status` en
      verde; `doctor` no avisa de version; suite en verde. Sin `LUID` fijo en ningun script. **La
      clave de `apiKeys`, con las dos mitades**: una peticion al llama-swap de produccion **con** la
      clave da 200 y **sin** clave da 401. Solo el 401 no discrimina (es lo que se veria si v255 dejara
      de expandir `${env...}`), y solo el 200 tampoco (una expansion a vacio podria dejarlo abierto).
      Y la Mac delega con su configuracion de siempre.
    - Rollback or recovery: restaurar el `config.yaml` respaldado y devolver el perfil a la ruta de
      b9925, medido; b9925 sigue en disco. El cambio de `RECOMMENDED_VERSIONS` se revierte con el PR.

23. **Capturas reales para REQ-020 y la senal de modelo cargandose**
    - Files or modules: `tests/fixtures/backend/` (nuevo, respuestas crudas con version anotada),
      `benchmarks/catalogo-2026-09/llama-swap-capturas.yaml` (nuevo; como `llama-swap-pruebas.yaml`,
      con rutas de modelos de esta maquina y **ninguna clave**),
      `src/local_delegate/fallos.py`, `src/local_delegate/server.py` (`_post_chat`),
      `tests/test_fallos.py`, `tests/test_fallos_integracion.py`
    - Requirements covered: REQ-001, REQ-015, REQ-016, REQ-018, REQ-019, REQ-020
    - Detalle: con las **mismas versiones que produccion tras la 22** (b10909, v255) pero con una
      **config de captura aparte** (`benchmarks/catalogo-2026-09/llama-swap-capturas.yaml`, puerto
      propio, **daemon y llama-swap de produccion parados** —su residente persistente ocuparia VRAM y
      falsearia el OOM y los tiempos de carga—, y un solo `llama-server` vivo), porque varias capturas necesitan configs que produccion no debe tener:
      OOM con perfil (`cp1-no-cabe`: 14B a 65 536 con KV f16, ya medido), OOM sin perfil (la misma
      carga), error de carga (ruta de modelo inexistente), peticion durante la carga y timeout durante
      la carga (Qwen3.6-35B-A3B, el que mas tarda en montarse, con timeout corto del cliente), y
      `length` con razonamiento (Gemma 4 26B-A4B **con** razonamiento y `max_tokens` bajo). Todos
      estan en disco desde la tanda; **ninguno depende de la 24**. Se captura por llama-swap (lo que ve
      el cliente) y directo a llama-server. El tramo sin perfil exige que el usuario lo retire de la
      ruta de b10909, que tras la 22 es la de produccion: por eso va con el daemon parado y se mide al
      devolverlo. **Clase esperada de cada captura, escrita antes de capturar**: OOM con perfil y
      error de carga -> `CAPACIDAD`; OOM sin perfil -> **`TIMEOUT_LECTURA`**, capturado con el timeout
      del cliente **por encima del tiempo de carga medido** para esa config (asi la muestra al vencer
      ve el modelo ya cargado) y por debajo de lo que tarda en generar desbordado. Si no se consigue ese
      hueco, se anota **«no capturado»** y no cuenta como verificado: un modelo que desborda en cada
      llamada debe dejar de recibirlas, y eso queda sin prueba real hasta que se capture; carga en curso y
      timeout durante la carga -> `CAPACIDAD`; `length` con razonamiento -> `CONFIGURACION`.
      **Senal de carga (REQ-018), tomada AL vencer y no despues:** un temporizador arranca con la
      peticion y, si sigue viva a `HTTP_TIMEOUT` menos un margen, consulta `/running` y guarda si el
      modelo estaba `ready` o cargando; al llegar el `ReadTimeout` se usa esa muestra. Reglas del temporizador: **un temporizador por
      intento** (`_post_chat` hace dos, `server.py:665`), cancelado en todos los caminos de salida; el
      plazo cuenta **desde que se envia la peticion**, como el de lectura de httpx; el **margen es mayor
      que el tope de la consulta mas holgura** (tope 1 s, margen 3 s), para que la muestra este lista
      al vencer; y si al llegar el `ReadTimeout` la consulta sigue en curso se espera como mucho hasta
      su tope, y si no llega, `None`. Probado con reloj controlado. Consultar tras
      el timeout veria el estado de despues, y si la carga termina en ese hueco el fallo se contaria
      como de lectura, justo lo que D-2 prohibe. El camino feliz no consulta nada (se cancela el
      temporizador). **Si `/running` no responde, no existe (Ollama, LM Studio) o tarda mas de 1 s,
      `modelo_cargado` queda en `None` y la clase es `CAPACIDAD`**: no enfria. Consecuencia que se
      escribe en la spec y aprueba el usuario en el gate: **fuera de llama-swap, D-2 no se cumple** y
      un modelo colgado no se enfria por timeouts; se elige el lado que no castiga a un modelo lento de
      montar, igual que F0. `ConnectTimeout` (REQ-016) no se captura: es un error del cliente sin
      respuesta del backend, y ya lo cubre F0 (tarea 2).
      **Privacidad de las capturas:** se guarda solo el cuerpo y el estado de la **respuesta**, nunca
      las cabeceras de la peticion (`Authorization`); las rutas de la maquina se sanean. Un test lo
      asevera sobre todas las fixtures, porque `personal-security-check` busca datos personales, no
      cabeceras.
    - Verification: cada patron con su fixture, su version y su clase esperada; test de que una
      variante desconocida va a «sin clasificar» y **no** a `MODELO`; control positivo por patron
      (quitar el patron hace caer su test, y por el assert de la clase); test de que el camino feliz no
      llama a `/running`; **test de la carrera**: la muestra dice «cargando» y `/running` ya diria
      `ready` cuando llega el timeout -> `CAPACIDAD` (con un mutante que consulte despues, que tiene que
      caer); test de `/running` caido o lento -> `CAPACIDAD` sin esperar mas de 1 s.
    - Rollback or recovery: patrones y fixtures son datos; vaciar la tupla devuelve el comportamiento
      de F0. Maquina: parar el llama-swap de capturas, devolver el perfil a la ruta de b10909 **y
      medirlo** (OOM con la carga de CP-1), y arrancar el daemon, que levanta el llama-swap de
      produccion; comprobar con `local_status` que el residente vuelve a estar cargado.

24. **Catalogo nuevo en produccion, y si el residente cabe al lado**
    - Files or modules: fuera del repo `config.yaml` de produccion, **las variables `LOCAL_DELEGATE_MODEL_*`
      del lanzador del daemon** (si P-16 deja los defectos del paquete) y **la configuracion de la
      Mac**, que delega contra este backend y pediria los nombres viejos; en el repo `verification.md`
      y `protocolo-f2.md` §10
    - Requirements covered: REQ-F2-5; prepara REQ-004 (residente) y el `n_ctx` de backlog 1.3
    - Detalle: sustituir `llama31-8b`, `qwen25-coder-14b` y `qwen3-vl-8b` por los ganadores con sus
      flags de la tanda (`-ncmoe`, `--reasoning off`, `--ubatch-size 2048` en el 12B) y `n_ctx`
      fijado en **tokens medidos** para el `MAX_CHARS` de produccion de cada rol (§3.5), que cierra
      backlog 1.3. **La medida que falta:** cargar el residente y, con el cargado, cada modelo del
      grupo `swap`, con el perfil activo y con escritorio en uso tipico (navegador y video). **«Cabe»
      se define asi, las cuatro a la vez:** carga sin OOM; responde a la **entrada mayor de su rol**
      (`extraer-uvlock-48k` en `long`, `commit-diff-19k` en `code`, la imagen de control en `vision`),
      no a un prompt corto, porque el KV crece con la entrada; `Shared Usage` del adaptador no sube mas
      de 1 024 MiB (el umbral de §6); y el residente sigue respondiendo despues. Salen
      tres resultados posibles y los tres se escriben: cabe con el `-ncmoe` de la tanda; cabe solo con
      un `-ncmoe` mayor (el barrido tiene 4/8/12 medidos: se anota la velocidad que se pierde); o no
      cabe con ninguno. En el tercero **no se escribe ninguna cadena** hasta que el usuario elija entre
      residente no persistente o saltos que asumen swap, porque D-3/D-4 se aprobaron con la premisa
      contraria. Los modelos viejos se quedan en disco.
    - Verification: tabla de coexistencia (residente + cada modelo, VRAM, `Shared Usage`, OOM si/no)
      en `verification.md`; cada rol responde por el daemon con una delegacion real; la entrada mayor
      de `long` (`extraer-uvlock-48k`) ya **no** da rechazo por contexto.
    - Rollback or recovery: el respaldo de `config.yaml` de la tarea 22 (catalogo vigente sobre
      b10909), **y** devolver las variables del lanzador y la config de la Mac a los nombres viejos, con
      el daemon reiniciado (los hooks y el daemon heredan el entorno del lanzador).

25. **Topes por rol y no por modelo**
    - Files or modules: `src/local_delegate/config.py` (`MAX_CHARS`, `max_chars_for`), `server.py`
      (llamadas a `max_chars_for` y `_read_input`), `tests/test_core.py`, `tests/test_chunking.py`,
      `tests/test_map_reduce.py`
    - Requirements covered: REQ-003 (condicion de tamano), REQ-004 (roles que comparten modelo)
    - Detalle: el tope se declara **por rol** (`max_chars_for_role`) y **el modelo principal de una
      llamada usa siempre el de su rol**, asi que el enrutado, el troceado, el truncado de
      `local_translate` y lo que enseña `local_status` no cambian aunque dos roles compartan modelo. El
      tope **por modelo** —el minimo de los roles que resuelven a el— se usa **solo para validar
      candidatos de respaldo** (REQ-003), donde prometer de mas es el fallo. Las variables
      `LOCAL_DELEGATE_MAX_CHARS_*` ya son por rol, asi que no cambia ninguna.
    - Verification: tests con las colisiones que **si** cambian el tope de `long` hoy —largo = codigo
      (el literal lo baja a 20 000) y largo = rapido (a 12 000)— que aseveran que `local_summarize`,
      `local_lint_summary` y `local_translate` trocean y truncan **igual que con modelos distintos**,
      con el rojo visto antes de arreglar en cada una. Mecanico = largo **no sirve de control**: el
      literal ya da 48 000 y el mecanico solo se elige con entradas de 6 000 o menos
      (`server.py:1565`), asi que saldria verde con el defecto vivo. Y que un
      candidato de respaldo se valida contra el minimo. Mutante: el principal usando el minimo, que
      tiene que caer en el test de `local_summarize` por el numero de trozos.
    - Rollback or recovery: cambio interno sin superficie publicada.

26. **Estado de enfriamiento compartido**
    - Files or modules: `src/local_delegate/enfriamiento.py` (nuevo, puro salvo el fichero),
      `config.py`, `tests/test_enfriamiento.py` (nuevo)
    - Requirements covered: REQ-009, REQ-010, REQ-011, REQ-012, REQ-014 (N, T, Tmax, apagado)
    - Detalle: fichero en `LOG_DIR` con el patron de `inflight.json` (bloqueo de 2 s, escritura
      atomica, degradacion a «sin enfriamiento»). Reloj inyectable; vencimientos en hora real y
      recortados a Tmax al leer. Solo nombres de modelo, contadores y fechas. **P-4 se resuelve
      parametrizando**: F2 no midio tasas de fallo —en la Tabla 2 de la tanda todas las corridas acaban
      en `ok`, `truncado` o `rechazo_por_contexto`, ninguna en error del backend—, asi que 3/120 s/x2/
      900 s quedan como defecto configurable y su validacion va a la tarea 30, con criterio escrito
      antes de encender.
    - Verification: tests con reloj controlado de los escenarios de enfriamiento; dos «procesos»
      (dos instancias sobre el mismo fichero) sumando fallos; fichero corrupto y bloqueo ocupado que
      no bloquean ni fallan; test de privacidad (el fichero no contiene nada fuera del esquema).
      Mutantes: sin duplicar, sin tope, reset por clase neutra, y «tras vencer hacen falta N fallos»
      (REQ-010 pide que baste **uno**). **Regla que la spec no fijaba, decidida aqui:** `CAPACIDAD` y
      `CONFIGURACION` se tratan como las clases neutras de REQ-011 —ni suman ni ponen a cero—, porque
      no dicen nada de si el modelo responde bien; con su test.
    - Rollback or recovery: modulo sin consumidores hasta la 28; borrar el fichero es seguro.

27. **Cadenas por rol**
    - Files or modules: `config.py` (variables de cadena, saltos maximos, apagado; `LLAMASWAP_CONFIG`
      pasa por `_leer`), `server.py` (`_llamaswap_groups`, 2242), **`autostart.py:56` y
      `doctor.py:346`**, que hoy leen `LLAMASWAP_CONFIG` con `os.environ` directo —los tres sitios pasan
      a `config`, o seria otra vez dos fuentes para el mismo dato y el guardian de
      `test_aislamiento_entorno.py` solo mira `config.py`—, `src/local_delegate/checks.py` (check de
      cadena con modelo fuera de catalogo), `docs/wiki/` (tabla del doctor), `tests/test_cadenas.py`
      (nuevo), `tests/test_wiki.py`, `tests/test_checks.py`
    - Requirements covered: REQ-003, REQ-004, REQ-014
    - Detalle: resolucion al vuelo con la config vigente; residente = modelo del grupo `persistent`
      si la config se lee (pyyaml es opcional), si no `MODEL_MECHANICAL`; **con varios miembros, el
      primero que este en `ALLOWED_MODELS`, en el orden del YAML**; repetidos fuera; `vision` sin
      cadena **antes** de filtrar por `ALLOWED_MODELS`, que lo excluye a proposito
      (`test_vision.py:177`); lista vacia desactiva. `local_status` dice el residente **y de donde
      salio** (grupo `persistent` o defecto del mecanico): en esta maquina los dos son `gemma3-4b`, y
      sin eso la tarea 30 no distingue que camino se uso. Implementa las cadenas por defecto de
      REQ-004; si la 24 da «no cabe», las salidas son dos y **no son equivalentes**: cambiar la
      **config de esta maquina** (un `-ncmoe` mayor que haga caber) no toca este codigo; pero un
      residente no persistente hace que el primer salto fuerce swap, lo que contradice el requisito de
      VRAM de la spec y la premisa de D-3/D-4, y eso **reabre la spec y su gate**, no es un retoque.
    - Verification: tests de cadena por defecto, sobrescrita, vacia, con repetidos, con un modelo
      desconocido (que se ignora y `doctor` avisa), con varios miembros en `persistent` y sin pyyaml
      (cae al mecanico y lo dice); `fast` inalcanzable **recorriendo las tools por rol** (ninguna tool
      resuelve a `MODEL_FAST` sin `model` explicito); el guardian de `test_aislamiento_entorno.py` ve
      las variables nuevas y ningun `os.environ` directo sobre `LLAMASWAP_CONFIG` queda fuera.
    - Rollback or recovery: sin consumidores hasta la 28.

28. **El salto, dentro de la plaza de concurrencia**
    - Files or modules: `server.py` (`_run_chat`, `_chat`, `_chat_chunked`, `_chat_map_reduce`, las
      tools que pasan el rol y si el `model` es explicito), `tests/test_respaldo.py` (nuevo),
      `tests/test_post_chat_caminos.py`
    - Requirements covered: REQ-002, REQ-005, REQ-006, REQ-007, REQ-008, REQ-017, REQ-018, REQ-019
    - Detalle: `_run_chat` recibe la cadena resuelta; tras el reintento de schema y dentro del `with`
      decide segun `result.clase`, y **devuelve la lista de intentos** (modelo, clase, ms), no solo el
      ultimo resultado: sin eso `_accumulate` (1137-1144) sigue contando una llamada y la tarea 29 no
      tiene de donde sacar `chunks`. `local_delegate` distingue «explicito» de «por defecto» y lo baja
      hasta `_chat`; **un modelo elegido por el usuario en la pregunta de elicitation
      (`server.py:1773`) cuenta como explicito**: lo eligio una persona. En varios trozos
      (`_chat_chunked`), el modelo que respondio pasa a los siguientes. **En map-reduce el respaldo de
      `long` esta muerto por construccion con los topes de hoy**: los trozos miden
      `0,8 × 48 000 = 38 400` caracteres (`server.py:1301`) y ningun candidato de 20 000 los admite
      (REQ-003); se escribe asi en la docs y un test lo fija, en vez de descubrirlo en produccion. El
      escenario «la entrada no cabe en el respaldo» (30 000 contra 48 000) es el camino de `_chat`
      sin trocear, no map-reduce. El aviso va en metadatos en `local_extract` y en la respuesta, nunca
      en el fichero, en `local_boilerplate`. El autoarranque y la pregunta de **arrancar el backend**
      (`server.py:706`) ya retienen la plaza hoy: no cambia, y se escribe. La pregunta de **elegir
      modelo** (`server.py:1773`) corre en la tool, antes de `_chat` y fuera de la plaza, y tampoco
      cambia. **Freno de mezcla:** este PR no se mezcla sin la 23 cerrada
      y sin la tabla de coexistencia de la 24 en «cabe» o la decision del usuario.
    - Verification: los 16 escenarios de la spec como tests sobre `backend_mock` con un doble que
      responde segun `model` (`side_effect` funcion); concurrencia con el semaforo a 1; `vision` con
      enfriamiento y sin respaldo (spec, casos limite). **El interruptor, con un caso que distingue**:
      con las dos variables apagadas, un 500 del principal y un fichero de estado que ya lo tiene en
      enfriamiento dan **el error de hoy, una sola llamada al backend y ningun cambio en el fichero**;
      con ellas encendidas, el mismo caso salta. La bateria de tools en camino feliz no sirve: da lo
      mismo con el interruptor roto. Mutantes: interruptor ignorado, salto por clase que no toca,
      tercer salto, respaldo fuera del semaforo, aviso dentro del contenido.
    - Rollback or recovery: las variables de apagado; el PR se revierte entero.

29. **Observabilidad: log, panel y `local_status`**
    - Files or modules: `server.py` (`_log_event`, `local_status`), `web/metrics.py` (`by_model` y el
      espejo JS `acct`), `tests/test_metrics.py`, `tests/test_core.py`
    - Requirements covered: REQ-013, y la parte de REQ-019 que va al panel
    - Detalle: campos aditivos (pedido, respondido, clase del salto); `model` sigue siendo el que
      respondio para que el historico sin campos nuevos se lea igual; `chunks` cuenta tambien las
      llamadas del respaldo. Dos fuentes para el mismo dato es el defecto recurrente del repo: el
      cambio va a Python y al JS a la vez, y el test de paridad lo ata.
    - Verification: test de paridad en verde con un evento con salto **y con uno de causa
      `CONFIGURACION`** (REQ-019 va al panel); test de historico sin campos; `chunks` contando las
      llamadas del respaldo a partir de la lista de intentos de la 28; `local_status` con un modelo en
      enfriamiento, su tiempo restante **y cuantas veces seguidas ha vuelto a entrar** (REQ-013);
      panel comprobado en navegador.
    - Rollback or recovery: campos aditivos; un lector viejo los ignora.

30. **Activacion, criterio de P-4 y release**
    - Files or modules: `verification.md`, `CHANGELOG.md`, `README.md`, `docs/wiki/`
    - Requirements covered: D-1, P-4, y la verificacion de extremo a extremo de REQ-001 a REQ-020
    - Detalle: **no se activa sin el freno de la 28** (23 cerrada; coexistencia en «cabe» o decision
      del usuario). Antes de encender en esta maquina se escribe el criterio de P-4, igual que
      REQ-F1-12: ventana, que se cuenta (entradas en enfriamiento, saltos por clase, llamadas que
      fallaron al momento) y que numero obliga a cambiar los defectos, **con un tercer resultado
      explicito, «no concluyente»**, para una ventana con menos de un minimo de fallos que cuentan: la
      tanda no tuvo ni un error del backend, y una ventana sin enfriamientos no valida los defectos,
      no mide nada. **La ventana de P-4 no bloquea publicar** —los numeros son configurables y no
      cambian ningun schema—; la de F1 si. Mientras corra un benchmark se para **todo lo que puede
      delegar contra este backend**: el daemon, los procesos stdio de cualquier cliente (llevan el
      mecanismo dentro) y **la Mac**, que delega contra el backend de la PC con su propio
      local-delegate. El runner va directo al backend (`benchmark.py:1258`) y el swap que lo
      ensuciaria vendria de cualquiera de ellos, que las variables de apagado de un proceso no tocan. Apagar o encender por
      variable exige **reiniciar el daemon**: `config` se lee al importar. Verificacion contra el backend real **por
      el daemon** (`uv tool install --force .` y `schtasks /Run`), provocando un fallo de modelo
      reproducible y comprobando salto, aviso, log y panel. **No se publica hasta cerrar la ventana
      de F1**; la release toca CHANGELOG, README y wiki.
    - Verification: los 16 escenarios comprobados en `verification.md` con su evidencia; suite,
      `ruff` y CI entero (incluidos los checks que no son workflows); `personal-security-check`.
    - Rollback or recovery: `LOCAL_DELEGATE_*` de apagado en el bloque `env` del lanzador del daemon,
      sin reinstalar.

**P-16, resuelta por el usuario (2026-09-15): los defectos del paquete pasan a los ganadores de F2.**
Contexto de la pregunta: los defectos de `config.py`
(`MODEL_LONG`, `MODEL_CODE`, `MODEL_VISION`) son **nombres** que tienen que existir en la config de
llama-swap de quien instale el paquete. Cambiarlos a los ganadores de F2 hace que el README, el
`.env.example` y `init-llamaswap` recomienden el catalogo medido, pero rompe al actualizar a quien
tenga los nombres viejos (breaking). Dejarlos y fijar los nuevos por variable en esta maquina no
rompe a nadie, pero el paquete seguiria recomendando un catalogo que la medicion desaconseja. Lo
decidio el usuario con este dato delante. **Consecuencias para la tarea 24**, que suma una parte en
el repo en el mismo PR que la config de la maquina, para que paquete y produccion no se separen:
`MODEL_LONG`, `MODEL_CODE` y `MODEL_VISION` pasan a `gemma4-26b-a4b`, `qwen36-35b-a3b` y
`gemma4-12b` (las etiquetas de la tanda sin el prefijo `t-`, que son tambien los nombres del
`config.yaml` de produccion); `init-llamaswap` (`cli.py:467-522`) genera ese catalogo con sus flags
(`-ncmoe`, `--reasoning off`, `--ubatch-size 2048`); y cambian `README.md`, `examples/.env.example`,
`docs/wiki/Configuration.md`, `Tools.md`, `Backend-versions.md`, `Savings-and-metrics.md` y los datos
de captura del README (`scripts/dev/capture_dashboard.py`, `fake_backend.py`). **Breaking** en el
CHANGELOG, con la receta para quien tenga los nombres viejos: renombrar en su llama-swap o fijar
`LOCAL_DELEGATE_MODEL_*`. Con esta decision **las variables del lanzador del daemon ya no hacen
falta**; la config de la Mac si se revisa. `gemma3-4b` y `qwen35-2b` no cambian. La verificacion
suma: suite en verde tras el cambio de defectos, `doctor` sin avisos y el README capturado contra la
app de metricas (9494), como en cada release.

## Test strategy

- **Unit**: el clasificador de F0 (una clase por test, con control positivo); la politica por
  extension del hook; el parseo acotado del hook de shell; la lectura del fichero de salud.
- **Integration**: `_post_chat` contra `tests/backend_mock.py` (`httpx2.MockTransport`), con los
  tres defectos reproducidos **en rojo** antes de arreglarlos; la correlacion hook -> evento de
  tool; el panel y su espejo JS con el test de paridad.
- **End-to-end o manual**: `install` en Windows con los cuatro flags de esta maquina
  (`--mcp-mode http --web-token-env --enable-read-hook --agents`), y ver el hook **disparar
  instalado**, no solo en la suite. Verificacion contra el backend real la corre el **daemon**
  (`uv tool install --force .` y `schtasks /Run`), nunca pidiendole la clave al usuario.
- **Security and secret scanning**: `personal-security-check` antes de cada commit. La telemetria no
  escribe prompts, comandos ni rutas, y el fichero de salud solo lleva estado y hora: test explicito
  de que ninguno de los dos filtra contenido.
- **F2**: los tests de la sonda son **Windows-only** (`ctypes`, `typeperf`) y el CI corre en Ubuntu,
  Windows y macOS: llevan marca de plataforma declarada, con el antecedente del test que fallo solo
  en macOS. El corpus se prueba contra la distribucion del log real, no contra la tabla que uno mismo
  escribio. Y los controles CP-1 a CP-4 son verificacion **en la maquina**, no en la suite: un
  instrumento se prueba ejecutandolo, que es la leccion de los dos hooks del 2026-09-12.
- **F3**: los patrones de fallo se prueban contra **fixtures capturadas** del backend real con su
  version, nunca contra respuestas escritas a mano; los escenarios de la spec, con un doble de
  `backend_mock` que responde segun `model`; el estado con reloj inyectable y dos instancias sobre el
  mismo fichero; «mecanismo apagado» con un caso que distingue (un 500 y un modelo ya enfriado), no
  con la bateria de tools en camino feliz, que da lo mismo con el interruptor roto. La prueba
  de uso es por el **daemon** contra el backend real (tarea 30): una suite verde no vio un breaking
  change en este repo porque la tool no tenia test.
- **Trampas conocidas del repo, que se comprueban en cada tarea**: que el test falle por la razon
  que dice y no por otra guarda; que el mutante mute de verdad; que el caso elegido pueda
  distinguir; y que lo que se cuente lo cuente el programa, no yo a ojo.

## Migration and compatibility

- **El bloqueo nace apagado.** Se enciende solo cuando la tarea 10 haya dejado escrito el criterio
  de exito y de abandono. Apagarlo no exige cerrar la sesion (REQ-F1-11).
- **Ninguna tool cambia su schema.** El identificador de correlacion es un campo aditivo; un cliente
  viejo o un evento sin identificador se comportan como hoy. Recordar que el cliente MCP **cachea el
  schema de la sesion**: tras cambiar una firma se sigue viendo la vieja aunque el argumento nuevo
  si llegue.
- **Claude Desktop queda fuera de F1** hasta resolver P-2: alli no hay hooks, asi que ningun
  requisito de F1 puede darse por cumplido mirando solo a Claude Code.
- **Hooks nuevos**: se registran en `install.py`; si alguno se retira mas adelante, entra en
  `_SCRIPTS_RETIRADOS` o su copia queda inmortal en `~/.claude/hooks/`.
- **Release**: los cambios de F0 y F1 salen con el umbral de 8 KB y el fix de `__pycache__` que ya
  esperan en `main`. La release toca CHANGELOG, README y `docs/wiki/`.
- **Breaking de F2**: el runner deja de aceptar `schema_version: 1` en el corpus (tarea 16). El
  corpus de julio se conserva como fichero y el cargador viejo queda en el historial de git; ningun
  REQ-F2 pide repetir aquella prueba. Se anota como breaking en el CHANGELOG, y `benchmark` es
  superficie publicada: la release toca tambien README y `docs/wiki/Backend-versions.md`.
- **F3, maquina**: motor y catalogo se cambian en tareas distintas (22 y 24), cada una con el
  `config.yaml` anterior respaldado; el perfil del driver se mide por su efecto cada vez que se mueve.
- **F3, paquete**: ninguna tool cambia su schema; los campos del log son aditivos y `model` conserva
  su significado para el historico; respaldo y enfriamiento se apagan por variable sin reinstalar
  (D-1). `doctor` pasa a recomendar b10909/v255. P-16 cambia los modelos por defecto (decision del
  usuario): es breaking y va asi en el CHANGELOG, con la receta de migracion. **No se publica hasta cerrar la ventana de F1.**

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.

### Cobertura por requisito

| Requisito | Tarea |
| --- | --- |
| REQ-F0-1 | 2 |
| REQ-F0-2 | 1, 2 |
| REQ-F0-3 | 3 |
| REQ-F0-4 | 1 |
| REQ-F0-5 | 1 |
| REQ-F0-6 | 2 |
| REQ-F1-1 | 5, 7 |
| REQ-F1-2 | 7 |
| REQ-F1-3 | 7 |
| REQ-F1-4 | 4 (lo que queda vivo; el resto suspendido por P-7) |
| REQ-F1-5 | 5, 9 |
| REQ-F1-6 | 5, 10 |
| REQ-F1-7 | 11 |
| REQ-F1-8 | 10 |
| REQ-F1-9 | 8 |
| REQ-F1-10 | 6, 7 |
| REQ-F1-11 | 7 |
| REQ-F1-12 | 10 |
| REQ-F2-1 | 13, 16, 18, 20 |
| REQ-F2-2 | 14, 15, 16, 19, 20 |
| REQ-F2-3 | 12, 13, 16, 20 |
| REQ-F2-4 | 17, 21 |
| REQ-F2-5 | 21 |
| REQ-F2-6 | 17, 20, 21 |
| REQ-001 | 23 |
| REQ-002 | 28 |
| REQ-003 | 25, 27, 28 |
| REQ-004 | 24 (residente), 25, 27 |
| REQ-005 | 28 |
| REQ-006 | 28 |
| REQ-007 | 28 |
| REQ-008 | 28 |
| REQ-009 | 26 |
| REQ-010 | 26 |
| REQ-011 | 26 |
| REQ-012 | 26 |
| REQ-013 | 29 |
| REQ-014 | 26, 27 |
| REQ-015 | 23 (F0 ya lo cubre; se reverifica con capturas) |
| REQ-016 | F0, tarea 2 (sin captura posible: es un error del cliente sin respuesta del backend) |
| REQ-017 | 28 |
| REQ-018 | 23, 28 |
| REQ-019 | 23, 28, 29 |
| REQ-020 | 22 (version), 23 |
| P-4 | 26 (parametro), 30 (criterio y validacion) |
