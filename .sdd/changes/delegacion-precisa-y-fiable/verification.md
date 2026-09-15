# Verification: delegacion precisa y fiable

## F0 - Deteccion de fallos

Cerrada el 2026-09-11. Los tres defectos estaban verificados por ejecucion **antes** de tocar
codigo, y los tests que los cubren se vieron **rojos por su propia razon** antes de arreglarlos.

### REQ-F0-1 y REQ-F0-2: los tests fallaron primero, y por lo que decian

Al instalar `tests/test_fallos_integracion.py` contra el codigo viejo:

| Test | Fallo observado |
| --- | --- |
| `test_content_nulo_devuelve_un_error_legible` | `AttributeError: 'NoneType' object has no attribute 'strip'` en `server.py:605` |
| `test_razonamiento_que_se_come_max_tokens_se_dice_en_claro` | el mismo `AttributeError`, misma linea |
| `test_connect_timeout_ofrece_arrancar_el_backend` | `AssertionError: no se ofrecio arrancar el backend` |
| los cinco restantes | `AttributeError: 'ChatResult' object has no attribute 'clase'` |

Antes de eso hubo un **falso rojo** que conviene dejar escrito: los nueve tests fallaban con
«peticion no mockeada», no con el defecto. La causa no era el codigo: la fixture registraba la ruta
del backend de mentira, y `@backend_mock.mock` **limpia el registro de rutas al entrar**, mientras
que las fixtures se resuelven antes. La fixture pasa a devolver un registrador que se invoca dentro
del test. Es otra vuelta de la misma leccion del repo: un test que falla no demuestra nada hasta
que falla por lo que dice.

### REQ-F0-3: `retry_exhausted` es inalcanzable, medido y con control positivo

Metodo: se enumeraron las **16 formas** de terminar el `try` de `_post_chat` —camino feliz, cuerpo
inservible en cuatro variantes, cada rama del `except`, y el autoarranque con sus cuatro
desenlaces— y se ejecutaron todas
(`scratchpad/verificar_retry_exhausted.py`). Resultado: **ninguna** llega al `return` final.

Un no-resultado no es evidencia si no se comprueba que el instrumento podia encontrar algo, asi
que el mismo experimento se repitio sobre un mutante que quita la guarda `attempt == 1` del
autoarranque. Con el mutante, **dos** casos alcanzan la linea:
`['ConnectError, autostart que arranca', 'ConnectTimeout, autostart que arranca']`. El experimento
discriminaba.

Procede **eliminarla** (REQ-F0-3 anula el non-goal heredado). Lo que esa linea prometia —que
`_post_chat` siempre devuelve un `ChatResult`— lo garantiza ahora `tests/test_post_chat_caminos.py`,
que enumera los 16 caminos y **si se ejecuta**, con una guarda que falla si aparece una salida
nueva sin caso propio.

### REQ-F0-4 y REQ-F0-5: control positivo por clase, verificado al reves

`src/local_delegate/fallos.py` es puro: sin red, sin estado, sin decidir reintentos. Cada clase
tiene un caso que la produce y otro parecido que no (`ConnectTimeout` contra `ReadTimeout`,
`ReadTimeout` cargando contra cargado, `length` con razonamiento contra sin el, `content` nulo
contra vacio).

Seis mutantes, y cada uno muere en el test que le toca (`scratchpad/mutantes.py`):

| Mutante | Test que lo caza |
| --- | --- |
| `es_backend_ausente` olvida `ConnectTimeout` | `test_nadie_escuchando_habilita_el_autoarranque` |
| un `ReadTimeout` siempre es timeout de lectura | `test_read_timeout_sin_saber_si_estaba_cargado_es_capacidad` |
| `length` sin razonamiento se lee como configuracion | `test_length_sin_razonamiento_no_es_de_configuracion` |
| un `content` vacio se toma por fallo | `test_el_content_vacio_no_es_un_fallo` |
| los 4xx se achacan al modelo | `test_los_4xx_son_de_la_peticion` |
| lo desconocido se achaca al modelo | `test_una_excepcion_ajena_no_se_achaca_al_modelo` |

**Un septimo mutante sobrevivio, y cambio el diseno.** Quitar la rama `if isinstance(exc,
ConnectTimeout): return Clase.ENDPOINT` no rompia **ningun** test: `ConnectTimeout` ya caia en el
`HTTPError` generico y daba `ENDPOINT` igual. La rama era redundante, y su redundancia destapaba
algo mas importante: **la clase no basta para decidir el autoarranque**. `ConnectError`,
`ConnectTimeout`, `WriteTimeout` y `RemoteProtocolError` son los cuatro `ENDPOINT`, pero solo los
dos primeros significan que no hay nadie escuchando. De ahi nace `es_backend_ausente()`, que es
quien decide si se ofrece arrancar el backend, con sus dos tests de control positivo.

### REQ-F0-6: `ConnectTimeout` entra al camino del autoarranque

`test_connect_timeout_ofrece_arrancar_el_backend` asevera que se ofrece, y
`test_read_timeout_no_ofrece_arrancar_nada` que un `ReadTimeout` **no** lo hace: el backend si
acepto la conexion, y arrancar otro no arregla que el modelo este cargando.

### Suite

`uv run pytest -q`: **853 passed, 2 skipped** tras la tarea 2 (843 antes de F0, mas los 10 nuevos
de clasificacion e integracion). `ruff check` y `ruff format --check` limpios en `src/` y `tests/`.

### Lo que F0 deja pendiente a proposito

- `PATRONES_DE_CAPACIDAD` esta **vacio**: REQ-020 exige que salga de respuestas reales de
  llama-swap y llama-server, capturadas con su version anotada, y eso es trabajo de F3. La rama que
  los consume esta probada inyectando un patron, asi que no es codigo muerto: esta desactivada por
  datos, no por codigo.
- La senal que separa los dos `ReadTimeout` (modelo cargandose contra ya cargado) tampoco existe
  aun. Hasta que llegue, un `ReadTimeout` se clasifica como capacidad o carga, que es el lado que
  no castiga a un modelo lento de montar.


## F1 - Precision de la delegacion (tareas 4 a 9)

### Lo que se probo al reves, y lo que cambio por ello

Once mutantes sobre el codigo nuevo, cada uno con el test que tiene que cazarlo. **Tres
sobrevivieron al principio**, y los tres ensenaron algo:

| Mutante que sobrevivio | Que destapo |
| --- | --- |
| quitar la rama `ConnectTimeout` del clasificador (F0) | era redundante —ya caia en `HTTPError`— y con ella se veia que **la clase no basta para decidir el autoarranque**. Nace `es_backend_ausente()` |
| ignorar los metacaracteres en el hook de shell | los tests usaban `cat x.md \| head`, que ya cae por «mas de una palabra tras el verbo». El caso que de verdad necesita esa guarda es **pegado**: `cat x.md>copia.md` |
| ignorar los flags que acotan | igual: `cat -v` no cambia si se bloquea, pero si el **motivo** registrado, y el denominador de F1 se lee por motivo |

Los dos ultimos se cubrieron probando el motivo, no solo la salida. Tras el arreglo: **6 de 6
mutantes del hook de lectura y 6 de 6 del de shell mueren en el test que les toca**.

### Lo que un test caza y no estaba previsto

- **`test_una_url_invalida_tampoco_lanza`**: `urllib.request.Request()` lanza `ValueError` en el
  **constructor** con una `LOCAL_DELEGATE_BASE_URL` mal escrita, fuera del `try` que la rodeaba.
  Habria reventado el hook, y con el la lectura del usuario, por una variable mal puesta.
- **El guardian `test_toda_variable_que_lean_los_hooks_esta_declarada_en_config` hizo su trabajo**:
  `LD_HOOK_READ_BLOQUEAR` se quedaba sin declarar en `config.py` y la suite lo dijo sola.
- **El test de cruce instalador-script** (`test_enable_read_hook_deja_TAMBIEN_el_hook_de_shell_...`)
  se verifico con control positivo: rompiendo el import del hook, falla con el traceback del
  `ModuleNotFoundError`. Sin eso seria un test que pasa en vacio.

### Decisiones de diseno que salieron de medir, no de opinar

- **La salud del backend no puede salir de las delegaciones anteriores.** Seria un circulo cerrado:
  sin delegaciones no hay marca fresca, sin marca fresca no se bloquea, y sin bloqueo no hay
  delegaciones. Con adopcion cero medida cuatro veces, la regla no habria arrancado nunca. El hook
  sondea el backend el mismo, con 300 ms de plazo y la respuesta cacheada un minuto.
- **La «version» del hook es la huella sha256 del script**, no una constante. El repo ya tiene
  cuatro sitios con el numero de version y un `--check` que los compara; un quinto seria otra
  fuente de verdad que se desincroniza. Lo que hace falta saber al leer una medicion no es que
  release estaba instalada, sino si el script que corrio era el nuevo o el viejo.
- **El identificador del bloqueo no viaja por el agente.** El hook deja una nota en disco con el id
  y una **huella** de la ruta —no la ruta: hereda la regla de la telemetria—, y el servidor la
  recoge cuando le llega una tool con ese mismo `path`. Pedirle al agente que lo pase seria
  depender de que obedezca, que es justo lo que se quiere medir.
- **El formato de esa nota vive en dos sitios** (lo escribe un hook stdlib puro, lo lee el
  servidor), asi que `tests/test_correlacion.py` va de **ida y vuelta**: escribe con el hook de
  verdad y lee con el servidor de verdad. Misma cautela que el test de paridad del espejo JS.

### Suite

`uv run pytest -q`: **941 passed, 2 skipped**.

Dos tests de `test_dashboard_ui.py` (paginacion y cambio de rango) fallan por timeout de
Playwright. **No son de este cambio**: se comprobo con `git stash`, y fallan igual en `main` sin
nada de F0 ni F1 aplicado. Quedan anotados como defecto aparte.

### Lo que F1 deja pendiente

- **Tareas 10 y 11**: la medicion de la guarda «acotada» con su criterio escrito antes (REQ-F1-8),
  el criterio de la quinta medicion (REQ-F1-12), el panel y la documentacion (wiki y README).
- **El bloqueo esta apagado** y no se enciende hasta que la tarea 10 deje escrito el criterio de
  exito **y el de abandono**.
- **Falta la prueba end-to-end en Windows con el hook instalado de verdad**, disparando sobre una
  lectura real. Los tests cubren el script y el instalador por separado y tambien cruzados, pero la
  regla del repo es no publicar un hook sin verlo dispararse instalado.


## Criterio de la quinta medicion (REQ-F1-12)

**Escrito el 2026-09-12, con el bloqueo todavia apagado.** Va antes de encenderlo a proposito:
despues de cuatro mediciones con adopcion cero, un criterio decidido a posteriori no vale nada:
siempre se encuentra la forma de leer el dato como si hubiera salido bien.

### Que se mide, y con que

`python scripts/medir_adopcion.py --desde <fecha en que se encendio>`. El cruce lo hace el
programa: cada bloqueo lleva un identificador que el evento de la tool recoge por disco. Las cuatro
mediciones anteriores ataron los dos logs a mano, y por eso la pregunta central se quedo sin
responder.

- **Ventana**: 7 dias naturales desde que se encienda `LD_HOOK_READ_BLOQUEAR=1`, y como minimo
  **30 bloqueos**. Si en 7 dias no se llega a 30, se alarga hasta llegar, porque una tasa sobre
  cinco casos no distingue nada.
- **Denominador**: todas las lecturas vistas por los dos hooks, `read` y `shell`. Contar solo el
  camino cerrado es lo que dejaria subir la adopcion sin ahorrar un token.
- **Solo se cuentan eventos con `version` de script**, y si la ventana mezcla dos versiones, el
  propio script lo avisa: una sesion abierta hereda el entorno del lanzador.

### Numeros que se declaran de antemano

| Medida | Como se lee |
| --- | --- |
| **Tasa de aceptacion** = bloqueos que acabaron en una llamada `local_*` correlacionada / bloqueos | El numero principal |
| **Escapes** = lecturas por franjas del mismo fichero justo despues de un bloqueo | Lo que mide la molestia |
| **Desvio** = volcados por shell contados frente a lecturas por la tool `Read` | Si la conducta se mudo de sitio |
| **Delegaciones espontaneas** | Control: lo que el agente ya hacia solo, que no se puede apuntar la regla |

### Que resultado retira el cambio

El bloqueo se **apaga y se revierte** si se cumple cualquiera de estas tres:

1. **Tasa de aceptacion por debajo del 50 %**. Si menos de la mitad de los bloqueos acaban en
   delegacion, la regla no esta encaminando trabajo: esta estorbando.
2. **Mas del 30 % de los bloqueos acaban en un escape** —el mismo fichero leido por franjas justo
   despues—. Eso significa que el caso acotado esta mal elegido: se estaria bloqueando lectura que
   hacia falta literal.
3. **El usuario lo apaga a mano una sola vez.** No hace falta un umbral para esto: si molesta lo
   suficiente como para apagarlo, la regla ya fallo. El apagado queda registrado en el evento.

Y se considera **un exito**, con el bloqueo encendido para quedarse, si la tasa de aceptacion pasa
del 70 % y los escapes se quedan por debajo del 10 %.

### Lo que NO se va a concluir

- Que la regla «funciona» porque suban las delegaciones totales: pueden subir por las espontaneas,
  que es justo lo que el agente ya hacia. Solo cuentan las correlacionadas.
- Que la guarda de «lectura acotada» sobra o hace falta con los datos de hoy: **no se puede**. La
  huella de ruta que permite agrupar por fichero se anadio ahora, asi que los 277 silencios ya
  registrados no son agrupables. La pregunta se responde en esta quinta medicion, no antes.


## F1 - Prueba end to end con los hooks instalados (tareas 10 y 11)

La regla del repo es no dar un hook por bueno sin verlo dispararse **instalado**. Se instalo en un
HOME de prueba (`install --home ... --enable-read-hook`) y se ejecutaron los comandos **tal y como
quedaron en `settings.json`**, contra el backend real de la maquina.

Registro: `3 registrado(s): UserPromptSubmit, PreToolUse/Read, PreToolUse/Bash|PowerShell`, y
`4 script(s)` copiados.

| Caso | Resultado |
| --- | --- |
| `.md` de 40 KB entero, por la tool `Read` | **deny** |
| `.json` de 40 KB entero | aviso, sin bloqueo |
| `.md` pedido por franjas (`limit: 20`) | silencio |
| `cat informe.md` | **deny** |
| `cat informe.md \| head -5` | silencio |

Y el circuito completo, con la nota que dejo el hook instalado:
`server._bloqueo_reciente(...)` devolvio `4e889edd5c64`, y `None` para otra ruta.

### Dos defectos que solo aparecieron al ejecutarlo de verdad

**1. El 401 no significa «no hay backend».** La primera pasada no bloqueo nada, y no era el hook:
el sondeo hacia `GET /v1/models` sin credencial y recibia **401**, que se leia como «no esta».
Pero el hook casi nunca tiene la clave —la tiene el lanzador del daemon, y el hook hereda el
entorno del cliente, que es el mismo motivo por el que `--mcp-mode http` existe—, asi que el
bloqueo habria quedado apagado para siempre en cualquier maquina con el backend protegido, que es
la configuracion recomendada. Comprobado en vivo: `GET /v1/models` sin credencial responde 401 y el
backend estaba perfectamente.

La pregunta correcta no es «me autoriza» sino «hay alguien escuchando»: quien delega es el servidor
MCP, que si tiene la credencial. Ahora cualquier respuesta por debajo de 500 cuenta como backend
vivo, y solo la falta de respuesta —conexion rechazada o plazo agotado— cuenta como ausente.

**2. La marca de salud era global y se heredaba entre endpoints.** Lo destapo el test de cruce del
instalador, que apunta a un puerto donde no hay nadie y aun asi recibio un bloqueo: la marca escrita
por el backend de verdad, minutos antes, seguia fresca. Ahora el fichero lleva la huella de
`LOCAL_DELEGATE_BASE_URL` en el nombre, con su test.

Los dos son el mismo tipo de fallo —lo que funciona en la suite no funciona instalado— y ninguno de
los dos habria aparecido sin ejecutar el hook de verdad.

### Medicion: el denominador de hoy, antes de encender

`python scripts/medir_adopcion.py --desde 2026-09-08T23:03`, que es cuando arranco el experimento
del umbral:

| Medida | Valor |
| --- | --- |
| Lecturas vistas | 460 |
| acotada / pequeno / codigo | 252 / 76 / 47 |
| Ofrecidos | 85 |
| Bloqueos | 0 (el bloqueo esta apagado) |
| Delegaciones | 5, **todas espontaneas** |

Coincide con la cuarta medicion, que es lo que tenia que pasar: todavia no ha cambiado nada de
conducta. El script avisa por su cuenta de que hay eventos sin version de script, o sea anteriores
a que se registrara.

**De los 252 silencios por «lectura acotada» no se puede decir nada todavia**, y eso es un limite
real de REQ-F1-8: la huella de ruta que permite agrupar por fichero se anadio ahora, asi que lo ya
registrado no es agrupable. La pregunta se responde en la quinta medicion. Verificado end to end
que la agrupacion funciona: en la prueba instalada, la franja y la lectura completa del mismo
fichero compartieron `path_sha`, y dos ficheros distintos dieron huellas distintas.

### Documentacion (tarea 11)

Una release toca **tres** sitios, y aqui fueron cuatro. Dos de ellos estaban **desfasados de
antes**, no por este cambio:

- `README.md` recomendaba `PreToolUse`/`Bash` «(salidas largas de lint/tests)», un hook
  (`suggest_lint_summary.py`) **retirado en la 0.27.0**.
- `docs/recipes/claude-code-hooks.md` documentaba las bandas como «8-32 KiB» y «mas de 32 KiB»,
  cuando son 8 y 100 desde el mismo cambio que bajo el umbral.
- `docs/wiki/Savings-and-metrics.md` afirmaba que cruzar una sugerencia con una delegacion «seria
  inventar una correlacion», que era cierto hasta este cambio y ya no.
- `docs/wiki/Configuration.md` no tenia seccion de hooks de lectura; ahora la tiene, con las cinco
  variables y las tres formas de que no bloquee.

## Encendido del bloqueo: 2026-09-12

Encendido en esta maquina a las **03:5x UTC del 2026-09-12**, con el criterio de la quinta
medicion ya escrito mas arriba. La ventana de 7 dias y los 30 bloqueos minimos cuentan desde aqui.

### Que se toco, exactamente

| Sitio | Cambio |
| --- | --- |
| `~/.claude/settings.json`, bloque `env` | `LD_HOOK_READ_BLOQUEAR=1` |
| Paquete de `uv tool` | reinstalado **desde el repo** (`uv tool install --force .`), rama `f0-clasificar-fallos` |
| `~/.claude/hooks/local-delegate/` | 4 scripts, con `suggest_delegate_shell.py` nuevo |
| `settings.json`, `hooks.PreToolUse` | 3 registrados: `Read`, `Bash\|PowerShell`, `UserPromptSubmit` |
| Daemon | parado, actualizado y rearrancado (pid nuevo) |

El interruptor va en `settings.json` y no en el entorno del shell **porque los hooks heredan el
entorno del lanzador de Claude Code**, no el de la sesion interactiva. Es el mismo sitio donde ya
vivia `LD_HOOK_TELEMETRY_LOG`. Se comprobo ademas que `install` no se lo lleva por delante al
reescribir la seccion de hooks.

**El daemon corre codigo sin publicar, a proposito.** El lanzador
(`D:\Projects\llms\llama-swap\start-local-delegate-secure.ps1`) apunta al paquete de `uv tool`, que
ahora sale del repo y no de PyPI. Cuando se publique la 0.28.0 hay que reinstalar desde PyPI para
que la maquina vuelva a parecerse a la de cualquier usuario.

### Verificacion en produccion, no en la suite

Los hooks **instalados**, ejecutados con el entorno real —sin `LOCAL_DELEGATE_API_KEY`, que es lo
que tiene el hook de verdad—:

| Caso | Resultado |
| --- | --- |
| `README.md` entero (27 KB) por la tool `Read` | **deny** |
| `README.md` con `limit: 40` | silencio |
| `uv.lock` (grande, no es prosa) | aviso |
| `cat README.md` | **deny** |

Y el circuito completo contra el **daemon de verdad**: tras ese bloqueo se llamo a
`local_summarize(path=README.md)` por MCP, y el evento quedo escrito con
`"bloqueo_id": "461c4de109cb"`. Es la primera vez que este repo puede decir «este aviso acabo en
esta delegacion» sin cruzar nada a mano.

`scripts/medir_adopcion.py` sobre esos minutos: 2 bloqueos, 1 aceptado, tasa 0.5, y el desglose
por camino (`read` 9, `shell` 12). Son datos de la propia prueba, no de uso real: la ventana que
cuenta empieza ahora.

### Como se apaga

`LD_HOOK_READ_BLOQUEAR` a `0` en `~/.claude/settings.json`, y surte efecto **en la siguiente
invocacion del hook**, sin cerrar nada. Las sesiones ya abiertas cuando se encendio siguen con el
valor viejo, que es la trampa de medicion conocida: la ventana solo cuenta sesiones nuevas.

## F2: la mitad que depende de la maquina, hecha (2026-09-12)

El usuario activo **«Prefer No Sysmem Fallback»** desde la NVIDIA App, sobre `llama-server.exe`
(perfil por programa, no global). La maquina es una **RTX 5060 Ti de 16 GB con driver 616.92**.

**Sin verificar todavia, y no es un detalle:** el panel no confirma nada y `nvidia-smi` no expone
esa politica, asi que solo se comprueba **por su efecto** —un modelo que no quepa tiene que fallar
con error de memoria en segundos, en vez de cargar y arrastrarse—. Ese es el control positivo del
protocolo de F2 y va **antes** de cualquier medida.

**Trampa anotada antes de tropezar con ella:** el perfil se guarda **por ruta de ejecutable**. F2
necesita llama.cpp **b10909 en carpeta aparte**, y ese sera otro ejecutable para el driver
(`D:\Projects\llms\llamacpp-b10909\llama-server.exe` o como se llame). Si no se le anade su propio
perfil, la medicion vuelve a correr con el desbordamiento silencioso a RAM activado — que es
exactamente el error que descarto `gpt-oss-20b` en julio. El ejecutable de produccion hoy es
`D:\Projects\llms\llamacpp\llama-server.exe` (9 KB: es un lanzador, el trabajo CUDA lo hacen las
DLL de al lado, pero es el proceso que crea el contexto y por tanto el que lleva el perfil).

## F2: tarea 13, la sonda de recursos por proceso (2026-09-14)

Dentro de `src/local_delegate/benchmark.py` (`ProcessProbe`, `TypeperfStream`, `ResourceSampler`,
`summarize_resources`), con `--probe-process` y `--gpu-luid` en el CLI y el envoltorio
`scripts/sonda_recursos.py` para `llama-bench`. Apagada por defecto: sin el flag, cada registro
lleva el bloque `resources` con `enabled: false` y los campos vacios, que es el rollback del plan.
Sin dependencias nuevas.

### Lo que se probo al reves, y lo que cambio por ello

Ocho mutantes sobre el codigo, cada uno contra su test y mirando **que assert dispara**:

| Mutante | Resultado | Assert que lo mata |
| --- | --- | --- |
| parseo sin filtro de LUID | muere | la cabecera trae 4 columnas en vez de 2 |
| `-1` tratado como valor | muere | `process_gone` sale `False` |
| no relanzar el flujo al cambiar de PID | muere | `[40160] == [40160, 31776]` |
| cero muestras no anula | muere | `zero_vram_samples` en vez de `zero_ram_samples` |
| sin lectura sincrona al salir | muere | 1 muestra en vez de 2 |
| dos `llama-server` vivos no anula | **sobrevivio**, luego muere | — |
| el runner no escribe `resources` | muere | `KeyError: 'resources'` |
| working set devuelto como RAM privada | **sobrevivio**, luego muere | «lo mapeado NO puede subir la privada» (129 MiB contra 32) |

Los dos supervivientes eran huecos de la prueba, no de la sonda:

- **«Varios procesos»** solo se probaba sobre el resumen con muestras fabricadas; nadie ejercitaba
  que `ProcessProbe` lo detectara. Test nuevo contra la sonda.
- **El control positivo no distinguia un contador del otro.** Reservaba memoria anonima, que sube
  la privada **y** el working set por igual, asi que devolver uno por otro pasaba. Es exactamente la
  diferencia que decide CP-2b. Ahora son tres hijos —quieto, 128 MiB anonimos, 128 MiB mapeados
  desde fichero y leidos— y lo mapeado tiene que subir el working set **sin** subir la privada: la
  mitad negativa del control de la tarea 12, que el test habia perdido.

### Contra procesos reales de esta maquina, sin tocarla

Ni modelo cargado ni daemon parado; solo lecturas.

```text
luid resuelto: 0x00000000_0x0000F722
llama-swap: [16916] muestras 4 ram 4 vram 0 privada MiB 56.3 ws MiB 13.4 annul zero_vram_samples
dwm: [1556] muestras 10 ram 0 vram 5 dedicada MiB 9236.0 shared MiB 3.5 annul zero_ram_samples stream_error None
motivos: ['no_access']
typeperf vivos tras cerrar: []
```

- El LUID se resuelve solo y coincide con el emparejado a mano en la tarea 12.
- `llama-swap.exe`: 56,3 MiB, el mismo numero que .NET; no usa la GPU y la corrida sale anulada por
  `zero_vram_samples`, que es lo correcto.
- `dwm.exe`: el `typeperf` real da 5 muestras de VRAM en 4,5 s (el resto es el arranque de ~2 s) y
  la RAM sale `no_access`: sin elevar no se abre un proceso de otra sesion. Al cerrar no queda
  ningun `typeperf` vivo.

### Suite

`uv run pytest -q`: **983 passed, 2 skipped**. 27 tests nuevos en `tests/test_sonda.py`, tres de
ellos solo Windows con marca declarada. `ruff check .` y `ruff format --check .` limpios.

### Lo que la tarea 13 deja para la 18

- **Que `llama-server.exe` sea el proceso con la memoria.** El de produccion es un ejecutable de
  9 KB que carga las DLL en el mismo proceso; si el de b10909 lanzara un hijo con otro nombre, la
  sonda mediria el cascaron. CP-2 lo caza —dos modelos darian el mismo numero—, pero hay que
  mirarlo con `witr --pid <pid> --tree` antes de dar CP-2 por bueno.
- **Que `OpenProcess` abra el `llama-server.exe` que lanza llama-swap.** Deberia, porque corre como
  el mismo usuario (comprobado con `witr` en la tarea 12), pero solo se ve con el proceso vivo.
- **El primer run tras un cambio de modelo sale `process_changed`** si el `llama-server` anterior
  seguia vivo al entrar: los picos mezclarian dos procesos. Es correcto anularlo, y obliga a la
  tarea 16 a precalentar cada modelo antes de su primer run medido.

## F2: tarea 14, el corpus v2 congelado (2026-09-14)

`scripts/construir_corpus.py` congela las fuentes en `benchmarks/catalogo-2026-09/fuentes/`, emite
`cases.json` (schema 2) y `conteos-log.json`, y `benchmark.load_corpus` las carga verificando el
hash de cada fuente y de la imagen de control. La tarea 16 conecta ese cargador al runner.

### Las reglas se comprobaron contra produccion, no contra la tabla

El constructor llama a **la tool real** con `_run_chat` interceptado (sin backend, sin log de uso,
sin las variables `LOCAL_DELEGATE_*`) y registra el modelo que elige y las llamadas que hace:

```text
ok: 15 casos de calidad, 2 sondeos, 1 control
  resumen-md-2k            mechanical llamadas=1   chars=2010 bytes=2036
  extraer-toml-2k          mechanical llamadas=1   chars=2056 bytes=2075
  clasificar-53            mechanical llamadas=1   chars=53 bytes=54
  traducir-42              mechanical llamadas=1   chars=42 bytes=43
  delegar-56               mechanical llamadas=1   chars=56 bytes=56
  resumen-md-10k           long       llamadas=1   chars=10331 bytes=10480
  resumen-changelog-43k    long       llamadas=1   chars=43293 bytes=44120
  extraer-uvlock-48k       long       llamadas=1   chars=48000 bytes=48000
  lint-33k                 long       llamadas=1   chars=33343 bytes=33347
  commit-diff-19k          code       llamadas=1   chars=19041 bytes=19089
  explicar-metrics-15k     code       llamadas=1   chars=15400 bytes=15468
  explicar-install-20k     code       llamadas=1   chars=20000 bytes=20171
  boilerplate-156          code       llamadas=1   chars=156 bytes=158
  describir-dashboard      vision     llamadas=1   chars=None bytes=718456
  leer-cifras-dashboard    vision     llamadas=1   chars=None bytes=718456
  techo-resumen-103k       long       llamadas=5   chars=102987 bytes=106092
  techo-commit-156k        code       llamadas=13  chars=155713 bytes=157873
```

La primera pasada **no escribio el corpus**: seis ids prometian un tamano que la fuente no tenia,
y `pyproject.toml` entero habria ido a `long`. Correcciones y razones en `protocolo-f2.md` §4.4,
«Resultado de la tarea 14», junto con el hallazgo de que las seis cifras grandes del dashboard son
identicas en las dos imagenes del control de CP-3.

### Conteos del log, emitidos por el programa

152 eventos, 146 de tools `local_*`, 18 troceados; por modelo 54/50/36/4/2. Coinciden con §4.2. Y
uno que **no** coincidia: los `inline` son **50 de 146**, no «56 de 146» —56 es sobre los 152—, el
mismo cruce de denominadores que §11 daba por corregido. Corregido en el protocolo y en el plan.
59 eventos con ruta de fuera del repo se cuentan y no se nombran.

### Lo que se probo al reves

Once mutantes, todos muertos por su assert: sin regla de rol, de una llamada, de entrada entera,
de techo que cabe, de terminos en la fuente; rutas de fuera del repo contadas; log de uso sin
interceptar; eventos no locales contados; hash sin verificar; control sin verificar; y ruta viva
aceptada en `source_file`.

Este ultimo **moria por la razon equivocada** en la primera version del test: sin la regla, la
carga fallaba porque la ruta viva no existia en la copia temporal, y el test pasaba por un mensaje
que no casaba. Ahora el test pone un fichero real con su hash correcto en esa ruta, y solo la regla
del nombre puede pararlo.

Revisando los datos derivados salieron dos defectos que ningun test habia visto: `extraer-uvlock`
tenia como termino esperado `'1'` (sale de `version = 1` y aparece en cualquier respuesta), y los
nombres de fuente salian en minusculas porque `normcase` se aplicaba al nombre y no solo a la
comparacion. Los dos corregidos.

### Suite

`uv run pytest -q`: **1000 passed, 2 skipped**. `ruff check .` y `ruff format --check .` limpios.
Fuentes con `-text` en `.gitattributes`, comprobado con `git check-attr`. Y un fallo de la tarea 13
que salio aqui: `scripts/sonda_recursos.py` se commiteo **sin el bit de ejecucion** y
`test_un_script_con_shebang_esta_marcado_ejecutable_en_git` solo lo ve una vez el fichero esta en
git —la segunda mitad de la leccion que ese test documenta—. Corregido con `git add --chmod=+x`.

## F2: tarea 15, las parejas de referencia de CP-4 (2026-09-14)

Cinco parejas `reference_ok` / `reference_bad`, una por senal que se puede ejercitar con texto. No
se escriben en `cases.json`: las define y las emite `scripts/construir_corpus.py`, que no escribe
el corpus si una pareja no cumple. Detalle y razones en `protocolo-f2.md`, CP-4, «Resultado de la
tarea 15».

```text
resumen-md-2k         cobertura    154 154
extraer-toml-2k       json_valido   98  98
extraer-uvlock-48k    json_campos   78  78
describir-dashboard   unicode       86  86
leer-cifras-dashboard prohibido     62  62
```

### Que cada pareja difiera solo en su senal lo decide un oraculo, no el puntuador

`senales()` calcula por su cuenta cobertura (normalizada y literal), termino prohibido, JSON valido
y campos. Es independiente del puntuador de la tarea 16 **a proposito**: CP-4 valida ese puntuador,
y si compartieran codigo compartirian el error. Una pareja pasa si tiene la misma longitud, la buena
es buena en todas las senales, y el conjunto de senales en que difieren es exactamente el esperado.

### Lo que se probo al reves

Seis mutantes, todos muertos por su assert: sin comprobar longitud; aceptar una diferencia de mas;
normalizar sin quitar acentos (cae la pareja de Unicode versionada, porque la buena deja de cubrir
`computo`); aceptar una buena que no es buena; referencias fuera de los campos vigilados; y una
referencia retocada a mano en el JSON.

**El de los campos vigilados sobrevivio a la primera.** Quitar `reference_ok` y `reference_bad` de
lo que `--comprobar` compara contra el constructor no rompia nada, porque con el JSON intacto no hay
diferencia que ver. El mutante del dato retocado si moria, pero lo cazaba el oraculo, no la
vigilancia. Test nuevo: retoca una referencia en una copia **sin romper la pareja** («Guía» por
«Guia», misma longitud, sigue difiriendo solo en cobertura), de modo que solo la vigilancia puede
verlo.

### Dos precisiones que heredan la tarea 16 y CP-4

- La normalizacion de §4.7 es **NFKD, quitar marcas combinantes y `casefold`**. NFKD solo deja el
  acento como marca suelta; hay un test que lo demuestra.
- En la pareja de Unicode la cobertura **literal** no cambia: las dos respuestas fallan sin
  normalizar. Por eso `describir-dashboard` gana el termino `computo`, sin acento, frente a un panel
  que dice «cómputo».

### Suite

`uv run pytest -q`: **1007 passed, 2 skipped**. `ruff check .` y `ruff format --check .` limpios.

## F2: tarea 16, el runner del corpus v2 (2026-09-14)

`local-delegate benchmark` carga solo el corpus v2 (**breaking**: el de julio ya no carga y se
conserva como archivo), manda el prompt de produccion de cada caso sobre su fuente congelada, y
puntua segun §4.7. Detalle de las decisiones que el protocolo no fijaba en `protocolo-f2.md` §4.7,
«Resultado de la tarea 16». Documentado en el CHANGELOG (entrada BREAKING), en
`docs/wiki/Backend-versions.md` y en `benchmarks/moe/README.md`. El README del proyecto no menciona
`benchmark` en ningun sitio, asi que no tenia nada que cambiar.

### En rojo antes de arreglarlo

El defecto literal de julio, con el puntuador de antes y la respuesta correcta en espanol:

```text
puntuador de hoy, respuesta correcta en espanol: {'expected_terms': 2, 'matched_terms': 1, 'term_coverage': 0.5}
```

### Lo que se verifico contra el motor, y lo que queda para la tarea 19

Buscado en los binarios de b9925: `llama-server-impl.dll` contiene `exceed_context_size_error`,
`chat_template_kwargs`, `enable_thinking` y `reasoning_content`. **No** esta comprobado que b10909
conteste asi un desborde real ni que un razonador respete `enable_thinking: false`; el runner guarda
`error_body` y `reasoning_chars` para poder reclasificar sin repetir la tanda.

### CP-4 ya corre

`test_cp4_el_puntuador_separa_cada_pareja_por_su_senal` puntua las cinco parejas del corpus y exige
que cada una se separe **por su componente**; otro test comprueba que un puntuador literal no
separaria la pareja de Unicode. Estan en verde en cada commit.

### Lo que se probo al reves

Catorce mutantes sobre el runner y el puntuador, todos muertos por su assert: sin normalizar;
prohibido que no hunde; truncado que puntua; JSON invalido que no hunde; `zero_by` sin anotar;
truncado que no se repite; rechazo por contexto leido como error, y **cualquier** 400 leido como
rechazo (los dos sentidos); configuracion leida como truncado; sin `image_url`; `off` enviado como
`reasoning_effort`; el modelo mandando sobre el caso; frio en cada caso como en julio; y el control
de CP-3 ignorado. Dos caen por consecuencia y no por un assert directo, y valen: «configuracion como
truncado» cae al desempaquetar porque la corrida se repitio, y «sin `image_url`» por un `TypeError`
al indexar un texto donde tenia que haber bloques.

Y un decimoquinto, el que importa del constructor, **murio por la razon equivocada a la primera**:
«recongelar siempre» hacia caer el test en `construir(...) == 0` —la construccion fallaba por otra
regla, porque el CHANGELOG vivo ya traia la entrada nueva—, no en la marca de la fuente congelada.
Tras una release que no moviera ese tamano habria sobrevivido. Se reordenaron los asserts y ahora
cae en la comparacion de la marca (`test_corpus.py:352`).

### Un defecto que salio al hacerlo

Regenerar el corpus para anadir el prompt de los sondeos de techo **recongelo dos fuentes desde los
ficheros vivos**: `resumen-changelog-43k` (el CHANGELOG ya traia la entrada de esta tarea) y
`lint-33k` (ruff sobre un `src/` modificado). Lo delato la regla del tamano del id, que hizo que el
corpus no se escribiera; `git status` confirmo las dos. Restauradas desde git; la copia congelada
se reutiliza y recongelar exige `--refrescar-fuentes`. Tras el arreglo, reconstruir cambio solo los
cuatro campos de prompt de los dos sondeos (8 lineas de `cases.json`), y ninguna fuente.

### Suite

`uv run pytest -q`: **1024 passed, 2 skipped**. `ruff check .` y `ruff format --check .` limpios.

## F2: tarea 19, CP-3 y CP-4 contra la maquina, y lo que el piloto obligo a cambiar (2026-09-14)

Sesion 2 de §10 (20:09-20:58 UTC). Perfil del driver movido a b10909 y medido antes (b10909 OOM,
b9925 carga desbordando 6 053 MiB) y devuelto a produccion y medido al cerrar (b9925 no carga,
b10909 desborda 5 958 MiB). Daemon arriba y `local_status` verde al terminar. Resultados y lectura
caso a caso en `protocolo-f2.md` §2 «Resultado de CP-3».

### CP-4 pasa; CP-3 no

CP-4 es un test desde la tarea 16 y pasa. CP-3 no pasa en `code` ni `mechanical`, y leyendo las
salidas casi siempre por el corpus: terminos unicos o privados que la respuesta buena no nombra, un
suelo en el changelog, `boilerplate` en techo con codigo roto, y dos defectos del runner (truncado
repetido «sin puntuacion»; corrida anulada que no se repetia pese al comentario).

### Lo que se cambio, con decision del usuario

Commit `27e2020`: terminos derivados por regla escrita en `commit-diff-19k`, `explicar-*` y el
changelog (ahora `resumen-changelog-7k`). Despues: truncado repetido puntua 0, la anulada se repite
hasta 2 veces y el analisis juzga por el ultimo intento, `boilerplate-156` se puntua ejecutando el
codigo generado (sexta pareja de CP-4, senal `ejecucion`), y §7 decide por velocidad un rol con
todos los casos en techo. P-9 resuelta: el piloto se repite entero.

### Lo que se probo al reves

Cinco mutantes sobre las reglas de terminos, todos muertos en su assert. Doce sobre el runner, el
arnes de ejecucion, el analisis y el oraculo (script `mutantes.py` que muta el fichero real, corre
solo sus tests y restaura; `git diff --stat` identico antes y despues), todos muertos: sin repetir
la anulada, sin tope, `repeated` ignorado, entorno heredado, primera linea en vez de la ultima (un
`print` del codigo fingiria el resultado), sin comprobar el tipo, sin quitar vallas, descartada por
cualquier intento, truncado repetido sin calidad, nunca todos en techo, basta un caso en techo y
oraculo que siempre ejecuta bien.

**Dos controles que no controlaban, encontrados mirando QUE assert caia:**

- El mutante «sin comprobar el tipo» **habria sobrevivido**: ningun test pedia `int` frente a
  `45.0`. Se anadio `test_el_valor_correcto_con_otro_tipo_no_pasa` antes de correrlo.
- «Descartada por cualquier intento» moria en el veredicto y no en el assert de la corrida: el test
  cogia `corridas[0]`, que por el orden de `ts` era la corrida 2. Ese assert no probaba nada. Ahora
  elige la corrida por numero y exige sus dos intentos, y el mutante cae ahi.

Y un error de lectura propio, corregido en el protocolo y en el vault: el informe llamo «inventado»
al `chore: update version to 0.7.0` del 14B sin mirar el diff, que si sube a 0.7.0.

### Suite

`uv run pytest -q`: **1081 passed, 2 skipped**. `ruff check` y `ruff format --check` limpios en
`src`, `scripts` y `tests`. `construir_corpus.py --comprobar`: ok.

## F2: tarea 20, la tanda y el veredicto por rol (2026-09-14 a 2026-09-15)

Sesiones 4 y 5 de §10. PRs #180 (P-13 y P-14), #181 (`n_ctx` y KV medidos), #182 (barrido de
`-ncmoe`) y #183 (la tanda y las reglas que corrigio), todos mezclados con el CI entero en verde.
Resultado y salvedades en `protocolo-f2.md` §7 «Resultado de la tarea 20»; informe del programa en
`resultados/decidir-final.md`.

### El veredicto

| Rol | Veredicto | Lo decide |
| --- | --- | --- |
| `mechanical` | no se cambia `gemma3-4b` | todo en techo, empate de latencia |
| `long` | **Gemma 4 26B-A4B** sustituye a `llama31-8b` | pares 15 a 0; ademas 1,8 s contra 3,0 s |
| `code` | **Qwen3.6-35B-A3B** sustituye a `qwen25-coder-14b` | pares 15 a 0; techo 157 873 contra 20 171 bytes; mitad de latencia |
| `vision` | sin agregado; Gemma 4 12B mejor caso a caso | 1,0 y 1,0 contra 0,75 y 0,67 |

### Lo que la maquina obligo a cambiar, con decision del usuario

- **El perfil del driver es por ejecutable**: `llama-bench.exe` desbordaba sin avisar y el primer
  barrido no valia (Qwen3.6 con `-ncmoe 4` corria a 91 tok/s y no cabe). Entrada propia, medida por su
  efecto con `-v` y un control negativo.
- **Los cuatro candidatos piensan por defecto** y devolvian vacio: corren con `--reasoning-effort off`.
- **Techo en config aparte con la misma `--label`**: con el `n_ctx` de calidad los sondeos median la
  ventana. §6 compara `n_ctx` por tipo de caso.
- **Umbral de `Shared Usage` 1 024 MiB** (estaba en 0 sin calibrar y nada era concluyente).
- **Latencia sobre casos comunes**: el vigente de `long` no termino nunca `lint-9k` y vetaba al
  candidato.
- **Gemma 4 12B necesita `--ubatch-size 2048`**, y **un reinicio de Windows reasigna el LUID de la
  GPU**: el script ya no lo fija, y el del perfil lo resuelve solo.

### Lo que se probo al reves

- Mutantes muertos, cada uno por su assert: resta de picos y VRAM ausente como cero en la RAM del host;
  los dos limites del presupuesto de uso diario; §6 sin agrupar por tipo, `_pico` contando el techo y
  §6 solo con calidad; y la latencia sobre todos los casos.
- **Cada fallo se diagnostico por reproduccion y no por suposicion.** Dos hipotesis propias cayeron: que
  el 502 de `vision` fuera el `mmproj` o `--load-mode none` (era el `ubatch`), y que la falta de VRAM
  fuera un `-1` de `typeperf` (era el LUID).
- **Los 30 votos se compararon letra a letra** con los que el usuario dio en el chat: 0 diferencias, y
  las letras no son todas iguales (9/6 y 8/7), asi que no es un sesgo de posicion.
- El perfil del driver se midio al montar y al desmontar: al cerrar, b9925 da OOM y b10909 desborda
  5 985 MiB, y el daemon volvio a arrancar.

### Suite

`uv run pytest -q`: **1119 passed, 2 skipped**. `ruff check` y `ruff format --check` limpios.

## F2: tarea 21, asignacion de roles y que pasa a produccion (2026-09-15)

Detalle y lo que hereda F3 en `plan.md`, tarea 21. Prueba de carga en b9925 en `protocolo-f2.md` §10,
sesion 6.

### Roles (REQ-F2-4)

| Rol | Modelo | Criterio | Dato que lo sostiene |
| --- | --- | --- | --- |
| `mechanical` | `gemma3-4b`, **no cambia** (REQ-F2-6) | empate en techo, decide la velocidad | los 5 casos en 1,0 con los dos; 516 contra 561 ms, dentro de la banda. La regla no puede disparar en este rol: «no cambia» no distingue nada |
| `long` | **Gemma 4 26B-A4B** `-ncmoe 0` | calidad por pares | 15 a 0; `extraer-uvlock-48k` 1,0 contra 0,5; 1,8 s contra 3,0 s; techo igual (106 092 bytes) |
| `code` | **Qwen3.6-35B-A3B** `-ncmoe 8` | calidad por pares | 15 a 0; `boilerplate-156` 1,0 contra 0,8; 4,6 s contra 9,3 s; techo 157 873 contra 20 171 bytes |
| `vision` | **Gemma 4 12B** | **decision del usuario**, no de la regla | §7 sin agregado. Separa en `leer-cifras-dashboard` (1,0 contra 0,67, banda 0); en `describir-dashboard` la diferencia (0,25) iguala la banda. Mas lenta (6,1 s y 1,2 s contra 4,4 s y 0,5 s). Una sola imagen, un caso inventado |
| `fast` | `qwen35-2b`, **no cambia y no se mide** | decidido antes de medir (desviacion aprobada en el gate de plan) | 2 usos reales en tres meses; ninguna tool lo enruta; cero casos en el corpus |

**Un modelo para varios roles (P-5): no se da.** Cada rol sale con un modelo distinto, y ninguno se
midio fuera de su rol; que Gemma 4 26B-A4B cubra `vision` es una hipotesis sin dato, no un descarte.

**Revision humana (REQ-F2-2):** la cubren los 30 pares a ciegas (15 en `long`, 15 en `code`),
comprobados letra a letra contra la hoja; no se genera la hoja 0/1/2 de §4.8 (decision del usuario).

### Que pasa a produccion

**La medida es sobre b10909 y produccion corre b9925.** Se comprobo por ejecucion que los tres modelos
nuevos **cargan y generan en b9925** con el perfil del driver activo (Gemma 4 26B-A4B 14 917 MiB, Qwen3.6
14 847 MiB, Gemma 4 12B 9 549 MiB con imagen), asi que la migracion no la fuerza una incompatibilidad.
La fuerza REQ-F2-6: calidad y velocidad solo estan medidas sobre b10909. **Decision del usuario:
produccion migra a b10909 antes de que F3 toque el catalogo.** `config.py` no se toca en F2.

Salvedades que hereda F3: Gemma 4 26B-A4B `-ncmoe 0` **no cabe en el presupuesto de uso diario**
(15,1 GB de VRAM pico contra 14; la alternativa medida es `-ncmoe 4`); los candidatos van con el
razonamiento apagado; Gemma 4 12B necesita `--ubatch-size 2048`; el `n_ctx` de produccion esta por
fijar; y `fast` queda fuera de las cadenas de respaldo.

### Las cuatro tablas de §9

Pegadas por programa desde `benchmarks/catalogo-2026-09/resultados/decidir-final.md` (salida de
`analizar_benchmark.py decidir`), sin editar. El veredicto `sin_agregado` de `vision` es el de la regla;
la asignacion es la de la tabla de roles de arriba. Las anuladas son todas primeras corridas por
`process_changed` y una `zero_vram_samples`, repetidas por el runner; los `rechazo_por_contexto` son las
5 corridas de `techo-commit-156k` con `qwen25-coder-14b` (contexto nativo de 32 768 tokens, §10 sesion 5).

#### Tabla 1: por rol

| Rol | Vigente | Candidato | Calidad v / c | Banda | Latencia ms v / c | RAM host pico c | RAM privada pico c | Working set pico c | VRAM dedicada pico c | Shared pico c | Cabe uso diario c | Descartadas | Rechazos | Veredicto | Criterio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mechanical | gemma3-4b | gemma4-e4b | 1.000 / 1.000 | 0.100 | 516 / 561 | 3835772928 | 10081951744 | 3419594752 | 3477020672 | 2434793472 | si | 0 | 0 | **no_sustituye** | empate |
| long | llama31-8b | gemma4-26b-a4b | 0.500 / 1.000 | 0.000 | 3013 / 1849 | 3716284416 | 18551582720 | 3419594752 | 15100747776 | 918552576 | no | 0 | 0 | **sustituye** | calidad |
| code | qwen25-coder-14b | qwen36-35b-a3b | 0.800 / 1.000 | 0.600 | 9348 / 4619 | 6123499520 | 21017739264 | 5472796672 | 14894239744 | 3625975808 | si | 0 | 0 | **sustituye** | calidad |
| vision | qwen3-vl-8b | gemma4-12b | — / — | — | — / — | 4960354304 | 13616750592 | 3321196544 | 9496805376 | 759169024 | si | 0 | 0 | **sin_agregado** | — |

##### mechanical: no_sustituye

- nadie mejora al vigente: el rol no se cambia (REQ-F2-6)
- casos en el agregado: 0 (ninguno)
- fuera del agregado: resumen-md-2k (techo)
- fuera del agregado: extraer-toml-2k (techo)
- fuera del agregado: clasificar-53 (techo)
- fuera del agregado: traducir-42 (techo)
- fuera del agregado: delegar-56 (techo)
- **la regla no puede disparar**: ni un candidato con calidad 1,0 superaria la banda; «no se cambia» aqui no distingue nada

##### long: sustituye

- casos en el agregado: 0 (ninguno)
- fuera del agregado: extraer-uvlock-48k (techo)
- comparacion por pares (resumen-md-10k, resumen-changelog-7k, lint-9k): candidato 15, vigente 0, empates 0 -> **mejor**

##### code: sustituye

- casos en el agregado: 1 (boilerplate-156)
- comparacion por pares (commit-diff-19k, explicar-metrics-15k, explicar-install-20k): candidato 15, vigente 0, empates 0 -> **mejor**
- **la regla no puede disparar**: ni un candidato con calidad 1,0 superaria la banda; «no se cambia» aqui no distingue nada

##### vision: sin_agregado

- vision no presenta agregado (§7): decide la tabla caso a caso y la revision

#### Tabla 2: caso a caso

| Rol | Caso | Modelo | Corridas (calidad, outcome) | Mediana | Dispersion | Latencia mediana |
| --- | --- | --- | --- | --- | --- | --- |
| mechanical | resumen-md-2k | gemma3-4b | 1.00 ok fria, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 1697 |
| mechanical | extraer-toml-2k | gemma3-4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 467 |
| mechanical | clasificar-53 | gemma3-4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 71 |
| mechanical | traducir-42 | gemma3-4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 113 |
| mechanical | delegar-56 | gemma3-4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 233 |
| mechanical | resumen-md-2k | gemma4-e4b | 1.00 ok, 1.00 ok, 0.50 ok, 1.00 ok, 1.00 ok | 1.000 | 0.500 | 1731 |
| mechanical | extraer-toml-2k | gemma4-e4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 605 |
| mechanical | clasificar-53 | gemma4-e4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 85 |
| mechanical | traducir-42 | gemma4-e4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 116 |
| mechanical | delegar-56 | gemma4-e4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 267 |
| long | resumen-md-10k | llama31-8b | 0.33 ok, 0.00 ok, 0.00 ok, 0.00 ok, 0.67 ok | 0.000 | 0.667 | 4645 |
| long | resumen-changelog-7k | llama31-8b | 1.00 ok, 0.33 ok, 0.83 ok, 0.83 ok, 0.50 ok | 0.833 | 0.667 | 3837 |
| long | extraer-uvlock-48k | llama31-8b | 0.50 ok, 0.50 ok, 0.50 ok, 0.50 ok, 0.50 ok | 0.500 | 0.000 | 558 |
| long | lint-9k | llama31-8b | 0.00 truncado, 0.00 truncado, 0.00 truncado, 0.00 truncado, 0.00 truncado | 0.000 | 0.000 | — |
| long | techo-resumen-103k | llama31-8b | — truncado, — truncado, — truncado, — truncado, — truncado | — | — | — |
| long | resumen-md-10k | gemma4-26b-a4b | 0.67 ok, 0.67 ok, 0.67 ok, 0.67 ok, 0.67 ok | 0.667 | 0.000 | 2519 |
| long | resumen-changelog-7k | gemma4-26b-a4b | 0.83 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.167 | 2486 |
| long | extraer-uvlock-48k | gemma4-26b-a4b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 543 |
| long | lint-9k | gemma4-26b-a4b | 0.33 ok, 0.33 ok, 0.33 ok, 0.33 ok, 0.33 ok | 0.333 | 0.000 | 5794 |
| long | techo-resumen-103k | gemma4-26b-a4b | — ok, — ok, — ok, — ok, — ok | — | — | 3290 |
| code | commit-diff-19k | qwen25-coder-14b | 0.00 ok, 0.00 ok, 0.00 ok, 0.00 ok, 0.00 ok | 0.000 | 0.000 | 684 |
| code | explicar-metrics-15k | qwen25-coder-14b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 16359 |
| code | explicar-install-20k | qwen25-coder-14b | 0.60 ok, 0.80 ok, 0.20 ok, 0.60 ok, 0.80 ok | 0.600 | 0.600 | 11719 |
| code | boilerplate-156 | qwen25-coder-14b | 1.00 ok, 1.00 ok, 0.80 ok, 0.80 ok, 0.60 ok | 0.800 | 0.400 | 8628 |
| code | techo-commit-156k | qwen25-coder-14b | — rechazo_por_contexto, — rechazo_por_contexto, — rechazo_por_contexto, — rechazo_por_contexto, — rechazo_por_contexto | — | — | — |
| code | commit-diff-19k | qwen36-35b-a3b | 0.20 ok, 0.20 ok, 0.20 ok, 0.20 ok, 0.20 ok | 0.200 | 0.000 | 270 |
| code | explicar-metrics-15k | qwen36-35b-a3b | 0.29 ok, 0.57 ok, 0.29 ok, 0.29 ok, 0.29 ok | 0.286 | 0.286 | 4277 |
| code | explicar-install-20k | qwen36-35b-a3b | 0.40 ok, 0.80 ok, 0.60 ok, 0.40 ok, 0.40 ok | 0.400 | 0.400 | 4373 |
| code | boilerplate-156 | qwen36-35b-a3b | 1.00 ok, 1.00 ok, 1.00 ok, 0.40 ok, 1.00 ok | 1.000 | 0.600 | 9555 |
| code | techo-commit-156k | qwen36-35b-a3b | — ok, — ok, — ok, — ok, — ok | — | — | 375 |
| vision | describir-dashboard | qwen3-vl-8b | 1.00 ok, 0.75 ok, 0.75 ok, 1.00 ok, 0.75 ok | 0.750 | 0.250 | 4431 |
| vision | leer-cifras-dashboard | qwen3-vl-8b | 0.67 ok, 0.67 ok, 0.67 ok, 0.67 ok, 0.67 ok | 0.667 | 0.000 | 524 |
| vision | describir-dashboard | gemma4-12b | 1.00 ok fria, 1.00 ok, 0.75 ok, 0.75 ok, 1.00 ok | 1.000 | 0.250 | 6080 |
| vision | leer-cifras-dashboard | gemma4-12b | 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok, 1.00 ok | 1.000 | 0.000 | 1213 |

#### Tabla 3: entorno

| Modelo | n_ctx | --load-mode | -ncmoe | llama-server | llama-swap | Anuladas (motivo) |
| --- | --- | --- | --- | --- | --- | --- |
| gemma3-4b | 2560 | none | — | b10909 | v255 | — |
| gemma4-e4b | 2560 | none | — | b10909 | v255 | resumen-md-2k run=1 (process_changed) |
| llama31-8b | 36736 | none | — | b10909 | v255 | resumen-md-10k run=1 (process_changed); techo-resumen-103k run=1 (process_changed) |
| llama31-8b | 65536 | none | — | b10909 | v255 | resumen-md-10k run=1 (process_changed); techo-resumen-103k run=1 (process_changed) |
| gemma4-26b-a4b | 36736 | none | 0 | b10909 | v255 | resumen-md-10k run=1 (process_changed); techo-resumen-103k run=1 (process_changed) |
| gemma4-26b-a4b | 65536 | none | 0 | b10909 | v255 | resumen-md-10k run=1 (process_changed); techo-resumen-103k run=1 (process_changed) |
| qwen25-coder-14b | 65536 | none | — | b10909 | v255 | commit-diff-19k run=1 (process_changed); techo-commit-156k run=1 (process_changed); techo-commit-156k run=1 (zero_vram_samples) |
| qwen25-coder-14b | 7168 | none | — | b10909 | v255 | commit-diff-19k run=1 (process_changed); techo-commit-156k run=1 (process_changed); techo-commit-156k run=1 (zero_vram_samples) |
| qwen36-35b-a3b | 65536 | none | 8 | b10909 | v255 | commit-diff-19k run=1 (process_changed); techo-commit-156k run=1 (process_changed) |
| qwen36-35b-a3b | 7168 | none | 8 | b10909 | v255 | commit-diff-19k run=1 (process_changed); techo-commit-156k run=1 (process_changed) |
| qwen3-vl-8b | 8192 | none | — | b10909 | v255 | describir-dashboard run=1 (process_changed) |
| gemma4-12b | 8192 | none | — | b10909 | v255 | — |

Tanda concluyente segun §6: **si**.

#### Tabla 4: techo

| Rol | Modelo | Mayor entrada aceptada (bytes) |
| --- | --- | --- |
| mechanical | gemma3-4b | 2075 |
| mechanical | gemma4-e4b | 2075 |
| long | llama31-8b | 106092 |
| long | gemma4-26b-a4b | 106092 |
| code | qwen25-coder-14b | 20171 |
| code | qwen36-35b-a3b | 157873 |
| vision | qwen3-vl-8b | 718456 |
| vision | gemma4-12b | 718456 |

## F3: tarea 22, produccion migrada a b10909 y llama-swap v255 (2026-09-15)

Sesion 7 de `protocolo-f2.md` §10 (14:32:47-15:04:55 UTC), con la tabla de pasos y horas.

### Lo que se comprobo, y con que prueba

| Comprobacion | Prueba | Resultado |
| --- | --- | --- |
| Perfil del driver en la ruta nueva | carga de CP-1 contra los dos ejecutables | b10909 **OOM** a los 6,1 s; b9925 carga desbordando 5 885 MiB |
| v255 lee la config de produccion | arrancarlo con ella, sin cargar modelos | acepta `groups` y lista los cinco modelos |
| `apiKeys`, las dos mitades | con clave, sin clave y con clave incorrecta | 200, 401 y 401 (con clave falsa y con la real) |
| `apiKeys` con la variable ausente | arrancar v255 sin ella | **no arranca**: falla cerrado, no queda abierto |
| Catalogo vigente sobre b10909 | peticion real a cada modelo, vision con imagen | los cinco responden; el residente sigue `ready` al entrar cada modelo de `swap`; todos los `llama-server` desde `llamacpp-b10909` |
| Por el daemon, no por `curl` | `local_status`, `local_classify`, `local_describe_image` | arriba y responden; llama-swap desde `llama-swap-v255` |
| `doctor` contra la instalacion real | `uv run local-delegate doctor --config ...` | `v255` y `b10909` |

### Defecto encontrado al migrar

`doctor.detect_llamaserver_version` buscaba el primer numero tras `version:`, y b10909 imprime
`version: 0.4.0-dev (build 10909, ...)`: devolvia **`b0` sin avisar**. Dos tests nuevos, vistos en
rojo por su propio assert (`'b0' == 'b10909'` y `'b0' is None`) antes del arreglo; un mutante que
quita el parentesis obligatorio del formato viejo cae solo en el test del semver sin build; y se
comprobo despues contra el binario real.

### La Mac

Comprobada por el usuario (2026-09-15, tras la mezcla del #187): una delegacion de prueba con
`local_summarize` desde la Mac contra este backend devolvio el resumen hecho por `gemma3-4b`, el
residente, con los otros cuatro modelos sin cargar. El camino de la tailnet y la clave que manda la
Mac funcionan con v255: la tarea 22 queda verificada entera.

## F3: tarea 23, capturas reales para REQ-020 y la senal de carga (2026-09-15)

Sesion 8 de `protocolo-f2.md` §10 (15:20:58-15:24:09 UTC), con la tabla de capturas y horas.

### Las capturas, contra su clase esperada escrita antes

| Caso | Lo que devolvio el backend | Clase esperada | Clase obtenida |
| --- | --- | --- | --- |
| OOM con perfil | 500 `upstream command exited prematurely` en 4,7 s | capacidad | **capacidad** (con el patron nuevo; antes `modelo`) |
| error de carga (modelo inexistente) | el mismo 500, byte a byte, en 0,25 s | capacidad | **capacidad** |
| timeout del cliente durante la carga | `ReadTimeout`; `/running` en `starting` al vencer | capacidad | **capacidad** |
| peticion durante la carga | 200 en 7,0 s tras `starting` -> `ready` | no es fallo | **no es fallo** |
| razonamiento que agota `max_tokens` | 200, `length`, razonamiento lleno, `content: ""` | configuracion | **configuracion** (con la opcion A; antes exito vacio) |
| OOM sin perfil | 200 en 8,2 s: desborda y responde | timeout de lectura | **no capturado**: no hubo timeout |

La copia sin perfil se comprobo por su efecto antes de capturar: la carga de CP-1 da OOM a los 6,1 s
en `llamacpp-b10909` y desborda 5 887 MiB en la copia.

### Lo que se probo al reves

| Cambio | Test rojo antes del arreglo, por su assert | Mutante y donde cae |
| --- | --- | --- |
| patron de capacidad | los dos casos de capacidad daban `MODELO is CAPACIDAD` | quitar el patron: caen exactamente esos dos |
| sonda de carga | faltaban las piezas (rojo debil, por eso los mutantes) | volver a consultar tras el timeout: cae el test de la carrera (`True is False`) y el de la consulta lenta; quitar `cancelar()`: cae el camino feliz (`1 == 0`) |
| contenido vacio | unitario, captura real e integracion: `None is CONFIGURACION` y `True is False` | sin `length`: cae el control del razonamiento terminado en `stop`; sin razonamiento: cae el control sin razonamiento |

Dos controles que no controlaban, corregidos antes de fiarse de ellos:

- **El test del camino feliz usaba un retraso de 30 s**: con el `cancelar()` quitado tampoco habria
  disparado durante el test. Ahora el retraso es de 0,2 s y se espera despues.
- **El primer mutante de `cancelar()` no muto** (`server.py` es CRLF y el texto buscado llevaba LF):
  su «15 passed» no demostraba nada. Repetido con un reemplazo de una sola linea, muto y cayo.

Y un defecto propio de privacidad: la primera pasada del script de captura no saneaba las muestras
de `/running`, que llevan la linea de comando con rutas. Se corrigio antes de versionar; un test
recorre las seis fixtures buscando rutas y credenciales.

### Suite

`uv run pytest -q`: **1150 passed, 2 skipped**. `ruff check` y `ruff format --check` limpios.
`server.py` sigue entero en CRLF (0 LF sueltos).

## F3: tareas 25, 26 y 27, sin tocar la maquina (2026-09-15)

Tres commits en la rama `sdd/f3-t25-27-topes-enfriamiento-cadenas`: `39c63cd` (25), `e998cf4` (26) y
el de la 27. Ninguno tiene consumidores en las tools todavia: los usa la tarea 28.

### Tarea 25: el tope de entrada es del rol

| Test, con colision real (recargando `config`) | Rojo antes del arreglo, por su assert |
| --- | --- |
| largo = codigo, resumen de 30 000 chars | `3 == 1` llamadas |
| largo = rapido, resumen de 30 000 chars | `5 == 1` llamadas |
| largo = codigo, log de 30 000 chars | `3 == 1` llamadas |
| largo = codigo, traduccion | el final del texto no llego al backend |
| largo = codigo, extraccion | `procesados 20027 de 30000 chars` |

Mutante que hace usar al modelo principal el tope por modelo (el minimo): caen seis tests. Parchear
`config.MODEL_CODE` en caliente **no** reproducia la colision —el dict se construye al importar—, y
por eso el fixture `recargar_config` recarga el modulo con las variables puestas.

### Tarea 26: el estado de enfriamiento

Seis mutantes, cada uno en su test: sin doblar la espera, sin tope, una clase neutra que pone a cero,
N fallos tras vencer, el recorte sin guardar y sin recorte.

**Un mutante sobrevivio en la primera pasada y destapo un defecto propio.** «Sin tope» paso los 20
tests: el de Tmax miraba `restante_s`, que la lectura recortaba, y el recorte se hacia contra
«ahora» **en cada lectura**. Consecuencia real, no solo un test flojo: un vencimiento en el futuro
lejano dejaba siempre 900 s por delante y **el modelo no vencia nunca**. El test del vencimiento
lejano solo pedia `restante_s <= 900`. Arreglo: el recorte se guarda. Dos tests nuevos miran que el
modelo quede libre pasado Tmax y que la espera guardada no pase de Tmax; los dos se vieron caer.

### Tarea 27: cadenas por rol

Seis mutantes sobre `cadenas.py`, cada uno en su test: no quitar el modelo principal, no quitar
repetidos, ignorar `persistent`, coger un miembro fuera del catalogo, `none` que no desactiva, y un
desconocido que entra en la cadena (cae tambien el check del doctor). Y los dos controles que
nunca se habian visto fallar —el primer rojo fue un `ImportError` que no dejo ni colectarlos—:
volver a leer `LLAMASWAP_LISTEN` con `os.environ` hace caer el guardian (`autostart.py:54`), y quitar
la lectura al importar saca `LLAMASWAP_CONFIG` del inventario.

Dos cosas que los tests no habrian destapado solos:

- **En Windows una variable vacia no existe**: fijarla a `""` la borra. `monkeypatch.setenv` si guarda
  la cadena vacia, asi que el test de «lista vacia desactiva» pasaba y en el daemon real no se podia
  expresar. `none` tambien desactiva, con su test.
- **`fast` es inalcanzable desde las tools**, comprobado recorriendo las nueve tools de texto con un
  espia sobre `_run_chat`, con control de que el espia veia los otros tres modelos.

### Suite

`uv run pytest -q`: **1198 passed, 2 skipped**. `ruff check` y `ruff format --check` limpios. Los
recuentos del doctor (diecinueve checks) cuadran en `checks.py`, `test_checks.py` y la wiki.

## F3: tarea 24, catalogo nuevo en produccion y coexistencia con el residente (2026-09-15)

Rama `sdd/f3-t24-catalogo`. Bitacora de maquina en `protocolo-f2.md` §10, sesion 9.

### Tabla de coexistencia (REQ-F2-5)

Residente `gemma3-4b` (3 270 MiB dedicados) cargado y, a su lado, cada modelo nuevo con la entrada
mayor de su rol; perfil del driver activo, `--load-mode mmap`, video de fondo y las aplicaciones
habituales del usuario (sin Docker). «Cabe» son **cinco** condiciones: las cuatro del plan y la
enmienda (la VRAM del residente no baja mas de 256 MiB).

| Modelo | `-ncmoe` | VRAM candidato | Adaptador pico | Residente min | OOM | Responde | `Shared Usage` sube | Residente despues | Cabe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Gemma 4 12B | — | 9 060 | 13 047 | 3 270 | no | si | +289 | 0,06 s | **si** |
| Gemma 4 26B-A4B | 0 (tanda) | 14 368 | 15 928 | 806 | no | si | +300 | 1,80 s | no |
| Gemma 4 26B-A4B | 4 | 13 062 | 15 892 | 2 118 | no | si | +300 | 0,88 s | no |
| Gemma 4 26B-A4B | 8 | 11 910 | 15 889 | 3 270 | no | si | +232 | 0,08 s | si |
| Gemma 4 26B-A4B | **12** | 10 534 | 14 516 | 3 270 | no | si | +239 | 0,07 s | **si, elegido** |
| Qwen3.6-35B-A3B | 8 (tanda) | 14 328 | 15 900 | 838 | no | si | +300 | 1,72 s | no |
| Qwen3.6-35B-A3B | 12 | 12 904 | 15 895 | 2 054 | no | si | +275 | 0,90 s | no |
| Qwen3.6-35B-A3B | 16 | 11 546 | 15 652 | 3 270 | no | si | +211 | 0,09 s | si |
| Qwen3.6-35B-A3B | **20** | 10 120 | 14 228 | 3 270 | no | si | +216 | 0,06 s | **si, elegido** |

Resultado del plan: **«cabe solo con un `-ncmoe` mayor»** en los dos MoE, y el 12B cabe tal cual.
Eleccion del usuario: el menor `-ncmoe` que no desaloja **dentro de la reserva de P-14** (candidato
<= 10 993 MiB), para que un video en primer plano (1 996 MiB medidos) no vuelva a sacar al residente.
Velocidad que se pierde, en la misma prueba: 26B de 62,4 a 37,1 tok/s; Qwen3.6 de 60,0 a 39,8.

### Lo que se probo al reves

- **Las cuatro condiciones del plan no distinguian.** En la primera tanda, solo con el contador del
  adaptador, los tres «cabian»; la suma de VRAM no cuadraba y el residente tardaba 1,6-1,9 s en 8
  tokens. Con la VRAM por proceso se vio el desalojo, que no pasa por `Shared Usage`. Control
  negativo de la quinta condicion: con el 12B la VRAM del residente no se mueve.
- **La primera pasada del script no media nada**: `\Memory\Available MBytes` esta traducido en este
  Windows y `typeperf` descarta la columna sin avisar.
- **Defectos del paquete (P-16)**: con `config.py` cambiado y los tests sin tocar, `test_cadenas`
  cayo por sus asserts de defectos; tras actualizar las constantes, verde. La guarda del corpus
  (`test_corpus_versionado_sigue_reflejando_a_produccion`) cayo tambien, porque el corpus anotaba los
  modelos viejos como produccion: se regenero con `construir_corpus.py` y el diff de `cases.json` son
  solo los 12 `production.model` y los 3 de `production_config`. El constructor reescribio ademas
  `conteos-log.json` desde el log vivo, y **se restauro**: esos conteos son de F2.

### Produccion, por el daemon

| Hora UTC | Paso | Resultado |
| --- | --- | --- |
| 17:20:45-17:20:58 | `config.yaml` = `config.catalogo-f3.yaml` (sha256 `B1A4CDCA...`); respaldo `config.yaml.pre-catalogo-f3-20260915.bak` (`7858E9AB...`, el de la tarea 22) | daemon arriba |
| 17:21 | `local_status` | **catalogo viejo en el daemon**: `uv tool install --force .` reutilizo la rueda en cache (misma version 0.27.0). Largo, codigo y vision rotos hasta 17:22:21 |
| 17:22:14-17:22:21 | `uv tool install --force --reinstall --refresh --no-cache .` | `config.py` instalado con los defectos nuevos y `cadenas.py` presente |
| 17:22-17:24 | una delegacion real por rol | `local_classify` -> `bug`; `local_extract` de `extraer-uvlock-48k` (48 000 chars) -> los tres campos correctos, **sin rechazo por contexto**; `local_commit_msg` de `commit-diff-19k` -> mensaje correcto (6 011 tokens); `local_describe_image` de la imagen de control -> descripcion correcta (1 172 tokens) |
| 17:25 | residente de las cadenas | el daemon lo daba como «defecto del mecanico»: al paquete de `uv tool` le faltaba pyyaml. Reinstalado con `[llamaswap]` (17:25:08-17:25:15): `local_status` da «residente: gemma3-4b (grupo persistent «resident» de llama-swap)» y los grupos `resident` y `swap` activos |

Pendiente para la release (tarea 30): recapturar la imagen del README contra la app de metricas en el
9494; los datos de captura ya llevan los nombres nuevos.

`local-delegate doctor` desde el repo: llama-swap v255, llama-server b10909, cadenas validas con el
residente del grupo `persistent`, «todo a punto». **La Mac** sigue en 0.27.0 y pide los nombres
viejos: sus roles largo, codigo y vision fallan hasta que instale la version con los defectos nuevos
(decision del usuario: sin alias). Los modelos viejos se quedan en disco.

### Suite

`uv run pytest -q`: **1198 passed, 2 skipped**. `ruff check` y `ruff format --check` limpios sobre
`src`, `tests` y `scripts`.

## F3: tarea 28, el salto dentro de la plaza de concurrencia (2026-09-15)

Rama `sdd/f3-t28-salto`. Freno de mezcla cumplido: tarea 23 cerrada y coexistencia de la 24 en
«cabe» (PR #190 mezclado, `810f315`).

### Los escenarios, sobre un backend que responde segun el modelo

`tests/test_respaldo.py` monta el POST de chat con una respuesta **por modelo pedido** y anota la
secuencia de modelos: es lo unico que distingue un salto de un reintento. Cubre los 16 escenarios de
la spec y lo que el plan añade: tope de saltos (2 y configurable), un fallo de otra clase que corta
la cadena, REQ-008 con los dos respaldos fallando, el aviso de REQ-007 en `local_extract` y en
`local_boilerplate`, vision enfriada y sin respaldo, `local_commit_msg` en map-reduce saltando y
siguiendo con el respaldo, el map-reduce de `long` con el respaldo **muerto por construccion**
(trozos de 38 400 contra candidatos de 20 000), el modelo elegido en la pregunta como explicito,
REQ-017 con el semaforo a 1 y el camino feliz sin escribir el estado.

**El interruptor, con el caso que distingue**: con `LOCAL_DELEGATE_FALLBACK=0` y
`LOCAL_DELEGATE_COOLDOWN=0`, un 500 del principal con un fichero que ya lo enfria da el error de hoy
literal, una sola llamada y el fichero igual byte a byte; el mismo caso encendido salta sin llamar al
principal.

Rojo antes de implementar: **20 fallaron y 15 pasaron**; los 15 son los casos en que hoy tampoco se
salta, y quedan como guarda de regresion. Dos defectos del propio test salieron al leer ese rojo, no
del codigo: `backend_mock` atiende con la **primera** ruta que casa (un segundo `_backend` en el mismo
test no recibia nada), y `recargar_config` **solo añade** variables (la pasada «encendida» seguia
apagada y el test no podia distinguir). Los dos corregidos, y el test de la entrada que no cabe
asevera ahora que el mecanismo esta encendido antes de comparar.

### Mutantes

Reemplazos de una linea sobre bytes (`server.py` es CRLF), con comprobacion de que muto y
restauracion siempre; sin restos en `src` al acabar.

| Mutante | Cae en |
| --- | --- |
| respaldo ignora `LOCAL_DELEGATE_FALLBACK` | `test_con_el_respaldo_apagado_ningun_fallo_salta`, `test_con_las_dos_variables_apagadas_es_el_comportamiento_de_hoy` |
| enfriamiento ignora `LOCAL_DELEGATE_COOLDOWN` | `test_con_las_dos_variables_apagadas_es_el_comportamiento_de_hoy` |
| salta con cualquier clase | 400, backend caido, razonamiento agotado, `length` sin razonamiento, timeout con el modelo cargado |
| tercer salto | `test_como_mucho_dos_saltos`, `test_el_tope_de_saltos_es_configurable` |
| respaldo fuera del semaforo | `test_el_salto_no_suelta_la_plaza_entre_el_principal_y_el_respaldo` |
| aviso dentro del JSON de `local_extract` | `test_en_extract_el_aviso_va_en_los_metadatos` |
| aviso dentro del fichero de `local_boilerplate` | `test_en_boilerplate_el_aviso_va_en_el_recibo_y_no_en_el_fichero` |
| capacidad salta a cualquiera | `test_capacidad_del_residente_no_salta_a_un_modelo_grande` |
| `model` explicito con respaldo | los dos tests de explicito (el pedido y el elegido en la pregunta) |
| no valida el tope del candidato | la entrada que no cabe y el map-reduce de `long` |
| los trozos siguientes vuelven al modelo que fallo | traduccion en cuatro trozos y commit en map-reduce |
| el principal enfriado se llama igual | cuarta llamada tras tres fallos, enfriado sin alternativa, mecanismo encendido, vision enfriada |
| un exito sin entrada vuelve a escribir el fichero | solo `test_el_camino_feliz_no_crea_el_fichero_de_estado` |

El ultimo se hizo fino a proposito: la primera version (`if False:` en la escritura) tumbaba 24 tests
y no decia que guardaba el del camino feliz, que ya pasaba antes de implementar.

**Una guarda redundante, anotada y no quitada**: tras un fallo de capacidad, el `break` por
`residente is not None` no cambia nada, porque el filtro ya salta cualquier candidato que no sea el
residente y este aparece una sola vez en la cadena. Se deja como defensa explicita de «sin segundo
salto»; un mutante sobre ella sobreviviria, y por eso el mutante de REQ-018 va sobre el filtro.

### Lo que no cambia, y se escribe

El autoarranque y la pregunta de **arrancar el backend** siguen dentro de `_post_chat`, que ya
retenia la plaza. La pregunta de **elegir modelo** sigue en `local_delegate`, antes de `_chat` y
fuera de la plaza. `_post_chat` no se toco, asi que `test_post_chat_caminos.py` sigue igual.
`scripts/construir_corpus.py` intercepta `_run_chat` y pasa a devolver la tupla de cuatro con un
intento: la guarda del corpus fue la que lo detecto (10 tests en rojo por la firma).

### Suite

`uv run pytest -q`: **1233 passed, 2 skipped**. `ruff check` y `ruff format --check` limpios sobre
`src`, `tests` y `scripts`. **Sin verificar contra el backend real**: es de la tarea 30. El daemon
sigue corriendo el codigo de la 24; instalar esta rama activa el respaldo, que viene encendido por
defecto.

## F3: tarea 29, observabilidad del salto (2026-09-15)

Rama `sdd/f3-t29-observabilidad`. Campos aditivos: un evento sin salto se escribe igual que antes
(test), y `model` sigue siendo el que respondio.

### Lo comprobado

- **Log** (`tests/test_observabilidad_respaldo.py`): pedido, respondido, motivo y clase del salto en
  `_chat`, en trozos y en map-reduce; `chunks` con las llamadas del respaldo (2 en una llamada, 5 en
  la traduccion de cuatro trozos); el salto por enfriamiento con `fallback_class: enfriamiento` y sin
  `chunks`; el razonamiento agotado con `error_class: configuracion` (REQ-019).
- **Cuenta y panel** (`tests/test_metrics.py`): `fallback` y `cause` en `_accounting`, un evento
  historico que se lee igual, las estadisticas con saltos, causas y tokens del salto atribuidos al
  modelo que respondio, y **la paridad Python–JS con un evento con salto, uno de configuracion y uno
  con los dos campos**, mas la guarda de que la lista tiene casos de cada.
- **`local_status`** (REQ-013): el modelo enfriado con los segundos que le quedan (100-120 tras tres
  fallos) y «1 vez seguida»; tras vencer y volver a fallar, «2 veces seguidas» y la espera doblada;
  «ningun modelo enfriado»; y «apagado» con `LOCAL_DELEGATE_COOLDOWN=0` aunque el fichero enfrie.
- **Panel en el navegador** (app de metricas en el 9494 con un log de ejemplo de cuatro filas):
  dos filas con la marca `↪` y su titulo («Respondio gemma3-4b en lugar de gemma4-26b-a4b
  (http_500)» y el de enfriamiento), el punto de error con «causa: configuracion» y la tarjeta
  «5 al backend (+1 por trocear) · 2 con salto». De ahi salio un texto que ya no era cierto: la
  llamada de mas la hizo el respaldo, no un troceo; ahora dice «por trocear o saltar».

Rojo antes de implementar: 16 fallaron; paso solo «sin salto el evento se escribe como antes», que
es el comportamiento de hoy. Un defecto propio al implementar, visto por la suite y no por los
tests nuevos: la funcion de `local_status` se inserto **debajo del decorador `@mcp.tool`** y
`local_status` dejo de ser una tool (cayeron el smoke de las once tools, dos de la wiki y uno de
catalogo).

### Mutantes

| Mutante | Cae en |
| --- | --- |
| `_accounting` sin `fallback` | paridad, la cuenta con salto y las estadisticas |
| `_accounting` sin causa de configuracion | paridad, la cuenta de configuracion y las estadisticas |
| el JS sin `fallback` | paridad |
| **el JS con la causa en otro orden** | **sobrevivio**; con el caso de los dos campos, cae en la paridad |
| el log sin `model_requested` | los cuatro tests de salto del log |
| `chunks` de `_chat` sin el respaldo | el log con salto |
| el log sin `error_class` | el razonamiento agotado |
| `local_status` ignora las reentradas | reentradas seguidas |
| `local_status` ignora el interruptor | enfriamiento apagado |
| el panel no cuenta causas | las estadisticas |
| los tokens del salto van al modelo pedido | las estadisticas |
| en trozos el log no marca el salto | trozos y map-reduce |

El superviviente no era equivalente: una operacion por trozos que salta y despues falla escribe
`fallback_class` **y** `error_class`, y en ese caso el orden decide la causa que ve el panel.

## Criterio de P-4: los numeros del enfriamiento (tarea 30)

**Escrito el 2026-09-15, con el daemon todavia en el codigo de la tarea 24**, es decir, sin respaldo
ni enfriamiento en produccion. Va antes de instalar `main` por la misma razon que el criterio de
REQ-F1-12: un criterio decidido despues siempre encuentra la forma de leer el dato como un exito.
Los numeros que se juzgan son los defectos de `config.py`: **N = 3** fallos seguidos, **T = 120 s**,
la espera **se duplica** en cada reentrada y el **tope es Tmax = 900 s**.

### Lo que el log ya dice, antes de encender

Todo el historico de `usage-*.jsonl` de esta PC (julio a septiembre de 2026): **158 eventos y 10 con
error**: 5 `http_401`, 3 `http_400` y 2 `http_500`. Con la tabla de F3, los 401 y 400 son de la
peticion y no cuentan; solo los dos 500 habrian sumado, y ningun timeout. **Con esa tasa no se
espera ni una entrada en enfriamiento en una semana**, porque entrar exige tres fallos seguidos del
mismo modelo. Se escribe aqui para que el resultado mas probable, «no concluyente», no se lea
despues como «los defectos funcionan». Matiz: esos fallos son de modelos que F2 retiro
(`llama31-8b`, `gemma3-4b`, `qwen25-coder-14b`), asi que la tasa del catalogo nuevo es otra y esta
sin medir.

### Que se cuenta, y que tarea lo produce

Un control que consume un dato que nadie produce no es un control. Cada fila nombra su productor.

| Medida | De donde sale | Quien lo produce |
| --- | --- | --- |
| **Delegaciones** (denominador) | eventos `local_*` del log con `ts` dentro de la ventana | ya existe |
| **Fallos que cuentan** | eventos con `error_class` `modelo` o `timeout_lectura`, y saltos con `fallback_class` `modelo` (fallo el pedido) | tarea 29 |
| **Saltos por clase** | `fallback_class`: `modelo`, `capacidad_o_carga`, `enfriamiento` | tarea 29 |
| **Fallos al momento** | eventos con `error: "cooldown"` (no quedaba candidato, REQ-009) | tarea 28 |
| **Operaciones desviadas por un episodio** | saltos `enfriamiento` + fallos `cooldown` del modelo mientras estaba enfriado | tareas 28 y 29 |
| **Episodios**: entradas, reentradas, y si la primera llamada tras vencer salio bien o reentro | **nadie hoy** | **tarea 30, parte nueva** (ver abajo) |

**El hueco de la ultima fila.** `enfriamiento.json` solo guarda el presente y el primer exito borra
la entrada, asi que al cerrar la ventana no queda rastro de cuantas veces entro un modelo ni de como
salio. Y el log de uso no lo puede reconstruir: guarda **un evento por operacion**, de modo que no
ve el fallo del segundo salto ni los de los trozos despues del primero; los «fallos que cuentan» de
la tabla son un **minimo**, no el total. Productor propuesto: `Estado` anade una linea a
`LOG_DIR/enfriamiento-eventos.jsonl` en cada transicion (`entra`, `reentra`, `limpia` cuando el
exito llega a un modelo que estuvo enfriado), con modelo, hora, reentradas y espera, bajo el mismo
bloqueo y con la misma regla de privacidad del fichero de estado. Con su test, un control positivo
que provoque las tres transiciones y el test de privacidad. **Confirmado por el usuario
(2026-09-15): amplia el alcance de la tarea 30**, que en el plan solo tocaba documentacion, y va
antes de instalar `main` en el daemon. Sin ese productor, este criterio no se podria calcular y la
ventana solo podria dar «no concluyente».

El conteo lo hace un programa (`scripts/medir_enfriamiento.py --desde <fecha>`), no un recuento a
mano: es lo que dejo sin responder las cuatro primeras mediciones de adopcion.

### Ventana

- **Empieza** el dia en que `local_status` del daemon muestre `main` con respaldo y enfriamiento
  encendidos. La fecha se anota aqui al instalar. Solo cuenta esta PC: la Mac comparte el backend
  pero no el estado (REQ-012 es por maquina) y sigue con la 0.27.0 hasta la release.
- **Dura 14 dias naturales.** Si al cerrarlos no se llega al minimo, el resultado es «no
  concluyente» y la medicion se repite, acumulada desde el mismo inicio, a los **30 y a los 90
  dias**. Si a los 90 sigue sin minimo, **P-4 se cierra como no concluyente por falta de fallos**:
  los defectos se quedan y la documentacion dice que no estan medidos. No se alarga sin fin: con la
  tasa de arriba, «hasta llegar» podria no llegar nunca.
- **Se excluyen**: el tramo de la verificacion con fallo provocado de esta misma tarea (se anota su
  hora de inicio y de fin), cualquier tramo de benchmark, y los eventos de procesos que no lleven los
  campos de la tarea 29. Las llamadas con `model` explicito (REQ-005) **no se pueden separar en el
  log de uso**, que no las marca; si en el de episodios, que es donde importan: un fallo durante el
  enfriamiento no abre ni alarga un episodio, y un exito antes de vencer se escribe con
  `tras_vencer: false` y no cuenta como recuperacion.

### Minimo para concluir

**5 episodios** (entradas en enfriamiento) **y 10 fallos que cuentan** dentro de la ventana
acumulada. Con menos de 5 episodios, una sola tarde con un modelo roto decide el resultado.

### Que numero obliga a cambiar los defectos

Por episodio se mira como termino: **se recupero** (la primera llamada tras vencer salio bien) o
**reentro** (la primera llamada que cuenta tras vencer volvio a fallar). **R** es la fraccion de
episodios que reentraron al menos una vez, **sobre los de desenlace conocido**: los que reentraron
o se recuperaron tras vencer. Un episodio abierto al cerrar la ventana, o limpiado por un exito con
`model` explicito antes de vencer, no dice si el modelo se habria recuperado y no entra en R (si
cuenta para el minimo de episodios).

| Orden | Regla | Que dice | Que se cambia |
| --- | --- | --- | --- |
| 1 | **R > 60 %** | el modelo seguia roto al vencer: T es corto | T pasa a 240 s |
| 2 | **Al menos la mitad de los episodios la abren fallos `timeout_lectura`** | cada uno ya costo `LOCAL_DELEGATE_TIMEOUT` antes de entrar (D-2): N es alto para los timeouts | N pasa a 2 |
| 3 | **R < 20 % y 3 o mas operaciones desviadas de media por episodio** | el modelo ya estaba bien y se pago desviando trabajo: enfria de mas | T pasa a 60 s |
| 4 | **Algun episodio llega a Tmax y vuelve a reentrar** | el tope se queda corto para un modelo que no se arregla solo | Tmax pasa a 1800 s |

**Precedencia**: se aplica **solo la primera regla que se cumpla**, en ese orden, y las demas se
anotan para la ventana siguiente. Se toca un numero por ventana porque dos cambios a la vez no
dejan saber cual movio el resultado. Las reglas 1 y 3 no pueden cumplirse juntas (R no puede ser a
la vez mayor del 60 % y menor del 20 %), y cada una cambia un numero distinto, asi que el orden
basta para que el criterio sea ejecutable. Un cambio de defecto es una release aparte con su
CHANGELOG y abre una ventana nueva con este mismo criterio.

### Los tres resultados

- **Cambiar**: minimo alcanzado y se cumple una regla. Se cambia ese numero y nada mas.
- **Se quedan**: minimo alcanzado y no se cumple ninguna. Los defectos quedan **validados para esta
  maquina y este catalogo**, y asi se escribe.
- **No concluyente**: no se llega al minimo. No valida ni retira nada: los defectos siguen como
  defecto configurable y sin medir.

### Lo que NO se va a concluir

- Que los numeros estan bien porque la ventana no tuvo problemas. Una ventana sin enfriamientos no
  mide nada: es «no concluyente», no «se quedan».
- Que los numeros estan bien porque la verificacion con fallo provocado paso. Esa prueba demuestra
  que el mecanismo salta, avisa y registra; los numeros los decide un fallo que nadie provoco.
- Nada sobre otras maquinas ni sobre otro backend: sin llama-swap no hay senal de carga (D-2) y los
  timeouts se clasifican de otra forma.
- **Fuera de P-4**: si los fallos al momento superan el 5 % de las delegaciones, el problema no son
  los numeros sino que falta candidato (vision no tiene cadena). Eso abre una pregunta sobre las
  cadenas, no cambia N, T ni Tmax.

### El productor de los episodios, y el script que aplica el criterio (2026-09-15)

Rama `sdd/f3-t30-activacion`, sin instalar todavia en el daemon.

- **`enfriamiento.py`**: `entra` y `reentra` con la clase del fallo que los dispara; `limpia` con
  `tras_vencer` cuando el exito llega a un modelo que llego a enfriarse; nada por los fallos por
  debajo de N, ni por los que llegan en pleno enfriamiento, ni por el exito de un modelo con fallos
  sueltos. Las lineas se escriben **bajo el mismo bloqueo** que el estado, para que su orden sea el
  del estado, y un error de disco en el registro no deshace el estado ya escrito.
- **`scripts/medir_enfriamiento.py`**: importa `CLASES_QUE_CUENTAN` y `FICHERO_EVENTOS` del paquete
  y `directorio_de_logs()` de `medir_adopcion.py`, que se saco a funcion para no tener dos copias de
  la ruta. Test de ida y vuelta: los eventos que escribe `Estado` son los que el script agrupa.

Rojo antes de implementar: los 10 tests nuevos de `test_enfriamiento.py` fallaron, y los 20 de
antes pasaron. Pero fallaron por `AttributeError` (el nombre no existia), que no dice nada del
comportamiento; eso lo dicen los mutantes.

| Mutante | Cae en |
| --- | --- |
| sin evento `limpia` | recuperado, exito antes de vencer, dos procesos, privacidad |
| `tras_vencer` siempre verdadero | exito antes de vencer |
| sin evento `reentra` | reentrar, privacidad, ida y vuelta |
| clase fija `modelo` | entrar con su clase, ida y vuelta |
| `_mutar` sin eventos | los ocho tests de eventos |
| regla 1 con `>=` | el borde de R en 60 % |
| **regla 2 con `>`** | **sobrevivio**; con seis episodios y tres por timeout, cae en el borde de la mitad exacta |
| regla 3 con `>` | enfria de mas (15 desviadas en 5 episodios, el borde) |
| regla 4 con un solo Tmax | llega a Tmax y se recupera |
| R sobre todos los episodios | R sin desenlace conocido |
| precedencia invertida | primera regla y anotadas |
| minimo con `and` | cuatro episodios, nueve fallos, tramo excluido |
| exito explicito como recuperado | R sin desenlace conocido |
| sin saltos `modelo` en los fallos | fallos de la tabla |
| la exclusion no quita episodios | tramo excluido |

Los 15 comprobados como mutantes de verdad: el runner cuenta las sustituciones antes de correr. El
superviviente no era equivalente: con cinco episodios, «la mitad» no es un numero entero, asi que
`>=` y `>` no se distinguian.

Suite: 1278 passed, 2 skipped. `ruff check` y `ruff format --check` limpios en lo versionado; los
tres avisos de ruff son de `benchmarks/catalogo-2026-09/resultados/`, que no se versiona.
