# Handoff: Release 0.10.0, wiki y distribución

## Current state

- SDD status: `verifying`.
- Last completed gate: `quality` aprobado.
- Current revision: release commit todavía pendiente sobre `af823bc`.

## What changed

- Bump coordinado a 0.10.0, changelog, README y wiki remota.
- Tests aislados del log real y sdist protegido contra `.codex/.sdd/.venv/dist`.
- Build, import de wheel y `server.json` validados.

## Decisions

- 0.10.0 sigue beta; 1.0.0 espera observación real.
- v238/b9925 siguen como backends estables.
- Prompt+Bash se adoptan; Read permanece apagado por defecto.

## Next action

- Crear el commit de release, fast-forward de `main`, esperar CI y solo entonces crear `v0.10.0`.

## Memory

- Canonical note: pendiente hasta confirmar URLs y estados públicos.
- Indexes updated: ninguno todavía.
