# Handoff

## Current state

- SDD status: verifying (quality y conformance aprobadas; memory y cierre tras mezclar)
- Last completed gate: conformance
- Current revision: rama `fix/recompute-cost-sin-perdida`

## What changed

- recompute-cost funde contra una lectura estricta (json_state.read_before_merge), con reintentos, copia de los danados y cerrojo de corrida.

## Decisions

- Copiar (no mover) el fichero danado; el viejo nunca se copia; los lectores del panel siguen tolerantes.

## Next action

- Mezclar el PR, cerrar el SDD (puerta memory + `closed`) y mover la tarjeta a «Hecho».

## Memory

- Canonical note: la jornada del 2026-11-09 la recoge el orquestador
- Indexes updated: no
