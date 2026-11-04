# Handoff: Un read_timeout dice si fue cola, carga o generación y en qué trozo (#572)

## Current state

- SDD status: closed (PR de cierre `chore/close-sdd-2026-11-04-tarde`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `fae612c7` (PR #575)

## What changed

- `concurrency.py`: la vigilancia de cada envío (`SendWatch`) anota si vio el modelo cargándose y a los cuántos segundos lo vio listo; `Trace.phase_ms` da la espera de turno y plaza.
- `server.py`: `_post_chat` lee esa vigilancia al vencer el plazo; con causa `busy` y carga vista, el texto dice que se cargó durante el envío y cuándo quedó listo; nombra la espera de turno de 1 s o más y, en operaciones troceadas, el «trozo X de N» o la reducción. Eventos nuevos: `read_timeout_load_ms`, `read_timeout_piece` y `pieces`.
- Catálogo i18n es+en, wiki (`Architecture`, `Savings-and-metrics`) y CHANGELOG.
- Ajustes de la revisión de resultado (F1–F7): modelo listo solo en la sonda del plazo, tests sin dependencia del reloj, texto de la espera acumulada, sin nota de carga con `model_swap`.

## Decisions

- No se sube el plazo (`HTTP_TIMEOUT` sigue en 180 s) ni cambian los valores de `read_timeout_cause`.
- El turno remoto (`_remote_wait`) no se nombra (F8) y el reagrupado no tiene test propio (F9): aceptados como límite.

## Next action

- Ninguna. Queda opcional una prueba en vivo con un plazo agotado de verdad.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: índice de jornadas de `projects/local-delegate` (sesión principal)
