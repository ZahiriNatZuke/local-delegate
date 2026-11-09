# Handoff: La medicion de adopcion del plugin acota las exclusiones a su periodo

## Current state

- SDD status: verifying (puertas quality y conformance aprobadas; memory y cierre los hace el orquestador tras mezclar)
- Last completed gate: conformance
- Current revision: rama `fix/adopcion-exclusiones-por-periodo`

## What changed

- `measure()` saca `excluded_rows` de una segunda pasada acotada a `[since, until)`; los ids siguen sin final.

## Decisions

- Segunda llamada a `model_decided_ids` en vez de cambiar su contrato: la función queda igual y las filas ya están en memoria.

## Next action

- Mezclar el PR y cerrar el SDD (puerta memory + `closed`).

## Memory

- Canonical note: ninguna nueva (cambio pequeño; la jornada del día la recoge el orquestador)
- Indexes updated: no
