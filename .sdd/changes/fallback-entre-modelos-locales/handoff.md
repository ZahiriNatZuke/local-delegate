# Handoff: cadena de respaldo entre modelos locales y enfriamiento por modelo

**Estado al 2026-09-11:** fase `specifying`, gate `spec` **sin aprobar**, cero código escrito.
`brief.md`, `research.md` y `spec.md` están completos (20 requisitos, 16 escenarios).

## Por qué se para aquí

Decisión del usuario: **unificar este cambio con la investigación de modelos nuevos** que lleva otra
sesión (nota del vault `projects/llms/investigacion-modelos-abiertos-2026-09.md`), en **una sola
especificación SDD**, y decidir allí el orden de implementación. Este directorio queda como fuente de
la parte de fiabilidad; no se aprueba su gate por separado.

## Qué hay que llevarse

1. **La spec entera** (respaldo entre modelos + enfriamiento), ya alineada con la otra sesión: cadenas
   por rol y no por nombre de modelo, clase «capacidad o carga» separada por la política
   «Prefer No Sysmem Fallback», clase «configuración» para el razonamiento que agota `max_tokens`,
   y patrones sacados de respuestas reales con la versión anotada (REQ-018 a REQ-020).
2. **Las cuatro decisiones del usuario** (D-1 a D-4 en `spec.md`): encendido por defecto, los timeouts
   enfrían pero no saltan, cadenas de hasta 2 saltos, y el rol de código con respaldo al residente.
3. **El mapa de impacto del código** en `research.md`, con fichero:línea. Sirve igual para cualquier
   cambio que toque `_run_chat`, la clasificación de errores o el estado compartido.
4. **Dos defectos vivos que encontró la investigación**, independientes de este cambio:
   - `server.py:605` lanza `AttributeError` con `content: null`, sin capturar.
   - Un `ConnectTimeout` cae en `http_error`: no dispara autoarranque ni la pregunta.
   - Además, `retry_exhausted` (`server.py:659-663`) es inalcanzable.

## Lo que el usuario dijo que le importa de verdad

La prioridad no es la fiabilidad, es la **precisión de la delegación**: que las tareas mecánicas
acaben en los modelos locales en vez de gastar contexto y cuota del modelo principal. De OmniRoute
salen cuatro ideas para eso, que deben entrar en la spec unificada:

1. **Decidir fuera del criterio del agente:** interceptar y decidir por reglas, no sugerir. Enlaza
   con el cambio abierto `read-obliga-a-delegar`, cuya medición ya demostró que buena parte del
   «no delegas» era «no se pidió»: el hook no se disparó ni una vez (umbral 32 KB, ficheros de 9,5 y
   14,2 KB), y de 96 lecturas calló por tamaño 24, todas documentación.
2. **Comprimir por el camino:** recortar o resumir la salida de una herramienta antes de que entre en
   el contexto, sin depender del juicio del agente.
3. **Clasificador barato que enruta:** una tool que reciba el paso y responda a qué tool local va, o si
   no se delega.
4. **Trazabilidad:** medir delegaciones ofrecidas, aceptadas y rechazadas, y por qué; hoy el panel solo
   ve las que ocurrieron.

## Pendiente que no se hizo

- Revisión independiente de esta spec buscando huecos (el usuario la prefería antes del gate).

## ABSORBIDO (2026-09-11)

Este cambio queda absorbido por `.sdd/changes/delegacion-precisa-y-fiable/` como su fase **F3**, por
decision del usuario. Sus 20 requisitos se heredan sin reescribir y conservan sus identificadores.
**No se aprueba su gate por separado.** Sigue listado en `specifying` porque el harness no permite
cerrar un cambio desde esa fase; se cerrara cuando F3 termine.
