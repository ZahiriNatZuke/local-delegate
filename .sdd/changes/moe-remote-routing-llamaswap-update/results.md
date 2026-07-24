# Decision package: MoE, delegacion, remoto y backends

Fecha: 2026-07-23. Hardware: RTX 5060 Ti 16 GiB, 32 GiB RAM. Stable no modificado:
llama-swap v238 y llama-server b9925.

## Decisiones

| Linea | Decision | Motivo |
| --- | --- | --- |
| MoE en producto | **ITERATE; no añadir rol/default todavía** | gpt-oss funciona y es rápido, pero no supera la calidad de los densos; 16k/32k exceden el gate de RAM y el resumen largo degeneró al construir una tabla |
| Qwen3-30B-A3B | **DEFER** | el segundo candidato estaba condicionado a que gpt-oss pasara el gate completo; no lo pasó, y Qwen exige todavía más RAM/offload |
| Hooks Claude | **ADOPT como piloto medido** | son consultivos, actúan antes de Read/Bash, excluyen tareas de criterio y no guardan contenido; falta medir adopción/falsos positivos en sesiones reales |
| Backend remoto | **ADOPT** | canary autenticado pasó 20/20, 401 sin key, path de Mac, concurrencia y reinicio |
| Upgrade backend | **REJECT ahora** | v241/b10098 no tienen 7 días; llama-swap #946 reporta deadlock TTL/request |

## Respuesta al problema de “cuantos expertos”

No existe un número de expertos que se monte por tarea. gpt-oss-20b siempre tiene 32 expertos y su
router activa 4 por token; Qwen3-30B-A3B tiene 128 y activa 8. `--n-cpu-moe` mueve capas expertas
entre GPU y CPU, pero no cambia el top-k ni la capacidad semántica. Para leer un archivo o resumir
un PDF importan el contexto, el pipeline de extracción/chunking, la calidad y la memoria total.

## Evidencia MoE

GGUF: `gpt-oss-20b-MXFP4.gguf`, 12,109,566,624 bytes. SHA-256 verificado:
`27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901`.

Se ejecutaron 15 variantes × 5 casos × 3 corridas = 225 llamadas. `reasoning_effort=low`; un
primer canary sin ese parámetro se conservó como evidencia inválida porque agotó la salida en
razonamiento y devolvió `content` vacío.

| Contexto / CPU-MoE | Éxitos | VRAM steady GiB | RAM host steady GiB | Decode hot tok/s | Truncadas |
| --- | ---: | ---: | ---: | ---: | ---: |
| 8k / 0 | 9/15 | 12.93 | 27.16 | 121.3 | 0 |
| 8k / 12 | 9/15 | 8.31 | 27.49 | 46.1 | 0 |
| 8k / 24 | 9/15 | 3.66 | 28.52 | 25.5 | 0 |
| 16k / 0 | 12/15 | 13.18 | 28.87 | 123.4 | 3 |
| 16k / 12 | 12/15 | 8.70 | 29.13 | 44.2 | 3 |
| 32k / 0 | 15/15 | 13.58 | 29.42 | 116.3 | 4 |
| 32k / 12 | 15/15 | 8.90 | 28.89 | 46.0 | 4 |
| 32k / 24 | 15/15 | 4.12 | 28.67 | 26.8 | 6 |

Los errores 8k/16k son rechazos explícitos por contexto, no truncación silenciosa. En 32k todas
las requests llegaron al modelo, pero varias respuestas alcanzaron `max_tokens`. El caso de 96k
caracteres preservó los hechos en prosa, pero una corrida degeneró en cientos de separadores `|`
al construir la tabla final. El scoring literal además penaliza espacios finos/guiones Unicode;
por eso se revisó manualmente la salida y no se usa la cobertura sola como judge.

Comparación común a 8k:

| Modelo | summary-2k | summary-8k | extract-json |
| --- | ---: | ---: | ---: |
| Gemma 3 4B Q4_K_M | 0.83 | 1.00 | 1.00 |
| Llama 3.1 8B Q4_K_M | 0.83 | 1.00 | 1.00 |
| gpt-oss-20b MXFP4, CPU-MoE 12 | 0.67 | 0.90 | 1.00 |

El mejor perfil experimental es **8k / `--n-cpu-moe 12`**: cumple VRAM/RAM, mantiene 46 tok/s y
reduce VRAM frente a m0. Aun así, no aporta calidad sobre los densos y no resuelve documentos
largos. Por tanto no se descarga Qwen3 ni se añade un rol MoE al catálogo.

El soak corto adicional del candidato completó **20/20** llamadas sin error: 8.24 GiB VRAM,
27.51 GiB RAM host, p95 9.1 s y 38.7 tok/s calientes. Pasa estabilidad/rendimiento para 8k, pero
no revierte el fallo del gate global de calidad/documentos largos.

## Delegación Claude

- Read consultivo en 8 KiB; sugerencia fuerte en 32 KiB.
- Bash ruidoso se detecta en `PreToolUse`, antes de ejecutar, no en `PostToolUse`.
- `UserPromptSubmit` reconoce resumir/extraer/clasificar/traducir/lint/boilerplate y excluye
  arquitectura, investigación, seguridad, deploy y migraciones.
- Telemetría: evento, categoría, tamaño y decisión; nunca prompt, comando o path.
- Auditoría: 27/40 agentes permiten local-delegate. Los 13 excluidos son perfiles de seguridad,
  investigación/revisión SDD o razonamiento especializado; no se amplió su allowlist.

Gate pendiente: medir sesiones reales hasta poder calcular adopción >=40% y falsos positivos <=10%.

## Remoto

La recipe `docs/recipes/remote-backend.md` fija MCP local en Mac -> llama-swap privado en PC. El
cliente envía Bearer también a chat, `/models`, `/running` y métricas. La config canary confirmó
auth nativa de llama-swap (401/200) sin persistir keys.

Canary autenticado en Mac contra la revisión
`6d60980beedb4a4c67ec07207ff3b54c19c1ca4d`: **20/20**, path temporal exclusivo de la Mac,
concurrencia 2, dos arranques del proceso y p95 2.983 s. El endpoint HTTPS privado respondió 401
sin credencial y 200 con la key guardada en Keychain; en Windows la key queda cifrada con DPAPI y
solo se inyecta al entorno del proceso. No se publica el MCP completo desde la PC como default
porque rompería paths de `/Users/...`.

## Versiones

`doctor --online` ahora reporta instalada/probada/latest/edad y hasta tres issues de riesgo por
título. Resultado vivo: v241 (1 día), b10098 (<1 día), ambos HOLD; issue #946 también bloquea la
promoción. Se mantienen v238/b9925.

## Evidencia y rollback

- Resultados JSONL: `evidence/bench-*.jsonl` y estabilidad `evidence/stability-*.jsonl`.
- Canary: `benchmarks/moe/llama-swap-canary.yaml`, puerto 9294; quedó apagado y VRAM volvió a
  ~1.7 GiB.
- Stable: config y binarios no fueron reemplazados; `/v1/models` siguió respondiendo 200.
- Hooks: backup en
  `%USERPROFILE%\.claude\settings.json.pre-local-delegate-hook-pilot-20260723.bak`.
