# Verification: Cadena de respaldo entre modelos locales y enfriamiento temporal por modelo

## Environment

- Revision: `0253b630` (`main`, 2026-11-23)
- Relevant runtime and tool versions: Python del `uv.lock`; `uv run --locked pytest`

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_failures.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-002 | `test_fallback.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-003 | `test_chains.py, test_fallback.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-004 | `test_chains.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-005 | `test_fallback.py, test_cooldown.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-006 | `test_fallback.py, test_cooldown.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-007 | `test_fallback.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-008 | `test_fallback.py, test_chains.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-009 | `test_cooldown.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-010 | `test_cooldown.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-011 | `test_cooldown.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-012 | `test_cooldown.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-013 | `test_fallback_observability.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-014 | `test_chains.py, test_cooldown.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-015 | `test_failures_integration.py, test_fallback.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-016 | `test_failures.py, test_failures_integration.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-017 | `test_fallback.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-018 | `test_fallback.py, test_failures_integration.py, test_failure_captures.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-019 | `test_fallback.py, test_chains.py, test_fallback_observability.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |
| REQ-020 | `test_failure_captures.py, test_failures.py, test_chains.py` | pass | pytest de los ficheros citados en `0253b630` (996 passed, 2026-11-23); implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, 0.28.0) |

## Quality checks

- [x] Project-native tests pass (los ficheros citados, 996 passed; la suite entera corre en el CI de cada PR).
- [x] Lint, formatting, type checking, and build checks pass where applicable (CI de los PR #187-#199).
- [x] Secret scanning passes (CI de los PR).
- [x] No unrelated changes are present.

## Deviations and residual risk

- Cierre administrativo de un SDD absorbido: la verificación original está en `.sdd/changes/delegacion-precisa-y-fiable/verification.md`, secciones F3. Aquí se repiten los tests en la revisión de cierre.
- Los valores por defecto del enfriamiento (N = 3, 120 s, tope 900 s) siguen sin medir: el criterio P-4 se cierra con el corte de 90 días del 2026-12-14 en el SDD que lo absorbió.

