# Brief: que el aviso de lectura llegue, y decidir con datos si además debe obligar

> **Si retomas esto en unos días, lee primero `research.md`** — sobre todo la tabla «Criterio de
> decisión», escrita **antes** de ver el resultado a propósito.

## Problem

El usuario lo planteó así: *«el sistema funciona hasta que llega a ti, que te saltas la
sugerencia»*. Es una observación repetida y legítima: hay tres mediciones de adopción con cero
delegaciones.

**Pero la causa que se le atribuía era falsa, y medirlo es lo que abrió este cambio.** El hook
`PreToolUse/Read` está encendido y aun así **no se disparó ni una vez** en la sesión que motivó la
pregunta: su umbral bajo eran **32 KB** y los ficheros pesaban **9,5 y 14,2 KB**. Los avisos que se
veían venían del hook de `UserPromptSubmit`, que dispara por el texto del prompt. No hubo
desobediencia porque no hubo orden.

Cuantificado sobre 96 lecturas: el hook callaba por tamaño **24 veces, y las 24 eran `.md`, `.json`
o `.txt`**, 17 de ellas entre 8 y 16 KB.

## Desired outcome

Dos cosas, **en este orden**, que fue decisión explícita del usuario:

1. **Ahora:** que el aviso llegue en la franja donde vive la documentación. Umbral bajo de 32 → 8 KB.
   Observable: leer un `.md` de 10–20 KB produce `Sugerencia`; uno de 5 KB sigue sin decir nada.
2. **Dentro de un par de días, con la medición delante:** decidir si además hace falta **bloquear**
   la lectura (deny en `PreToolUse`) con un flag para desactivarlo, activo por defecto.

## In scope

- Umbral bajo a 8 KB en los **cuatro** sitios donde vive el número.
- Un test que ate esas fuentes: no se pueden unificar (el hook es stdlib pura y no puede importar
  `config`), solo atar.
- El criterio de decisión de la fase 2, escrito antes de ver los datos.

## Out of scope

- **El bloqueo, por ahora.** No porque no se quiera: porque **no está medido** que el asistente
  desobedezca un aviso que llega. Construirlo hoy sería pagar su coste sin saber si hace falta.
- La banda `strong` (100 KB). Se cambia **una** cosa para que la próxima medición sea
  interpretable.
- El hook de `UserPromptSubmit`, que es otro mecanismo y ya tiene sus tres mediciones.

## Constraints and risks

- **El riesgo real es repetir la historia de este hook.** Ya avisó en 572 de 852 lecturas con un
  acierto del 5 %, y eso enseñó a ignorarlo. Bajar el umbral aumenta los disparos: si la puntería
  cae, el remedio es peor. Mitigado en parte porque las guardas de `codigo` y `acotada` siguen
  intactas y las 24 lecturas afectadas son **todas** documentación — pero **la puntería nueva no
  está medida**, y ese es justo el dato que traen estos días.
- El hook del HOME es una **copia**: hasta que no se reinstala, el cambio no corre. Y `install` en
  esta máquina necesita los **cuatro** flags (`--mcp-mode http --web-token-env --enable-read-hook
  --agents`), o borra la cabecera `Authorization`.

## Open questions

1. **¿Obedece el asistente el aviso cuando llega?** Es la pregunta que decide la fase 2 y hoy no
   tiene respuesta.
2. Si resulta que sí obedece, ¿el umbral correcto es 8 KB o aún más bajo? La franja 4–8 KB tuvo 4
   lecturas en tres semanas: probablemente no compensa.
