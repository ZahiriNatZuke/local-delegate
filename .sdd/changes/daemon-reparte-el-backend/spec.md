# Specification: el daemon no se pelea por el modelo, usa el que ya está cargado, distingue espera de lentitud y la residencia es opcional

## Summary

En una GPU de 16 GB solo cabe un modelo grande a la vez y, desde el 2026-10-06, **no hay ningún
modelo residente**: los cinco modelos están en un solo grupo `swap` de llama-swap, con TTL de 120 s
los cuatro de texto y 30 s el de visión. Este cambio hace que el daemon:

1. **no mande a la vez** dos operaciones que obliguen a cambiar de modelo (turno por conjunto de
   modelos compatibles, con un orden de adquisición que no puede bloquearse);
2. **use el modelo ya cargado** cuando una evaluación escrita de antemano lo aprobó para esa tool
   (matriz tool × modelo), sabiendo qué está cargado por lo que dice llama-swap y no por una
   estimación a ciegas;
3. **saque de las cadenas de respaldo** el eslabón «residente», que ya no existe, lo sustituya por
   «el modelo cargado» y no vuelva a mandar código ni largo al modelo mecánico (enmienda de F3);
4. **registre** si una llamada tardó por esperar o porque el modelo iba lento;
5. y ofrezca en el CLI **ver y cambiar la residencia y los TTL** sin editar el YAML a mano, con
   «ningún residente» como estado recomendado, confirmación de que llama-swap recargó y vuelta atrás.

Fuera de alcance, por decisión del usuario: las llamadas que no pasan por el daemon de la PC (la Mac
contra el llama-swap de la PC y Claude Desktop en stdio). Evidencia y cifras en `research.md`. Los
requisitos de afinidad (B) **no se implementan** si la evaluación (F) no aprueba ninguna celda.

## Requirements

### A. Turno por conjunto de modelos compatibles

- **REQ-001:** El daemon calcula qué modelos **chocan** con la misma regla que llama-swap v255
  (`groupSwapper.EvictionFor`): cargar A desaloja a B si están en el mismo grupo con `swap: true`, o
  en grupos distintos donde el de A es `exclusive` y el de B no es `persistent`. A y B **chocan** si
  cargar uno desaloja al otro, en cualquiera de los dos sentidos; un modelo nunca choca consigo mismo.
  Lee los grupos de `LLAMASWAP_CONFIG` en las dos sintaxis (`groups` arriba y
  `routing.router.settings.groups`), aplica los valores por defecto de v255 (`swap: true`,
  `exclusive: true`, `persistent: false`), mete los modelos sin grupo en un grupo `(default)` con
  `swap: true, exclusive: true`, y resuelve los alias al id real. **No da por fijo ningún nombre** de
  modelo ni de grupo.
- **REQ-002:** El daemon **no usa turno** para un modelo, y se comporta como hoy, si no hay topología
  —sin `LLAMASWAP_CONFIG`, sin el extra `[llamaswap]`, YAML ilegible, router `matrix`, o un modelo que
  no aparece en la config— o si el backend **no es local** (cualquier host que no sea loopback: la Mac,
  que está fuera de alcance). Un modelo sin turno se trata como compatible con todos. `doctor` y
  `local_status` dicen por qué no hay turno.
  *(Aclarado el 2026-10-07: dos motivos más y sus textos, en «Aclaraciones posteriores a la
  aprobación».)*
- **REQ-003: Operación, conjunto aceptable y concesión.** Una **operación** es una llamada a una tool
  (simple, troceada o map-reduce, con sus saltos de respaldo).
  - Al empezar, **sin consultar la red**, la operación calcula su **conjunto aceptable** `A`: el modelo
    del rol (id real) más los alternativos cuya celda está `aprobada` para esa tool (bloque B). Con
    `model` explícito, `A = {model}`. Sin bloque B, `A = {rol}`.
  - El daemon guarda un solo **estado de turno**, en memoria: `activos`, las operaciones que tienen
    turno, cada una con su modelo elegido o, mientras no lo ha elegido, con su **reserva** (un conjunto
    de modelos); y `cola`, las que esperan, en orden de llegada. `modelos(activos)` es la unión de los
    modelos elegidos y de las reservas.
  - `compatible(m, S)`: `m` no choca con ningún modelo de `S`.
  - **Concesión.** Se vuelve a evaluar **cada vez que algo puede cambiar su resultado**:
    1. llega una petición;
    2. una operación sale de `activos`;
    3. una reserva se reduce al modelo elegido;
    4. una espera sale de la cola por cualquier motivo (concedida, forzada o abandonada);
    5. cambia la topología (REQ-009);
    6. y, además, **una vez por segundo como mínimo**: cada espera duerme en la condición del turno
       con un tope de 1 s, y al despertar vuelve a evaluar la cola y la red de seguridad de REQ-007.
       Así la red salta aunque nadie llegue ni salga.

    La cabeza de la cola `W` se concede si su conjunto concedible `A'_W` no está vacío:
    - si `activos` está vacío, `A'_W = A_W`;
    - si no, `A'_W` contiene el modelo del rol si es compatible con `modelos(activos)`, y los
      alternativos de `A_W` que **ya están** en `modelos(activos)` con un modelo elegido. Un
      alternativo que no está en uso por el propio daemon no entra en `A'` mientras haya alguien en
      `activos`.

    Al concederse, `W` entra en `activos` con la reserva `A'_W` (si tiene un solo modelo, ese queda
    elegido), sale de la cola y se evalúa la cabeza siguiente. Detrás de una cabeza no concedida no se
    concede a nadie, salvo con la excepción de REQ-005.
  - **Elección.** Con un solo modelo en `A'`, ese. Con varios, la operación elige con REQ-012 **después
    de obtener la plaza de su primera llamada**, justo antes de enviar, y su reserva se reduce al
    modelo elegido (lo que dispara una nueva evaluación de la cola, punto 3). Si al elegir ningún
    modelo de `A'` es compatible con `modelos(activos)` sin contar la propia operación (solo puede
    pasar tras una concesión forzada), la operación suelta la plaza y su reserva y vuelve a la
    **cabeza** de la cola, sin perder su puesto.
    *(Aclarado el 2026-10-07: `A'` con el destino de un salto y la elección atómica, en
    «Aclaraciones posteriores a la aprobación».)*
  - La operación conserva el turno de principio a fin; cada trozo toma y suelta su plaza como hoy. Las
    operaciones con el mismo modelo comparten el turno, y su concurrencia la sigue limitando
    `MAX_CONCURRENT_REQUESTS`.
- **REQ-004: Orden de adquisición.** El turno se obtiene **siempre antes** que la plaza: una operación
  **nunca pide turno mientras tiene una plaza**, y quien espera turno no ocupa plaza. Con la plaza en
  la mano, una operación solo espera a cosas externas con tope: las consultas de REQ-013, de 1 s cada
  una, y la llamada al backend, con tope `HTTP_TIMEOUT`.
- **REQ-005: Sin inanición.** Las esperas se conceden en orden de llegada. Mientras alguien espera,
  una petición nueva **no se cuela**, aunque su modelo, por afinidad o no, sea compatible con
  `activos`. **Única excepción (E-1):** se concede en el acto una petición `R` con algún modelo `m` de
  `A_R` compatible con `modelos(activos)` **y** con todos los modelos de los conjuntos aceptables de
  quienes esperan delante; entra con la reserva de esos `m`.
  *Justificación:* un `m` así no desaloja nada de lo que usan ni de lo que piden los que esperan, así
  que no retrasa ningún cambio de modelo, y no impide que la cabeza se conceda, porque la concesión
  solo mira la compatibilidad. Con la config de hoy (un solo grupo `swap`) no se da nunca; solo sirve
  con un residente opcional (`--fijar`). La afinidad **no** se aprovecha de E-1: un alternativo que
  choca con lo que pide la cabeza no la cumple.
  *Cota:* una espera solo puede ser adelantada por peticiones de E-1, que no chocan con ella. Por
  tanto, se concede como muy tarde cuando terminan las operaciones que estaban en `activos` al llegar
  ella y las que esperaban delante.
  *(Aclarado el 2026-10-07: E-1 también en evaluaciones posteriores, en «Aclaraciones posteriores a
  la aprobación».)*
- **REQ-006: Saltos de respaldo.** Si una operación necesita otro modelo a mitad (un salto de respaldo,
  REQ-006 de F3), primero **suelta su plaza** y **sale de `activos`**. Después pide turno con
  `A = {destino}` (o, para el paso `cargado`, el conjunto de REQ-019), **al final de la cola**, y por
  último pide plaza. Nunca retiene dos turnos ni pide turno con plaza. El tope de
  `MAX_CONCURRENT_REQUESTS` se sigue cumpliendo, porque la plaza es el mismo semáforo. Enmienda
  REQ-017 de F3 (REQ-037).
- **REQ-007: Liberación y red de seguridad.**
  - El turno y la plaza se liberan en todos los caminos: éxito, error, excepción y cancelación.
  - **Falta de progreso, no tiempo total.** El reloj de la red **solo corre mientras el daemon no tiene
    ninguna llamada al backend en vuelo**: ni de `activos` ni de una operación sin turno (REQ-002) que
    ocupe una plaza. Se pone a cero cada vez que una llamada empieza o termina. Si la cabeza lleva `LOCAL_DELEGATE_TURNO_MAX_S` (600 s por defecto) esperando
    **y** ese reloj llega a `LOCAL_DELEGATE_TURNO_MAX_S`, la cabeza se concede **forzada**: entra en
    `activos` aunque choque y su evento lleva `turno: "forzado"`. Su modelo es el del rol si está en su
    `A`; si no (una espera de salto, con `A = {destino}` o el conjunto de `cargado`), el primero de su
    `A` en el orden de la cadena. Nunca hay afinidad en una concesión forzada. Las que tenían turno lo
    conservan. Las demás siguen la regla normal: un `activos` con modelos que chocan entre sí no deja
    pasar a nadie que choque con alguno de ellos. Quien comprueba la condición es la propia espera,
    que se despierta al menos una vez por segundo (REQ-003, punto 6).
    *(Aclarado el 2026-10-07: la forzada pone el reloj a cero y hay una como mucho por evaluación,
    en «Aclaraciones posteriores a la aprobación».)*
    *Por qué así, sin suponer ningún plazo HTTP:* una llamada en vuelo es una operación viva. Termina
    cuando la corta su propio plazo, `HTTP_TIMEOUT` (`LOCAL_DELEGATE_TIMEOUT`, 180 s por defecto), sea
    cual sea su valor. Por eso el tiempo en vuelo no cuenta como falta de progreso. **Con
    `LOCAL_DELEGATE_TIMEOUT` por encima de 600** (por ejemplo, 900), una llamada de 700 s no fuerza
    nada: la cabeza espera a que termine, como esperaría a cualquier operación larga. Una cola larga de
    operaciones legítimas tampoco dispara la red. Solo la dispara una operación que tiene el turno y
    pasa 600 s sin ninguna llamada en vuelo: está atascada fuera del backend.
  - **Cancelación.** Con el SDK instalado (`mcp` 2.2.0), la cancelación del cliente **no llega** al hilo
    de la tool: las tools síncronas se ejecutan con `anyio.to_thread.run_sync` sin `abandon_on_cancel`
    (`.venv/Lib/site-packages/mcp/server/mcpserver/utilities/func_metadata.py:164`). La operación sigue
    como hoy, porque el daemon ya termina el trabajo de un cliente que canceló. No queda ninguna espera
    fantasma: ocupa su turno lo que dura su operación. No se diseña otra rama hasta que el SDK la
    ofrezca. **Para el plan:** cada espera de turno ocupa uno de los hilos de anyio (40 por defecto);
    hay que comprobar que, con muchas esperas, los demás manejadores síncronos del proceso no se quedan
    sin hilo.
- **REQ-008: Observabilidad del turno.** Se usa el contrato de espera local que ya aprobó
  `panel-cuentas-y-estados-honestos` (su REQ-022, `spec.md:317-329`): un solo campo, `espera_local`,
  con el motivo como texto, escrito y borrado con **su** ayudante. Este cambio **solo escribe** el
  motivo nuevo `espera_local: "turno"` mientras la operación espera turno. Al obtener el turno lo
  borra y, si después espera plaza, el ayudante del panel escribe `"plaza"`, como ya hace. Al ser un
  solo campo, nunca hay dos motivos a la vez. **No** crea otras claves de espera ni toca la tabla de
  estados del panel ni `estadoModelo`. Como datos aparte, que no deciden ninguna fila, la entrada lleva
  `turno_en_uso` (lista de modelos de `activos`) y `turno_posicion` (puesto en la cola) mientras espera
  turno. Las dos se añaden a la lista de claves que deja pasar `/api/inflight`. El evento del log
  lleva `espera_turno_ms` cuando es mayor que 0, y `turno: "forzado"` cuando lo fue.
  `local_status` muestra la relación de choques (por grupos de la config), los modelos de `activos` y
  cuántas operaciones esperan.
- **REQ-009:** La topología se vuelve a leer cuando cambia la `mtime` o el tamaño de la config, sin
  reiniciar el daemon. Las operaciones que ya tienen turno lo conservan; la topología nueva rige desde
  la siguiente concesión.

#### Por qué turno y plaza no pueden bloquearse mutuamente

Hay dos recursos: el turno (cola FIFO con la excepción E-1) y las plazas (semáforo de
`MAX_CONCURRENT_REQUESTS`). En el grafo de esperas, X → Y significa «X espera a Y».

1. **Quien tiene plaza no espera a nada del daemon** (REQ-004): solo espera a consultas y llamadas con
   tope. No sale ninguna arista desde quien tiene plaza hacia otro recurso del daemon. Vale también
   para una operación **sin turno** (REQ-002) que ocupa una plaza: tampoco espera nada del daemon.
2. **Quien tiene turno nunca espera turno** (REQ-006: para saltar, primero sale de `activos`). Solo
   puede esperar plaza, es decir, esperar a quien tiene plaza, y por (1) ahí acaba la cadena.
3. **Quien espera turno** espera a operaciones de `activos` (por (2), acaban en una cadena finita) o a
   quien está delante en la cola, que es un orden total sin ciclos.

Todo camino del grafo termina en una operación con plaza, que avanza en un tiempo acotado. Por tanto,
no hay ciclo. El caso de la revisión —dos saltos simultáneos con las dos plazas ocupadas mientras una
operación troceada tiene el turno— queda así: los dos sueltan plaza antes de pedir el turno nuevo, la
troceada obtiene plaza y termina, y luego los dos se conceden. Lo cubre el escenario «dos saltos a la
vez no bloquean».

### B. Afinidad: usar el modelo cargado si está aprobado

- **REQ-010:** Hay una **matriz tool × modelo alternativo** con tres estados por celda: `aprobada`,
  `rechazada` y `sin base`. La clave de una celda es (tool, modelo alternativo, modelo del rol con el que
  se comparó). Solo se usa una celda `aprobada` cuya **huella** coincide con la config vigente. La
  huella guarda la ruta y el tamaño del GGUF, los flags que cambian el modelo cargado (`-ncmoe`/
  `--n-cpu-moe`, `--ctx-size`, tipos de caché, `--reasoning`, `--mmproj`) y el `sha256` del prompt de
  sistema de la tool. Una celda que no está en `veredicto.json`, o cuya huella no coincide, no se usa
  (cuenta como `sin base`), y `doctor` lo avisa. Por ejemplo: otro `-ncmoe` bajo el mismo id, otro
  modelo en el rol por variable de entorno o un prompt cambiado. La matriz vive en **un solo sitio**
  del código, y un test la compara con `veredicto.json` (REQ-043).
- **REQ-011:** **Direcciones permitidas.** Las demás celdas no existen ni se evalúan:
  - tools del rol mecánico → modelo del rol largo o del rol de código. Son `local_classify`,
    `local_delegate` sin `model`, y `local_extract`, `local_lint_summary` y `local_translate` cuando su
    entrada queda por debajo de `LONG_INPUT_CHARS`. **`local_summarize` queda fuera** de esta
    evaluación (ver Non-goals);
  - `local_commit_msg` → modelo del rol largo;
  - **nunca** una tool de código o de largo → modelo mecánico (decisión del usuario);
  - **nunca** con modelo explícito (`local_delegate(model=…)`).

  Visión no tiene dirección: el único modelo con `--mmproj` es el de su rol.
- **REQ-012:** **Elección del modelo**, con una función **pura** `elegir(A', rol, observado, propios)`.
  `observado` es la foto de REQ-013 y `propios` son los modelos ya elegidos por operaciones de
  `activos`, es decir, los que el propio daemon está usando:
  1. si el rol está en `A'` y está en `propios` o `observado` lo da `ready`, se elige el rol;
  2. si no, entre los alternativos de `A'` con celda aprobada que están en `propios` o **cargados con
     margen** (REQ-013), se elige el primero por este desempate: con una petición en vuelo (propia o
     ajena); más TTL restante (`ttl: 0` cuenta como infinito); el orden de la cadena del rol; el id;
  3. si no, el rol.

  Por construcción de `A'` (REQ-003), si el rol no está en `A'`, todos los alternativos de `A'` están en
  `propios` y el paso 2 elige uno; así que, al conceder, el paso 3 tiene el rol disponible. Como la
  elección llega después de la concesión, el paso 1 y el paso 3 solo valen si el rol es compatible con
  `modelos(activos)` sin contar la propia operación. Si no (solo tras una concesión forzada), se aplica
  la vuelta a la cabeza de la cola de REQ-003. La función no consulta la red: recibe la foto ya tomada.
- **REQ-013:** **«Cargado con margen».** Solo se pide la foto `observado` cuando hace falta: `A'` tiene
  alternativos que no están en `propios` y el rol no está en `propios`. La foto se toma con la plaza ya
  obtenida, en este orden y con un tope de 1 s por consulta:
  1. `GET /running`: estado y TTL efectivo de cada modelo cargado;
  2. `GET /api/events`: se lee hasta el primer mensaje `inflight`, que es la foto de **todas** las
     peticiones en vuelo de llama-swap, de cualquier cliente, con su modelo, y se cierra la conexión;
  3. `GET /api/metrics/activity?model=<id>&limit=1`, solo si el punto c no queda resuelto con lo
     anterior. Devuelve la última petición **terminada** de ese modelo (`ts_created`).

  Un alternativo `a` está cargado con margen si se cumplen las tres condiciones:
  - a) `/running` lo da `ready`;
  - b) en la foto de peticiones en vuelo **no hay ninguna** para un modelo que choque con `a` y no esté
    `ready`, porque eso es un cambio de modelo pendiente de otro cliente;
  - c) `a` tiene alguna petición en vuelo, **o** su TTL efectivo es 0, **o**
    `ttl − (ahora − ts_created) ≥ LOCAL_DELEGATE_AFINIDAD_MARGEN_S`.

  `ahora` es el reloj local: el backend es local (REQ-017), así que comparte el reloj con llama-swap.
  Si falta cualquier dato (no es llama-swap, no responde a tiempo, 401, no hay `store`), el
  alternativo no cuenta como cargado con margen.
  - **El margen por defecto es de 5 s, y lo justifica el código de v255** (copia en
    `scratchpad/ls255v2/` y `scratchpad/docs-v255/`):
    - `lastUse` es la hora en que **termina** la última petición. Se escribe en un solo sitio, el
      `defer` de `ServeHTTP`, junto con `inflight.Add(-1)` (`process_command.go:132`, `:804-808`);
    - la gorrutina del TTL comprueba una vez por segundo. Si hay alguna petición dentro del proceso,
      no hace nada (`if p.inflight.Load() != 0 { continue }`), así que el reloj queda congelado; si no
      hay ninguna, descarga cuando `time.Since(lastUse) > ttl` (`process_command.go:346-363`). Esa
      comprobación por segundo **retrasa** la descarga, nunca la adelanta, así que el margen no tiene
      que cubrirla;
    - `ts_created` se fija con `time.Now()` en `record` (`src_metrics.go:137-143`), que se llama en el
      mismo hilo justo después de `ServeHTTP` (`src_mm.go:78-82`), y se guarda truncado al segundo
      (`store.go:210`). Por eso nunca es anterior a `lastUse`: como mucho, posterior en milisegundos.
      El truncado deja la estimación del lado prudente.

    La única ventana de carrera va desde el cálculo hasta `inflight.Add(1)` en el proceso. La consulta
    de actividad es la última y la foto se toma con la plaza en la mano, así que esa ventana son
    milisegundos. Los 5 s la cubren con mucha holgura, junto con el desfase de milisegundos entre
    `lastUse` y `ts_created`. Con TTL 120, el modelo cargado sirve 115 s de cada 120, no 60. `ahora`
    sale de `time.time()` (hora del sistema, comparable con `ts_created`), nunca de
    `time.monotonic()`.
  - **La prueba lo comprueba, no lo decide.** El apartado (a) del control «Carrera real» sí puede
    fallar, y comprueba la lectura del código: si el TTL contara desde el inicio de la petición,
    REQ-013 se reescribe. El apartado (b), que mide la ventana, es una comprobación de que todo está
    en orden: si contra lo esperado su p99 más 1 s superara el margen, se sube antes de implementar B.
- **REQ-014:** Con afinidad, la operación conserva **el tope y los prompts de su rol**
  (`max_chars_for_role`), así que se trocea igual que con el modelo del rol. Si el alternativo no
  admite el tamaño (`max_chars_for(alternativo)`), no entra en `A`.
- **REQ-015:** Si el alternativo falla con una clase que salta, el primer candidato es **el modelo del
  rol** y después su cadena, con el tope de saltos de siempre y por el camino de REQ-006.
- **REQ-016:** La afinidad **no añade texto a la respuesta**: no es una degradación, y el texto entra en
  el contexto de Claude. Queda en el log (`model` = el que respondió, `model_requested` = el del rol,
  `routing: "afinidad"`) y el panel **no** la cuenta como respaldo. El evento lleva también
  `afinidad_vuelo_ajeno` (peticiones en vuelo de otros clientes contra ese modelo en la foto) y
  `afinidad_fallida: true` cuando no había ninguna y la espera del backend en la primera llamada fue de
  3 000 ms o más. Eso apunta a que el modelo tuvo que cargarse; las cargas medidas son de 6 a 14 s. Con
  peticiones ajenas en vuelo, la espera puede ser de cola y no de carga: el campo se omite.
- **REQ-017:** Con backend **remoto** no hay afinidad (la Mac queda fuera de alcance, decisión del
  usuario): se usa el modelo del rol, como hoy.
- **REQ-018:** **Si la evaluación no aprueba ninguna celda, los requisitos REQ-010 a REQ-017 se caen y
  no se implementan.** Si solo se aprueban algunas, se implementan con esas.

### C. Cadenas de respaldo sin residente

- **REQ-019:** El paso `residente` de las cadenas se sustituye por **`cargado`**. Se resuelve en el
  momento del salto: el conjunto de alternativos con celda `aprobada` para la tool, distintos del que
  falló, que están en `propios` o, si el daemon no tiene a nadie más en `activos`, cargados con margen
  (REQ-013). El salto pide turno con ese conjunto (REQ-006). Si el conjunto está vacío, o al concederse
  ya no queda ninguno que cumpla REQ-012, el paso se salta **sin gastar salto**.
  **Sin bloque B, la matriz está vacía y `cargado` no tiene miembros**: se resuelve sin consultar la
  red y nunca necesita el código de REQ-013. El plan no puede hacer que C dependa de piezas de B.
- **REQ-020:** Cadenas por defecto: `code → cargado → long`, `long → cargado → code`,
  `mechanical → cargado → long`. **Ninguna** lleva al modelo mecánico desde código o largo. **Sin
  bloque B, las cadenas efectivas son `code → long`, `long → code` y `mechanical → long`.** Revierte
  D-4 de F3 por decisión del usuario del 2026-10-06 (REQ-037).
- **REQ-021:** Un fallo **de capacidad** solo puede saltar a `cargado` (no carga nada, que es la razón
  de ser de REQ-018 de F3), sin segundo salto. Si no hay `cargado`, no salta: devuelve el error de
  siempre. **Consecuencia que se acepta:** hoy, sin bloque B, un fallo de capacidad **no tiene
  respaldo**, cuando antes saltaba al 4B, y ese salto, sin residente, lo cargaba.
- **REQ-022:** `residente` en `LOCAL_DELEGATE_FALLBACK_<ROL>` se sigue aceptando como sinónimo de
  `cargado`, y `doctor` avisa de que conviene renombrarlo.
- **REQ-023:** `local_status`, `doctor` y la wiki **solo** hablan de «residente» si la config tiene un
  modelo con TTL efectivo 0 (REQ-029). Si no, dicen «sin residente». El texto «defecto: el modelo del
  rol mecánico» desaparece.
- **REQ-037: Enmienda de F3, y cómo queda registrada.** Este cambio enmienda estos puntos de
  `.sdd/changes/delegacion-precisa-y-fiable/spec.md`:

  | Punto de F3 | Texto vigente | Queda así |
  | --- | --- | --- |
  | REQ-004 (`:283-296`) | «La regla es "primero el residente, después el resto": residente = el modelo de un grupo persistente de llama-swap, si su configuración se puede leer; si no, el del rol mecánico; código → residente → largo; largo → residente → código; rápido → residente → largo; mecánico → largo» | REQ-019 y REQ-020: `cargado` en lugar de `residente`, sin caída al mecánico, y `mecánico → cargado → largo`. Lo demás de REQ-004 (por rol, repetidos fuera, sobrescribible por variable) sigue igual |
  | REQ-017 (`:351-352`) | «La llamada del respaldo ocupa la misma plaza de concurrencia que la original: el mecanismo nunca supera `MAX_CONCURRENT_REQUESTS`» | REQ-006: el salto suelta la plaza, pide turno y vuelve a pedir plaza. El tope de `MAX_CONCURRENT_REQUESTS` se mantiene |
  | REQ-018 (`:353-355`) | «Un fallo de capacidad o carga solo puede saltar al residente, que ya está en memoria y no obliga a cargar nada…» | REQ-021: solo a `cargado`; si no hay, no salta. Sin segundo salto, sin enfriamiento y con el timeout durante la carga igual que hoy |
  | D-3 (`:528`) y su combinación con D-4 (`:532-533`) | «Hasta 2 saltos por llamada, aceptando que el segundo puede forzar un swap»; «el primer salto es siempre el residente (sin swap)» | Se mantienen los 2 saltos. El primero es `cargado` (sin swap) o se salta sin gastar salto; la premisa «el residente no fuerza swap» cae |
  | D-4 (`:529-530`) | «El rol de código también tiene respaldo, y el primero es el mecánico» | Revocada por el usuario (2026-10-06): código y largo nunca caen al mecánico |
  | «Cambios respecto al original», P-3 (`:234-235`) | «el primero va siempre al residente, que ya está en memoria» | Como D-3 |
  | Requisito no funcional de VRAM (`:505-507`) | «el primer salto va al mecánico (el residente en la receta de grupos), que no fuerza swaps» | Como D-3 |
  | Escenarios «el modelo largo falla y responde el mecánico» (`:376`), «la entrada no cabe en el respaldo» (`:384`) y «el modelo no cabe en la VRAM» (`:435`) | Usan la caída al mecánico o al residente | Los sustituyen los escenarios de C de esta spec; los tests correspondientes se reescriben, no se borran sin sustituto |

  **Registro.** Es la primera tarea de la implementación, antes de tocar `cadenas.py`. No reescribe el
  texto heredado de F3:
  - añade a «Cambios respecto al original» de la spec de F3 un punto «Enmienda del 2026-10-06
    (`daemon-reparte-el-backend`, decisión del usuario)», con la tabla de arriba y un enlace a esta
    spec;
  - registra el evento en el historial de `state.json` de F3 con la herramienta del harness, nunca a
    mano;
  - pide al usuario que vuelva a aprobar el gate `spec` de F3, con la evidencia que cita su decisión
    del brief. Lo exige el propio plan de F3 (`plan.md:733-738`: un residente no persistente «reabre
    la spec y su gate»).

  El bloque C no se mezcla hasta que ese gate esté aprobado.

### D. Espera frente a lentitud

- **REQ-024:** `_post_chat` conserva los `timings` de la respuesta. Cada evento del log lleva, sumados
  sobre sus llamadas reales al backend: `inferencia_ms` (Σ `prompt_ms` + `predicted_ms`), `espera_ms`
  (`latency_ms − inferencia_ms`, mínimo 0: incluye el turno, la plaza, la cola de llama-swap y la
  carga), `tok_s` (Σ `predicted_n` / Σ `predicted_ms`) y `prefill_tok_s`. Si el backend no manda
  `timings`, los campos **se omiten** (nunca 0).
- **REQ-025:** La velocidad **normal** de un modelo es la **mediana de `tok_s`** de sus últimos 50
  eventos correctos con `tokens_out ≥ 8`. Se guarda en una **ventana en memoria** por modelo, que se
  siembra al arrancar con el log de uso del mes en curso y del anterior y se actualiza con cada evento
  propio; no se relee el log en cada llamada. Hacen falta al menos 10 muestras. Con referencia, el
  evento lleva `ritmo_rel` (`tok_s` / mediana, redondeado a dos decimales) y `lento: true` si
  `ritmo_rel < LOCAL_DELEGATE_UMBRAL_LENTO` (0,5 por defecto, decisión del usuario). Sin referencia, se
  omiten. Se compara **solo la generación**, nunca el prefill. **Tamaño de la entrada:** si el control
  de lentitud con contexto largo (ver «Controles») encuentra que la mediana de generación con más de 10k
  tokens de entrada es menor que 0,75 × la de menos de 2k, la referencia se lleva por tramos de entrada
  (`< 2k`, `2k–10k`, `> 10k` tokens), cada uno con su ventana y su mínimo. Si no, una sola. Se decide
  con el control, antes de implementar D.
- **REQ-026:** Si `lento` y el backend es **local**, el evento lleva `ram_libre_mb` (best-effort). Con
  backend remoto, no.
- **REQ-027:** El panel muestra, por llamada, la espera y la inferencia por separado y una marca
  «lento ×0,37». Para la espera de turno basta con REQ-008: con `espera_local: "turno"`, la fila 3 del
  panel («en cola local») ya la cubre, sin tocar su condición. Lo único que añade este cambio son
  **palabras** para el motivo `"turno"`, opcionales según la spec del panel: en el `title`, «esperando
  turno del daemon (en uso: <modelos>)», y lo mismo en «En curso», con `turno_en_uso`.
  `local_status` muestra la mediana de referencia de cada modelo y cuántas muestras tiene.
- **REQ-028:** Observar no rompe una tool: si falla cualquier cálculo de este bloque, la delegación se
  registra igual, sin esos campos.

### E. CLI de residencia y TTL

- **REQ-029:** `local-delegate llamaswap residencia` (sin opciones) **muestra**, para la config
  resuelta (`--config`; si no, `LLAMASWAP_CONFIG` del shell; si no, la ruta que usa el daemon, que la da
  su endpoint de REQ-039): cada modelo con su grupo, `swap`/`exclusive`/`persistent`, el **TTL
  efectivo** (resolviendo `-1` y la ausencia a `globalTTL`), si tiene `--mmproj` y si está en
  `hooks.on_startup.preload`; y el veredicto: **«sin residente (recomendado)»** si **ningún** modelo
  tiene TTL efectivo 0, o «residente: X» por cada modelo con TTL efectivo 0. Avisa de los grupos
  `persistent` con TTL efectivo mayor que 0 («`persistent` no lo mantiene cargado») y de los modelos
  con TTL efectivo 0 fuera de un grupo persistente («se queda cargado hasta que otro lo desaloje»).
  Nunca imprime claves de API ni los `cmd`.
- **REQ-030:** `--ninguno` deja la config **sin residente**. Mueve los miembros de los grupos
  `persistent` al único grupo con `swap: true` (si no hay exactamente uno, pide `--grupo`), borra los
  grupos `persistent` vacíos y pone `--ttl` a los modelos con TTL efectivo 0. Si hay alguno y no se
  pasa `--ttl`, falla y sugiere el TTL más frecuente entre los demás modelos sin `--mmproj` (hoy, 120).
  Si la config ya cumple, dice «nada que cambiar» y **no escribe**.
- **REQ-031:** `--fijar MODELO` es la residencia **opt-in**: pone el modelo en un grupo
  `persistent: true, swap: false, exclusive: false` con `ttl: 0`. Siempre avisa de que ese modelo
  ocupará VRAM de forma permanente. Solo lo hace si
  `vram(MODELO) + max(vram(m) de los modelos de los demás grupos) ≤ --vram-gb − --reserva-gb` (2 por
  defecto); si no cabe, se niega y dice cuánto falta. La VRAM de cada modelo sale, en este orden, de:
  1. `--vram-modelo ID=GiB` (repetible): cifras medidas, por ejemplo las de la tabla de coexistencia de
     F2 (`insumos/llamaswap-grupos.md` §2);
  2. el estimador de `llamaswap_config.py`, **ampliado para `-ncmoe`/`--n-cpu-moe N`**: a los pesos se
     les restan los bytes de los tensores de expertos (`blk.<i>.ffn_*_exps.*`) de las capas `i < N`. El
     tamaño de cada tensor sale de la tabla de tensores del GGUF (diferencia entre offsets
     consecutivos, sin tabla de tipos) y se suma el fichero de `--mmproj` si lo hay. Solo se usa si
     pasó su control en los cuatro modelos medidos (ver «Controles»); si falla en alguno, no se usa
     para ninguno;
  3. si no hay cifra fiable para algún modelo implicado, se niega y pide `--vram-modelo` para ese
     modelo.
- **REQ-032:** `--ttl MODELO=SEGUNDOS` (repetible) cambia el TTL. `SEGUNDOS` es un entero ≥ 1. El 0 se
  rechaza y remite a `--fijar`, porque es residencia. El `-1` solo se acepta si `globalTTL` es mayor
  que 0.
- **REQ-033:** **Escritura:**
  - edición **quirúrgica**: las líneas que no cambian quedan **byte a byte** iguales (comentarios,
    comillas, plegado de los `cmd`, sangrías, fin de línea LF o CRLF, BOM, codificación);
  - **autocomprobación**: el YAML resultante, parseado, es exactamente el original más el cambio
    pedido, y cumple lo que exige `load.go` (cada modelo en un solo grupo, sin las dos sintaxis a la
    vez, TTL enteros ≥ 0, miembros que existen). Si no, no se escribe nada;
  - se rechazan con un mensaje claro los nodos en estilo flujo (`{…}`, `[…]`), las anclas, los alias y
    `<<:`, las claves duplicadas y el router `matrix`;
  - **copia** `<config>.<AAAAMMDD-HHMMSS>.bak` antes de escribir, sin pisar ninguna anterior;
  - **reemplazo atómico**: fichero temporal en la misma carpeta y `os.replace`, para que
    `-watch-config` nunca lea un fichero a medias. En Windows se reintenta hasta 5 veces, con 200 ms
    entre intentos, si `os.replace` da una violación de compartición. Si sigue fallando, se borra el
    temporal, el original queda intacto y se informa;
  - `--dry-run` imprime solo las líneas cambiadas, sin contexto, y oculta los valores de cualquier
    línea que contenga `key`.
- **REQ-034:** **`-watch-config`, antes y después de escribir.**
  - *Antes:* el CLI avisa de que llama-swap recargará en unos 2 s y **descargará todos los modelos**. Se
    niega, salvo con `--ahora`, si hay delegaciones propias en curso (`inflight.json` con pids vivos),
    peticiones en vuelo en llama-swap de **cualquier** cliente (la foto de REQ-013) o modelos en
    `/running`.
  - *Después:* confirma qué pasó con la vigía de REQ-039, que se abre **antes** de escribir y espera
    hasta 45 s (sondeo de 2 s más el apagado del servidor viejo, de hasta 30 s). Hay cuatro salidas,
    cada una con su mensaje:
    - **recargó** (llama-swap escribe «configuration reloaded»);
    - **rechazó**: llama-swap escribe «failed to reload config» o «failed to build new server during
      reload» y sigue con la config vieja. El CLI **restaura la copia** por el camino de REQ-038, para
      que el fichero coincida con lo que corre y el próximo arranque no falle, y muestra el error de
      llama-swap;
    - **no vigila el fichero**: no aparece «reloading configuration» en 10 s. El CLI dice que el
      cambio se aplicará en el próximo arranque y, si el daemon arrancó llama-swap, que falta
      `LLAMASWAP_WATCH_CONFIG=1`;
    - **caído**: llama-swap no responde. El cambio se aplica en el próximo arranque.
  - **No** reinicia llama-swap ni toca el lanzador.
- **REQ-035:** `init-llamaswap` deja de recomendar residente: la ayuda y el README presentan
  `--resident` como residencia opt-in, y `--ttl-resident` pasa a 0 por defecto (con `persistent` y
  TTL mayor que 0 no hay residencia de verdad). Su copia de seguridad deja de ser un `.bak` fijo
  (`cli.py:573-578`) y usa el nombre con fecha de REQ-033.
- **REQ-036:** `doctor` tiene dos checks nuevos. **Residencia**: OK con «sin residente»; aviso
  informativo con un residente configurado (cuánta VRAM retiene); aviso si hay un grupo `persistent`
  con TTL mayor que 0 o una celda de la matriz con la huella cambiada. **Topología**: dice si hay
  turno y, si no, por qué (REQ-002).
- **REQ-038:** `residencia --restaurar <bak>` vuelve a una copia. Valida que la copia parsea y cumple
  lo de `load.go`, hace a su vez una copia del fichero actual, reemplaza de forma atómica (REQ-033) y
  pasa por las mismas negativas y la misma confirmación de REQ-034. Restaura los bytes tal cual, sin
  edición quirúrgica.
- **REQ-039:** **Credencial y estado del backend sin pedírselo al usuario.** La API key de llama-swap
  vive en el lanzador del daemon, no en el shell. El CLI consigue el estado así, en este orden:
  1. a través del **daemon**, con `web_auth_headers()`, como ya hace `doctor`. El daemon expone, tras
     el token web:
     - `GET /api/llamaswap/estado`: estado y TTL de los modelos, número de peticiones en vuelo por
       modelo de todos los clientes, delegaciones propias vivas y la ruta de config que usa el daemon.
       Nunca devuelve `cmd`, cabeceras ni claves;
     - la **vigía de recarga**: `POST /api/llamaswap/vigia` abre una suscripción a `/api/events` con
       la key del daemon y responde con un id cuando ya consumió la carga inicial;
       `GET /api/llamaswap/vigia/<id>` devuelve la salida de REQ-034 y la línea de llama-swap que la
       decidió;
  2. si el daemon no responde, directamente contra llama-swap con `LOCAL_DELEGATE_API_KEY` del shell,
     haciendo lo mismo;
  3. si ninguna de las dos funciona (sin daemon, 401 o sin key), el estado es **«no se sabe»**: el CLI
     se niega a escribir salvo con `--ahora`, dice qué no pudo comprobar y no pide la key. Con
     `--ahora` escribe y avisa de que no puede confirmar la recarga.

### F. Evaluación que aprueba las celdas (va antes de implementar B)

- **REQ-040:** **Corpus de afinidad** (`benchmarks/afinidad-2026-10/`), construido como el de F2: el
  rol, los prompts y el número de llamadas se **capturan** llamando a la tool real con el backend
  interceptado. Cada caso declara su procedencia, su `reference_ok` y su `reference_bad`. **Casos
  distintos en vez de repeticiones:** las tools mecánicas van a temperatura 0 (`local_classify`,
  `local_extract`) o baja con semilla fija, así que repetir corridas da la misma respuesta y no aporta
  información. Cada caso comprueba algo objetivo que un modelo puede fallar:
  - `local_classify`, 8 casos: la salida es **exactamente** una de ≥ 4 etiquetas. Cada caso declara
    antes de medir el conjunto de etiquetas aceptables (normalmente una). Un caso que solo se sostiene
    con una respuesta discutible se quita, no se puntúa. Entre ellos, al menos uno con etiquetas en
    inglés y texto en español;
  - `local_extract`, 8 casos: JSON **estricto** con las claves exactas; entre ellos, un campo ausente
    que debe salir `null`, números y una línea de log como fuente;
  - `local_translate`, 4 casos en Markdown: se conserva el número de títulos, listas y bloques de
    código, y el código sale byte a byte;
  - `local_lint_summary` (tamaño mecánico), 4 casos: los conteos coinciden con la fuente;
  - `local_delegate` sin modelo, 4 casos con formato exacto de salida (un número, una línea CSV…);
  - `local_commit_msg`, **30 casos distintos**: `commit-diff-19k` de F2 más 29 diffs del historial,
    elegidos por una regla escrita **antes** de mirar salidas: los commits más recientes de `main`
    anteriores al 2026-10-06, sin merges, sin Dependabot ni `chore(deps)`, sin `chore: release`, y con
    un diff de entre 2 000 y 20 000 chars. Si salen menos de 29, se amplía hacia atrás sin límite de
    fecha y, después, al rango de 1 000 a 30 000 chars. Hoy hay 104 candidatos entre los últimos 400
    commits. Se añade el techo `techo-commit-156k`;
  - los 5 casos mecánicos de F2 se repiten como **regresión**: no cuentan como discriminantes.
- **REQ-041:** **Tanda**: `benchmark.py` con los flags de producción (el `cmd` de `config.yaml`) y la
  temperatura de producción de cada tool. **Una corrida por caso y modelo**, con una semilla fija y
  registrada, salvo el techo, que lleva 3 (es una prueba de fiabilidad del map-reduce, no de calidad).
  La semilla es solo de la tanda: el payload de producción no la manda, y a temperatura 0 no cambia el
  resultado.
  Cada modelo se calienta con una llamada que se descarta. Modelos (los cuatro de la tanda):
  - el del rol: `gemma3-4b` en las mecánicas y `qwen36-35b-a3b` en commit_msg;
  - los candidatos de cada celda: `gemma4-26b-a4b` y `qwen36-35b-a3b` en las mecánicas, y
    `gemma4-26b-a4b` en commit_msg;
  - `qwen35-2b`, como control débil en las mecánicas.

  Se corre con el cerrojo `pesado.sh`, el daemon sin delegaciones en curso y la PC sin otros pesados.
  La tanda escribe filas en el `metrics.db` real, así que su ventana (inicio y fin en UTC) queda
  anotada en `verification.md` para excluirla de las mediciones de P-4 y F1.
- **REQ-042:** **Hoja a ciegas de commit_msg** (`hoja_pares.py`), que juzga el usuario:
  - **30 pares reales**: en cada caso, el mensaje del 26B contra el de Qwen3.6, en lados al azar con
    semilla registrada;
  - **3 pares trampa**, mezclados con los reales en posiciones al azar. En cada uno, un mensaje que se
    sabe peor, preparado **antes** de la tanda, va contra el mensaje de un modelo (elegido al azar) en
    un caso elegido al azar. Hay un tipo de trampa por par:
    - *de la misma zona*: el asunto real de otro commit, fuera de los 30, que toca el fichero más
      cambiado del caso. Tiene buen formato, pero no es fiel;
    - *lo secundario*: un mensaje con buen formato que solo nombra un cambio secundario del diff (los
      tests, la documentación o una subida de versión), el patrón que F2 encontró en
      `qwen25-coder-14b`;
    - *genérico*: un mensaje con buen formato pero que no dice nada concreto.
  - **Por cada mensaje**, el usuario marca: **inventa** (sí/no: «¿dice algo que el diff no hace?»; lo
    que el mensaje se deja fuera **no** se marca aquí, sino en «lo principal»; es la forma de la regla
    que confirmó el usuario, «inventa algo en menos de 1 de cada 10»), **lo principal**
    (sí/parcial/no: nombra el cambio más importante), **específico** (sí/no:
    se entiende sin abrir el diff) y **formato** (sí/no: una línea de 72 caracteres como máximo, prefijo
    convencional y sin adornos). **Por cada par**, su preferencia: A, B o empate;
  - la clave (qué mensaje es de qué modelo y cuáles son trampa) va en un fichero aparte que solo lee el
    programa del veredicto;
  - **si la hoja se repite**, lleva pares en otro orden y trampas nuevas, construidas con otros commits.
- **REQ-043:** **Veredicto por programa**: un subcomando de `analizar_benchmark.py` aplica los criterios
  de abajo y escribe `benchmarks/afinidad-2026-10/veredicto.json` (estado, criterios y **huella** de
  REQ-010 por celda) y la tabla que se pega en `verification.md`. Ninguna celda se aprueba a mano.
- **REQ-044:** **Idioma del mensaje de `local_commit_msg`** (decisión del usuario, 2026-10-07: «Fijar el
  idioma y repetir»). La tanda de T5 midió que, con un prompt que no pedía idioma, el 26B escribió 17
  de los 30 mensajes en inglés y Qwen3.6, 6; las trampas de REQ-042 están en español, así que el
  idioma las habría delatado y la hoja no se podía generar.
  - Variable nueva **`LOCAL_DELEGATE_COMMIT_IDIOMA`** (texto libre y corto, `es`, `en`…; se lee con
    `config.commit_idioma()` por los helpers `_env*`, al llamar).
  - Con ella puesta, el prompt de sistema de `local_commit_msg` termina con la orden «Escribe el mensaje
    de commit entero (primera línea y cuerpo) en *idioma*.» `es` → «español», `en` → «inglés», y también
    `fr`, `pt`, `de` e `it`; un código con región (`es-CU`) se reconoce por su primera parte, y lo que
    no está en el mapa se usa tal cual.
  - Sin ella, la orden es «Escribe el mensaje de commit entero (primera línea y cuerpo) en el idioma
    predominante de los textos del diff (comentarios, documentación y mensajes).»
  - Vale para los dos estilos (`conventional` y `plain`) y va **solo donde se redacta el mensaje**: la
    llamada única y el reduce del map-reduce. El map y el reagrupado de partes producen notas
    intermedias que nadie lee y no la llevan (lo que decide el idioma del resultado es el reduce).
  - **Efecto en la evaluación:** los casos de commit de `benchmarks/afinidad-2026-10/cases.json` se
    reconstruyen con `LOCAL_DELEGATE_COMMIT_IDIOMA=es`, que es lo que tendrá esta PC en producción, y
    sus resultados sin idioma se apartan a `resultados-sin-idioma/`. Solo cambian los prompts (`system`)
    de los 30 casos reales, las 9 trampas y el techo; los casos, las trampas y las reglas no
    cambian.

#### Criterio de aceptación de las celdas (escrito antes de medir)

**Celda mecánica (tool T → modelo M)**, sobre los casos de T, con una corrida por caso. El orden de
los desenlaces es fijo: si falla el criterio 1, la celda queda **`sin base`**, falle lo que falle
además. Si el 1 se cumple y falla cualquiera de los demás, queda **`rechazada`**. Si se cumplen todos,
**`aprobada`**.

1. **El corpus discrimina:** en todos los casos de T, el puntuador da 1 a `reference_ok` y menos de 1
   a `reference_bad`; **y** `qwen35-2b` o el modelo del rol sacan menos de 1 en al menos un caso de T.
2. **Calidad:** en cada caso, la puntuación de M es ≥ la del modelo del rol.
3. **Formato:** en cada caso en que el modelo del rol da formato correcto, M también.
4. **Verbosidad:** la mediana, entre los casos, de `chars_out(M) / chars_out(rol)` es ≤ 1,5.
5. **Fiabilidad:** ningún caso donde M tenga error, timeout o `finish_reason: length` y el modelo del
   rol no.
6. **Latencia:** la mediana de la latencia en caliente de M es ≤ la del modelo del rol más su carga
   en frío mediana (la saca el programa de `metrics.db`; hoy, unos 6 s para `gemma3-4b`).

**Celda `local_commit_msg` → `gemma4-26b-a4b`.** Regla del usuario, fijada antes de ver datos, más dos
precondiciones de funcionamiento:

0. **Hoja válida:** el usuario marca la trampa como peor (prefiere el otro mensaje) en **al menos 2 de
   los 3** pares trampa. Si no, la hoja no vale y se repite (REQ-042), hasta dos veces. Si tampoco
   vale, la celda queda `sin base`.
1. **No inventa:** «inventa = sí» en **menos del 10 %** de los 30 mensajes del 26B, es decir, en 2
   como mucho.
2. **Preferencia:** con `c` = pares reales en que prefiere el 26B y `v` = en que prefiere Qwen3.6, el
   26B **no pierde**: `c ≥ v`. Un empate global (`c = v`) cuenta como no perder; los empates par a par
   no suman a nadie. Es la lectura confirmada de «no pierde contra el modelo de código (empates
   incluidos)».
3. **Funcionamiento** (dos condiciones previas que no son de calidad; **pendientes de confirmar con
   el usuario**, ver «Para confirmar con el usuario»):
   - a) `techo-commit-156k` por el camino de producción (map-reduce con el tope del rol de código)
     termina sin error en 3 de 3 corridas del 26B;
   - b) ninguno de los 30 casos da error, timeout o `length` en el 26B si no lo da en Qwen3.6.

Si falla el 0, queda `sin base`; si el 0 se cumple y falla el 1, el 2 o el 3, queda `rechazada`.
«Lo principal», «específico» y «formato» se registran y se publican en `verification.md`, pero no
deciden. Si una celda no se aprueba, **su** afinidad no se implementa. Si no se aprueba ninguna, se
aplica REQ-018.

## Acceptance scenarios

Los nombres de modelo son los de hoy. Lo que se comprueba es el rol y la topología.

### Scenario: dos tools en paralelo ya no se quitan el modelo

- **Given** la topología de hoy (todo en un grupo `swap`) y el backend simulado que cuenta cambios de
  modelo
- **When** se lanzan a la vez `local_commit_msg` con un diff de 3 trozos (Qwen3.6) y
  `local_lint_summary` con un log de 3 trozos (26B)
- **Then** hay **1** cambio de modelo (el mismo guion sin turno da varios: el test lo mide en los dos
  sentidos), la segunda operación registra `espera_turno_ms > 0` y las dos terminan bien.

### Scenario: el mismo modelo no se serializa de más

- **Given** dos `local_summarize` largos (26B) a la vez
- **When** corren
- **Then** ninguno espera turno (`espera_turno_ms` ausente) y los dos entran en las dos plazas.

### Scenario: nadie se queda esperando para siempre

- **Given** una operación larga en el 26B y una de Qwen3.6 esperando
- **When** llegan tres operaciones nuevas para el 26B
- **Then** esperan detrás de la de Qwen3.6: el orden de servicio es el 26B (la larga), Qwen3.6, y
  después las tres del 26B.

### Scenario: dos saltos a la vez no bloquean

- **Given** `MAX_CONCURRENT_REQUESTS = 2`; la operación C, troceada en 3, tiene el turno del 26B; A y B,
  también en el 26B, ocupan las dos plazas; y `LOCAL_DELEGATE_TURNO_MAX_S = 60`, para que la red de
  seguridad no pueda tapar un bloqueo
- **When** A y B fallan a la vez con una clase que salta a Qwen3.6, mientras C espera plaza para su
  segundo trozo
- **Then** A y B sueltan su plaza antes de pedir el turno de Qwen3.6; C termina sus 3 trozos en el
  26B; después A y B se conceden juntas en Qwen3.6 y terminan. El test espera como mucho 2 s con
  latencias simuladas de milisegundos y comprueba que «C terminó», con el mensaje «sin progreso:
  bloqueo turno/plaza».

### Scenario: la afinidad no se cuela si alguien espera

- **Given** la celda `local_classify → gemma4-26b-a4b` aprobada, una operación propia en el 26B en
  `activos` y una de Qwen3.6 en la cola
- **When** se llama a `local_classify`
- **Then** espera detrás de la de Qwen3.6, sin unirse al turno del 26B.

### Scenario: la afinidad se une si nadie espera

- **Given** la misma celda aprobada, una operación propia en el 26B en `activos` y la cola vacía
- **When** se llama a `local_classify`
- **Then** se concede en el acto con el 26B, sin consultar la red, y el log lleva
  `routing: "afinidad"`.

### Scenario: un residente compatible no espera (E-1)

- **Given** una config con `gemma3-4b` en un grupo `persistent: true, swap: false, exclusive: false` y
  los demás en un grupo `swap: true, exclusive: false`; el 26B en `activos` y una de Qwen3.6 en la cola
- **When** se llama a `local_classify` (rol mecánico, sin celdas aprobadas)
- **Then** se concede en el acto con `gemma3-4b`, que no choca con nada de lo que se usa ni de lo que
  se espera; la de Qwen3.6 sigue primera en la cola.

### Scenario: sin progreso, la cabeza se concede forzada

- **Given** con un reloj simulado, una operación en el 26B que tiene el turno y pasa 600 s sin ninguna
  llamada en vuelo, una de Qwen3.6 en la cabeza de la cola, y **nadie más llega ni sale**
- **When** pasan 600 s
- **Then** la de Qwen3.6 se concede con `turno: "forzado"`, porque la despierta su propia comprobación
  de cada segundo. Si la del 26B termina una llamada en el segundo 599, no se fuerza nada a los 600.
  Un mutante sin la comprobación periódica (que solo evalúa al llegar o salir alguien) no fuerza
  nunca y falla en el assert de la concesión forzada.

### Scenario: una llamada larga con un plazo HTTP mayor que 600 s no se fuerza

- **Given** `LOCAL_DELEGATE_TIMEOUT=900`, una operación en el 26B con una sola llamada en vuelo que
  dura 700 s, y una de Qwen3.6 en la cabeza de la cola
- **When** pasan 650 s
- **Then** no hay concesión forzada: el reloj de la red no corre mientras hay una llamada en vuelo. La
  de Qwen3.6 se concede de forma normal cuando termina la del 26B. Un mutante que cuenta también el
  tiempo en vuelo fuerza en el segundo 600 y falla.

### Scenario: cuando una reserva se reduce, la cola se vuelve a mirar

- **Given** la celda `local_classify` aprobada para el 26B y para Qwen3.6, y `activos` vacío
- **When** llega W1 (`local_classify`), que queda con la reserva {4B, 26B, Qwen3.6}; llega W2
  (`local_lint_summary`, 26B), que espera porque el 26B choca con el 4B y con Qwen3.6 de la reserva; y
  W1 elige el 26B en su primera llamada
- **Then** W2 se concede en ese momento, mientras W1 sigue con sus trozos, sin esperar a que W1
  termine. Un mutante que no vuelve a evaluar la cola al reducir la reserva deja a W2 esperando hasta
  el final de W1 y falla en el assert «W2 empezó antes de que W1 terminara».

### Scenario: la espera de turno se ve en el panel como espera local

- **Given** una operación esperando turno
- **When** se lee su entrada de `inflight.json` y `/api/inflight`
- **Then** lleva `espera_local: "turno"`, `turno_en_uso` y `turno_posicion`; el panel la pinta en la
  fila 3 («en cola local») con el `title` «esperando turno del daemon (en uso: …)». Un mutante que
  escribe una clave de espera propia en vez de `espera_local` hace que la fila salga «esperando
  turno» o «procesando», y el test falla en el assert de la fila.

### Scenario: sin topología o con backend remoto, como hoy

- **Given** `LLAMASWAP_CONFIG` vacío, un `config.yaml` con `routing.router.use: matrix`, o un backend
  que no es loopback
- **When** se delega en paralelo
- **Then** no hay turno, nada espera en el daemon y `doctor` lo dice con la causa.

### Scenario: la tarea mecánica usa el 26B cargado

- **Given** la celda `local_classify → gemma4-26b-a4b` aprobada, nada en `activos`, el 26B `ready` en
  `/running` con `ttl: 120`, ninguna petición en vuelo y su última actividad hace 20 s
- **When** se llama a `local_classify`
- **Then** responde el 26B, no se carga el 4B, el log lleva `routing: "afinidad"` y
  `model_requested: gemma3-4b`, y la respuesta no lleva ningún aviso.

### Scenario: al cargado le quedan 3 s

- **Given** lo mismo, pero con la última actividad hace 117 s (quedan 3 s, menos que el margen de 5 s)
- **When** se llama a `local_classify`
- **Then** va al 4B, como hoy.

### Scenario: al cargado le quedan 40 s

- **Given** lo mismo, con la última actividad hace 80 s
- **When** se llama a `local_classify`
- **Then** responde el 26B.

### Scenario: el cargado está trabajando para otro cliente

- **Given** el 26B `ready`, su última actividad terminada hace 200 s (más que el TTL) y, en la foto de
  `/api/events`, una petición de otro cliente en vuelo contra el 26B
- **When** se llama a `local_classify`
- **Then** responde el 26B: su TTL está congelado mientras haya peticiones en vuelo.

### Scenario: otro cliente tiene un cambio de modelo pendiente

- **Given** el 26B `ready` y usado hace 20 s, y en la foto una petición en vuelo de otro cliente contra
  Qwen3.6, que no está `ready`
- **When** se llama a `local_classify`
- **Then** va al 4B: el 26B está a punto de salir.

### Scenario: una celda no aprobada no se usa

- **Given** el 26B cargado y la celda `local_explain_code → gemma4-26b-a4b` inexistente
- **When** se llama a `local_explain_code`
- **Then** se carga Qwen3.6, como hoy.

### Scenario: la huella cambió

- **Given** la celda `local_classify → gemma4-26b-a4b` aprobada con `-ncmoe 12`, y la config de hoy con
  `-ncmoe 16`
- **When** se llama a `local_classify` con el 26B cargado
- **Then** va al 4B, y `doctor` avisa de que la celda no corresponde al modelo cargado.

### Scenario: código nunca cae al mecánico

- **Given** el 4B cargado y Qwen3.6 que falla con un error del modelo, sin celdas aprobadas
- **When** se llama a `local_commit_msg`
- **Then** el respaldo **no** va al 4B: `cargado` se salta sin gastar salto y responde el 26B.

### Scenario: fallo de capacidad sin nada cargado

- **Given** nada cargado y Qwen3.6 que no puede cargar por falta de memoria
- **When** se llama a `local_explain_code`
- **Then** no hay salto y vuelve el error de capacidad de siempre.

### Scenario: el estado ya no habla de un residente fantasma

- **Given** la config de hoy, sin grupo `persistent` y sin TTL 0
- **When** se ejecutan `doctor` y `local_status`
- **Then** dicen «sin residente» y no aparece «residente gemma3-4b» ni «defecto: el modelo del rol
  mecánico».

### Scenario: una llamada lenta se distingue de una espera

- **Given** 20 eventos previos del 26B con mediana de `tok_s` de 40,5, y una respuesta con
  `predicted_per_second` 15 tras 47 s de espera
- **When** se registra
- **Then** el evento lleva `espera_ms` ≈ 47 000, `ritmo_rel: 0.37`, `lento: true` y, con backend local,
  `ram_libre_mb`; el panel muestra las dos cosas por separado.

### Scenario: ver la residencia

- **Given** la config de hoy
- **When** se ejecuta `local-delegate llamaswap residencia`
- **Then** dice «sin residente (recomendado)», lista los 5 modelos con TTL 120 (el 12B, 30) y no
  imprime claves ni `cmd`.

### Scenario: volver a «ningún residente» desde la config del 2026-09-15

- **Given** una copia de `config.yaml.pre-sin-residente-20261006.bak` (grupo `resident` persistente con
  `gemma3-4b`, TTL 600)
- **When** se ejecuta `residencia --ninguno --config <copia>`
- **Then** el `diff` contra la copia son exactamente las líneas del grupo `resident` borradas y
  `- gemma3-4b` añadida a `swap` (el TTL 600 no se toca, porque no es 0); queda una copia
  `.<fecha>.bak` y el YAML parsea a lo esperado.

### Scenario: fijar un residente que no cabe

- **Given** `--vram-gb 16 --reserva-gb 2` y `--vram-modelo` con las cifras medidas (26B 10,29 GiB,
  Qwen3.6 9,88 GiB)
- **When** se ejecuta `residencia --fijar gemma4-26b-a4b`
- **Then** se niega: 10,29 + 9,88 = 20,17 GiB no caben en 14; dice que faltan 6,17 GiB y no escribe.

### Scenario: fijar el 4B con la config de hoy se acepta

- **Given** la config de hoy, `--vram-gb 16 --reserva-gb 2` y `--vram-modelo` para los cinco: las
  cifras medidas (4B 3,19; 12B 8,85; Qwen3.6 9,88; 26B 10,29 GiB) y, para `qwen35-2b`, que no se midió,
  3,5 GiB (el extremo alto de la estimación del insumo)
- **When** se ejecuta `residencia --fijar gemma3-4b --config <copia>`
- **Then** se acepta (3,19 + 10,29 = 13,48 ≤ 14 GiB): el 4B pasa a un grupo `persistent` con `ttl: 0` y el CLI avisa
  de que retendrá VRAM. Si el estimador pasa su control, lo mismo sin `--vram-modelo`.

### Scenario: no escribir con delegaciones en curso

- **Given** una delegación viva en `inflight.json`, o una petición en vuelo de otro cliente en la foto
  de llama-swap
- **When** se ejecuta `residencia --ttl gemma4-12b=60`
- **Then** se niega y explica que la recarga descargaría el modelo; con `--ahora`, escribe.

### Scenario: sin credencial no se escribe a ciegas

- **Given** el daemon apagado y el shell sin `LOCAL_DELEGATE_API_KEY`
- **When** se ejecuta `residencia --ttl gemma4-12b=60`
- **Then** se niega con «no se sabe si hay delegaciones en curso», sin pedir la key; con `--ahora`,
  escribe y avisa de que no puede confirmar la recarga.

### Scenario: llama-swap rechaza la config

- **Given** el llama-swap de prueba con `-watch-config` y un fichero que nuestra autocomprobación deja
  pasar (en el test se escribe por la función interna, sin autocomprobación)
- **When** se escribe
- **Then** la salida es «rechazó», con el mensaje de llama-swap, y el fichero vuelve byte a byte a la
  copia.

### Scenario: llama-swap no vigila el fichero

- **Given** el llama-swap de prueba sin `-watch-config`
- **When** se cambia un TTL
- **Then** la salida es «no vigila el fichero: se aplicará en el próximo arranque», a los 10 s.

### Scenario: restaurar una copia

- **Given** una config cambiada con `--ttl` y su copia `.bak`
- **When** se ejecuta `residencia --restaurar <bak>`
- **Then** el fichero queda byte a byte como la copia, el actual queda guardado en otra copia y se
  informa de la recarga.

### Scenario: el mensaje de commit sale en el idioma pedido

- **Given** `LOCAL_DELEGATE_COMMIT_IDIOMA=es` y un diff con comentarios en inglés
- **When** se llama a `local_commit_msg` (`conventional` o `plain`)
- **Then** el prompt de sistema lleva la orden de escribir el mensaje entero en español; sin la variable,
  lleva la de escribir en el idioma predominante del diff. En un diff que se procesa por partes, la
  lleva la llamada que redacta el mensaje y no las que describen cada trozo.

## Edge cases and failure behavior

- **Alias:** si un rol apunta a un alias, el turno, la matriz, la foto y la consulta de actividad usan
  el id real (llama-swap resuelve el alias al id real, `swaputil/http.go:242-246`). Si la prueba con
  el llama-swap de prueba muestra filas de actividad con el alias, la consulta pide el id real y sus
  alias (el filtro admite varios).
- **Modelo explícito** en `local_delegate`: pasa por el turno con `A = {model}`, sin afinidad ni
  respaldo.
- **Operación de varios trozos con afinidad:** la decisión se toma una vez, en la primera llamada;
  todos los trozos van al mismo modelo (REQ-006 de F3).
- **Config editada con el daemon corriendo:** las operaciones con turno lo conservan; la topología
  nueva rige en la siguiente concesión.
- **El cargado se descarga a pesar del margen** (por ejemplo, otro cliente pide un modelo que choca
  justo después de la foto): llama-swap carga el elegido, el evento lleva `espera_ms` alta y, si no
  había peticiones ajenas en vuelo, `afinidad_fallida: true`. No hay reintento.
- **Un modelo de `propios` que se descarga:** solo puede pasar si una operación lleva más de su TTL
  esperando plaza mientras otras, compatibles, ocupan todas las plazas (un residente opcional). El
  modelo se vuelve a cargar y la espera queda en el log; no se intenta evitar.
- **Un modelo recién cargado por precarga** (`hooks.on_startup.preload`), sin ninguna petición
  terminada: no hay fila de actividad, así que no cuenta como cargado con margen.
- **`/api/metrics/activity` sin `store`, 404, 401 o lento (> 1 s):** sin afinidad.
- **La carga inicial de `/api/events`** trae antes el historial de logs (hasta 100 KB por monitor). Si
  no llega el mensaje `inflight` en 1 s, no hay foto y no hay afinidad.
- **`timings` incompletos** (falta `predicted_ms`): se omiten los campos que dependen de ellos.
- **Primeros días tras actualizar:** con menos de 10 muestras, ni `ritmo_rel` ni `lento`.
- **YAML con CRLF, mixto o con BOM:** se conserva el fin de línea de cada línea editada y el BOM. Una
  línea insertada usa el de la línea anterior.
- **Las dos sintaxis de grupos a la vez:** el CLI se niega (llama-swap tampoco arranca).
- **Un `.bak` con el mismo segundo ya existe:** se añade un sufijo; nunca se pisa.
- **El disco falla a mitad del reemplazo:** el original queda intacto (renombrado atómico).
- **`--ninguno` sin ningún grupo `swap: true`:** error, con `--grupo`.
- **Procesos fuera del daemon** (una instancia stdio de Claude Desktop, `benchmark.py`, la Mac): no
  pasan por el turno, pero sus peticiones en vuelo **sí** aparecen en la foto de REQ-013 y cuentan para
  las condiciones b y c.
- **Plazos de los clientes MCP:** una operación puede sumar espera de turno e inferencia. Hoy una de
  13 trozos ya tarda minutos. Una tarea del plan comprueba el plazo real de Claude Code y de Codex para
  una tool MCP y lo documenta en la wiki. Si alguno es menor que lo que puede durar una espera, se
  documenta cómo subirlo. No se cambia nada en este cambio.

## Non-functional requirements

- **Sin dependencias nuevas.** La edición del YAML usa PyYAML (extra `[llamaswap]`). `ruamel.yaml`
  0.19.1 puntúa ≥ 0,99 en Socket, pero no conserva este fichero; ver `research.md`.
- **Coste del camino feliz.** No hay ninguna consulta de red para la decisión cuando la tool no tiene
  celdas aprobadas (`A = {rol}`), cuando el rol o el alternativo están en `propios`, o cuando el
  backend es remoto. En los demás casos se hacen hasta tres consultas, de 1 s como máximo cada una,
  con la plaza en la mano y solo en la primera llamada de la operación.
- **Seguridad:** el CLI y los endpoints nuevos no imprimen ni devuelven claves, `cmd` ni cabeceras.
  `/running` incluye el `cmd` y la foto de `/api/events` incluye cabeceras: de las dos solo se leen
  id, estado, TTL y modelo. Las copias quedan junto a la config, con los mismos permisos. Nada de esto
  va al log de uso ni a la spec.
- **Compatibilidad:** los campos nuevos del log son aditivos y se omiten si no hay dato; el histórico
  se lee igual. `residente` sigue funcionando en las variables.
- **Variables nuevas** (`LOCAL_DELEGATE_TURNO_MAX_S` 600, `LOCAL_DELEGATE_AFINIDAD_MARGEN_S` 5,
  `LOCAL_DELEGATE_UMBRAL_LENTO` 0,5) por los helpers `_env*`, con su fila en el inventario y en
  `docs/wiki/Configuration.md`.
- **Release:** CHANGELOG, README y `docs/wiki/` (Configuration, Tools, Architecture,
  Integration-install, Backend-versions, Savings-and-metrics, Troubleshooting) y
  `docs/recipes/llama-swap-groups.md`, que hoy recomiendan un residente.

## Non-goals

- Cambiar la composición de los grupos, meter dos modelos grandes juntos o tocar la config de
  llama-swap de esta PC (la cambió el usuario; el CLI solo actúa si él lo ejecuta).
- Cambiar los modelos por defecto de los roles.
- Coordinar el turno **entre procesos** de la misma máquina o **entre máquinas**. La Mac y Claude
  Desktop en stdio quedan fuera, por decisión del usuario: en 30 días solo hubo 2 peticiones de la Mac
  bloqueadas. Sus peticiones sí se **ven** en la foto de REQ-013.
- Prioridad FIFO de llama-swap, `matrix` y valores de TTL: el CLI permite cambiar el TTL, pero este
  cambio no decide valores.
- **Celdas que no se evalúan aquí:** `local_summarize` (el criterio de cobertura de términos salió a
  cara o cruz en F2 y no hay otro objetivo barato; se podrá evaluar con juicio a ciegas en un cambio
  aparte), `local_boilerplate` y `local_explain_code` → 26B, y las tools del rol largo → Qwen3.6. La
  matriz las admite más adelante, con su propia evaluación.

## Ficheros compartidos con `panel-cuentas-y-estados-honestos`

Este cambio se implementa **después** de que aquel se mezcle, y rebasa sobre él. Los números de línea
de `research.md` se moverán al rebasar: se recalculan en el plan. Lista contrastada con la tabla de
propiedad de su `plan.md` (versión de las 12:14 del 2026-10-06) y con su REQ-022 (`spec.md` de las
12:10, `:317-329`). **De su contrato de espera local solo se consume, no se redefine nada**: este
cambio escribe `espera_local: "turno"` con su ayudante (REQ-008).

| Fichero | Lo toca aquel (su tarea) | Lo toca este |
| --- | --- | --- |
| `src/local_delegate/server.py` | T1: `tokens_claude`, `_accounting`, ahorro de `local_status`. T3: `_get_client`, `ChatResult`, `_log_event` y sus tres llamadas, `_post_chat`, `_run_chat` (espera local), `_inflight_start` y el ayudante de `espera_local`, `sondear_backend`, `_models_with_status`, `_llamaswap_running`, línea `Backend:` de `local_status` | `_run_chat` (turno delante de la plaza), `_con_respaldo`, `_chat*`, `ChatResult` y `_post_chat` (`timings`), `_log_event` (campos nuevos), **llamadas** al ayudante de `espera_local` con el motivo `"turno"` (sin cambiarlo), `local_status` (turno, residencia, medianas), `/running` en la foto de REQ-013 |
| `src/local_delegate/web/metrics.py` y espejo JS | T1, T5 y T4; en T4, `/api/inflight` deja pasar `espera_local`, `estadoModelo`, `pollInflight`, `renderInflight` | `/api/inflight`: deja pasar también `turno_en_uso` y `turno_posicion`. Palabras para el motivo `"turno"` en el `title` y en «En curso». Espera, inferencia y «lento» en la tabla de actividad. Endpoints de REQ-039. **No** toca la tabla de estados ni la condición de la fila 3 |
| `src/local_delegate/config.py` | T3: tres constantes de plazo | Tres variables nuevas |
| `src/local_delegate/checks.py`, `src/local_delegate/doctor.py` | T3: `_default_backend_models`, `Context.backend_models`, `_probe_backend_models`; `backend_probe` | Checks de residencia y topología (REQ-036) |
| `tests/test_metrics.py`, `tests/test_dashboard_js.py`, `tests/test_dashboard_ui.py` | T1, T4, T5 | `/api/inflight` con las claves nuevas, paridad de los campos nuevos y la marca «lento» |
| `tests/test_panel_estados.py` (nuevo de aquel) | T4 | Test del motivo `"turno"`: fila 3 y `title` (escenario «la espera de turno se ve en el panel») |
| `tests/conftest.py` | T3: fixture autouse que vacía la lista guardada | Otra fixture que vacía el estado del turno entre tests |
| `tests/test_sondeo_backend.py`, `tests/test_delegacion_conexion.py` (nuevos de aquel), `tests/test_checks.py`, `tests/test_doctor.py`, `tests/test_observabilidad_respaldo.py`, `tests/test_fallos_integracion.py`, `tests/test_post_chat_caminos.py` | T3 | Respaldo y cadenas, `timings`, `/running`, el camino de `_run_chat` y los checks nuevos |
| `tests/test_captura.py`, `tests/backend_mock.py`, `scripts/dev/capture_dashboard.py` | En su verificación y en T6 (mock del panel) | El mock devuelve `timings`, `/running`, `/api/events` y `/api/metrics/activity`; el del panel, los campos nuevos |
| `tests/test_wiki.py` | En su verificación | `_NUMERO_DE_CHECKS` sube con los dos checks nuevos |
| `CHANGELOG.md`, `docs/wiki/*.md` | T6 | Savings-and-metrics, Configuration, Troubleshooting, Daemon, Tools, Architecture, Integration-install, Backend-versions |

Solo de este cambio: `tests/test_aislamiento_entorno.py` (variables nuevas), `cadenas.py`, `cli.py`,
`llamaswap_config.py`, el corpus y los scripts de la evaluación. Solo de aquel, y aquí no se tocan:
`fallos.py`, `tests/test_causa_conexion.py`, `tests/test_update.py` y su `verification.md`.

## Controles e insumos

Cada control nombra la tarea del plan que produce lo que consume y puede dar un resultado distinto.

| Control | Qué puede salir distinto, y por qué razón falla | Insumo | Lo produce |
| --- | --- | --- | --- |
| Turno: 2 tools en paralelo hacia modelos que chocan | Sin turno salen varios cambios con el guion (se mide antes de implementar); con turno, 1. Un mutante sin turno falla en el assert del número de cambios | Backend simulado que cuenta cambios por modelo | Tarea de tests del turno |
| Turno: orden y E-1 | Un mutante que deja colarse a la afinidad falla en el assert del orden del escenario «la afinidad no se cuela»; uno sin E-1 falla en «un residente compatible no espera» | Backend simulado con latencias controladas | Tarea de tests del turno |
| Bloqueo turno/plaza | Un mutante que salta sin soltar la plaza deja a C sin progreso: falla el assert «C terminó» tras 2 s, con `TURNO_MAX_S = 60` para que la red no lo tape. Si fallara por timeout del runner, el test está mal | Backend simulado, 2 plazas | Tarea de tests del turno |
| Red de seguridad sin progreso | Con reloj simulado, tres mutantes, cada uno con su assert: uno que mide la espera total fuerza aunque hubo progreso en el segundo 599; uno sin la comprobación periódica no fuerza nunca si nadie llega ni sale; uno que cuenta el tiempo en vuelo fuerza la llamada de 700 s con `LOCAL_DELEGATE_TIMEOUT=900` | Reloj simulado | Tarea de tests del turno |
| Momentos en que se vuelve a mirar la cola | Un mutante que no evalúa la cola al reducir una reserva falla en «W2 empezó antes de que W1 terminara»; uno que no la evalúa cuando una espera sale de la cola deja parada a la siguiente compatible; uno que no la evalúa al cambiar la topología no concede a una espera que la topología nueva ya permite | Backend simulado y YAMLs de prueba | Tarea de tests del turno |
| Espera de turno en el panel | Con `espera_local: "turno"`, la fila 3 dice «en cola local» y el `title` nombra el turno; un mutante que escribe una clave propia falla en el assert de la fila. Otro, que filtra `turno_en_uso` en `/api/inflight`, falla en el assert del `title` | `inflight.json` en `tmp_path` y `estadoModelo` con node | Tarea del panel de este cambio |
| Topología igual que v255 | Tabla de casos (valores por defecto, `(default)`, `exclusive`, `persistent`, dos sintaxis, alias) contra lo que dice `EvictionFor`. Un mutante que ignore el defecto `exclusive: true` falla | YAMLs de prueba | Tarea del lector de topología |
| «Cargado con margen» | Con `/running`, `/api/events` y la actividad simulados: «quedan 3 s» → rol, «quedan 40 s» → alternativo, «en vuelo ajeno» → alternativo, «cambio pendiente» → rol. Un mutante sin margen falla en el primero, uno que ignora lo que está en vuelo en el tercero y uno que ignora el cambio pendiente en el cuarto | Endpoints simulados | Tarea de afinidad (solo si REQ-018 no la tumba) |
| Carrera real y semántica del TTL | En el llama-swap v255 de prueba: (a) una petición de 3 s a un modelo con `ttl: 2` no lo descarga mientras dura, y sí entre 2 y 4 s después de terminar (si no, la lectura de `process_command.go` está mal y REQ-013 se reescribe); (b) en 200 decisiones, el p99 entre el cálculo y la entrada de la petición en el servidor falso. Si p99 + 1 s supera el margen, se sube antes de implementar B; (c) una petición por alias aparece con el id real en la actividad | llama-swap v255 en otro puerto, con un servidor falso en Python como `cmd` (sin modelos) y su **propio** `store` en una carpeta temporal, nunca el `metrics.db` real | Tarea de prueba de llama-swap |
| Celdas aprobadas | Los criterios pueden dar `rechazada` o `sin base`, y el orden de los desenlaces está escrito | Corpus (REQ-040), resultados (REQ-041) y hoja juzgada (REQ-042) | Tareas de corpus, tanda y hoja, **antes** de implementar B |
| Hoja de commit válida | Si el usuario no marca como peor al menos 2 de las 3 trampas, la hoja no vale y se repite | Pares trampa de REQ-042 | Tarea de la hoja |
| Matriz del código = veredicto, con huella | Una celda aprobada a mano rompe el test; una huella distinta (otro `-ncmoe`) hace que la celda no se use | `veredicto.json` (REQ-043) | Tarea del veredicto |
| Umbral de lentitud: la regla exacta | (a) Sobre las filas **de la PC** de la copia de `metrics.db`, cruzadas con `usage-*.jsonl` como en el insumo y agrupadas por evento, en orden temporal y con la ventana de 50, el mínimo de 10 y `tokens_out ≥ 8`: marca como mucho el 5 % de los eventos. Si marca más, el umbral se revisa con el usuario antes de implementar D. (b) **Control positivo de la regla** (no de la población del daemon): la misma regla sobre las filas de Qwen3.6 de todos los orígenes marca las 570, 571 y 573. Si no las marca, la regla está mal, no el umbral | Copia de `metrics.db`, `usage-*.jsonl` y un script nuevo que sustituye a `umbral_lento.py` | Tarea de la referencia de velocidad |
| Lentitud y tamaño de la entrada | Mediana de generación por tramos de entrada en las filas de la PC: si el tramo de más de 10k es menor que 0,75 × el de menos de 2k, la referencia va por tramos (REQ-025); si no, una sola. Además cuenta los falsos positivos con entradas de más de 10k tokens con la regla elegida | Lo mismo | Tarea de la referencia de velocidad |
| Edición quirúrgica | Sobre copias de la config vigente y de la del 2026-09-15, y sobre una tabla de casos: secuencias sangradas y sin sangrar (la de hoy es sin sangrar); comentarios en la misma línea y entre miembros; un modelo sin `ttl` cuyo `ttl` se inserta después de un `cmd` entre comillas en varias líneas y después de un escalar `\|` o `>`; un grupo al final del fichero sin salto de línea final; fin de línea mixto (el real `config.yaml.pre-b10909-20260915.bak`); BOM; claves entre comillas; la sintaxis `routing.router.settings.groups`; y, para rechazar, anclas, alias, `<<:` y claves duplicadas. En cada caso, o el `diff` son solo las líneas pedidas, o hay una negativa con mensaje: nunca un fichero roto. Un mutante que reescriba con `safe_dump` falla porque pierde los comentarios de la cabecera y cambia las comillas de `apiKeys` (el número de líneas lo da el test) | Copias de los `config.yaml`, con las claves sustituidas por valores falsos | Tarea del CLI |
| Estimador de VRAM con `-ncmoe` | Contra lo medido en F2 (`insumos/llamaswap-grupos.md` §2: 4B 3 270, 12B con mmproj 9 060, 26B `-ncmoe 12` 10 534 y Qwen3.6 `-ncmoe 20` 10 120 MiB): pasa si las cuatro estimaciones quedan entre −3 % y +10 % de lo medido (quedarse corto es lo peligroso: da OOM). Si alguna no pasa, `--fijar` exige `--vram-modelo` para todos los modelos implicados (REQ-031) | GGUF reales (solo lectura de cabecera) | Tarea del CLI |
| Recarga con `-watch-config` | Salen las cuatro salidas de REQ-034 con el llama-swap de prueba (recarga válida, rechazo escrito sin autocomprobación, sin `-watch-config`, apagado). Además se mide si las peticiones en curso **se cortan** al recargar: si no se cortan, el aviso de REQ-034 se suaviza; si se cortan, se mantiene la negativa | llama-swap v255 de prueba con su propio `store` | Tarea de prueba de llama-swap |
| Restaurar | `--restaurar` deja el fichero byte a byte como la copia. Un lector que relee el fichero en bucle durante una restauración lenta nunca ve un YAML a medias; con un mutante que copia en dos pasos, sí lo ve | Copias de prueba | Tarea del CLI |

## Traceability

| Requisito | Trabajo previsto | Evidencia de verificación |
| --- | --- | --- |
| REQ-001, REQ-002, REQ-009 | Lector de topología | Tabla de casos contra `EvictionFor`; mutantes; recarga por `mtime`; backend remoto sin turno |
| REQ-003 a REQ-008 | Estado del turno, concesión, E-1, orden de adquisición y red de seguridad en `server.py` | Tests de cambios, orden, E-1, bloqueo turno/plaza, salto, excepción, momentos de reevaluación de la cola, sin progreso (con temporizador y con `LOCAL_DELEGATE_TIMEOUT=900`) y `espera_local: "turno"` |
| REQ-010 a REQ-018 | Matriz con huella, elección pura y foto de llama-swap | Tests con endpoints simulados; test matriz = veredicto; prueba de la carrera |
| REQ-019 a REQ-023, REQ-037 | `cadenas.py`, `checks.py`, `local_status`, wiki; enmienda registrada en F3 | Tests de cadenas con y sin `cargado` (matriz vacía); textos de `doctor` y `local_status`; punto en la spec de F3 y gate de F3 aprobado |
| REQ-024 a REQ-028 | `timings`, ventana de referencia, log y panel | Tests del log con y sin `timings`; paridad JS; controles de lentitud |
| REQ-029 a REQ-036, REQ-038, REQ-039 | CLI `llamaswap residencia`, endpoints del daemon, `init-llamaswap`, checks de `doctor` | Tests sobre copias; tabla de edición; estimador contra lo medido; prueba de recarga y restauración |
| REQ-040 a REQ-043 | Corpus, tanda, hoja y veredicto | `veredicto.json` y tabla en `verification.md` |
| REQ-044 | Orden de idioma en `local_commit_msg` y corpus reconstruido con `es` (T5b) | Tests con mutantes; `afinidad --comprobar`; `--seco` con solo las celdas de commit pendientes |

## Decisiones confirmadas

Del brief (2026-10-06) y de lo que ya se le contó al usuario:

- El código y el largo nunca caen al modelo mecánico.
- Umbral de lentitud de 0,5.
- El margen antes de la descarga se ajusta al TTL de 120 s (REQ-013 lo fija en 5 s).
- La Mac y Claude Desktop quedan fuera.
- **Los 600 s cuentan como «sin progreso», no como espera total** (REQ-007): se le contó al usuario y
  no objetó. Al vencer, la cabeza se concede forzada.
- Evaluación a ciegas de commit_msg con 30 pares más 3 trampas; la hoja vale con 2 trampas de 3; el
  26B tiene que inventar algo en menos de 1 de cada 10 mensajes; y no pierde si el usuario lo elige
  al menos tantas veces como al modelo de código (`c ≥ v`), sin que los empates sumen a nadie.
- `local_summarize` queda fuera de la matriz.

## Para confirmar con el usuario

Las dos condiciones previas de la celda de commit (criterio 3), que pueden **rechazar** al 26B aunque
gane en la hoja:

1. Aunque sus mensajes ganen en la hoja, el 26B se descarta si falla alguna de las 3 veces que se le
   pide el mensaje de un cambio enorme, de unos 156 000 caracteres.
2. También se descarta si da error o no llega a terminar en alguno de los 30 commits en los que el
   modelo de código sí terminó bien.

## Decisiones de diseño, con recomendación (se confirman en el gate)

1. **30 commits distintos, una corrida cada uno**, en vez de 6 casos × 5 corridas. «Cuatro modelos»
   se lee como los cuatro de la tanda; los pares son solo 26B contra Qwen3.6. Recomendado: sí.
2. **Excepción E-1** del orden de llegada (solo actúa con un residente opcional). Recomendado: sí.
3. **El CLI restaura solo la copia si llama-swap rechaza la config.** Recomendado: sí.
4. **Endpoints nuevos en el daemon** (`/api/llamaswap/estado` y la vigía), tras el token web, para no
   pedir la key. Recomendado: sí.
5. **Orden de llegada estricto**, sin ventana para unirse al turno (hallazgo menor 27): cuesta un
   cambio de modelo de más en el escenario de la inanición. Recomendado: estricto.
6. **Nombre del comando:** `local-delegate llamaswap residencia` con `--ninguno`, `--fijar`, `--ttl`,
   `--restaurar` y `--vram-modelo`.

## Aclaraciones posteriores a la aprobación

### REQ-042 y REQ-040: trampas y hoja (2026-10-06, tras la revisión del plan)

Decisión de la sesión principal, a raíz del bloqueante B1 de la revisión del plan (`review.md`,
«Revisión del plan»): con las trampas sobre uno de los 30 casos, el usuario veía dos veces el mismo
diff y el mismo mensaje, y las trampas de una línea se distinguían de los mensajes con cuerpo. Así
el criterio 0 pasaría siempre y dejaría de ser un control. **La regla de aprobación del usuario no
cambia.** Se aclara:

1. **Los pares trampa usan diffs propios**, fuera de los 30: los 9 commits siguientes que da la
   regla de REQ-040 (tres por juego, para la hoja y dos repeticiones posibles). La tanda corre los
   dos modelos sobre ellos, y nunca cuentan para los criterios 1 y 2. «Un caso elegido al azar»
   pasa a ser «el caso trampa de ese par».
2. **Cada trampa tiene la forma del mensaje con el que se empareja**: con cuerpo si ese mensaje lo
   tiene (con el mismo número de líneas de cuerpo, hasta 5) y sin cuerpo si no; la primera línea,
   de 72 caracteres como mucho. Las dos formas se escriben antes de la tanda y el programa elige.
   La trampa *de la misma zona* sale de commits con asunto de 72 caracteres como mucho.
3. **«Formato» lo calcula el programa** (primera línea de 72 caracteres como mucho, prefijo
   convencional y sin adornos), no el usuario: no decide y es mecánico. Se publica igual.
4. **Parada anticipada**: el usuario puede preguntar si el desenlace ya está decidido; el programa
   solo contesta «puedes parar» o «sigue», y solo cuando las tres trampas están contestadas y la hoja
   vale.
5. **Pendiente del usuario** (no se fija aquí): si «inventa» se endurece (descartar con más de 1 de
   los 30, en vez de 2) y si «lo principal» y «específico» pasan a opcionales. Los dos valores viven
   en un solo sitio, `benchmarks/afinidad-2026-10/reglas.json`, y se cierran antes de generar la
   primera hoja.
6. **Si la hoja no se termina**, la celda de commit queda no aprobada y `local_commit_msg` sigue como
   hoy (REQ-018 para esa celda).

### REQ-044: idioma del mensaje de commit (2026-10-07, durante T5)

La tanda de T5 se paró antes de la hoja porque los modelos escribían los commits en idiomas distintos
(26B: 17 en inglés, 13 en español; Qwen3.6: 23 en español, 6 en inglés, 1 ambiguo), y las trampas, en
español, se habrían notado. La sesión principal preguntó al usuario cómo seguir y **decidió: «Fijar el
idioma y repetir»**. Se añade REQ-044 (y la tarea T5b del plan): el idioma pasa a ser parte del prompt
de producción, se reconstruye el corpus con él y se repiten solo las celdas de commit. **La regla de
aprobación del usuario no cambia**; las filas mecánicas ya medidas se conservan, y las de commit sin
idioma se apartan, sin borrarse, a `resultados-sin-idioma/`. Las trampas no se reescriben: siguen siendo
las preregistradas en T4, y con el idioma fijado ya no las delata el idioma.

### REQ-002, REQ-003, REQ-005 y REQ-007: aclaraciones tras la revisión de la ola 3 (2026-10-07)

Las propuso la revisión del código de la ola 3 (T7 lector de topología, T8 núcleo del turno, T9
referencia de velocidad) para alinear el texto con lo implementado. El texto de arriba no se
reescribe; cada requisito afectado lleva una línea que remite aquí y, **donde contradiga esta tabla,
manda la tabla**. Como la enmienda de F3 (REQ-037), necesita una aprobación **nueva** del gate `spec`
de este cambio, del usuario, posterior a esta escritura y con evidencia que cite esta tabla. Las
tareas del plan que la recogen (T7, T8, T10, T11 y T14) llevan la marca «aclarado el 2026-10-07».

| Requisito | Texto vigente | Queda así |
| --- | --- | --- |
| REQ-003, conjunto concedible (`:66-69`) | «si no, `A'_W` contiene el modelo del rol si es compatible con `modelos(activos)`, y los alternativos de `A_W` que **ya están** en `modelos(activos)` con un modelo elegido» | «si no, `A'_W` contiene el modelo del rol —o, en una espera de salto, el destino (campo `directos` de la petición)— si es compatible con `modelos(activos)`; los demás de `A_W` solo si ya están elegidos en `activos` y son compatibles con ellos». La última frase («un alternativo que no está en uso…») sigue igual |
| REQ-003, «Elección» (`:74-79`) | La operación reduce su reserva al modelo elegido o, si ninguno cabe, suelta plaza y reserva y vuelve a la cabeza | Igual, y además **la elección es atómica**: reducir la reserva al primer candidato compatible o volver a la cabeza de la cola se hace en un solo paso, bajo el mismo cerrojo que la concesión, sin que otra evaluación vea un estado intermedio |
| REQ-005, E-1 (`:91-93`) | «se concede **en el acto** una petición `R` con algún modelo `m`…» | «se concede, **al llegar o en cualquier evaluación posterior, con la misma condición**, una petición `R` con algún modelo `m`…». La justificación y la cota no cambian |
| REQ-007, red de seguridad (`:112-121`) | El reloj de falta de progreso se pone a cero cuando una llamada empieza o termina | Además, **una concesión forzada también pone a cero el reloj** de falta de progreso, y **como mucho se concede una forzada por evaluación** |
| REQ-002, motivos de «sin topología» (`:37-41`) | «sin `LLAMASWAP_CONFIG`, sin el extra `[llamaswap]`, YAML ilegible, router `matrix`, o un modelo que no aparece en la config» | Se añaden **«dos sintaxis»** (`groups`/`matrix` arriba y `routing.router` a la vez) y **«no cumple load.go»** (la config que `load.go` de v255 rechazaría, con las reglas de REQ-033). Una config con **forma inesperada** nunca rompe la lectura: cuenta como sin topología: «ilegible» si el YAML no se puede leer o su raíz no es un mapa, y «no cumple load.go» si una clave tiene un tipo que `load.go` no puede deserializar (un mapa escrito como lista o al revés). `doctor` y `local_status` dicen el motivo con estas palabras: «sin LLAMASWAP_CONFIG», «sin PyYAML» (el extra `[llamaswap]`), «ilegible», «matrix», «dos sintaxis», «no cumple load.go»; en `local_status`, «Turno: no (<motivo>)» (plan, T10 punto 8). El backend no local y el modelo que no aparece en la config siguen como estaban |

*Por qué cada una:*

- **REQ-003.** Con el texto vigente, una espera de salto (`A = {destino}`, REQ-006) no tiene «modelo
  del rol» dentro de `A` y su destino solo entraría en `A'` si ya estuviera en uso: con alguien en
  `activos`, el salto no se concedería nunca por la regla normal. El destino cuenta como el rol. Y
  «compatibles con ellos» solo restringe tras una concesión forzada, cuando `activos` puede tener
  modelos que chocan entre sí (REQ-007, «las demás siguen la regla normal»). La elección atómica
  evita que dos evaluaciones vean la reserva a medio reducir.
- **REQ-005.** Una petición que llega cuando aún no cumple E-1 y la cumple después (por ejemplo, al
  salir alguien de `activos`) se concede entonces, en vez de quedar detrás de la cabeza. Sigue sin
  chocar con nada de lo que usan ni piden los de delante, así que la cota se mantiene.
- **REQ-007.** Sin poner el reloj a cero, tras una forzada la siguiente cabeza encontraría el reloj ya
  pasado de `LOCAL_DELEGATE_TURNO_MAX_S` y se forzaría también, en cascada, en la misma evaluación.
- **REQ-002.** Son los motivos que ya devuelve el lector (`topologia.py`) y que `doctor` y
  `local_status` deben poder nombrar.
