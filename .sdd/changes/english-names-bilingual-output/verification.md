# Verification: Renombrado a inglés de lo publicado y salidas en español e inglés

## Environment

- Revision: rama `release/0.35.0` desde `main` en `5723ac9` (A0–A6 + arreglo #263), versión
  subida a 0.35.0 con `scripts/bump_version.py`.
- Relevant runtime and tool versions: Python 3.11.15, uv 0.10.12, Windows 11. La pasada en vivo
  corrió con el daemon sobre el código de `main` en `2bca590` (se identificaba como 0.34.0).

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-017 | Suite completa en la rama de release; pasada en vivo de las 11 tools por MCP dentro de la ventana `w-20261013T123443Z` (0.35.0 candidata) | Suite: 2565 passed, 2 skipped. Tools: 11 de 11 responden; sin regresiones de idioma en lo que lee el usuario | `evidence/live-035/tools.md` |
| REQ-038 | `install`, `doctor`, `update`, panel (claro y oscuro), comando de P-4 y avisos de alias en vivo, dentro de la ventana de prueba `w-20261013T123443Z` (abierta 2026-10-13T12:34:43Z, cerrada 13:03:12Z con `local-delegate test-window stop`) | OK; ver observaciones del propio fichero | `evidence/live-035/install-doctor-panel.md`, `evidence/live-035/panel-*.png` |
| REQ-035 | Orden de mezcla en `main` (`git log --first-parent 8ec2f1d..main`) | A0 #247, A1 #249, A2 #250, A3 #251, A4 #252, A5a #253, A5b #259, A5c #261, (#248, ajeno al cambio), A6 #262, arreglo #263 | esta tabla |
| REQ-004 | `bump_version.py 0.35.0` cambió los 8 `UNRELEASED` de `deprecations.py` por `0.35.0`; `removal_version` deriva 0.38.0 en todos; `tests/test_deprecations.py` comprueba que `[0.35.0]` del CHANGELOG nombra cada `old` y `new` | OK | log de la suite de la rama de release |

Ventanas de prueba de este cambio: `w-20261013T123443Z` (0.35.0 candidata). La de la 0.36.0
candidata queda pendiente.

## Quality checks

Estado en la rama de release de la 0.35.0 (no cierra el gate `quality`, que espera a la 0.36.0):

- [x] Project-native tests pass (2565 passed, 2 skipped).
- [x] Lint, formatting, type checking, and build checks pass where applicable (`ruff check`,
  `ruff format --check`, `bump_version.py --check`).
- [ ] Secret scanning passes (lo da GitGuardian en el PR de release).
- [x] No unrelated changes are present.

## Deviations and residual risk

- `scripts/release.py 0.35.0 --dry-run` no pasa de la comprobación de rama en `release/0.35.0`
  (exige `main`): se ejecuta tras mezclar. La extracción de notas del CHANGELOG sí se comprobó
  (212 líneas).
- El plan pedía anunciar que «`doctor --json` cambia sus ids»; `doctor` no tiene `--json`. El
  CHANGELOG dice que cambian los ids y grupos de los checks, que solo se ven en `checks.CHECKS` y
  la wiki.
