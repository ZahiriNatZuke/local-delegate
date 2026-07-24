# Result review: MoE, inferencia de delegacion, MCP remoto y backends

## Gate and proposed verdict

- Gate: conformance/result.
- Verdict: **does-not-conform yet**. La implementación local y las decisiones están sustentadas,
  pero REQ-006, REQ-007 y REQ-008 requieren evidencia externa que no puede simularse en esta PC.

## Blocking findings

1. Falta el A/B de hooks en sesiones reales: no hay adopción ni falsos positivos medidos.
2. Falta el canary real Mac -> PC: 20 llamadas, `path` de Mac, reconexión, concurrencia, firewall e
   intento sin autorización desde la interfaz privada.

## Non-blocking findings

- El scorer de términos necesita normalización Unicode antes de convertirse en juez automático.
- Los baselines iniciales no conservaron `timings` del backend; la comparación de calidad sí es
  válida, pero no debe presentarse su throughput aproximado como decode tok/s.
- PDF/chunking necesita un cambio SDD separado si se decide implementarlo.

## Missing evidence and exact remediation

1. Abrir nuevas sesiones equivalentes de Claude Code con el piloto activo, etiquetar manualmente
   oportunidades elegibles y falsos positivos, y calcular los gates 40%/10%.
2. En la Mac, configurar el MCP local con el endpoint privado y key; ejecutar 20 llamadas mixtas,
   incluyendo archivo exclusivo de `/Users`, dos concurrentes, corte/reconexión y una request sin
   key que debe devolver 401.
3. Adjuntar ambos resultados a `verification.md`; después repetir esta revisión y solo entonces
   aprobar `quality`/`conformance`.

## Requirement comparison

REQ-001..005, REQ-009 y REQ-010: implementados y verificados. REQ-006..008: implementados
parcialmente, evidencia externa pendiente. No hay desviaciones ocultas ni upgrade estable.
