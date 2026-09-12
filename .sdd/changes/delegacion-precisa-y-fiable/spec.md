# Specification: delegacion precisa y fiable

## Summary

Un solo cambio con cuatro fases y gates propios, en el orden que decidio el usuario el 2026-09-11:
**F0 deteccion de fallos -> F1 precision de la delegacion -> F2 catalogo de modelos -> F3 respaldo y
enfriamiento**. Cada fase entrega valor por si sola y ninguna bloquea a la siguiente mas de lo
necesario: F0 sostiene la clasificacion que F3 necesita, F1 es la prioridad declarada del usuario y
no depende del catalogo, y F2 cierra el catalogo que F3 usa para armar sus cadenas.

El problema de fondo esta medido (ver `research.md`): el aviso de delegacion **ya llega y ya acierta
el tipo de fichero**, y aun asi la adopcion es cero por cuarta medicion consecutiva. La conclusion de
diseno que atraviesa toda la spec es que **sugerir no cambia la conducta**: lo que decida delegar
tiene que ser una regla, no un consejo.

## Non-goals

- Instalar OmniRoute o incorporar su codigo. Solo se toman tres ideas de diseno. Motivo:
  CVE-2026-88062 (RCE critica con PoC publico), contradiccion sin resolver sobre la version
  corregida, camuflaje de huella TLS y baneos de cuentas reportados.
- Proveedores externos: todo sale de `LOCAL_DELEGATE_BASE_URL`.
- El fork de streaming de KV de llama.cpp.
- Cambiar el contrato publico de las tools `local_*` salvo donde una fase lo exija.

---

## F0 - Deteccion de fallos

Los tres defectos estan **verificados por ejecucion**, no deducidos (`research.md`, seccion 3).

- **REQ-F0-1:** Una respuesta con `content` nulo o ausente se convierte en un fallo clasificado,
  nunca en una excepcion que se escape de `_post_chat`.
- **REQ-F0-2:** La clasificacion distingue **cuatro** situaciones que hoy caen todas en
  `http_error`:
  - `ConnectTimeout`: el backend no acepta la conexion. Clase **del endpoint**, el mismo camino que
    `connect_error`; su efecto sobre el autoarranque lo fija REQ-F0-6.
  - `ReadTimeout` **con el modelo todavia montandose**: clase de **capacidad o carga**. No dispara
    autoarranque y no cuenta para el enfriamiento (REQ-018).
  - `ReadTimeout` **con el modelo ya cargado**: clase **timeout de lectura**, distinta de la
    anterior. No dispara respaldo y si cuenta para el enfriamiento (D-2).

    Las dos clases de `ReadTimeout` nacen ya en F0 aunque su efecto solo se note en F3: si F0
    las fundiera en una, F3 tendria que deshacerlo y D-2 se quedaria sin soporte. La senal que las
    separa no se inventa aqui: F0 deja el punto de extension y la distincion se afina con los
    patrones reales que captura REQ-020. Mientras no haya patron aplicable, un `ReadTimeout` cae en
    **capacidad o carga**, que es la opcion que no castiga a un modelo lento de montar.
  - Resto de `HTTPError`: se mantiene como fallo de endpoint.
- **REQ-F0-3:** El codigo inalcanzable de `retry_exhausted` se elimina o se hace alcanzable, con la
  evidencia de cual de las dos cosas procede anotada en `verification.md`. Este requisito **anula**
  el non-goal heredado de F3 («se anota, no se toca»): al pasar la clasificacion a una funcion pura
  (REQ-F0-4), esa rama deja de ser un detalle suelto y pasa a ser una clase mas del clasificador.
- **REQ-F0-4:** La clasificacion vive en una **funcion pura** que recibe el resultado o la excepcion
  y devuelve la clase, separada de la decision de reintentar y del estado de salud del modelo. Es la
  primera de las tres capas que F3 necesita.
- **REQ-F0-5:** Cada clase tiene test con **control positivo**: un caso que la produce y otro
  parecido que no, para que el test no pase por la guarda equivocada.
- **REQ-F0-6:** Que `ConnectTimeout` entre por el camino de `connect_error` **si** cambia el
  comportamiento observable: hoy ese caso no ofrece arrancar el backend, y despues si. Es
  deliberado y **acota** el REQ-016 heredado: «el autoarranque no cambia» significa que no se
  redisena, no que ningun caso nuevo pueda llegar a el. El autoarranque sigue siendo opt-in y la
  pregunta al usuario sigue siendo la misma.

### Escenarios

- **`content: null`**: el backend responde `{"choices":[{"message":{"content":null}}]}`; la tool
  devuelve un error legible y el proceso sigue vivo. Hoy lanza `AttributeError`.
- **Modelo cargando**: el backend tarda mas que el timeout de lectura mientras llama-swap monta el
  modelo; se clasifica como capacidad o carga y **no** se intenta arrancar un backend que ya esta
  corriendo.
- **Modelo cargado que no termina**: el mismo `ReadTimeout`, pero con el modelo ya en memoria; cae
  en la clase timeout de lectura, que en F3 enfria y no salta.
- **Backend apagado**: `ConnectTimeout` en un host que no escucha; se ofrece arrancarlo, igual que
  con `ConnectError` (REQ-F0-6).

---

## F1 - Precision de la delegacion

La prioridad declarada del usuario. Tres piezas vivas —decidir por regla, acotar la superficie y
medir— y una suspendida: comprimir la salida antes del contexto (REQ-F1-4), que no tiene hoy
mecanismo viable.
Absorbe el cambio abierto `read-obliga-a-delegar`, que queda cerrado por esta spec.

- **REQ-F1-1:** La decision de delegar una lectura la toma una **regla evaluable**, no el criterio
  del agente. **Decision del usuario (2026-09-11, P-1 resuelta): bloquear y obligar a delegar.** La
  lectura que cumple REQ-F1-2 se rechaza con un mensaje que nombra la tool que si sirve; el agente
  tiene que llamarla el. No se sustituye la salida por el resumen: el usuario conserva el control de
  que se lee. Cada bloqueo se registra (REQ-F1-5).
- **REQ-F1-2:** El caso acotado donde la regla aplica se define por datos medidos, no por intuicion.
  De los 85 avisos del periodo: `.md` 49, imagenes 19 (`.jpg` 18, `.png` 1), `.txt` 15, `.json` 2.
  De ahi salen tres tratos distintos, y ninguna extension entra a bloquear sin dato propio:
  - **Se bloquea**: `.md` y `.txt`, prosa donde el resumen puede sustituir a la lectura, en lectura
    completa (no acotada por offset o limite) y por encima del umbral vigente.
  - **Se avisa, no se bloquea**: `.json`, `.csv`, `.log` y `.yaml`. Se leen para un valor exacto
    —un `package.json`, un `state.json`, un lockfile, la linea del error—, donde el resumen no
    sirve; ademas `.csv` y `.log` no tienen **ni un aviso medido** en el periodo. Entran a la regla
    solo si una medicion posterior demuestra que convenia delegarlos.
  - **Imagenes** (`.jpg`, `.png`): segundo grupo por volumen y hasta ahora sin politica. Se avisa
    nombrando `local_describe_image`; no se bloquea, porque su ahorro no esta medido.
  - **Lo que no este en ninguna lista** se comporta como hoy. El hook vigente es una **lista negra
    de extensiones de codigo** (`suggest_delegate_read.py:145-147`), no una lista blanca: todo lo
    demas avisa sin bloquear. Pasar a lista blanca seria un cambio de politica, y aqui se declara
    que **no se hace**.
- **REQ-F1-3:** Siempre existe una salida para leer el fichero de verdad. Cada uso de esa salida se
  registra: si la regla se equivoca a menudo, tiene que verse en el dato y no en la irritacion del
  usuario.
- **REQ-F1-4:** *(SUSPENDIDO — no entra al plan hasta que P-7 lo resuelva.)* Recortar o resumir la
  salida de una herramienta **antes** de que entre al contexto no tiene hoy mecanismo viable, y la
  spec no puede pedir lo que no puede nombrar. Esta medido y retirado en la 0.27.0
  (`CHANGELOG.md:127-141`): `PostToolUse` no puede sustituir la salida —cuando dispara, ya entro al
  contexto, y los comandos que fallan ni siquiera la persisten— y el `updatedInput` de `PreToolUse`
  **se salta el allowlist de permisos**, porque el permiso se evalua sobre el comando original. Por
  eso se retiraron `output_policy.py`, `output_stats.py` y `emit_updated_input()`. Lo que si sigue
  vivo de la idea, y no depende del cliente, es leer del lado del servidor con `path`: ahi el
  contenido nunca entra al contexto.
- **REQ-F1-5:** La telemetria distingue **ofrecido, aceptado y rechazado, con motivo**. Hoy el panel
  solo ve las delegaciones que ocurrieron, que es justo el dato que no sirve para saber por que no
  ocurren las demas. «Aceptado» exige **correlacion**: el aviso o el bloqueo lleva un identificador
  propio que viaja hasta el evento de la tool, porque los dos lados son procesos y ficheros
  distintos (`~/.claude/hooks/telemetry.jsonl` y `%LOCALAPPDATA%/local-delegate/usage-*.jsonl`) y la
  cuarta medicion tuvo que cruzarlos a mano. Sin ese identificador, «aceptado» no es medible y F1
  no es falsable.
- **REQ-F1-6:** Todo evento de medicion anota la version del script y el momento de arranque de la
  sesion. Motivo medido: 14 lecturas se comportaron con el umbral viejo despues del cambio, porque
  una sesion abierta hereda el entorno del lanzador.
- **REQ-F1-7:** La spec deja escrito que **en Claude Desktop no hay hooks** y que F1 no le aplica
  hasta resolver la pregunta P-2. Ningun requisito de F1 puede darse por cumplido mirando solo a
  Claude Code.
- **REQ-F1-8:** La guarda de "lectura acotada", hoy la mayor fuente de silencio (242 de 447), se
  mide antes de tocarla. El criterio de «convenia delegar» se fija **de antemano** y es comprobable
  sobre el registro, no a ojo: una lectura acotada convenia delegarla si el mismo fichero se leyo
  entero, o en tres o mas franjas, dentro de la misma sesion. Lo demas cuenta como acotada legitima.
- **REQ-F1-9:** La regla se declara sobre una **superficie de lectura enumerada**, no sobre una
  tool. Motivo: cerrar un camino solo mueve la conducta al de al lado, y entonces la adopcion medida
  sube sin que se ahorre un token. **Decision del usuario (2026-09-11, P-6 resuelta):**

  | Camino | Trato |
  | --- | --- |
  | Tool `Read` | **Se cierra** |
  | `cat`, `head`, `sed`, `Get-Content`, `rtk read` por Bash o PowerShell, en lectura completa | **Se cierra** |
  | Tools de lectura de otros MCP (`mcp__filesystem__read_text_file` y equivalentes) | **Se mide**, no se cierra |
  | Clientes sin hooks (Claude Desktop, REQ-F1-7) | Fuera de alcance hasta P-2 |

  Los tres primeros se **cuentan siempre**, se cierren o no: sin el denominador completo no se
  distingue «se delego» de «se leyo por otro lado». Un comando de shell que lee una franja
  (`sed -n`, `head -n`) sigue la misma guarda de lectura acotada que la tool `Read`.
- **REQ-F1-10:** El bloqueo se cae solo cuando la alternativa no esta viva. Si el backend local no
  responde —clase `connect_error` o de capacidad segun F0— o el modelo del rol esta en enfriamiento
  (F3), la lectura pasa sin bloquear y el evento se registra con ese motivo. Una regla que bloquea
  sin destino deja al agente sin forma de leer.
- **REQ-F1-11:** El bloqueo se apaga **en caliente**, sin reiniciar la sesion. Una variable de
  entorno no sirve: esta medido que una sesion abierta hereda el entorno del lanzador (14 lecturas
  con el umbral viejo), asi que el apagado se lee en cada invocacion desde un sitio que el usuario
  pueda tocar sin cerrar nada. El evento anota si el bloqueo estaba apagado.
- **REQ-F1-12:** Antes de encender el bloqueo se fija la **quinta medicion**: ventana, denominador
  y el resultado que **retira** el cambio. Despues de cuatro mediciones con adopcion cero, un
  criterio decidido a posteriori no vale. Se declara al menos: cuantas lecturas bloqueadas acaban
  en una llamada `local_*` correlacionada (REQ-F1-5), cuantas acaban en el escape de REQ-F1-3, y a
  partir de que proporcion de escapes se retira el bloqueo.

### Escenarios

- **Documento largo**: el agente pide leer un `.md` de 14 KB entero; la lectura se **bloquea** (P-1
  resuelta) con el nombre de la tool que si sirve a la vista, y el bloqueo queda registrado.
- **Codigo**: el agente pide leer un `.py` de 40 KB; la regla no aplica, porque el mercado medido es
  documentacion.
- **JSON de configuracion**: el agente pide leer un `state.json` de 12 KB; se avisa, no se bloquea
  (REQ-F1-2), porque ahi se busca un valor exacto.
- **Lectura acotada**: el agente pide 50 lineas de un fichero grande; no se delega, y el caso se
  cuenta para poder revisar esa guarda con el criterio de REQ-F1-8.
- **La regla se equivoca**: el usuario o el agente fuerzan la lectura real; queda registrado como
  rechazo con motivo.
- **El backend esta caido**: la regla no bloquea, la lectura pasa y el evento anota el motivo
  (REQ-F1-10).
- **El camino de al lado**: tras un bloqueo, el agente lee el mismo fichero con `cat`; el evento se
  cuenta como lectura por otro camino (REQ-F1-9), nunca como delegacion.

---

## F2 - Catalogo de modelos

Sustituye la eleccion heredada por una medida en esta maquina. Detalle y candidatos en el vault
(`projects/llms/investigacion-modelos-abiertos-2026-09.md`).

- **REQ-F2-1:** Ninguna medida vale sin: entorno limpio, "Prefer No Sysmem Fallback" activo, version
  de llama.cpp y de llama-swap anotadas, tres repeticiones y mediana. Una prueba durante la cual
  crezca la VRAM compartida se descarta.
- **REQ-F2-2:** La calidad se juzga con un corpus de **tareas reales de delegacion**, no sintetico,
  con mas casos que la prueba de julio (que uso cinco), razonamiento fijado por modelo y `max_tokens`
  holgado. La puntuacion automatica no decide sola: hay revision humana.
- **REQ-F2-3:** La memoria se mide en el **proceso** (`PrivateMemorySize64`) y la VRAM con el
  contador dedicado del proceso. Motivo: el gate de julio midio la RAM de todo el sistema y descarto
  un modelo por ello.
- **REQ-F2-4:** Cada rol (`fast`, `mechanical`, `long`, `code`, `vision`) queda asignado con criterio
  explicito y con el dato que lo sostiene. Si un solo modelo cubre varios roles, se dice.
- **REQ-F2-5:** El catalogo resultante es la entrada de F3: las cadenas de respaldo se declaran sobre
  los roles que salgan de aqui.
- **REQ-F2-6:** El catalogo **vigente** se mide con el mismo protocolo y en la misma tanda que los
  candidatos. Sin linea base no hay con que comparar: un candidato «bueno» sin referencia no dice
  si mejora lo que ya corre. Si ningun candidato supera al modelo vigente de un rol con margen
  fuera del ruido de las tres repeticiones, **ese rol no se cambia**, y eso se escribe como
  resultado, no como fracaso de la medicion.

### Escenarios

- **Un candidato no cabe**: con la politica del driver activa da error de memoria, no lentitud
  silenciosa, y la prueba se anota como no apta en vez de como lenta.
- **Empate de calidad**: dos modelos puntuan igual; decide la velocidad medida, y queda escrito.
- **El caso no discrimina**: si el corpus no puede distinguir dos modelos, no se concluye que
  empatan; se cambia el corpus.
- **Nadie mejora al que esta**: los candidatos de un rol no superan al vigente fuera del ruido; el
  rol se queda como esta y queda escrito (REQ-F2-6).

---

## F3 - Respaldo entre modelos y enfriamiento

Hereda, sin reescribir, los 20 requisitos y 16 escenarios de
`.sdd/changes/fallback-entre-modelos-locales/spec.md`, que queda **absorbido y no se aprueba por
separado**. Se conservan sus identificadores `REQ-001` a `REQ-020` para no romper su trazabilidad.

**Cambios respecto al original, decididos con la evidencia de hoy:**

- La clasificacion de fallos ya no la define F3: la entrega F0 (REQ-F0-4), y `REQ-001`, `REQ-015` y
  `REQ-016` se apoyan en ella en vez de duplicarla.
- **`REQ-016` queda acotado por REQ-F0-6**: «el autoarranque no cambia» quiere decir que no se
  redisena, no que ningun caso nuevo pueda llegar a el. `ConnectTimeout` pasa a ofrecerlo, igual
  que `ConnectError`.
- **El non-goal de `retry_exhausted` queda anulado por REQ-F0-3**: F0 lo elimina o lo hace
  alcanzable, con la evidencia anotada. La lista de non-goals de mas abajo lo refleja.
- **Las dos clases de `ReadTimeout`** (durante la carga y con el modelo cargado) las define F0
  (REQ-F0-2); la tabla de clasificacion de aqui las consume tal cual.
- Las cadenas se declaran sobre los roles que salgan de **F2**, no sobre el catalogo actual.
- **Confirmado por el usuario (2026-09-11, P-3 resuelta)**: hasta **2 saltos**, y **el primero va
  siempre al residente**, que ya esta en memoria; solo el segundo puede forzar un cambio de modelo.
- **Sigue sin medir**: los numeros del enfriamiento (3 fallos, 120 s, duplicar, tope 900 s), que
  vienen de bajar de escala los de OmniRoute. Se parametrizan y se validan con datos de F2. Ver P-4
  del brief.

El texto heredado sigue a continuacion, con sus encabezados rebajados un nivel.
### Clasificación de fallos

| Clase | Qué incluye | ¿Respaldo? | ¿Cuenta para el enfriamiento? |
| --- | --- | --- | --- |
| **Del endpoint** | no conecta (`ConnectError`, `ConnectTimeout`), errores de transporte sin respuesta del modelo | No | No |
| **De la petición** | cualquier 4xx: 400 (incluido el desborde de contexto y el schema no soportado), 401, 403, 404, 413, 422 | No | No |
| **De capacidad o carga** | el modelo no se pudo montar: falta de memoria (OOM), error de carga, llama-swap aún cargándolo, timeout mientras cargaba | Solo al residente, sin segundo salto | No |
| **De configuración** | el modelo terminó por `max_tokens` (`finish_reason: length`) con `content` vacío **y** `reasoning_content` no vacío: un modelo de razonamiento que gastó el presupuesto pensando | No | No |
| **Del modelo** | 5xx que no sea de capacidad; respuesta rota (JSON inválido, sin `choices`, `content` nulo o ausente sin que el motivo sea `length`) | Sí | Sí |
| **Timeout de lectura** | el modelo ya estaba cargado y no terminó dentro de `LOCAL_DELEGATE_TIMEOUT` | No (D-2) | Sí (D-2) |
| **Sin clasificar** | cualquier otro caso | No | No |

Las clases de capacidad y de configuración salen de la coordinación con la sesión que investiga modelos
nuevos (`local-delegate-44`, 2026-09-11):

- **Capacidad o carga:** con la política de NVIDIA «Prefer No Sysmem Fallback», que el usuario va a
  activar, un modelo que no cabe da un error de carga en vez de ir lento. Si ese error se leyera como
  fallo del modelo, el respaldo saltaría a otro modelo grande y provocaría una cascada de swaps y OOM.
- **Configuración:** el canary de julio de 2026 con `gpt-oss-20b` devolvió `content` vacío porque el
  razonamiento se comió `max_tokens`. Es un fallo de configuración: taparlo con un respaldo haría que
  nadie lo arreglara.

### Requirements

- **REQ-001:** Todo fallo de una llamada al backend se asigna a una de las clases de la tabla. Lo que no
  encaje en ninguna va a «sin clasificar».
- **REQ-002:** Un fallo **del modelo** provoca un reintento con el siguiente candidato válido de la
  cadena del rol, en orden. Hay un máximo de **2 saltos** por llamada lógica (configurable), y cada
  salto exige que el intento anterior fallara también por el modelo: un fallo de otra clase corta la
  cadena. Si hay reintento de schema (`json_schema_fallback`), va antes y sigue funcionando igual.
- **REQ-003:** Un candidato es válido si:
  - está en el catálogo de modelos de texto (`ALLOWED_MODELS`);
  - es distinto del que falló;
  - no está en enfriamiento;
  - su límite de caracteres (`max_chars_for`) admite el tamaño de la petición que se va a enviar.
  El que no cumpla algo se salta sin llamarlo.
- **REQ-004:** Las cadenas se declaran **por rol, no por nombre de modelo**, y se resuelven al vuelo con
  la configuración vigente. Así sobreviven a un cambio de los modelos por defecto (hay candidatos nuevos
  en estudio para todos los roles). La regla es «primero el residente, después el resto»:
  - **residente** = el modelo de un grupo persistente de llama-swap, si su configuración se puede leer;
    si no, el del rol mecánico;
  - código → residente → largo
  - largo → residente → código
  - rápido → residente → largo
  - mecánico → largo
  - visión → ninguna

  Tras resolver, se quitan los repetidos: si dos roles apuntan al mismo modelo (por ejemplo, largo y
  código consolidados en uno solo), ese modelo se intenta una vez. Cada rol se puede sobrescribir con una
  lista ordenada de roles o modelos, y una lista vacía desactiva el respaldo de ese rol.
- **REQ-005:** Una llamada con `model` **explícito** en `local_delegate` no usa respaldo. Se envía
  aunque el modelo esté en enfriamiento, y su resultado actualiza el estado de ese modelo igual que
  cualquier otra llamada.
- **REQ-006:** En una operación de varios trozos (`_chat_chunked`, `_chat_map_reduce`), si un trozo
  respondió con el respaldo, los trozos siguientes de esa misma operación van directos a ese respaldo.
  Así la salida cambia de modelo como mucho una vez y no se vuelve a llamar a un modelo que acaba de
  fallar.
- **REQ-007:** Cuando respondió un respaldo, la respuesta de la tool lo dice: qué modelo respondió, en
  lugar de cuál y por qué, y desde qué trozo si hubo varios. El aviso **nunca** se mezcla con el
  contenido que el agente usa tal cual:
  - en el JSON de `local_extract`, va dentro de su bloque de metadatos;
  - con `local_boilerplate`, va en la respuesta, no en el fichero que se escribe en disco.
- **REQ-008:** Si fallan también los respaldos, la tool devuelve el error del modelo original, igual que
  hoy, más una línea con los respaldos que se probaron y cómo falló cada uno. Cada fallo cuenta para el
  enfriamiento de su modelo según su propia clase.
- **REQ-009:** Un modelo que acumula **N** fallos seguidos de las clases que cuentan (por defecto 3,
  sumando todos los procesos) entra en enfriamiento durante **T** segundos (por defecto 120). Mientras
  tanto:
  - no se le envía ninguna petición, salvo las de REQ-005;
  - si es el modelo principal de un rol, se va directo a la cadena de respaldo;
  - si no queda ningún candidato, la tool falla **al momento**, con un error propio que dice qué modelo
    está en enfriamiento y hasta cuándo. Nunca espera un timeout.
- **REQ-010:** Cuando vence el enfriamiento, el modelo vuelve a recibir peticiones. El primer éxito lo
  deja limpio (contador y espera a cero). El primer fallo que cuente lo enfría otra vez con la espera
  doblada, hasta un tope **Tmax** (por defecto 900 s). Todo enfriamiento tiene fecha de vencimiento
  menor o igual a Tmax: ninguno es permanente.
- **REQ-011:** Cualquier éxito de un modelo pone a cero su contador de fallos seguidos. Los fallos del
  endpoint, de la petición y sin clasificar ni suman ni ponen a cero.
- **REQ-012:** El estado de enfriamiento es el mismo para todos los procesos de local-delegate de la
  máquina (daemon y stdio) y sobrevive a un reinicio del proceso. Si el estado no se puede leer o
  escribir (fichero corrupto, bloqueo ocupado), la llamada sigue como si no hubiera enfriamiento: nunca
  bloquea ni falla por eso.
- **REQ-013:** El log de cada operación registra:
  - el modelo pedido y el que respondió;
  - si hubo respaldo y por qué;
  - todas las llamadas reales al backend en `chunks`, incluidas las del respaldo.
  El panel atribuye tokens y latencia al modelo que respondió y **marca las operaciones en las que hubo
  salto**, con la clase del fallo, para que un benchmark o una medición sepa si la contaminó un swap.
  `local_status` lista los modelos en enfriamiento, con el tiempo que les queda y cuántas veces seguidas
  han vuelto a entrar.
- **REQ-014:** Todo es configurable por variables de entorno, registradas en `VARIABLES_DE_ENTORNO`:
  - apagar el respaldo;
  - apagar el enfriamiento;
  - N, T y Tmax;
  - el número máximo de saltos;
  - la cadena de cada rol.
  Un modelo de una cadena que no esté en el catálogo se ignora, y `doctor` lo avisa.
- **REQ-015:** Una respuesta con `content` nulo o ausente se convierte en un fallo, nunca en una
  excepción que salga de la tool. Se clasifica así:
  - `length` con razonamiento no vacío → de configuración (REQ-019);
  - `length` sin razonamiento → sin clasificar;
  - cualquier otro motivo de parada → del modelo (`bad_response`).
- **REQ-016:** Un `ConnectTimeout` se clasifica como fallo del endpoint (sin respaldo ni enfriamiento).
  El comportamiento de autoarranque y de la pregunta por elicitation no cambia en este change.
- **REQ-017:** La llamada del respaldo ocupa la misma plaza de concurrencia que la original: el mecanismo
  nunca supera `MAX_CONCURRENT_REQUESTS`.
- **REQ-018:** Un fallo **de capacidad o carga** solo puede saltar al residente, que ya está en memoria y
  no obliga a cargar nada. No hay segundo salto y no cuenta para el enfriamiento. Un timeout de lectura
  cuenta como de carga si el modelo todavía se estaba montando cuando venció.
- **REQ-019:** Un fallo **de configuración** no dispara el respaldo ni cuenta para el enfriamiento. El
  error dice la causa en claro («el modelo agotó `max_tokens` sin responder; súbelo o desactiva el
  razonamiento») y queda registrado como causa propia en el log y en el panel, para que se vea y se
  arregle.
- **REQ-020:** La forma de reconocer los fallos de capacidad, carga y configuración se basa en respuestas
  **reales** de llama-swap y llama-server capturadas en el plan, no en suposiciones:
  - Casos a capturar: OOM, error de carga, carga en curso, timeout de carga y parada por `length`.
  - El OOM se captura **con y sin** la política «Prefer No Sysmem Fallback». Sin ella no hay error: el
    driver desborda a RAM y el síntoma es un timeout, que tiene que caer en su propia clase.
  - Cada patrón lleva anotada la versión de llama-swap y llama.cpp de la que salió. Se captura contra la
    versión que vaya a correr en producción cuando se active el respaldo; hoy son v238 y b9925, y la de
    pruebas en estudio, v255 y b10909.
  Una variante que no encaje en ningún patrón va a «sin clasificar» (sin respaldo ni enfriamiento), nunca
  a «del modelo».

### Acceptance scenarios

Los nombres de modelo son los valores por defecto de hoy (residente `gemma3-4b`). Los escenarios valen
igual con otros modelos: lo que se comprueba es el rol.

### Scenario: el modelo largo falla y responde el mecánico

- **Given** `local_summarize` con una entrada que cabe en el modelo mecánico, y el backend responde 500
  a `llama31-8b` y 200 a `gemma3-4b`
- **When** se llama a la tool
- **Then** el resumen llega hecho por `gemma3-4b`, la respuesta dice que respondió el respaldo y por qué
  (`http_500`), y el log registra `llama31-8b` como pedido y `gemma3-4b` como el que respondió

### Scenario: la entrada no cabe en el respaldo

- **Given** una entrada de 30 000 caracteres para el modelo largo (límite 48 000) y la cadena largo →
  mecánico (límite 20 000)
- **When** `llama31-8b` responde 500
- **Then** no se llama a `gemma3-4b` y se devuelve exactamente el error de hoy

### Scenario: un 400 no dispara el respaldo

- **Given** el backend responde 400 a una petición
- **Then** no se llama a ningún otro modelo, el contador de enfriamiento no cambia y el resultado es el
  de hoy, incluido el reintento sin schema de `local_extract` en modo `auto`

### Scenario: el backend está caído

- **Given** el endpoint no acepta conexiones
- **Then** se comporta exactamente como hoy (autoarranque o pregunta), no se llama a ningún respaldo y
  **ningún** modelo entra en enfriamiento

### Scenario: tres fallos seguidos enfrían el modelo

- **Given** `qwen25-coder-14b` responde 500 tres veces seguidas, en llamadas desde dos procesos distintos
- **When** llega una cuarta llamada de código
- **Then** no se envía a `qwen25-coder-14b`: va directa al respaldo, y `local_status` muestra el modelo
  en enfriamiento con su tiempo restante

### Scenario: el modelo en enfriamiento sin alternativa falla al momento

- **Given** `gemma3-4b` en enfriamiento y la cadena del mecánico vacía
- **When** se llama a `local_classify`
- **Then** la tool falla en menos de un segundo, con un error que dice que `gemma3-4b` está en
  enfriamiento y hasta cuándo, sin esperar ningún timeout

### Scenario: vence el enfriamiento y la prueba sale bien

- **Given** un modelo cuyo enfriamiento acaba de vencer
- **When** la siguiente llamada tiene éxito
- **Then** el modelo queda limpio: sin contador, espera base y fuera de `local_status`

### Scenario: vence el enfriamiento y la prueba falla

- **Given** un modelo cuyo enfriamiento de 120 s acaba de vencer
- **When** la siguiente llamada falla con un 5xx
- **Then** vuelve a enfriamiento por 240 s, y la espera nunca pasa de Tmax por muchos ciclos que se repitan

### Scenario: traducción en trozos con respaldo a mitad

- **Given** `local_translate` en 4 trozos, y el trozo 2 falla con 500 en el modelo largo
- **Then** el trozo 2 lo hace el respaldo, los trozos 3 y 4 van directos al respaldo, y la respuesta dice
  que desde el trozo 2 respondió el respaldo

### Scenario: el modelo no cabe en la VRAM

- **Given** el modelo de código falla al cargarse por falta de memoria
- **Then** la llamada salta al residente, que ya está cargado. Si el residente también falla, se
  devuelve el error de hoy **sin segundo salto**, y el modelo de código no entra en enfriamiento

### Scenario: un modelo de razonamiento agota `max_tokens`

- **Given** el backend responde 200 con `finish_reason: length`, `content` vacío y `reasoning_content`
  no vacío
- **Then** no hay respaldo ni enfriamiento, el error explica que el modelo agotó `max_tokens` sin
  responder, y el log y el panel lo registran como causa de configuración
- **And** la misma respuesta **sin** `reasoning_content` queda como «sin clasificar», no como
  configuración

### Scenario: timeout mientras el modelo carga

- **Given** un modelo MoE que tarda en montarse, y el timeout vence mientras llama-swap aún lo carga
- **Then** el fallo es de carga: no cuenta para el enfriamiento del modelo

### Scenario: benchmark con el mecanismo apagado

- **Given** la variable que apaga el respaldo, puesta durante un benchmark
- **Then** ningún fallo provoca un salto, y por tanto ningún swap ajeno a la medición

### Scenario: modelo explícito

- **Given** `local_delegate(model="llama31-8b")` con `llama31-8b` en enfriamiento
- **Then** la petición se envía igualmente a `llama31-8b`, no hay respaldo, y su resultado actualiza el
  estado del modelo

### Scenario: mecanismo apagado

- **Given** las variables que apagan el respaldo y el enfriamiento
- **Then** todas las tools se comportan exactamente como antes de este change

### Scenario: estado ilegible

- **Given** el fichero de estado corrupto o bloqueado por otro proceso más allá del plazo
- **Then** la llamada sigue sin enfriamiento, y no falla ni se queda esperando

### Edge cases and failure behavior

- **Varios procesos fallan a la vez** contra el mismo modelo: cada fallo cuenta una vez; el estado se
  actualiza bajo bloqueo.
- **El respaldo también está en enfriamiento**, o no hay candidato válido: se devuelve el error de hoy
  o el de enfriamiento de REQ-009, lo que corresponda; nunca se superan los saltos máximos.
- **Reloj:** los vencimientos se guardan en hora de reloj real (comparable entre procesos de la misma
  máquina). Un vencimiento en el futuro lejano, por ejemplo tras un cambio de hora, se recorta a Tmax al
  leerlo.
- **Visión** (`local_describe_image`) no tiene respaldo, pero sí enfriamiento.
- **Respaldo en `local_boilerplate`:** el fichero se escribe solo si el respaldo tuvo éxito, como hoy
  con el modelo original.
- **Un `content` vacío (`""`) no es un fallo:** se trata como hoy. Solo cuenta el nulo o ausente
  (REQ-015).

### Non-functional requirements

- **Latencia:** el respaldo nunca se dispara tras un timeout, así que el peor caso de una llamada sube,
  como mucho, en dos llamadas más que fallaron rápido (más la carga del modelo si hubo swap), nunca en
  otros 180 s. Con el modelo sano, el coste añadido es una lectura del estado bajo bloqueo por llamada.
- **Privacidad:** el estado guarda nombres de modelo, contadores y fechas. Nunca prompts, rutas ni
  contenido.
- **Compatibilidad:** ninguna tool cambia su schema. Un cliente viejo solo nota la línea de aviso cuando
  hubo respaldo.
- **Sin dependencias nuevas.**
- **VRAM:** el primer salto va al mecánico (el residente en la receta de grupos), que no fuerza swaps. El
  segundo salto sí puede cargar un modelo del grupo `swap` y expulsar el que use otra petición u otra
  sesión: es el precio aceptado de las cadenas largas (D-3).

### Non-goals

- Proveedores remotos, o cualquier destino fuera del endpoint configurado.
- Reintentar el mismo modelo antes de saltar.
- Enrutar según la VRAM libre o el modelo cargado (idea 3 del análisis de OmniRoute, cambio aparte).
- Mandar un desborde de contexto a un modelo con más contexto: lo sigue tratando map-reduce.
- Respaldo para visión.
- Tocar la configuración de llama-swap.
- ~~Quitar el código muerto `retry_exhausted` (se anota, no se toca).~~ **Anulado por REQ-F0-3**:
  F0 lo elimina o lo hace alcanzable, con la evidencia de cuál procede en `verification.md`.

### Decisiones del usuario (2026-09-11)

- **D-1 — Activado por defecto.** El respaldo y el enfriamiento vienen encendidos y se pueden apagar por
  variable de entorno.
- **D-2 — Los timeouts enfrían pero no disparan el respaldo.** Un modelo colgado deja de recibir
  peticiones tras N timeouts, pero en la llamada que ya esperó 180 s no se añade otra espera. Matiz de la
  coordinación: un timeout **mientras el modelo cargaba** no cuenta (REQ-018), para no castigar a un
  modelo lento de montar.
- **D-3 — Cadenas largas.** Hasta 2 saltos por llamada, aceptando que el segundo puede forzar un swap.
- **D-4 — El rol de código también tiene respaldo, y el primero es el mecánico.** El boilerplate, los
  mensajes de commit y las explicaciones pueden salir de un modelo más pequeño, y la respuesta lo avisa.

D-3 y D-4 se combinan con la regla de REQ-004: el primer salto es siempre el residente (sin swap) y
después se sigue por el grupo `swap`.

### Traceability

| Requisito | Trabajo previsto | Evidencia de verificación |
| --- | --- | --- |
| REQ-001 | clasificador de fallos a partir del resultado de `_post_chat` | tests por clase, incluido un caso sin clasificar |
| REQ-002 | respaldo en cadena en `_run_chat`, después del reintento de schema, con tope de saltos | tests con doble que responde según `model`: un salto, dos saltos, tope alcanzado, cadena cortada por un 4xx |
| REQ-003 | filtro de candidatos | tests: candidato en enfriamiento, igual al fallido, fuera de catálogo, sin sitio |
| REQ-004 | cadenas por defecto y por variable | tests de cadena por defecto, sobrescrita y vacía |
| REQ-005 | modelo explícito sin respaldo y sin bloqueo | test con el modelo en enfriamiento |
| REQ-006 | modelo fijo dentro de una operación | test de `local_translate` en 4 trozos |
| REQ-007 | aviso en la respuesta, separado del contenido | tests de summarize, extract y boilerplate con respaldo |
| REQ-008 | error original más la línea del respaldo | test con los dos modelos fallando |
| REQ-009 | enfriamiento tras N fallos, fallo inmediato sin candidato | test de 3 fallos desde dos «procesos» y tiempo de respuesta |
| REQ-010 | vencimiento, prueba, espera doblada con tope | tests con reloj controlado |
| REQ-011 | reset por éxito; clases neutras | tests de secuencias mixtas |
| REQ-012 | fichero compartido con bloqueo; degradación | tests de fichero corrupto y bloqueo ocupado |
| REQ-013 | campos nuevos en el log, atribución en el panel, `local_status` | tests de `_log_event`, `web/metrics.py` y `local_status` |
| REQ-014 | variables en `VARIABLES_DE_ENTORNO`; check de `doctor` | `test_aislamiento_entorno.py` en verde; test del check |
| REQ-015 | `content` nulo → `bad_response` | test con `content: null` |
| REQ-016 | `ConnectTimeout` → clase del endpoint | test que asevera cero enfriamiento y cero respaldo |
| REQ-017 | respaldo dentro del mismo `_chat_slots` | test de concurrencia con el semáforo a 1 |
| REQ-018 | fallo de capacidad: solo al residente, sin segundo salto ni enfriamiento | tests con OOM simulado y con timeout durante la carga |
| REQ-019 | causa de configuración propia, mensaje en claro | test con `finish_reason: length` y contenido vacío; campo en log y panel |
| REQ-020 | patrones sacados de respuestas reales | capturas de llama-swap y llama-server guardadas como fixtures; test de variante desconocida → sin clasificar |

---

## Traceability de F0, F1 y F2

La tabla de arriba es la heredada de F3 y cubre `REQ-001` a `REQ-020`. Esta cubre los requisitos
propios de este cambio.

| Requisito | Trabajo previsto | Evidencia de verificación |
| --- | --- | --- |
| REQ-F0-1 | `content` nulo o ausente deja de escaparse de `_post_chat` (`server.py:605`) | test con `{"content": null}` y control positivo con contenido real |
| REQ-F0-2 | clasificar `ConnectTimeout`, los dos `ReadTimeout` y el resto de `HTTPError` | un test por clase con dobles de `httpx2`; test de que un `ReadTimeout` no atribuible cae en capacidad o carga |
| REQ-F0-3 | eliminar `retry_exhausted` o hacerlo alcanzable (`server.py:659-663`) | evidencia en `verification.md` de cuál de las dos procede; si queda, test que lo alcanza |
| REQ-F0-4 | función pura de clasificación, separada del reintento y del estado de salud | tests unitarios sin red; F3 la consume sin duplicarla |
| REQ-F0-5 | control positivo por clase | cada test de clase acompañado de un caso parecido que **no** la produce |
| REQ-F0-6 | `ConnectTimeout` entra al camino de autoarranque y de la pregunta | test que asevera que se ofrece arrancar, y que sigue siendo opt-in |
| REQ-F1-1 | decisión de bloqueo en el hook de lectura | test del hook: bloquea y el mensaje nombra la tool que sirve |
| REQ-F1-2 | listas por extensión según lo medido | tests por extensión: `.md` bloquea, `.json` avisa, imagen avisa, `.py` calla |
| REQ-F1-3 | escape para leer de verdad, con su evento | test del escape y del evento que deja |
| REQ-F1-4 | **suspendido**: no entra al plan hasta P-7 | ninguna; se revisa cuando P-7 nombre un mecanismo |
| REQ-F1-5 | ofrecido/aceptado/rechazado con identificador correlacionable | test de que el id del hook llega al evento de la tool y los dos ficheros se pueden cruzar sin trabajo manual |
| REQ-F1-6 | versión del script y arranque de sesión en cada evento | test del payload del evento |
| REQ-F1-7 | Claude Desktop declarado fuera del alcance hasta P-2 | revisión documental: ningún requisito de F1 se da por cumplido mirando solo a Claude Code |
| REQ-F1-8 | medición de la guarda «acotada» con el criterio escrito antes | consulta reproducible sobre el registro, guardada en `verification.md` |
| REQ-F1-9 | cerrar `Read` y las lecturas completas de shell; medir las de otros MCP | test por camino: bloqueo en `Read` y en `cat`/`Get-Content`, registro sin bloqueo en el MCP ajeno; recuento por camino en la quinta medición |
| REQ-F1-10 | el bloqueo se cae con el backend caído o el modelo en enfriamiento | test con el backend simulado caído y con el modelo enfriado |
| REQ-F1-11 | apagado en caliente, sin reiniciar la sesión | test de que no hace falta relanzar nada; el evento anota el estado |
| REQ-F1-12 | criterio de la quinta medición escrito **antes** de encender | el criterio en `verification.md`, con fecha anterior al encendido |
| REQ-F2-1 | protocolo de medición: entorno limpio, política del driver, versiones fijadas, tres repeticiones | hoja de resultados con las versiones y las tres repeticiones por caso |
| REQ-F2-2 | corpus de tareas reales de delegación, mayor que los cinco casos de julio | corpus versionado + revisión humana anotada junto a la puntuación automática |
| REQ-F2-3 | memoria por proceso (`PrivateMemorySize64`) y VRAM del proceso | la medida cruda de cada prueba, no un resumen |
| REQ-F2-4 | asignación de rol con criterio explícito | tabla de roles con el dato que sostiene cada elección |
| REQ-F2-5 | el catálogo alimenta las cadenas de F3 | las cadenas de F3 se escriben sobre los roles resultantes |
| REQ-F2-6 | medir también el catálogo vigente, en la misma tanda | comparación candidato/vigente por rol, con el ruido de las tres repeticiones a la vista |
