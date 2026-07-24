# Research: MoE, inferencia de delegacion, MCP remoto y versiones backend

## 1. Mixture of Experts: que ocurre realmente

Un MoE sustituye parte de las capas feed-forward densas por varios expertos y un router. Para cada
token, el router puntua los expertos y activa un `top-k` pequeño. Eso reduce computo por token
respecto al total de parametros, pero no convierte el modelo en un conjunto de archivos que
`llama-swap` carga y descarga segun si la tarea es PDF, codigo o resumen.

Consecuencias operativas:

- **Expertos activos no es memoria ocupada.** Los pesos totales deben residir en algun lugar
  accesible (VRAM, RAM/mmap o ambas), aunque solo una fraccion participe en cada token.
- **No hay un umbral por tarea.** Qwen3-30B-A3B activa 8 de 128 expertos por token; gpt-oss-20b
  activa 4 de 32. El usuario no elige 4 para lectura y 8 para PDF.
- **El routing ocurre por token.** Un mismo prompt puede usar expertos distintos a lo largo de la
  secuencia; el router fue aprendido durante training.
- **Offload no cambia capacidad teorica.** `--cpu-moe` conserva todos los pesos expertos en CPU y
  `--n-cpu-moe N` hace lo mismo para las primeras N capas. Cambia memoria y velocidad, no el top-k.
- **No existe hoy una cache persistente que cargue solo los expertos usados.** llama.cpp puede
  copiar subfilas expertas usadas durante computo, pero la propuesta de cache GPU/RAM de expertos
  sigue abierta upstream; no debe venderse como capacidad estable.

Fuentes primarias:

- Paper sobre routing top-k fijo: https://arxiv.org/abs/2202.09368
- Qwen3-30B-A3B GGUF oficial: https://huggingface.co/Qwen/Qwen3-30B-A3B-GGUF
- Arquitectura oficial gpt-oss: https://openai.com/index/introducing-gpt-oss/
- Flags oficiales llama-server: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Gap de cache de expertos: https://github.com/ggml-org/llama.cpp/issues/20757

## 2. Candidatos viables en este host

| Candidato | Total / activo | Expertos total / activos | GGUF confiable | Encaje preliminar |
| --- | --- | --- | --- | --- |
| `gpt-oss-20b` | 21B / 3.6B | 32 / 4 | ggml-org MXFP4, 11.28 GiB | Primer canary: cabe en 16 GiB con contexto moderado y deja margen para comparar offload |
| `Qwen3-30B-A3B` | 30.5B / 3.3B | 128 / 8 | Qwen Q4_K_M, 17.28 GiB | Segundo canary: requiere offload; interesante por multilingue, pero mas presion sobre RAM/VRAM |

No se propone Qwen3.5/3.6 A3B en la primera ronda: existen pesos mas nuevos, pero el camino GGUF
y la combinacion de build/quantizacion tienen menos rodaje que los dos candidatos anteriores. No se
propone gpt-oss-120b ni Qwen3-Next-80B: exceden el margen razonable de 32 GiB RAM.

## 3. Que medir en vez de "cuantos expertos por tarea"

La variable controlable es **donde quedan las capas expertas**, no cuantos expertos se activan.

- gpt-oss-20b (24 capas): `--n-cpu-moe` = 0, 6, 12, 18, 24 y alias `--cpu-moe`.
- Qwen3-30B-A3B (48 capas): 0, 12, 24, 36, 48, solo si gpt-oss pasa el primer gate.
- Contexto: 8k, 16k y 32k; no empezar por 128k en 16 GiB VRAM.
- Memoria: pico VRAM, RAM working set, page faults y ausencia de shared-memory fallback de Windows.
- Rendimiento: cold load, prompt processing tok/s, decode tok/s, time-to-first-token y p95 end-to-end.
- Calidad: completitud, fidelidad, formato, alucinaciones y consistencia en tres corridas.

Corpus propuesto:

1. resumen de texto de 2k, 8k y 24k tokens con hechos verificables;
2. extraccion JSON con 20-50 campos y distractores;
3. resumen de logs de 2k/10k lineas;
4. explicacion de archivos de codigo de 5/20/50 KiB;
5. documento largo convertido previamente a Markdown;
6. PDF solo despues de escoger extractor y map-reduce; hoy `local_summarize(path=pdf)` no es valido.

Gate MoE recomendado: seguir solo si supera la calidad del baseline denso de su rol, cabe bajo
14.5 GiB VRAM/28 GiB RAM, mantiene al menos 10 tok/s de decode, no trunca el corpus y ofrece una
mejora util en tareas donde los modelos actuales fallan. Si solo es mas lento con igual calidad,
se documenta como backend compatible y no se agrega un rol especial a `local-delegate`.

## 4. Delegacion en Claude Code: evidencia y causa probable

La regla global de Claude y Codex es actualmente identica. Claude tiene ademas dos hooks activos:

- `PreToolUse(Read)` sugiere delegar solo por encima de 50 KiB;
- `PostToolUse(Bash)` avisa despues de salidas de test/lint mayores de 120 lineas.

Auditoria agregada de 30 sesiones recientes de Claude (sin leer ni conservar contenido):

| Evento | Conteo |
| --- | ---: |
| `Read` | 868 |
| `Bash` | 1,251 |
| tools `local_*` realmente invocadas | 6 |
| agents personales con `local_delegate` en allowlist | 27 de 40 |

El hook `PostToolUse(Bash)` llega demasiado tarde: el output ya entro al contexto. El umbral de
50 KiB tambien omite muchos archivos medianos. La telemetria de `local-delegate` del mes muestra:

| Entrada | Eventos | Latencia media | Tokens ahorrados via `path` |
| --- | ---: | ---: | ---: |
| <2k chars | 94 | 0.99 s | 512 |
| 2-6k | 42 | 1.44 s | 22,223 |
| 6-20k | 18 | 8.29 s | 44,066 |
| >=20k | 18 | 14.93 s | 254,724 |

Esto justifica un experimento por intencion y tamaño, no un umbral ciego:

- <8 KiB: leer directo salvo transformacion mecanica explicita;
- 8-32 KiB: sugerir `local_*` si el objetivo es resumen/extraccion/traduccion/explicacion global;
- >32 KiB: recomendacion fuerte de `path` salvo que se necesiten lineas exactas;
- >48k chars: no prometer resumen completo hasta implementar chunking/map-reduce.

Cambios a experimentar, en orden:

1. `UserPromptSubmit` determinista que detecte verbos/tipos claros y añada una sola frase de contexto;
2. `PreToolUse(Read)` con bandas 8/32 KiB e intencion, sin bloquear;
3. mover deteccion de test/lint a `PreToolUse(Bash)` para pedir redireccion antes de ejecutar;
4. compactar la regla global con lenguaje prescriptivo y ejemplos negativos;
5. revisar agents con allowlist y sincronizar solo los que hacen trabajo mecanico;
6. instrumentar oportunidades, aceptaciones y falsos positivos sin guardar prompts/contenido.

No se recomienda una tool LLM `local_should_delegate` en la primera iteracion: crea una decision
circular, añade latencia y delega una tarea de criterio al modelo menos capaz. Hooks deterministas y
descripciones de tools son mas baratos, medibles y consistentes.

Fuentes oficiales Claude Code:

- Hooks y `UserPromptSubmit`/`PreToolUse`: https://code.claude.com/docs/en/hooks
- Skills/tools de subagents: https://code.claude.com/docs/en/sub-agents

## 5. Acceso desde la Mac: tres topologias

### A. MCP local en Mac -> backend llama-swap remoto en PC (recomendada)

La Mac ejecuta el proceso liviano `local-delegate` y configura:

- `LOCAL_DELEGATE_BASE_URL=http://<ip-privada-pc>:9292/v1`
- `LOCAL_DELEGATE_API_KEY` mediante variable/secret store
- `LOCAL_DELEGATE_AUTOSTART=0`

La PC hace bind de llama-swap solo en su interfaz privada y configura `apiKeys`. Ventaja decisiva:
`path=/Users/...` lo lee el MCP en la Mac y el contenido viaja directo al backend sin entrar al
contexto de Claude. No se encadenan dos MCP ni se necesita feature nueva en el protocolo.

### B. Cliente Mac -> daemon MCP remoto en PC

Claude Code soporta Streamable HTTP remoto y headers. Sirve para inputs inline, status y un daemon
central, pero `path=/Users/...` se intentaria abrir en la PC y fallaria. Solo conviene con un
filesystem compartido y mapeo explicito, o para tools sin `path`.

### C. `llama-swap peers`

La version actual admite peers remotos y API key. Es util si se quiere un catalogo llama-swap que
combine varios hosts; agrega otra capa y no resuelve la lectura de paths de la Mac. No es necesaria
para el caso inicial.

La prueba remota debe medir latencia, reconexion, auth, limite de concurrencia y rutas Mac. Los dos
clientes mantienen `local-delegate` en scope global, respetando el inventario compartido vigente.

Fuentes:

- MCP HTTP remoto y headers en Claude Code: https://code.claude.com/docs/en/mcp
- Peers y apiKeys de llama-swap: https://github.com/mostlygeek/llama-swap/blob/main/docs/configuration.md

## 6. Actualizaciones: resultado de la inspeccion actual

- Instalado/probado: llama-swap v238 y llama-server b9925.
- Publicado: llama-swap v241 (2026-07-22) y llama.cpp b10098 (2026-07-23).
- v241 trae selectors/profiles, pero tiene apenas un dia de rodaje.
- Existe un issue abierto de deadlock entre TTL unload y una request entrante reportado contra v240
  despues de salir v241; no hay evidencia aun de que v241 lo resuelva.
- llama.cpp publico varios builds el mismo dia; el numero mas alto es un rolling build, no un canal
  estable.

Decision actual: **no actualizar hoy**. Mantener v238/b9925 como estable y crear un canary aislado.

Politica propuesta:

1. esperar al menos 7 dias desde release salvo security/correctness fix necesario;
2. revisar changelog e issues abiertos de Windows/CUDA/MoE/streaming;
3. verificar checksum y firma/procedencia;
4. instalar lado a lado, nunca sobreescribir primero;
5. correr config parse, `/v1/models`, `/running`, inferencia por cada rol, vision, concurrencia,
   TTL/swap y metricas SQLite;
6. hacer soak de 24 h y conservar rollback de binario+config;
7. solo entonces actualizar `RECOMMENDED_VERSIONS`, README y Wiki.

Fuentes oficiales:

- Releases llama-swap: https://github.com/mostlygeek/llama-swap/releases
- Releases llama.cpp: https://github.com/ggml-org/llama.cpp/releases
- Issue de deadlock: https://github.com/mostlygeek/llama-swap/issues/946

## Impact map

| Area futura | Impacto probable | Decision previa |
| --- | --- | --- |
| `llamaswap_config.py` | reconocer/reportar MoE y presupuestos CPU/GPU | solo si benchmark pasa |
| `server.py`/`config.py` | rol/modelo adicional o chunking | evitar rol MoE si no aporta calidad |
| hooks/skill/agents | aumentar invocacion en Claude | A/B con telemetria anonima |
| docs remotas | recipe backend remoto | validar primero en Mac real |
| doctor/docs versiones | canal stable/canary | aplicar politica de soak |
| PDF/documentos | extractor + map-reduce | cambio separado y auditoria de dependencia |
