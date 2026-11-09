# Handoff

## Current state

- SDD status: verifying (quality y conformance aprobadas; memory y cierre tras mezclar)
- Last completed gate: conformance
- Current revision: rama `fix/telemetria-escritura-concurrente`

## What changed

- hook_common.append_line: cerrojo (msvcrt byte 2**62 / flock), una sola escritura, reparacion del salto final, dedupe atomica en el camino del mod; record_block y _log_failure encima; lectores apartan no-objetos.

## Decisions

- Byte de cerrojo lejos de los datos (cerrojo obligatorio en Windows); espera acotada 1 s y escribir igual; 0o600; mod/read.js fuera de alcance.

## Next action

- Mezclar el PR, cerrar el SDD (puerta memory + `closed`) y mover la tarjeta a «Hecho».

## Memory

- Canonical note: la jornada del 2026-11-09 la recoge el orquestador
- Indexes updated: no
