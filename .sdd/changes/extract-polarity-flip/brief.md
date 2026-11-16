# Brief: local_extract: aviso cuando un valor invierte la negacion de la fuente

## Problem

`local_extract` devolvió una instrucción con la polaridad invertida (#667): el documento pedía
revisar el código real del mod y los adaptadores y el campo salió como «Do not review code real of
the mod and adapters of both clients, do not infer response from the skills or hooks.». Entrada de
3219 caracteres, rol `mechanical` (gemma3-4b), una sola llamada (sin troceado).

## Desired outcome

Que quien llama sepa, sin tener que releer la fuente, que un valor dice lo contrario que el
contenido: un aviso en `_local_delegate`, en la línea de `cross_filled_keys` y `placeholder_keys`.

## In scope

- Averiguar la causa real: prompt, post-proceso, troceado o modelo.
- Un detector determinista que compare cada frase de cada valor con su frase de la fuente.
- Aviso es/en, CHANGELOG, `docs/wiki/Tools.md`, docstring.

## Out of scope

- Cambiar el prompt de `local_extract` (huella de afinidad, corpus congelados y fixtures de
  peticiones; un cambio de prompt ya rompió en vivo con tests en verde).
- Corregir el valor: el aviso nunca cambia lo que devolvió el modelo.
- Lo que cambia el PR #676 (diffs calculados por programa y reintento troceado por corte).

## Constraints and risks

- Falsos positivos: un aviso que salta sin motivo enseña a ignorarlo. Puerta: las 177 respuestas
  guardadas en `tests/data/cross_fill/` sin ningún aviso.
- Coste: el detector corre en cada llamada; tope de tamaño y presupuesto de comparaciones.
- No se puede probar contra el backend real desde un agente (401).

## Open questions

- Ninguna que cambie la especificación.

## Log

- L1 2026-11-16 Original request, verbatim:

  > Resolver #667 de `ZahiriNatZuke/local-delegate`: «`local_extract` puede invertir la polaridad
  > de una instrucción extraída» (por ejemplo, el fichero dice «no hagas X» y el campo extraído dice
  > «haz X»). [...] Un pendiente es una hipótesis: primero averigua la causa real (¿prompt?,
  > ¿post-proceso que recorta negaciones?, ¿troceado que parte la frase?, ¿solo el modelo?). Si la
  > causa es solo el modelo, busca una salvaguarda verificable por programa [...] Un control que
  > no puede dar un resultado distinto no es un control: los tests deben tener un caso que dispara
  > el aviso y otro que no.
- 2026-11-16 Causa confirmada: el modelo. Detector `polarity.py` y aviso `polarity_flipped_keys`.
