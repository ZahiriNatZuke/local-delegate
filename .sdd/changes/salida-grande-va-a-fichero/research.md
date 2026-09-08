# Research: la salida grande va a fichero, no al contexto

## Pregunta

`suggest_lint_summary` lleva desde julio sugiriendo volcar a fichero y resumir con
`local_lint_summary`. ¿Cuántas de esas sugerencias apuntan a una salida que de verdad convenga
resumir, y cuál es el instrumento correcto para decidirlo sin capar el MCP a un solo perfil?

## Método

Cinco fuentes, cruzadas. Ninguna basta sola.

1. `~/.claude/hooks/telemetry.jsonl` — 13 200 eventos; 2 652 y 411 sugerencias en la ventana.
2. Transcripts de Claude Code (`~/.claude/projects/*/*.jsonl`) — el único sitio donde vive el
   **tamaño real de la salida** de cada Bash, que la telemetría no guarda a propósito.
3. `usage-YYYYMM.jsonl` del daemon — las delegaciones que llegaron a ocurrir.
4. Estado del arte externo — cuatro proyectos que atacan este mismo problema con números.
5. Dos experimentos con `claude -p` contra el binario real (2.1.263).

Ventana: **2026-08-19 → 2026-09-08** (21 días), la primera enteramente posterior al PR #146.

## Hallazgos

### La conversión sigue en cero, y el arreglo anterior no la movió

**411 sugerencias, 0 delegaciones.** No existe siquiera `usage-202609.jsonl`. La última
delegación real es del 18-ago, y son las 5 del control positivo de aquella jornada.

El PR #146 hizo lo que prometía y no compró adopción:

| Ventana | Eventos | Sugerencias | Tasa |
|---|---:|---:|---:|
| 9-ago → 18-ago (hook viejo) | 3 359 | 741 | 22,1 % |
| 19-ago → 8-sep (hook nuevo) | 2 652 | 411 | 15,5 % |
| Delegaciones en la segunda ventana | | | **0** |

### La causa está un nivel más abajo: se arregló el 3 % de los avisos

| Categoría | Avisos | Qué mira | Puntería |
|---|---:|---|---|
| `lint` | **363 (88 %)** | `command_chars`, antes de ejecutar | **0,3 %** |
| `summarize` | 35 | el prompt del usuario | — |
| `read` | 13 (3 %) | extensión y tamaño | **0 %** |
| `extract` | 1 | el prompt | — |

El PR #146 arregló `read`. El 88 % viene de `suggest_lint_summary`, que **no puede acertar por
diseño**: decide con `\b(lint|test|tsc|build|pytest|clippy|biome)\b` sobre el texto del comando,
antes de saber qué va a salir.

Medido contra los transcripts: **366 disparos, 1 con salida mayor o igual a 8 KB** —y esa era un
`ssh … cat > m1.js <<EOF`, un heredoc que *escribe*—. **Mediana de salida: 402 bytes.** Las
palabras que lo disparan son `test` (204) y `build` (102) como subcadena de rutas y nombres de
fichero; la palabra `lint` aparece **3 veces en 366**. Durante esta misma investigación se
disparó sobre un `grep -rn "lint"`, donde la palabra era el término de búsqueda.

Los 13 avisos de `read` del periodo son **`.png` los trece**: con el coste real de una imagen
(~1 500 tokens, no su tamaño en KB) el ahorro que proponen es nulo.

### El peor hook es el único que está encendido por defecto

`install._HOOK_EVENTS` registra `suggest_lint_summary.py` en **toda** instalación. El de Read
—el que sí se arregló— es opt-in tras `--enable-read-hook`. O sea: el hook con puntería 0,3 % es
el que recibe cualquiera que instale el paquete, y el bueno hay que pedirlo.

### Una lista de comandos no puede ser el instrumento

Tasa real de superación de 8 KB por ejecutable, sobre los 2 476 comandos de la ventana:

| Ejecutable | Veces | >= 8 KB | Tasa |
|---|---:|---:|---:|
| `yarn` | 23 | 2 | 9 % |
| `docker` | 47 | 4 | 9 % |
| `cat` | 278 | 15 | 5 % |
| `sed` | 476 | 14 | 3 % |
| `ls` | 212 | 5 | 2 % |
| `python` | 348 | 0 | 0 % |
| `npx` | 184 | 0 | 0 % |
| `curl` | 143 | 0 | 0 % |

**Ni el mejor llega a 1 de cada 10.** Una lista blanca bien investigada subiría la puntería del
0,3 % a ~9 % en este corpus, y seguiría siendo un aviso que se aprende a ignorar.

**Y este corpus no contiene el caso donde la lista sí funcionaría.** Quien ejecute `mvn test`
cuarenta veces al día tendría `mvn` muy por encima del 50 %. Calibrar con estos datos capa a ese
perfil; calibrar solo con una lista externa capa a este. La conclusión no es *qué comandos poner
en la lista*, sino que **la lista no puede ser el único instrumento**.

### El techo de 30 000 caracteres cambia el argumento

La tool Bash de Claude Code trunca a **30 000 caracteres, por el medio**. Verificado en los
propios datos: los mayores tamaños son 30000, 29977, 29849, 29815… y hay 91 marcas de
`truncated] ...` en los transcripts de un solo proyecto. Es configurable con
`BASH_MAX_OUTPUT_LENGTH`.

Consecuencia: para una salida grande, el valor de delegar **no es principalmente ahorro, es
capacidad**. El modelo local lee el fichero entero; Claude solo ve cabeza y cola, y no sabe qué
le falta. En un `pytest` con 200 fallos, el del medio no llega nunca.

Esto encaja con la lección ya registrada del proyecto: se obedece lo que no tiene alternativa.
Aquí la alternativa (leerlo directo) no es cara, **está rota**.

Nota de alcance: el techo es de la tool **Bash**. Las tools MCP no lo tienen — hay un caso
reportado de `getDiagnostics()` metiendo ~580 700 tokens en una sola llamada.

### El mercado real existe, y está en otro sitio

De las 2 476 salidas de Bash, **42 superan 8 KB** (1,7 %), ~137 000 tokens en total:

| | Casos | Tokens |
|---|---:|---:|
| Código leído literal — **no se delega** | 17 | ~58 000 |
| Logs y salidas de herramientas (`docker logs`, `yarn typeorm:run`, crash dumps) | 11 | ~41 000 |
| Resto (PLAN.md, `.sdd/*.md`, configs) — mixto | 14 | ~38 000 |

**El mercado genuino son 40–70 K tokens en tres semanas**, en *logs y documentos*, no en lint ni
en tests. La regex actual caza **1 de los 42**.

### Se vigila la puerta que no se usa

En la misma ventana: **2 476 comandos Bash contra 30 lecturas `Read`** — 82 a 1. De esas 30
lecturas, las delegables (texto no-código, entero, >= 32 KB) son **cero**. El grueso de la
lectura de ficheros pasa hoy por `cat`/`sed -n`, que ningún hook nuestro mira.

### `updatedInput` funciona (verificado por ejecución)

Claude Code 2.1.263, hook `PreToolUse` con `hookSpecificOutput.updatedInput`:

| | Resultado |
|---|---|
| Comando pedido | `echo MARCA_ORIGINAL` |
| Comando ejecutado | `echo MARCA_REESCRITA` |

El modelo recibe la salida del comando reescrito **y lo dice** («un hook reescribió el comando»),
o sea que no engaña. Esto permite que la salida deje de entrar al contexto **sin depender de que
el modelo obedezca un consejo**, que es la diferencia estructural con todo lo intentado hasta hoy.

### La envoltura preserva el código de salida (verificado por ejecución)

**Alcance de esta medición: se hizo ejecutando en el intérprete (Git Bash, POSIX), NO a través de
la tool `Bash` con `updatedInput`.** La diferencia importa y se cobró un defecto — ver la sección
siguiente. Con la forma `{ CMD ; } > fichero 2>&1; ec=$?; … ; exit $ec`:

| Caso | Resultado |
|---|---|
| Comando simple | `ec=0`, salida capturada |
| Comando que sale con 7 | **`ec=7`**, stderr capturado en el fichero |
| Compuesto con `&&` | `ec=0`, la redirección cubre **las dos** partes |
| Con pipe interno | `ec=0`, salida del pipe capturada |
| Fallo en la primera parte de un `&&` | `ec` distinto de cero |

Sin la envoltura con llaves, una redirección al final de un compuesto solo captura el último
tramo: por eso la forma es `{ … ; } >` y no `CMD >`.

### La envoltura con llaves está MAL, y solo se vio midiendo por el camino real

La medición de arriba se hizo **en el intérprete, no a través de la tool**. Al repetirla por el
camino real —hook con `updatedInput`, comando lanzado por la tool `Bash`— apareció un defecto que
la primera no podía ver:

| | Corre el extracto | Código de salida | Shell posterior |
|---|---|---|---|
| `{ CMD ; } > f` | **NO** | 7 (correcto) | sobrevive |
| `( CMD ) > f` | **sí** | 7 (correcto) | sobrevive |

**`{ }` no crea subshell**, así que un `exit` dentro del comando del usuario termina el script
entero y el extracto nunca se produce: el modelo recibe el error y **cero salida**. Con `( )` el
`exit` se queda en el subshell, el extracto corre y el código se propaga igual.

La primera medición no podía detectarlo porque su caso de prueba metía el `exit` dentro de un
`sh -c`, o sea en un proceso hijo. Es [[probar-la-pieza-no-es-probar-el-uso]] en el propio
research de este cambio.

**Efecto secundario del subshell, que hay que asumir por escrito:** con `( )`, un `cd` o una
asignación del comando no persisten para la llamada siguiente. No bloquea el diseño —un comando
que solo cambia de directorio no escupe salida y por tanto no es candidato a reescritura, y un
`cd X && comando` mantiene el `cd` dentro del mismo comando, que es lo que se quiere— pero es una
diferencia de comportamiento observable y debe quedar dicha.

Verificado además a través de la tool real: el código de salida **llega** a la herramienta
(`Exit code 7`) y la shell persistente **sobrevive** al `exit` (un comando posterior funcionó).

### Payloads reales de los hooks (capturados, no supuestos)

`PreToolUse` entrega `session_id`, `transcript_path`, `cwd`, `prompt_id`, `permission_mode`,
`hook_event_name`, `tool_name`, `tool_input` y **`tool_use_id`** — este último es lo que da un
nombre de fichero único por llamada sin riesgo de colisión.

`PostToolUse` entrega además **`tool_response`** (`stdout`, `stderr`, `interrupted`, `isImage`,
`noOutputExpected`) y `duration_ms`. Es lo que hace viable la capa de aprendizaje: el tamaño de
salida se puede medir sin volver a ejecutar nada.

Los dos payloads se capturaron con un hook de volcado en un directorio aislado. Advertencia para
quien reconstruya la medición: el `stdout` que llega al hook es el mismo que ve el modelo, o sea
que **ya viene truncado** — sirve para saber que la salida fue grande, no cuánto se perdió. De
ahí que la señal «vino truncada» valga por sí misma.

### EL CLIENTE YA HACE ESTO (medido el 2026-09-08, empezando T3)

Al ir a capturar un payload real de `PostToolUse` para saber cómo detectar el truncado, apareció
en `tool_response` algo que la captura del research original no tenía: **`persistedOutputPath` y
`persistedOutputSize`**.

Claude Code **ya guarda entera la salida grande de un comando Bash en un fichero** y **le da la
ruta al modelo**. Literal de lo que recibe el modelo, preguntado en una sesión aislada:

> `<persisted-output>` — Output too large (1.2MB). Full output saved to:
> `…	ool-resultsg0j44k0b.txt` — Preview (first 2KB) …

Medido con cuatro tamaños, leyendo el payload del hook y no lo que diga nadie:

| Salida real | `len(stdout)` que llega al hook | `persistedOutputSize` |
|---|---|---|
| 23 892 | 23 892 (completa) | ninguno |
| 43 893 | **30 000** (cortada) | 43 893 |
| 90 894 | **30 000** | 90 894 |
| 228 894 | **30 000** | 228 894 |

**No hay franja intermedia**: pasar de 30 000 caracteres y persistirse ocurren a la vez. O sea que
el problema que este cambio existe para resolver —que la salida grande entre al contexto o se
pierda— **ya está resuelto en el cliente**: al modelo le llegan 2 KB de preview y la ruta del
fichero completo.

**Por qué no se vio antes.** El research capturó los payloads con comandos de salida pequeña, y
estos dos campos **solo aparecen cuando la salida es grande**. El caso de prueba no podía
distinguir — el mismo defecto que ya costó una jornada entera en este proyecto. Se confirma con el
primer payload capturado hoy, el de un `seq 1 200000 > /dev/null`: `tool_response` trae cinco
claves y ninguna es `persistedOutputPath`.

**Qué queda en pie.** No el mecanismo, pero sí el hueco: el modelo tiene la ruta y **no sabe qué
hacer con ella**. Puede leerla con `Read` —cara— o resumirla con `local_lint_summary(path=…)`
—barata—. Un `PostToolUse` puramente consultivo que dispare **solo cuando `persistedOutputPath`
está presente** cubre el valor entero del cambio y se ahorra todo lo caro:

- no reescribe ningún comando, así que **el bypass del allowlist desaparece**;
- no necesita fichero propio, ni nombre por `tool_use_id`, ni limpieza por antigüedad;
- no necesita semilla ni aprendizaje, porque la señal **no es una predicción sobre el comando
  sino un hecho observado después**: cuando avisa, la salida grande ya existe.

Ese último punto es el que importa de verdad. Las tres mediciones de adopción concluyeron que el
problema no era la obediencia sino la **puntería** —366 disparos, 1 acierto—. Un aviso que solo
puede dispararse cuando la salida ya se persistió tiene puntería perfecta por construcción, que es
la condición que [[obediencia-no-viene-de-la-prosa]] señalaba como no cumplida.

#### Lo que se midió después, antes de tocar la spec

Cuatro preguntas más, porque el hallazgo de arriba cambia el cambio entero y conviene decidir con
datos y no con la primera impresión.

**1. El `stderr` grande también se persiste.** `seq 1 40000 >&2` da el mismo resultado: el hook ve
`stdout` de 30 000 y `stderr` vacío —Claude Code se los entrega combinados— y `persistedOutputSize`
de 228 894. No hay agujero por ahí.

**2. `PostToolUse` NO se dispara cuando el comando falla.** Medido con control positivo y negativo
**en la misma corrida**: `sh -c 'echo BETA; exit 0'` produce payload y `sh -c 'echo ALFA; exit 3'`
no produce ninguno, aunque el comando se ejecutó (el modelo reportó el código 3 y la salida).

Esto es serio para cualquier diseño apoyado en `PostToolUse`: **el aprendizaje no vería nunca un
comando que falla**, y un aviso post-hoc tampoco aparecería ahí — que es justo cuando la salida
importa, porque los logs de error y los tests rojos son los que hay que leer.

**3. El umbral de 30 000 es configurable con `BASH_MAX_OUTPUT_LENGTH`.** Con la variable a 5 000,
`seq 1 5000` —23 893 chars, que con el default llega entero y sin persistir— pasa a llegar cortado
a 5 000 **y persistido**. Es una palanca de una línea sobre el mercado real que midió el corpus:
42 salidas de 8 KB o más en 21 días, casi todas por debajo del umbral por defecto.

**4. Alcance de lo medido.** Claude Code 2.1.263 en Windows. `opencode` no está instalado en esta
máquina y la Mac no estaba a mano: **si el mecanismo existe en los otros clientes, sin verificar**.

#### Qué hace el modelo de verdad con una salida grande (cuatro trazas)

La pregunta que decide si queda hueco: cuando la salida es grande, ¿el modelo la vuelca al
contexto? Medido con un hook que traza cada tool en una sesión aislada, con
`BASH_MAX_OUTPUT_LENGTH=5000` para que el caso se dispare con salidas manejables.

| Tarea | Qué hizo | ¿Entró la salida al contexto? |
|---|---|---|
| Sumar los 5 000 números que imprime | Re-ejecutó con `awk '{s+=$1}'` | No |
| Decir la última línea (sólo está en el fichero: el preview son los primeros 2 KB) | **`tail -n 3`** sobre `persistedOutputPath` | No |
| Contar los tipos de ERROR de una salida de 4 000 líneas | Re-ejecutó con un `awk` agregador | No |
| Lo mismo, pero con una **suite lenta** (12 s), donde re-ejecutar sí duele | **Redirigió él solo a un fichero** (`> /tmp/suite-out.txt 2>&1`) y agregó con `grep -o … \| sort \| uniq -c` | No |

**Cuatro de cuatro sin volcado.** Y en el cuarto el modelo hizo *por iniciativa propia* justo lo
que este cambio iba a forzar reescribiendo comandos — sin hook, sin bypass de permisos y sin
tocar nada.

Ni una sola vez usó `Read` ni una tool `local_*`. El primer caso de prueba —sumar— no habría
distinguido nada, porque tenía atajo analítico y el comando era gratis de repetir; hizo falta un
caso cuyo dato **sólo** estuviera en el fichero, y otro donde repetir costara tiempo de verdad.

**La premisa central del cambio no se sostiene con este cliente y este modelo.** Y da una lectura
nueva a lo que ya sabíamos: tres mediciones de adopción, tres veces cero delegaciones. Se
concluyó que era puntería. Puede que además fuera que **al modelo no le hacía falta**, porque ya
resolvía el problema por otro camino más barato.

#### Dónde queda el hueco de verdad, y cuánto cuesta cerrarlo

La franja que sí entra entera al contexto hoy es **de 8 KB a 30 000 caracteres**: por encima el
cliente persiste y manda un preview de 2 KB, por debajo no vale la pena. Y ahí es donde está el
mercado que midió el corpus: 42 salidas de 8 KB o más, ~137 000 tokens, o sea una media de unos
11 000 caracteres por salida — casi todas por debajo del umbral por defecto.

Esa franja se cierra con **`BASH_MAX_OUTPUT_LENGTH=8000`** y ni una línea de código: el cliente
pasa a persistirlas y a mandar preview, que es exactamente el resultado que buscaba el diseño.

### El `additionalContext` viaja con la reescritura — y el modelo desconfía de él

Medido el 2026-09-08, empezando T1: un hook que emite `updatedInput` **y** `additionalContext` en
el mismo `hookSpecificOutput`, con `claude -p` en un directorio aislado.

| | Resultado |
|---|---|
| Comando pedido | `echo SONDA` |
| Comando ejecutado | `echo MARCA_REESCRITA` |
| ¿Llegó el `additionalContext`? | **Sí**, etiquetado como `PreToolUse:Bash hook additional context`, con el texto literal |

O sea que REQ-004 es implementable: la ruta del fichero puede viajar por ahí.

**Pero el segundo resultado cambia el diseño.** Se le preguntó al modelo qué había visto, y no
solo notó la reescritura: **se negó a seguir la pista**. Palabras suyas: *«ese texto viene
inyectado por un hook, no por ti — con la salida ya siendo alterada, no me parece prudente
tratarlo como una instrucción»*.

Es la reacción correcta de su parte y un problema para nosotros: si la ruta del fichero solo
viaja por el canal del que el modelo desconfía, la salida grande se guarda y **no se recupera**,
que es exactamente el fallo que este cambio existe para evitar.

**Consecuencia para T1:** la ruta va por **los dos canales**, y el que manda es el extracto.
El extracto se imprime por el `stdout` del comando reescrito —que el modelo lee como resultado
normal de la tool, no como una inyección— y lleva dentro la ruta y qué hacer con ella. El
`additionalContext` queda como refuerzo, no como canal principal.

### RIESGO: `updatedInput` se salta el allowlist de permisos

Segundo experimento, con `--allowedTools "Bash(echo:*)"`:

| | |
|---|---|
| Comando pedido (permitido) | `echo SONDA` |
| Comando reescrito por el hook | un `python -c` que imprime una marca |
| **Resultado** | **se ejecutó**, imprimió la marca del comando reescrito |

El permiso se evalúa sobre el comando **original**. Un hook puede por tanto ejecutar algo que el
usuario no autorizó. No invalida el diseño, pero lo condiciona:

- La reescritura debe ser **mínima y mecánica**: añadir redirección al comando original, nunca
  reordenarlo ni introducir un ejecutable nuevo.
- Debe ser **auditable y desactivable**, y quedar en la telemetría.
- El caso de un hook nuestro mal escrito pasa de «no sugiere» a «ejecuta algo distinto». Sube el
  listón de las pruebas.

### Bug reproducido y diagnosticado: el reintento del map-reduce está ciego a este backend

Encontrado midiendo otra cosa. `local_summarize(path=…)` sobre el `CHANGELOG.md` del propio repo
(122 435 chars) devuelve `Context size has been exceeded` y se rinde. Falla igual por llamada
directa y a través de un subagente, así que no es del llamante.

El mecanismo para esto **ya existe y está bien pensado**: `_map_piece` reintenta partiendo el
trozo cuando el backend dice que no cabe, hasta dos niveles, precisamente porque el presupuesto
va en chars y el límite del modelo en tokens. La puerta de entrada a ese reintento es
`_es_desborde_de_contexto()`, que compara el texto del error contra tres marcas literales
(`server.py:1027`):

| Marca que busca | ¿Casa con `Context size has been exceeded.`? |
|---|---|
| `exceed_context_size` | **no** |
| `exceeds the available context` | **no** |
| `context window` | **no** |

**Ninguna casa**, así que ese desborde se considera un error cualquiera y se vuelve terminal: el
trozo nunca se reintenta más pequeño. Verificado programáticamente, con control positivo (un
mensaje con `exceeds the available context` sí se reconoce, o sea que la comprobación
discrimina).

Números del troceado, sacados instrumentando `_run_chat`: para `MODEL_LONG` el presupuesto es
`48 000 × 0,8 = 38 400` chars, y el primer trozo del CHANGELOG mide **37 954** — cabe en chars y
no en tokens, que es exactamente el fallo que el reintento existe para absorber.

Horquilla observada: **113 341 chars sí pasaron** en el histórico; **122 435 no**.

#### Corrección del 2026-09-08 (implementando T10): el bug es más pequeño de lo que decía aquí

Al ir a verificar de extremo a extremo, el caso de prueba **dejó de reproducir el fallo**, así que
se midió el backend real en vez de dar por bueno el diagnóstico. Tres hechos nuevos, y dos frases
de arriba que hay que leer corregidas:

| Medición de hoy | Resultado |
|---|---|
| `local_summarize(path=CHANGELOG.md)` por el daemon publicado (0.26.0, código sin arreglar) | **funciona**: 4 partes, 5 pasadas, `ok=true` |
| `local_summarize(path=uv.lock)` (197 949 chars, contenido denso) | **funciona con reintentos**: 7 partes en **18 pasadas**, o sea el reintento por desborde se disparó y resolvió |
| Fichero denso de 47 000 chars en **una sola** llamada | `400` con `request (22171 tokens) exceeds the available context size (16384 tokens)`, tipo `exceed_context_size_error` — **sí casa** con las marcas viejas |

O sea: **hay dos desbordes distintos y solo uno estaba ciego.**

- **El `400`** —el prompt no cabe, validado antes de procesar— **siempre se reconoció** y el
  reintento adaptativo funciona hoy mismo: las 18 pasadas del `uv.lock` son la prueba viva.
- **El `500`** —`Context size has been exceeded.`, error de servidor durante el procesamiento—
  es el que no se reconocía. Es el que se observó ayer, y **es intermitente**: mismo fichero,
  mismo tamaño de trozo, ayer falló y hoy pasa.

El texto exacto del `500` se reconstruyó del log, que guarda el código y el tamaño pero no el
cuerpo. Los dos eventos fallidos (`2026-09-08T18:20:48Z` y `:49Z`) traen `error: "http_500"`,
`chars_out: 137` y **sin campo `chunks`** —que `_log_event` omite cuando vale 1, o sea **una sola
llamada al backend y ningún reintento**—. Y 137 es exactamente el prefijo
`[local-delegate error] llama31-8b respondió 500: ` (49) más
`{"error":{"code":500,"message":"Context size has been exceeded.","type":"server_error"}}` (88).
Cuadra al carácter.

**Qué queda en pie y qué no:**

- ✅ El defecto existe: un mensaje real de este backend no dispara el reintento.
- ✅ El paralelismo con el hook —lista blanca de literales de un proveedor— se sostiene entero.
- ❌ «El mecanismo de reintento queda **anulado por completo**»: falso. Está ciego a una de las
  dos formas, no a las dos.
- ❌ «El `CHANGELOG.md` **hoy falla**»: hoy no. No es un reproductor; el `500` no se ha
  conseguido provocar a voluntad y no se ha aislado su disparador (la sospecha es la
  concurrencia partiendo el `n_ctx` de 16 384 entre slots, **sin confirmar**).

`n_ctx` medido de `llama31-8b`: **16 384**.

Nota de método: instrumentar `_run_chat` desde un proceso propio da **401**, porque la clave del
backend la tiene el daemon y no el shell. El dato del presupuesto y del tamaño del trozo se
obtiene igual, que era lo que hacía falta.

**El paralelismo vale la pena verlo:** esto es el mismo defecto de fondo que el hook de lint —una
lista blanca de literales de un proveedor concreto, que falla en silencio cuando el proveedor
dice lo mismo con otras palabras—. Dos sitios distintos del repo, la misma forma de romperse.

### Estado del arte: ya hay cuatro implementaciones con números

| Proyecto | Qué hace | Números |
|---|---|---|
| token-saver | 36 procesadores por ecosistema | `npm install` 99,9 %, `pytest` 95–98 %, `cargo build` 98 %, `pip install` 95 %, `docker build` 88 %, `eslint` 89 %, `ruff` 87 %, `git diff` 76 % |
| HumanLayer (`run_silent`) | Silencio en éxito, salida entera en fallo | «200+ líneas» a un solo `✓` |
| build-output-tools-mcp | Rutea build/test a un LLM barato (lo mismo que nosotros) | **85 %**; pytest 3 017 a 458 tokens |
| build-brief | Gradle | `assembleDebug` 16 módulos: **414 líneas a 5** |

Tres cosas aprovechables:

1. La **cobertura por ecosistema** de token-saver (JVM, Rust, Go, .NET, Ruby, PHP, infra, cloud,
   datos, `nix`, `bazel`, `make`) resuelve el sesgo de perfil de la semilla.
2. Su arquitectura es **36 procesadores específicos más un fallback genérico** que acepta
   cualquier comando. No es una lista cerrada.
3. build-output-tools-mcp tuvo que añadir **recuperación del log crudo**, porque a veces hace
   falta el stack trace completo. Nuestro `local_lint_summary(path=…)` ya deja el fichero en
   disco, así que lo tenemos gratis si el fichero no se borra.

Enlaces: `github.com/ppgranger/token-saver`,
`humanlayer.dev/blog/context-efficient-backpressure`,
`gordles.io/blog/llm-friendly-test-suite-outputs-pytest-llm`, `bb.staticvar.dev`,
`github.com/anthropics/claude-code/issues/12054` y `/19901`, `code.claude.com/docs/en/hooks`.

## Mapa de impacto

17 ficheros mencionan el hook o la tool. Los que el cambio toca de verdad:

| Superficie | Qué hay hoy | Qué implica |
|---|---|---|
| `resources/hooks/suggest_lint_summary.py` | regex sobre el comando, `emit` consultivo | núcleo del cambio |
| `resources/hooks/hook_common.py` | `emit`/`record`, telemetría opt-in | soportar `updatedInput` y un evento nuevo |
| `install.py` (`_HOOK_EVENTS`, `hook_command`, `_SCRIPT_NAMES`, `merge_hook_settings`) | registra lint por defecto; string único con comillas por el incidente de Windows | registrar un `PostToolUse` nuevo; decidir si sigue por defecto |
| `checks.py` (`_probe_hook_files`, `_probe_hook_orphans`, `_probe_hook_settings`) | tres checks sobre los hooks | un script nuevo cambia lo que se espera encontrar |
| `server.py::local_lint_summary` | acepta `path`, **no trunca** (`_NO_TRUNCATE`) | **no requiere cambios**: ya es la pieza correcta |
| `tests/test_install.py`, `test_checks.py`, `test_smoke.py` | cubren registro y checks | ampliar |
| `docs/recipes/claude-code-hooks.md`, `claude-code-integration.md` | documentan el registro manual | actualizar |
| `docs/wiki/Architecture.md`, `Savings-and-metrics.md` | describen el mecanismo | actualizar |
| `resources/skills/delegacion-local/SKILL.md` | cataloga la tool | revisar el texto |

Fuera de alcance: el hook de `read` (ya arreglado en #146) y el de `prompt`.

## Preguntas abiertas para la fase de especificación

1. **¿Reescribir o solo avisar?** La reescritura es lo único que no depende de obediencia, y lo
   único que esquiva el truncado. Pero se salta el allowlist y es intrusiva.
2. **¿Qué shell?** La redirección difiere entre PowerShell y bash, y esta máquina usa los dos.
   Reescribir mal un comando es peor que no reescribirlo.
3. **Escapes obligatorios**: no tocar comandos que ya redirigen (`>`, `>>`), que ya pipean a
   `head`/`tail`, interactivos, o con heredoc. El `ssh … <<EOF` de los datos es exactamente uno
   que no hay que tocar.
4. **Preservar el exit code** tras la redirección, o se rompe todo encadenamiento con `&&`.
5. **¿Dónde vive el fichero?** Hace falta una ruta previsible y limpiable, y que el fichero
   sobreviva para poder recuperar el crudo.
6. **La capa de aprendizaje**: un `PostToolUse` que registre `ejecutable -> tamaño de salida` y
   si vino truncada, para que la decisión deje de depender de una lista. Definir umbral, ventana
   y dónde se guarda.
7. **¿Sigue encendido por defecto?** Hoy lo está, con 0,3 % de puntería.

## Lo que esta investigación descarta

- **Ampliar la regex con más comandos**: medido, techo ~9 %.
- **Bloquear (`permissionDecision: deny`)**: con la puntería actual denegaría 366 comandos
  legítimos para cazar uno.
- **Calibrar con los datos de esta máquina**: el corpus no contiene el perfil donde la lista
  funcionaría.
