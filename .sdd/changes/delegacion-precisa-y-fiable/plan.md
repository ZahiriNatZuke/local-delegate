# Implementation plan: Delegacion precisa y fiable: deteccion de fallos, enrutado por reglas, catalogo de modelos y respaldo

## Approach

La spec tiene cuatro fases. **F0, F1 y F2 se detallan tarea a tarea**; **F3 sigue siendo un bloque
con entrada, salida y condicion de replanificacion**, porque detallar sus cadenas ahora seria
inventarlas sobre unos roles que F2 todavia no ha fijado.

**Historial del gate `plan`:** se aprobo primero sobre F0 y F1 (2026-09-12), con F2 como bloque
porque dependia de una accion fisica del usuario —limpiar RAM y activar «Prefer No Sysmem
Fallback» en el panel de NVIDIA— que ya esta hecha. Vuelve a pasar ahora con las tareas 12 a 21 de
F2 y su protocolo (`protocolo-f2.md`). F3 volvera cuando cierre la tarea 21.

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

### F3 - Respaldo y enfriamiento (bloque, se replanifica)

- **Entrada**: el clasificador de F0 (tarea 1) y el catalogo de F2.
- **Salida**: los 20 requisitos heredados (`REQ-001` a `REQ-020`), con las cadenas declaradas sobre
  los roles de F2 y los numeros del enfriamiento validados o parametrizados (P-4).
- **Condicion de replanificacion**: la tarea 21 cerrada, con los roles escritos en `verification.md`,
  decidido si produccion migra a b10909, y **escrito que hace F3 con `fast`**, que sale de F2 sin un
  solo dato medido: o queda fuera de las cadenas de respaldo, o se encadena a `mechanical`. Sin esa
  frase, REQ-F2-5 entregaria a F3 un rol sobre el que no hay nada que declarar. Antes de eso, cualquier tarea de F3 se escribiria sobre
  roles que pueden cambiar, o sobre un motor en el que no se midieron.

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
| REQ-001 a REQ-020 | bloque F3, se replanifica |
