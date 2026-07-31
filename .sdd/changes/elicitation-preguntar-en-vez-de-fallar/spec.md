# Specification: que una tool pregunte en vez de adivinar o fallar seco

## Summary

Tres situaciones en las que hoy el servidor falla seco pasan a preguntarle al usuario a través del
cliente MCP. Las tres comparten forma: **un fallo cuya solución el servidor ya conoce**.

1. **El backend está caído.** En vez de un error seco, la tool pregunta si arrancarlo — y lo arranca
   solo si el usuario dice que sí. No contradice la decisión de arquitectura «backend opt-in»: sigue
   sin arrancar nada sin permiso; lo que cambia es que ahora hay una forma de darlo en caliente.
2. **Un `model` que no está en el catálogo.** El servidor devuelve hoy un error que **ya incluye la
   lista de válidos**; en vez de eso, la ofrece para elegir.
3. **`output_format` vacío o en blanco** en `local_delegate`. Hoy pasa sin validar y el guardrail se
   queda sin formato, así que el modelo improvisa.

> **Corrección de premisa, y va aquí porque cambió el alcance.** Este change entró con «`local_delegate`
> recibe una tarea **sin** formato de salida». **Eso no puede pasar:** `output_format` es un
> parámetro **obligatorio** de la tool (`server.py:1301`), así que nunca falta. Lo que sí existe es
> que **venga vacío y nadie lo compruebe**, que es el caso 3. Un pendiente es una hipótesis hasta
> que se lee el código.

**Y preguntar nunca puede ser peor que no preguntar.** Está medido que un cliente que no contesta
cuelga la tool indefinidamente: sin plazo propio, esto empeoraría justo lo que viene a arreglar.

## Requirements

- **REQ-001:** Con el backend caído y un cliente que puede responder, la tool pregunta si arrancarlo
  antes de fallar.
- **REQ-002:** Si el usuario acepta, se intenta el arranque y se reintenta la operación una vez. Si
  declina o cancela, se devuelve **el mismo error que hoy**, sin ruido adicional.
- **REQ-003:** Un `model` que no esté en el catálogo hace que se ofrezcan **los modelos válidos**
  para elegir, en vez de devolver el error de texto. Elegido uno, la operación continúa con él.
  *(Acotado por la revisión del plan, B-3: `chunk` y `style` quedan fuera. Sus listas son fijas y
  están documentadas; la de `model` sale de la configuración de cada instalación, que es lo que hace
  imposible adivinarla y útil preguntarla.)*
- **REQ-003b:** Cuando no se pueda o no se quiera responder —mecanismo apagado, cliente sin soporte,
  plazo agotado, negativa—, un `model` inválido devuelve **el error inmediato de hoy y no consume
  backend**. *(Consecuencia que la revisión del plan obligó a escribir, B-2: con respuesta, una
  llamada que hoy falla al instante y gratis pasa a ejecutar inferencia. Es el cambio de
  comportamiento más visible del change y no debe descubrirse en producción.)*
- **REQ-004:** `output_format` vacío o solo espacios en `local_delegate` hace que se pregunte el
  formato. Con formato presente no se pregunta nada.
- **REQ-005:** No se pregunta si el cliente no declara `elicitation` **o** si la conexión no admite
  peticiones del servidor. Las dos condiciones se comprueban por separado.
- **REQ-006:** Toda pregunta tiene **plazo máximo**. Agotado el plazo, la tool **continúa como si no
  hubiera preguntado** — nunca se queda esperando y nunca falla *por* haber preguntado.
- **REQ-007:** Cualquier fallo del mecanismo de preguntar degrada al comportamiento actual, sin
  propagar la excepción al cliente.
- **REQ-008:** El comportamiento es **configurable y desactivable** por variable de entorno, con el
  plazo ajustable.
- **REQ-009:** El mecanismo **no altera el schema público de ninguna tool**.

## Acceptance scenarios

### Scenario: backend caído y el usuario acepta

- **Given** el backend no responde y el cliente declara `elicitation`
- **When** se llama a una tool que necesita el backend
- **Then** el usuario ve la pregunta, y al aceptar se intenta arrancar el backend y se reintenta la
  operación una vez

### Scenario: backend caído y el usuario declina

- **Then** la tool devuelve **exactamente el error que devolvería hoy**

### Scenario: el cliente no soporta preguntar

- **Given** un cliente que no declara `elicitation`
- **When** el backend está caído
- **Then** no se intenta preguntar y se falla igual de rápido que hoy

### Scenario: el cliente no contesta

- **Given** un cliente que declara `elicitation` pero no responde
- **When** se agota el plazo
- **Then** la tool continúa y devuelve el error de siempre, **sin quedarse colgada**

### Scenario: modelo que no está en el catálogo

- **Given** una tool llamada con `model="gpt-4"`, que no está en `ALLOWED_MODELS`
- **When** el cliente puede responder
- **Then** se ofrecen los modelos válidos y, elegido uno, la operación **continúa con él**
- **And** si el usuario no elige, se devuelve el error de texto de hoy con la lista

### Scenario: `output_format` en blanco

- **Given** `local_delegate` con `output_format="   "`
- **Then** se pregunta el formato y se usa el que responda el usuario

### Scenario: delegación con formato indicado

- **Given** `local_delegate` con `output_format` no vacío
- **Then** no se pregunta nada

### Scenario: el mecanismo se desactiva

- **Given** la variable de entorno que lo apaga
- **Then** ninguna tool pregunta nunca, y todo se comporta como antes de este change

## Edge cases and failure behavior

- **Cliente que declara la capability pero no tiene canal de vuelta** (`NoBackChannelError`): se
  trata como «no se puede preguntar», no como error.
- **Respuesta `cancel` vs `decline`**: ambas significan «no»; ninguna trae datos.
- **Respuesta que no valida contra el esquema**: se trata como «no».
- **Varias tools preguntando a la vez**: cada pregunta es de su petición; no hay estado global.
- **El arranque del backend falla tras aceptar**: se devuelve el error del arranque, no un silencio.

## Non-functional requirements

- **Sin coste cuando no aplica**: si el backend responde, no se pregunta ni se comprueba nada caro.
- **Sin dependencias nuevas.**
- **Compatibilidad**: ninguna tool cambia su schema (REQ-008); un cliente viejo ve exactamente lo
  mismo que hoy.
- **Privacidad**: las preguntas no incluyen rutas, contenido de ficheros ni credenciales.

## Non-goals

- Preguntar en el resto de las tools más allá de los dos casos acordados.
- Sustituir `LOCAL_DELEGATE_AUTOSTART` por la pregunta: la variable sigue mandando cuando está
  puesta.
- Elicitation en modo URL (`elicit_url`) ni formularios de varios pasos.
- Recordar la respuesta entre llamadas.

## Traceability

| Requisito | Trabajo previsto | Evidencia de verificación |
| --- | --- | --- |
| REQ-001 | pregunta en el camino del backend caído | test con cliente que acepta |
| REQ-002 | acepta → arranca y reintenta; no → error de hoy | tests de las tres respuestas |
| REQ-003 | oferta de los modelos válidos | test de modelo inválido + cliente que elige |
| REQ-003b | sin respuesta → error inmediato y sin backend | test que asevera que no se llamó al backend |
| REQ-004 | validación de `output_format` en blanco | tests con formato vacío y con formato |
| REQ-005 | guarda doble: capability **y** canal | tests de cliente sin soporte y sin canal |
| REQ-006 | plazo propio | test con cliente mudo, que hoy cuelga |
| REQ-007 | degradación ante excepción | test con `elicit` que lanza |
| REQ-008 | variable de entorno | test con el mecanismo apagado |
| REQ-009 | el contexto viaja por `ContextVar`, no por firma | test que compara el schema de las 11 tools |
