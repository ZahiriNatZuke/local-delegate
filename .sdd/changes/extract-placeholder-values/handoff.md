# Handoff: local_extract: marcadores de sin dato a null y cuentas de listas vacías

## Current state

- SDD status: closed (cerrado en el PR de la release 0.49.0, rama `chore/release-0.49.0-b`)
- Last completed gate: memory
- Current revision: mezclado en `main` como `c5f8333c` (PR #591, 2026-11-04T22:58:25Z)

## What changed

- `local_extract` convierte a `null` un valor de primer nivel que es un marcador de «sin dato» (`N/A`, `unknown`, `desconocido`, `no consta`, `-`, `?`, cadena vacía, `"null"`, `"undefined"`): la clave entra en `missing_keys` y su texto original queda en `_local_delegate.placeholder_keys`, con aviso.
- Si la entrada es un objeto JSON y se pide la cuenta de una lista de primer nivel, el programa la cuenta cuando el modelo no dio nada o dio una cifra mayor; la del modelo queda en `_local_delegate.recounted_keys`, con aviso.
- El relleno desde parciales al trocear salta un marcador.
- Ajustes de las dos revisiones: guardas del recuento para totales legítimos, `--` y `...` fuera de los marcadores, prefijo `N| ` quitado antes de buscar el marcador, CodeQL en dos tests.

## Decisions

- El refuerzo del prompt (REQ-005) queda fuera de la 0.49.0 por decisión del usuario: rompía la red del corpus congelado y exigía cambiar tests existentes. El PR va con `Refs #586` y el issue sigue abierto solo con esa parte.
- Un valor que solo contiene un marcador dentro de un texto más largo no se toca: el criterio es el valor entero.

## Next action

- Ninguna para este cambio. El refuerzo del prompt se hará en un cambio aparte sobre el issue #586, con su frontera de corpus.

## Memory

- Canonical note: vault `projects/local-delegate/jornada-2026-11-04-seis-arreglos-y-el-vigilante-de-precios.md`
- Indexes updated: índice de jornadas de `projects/local-delegate` (sesión principal)
