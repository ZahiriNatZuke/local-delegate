# Verification: MoE, inferencia de delegacion, MCP remoto y llama-swap actualizado

## Environment

- Revision: worktree local sin commit; stable backend no reemplazado.
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
| REQ-005 | Hooks antes de prompt/Read/Bash, metadata-only | PASS local | scripts, settings activo y `tests/test_hook_recipes.py` |
| REQ-006 | Bandas 8/32 KiB y campos de telemetría | PARTIAL | implementación lista; falta muestra A/B de sesiones reales |
| REQ-007 | Recipe MCP local Mac -> backend PC | PARTIAL | diseño y auth local verificados; faltan 20 llamadas desde la Mac |
| REQ-008 | apiKeys por env, Bearer en endpoints, bind privado documentado | PARTIAL | canary 401/200 y secret scan; falta firewall/interfaz privada real |
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
- [x] `uv run pytest -q`: 156 passed, una advertencia de deprecación preexistente Starlette/httpx.
- [x] JavaScript del dashboard extraído y `node --check` aprobado.
- [x] `git diff --check`.
- [x] Gitleaks limpio en rutas relevantes. El escaneo bruto del workspace marcó seis falsos
  positivos dentro de `.venv`; al excluir dependencias vendorizadas, cero hallazgos.
- [x] Canary apagado, puerto 9294 cerrado, VRAM ~1.7 GiB y stable `/v1/models` = 200.

## Deviations and residual risk

- La primera configuración gpt-oss sin `reasoning_effort=low` agotó el límite en reasoning y dejó
  content vacío. Se conservó como evidencia inválida y se repitió toda la matriz correctamente.
- El scoring literal penaliza separadores Unicode; hubo revisión manual. Aun corrigiendo esa
  limitación, la degeneración de tabla y truncaciones son reales.
- La primera corrida m0 del sweep válido estaba caliente por el smoke; la latencia cold de carga
  está en los canaries inválidos. Memoria steady/hot y la decisión no dependen de ese dato.
- No hay evidencia desde la Mac ni muestra A/B de hooks todavía. Esas dos faltas bloquean cerrar el
  gate de conformidad, pero no invalidan las decisiones locales.
