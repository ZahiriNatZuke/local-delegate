# Handoff: Release 0.10.0, wiki y distribución

## Current state

- SDD status: listo para `complete`.
- Last completed gate: quality; conformance/memory listos para aprobación final.
- Current revision: release `3b8a11c` en main/tag; cierre documental post-release pendiente.

## What changed

- 0.10.0 publicada en PyPI, GitHub Release, MCP Registry y wiki nativa.
- Backend remoto autenticado Mac→PC, canary, benchmark/doctor y hooks medidos documentados.
- Tests aislados, telemetría de prueba limpia y sdist sin configuración local/SDD.

## Decisions

- Mantener 0.10.0 como beta y fijarla en Mac durante rollout.
- No promover 1.0.0, MoE ni backends nuevos hasta observación/canaries separados.
- Prompt+Bash adoptados; Read apagado por defecto.

## Next action

- Configurar los clientes MCP de la Mac con `local-delegate-mcp==0.10.0`, endpoint privado y key
  desde Keychain; ejecutar `local_status`, clasificación y resumen por path.

## Memory

- Canonical note: `projects/local-delegate/release-0.10.0-remote-backend.md`.
- Indexes updated: Claude global directo; Codex mediante update note ad-hoc permitido.
