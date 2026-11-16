# Handoff: local_extract: aviso cuando un valor invierte la negacion de la fuente

## Current state

- SDD status: verifying
- Last completed gate: plan
- Current revision: rama `fix/extract-polarity-flip`

## What changed

- Detector nuevo `src/local_delegate/polarity.py` y aviso `_local_delegate.polarity_flipped_keys`
  en `local_extract`, con i18n es/en, CHANGELOG, wiki y docstring.

## Decisions

- La causa del #667 es el modelo: el programa devuelve el valor palabra por palabra y la entrada
  del issue no se trocea. Por eso el arreglo es un aviso, no un cambio de valor.
- El prompt no cambia: movería la huella de afinidad, los corpus congelados y las fixtures de
  peticiones, y no se puede probar en vivo desde un agente.

## Next action

- Esperar el CI del PR en verde, aprobar `quality` y `conformance` y cerrar el SDD.

## Memory

- Canonical note: ninguna por ahora; lo durable está en este SDD.
- Indexes updated: no
