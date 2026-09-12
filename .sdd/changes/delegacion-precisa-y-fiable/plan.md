# Implementation plan: Delegacion precisa y fiable: deteccion de fallos, enrutado por reglas, catalogo de modelos y respaldo

## Approach

La spec tiene cuatro fases y solo dos son planificables hoy. **F0 y F1 se detallan tarea a tarea**;
**F2 y F3 quedan como bloques con entrada, salida y condicion de replanificacion**, porque detallar
F3 ahora seria inventar tareas sobre un catalogo de modelos que todavia no existe, y F2 depende de
una accion fisica del usuario (limpiar RAM y activar «Prefer No Sysmem Fallback» en el panel de
NVIDIA). El gate `plan` se aprueba sobre F0 y F1; F2 y F3 vuelven a pasar por aqui cuando les toque.

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

### F2 - Catalogo de modelos (bloque, se replanifica)

- **Entrada**: maquina limpia, «Prefer No Sysmem Fallback» activo (lo hace el usuario), llama.cpp
  b10909 en carpeta aparte, versiones de llama-swap y llama.cpp anotadas.
- **Salida**: un modelo por rol con el dato que lo sostiene, **y la medida del catalogo vigente en
  la misma tanda** (REQ-F2-6). Sin linea base no hay comparacion.
- **Condicion de replanificacion**: cuando el usuario confirme el entorno preparado. Requisitos
  cubiertos aqui: REQ-F2-1 a REQ-F2-6. Memoria del proyecto: se mide `PrivateMemorySize64` del
  proceso, nunca la RAM del sistema; asi se descarto `gpt-oss-20b` por error en julio.

### F3 - Respaldo y enfriamiento (bloque, se replanifica)

- **Entrada**: el clasificador de F0 (tarea 1) y el catalogo de F2.
- **Salida**: los 20 requisitos heredados (`REQ-001` a `REQ-020`), con las cadenas declaradas sobre
  los roles de F2 y los numeros del enfriamiento validados o parametrizados (P-4).
- **Condicion de replanificacion**: F2 cerrada. Antes de eso, cualquier tarea de F3 se escribiria
  sobre roles que pueden cambiar.

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
| REQ-F2-1 | bloque F2, se replanifica |
| REQ-F2-2 | bloque F2, se replanifica |
| REQ-F2-3 | bloque F2, se replanifica |
| REQ-F2-4 | bloque F2, se replanifica |
| REQ-F2-5 | bloque F2, se replanifica |
| REQ-F2-6 | bloque F2, se replanifica |
| REQ-001 a REQ-020 | bloque F3, se replanifica |
