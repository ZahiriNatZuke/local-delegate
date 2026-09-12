# Specification: cadena de respaldo entre modelos locales y enfriamiento temporal por modelo

## Summary

Cuando el modelo local de una tool falla **por un motivo del modelo**, la tool reintenta una vez con otro
modelo local compatible del mismo endpoint y dice que respondió el respaldo. Un modelo que falla varias
veces seguidas se aparta un tiempo acotado; pasado ese tiempo se le deja una petición de prueba, y nunca
queda apartado para siempre.

Tres principios mandan sobre todo lo demás:

1. **Nada sale de la máquina.** El respaldo es otro modelo del mismo `LOCAL_DELEGATE_BASE_URL`.
2. **Nunca peor que hoy.** Si no hay candidato válido, o el mecanismo está apagado, o falla el propio
   mecanismo, el resultado es **exactamente el error de hoy**.
3. **Lo que no se sabe clasificar no penaliza.** Un error dudoso no aparta al modelo ni dispara el
   respaldo. Es la lección de los bugs de «baneado para siempre» de OmniRoute (#12859, #13157): nunca
   falló su circuit breaker, falló la clasificación, que mandaba lo imprevisto al peor caso.

## Clasificación de fallos

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

## Requirements

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

## Acceptance scenarios

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

## Edge cases and failure behavior

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

## Non-functional requirements

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

## Non-goals

- Proveedores remotos, o cualquier destino fuera del endpoint configurado.
- Reintentar el mismo modelo antes de saltar.
- Enrutar según la VRAM libre o el modelo cargado (idea 3 del análisis de OmniRoute, cambio aparte).
- Mandar un desborde de contexto a un modelo con más contexto: lo sigue tratando map-reduce.
- Respaldo para visión.
- Tocar la configuración de llama-swap.
- Quitar el código muerto `retry_exhausted` (se anota, no se toca).

## Decisiones del usuario (2026-09-11)

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

## Traceability

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
