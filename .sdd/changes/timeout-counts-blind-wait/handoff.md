# Handoff: La espera ciega sin turno cuenta en la explicación del plazo agotado (#575 + #579)

## Current state

- SDD status: closed (cerrado en el PR de la release 0.49.0, rama `chore/release-0.49.0-b`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `8509e7da` (PR #590, 2026-11-04T22:26:51Z)

## What changed

- La nota de un `read_timeout` («esperó N s…») cuenta también la espera sin turno: fases internas `turn_unusable` y `blind` en `QUEUE_PHASES`.
- El log sigue publicando solo las fases de `PHASES` (`turn`, `slot`, `backend`); las internas no salen al evento.
- Ajustes de la revisión: el test espera a que la segunda llamada esté en cola antes de dormir, conjunto literal en el assert del log, tests unitarios de cada fase sola y caso bajo 1 s.

## Decisions

- La nota puede pasar de `turn_wait_ms` con un daemon lento en fallar; se aceptó y se matizó en el CHANGELOG.
- La nota suma esperas de trozos anteriores, igual que en #575 (F7, aceptado).

## Next action

- Ninguna para este cambio. Falta una prueba en vivo con un plazo agotado de verdad, que no se hizo.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: índice de jornadas de `projects/local-delegate` (sesión principal)
