# Result review: MoE, inferencia de delegacion, MCP remoto y backends

## Gate and proposed verdict

- Gate: conformance/result.
- Verdict: **conforms**. REQ-001..010 tienen evidencia suficiente para el paquete de decisión.
  El piloto rechazó el default de Read, adoptó Prompt+Bash y dejó la configuración ruidosa apagada.

## Blocking findings

Ninguno.

## Non-blocking findings

- El scorer de términos necesita normalización Unicode antes de convertirse en juez automático.
- Los baselines iniciales no conservaron `timings` del backend; la comparación de calidad sí es
  válida, pero no debe presentarse su throughput aproximado como decode tok/s.
- PDF/chunking necesita un cambio SDD separado si se decide implementarlo.
- Los logs de uso de tests deben aislarse antes de automatizar el KPI de adopción.
- El ahorro de tokens del piloto es una estimación por caracteres; no debe presentarse como costo
  facturado.

## Missing evidence and exact remediation

Ninguna para cerrar este paquete de decisión. Si se quiere reactivar Read, debe abrirse otro piloto
con una señal de intención además del tamaño y volver a pasar el gate <=10%.

## Requirement comparison

REQ-001..010: implementados y verificados contra el alcance de investigación/decisión. La variante
Read 8/32 no pasó el gate de ruido y quedó `ITERATE`, apagada por defecto; esto es una decisión
negativa válida bajo REQ-010, no una promoción incompleta. No se actualizó el backend estable.

## Recommended gate evidence

`quality`: suite completa 160 passed, hooks 6 passed, logs de tests aislados, Ruff/format/diff
checks limpios y evidencia sin secretos. `conformance`: A/B 5/6 -> 6/6, configuración adoptada
0/4 falsos positivos, canary remoto autenticado 20/20 y decisiones finales en `results.md`.
