# Result review: MoE, inferencia de delegacion, MCP remoto y backends

## Gate and proposed verdict

- Gate: conformance/result.
- Verdict: **does-not-conform yet**. REQ-007 y REQ-008 ya tienen evidencia real desde la Mac; solo
  REQ-006 requiere evidencia externa para cerrar conformidad.

## Blocking findings

1. Falta el A/B de hooks en sesiones reales: no hay adopción ni falsos positivos medidos.

## Non-blocking findings

- El scorer de términos necesita normalización Unicode antes de convertirse en juez automático.
- Los baselines iniciales no conservaron `timings` del backend; la comparación de calidad sí es
  válida, pero no debe presentarse su throughput aproximado como decode tok/s.
- PDF/chunking necesita un cambio SDD separado si se decide implementarlo.

## Missing evidence and exact remediation

1. Abrir nuevas sesiones equivalentes de Claude Code con el piloto activo, etiquetar manualmente
   oportunidades elegibles y falsos positivos, y calcular los gates 40%/10%.
2. Adjuntar el resultado de hooks a `verification.md`; después repetir esta revisión y solo entonces
   aprobar `quality`/`conformance`.

## Requirement comparison

REQ-001..005 y REQ-007..010: implementados y verificados. REQ-006 mantiene evidencia externa
pendiente. No hay desviaciones ocultas ni upgrade estable.
