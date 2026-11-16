# Handoff: Codex: resumen automático de lecturas y guard de escritura (#670)

## Current state

- SDD status: `verifying`. Puertas spec y plan aprobadas; quality, conformance y memory pendientes
  (las cierra la sesión principal con el PR común y su CI).
- Last completed gate: plan.
- Current revision: rama `feat/codex-read-summary-write-guard`.

## What changed

- `codex_reads.py` nuevo: decisión del hook `codex-tool-guard` (`PreToolUse`), estado por sesión y
  agente, cliente mínimo del `/mcp` del daemon.
- `codex_hooks.py`: una entrada en `SPECS`, `HookSpec.timeout`, etiqueta `pre_tool_use`, una rama en
  `run` antes del corte por backend.
- Textos `codex.read.*`/`codex.guard.*` es/en; cliente `local-delegate-codex-read` fuera del coste.
- Wiki, CHANGELOG, fixtures oficiales de `PreToolUse`, `tests/test_codex_reads.py`.

## Decisions

- Sustitución por el motivo de `deny` de `PreToolUse`: único camino de Codex 0.169.0 que impide la
  ejecución y muestra texto al modelo. `PostToolUse` no sustituye la salida de Bash y
  `updatedInput` a un `echo` pasaría por sandbox y quoting (ver `research.md`).
- Solo se sustituye un comando que es solo la lectura; un compuesto pasa con nota.
- Estado por agente (`main` / `agent:<agent_id>`) en un log JSONL con cerrojo, sin contenido.
- Sin caché de resúmenes ni diálogo; sin telemetría P-4 (decisión de #669).

## Next action

1. Integrar con #669 (otro `PreToolUse` en `SPECS` y `EVENT_LABELS`: conflicto trivial) y #671; los
   tests que cuentan hooks usan `len(codex_hooks.SPECS)`.
2. Prueba en vivo de la persona usuaria (wiki, «Prueba en vivo»): centinela, `apply_patch` rechazado
   y levantado con un tramo, daemon parado, y captura del payload real de Windows si no resume.
3. Revisión de resultado (deep: dos jueces y revisor de seguridad) y puertas quality/conformance.

## Memory

- Canonical note: sin nota aparte; lo durable va en `handoff.md`, la wiki y el CHANGELOG.
- Indexes updated: no
