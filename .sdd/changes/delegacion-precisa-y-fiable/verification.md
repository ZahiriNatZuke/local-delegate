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
