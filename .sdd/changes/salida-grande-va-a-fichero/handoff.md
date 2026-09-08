# Handoff: La salida grande va a fichero, no al contexto

## Current state

- **SDD status:** `plan-review`, listo para pasar a `implementing`.
- **Last completed gate:** `plan` (aprobado). `spec` también aprobado, y **reaprobado** tras
  cambiar materialmente en la ronda 1 de revisión.
- **Current revision:** plan revisión 2; spec con 26 requisitos.

## What changed

Ninguna línea de código todavía. Lo que existe son los cuatro artefactos:

- `research.md` — 21 días de uso real medidos, mapa de 17 superficies, estado del arte con
  números, y **seis verificaciones contra el binario real** (2.1.263).
- `brief.md` — el problema, las dos decisiones del usuario y lo que queda abierto.
- `spec.md` — 26 requisitos, 7 escenarios, trazabilidad completa, gate cuantitativo.
- `plan.md` — 11 tareas con propiedad exclusiva de ficheros, dos puntos de control tempranos.

Tres rondas de revisión adversarial: **block → revise → 3 bloqueantes**. 14 hallazgos, todos
verificados contra el código antes de aceptarlos.

## Decisions

Lo que una sesión futura no puede derivar del código:

- **Se reescribe el comando** (`updatedInput`), no se avisa. Es lo único que no depende de
  obediencia: tres mediciones seguidas dan cero delegaciones, la última con 411 avisos.
- **El hook queda apagado por defecto.** Hoy el de 0,3 % de puntería es el único encendido en
  toda instalación, mientras el bueno es opt-in. Se invierte.
- **Subshell, no llaves** (REQ-002b). Medido a través de la tool: con `{ }`, un `exit` del comando
  del usuario mata el script y el extracto no se produce.
- **El prefijo `cd` va fuera del subshell.** El cwd persiste entre llamadas y las variables no;
  23 de los 42 casos del corpus empiezan por `cd`.
- **Los lectores de ficheros no se reescriben nunca** (REQ-007), aunque escupan. Se renuncia a
  propósito a 17 de los 42 casos (~58 K tokens): son código que hay que leer literal.
- **La lista de comandos no puede ser el único instrumento.** Medido: ningún ejecutable supera el
  umbral en más del 9 % de sus ejecuciones, y este corpus no contiene el perfil donde una lista
  funcionaría. De ahí la capa de aprendizaje.
- **El bug del map-reduce entra al alcance** (T10) a petición del usuario, con frontera escrita:
  reconocer el desborde, **no** rediseñar el troceado.

## Next action

Transicionar a `implementing` y **empezar por T10 o por T1+T2**, que son independientes entre sí.

T10 es la más barata y cierra un bug ya diagnosticado: `_es_desborde_de_contexto`
(`src/local_delegate/server.py:1027`) compara contra tres literales y el mensaje real de este
backend —`Context size has been exceeded`— no casa con ninguno, así que el reintento adaptativo
del map-reduce está anulado. El test de regresión **debe fallar contra el código de hoy**.

Prerrequisito para verificar T10 de extremo a extremo: la clave del backend la tiene el daemon,
no el shell — instrumentar desde un proceso propio da 401.
