# Handoff: el comando del hook se rompe en Windows y bloquea cada prompt

## Estado actual

- SDD status: `closed`
- Último gate completado: `memory`
- Revisión: mergeado con los PRs **#55** y **#57** el 2026-07-30, publicado en la **0.14.0**.
  Verificado de nuevo por ejecución el **2026-07-31**.

## Qué cambió

`hook_command` **cita siempre** la ruta del script y la escribe con `as_posix()`. Antes solo
citaba si la ruta tenía espacios —y una ruta de Windows normalmente no los tiene—, así que el
shell se comía cada `\` como escape y el intérprete recibía
`C:\\UsersYohan.claudehookslocal-delegatesuggest_delegate_prompt.py`. Como el hook es
`UserPromptSubmit`, eso **no degradaba: bloqueaba todos los prompts del usuario**.

De paso, `backend_probe()` distingue «no responde» de «responde 401/403».

## Decisiones que no se deducen del código

1. **Citar siempre en vez de decidir cuándo citar.** El bug no era que la condición estuviera mal
   afinada: era tener una condición. Se elimina.

2. **`as_posix()` y no barras invertidas escapadas.** Python abre rutas con `/` en Windows sin
   problema, y la forma citada con `/` funciona en `sh`, `cmd` y PowerShell, en los tres sistemas.
   El hook de otro producto que el usuario ya tenía registrado usaba exactamente esa forma y sí
   funcionaba.

3. **Un 401 no es un servicio caído.** Mandar a arrancar un llama-swap que ya corre es peor que no
   decir nada.

## La ironía, que vale más que el fix

El PR #55 corrigió la afirmación «el formato con `args` no se ejecuta». Este bug la remata desde
el otro lado: **el formato heredado era el que funcionaba** (exec form, sin shell) y el «moderno»
con string de shell era el que estaba roto en Windows. Dos veces seguidas, el repo afirmó lo
contrario de la realidad sobre el mismo tema. De ahí la regla que ya es del proyecto: **un
comentario del repo no es evidencia; verifica por ejecución**.

## Deuda de traza, ya saldada

El `state.json` de este cambio **se escribió a mano**, con `mode: "lightweight"` —un valor que no
existe en el esquema— y solo uno de los cinco gates. `personal-harness` lo rechazaba entero, así
que el cambio era invisible para las herramientas. Se reparó el 2026-07-31: modo corregido, los
cuatro gates que faltaban añadidos **en `pending`** y la máquina recorrida con el harness. No se
aprobó ningún gate a mano.

## Siguiente acción

Ninguna. El pendiente que dejó el brief —volver a registrar los hooks del usuario— está verificado
como hecho: los dos aparecen citados y correctos en el `settings.json` real, y corren.

## Memoria

- Nota canónica: `projects/local-delegate/incidente-hooks-windows-2026-07-30.md`.
- Índices actualizados: la memoria de proyecto de Claude Code ya apunta a esa nota, con la regla
  **«no publicar sin probar `install` end-to-end en Windows»**.
- Sin secretos ni datos personales: las rutas citadas son del HOME de la máquina de desarrollo y
  ya aparecen en el brief original.
