# Handoff: Turno remoto inalcanzable: en serie, corte y aviso (#577)

## Current state

- SDD status: closed (PR de cierre `chore/close-sdd-2026-11-04-tarde`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `576344b5` (PR #579)

## What changed

- `remote_turn.py`: sitio «a ciegas» por URL de turno (`hold_blind`/`release_blind`): sin turno remoto (`unreachable`) las operaciones van de una en una en el proceso, en orden de llegada y cancelables; una espera de turno sale si otra ya declaró el daemon inalcanzable.
- `cooldown.remote_turn_cut()` (`remote-turn-cut.json`, compartido entre procesos): un intento sin turno que acaba en `read_timeout` abre el corte 120 s (dobla hasta 600 s); con el corte abierto las llamadas sin turno fallan al momento con `RemoteTurnDown`. Lo cierra un intento sin turno que sale bien o un turno concedido.
- El error de un intento sin turno lleva la nota «sin turno remoto»; el evento de una llamada cortada lleva `error: "remote_turn_unreachable"`.
- Ajustes de la revisión independiente (`58afc614`): solo `read_timeout` abre el corte; fila por llegada que se suelta entre trozos y `QueueSaturated` sin avance; una espera con `429` no se corta por otra; la serie es por proceso en la documentación.

## Decisions

- Seguir sin turno en serie y no fallar siempre rápido: el daemon parado con el backend sano es un caso real (#512).
- Serializar entre procesos queda fuera; el corte sí es compartido por fichero.

## Next action

- Arreglar las alertas de CodeQL 202 y 203 (`py/catch-base-exception` en `tests/test_remote_turn_unreachable.py:198` y `:473`, abiertas en `main`) y resolver sus dos hilos del PR #579.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: índice de jornadas de `projects/local-delegate` (sesión principal)
