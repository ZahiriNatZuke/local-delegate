# Handoff: Panel: los fallos no suman ahorro, los estados dicen la causa real y la presentación es coherente

## Current state

- SDD status: cerrado. Mezclado en `main` por el PR #231 (`4d56a9f`), sin versión publicada.
- Gates: spec, plan, quality, conformance y memory aprobados.

## What changed

- Contabilidad: los fallos no ahorran; el KPI es el contexto conservado neto; desglose por evento en
  caracteres (imagen en bytes) y conversión única `tokens_claude`/`tokensClaude`.
- `fallos.py`: clasificador de 12 reglas de la causa de un fallo de conexión, usado por el panel,
  `local_status`, `doctor` y las delegaciones. Con backend remoto nadie ofrece arrancar llama-swap.
- Sondeo con histéresis de dos fallos, lista de modelos estable, estados cargando y en cola local
  (`espera_local`), plazo de conexión de 10 s.
- Presentación: miles agrupados, coma decimal, latencia en segundos y tipografía por rol.
- `sondas.py` rompe el ciclo de imports entre `doctor` y `checks` (lo marcaba CodeQL).

## Durable decisions

- Recorded in the vault: `projects/local-delegate/jornada-2026-10-06-el-ahorro-que-se-contaba-a-medias.md`.
- El contrato de unidades con `coste-api-y-cuota` está en `spec.md`, «Contrato con coste-api-y-cuota».

## Next steps

- Ninguno propio. La conversión a tokens la sustituyó `coste-api-y-cuota` (#232).
