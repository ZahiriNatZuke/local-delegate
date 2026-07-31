# Revisión adversarial del plan

Hecha contra `plan.md` y `spec.md`, buscando por dónde rompe. **Cuatro hallazgos, tres
bloqueantes.** El plan se corrige antes de aprobar el gate.

## B-1 (bloqueante) — `snapshot()` puede reventar `/api/status` en caliente

El plan reconoce que `/api/status` es un endpoint **síncrono** de FastAPI y por tanto lee el estado
desde el threadpool de uvicorn, en otro hilo. Pero luego solo dice «hay lock» y describe
`snapshot()` como «lo que consume `/api/status`», sin exigir nada más.

**Cómo falla:** si `snapshot()` devuelve el diccionario interno (o una copia superficial de sus
valores mutables), el serializador JSON lo recorre **fuera** del lock mientras el middleware puede
estar actualizando `last_seen` o insertando una identidad nueva. Resultado:
`RuntimeError: dictionary changed size during iteration`, o peor, un `/api/status` que a veces
funciona. Un fallo intermitente en el endpoint que alimenta el panel.

**Corrección exigida:** `snapshot()` construye y devuelve una estructura **nueva y desligada**,
enteramente **dentro** del lock. Ningún objeto mutable compartido cruza la frontera.

## B-2 (bloqueante) — la sección crítica está sin delimitar, y es justo donde vive el bug

«Hay lock de verdad» no dice **qué** cubre. El orden natural al escribir el código —comprobar si la
identidad ya está, escribir la línea, añadirla al dict— produce exactamente el defecto que REQ-003
prohíbe si el lock solo envuelve el `dict`:

```
corrutina A: ¿está? no  ->  escribe línea  ->  añade
corrutina B: ¿está? no  ->  escribe línea  ->  añade     # dos líneas para la misma identidad
```

**Corrección exigida:** el lock cubre **comprobar + escribir + añadir** como una sola operación.
Y hay que dejar escrito lo que eso implica: se hace una escritura a disco con el lock tomado, lo que
bloquea brevemente el event loop. Es aceptable **porque ocurre una vez por identidad**, no por
mensaje — pero es una decisión, no un descuido, y va comentada en el código.

## B-3 (bloqueante) — el test de «no se puede escribir» es frágil en Windows

El plan pide un test con «`LOG_DIR` apuntando a una ruta no escribible». La vía obvia son los
permisos, y **en Windows `chmod` no los aplica como en POSIX**: el test pasaría en el runner de
Ubuntu y sería inútil o intermitente en el de Windows. Sería el mismo error que ya costó una vez
con `Path.home()` — probar el mecanismo en el sistema equivocado.

**Corrección exigida:** no probar los permisos del sistema de ficheros. Probar el **contrato**:
doblar la función de escritura para que lance y aseverar que la llamada a la tool responde igual.
Eso mide lo que REQ-005 pide de verdad —que el fallo de registro no llegue al cliente— y mide lo
mismo en los tres sistemas operativos.

## O-4 (no bloqueante, pero hay que decidirlo ahora) — la identidad vacía

REQ-006 cubre «capabilities sin `client_info`». El plan no dice nada del caso simétrico: un mensaje
en el que **no hay ni capabilities ni `client_info`** (posible en el camino del handshake antes de
que el commit se propague, o con un cliente que solo mande `initialize`).

Tal como está descrito, eso registraría una identidad `(None, None, protocolo, ())` — una línea de
ruido que no informa de nada y que además contaminaría el resultado del experimento con `elicitation`.

**Decisión:** si no hay capabilities **ni** `client_info`, no se registra. Se añade como escenario
a la spec para que quede verificable, no solo como nota del plan.

## Lo que sí está bien y conviene no tocar

- Saltarse `initialize` está **medido**, no supuesto, y el research deja la tabla.
- El dedupe por identidad en vez de por conexión evita atarse a `session._connection`, que es
  privado del SDK. La consecuencia (dos instancias idénticas cuentan como una) está escrita en la
  spec, no escondida.
- Leer `config.LOG_DIR` en tiempo de llamada, y no como default de módulo, es correcto y es
  exactamente el gotcha que este repo ya pagó.
- El test de «conjunto exacto de claves» (no «al menos») es el que impide que un campo colado por
  descuido pase silencioso.
