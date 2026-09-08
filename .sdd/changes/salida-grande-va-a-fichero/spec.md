# Specification: La salida grande va a fichero, no al contexto

## Summary

Cuando un comando de Bash va a producir una salida grande, esa salida deja de entrar al contexto
caro: se escribe entera a un fichero y al modelo solo le vuelve un extracto, con la ruta para
resumirla con `local_lint_summary(path=…)` o leer el crudo si hace falta.

La decisión de cuándo hacerlo deja de ser una regex de nombres de comando —medida al **0,3 %** de
puntería— y pasa a apoyarse en dos cosas: una semilla curada por ecosistema, y **el tamaño de
salida que esa máquina ya ha observado** para ese ejecutable. Así el criterio no está calibrado
al perfil de nadie: cada instalación aprende del suyo.

## Requirements

### Decisión y reescritura

- **REQ-001:** El hook actúa solo cuando `tool_name` es `Bash`. Cualquier otro valor se ignora
  sin registrar sugerencia.
- **REQ-002:** Cuando decide actuar, el hook devuelve `hookSpecificOutput.updatedInput` con el
  comando reescrito de forma que (a) toda la salida —stdout y stderr— va a un fichero, (b) al
  modelo le vuelve solo un extracto, y (c) **el código de salida del comando original se
  preserva**.
- **REQ-002b:** El comando original se envuelve en un **subshell**, no en un grupo de llaves. Está
  medido a través de la tool real: con llaves, un `exit` dentro del comando del usuario termina el
  script entero y **el extracto no llega a producirse** —el modelo recibe el error y cero salida—;
  con subshell el `exit` se queda dentro, el extracto corre y el código se propaga igual.

  **El efecto secundario del subshell no es el caso inofensivo, sino el que este diseño fabrica.**
  Un comando que solo cambia de directorio nunca sería candidato, cierto — pero el candidato
  típico es el **compuesto**: `cd build && make`, `cd app && npm run build`. De los 42 casos de
  salida grande del corpus, **23 empiezan por `cd`**, y la normalización del ejecutable salta ese
  prefijo justamente para volverlos candidatos.

  Medido en la tool real: **el cwd sí persiste entre llamadas** (dentro del proyecto; salir de él
  lo resetea con aviso), y **las variables exportadas no persisten** ni siquiera hoy. O sea que
  las asignaciones no pierden nada, y el `cd` sí.

  Decisión: cuando el comando empieza por un **prefijo `cd` simple**, ese prefijo queda **fuera
  del subshell** y solo se envuelve el resto: `cd build && ( make ) > fichero …`. Así el cwd se
  comporta exactamente como hoy y el `exit` del comando real sigue aislado. Esto no contradice
  REQ-003: no reordena nada, solo decide dónde empieza el paréntesis. Si el `cd` falla, el `&&`
  corta antes de ejecutar nada, igual que hoy.
- **REQ-002c:** Los escapes de REQ-006 se evalúan **sobre el comando original**, nunca sobre uno
  ya reescrito: el reescrito contiene por construcción redirección y utilidades de extracto, y
  volver a evaluarlo lo descartaría por sus propias marcas.
- **REQ-003:** La reescritura **no reordena el comando original** ni introduce ejecutables
  elegidos en tiempo de ejecución: lo envuelve, le añade redirección y le añade el andamiaje del
  extracto. El andamiaje solo puede usar una **lista cerrada y fija de utilidades**, escrita en
  el código y nunca derivada del comando del usuario ni de su entorno. Ninguna parte del comando
  original puede acabar en posición de ejecutable del andamiaje.

  *Por qué se redacta así:* la primera versión decía «no introduce ejecutables nuevos», y la
  revisión adversarial del plan encontró que eso hacía imposible REQ-005 —cualquier extracto
  necesita algo que lo produzca—. El requisito real no era «cero ejecutables», sino **que la
  transformación no pueda meter un ejecutable arbitrario**, que es lo que convierte el bypass de
  permisos en superficie de ataque. Una lista cerrada y fija cumple eso; «cero» no era cumplible.

- **REQ-003b:** Añadir una utilidad a esa lista es un cambio de superficie de seguridad: exige
  decisión explícita y queda registrado, no se hace de paso.
- **REQ-004:** El fichero de salida se nombra con el `tool_use_id` del payload, que es único por
  llamada, y su ruta se comunica al modelo por `additionalContext`.
- **REQ-004b:** Los ficheros de salida **no viven bajo el directorio de hooks instalado**. Cada
  `install` borra ese árbol entero antes de recopiarlo, así que guardarlos ahí los perdería en la
  siguiente instalación —y, peor, haría que reinstalar borrase una salida en curso—. La ubicación
  debe sobrevivir a una reinstalación y ser limpiable por antigüedad.
- **REQ-005:** El extracto que vuelve es más corto cuando el comando termina con éxito y más
  largo cuando falla.

### Cuándo NO se reescribe

- **REQ-006:** No se reescribe un comando que ya redirige a fichero (`>`, `>>`), que ya acota su
  salida con `head`/`tail`/`less`/`more`, o que contiene un heredoc (`<<`).
- **REQ-007:** No se reescriben **nunca** los comandos de lectura de ficheros (`cat`, `sed`,
  `head`, `tail`, `bat`, `less`, `more`) **cuando son el comando que el modelo pidió**, aunque su
  salida sea grande y aunque el aprendizaje los proponga. El modelo los usa para leer contenido
  literal que necesita íntegro, y resumirlo sería el error que este proyecto ya tiene documentado.

  Esto es independiente de que alguna de esas utilidades aparezca en el **andamiaje** del
  extracto (REQ-003): una cosa es el comando del usuario y otra la maquinaria que lo envuelve.
  La spec anterior confundía las dos y la revisión del plan lo señaló.
- **REQ-008:** No se reescribe cuando `permission_mode` indica que no se va a ejecutar nada.
- **REQ-009:** Ante un comando que el hook no sabe transformar con seguridad, **no se toca**. El
  fallo seguro es dejarlo pasar tal cual.

### Candidatura

- **REQ-010:** Un comando es candidato si su ejecutable está en la **semilla por ecosistema**
  (derivada del estado del arte, no del corpus de esta máquina) **o** si el aprendizaje local
  registra que ese ejecutable superó el umbral de tamaño en una proporción suficiente de sus
  últimas ejecuciones, con un mínimo de muestras.
- **REQ-011:** La semilla cubre, como mínimo, un representante de cada ecosistema mayor: JS/TS,
  Python, JVM, .NET, Go, Rust, Ruby, PHP, móvil, infraestructura, contenedores, cloud y logs de
  sistema. No se limita a los ecosistemas que usa el autor.
- **REQ-012:** La pertenencia a la semilla **no basta por sí sola** para reescribir si el
  aprendizaje local de esa máquina contradice la semilla con muestras suficientes.

### Aprendizaje

- **REQ-013:** Un hook `PostToolUse` sobre `Bash` registra, por ejecución: el ejecutable
  normalizado, el tamaño de `stdout`+`stderr`, si la salida llegó **truncada**, y la duración.
- **REQ-014:** El hook de aprendizaje **nunca emite contexto al modelo**. Es silencioso por
  contrato.
- **REQ-015:** El registro no guarda el comando completo, ni rutas, ni argumentos: solo el
  ejecutable y magnitudes, coherente con la política de la telemetría actual.
- **REQ-016:** La señal «llegó truncada» pesa más que el tamaño: indica pérdida de información,
  no solo coste.
- **REQ-016b:** El umbral de tamaño, la proporción exigida y el mínimo de muestras son
  **parámetros con valor por defecto**, ajustables por entorno como ya lo son las bandas del hook
  de lectura. La spec no fija sus valores: los fija la medición del replay.

### Instalación y diagnóstico

- **REQ-017:** El hook de reescritura queda **apagado por defecto**. Se enciende explícitamente,
  y el registro mismo es la única fuente de si está activo, como ya se resolvió para el hook de
  lectura.
- **REQ-018:** El hook de aprendizaje puede instalarse por separado del de reescritura, porque no
  molesta a nadie.
- **REQ-019:** `install`, `uninstall` y `doctor` conocen los scripts nuevos: se registran, se
  desregistran y se comprueban como los actuales, incluida la limpieza de versiones previas.
- **REQ-019b:** **`update` no puede apagar en silencio un interruptor que el usuario encendió.**
  Hoy `update` repara la instalación construyendo opciones con los opt-in en su valor por
  defecto, así que una reparación desregistraría los hooks opt-in sin decirlo. Es el mismo patrón
  que ya mordió con la cabecera de autorización que se borraba al reinstalar. O `update` preserva
  el estado observado, o lo dice; en ningún caso lo apaga callando.
- **REQ-019c:** Un script que deja de empaquetarse **sigue siendo reconocible como retirado**,
  para que `install` pueda limpiar la copia vieja y `doctor` no la reporte como ajena. La
  pertenencia «esto es nuestro» no puede depender solo de qué hay hoy en el paquete, porque
  entonces todo lo que se retira se vuelve inmortal.
- **REQ-020:** Los ficheros de salida se limpian por antigüedad, sin intervención del usuario.
- **REQ-021:** El almacén del aprendizaje **no depende de que la telemetría esté activada**. La
  telemetría es opt-in y está vacía por defecto; si el aprendizaje colgara de ella, sería un
  no-op en cualquier máquina que no la haya encendido, y los tests no lo verían porque la
  encienden siempre.
- **REQ-022:** Los hooks leen su configuración de `os.environ` directamente —son stdlib pura, se
  ejecutan fuera del paquete y no pueden importarlo—, pero **el nombre de cada variable nueva se
  declara además en el módulo de configuración** por los helpers que alimentan el inventario, de
  modo que el aislamiento de la suite la limpie. Sin esa declaración, la variable existe para el
  hook y es invisible para el inventario, y los tests heredan el entorno de quien los corre.

  *Por qué se redacta así:* la primera versión exigía que el hook leyera por los helpers, lo cual
  **no es implementable** —el hook no puede importar el paquete— y además dejaba el riesgo sin
  tapar, porque el guardián del aislamiento solo mira el módulo de configuración.

### El reintento del map-reduce (añadido al alcance el 2026-09-08)

Entra porque el cambio no sirve de nada si la tool a la que manda el trabajo se rinde con los
ficheros grandes, que son justo los que este hook va a producir. Es pequeño y localizado; si al
implementarlo creciera, sale a un cambio propio.

- **REQ-023:** Un desborde de contexto reportado por el backend **dispara el reintento
  adaptativo**, independientemente de cómo esté redactado el mensaje y del código HTTP que lo
  traiga. Hoy la detección compara contra tres literales, que cubren el `400` de validación
  (`exceeds the available context size`) pero **no** el `500` de procesamiento
  (`Context size has been exceeded.`), y en ese segundo caso el map-reduce se rinde en el primer
  trozo sin reintentar ni una vez.
  *(Corregido el 2026-09-08 al medir: el enunciado original decía que el reintento estaba
  «anulado por completo» y no lo está —el `400` sí lo dispara, verificado con `uv.lock` en 18
  pasadas—. Ver la corrección en `research.md`.)*
- **REQ-024:** La detección no puede depender de la redacción exacta de un proveedor: se compara
  de forma insensible a mayúsculas y cubriendo las formas en que los backends del catálogo
  expresan lo mismo. Es el mismo defecto que este cambio corrige en el hook —una lista blanca de
  literales ajenos— y no debe repetirse aquí.
- **REQ-025:** ~~Un fichero que hoy falla debe resumirse correctamente. El caso de prueba es
  reproducible y vive en el repo: `CHANGELOG.md`, 122 435 caracteres.~~
  **Retirado el 2026-09-08: el caso de prueba no discrimina.** El `CHANGELOG.md` se resume sin
  error con el código *sin arreglar*, así que no puede demostrar nada. El `500` que se observó
  ayer es intermitente y no se ha logrado provocar a voluntad. En su lugar, la evidencia de
  REQ-023/024 es (a) el **test de regresión con el mensaje real**, que falla contra el código de
  ayer y pasa con el de hoy, y (b) la **reconstrucción del `500` desde el log**, que cuadra al
  carácter. Queda como verificación de no-regresión —no de arreglo— que `CHANGELOG.md` y
  `uv.lock` sigan resumiéndose con el código nuevo contra el backend real.
- **REQ-026:** Si tras agotar el reintento el contenido sigue sin caber, la tool lo dice de forma
  accionable, no devuelve el error crudo del backend. Esto **no** se resuelve en la detección: el
  mensaje que ve el usuario se construye en el camino de error del map-reduce, así que el alcance
  de ficheros de la tarea tiene que incluirlo explícitamente o el requisito se queda sin dueño.

## Acceptance scenarios

### Scenario: una salida grande no entra al contexto y no se pierde

- **Given** el hook de reescritura encendido y un comando candidato que produce más de 30 000
  caracteres
- **When** el modelo lo ejecuta
- **Then** al contexto solo llega el extracto, el fichero en disco contiene la salida **entera y
  sin truncar**, y el `additionalContext` nombra la ruta

### Scenario: el código de salida sobrevive

- **Given** un comando candidato que termina con un código de salida distinto de cero
- **When** el hook lo reescribe
- **Then** la llamada reporta ese mismo código, y un encadenamiento con `&&` se comporta igual
  que sin el hook

### Scenario: un comando que ya se acotó no se toca

- **Given** un comando candidato que ya termina en `| tail -20`, o que ya redirige a un fichero,
  o que lleva un heredoc
- **When** el hook lo evalúa
- **Then** devuelve el comando intacto y no registra sugerencia

### Scenario: leer un fichero sigue devolviendo el fichero

- **Given** un `cat` o un `sed -n` sobre un fichero de código, aunque su salida supere el umbral
- **When** el hook lo evalúa
- **Then** no lo reescribe

### Scenario: la máquina aprende de su propio perfil

- **Given** un ejecutable que no está en la semilla y que en esa máquina ha superado el umbral en
  la mayoría de sus últimas ejecuciones, con muestras suficientes
- **When** vuelve a ejecutarse
- **Then** es candidato

### Scenario: el aprendizaje es silencioso

- **Given** solo el hook de aprendizaje instalado
- **When** se ejecuta cualquier comando
- **Then** no llega ningún `additionalContext` al modelo, y el registro contiene la magnitud de
  la salida sin el comando ni sus argumentos

### Scenario: apagado por defecto

- **Given** una instalación limpia sin banderas
- **When** se ejecuta un comando de la semilla
- **Then** no se reescribe nada

## Edge cases and failure behavior

- **El hook falla o tarda:** cualquier excepción no controlada se traduce en «no tocar el
  comando». Un hook roto no puede degradar la sesión.
- **Fichero no escribible** (disco lleno, permisos, ruta inválida): no se reescribe.
- **Comando interrumpido** (`interrupted`): el aprendizaje descarta la muestra; el tamaño no es
  representativo.
- **Salida vacía o `noOutputExpected`:** no cuenta como muestra.
- **Concurrencia:** dos comandos simultáneos no pueden pisarse el fichero — lo garantiza el
  `tool_use_id`. El almacén del aprendizaje tolera escrituras concurrentes sin corromperse.
- **Almacén corrupto o ilegible:** se ignora y se cae a la semilla; nunca es un error visible.
- **Sin `stdout` en el payload:** el aprendizaje no registra, no adivina.

## Non-functional requirements

- **Seguridad:** `updatedInput` elude el allowlist de permisos (verificado en `research.md`). Por
  eso REQ-003 acota la transformación a envolver y redirigir. Cualquier cambio futuro que
  introduzca un ejecutable en la reescritura es un cambio de superficie de seguridad y necesita
  su propia decisión.
- **Privacidad:** ni el registro de aprendizaje ni la telemetría guardan comandos, argumentos o
  rutas. Los ficheros de salida sí contienen la salida real y por eso se limpian solos.
- **Rendimiento:** el hook corre en **cada** comando Bash. Su coste debe ser despreciable frente
  al del propio comando, y no debe hacer red ni llamar al daemon.
- **Compatibilidad:** la reescritura se emite solo para el intérprete que la tool `Bash` usa
  realmente. En cualquier otro caso aplica REQ-009.
- **Operabilidad:** el estado (encendido, apagado, qué aprendió) es visible por `doctor` y por la
  telemetría existente.

## Non-goals

- El hook de lectura (`suggest_delegate_read`) y el de prompt: fuera.
- La **firma y el contrato** de `local_lint_summary` y `local_summarize`: ya aceptan `path` y no
  truncan, y siguen igual. De `server.py` se tocan la detección de desborde **y el camino de error
  del map-reduce** (REQ-023…026), sin cambiar ninguna interfaz. Ese camino de error lo comparten
  los tres llamantes del map-reduce, así que el mensaje nuevo se acota al caso de desborde
  agotado y no altera los demás.
- `local_boilerplate` con `reference`/`target`: es otro cambio.
- Comprimir o filtrar la salida por contenido (lo que hace token-saver). Aquí solo se decide
  **dónde va** la salida; resumirla es trabajo de la tool que ya existe.
- Cubrir la tool `PowerShell` u otros shells: se acota al intérprete verificado.
- Recuperar el mercado de `cat` de código (17 de los 42 casos, ~58 K tokens): se descarta a
  propósito por REQ-007.

## Traceability

| Requisito | Evidencia que lo justifica (`research.md`) | Cómo se verificará |
|---|---|---|
| REQ-001…005 | `updatedInput` verificado en 2.1.263; sintaxis de envoltura probada en el intérprete real | Tests del módulo + una ejecución real con salida > 30 000 |
| REQ-006…009 | Los 42 casos del corpus incluyen un `ssh … <<EOF` que no hay que tocar | Tests por cada escape, con un caso real del corpus |
| REQ-007 | 17 de los 42 casos grandes son código leído literal | Test dedicado |
| REQ-010…012 | Ningún ejecutable supera el umbral de forma fiable (máx. 9 %); el corpus no contiene el perfil donde la lista funcionaría | **Replay del módulo real contra los 2 476 comandos del corpus**, midiendo precisión y cobertura |
| REQ-013…016 | `PostToolUse` entrega `tool_response` con `stdout`/`stderr`/`interrupted` y `duration_ms` | Test con payload real capturado |
| REQ-017…019 | El hook de 0,3 % es hoy el único encendido por defecto | Tests de `install`/`uninstall`/`doctor` |
| REQ-020 | — | Test de limpieza por antigüedad |
| REQ-002b/002c | Medido a través de la tool: con llaves el extracto no se produce; el cwd persiste entre llamadas y las variables no | Test del compuesto `cd x && cmd`, y una pasada por la tool real con un comando que lleve `exit` |
| REQ-019b | `update` construye las opciones con los opt-in en su valor por defecto | Test de ida y vuelta: encender, `update`, seguir encendido |
| REQ-019c | La limpieza de huérfanos sale del directorio empaquetado, así que lo retirado se vuelve inmortal | Test con una copia vieja en la raíz de `hooks/` tras retirar el script |
| REQ-021 | La telemetría es opt-in y está vacía por defecto | Test con telemetría apagada y aprendizaje funcionando |
| REQ-022 | El guardián del aislamiento solo escanea el módulo de configuración | El guardián existente, más un test de que el nombre está declarado |
| REQ-023/024 | `Context size has been exceeded` (el `500`) no casa con ninguna de las tres marcas; verificado con control positivo, y el cuerpo del error reconstruido del log al carácter | Test de regresión con el mensaje real, que debe fallar contra el código de hoy — comprobado: falla, y el mutante del mensaje accionable dispara su propio assert |
| REQ-025 | Retirado: el `CHANGELOG.md` se resume bien con el código sin arreglar, o sea el caso no discrimina | No-regresión de extremo a extremo (`CHANGELOG.md` y `uv.lock`) con el código nuevo contra el backend real |
| REQ-026 | El mensaje al usuario se construye en el camino de error, no en la detección | Test del caso de reintento agotado |

**Criterio de aceptación cuantitativo del gate de calidad:** medido por replay contra los 2 476
comandos reales del corpus, **la precisión de la reescritura debe ser ≥ 50 %** — al menos la
mitad de los comandos que el hook decidiría reescribir tuvieron salida ≥ 8 KB — frente al
**0,3 %** actual.

**La precisión sola no puede aprobar el gate.** Una política que reescriba tres comandos y acierte
dos marca 66 % y no entrega nada: la métrica no distingue «silencioso porque acierta» de
«silencioso porque no dispara», que es el patrón de medida no discriminante que este proyecto ya
tiene documentado. Se exige además:

- **Un denominador mínimo de decisiones**, fijado antes de medir: por debajo de él la precisión no
  es interpretable y el gate no se aprueba, aunque salga alta.
- **Un suelo de cobertura** sobre los 42 casos de salida ≥ 8 KB del corpus. Puede ser bajo y
  justificado —descontando los 17 que REQ-007 excluye a propósito, el techo alcanzable es 25—,
  pero tiene que existir.

Los tres números —denominador mínimo, suelo de cobertura y hueco tramposa/honesta— **se fijan
antes de la primera pasada honesta y quedan escritos como constantes en el propio script del
replay**, no en un comentario ni en la cabeza de nadie. El orden tiene que ser auditable: un
umbral que se escribe después de ver el resultado no es un umbral, es una justificación.

El objetivo primario sigue siendo dejar de hacer ruido; el suelo de cobertura solo impide aprobar
un hook que calle porque no hace nada.

**El replay tiene que ser cronológico y ciego al futuro.** Es la parte fácil de hacer mal: si el
aprendizaje se alimenta del corpus entero y luego se evalúa sobre ese mismo corpus, el hook
«acierta» porque ya vio el resultado, y la cifra no significa nada. El replay procesa los
comandos en orden temporal y, para cada uno, decide **solo con lo aprendido de los anteriores**.
La precisión se mide únicamente sobre las decisiones tomadas así. Una medición que no pueda
demostrar esta propiedad no vale para el gate.

**Y la ceguera hay que demostrarla verificando el mecanismo, no comparando resultados.** Un test
que compruebe «la decisión sobre el comando *i* no cambia si altero los posteriores» pasa por
construcción. Y comparar una pasada honesta contra una tramposa **tampoco basta**: si la honesta
estuviera leyendo el almacén real de esta máquina —veintiún días ya aprendidos—, su cifra subiría,
la tramposa seguiría siendo mayor, y el contraste daría verde con la medición contaminada. Se
exigen por tanto tres cosas, y las tres son falsables:

1. **Un espía sobre la apertura del almacén real** que asegure que esa ruta **no se abre ni una
   vez** durante el replay. Se verifica el mecanismo, no el resultado.
2. **Un hueco numérico declarado** entre la pasada tramposa y la honesta, fijado antes de medir.
   «Visiblemente mayor» no es un criterio.
3. **Arranque en frío comprobable**: en los primeros N comandos del corpus la cobertura debe ser
   prácticamente nula, porque ningún ejecutable llega aún al mínimo de muestras. Si ahí ya hay
   decisiones, el almacén viene precargado de algún sitio.

Corolario de lo anterior: la precisión medida en el replay será **peor** que la de régimen,
porque el corpus arranca en frío y buena parte de los ejecutables no llegan al mínimo de
muestras. El umbral del 50 % se exige sobre la cifra pesimista, no sobre la optimista.
