# Handoff: local_summarize: aviso cuando el resumen niega una categoria que el runner de tests conto

## Current state

- SDD status: verifying
- Last completed gate: plan
- Current revision: rama `fix/summarize-test-totals-negation`

## What changed

- `runner_totals.py` nuevo (lector de totales de pytest/jest/cargo/go y detector de negaciones);
  `_test_totals_notice` en `server.py` envuelve el postproceso de `local_summarize`; aviso es/en.

## Decisions

- Solo aviso, sin reescribir el resumen ni tocar el prompt (como #630).
- La negación cuenta hacia atrás, en la misma frase, hasta seis palabras, y se corta con una cifra,
  un signo o «y/and/pero/but».

## Next action

- Prueba en vivo en la sesión principal con el caso del issue; luego revisión y puertas
  `quality`, `conformance` y `memory` con el CI del PR conjunto.
