# Result review: MoE, inferencia de delegacion, MCP remoto y backends

## Gate and proposed verdict

- Gate: conformance/result.
- Verdict: **does-not-conform yet**. REQ-007 ya tiene evidencia real desde la Mac, pero REQ-006 y
  REQ-008 todavía requieren evidencia externa para cerrar conformidad.

## Blocking findings

1. Falta el A/B de hooks en sesiones reales: no hay adopción ni falsos positivos medidos.
2. Falta repetir el canary Mac -> PC con auth activa: sin key debe devolver 401/403 y con key debe
   completar las 20 llamadas. La pasada sin auth ya verificó path de Mac, concurrencia y reinicio.

## Non-blocking findings

- El scorer de términos necesita normalización Unicode antes de convertirse en juez automático.
- Los baselines iniciales no conservaron `timings` del backend; la comparación de calidad sí es
  válida, pero no debe presentarse su throughput aproximado como decode tok/s.
- PDF/chunking necesita un cambio SDD separado si se decide implementarlo.

## Missing evidence and exact remediation

1. Abrir nuevas sesiones equivalentes de Claude Code con el piloto activo, etiquetar manualmente
   oportunidades elegibles y falsos positivos, y calcular los gates 40%/10%.
2. Activar `apiKeys` sin persistir el secreto y repetir desde la Mac con `--expect-auth`; una
   request sin key debe devolver 401/403 y las 20 llamadas autenticadas deben completar.
3. Adjuntar ambos resultados a `verification.md`; después repetir esta revisión y solo entonces
   aprobar `quality`/`conformance`.

## Requirement comparison

REQ-001..005, REQ-007, REQ-009 y REQ-010: implementados y verificados. REQ-006 y REQ-008:
evidencia externa pendiente. No hay desviaciones ocultas ni upgrade estable.
