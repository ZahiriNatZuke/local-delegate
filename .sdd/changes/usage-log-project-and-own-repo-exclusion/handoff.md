# Handoff: Log de uso con proyecto (hash y tipo) y mediciones que apartan el propio repo

## Current state

- SDD status: `implementing`; la sesión coordinadora pasa a `verifying` y aprueba `quality`,
  `conformance` y `memory` con la CLI.
- Last completed gate: `plan`.
- Current revision: PR #637 mezclado en `main` (`a19817e6`), dentro de la release 0.51.0 (PR #653).

## What changed

- T1 a T11 hechas: cada fila del log de uso, cada evento de los hooks y la línea del mod llevan
  `project` (hash con sal de 16 hex) y `project_kind` (`self`/`other`); el relleno lo recupera en
  filas viejas con cruce o con clave de sesión; el panel, `local_status` y los dos scripts de
  medición apartan el propio repo por defecto (`include_self=1` / `--include-self` lo devuelven).
- Prueba en vivo (REQ-026) pasada el 2026-11-10 (`verification.md`, «Prueba en vivo (REQ-026),
  resultado»); revisión de resultado en `review.md`.

## Decisions

- Las de la spec (D1 a D14). El mutante 14 es equivalente por diseño.
- El corte de 90 días de la medición de adopción (2026-12-14) se lee con `--include-self` para
  compararlo con los de 14 y 30 días.

## Next action

- Borrar las copias de la instantánea de T1 (`t1/`, `t11/`) del directorio temporal de la sesión,
  último paso de T11; después, puertas y estado `closed`.

## Memory

- Canonical note: por escribir (jornada del 2026-11-10 en `projects/local-delegate/` del vault).
- Indexes updated: los que toque la sesión coordinadora al cerrar.
