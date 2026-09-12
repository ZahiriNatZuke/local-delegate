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
