# Implementation plan: El hook de Read deja de sugerir y pasa a decidir: aviso en el momento, bloqueo con flag, y umbral del entorno

## Approach

No se implementó aquí: superado por el bloqueo de lectura de la 0.28.0 (F1 de `delegacion-precisa-y-fiable`) y por el mod de lectura de la 0.41.0 (`claude-plugin-and-mods`).

## Ordered tasks

- [x] T1 — Cubierto por el bloqueo de lectura de la 0.28.0 y el mod de lectura de la 0.41.0 (REQ-001)
  - Files or modules: `resources/hooks/suggest_delegate_read.py`, mod `read` del plugin
  - Verification: fila REQ-001 de `verification.md`
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

