# Handoff: El cancelled del CI en main tiene causa conocida y firma reconocible

## Current state

- Estado SDD: `verifying` → cierra con el CI del PR.
- Último gate aprobado: `quality`.
- Base `9c6cb47`; rama `fix/cancelled-ci-main`.

## What changed

- `.github/workflows/ci.yml`: comentario corregido con la firma medida; el paso `Tests (pytest)`
  recibe `timeout-minutes: 5`.
- `scripts/ci_gate.py`: docstring corregido.
- `docs/wiki/Repo-hardening.md`: sección reescrita, con tabla para clasificar un `cancelled`.
- `tests/test_ci_gate.py`: dos tests que atan los números al texto.
- `CHANGELOG.md`.

## Decisions

- **El pendiente pedía elegir remedio; medir disolvió la pregunta.** `timeout-minutes` ya actuaba.
  Lo que faltaba era saberlo y poder reconocer su firma.
- **13 = 8 + 5**, y la evidencia es que los tres runs murieron a los 13:00 exactos con **estados
  internos distintos**. Un solo run no habría bastado; tres con estados distintos sí.
- **La corrección se escribe como corrección**, diciendo qué se creía y por qué era falso. Es la
  segunda vez que este cuelgue se diagnostica mal; borrar el rastro invita a una tercera.
- **El límite del paso sale de la medición**, no de la completitud: en dos de tres, quien corría
  era pytest. Y tiene que ser **menor** que el del job o no llegaría a actuar nunca.
- **No se investiga la causa del cuelgue de pytest**: no hay log (`BlobNotFound`), y una causa sin
  evidencia es justo lo que este repo persigue.

## Next action

Merge. Después, el punto 7 del backlog (telemetría de hooks al dashboard).

## Memory

- Nota canónica: `projects/local-delegate/backlog.md` (borrar el punto al cerrar).
- Índices actualizados: al cierre de la sesión.
