# Verification: MoE, inferencia de delegacion, MCP remoto y llama-swap actualizado

## Environment

- Revision canary: `a79721f8c64c5be4fda1be025b80f1b7eab67ef0`; stable backend no reemplazado.
- Hardware: RTX 5060 Ti 16 GiB, 32 GiB RAM.
- Runtime: Python 3.11, llama-swap v238, llama-server b9925.
- Candidato: gpt-oss-20b MXFP4 oficial, SHA-256 verificado.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | Arquitectura/top-k y flags contrastados con fuentes upstream y ayuda del binario | PASS | `research.md`, `results.md` |
| REQ-002 | 15 variantes × 5 casos × 3 corridas, más baselines densos | PASS | `evidence/bench-*.jsonl` |
| REQ-003 | Gate de gpt-oss evaluado antes de descargar Qwen | PASS/DEFER | gpt-oss no pasó calidad+RAM global; Qwen no se descargó |
| REQ-004 | Contexto 8k/16k/32k y caso 96k caracteres | PASS con nota | rechazos de contexto explícitos; en 32k se observó truncación/degeneración, por lo que chunking queda separado |
| REQ-005 | Línea base y hooks consultivos antes del gasto, metadata-only | PASS | A/B real; Prompt+Bash adoptados, Read experimental apagado por ruido |
| REQ-006 | Adopción, falsos positivos, error, latencia, ahorro y bandas | PASS | 5/6 -> 6/6; configuración adoptada 0/4 FP, 0 errores; `evidence/hooks-pilot-20260724.json` |
| REQ-007 | MCP local Mac -> backend PC por endpoint HTTPS privado | PASS | canary real: 20/20, path exclusivo de Mac, concurrencia 2, dos arranques y p95 7.119 s |
| REQ-008 | apiKeys por env, Bearer en endpoints y exposición privada | PASS | DPAPI/Keychain, Tailscale Serve+ACL, 401 sin key, 200 con key y canary autenticado 20/20 |
| REQ-009 | instalada/probada/latest/edad/issues y gate 7 días | PASS | `doctor --online`: v241/b10098 HOLD y llama-swap #946 |
| REQ-010 | decisiones adopt/iterate/reject | PASS | `results.md` |

## MoE quantitative checks

- Sweep: 225 llamadas; candidato 8k/CPU-MoE 12.
- Estabilidad: 20/20, sin crash.
- Pico: 8.24 GiB VRAM, 27.51 GiB RAM host; sin swap/pagefile reportado.
- Rendimiento: 38.7 tok/s hot promedio; p95 9.1 s.
- Calidad: inferior a los baselines en los resúmenes comunes; degeneración de tabla en el caso
  largo. Decisión correcta: `ITERATE`, no promoción.

## Quality checks

- [x] `uv lock --check`.
- [x] `uv run ruff check .`.
- [x] `uv run ruff format --check .` después de aplicar formato.
- [x] `uv run pytest -q --basetemp <aislado>`: 160 passed, una advertencia de deprecación
  preexistente Starlette/httpx.
- [x] `uv run pytest -q tests/test_hook_recipes.py --basetemp <aislado>`: 6 passed después del
  ajuste que apaga Read por defecto.
- [x] JavaScript del dashboard extraído y `node --check` aprobado.
- [x] `git diff --check`.
- [x] Gitleaks limpio en rutas relevantes. El escaneo bruto del workspace marcó seis falsos
  positivos dentro de `.venv`; al excluir dependencias vendorizadas, cero hallazgos.
- [x] Canary apagado, puerto 9294 cerrado, VRAM ~1.7 GiB y stable `/v1/models` = 200.
- [x] Suite completa con aislamiento: 160 passed y el SHA-256 del log real quedó idéntico antes y
  después de pytest.
- [x] Limpieza: 192 filas de fixtures retiradas del JSONL real; 76 eventos legítimos conservados;
  telemetría/timestamps/directorios del piloto y dos scratchpads de pytest eliminados.

## Deviations and residual risk

- La primera configuración gpt-oss sin `reasoning_effort=low` agotó el límite en reasoning y dejó
  content vacío. Se conservó como evidencia inválida y se repitió toda la matriz correctamente.
- El scoring literal penaliza separadores Unicode; hubo revisión manual. Aun corrigiendo esa
  limitación, la degeneración de tabla y truncaciones son reales.
- La primera corrida m0 del sweep válido estaba caliente por el smoke; la latencia cold de carga
  está en los canaries inválidos. Memoria steady/hot y la decisión no dependen de ese dato.
- El canary autenticado desde la Mac pasó conectividad, path, concurrencia y reinicio del proceso;
  el endpoint rechazó la petición sin key.
- La telemetría de uso comparte destino con algunos tests y contenía filas sintéticas durante
  `pytest`. El cálculo A/B las excluyó de forma explícita; conviene aislar el log de tests en un
  cambio posterior si se automatiza este KPI.
- El ahorro incremental de ~70 tokens es una aproximación por caracteres, no consumo facturado por
  Claude. La adopción y los falsos positivos sí salen de eventos completos: 10/10 prompts B.
