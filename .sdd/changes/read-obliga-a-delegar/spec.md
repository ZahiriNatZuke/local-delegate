# Specification: El hook de Read deja de sugerir y pasa a decidir: aviso en el momento, bloqueo con flag, y umbral del entorno

## Summary

La lectura que toca delegar deja de depender del criterio del agente: el hook de `Read` avisa en el momento, puede bloquear con un interruptor y su umbral sale del entorno. Este SDD no llegó a especificarse aquí: lo absorbió `delegacion-precisa-y-fiable` (fase F1) y luego lo superó el mod de lectura de `claude-plugin-and-mods`.

## Requirements

- **REQ-001** — Una lectura de documentación que toca delegar recibe el aviso o el bloqueo en el momento de leer, sin depender de que el agente lo decida.
  - Request: derived: brief.md, «Desired outcome»
  - Verify: review cubierto por el bloqueo de lectura de la 0.28.0 (`tests/test_f1_conformance.py`, `tests/test_read_switch.py`, F1 de `delegacion-precisa-y-fiable`) y por el mod de lectura de la 0.41.0 (`read.test.ts`, `tests/test_hook_step_aside.py`)

## Acceptance scenarios

### Scenario: expected path

- **Given** a defined initial state
- **When** an actor performs the relevant action
- **Then** the observable result satisfies the requirement

## Edge cases and failure behavior

- Define validation, error, retry, concurrency, and recovery behavior where relevant.

## Non-functional requirements

- Security, privacy, accessibility, performance, compatibility, and operability expectations.

## Non-goals

- Explicitly exclude plausible adjacent work.

## Traceability

Map every requirement to planned work and later to verification evidence.

