# Implementation plan: Cadena de respaldo entre modelos locales y enfriamiento temporal por modelo

## Approach

Este SDD no se implementó por separado: `delegacion-precisa-y-fiable` lo absorbió el 2026-09-12 y sus 20 requisitos son la fase F3 de aquel (tareas 22 a 31). El diseño y el plan reales están en `.sdd/changes/delegacion-precisa-y-fiable/plan.md`.

## Ordered tasks

- [x] T1 — Implementado como F3 de `delegacion-precisa-y-fiable` (tareas 22-31, PR #187-#199, publicado en la 0.28.0) (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009, REQ-010, REQ-011, REQ-012, REQ-013, REQ-014, REQ-015, REQ-016, REQ-017, REQ-018, REQ-019, REQ-020)
  - Files or modules: `failures.py`, `cooldown.py`, `chains.py`, `server.py` (`_run_chat`)
  - Verification: tests de `verification.md`; criterio P-4 en el SDD que lo absorbió
  - Depends on: none

## Test strategy

- Unit:
- Integration:
- End-to-end or manual:
- Security and secret scanning:

## Migration and compatibility

- Describe compatibility boundaries, data migration, and rollout considerations.

## Plan review

- [ ] Every requirement maps to at least one task and verification step.
- [ ] Risky or destructive operations have safeguards and rollback.
- [ ] Dependencies and configuration changes are explicit.
- [ ] The plan does not include unrelated work.

