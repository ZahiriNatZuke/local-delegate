# Handoff: Las pruebas fuera de las métricas: ventanas de prueba y una sola regla de exclusión en todo el panel

## Current state

Fase `specifying`. `research.md`, `spec.md` (REQ-001 a REQ-026) y `plan.md` (T0 a T10) escritos y
pasados por una revisión adversaria (APROBADO CON CAMBIOS, correcciones aplicadas). Gates `spec` y
`plan` pendientes.

## What changed

Solo artefactos SDD en `.sdd/changes/test-windows-out-of-metrics/`. Ningún cambio en `src/` ni
`tests/`.

## Decisions

Abiertas para el usuario: D1 a D7 en `spec.md`, «Decisiones abiertas», cada una con recomendación.

## Next action

1. El usuario responde D1-D7 y aprueba spec y plan (`personal-harness sdd approve … spec|plan`).
2. T0: esperar a que el cambio del otro agente en `web/metrics.py` esté en `main` antes de T4/T5.

## Memory

Hallazgo para persistir al cerrar: `scripts/medir_enfriamiento.py` revienta siempre en `main()`
(`args.exclude`, introducido en #240); lo arregla T7. Afecta a la medición de P-4 de 30 días
(2026-10-15).
