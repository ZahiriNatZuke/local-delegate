# Mini-plan F7 — Groups de llama-swap como capacidad del paquete

> Deriva de la sección "F7" de `plan-v0.2-mejoras.md`. Este documento cierra el **Paso 0**
> (verificación contra docs actuales) y detalla fases/criterios/checklist antes de tocar código.

## Paso 0 — Verificación (hecha, 2026-07-09)

- `llama-swap.exe --version` local → **v235 (c59816b)**, built 2026-07-03. `c59816b` es un commit
  real de `main` en `mostlygeek/llama-swap` (confirmado vía `gh api`), no un fork ni un tag propio
  — es el repo oficial que ya asumía el plan.
- Descargados y leídos `docs/configuration.md` y `config-schema.json` **de ese commit exacto**
  (`?ref=c59816bace800e1630ca8791541b4a53a9705f9b`).

### Discrepancia importante encontrada

El plan maestro llama a esto "groups de llama-swap" sin matices. La realidad en esta versión:

- Existe un sistema **nuevo** (`matrix`, DSL basado en solver) que la propia doc del proyecto
  llama la alternativa moderna a groups. La doc dice explícitamente: *"A config must use either
  a matrix or legacy groups, not both"* y enlaza los ejemplos de "legacy Groups" a un commit
  viejo (`40e39f7`).
- **PERO** `groups` sigue vivo en el schema actual: existe como clave top-level (`groups:`) y
  también como forma canónica nueva `routing.router.settings.groups` con
  `routing.router.use: "group"` como **default** (`"group"` gana sobre `"matrix"` si no se
  especifica). O sea: groups NO está deprecado ni removido, es simplemente la opción "simple"
  frente a `matrix` (concurrencia con solver, útil para correr varios modelos A LA VEZ — no es
  nuestro caso, que es "un modelo a la vez con hot-swap + un residente fijo").
- **Decisión:** implementar contra la forma **top-level `groups:`** (la que ya usa el ejemplo
  legado y la que coincide con el `config.yaml` real del usuario, que no usa `routing:`).
  Documentarlo en un comentario del YAML generado y en la recipe, con nota de que `matrix` existe
  como alternativa si el usuario alguna vez quiere correr modelos concurrentes.

### Semántica exacta de `groups` (schema, no memoria)

```
groups:
  <nombre>:
    swap: bool       # default true.  true = solo 1 modelo del grupo corre a la vez.
                      #                false = todos los miembros pueden correr juntos.
    exclusive: bool  # default true.  true = al cargar un modelo de este grupo, TODOS los
                      #                otros grupos se descargan. false = no afecta a otros grupos.
    persistent: bool # default false. true = otros grupos no pueden descargar los modelos de
                      #                ESTE grupo (no fuerza precarga, solo evita eviction).
    members: [ids]   # ids de models: ya definidos. Un modelo solo puede estar en un grupo.
```

- **`ttl` NO es una clave de `groups`** (el plan maestro lo daba a entender). `ttl` es
  **por-modelo** (`models.<id>.ttl`, `-1` hereda `globalTTL`, `0` = nunca descarga, `N` segundos)
  y `globalTTL` es una clave **top-level** del config (default `0` = nunca descarga si no se fija
  ttl por modelo). `init-llamaswap` fijará `ttl:` en los modelos referenciados por
  `--resident`/`--swap`, no en el grupo.
- Confirmado con el ejemplo legado real (`config.example.yaml@40e39f7`): un grupo "resident"
  con `persistent: true, swap: false, exclusive: false` + un grupo "swap" con
  `swap: true, exclusive: false` es exactamente el patrón que pidió el usuario para el ritual
  F7.5 (gemma3-4b fijo, llama31-8b/qwen25-coder-14b turnándose).

### Ya cubierto por F2/F4 (nada que hacer en F7.4)

Revisado `server.py`: `_vram_info()` (línea ~902) **ya** añade `"ADVERTENCIA: <2 GB libres"` en
línea cuando `free_mb < 2048`, y `_llamaswap_running()` + `local_status()` ya exponen VRAM y
`/running`. `web/metrics.py` ya tiene `GET /api/backend` (proxy de `/running`) y
`GET /api/inflight`. **F7.4 no requiere código nuevo**, solo verificar (al final) que sigue
funcionando y, opcionalmente, que `local_status` mencione si hay `groups:` activos en el config
apuntado (best-effort, sin parsear el YAML si `pyyaml` no está instalado).

---

## Fases

### F7.1 — `llamaswap_config.py` (nuevo módulo, opcional como `autostart.py`)

**Ajuste decidido tras revisar los números reales del usuario (ver conversación):** un factor
plano `x1.2` no es uniformemente conservador. Con los GGUF reales del catálogo del usuario:
`llama31-8b` a `--ctx-size 16384` sin cuantizar KV → el plano da 5.50 GiB pero el KV cache real
son ~2 GiB extra (total real ~6.88 GiB, **subestimado en 1.38 GiB** — justo el caso peligroso).
`qwen25-coder-14b` con `--cache-type-k/v q4_0` → el plano da 10.04 GiB, el real son ~9.05 GiB
(sobreestimado, seguro pero desperdicia presupuesto). Un guardrail que subestima en el caso que
más importa no cumple su función. Se implementa entonces la vía fina que el plan maestro ya
insinuaba (`kv_estimate(ctx, n_layers?)`), con el factor plano como *fallback*, no como default:

- Import guard: si `pyyaml` no está instalado, `load_config`/`dump_config` (las únicas funciones
  que lo necesitan) lanzan `RuntimeError` con el mensaje exacto
  `pip install "local-delegate-mcp[llamaswap]"`. El estimador de VRAM (parser GGUF incluido) NO
  depende de `pyyaml` y funciona sin el extra — solo el I/O de config.yaml lo requiere. El resto
  del paquete (server MCP, tools) sigue funcionando igual sin el extra: este módulo no se importa
  desde `server.py` en el flujo normal, solo desde el dispatcher de CLI. `pyyaml` se añade también
  al `dependency-group` `dev` para que los tests corran sin instalar el extra público.
- `read_gguf_arch_info(gguf_path: Path) -> dict | None`: lee **solo el header de metadatos GGUF**
  (magic/version/counts + los pares clave-valor; nunca los tensores de pesos, así que es
  instantáneo incluso en archivos de 9 GB) y devuelve `{n_layer, n_head_kv, head_dim}` leyendo
  `general.architecture` + `{arch}.block_count` + `{arch}.attention.head_count[_kv]` +
  `{arch}.attention.key_length` (o `embedding_length / head_count` si no hay `key_length`).
  `None` si el archivo no es GGUF válido o faltan campos imprescindibles — dispara el fallback.
- `_parse_cmd_flags(cmd: str) -> dict`: tokeniza el `cmd` (ya sin saltos de línea: PyYAML pliega
  el bloque `>` a un solo string al parsear el YAML) y extrae `--model`/`-m`, `--ctx-size`/`-c`,
  `--cache-type-k`, `--cache-type-v`.
- `estimate_model_vram(model_id, model_entry, override_gb=None) -> VramEstimate` (dataclass con
  `gb`, `method` en `{"gguf-metadata","flat-fallback","override","error"}`, `detail` legible):
  - Si hay `override_gb` (viene de `--add-model id=ruta:VRAM_GB`) → se usa tal cual.
  - Si `read_gguf_arch_info` + `--ctx-size` están disponibles → `pesos*1.05 + kv_gib` donde
    `kv_gib = n_layer * n_head_kv * head_dim * ctx * (bytes_k + bytes_v) / 1024**3`, con
    `bytes_k`/`bytes_v` según `--cache-type-k/v` (tabla: f32=4, f16=2 [default], q8_0≈1.0625,
    q4_0≈0.5625, q4_1≈0.625, q5_0≈0.6875, q5_1≈0.75 bytes/elemento).
  - Si no → fallback `pesos_GB * 1.2`, marcado `method="flat-fallback"` para que el reporte de
    `check-llamaswap` diga explícitamente cuándo está confiando en el número fino vs. el bruto.
- `worst_case_vram_gb(groups: dict, estimates: dict[str, VramEstimate]) -> tuple[float, list[dict]]`:
  por cada grupo, `max(miembros)` si `swap` es true, `sum(miembros)` si es false; suma de todos
  los grupos. **Ignora `exclusive` a propósito** (deliberado: `exclusive=true` solo puede REDUCIR
  el pico real al descargar otros grupos, nunca aumentarlo — así que ignorarlo da un límite
  superior seguro, que es lo que quiere un guardrail anti-OOM). Devuelve también el desglose por
  grupo para el reporte legible.
- `load_config(path: Path) -> dict` / `dump_config(data: dict, path: Path)`: wrappers finos sobre
  `yaml.safe_load` / `yaml.safe_dump(..., sort_keys=False, default_flow_style=False)`.
  **Limitación documentada sin rodeos**: PyYAML no preserva comentarios ni el formato original
  (`>` multilinea, etc.) al reescribir. Un `config.yaml` con comentarios (como el real del
  usuario) los PERDERÁ al pasar por `init-llamaswap`. Por eso `init-llamaswap` **siempre** deja
  `.bak` del original antes de escribir — es la red de seguridad, no una promesa de preservar
  formato. Esto se avisa en el `--help` del comando y en la recipe, no se intenta resolver con
  `ruamel.yaml` (dependencia extra no pedida por el plan; mantenerse en `pyyaml` como se acordó).

### F7.2 — CLI `check-llamaswap`

```
local-delegate check-llamaswap --config <path.yaml> --vram-gb <N> [--margin-gb 1.5]
```

- Carga el YAML, exige que tenga `groups:` (si no, error claro: "no hay groups: en este config,
  nada que validar").
- Para cada modelo referenciado en `groups.*.members`, ubica su `.gguf` (regex sobre `cmd`) y
  estima VRAM. Si no puede ubicar el `.gguf` o el archivo no existe → error por ese modelo (no
  aborta el resto, pero el exit code final es de fallo — reporta todos los problemas de una vez).
- Calcula `worst_case_vram_gb`, compara contra `vram-gb - margin-gb`.
- Imprime tabla por grupo (nombre, modo swap/all-together, miembros con su GB estimado,
  contribución del grupo) + línea de total vs budget.
- Exit code `0` si cabe, `1` si no cabe, `2` si el config tiene un error de datos (grupo sin
  miembros válidos, modelo no encontrado, etc.).

### F7.3 — CLI `init-llamaswap`

```
local-delegate init-llamaswap --config <path.yaml> --resident id[,id...] --swap id[,id...]
  --vram-gb <N> [--margin-gb 1.5] [--ttl-resident 600] [--ttl-swap 300]
  [--add-model ID=GGUF_PATH[:VRAM_GB] ...] [--server-exe llama-server]
  [--out <path.yaml>] [--force] [--dry-run]
```

- `--config`: config existente a **aumentar** (no generar desde cero). Si no existe y no hay
  `--add-model`, error — el caso de uso real (y el del ritual F7.5) es partir de un
  `config.yaml` que ya tiene `models:` con sus `cmd` afinados a mano; regenerar `cmd` completos
  desde flags genéricos sería frágil (flags de `llama-server` varían mucho por modelo/hardware).
- `--add-model ID=RUTA[:VRAM_GB]` (repetible): para ids que NO existen ya en `--config`, crea una
  entrada mínima `cmd: "<server-exe> --port ${PORT} --host 127.0.0.1 --model <RUTA> -ngl 99"`.
  Si se da `:VRAM_GB`, se usa ese valor en vez de la estimación por tamaño de archivo (útil si el
  archivo no está descargado todavía o querés forzar un número).
- `--resident` / `--swap`: ids que deben existir ya en `models:` (los propios o los recién
  añadidos con `--add-model`). Se emite:
  ```yaml
  groups:
    resident:
      persistent: true
      swap: false
      exclusive: false
      members: [...--resident...]
    swap:
      swap: true
      exclusive: false
      members: [...--swap...]
  ```
- Fija `ttl: <--ttl-resident>` en cada modelo de `--resident` y `ttl: <--ttl-swap>` en cada
  modelo de `--swap` (solo esa clave; el resto de la entrada del modelo no se toca).
- **Corre el check de F7.2 internamente ANTES de escribir.** Si no cabe → imprime el mismo
  desglose que `check-llamaswap`, exit code `1`, **no escribe nada**. No hay bypass — ese es el
  guardrail anti-OOM que pidió el usuario; si no cabe hay que ajustar `--resident`/`--swap`, no
  forzar la escritura.
- Nunca sobreescribe `--out` (default: mismo que `--config`) sin `--force`; con `--force`, escribe
  primero `<out>.bak` (si `<out>` ya existía) y luego el nuevo contenido.
- `--dry-run`: imprime el YAML resultante a stdout, no toca disco (ni siquiera lee si hace falta
  escribir/backupear).
- Idempotente: misma invocación dos veces con el mismo `--config` de entrada produce el mismo
  YAML de salida (mismo orden de claves — `sort_keys=False` preserva inserción; los grupos se
  regeneran completos cada vez, no se hace merge parcial de `groups:` previos).

### F7.4 — Visibilidad runtime

Ya cubierta (ver Paso 0). Único añadido opcional: si `pyyaml` está instalado Y
`LLAMASWAP_CONFIG` (env ya usada por `autostart.py`) apunta a un archivo con `groups:`,
`local_status` añade una línea `Groups activos: resident, swap` (best-effort, nunca rompe si
falla el parseo). Se hace `try/except ImportError` para no forzar el extra.

### F7.5 — Tests (sin llama-swap real)

`tests/test_llamaswap_config.py` (nuevo):
- Import sin `pyyaml` instalado → `RuntimeError` con el mensaje exacto del extra (se simula
  con `monkeypatch` de `sys.modules['yaml'] = None` o similar, no desinstalando de verdad).
- `estimate_model_vram_gb`: archivo fake de tamaño conocido (crear con `path.write_bytes(...)`
  en `tmp_path`) → GB esperado con el factor 1.2.
- `parse_model_gguf_path`: cmd con `--model`, con `-m`, sin ninguno (→ `None`), multilinea (`>`).
- `worst_case_vram_gb`: 3 escenarios con fixtures YAML en `tests/fixtures/llamaswap/`:
  - `cabe.yaml`: resident+swap, total bajo el budget.
  - `no_cabe.yaml`: total supera el budget.
  - `justo_margen.yaml`: total cae exactamente en el borde del margen (verificar el `<=` vs `<`
    correcto).
- `check-llamaswap` CLI (invocando la función Python directamente, no subprocess): exit codes
  0/1/2 en los 3 escenarios + config sin `groups:`.
- `init-llamaswap`: idempotencia (correr 2 veces → mismo output), `.bak` se crea con `--force`,
  sin `--force` sobre archivo existente → error sin escribir, `--dry-run` no toca disco,
  `--add-model` crea entrada mínima, chequeo de VRAM fallido → no escribe nada.
- `ruff check .` y `uv run pytest` en verde.

### F7.6 — Dispatcher de CLI (server.py / nuevo `cli.py`)

- Nuevo módulo `cli.py` con `run(argv: list[str]) -> int` que parsea `argv[0]` en
  `{"check-llamaswap", "init-llamaswap"}` (usando `argparse` con subparsers) e importa
  `llamaswap_config` solo en ese momento (para no forzar el extra en el arranque MCP normal).
- `server.main()` gana una única línea al principio: si `sys.argv[1:]` no está vacío y matchea
  un subcomando conocido, delega a `cli.run(sys.argv[1:])` y hace `sys.exit(código)` — **antes**
  de tocar `autostart`/`mcp.run()`. Sin argumentos (caso normal de cualquier host MCP), el
  comportamiento actual no cambia ni una línea de ejecución.
- `[project.scripts]` no cambia (mismo entry point `local_delegate:main` para ambos alias).

### F7.7 — Extra opcional + release

- `pyproject.toml`: `[project.optional-dependencies] llamaswap = ["pyyaml>=6"]`.
- `docs/recipes/llama-swap-groups.md`: cuándo conviene (delegaciones frecuentes a modelos
  distintos → evitar cold-load repetido), presupuesto de VRAM con ejemplo real (el del usuario:
  16 GB, resident gemma3-4b ~3 GB, swap llama31-8b ~5 GB / qwen25-coder-14b ~9-10 GB, margen
  ~2 GB), los dos comandos con ejemplos copy-pasteables, el ritual de aplicación paso a paso, y
  advertencia explícita: mal config de groups = OOM o thrashing de VRAM, por eso el paquete
  **nunca** toca `llama-swap` por sí solo — estos comandos solo corren si el usuario los invoca
  a mano.
- Bump `0.4.0` en `pyproject.toml` (F6 ya cerró 0.3.0), entrada en `CHANGELOG.md`, sección nueva
  en `README.md` (extra `[llamaswap]`, los 2 CLIs, link a la recipe), actualizar
  `EXPECTED_TOOLS`/conteo en `test_smoke.py` si aplica (no aplica: esto NO añade tools MCP, son
  CLIs — el conteo de 11 tools no cambia). `uv build` sin errores. **No publicar sin confirmación
  explícita del usuario** (regla ya establecida en el plan maestro).

### F7.8 — Ritual de aplicación personal (aparte, con tu OK explícito en cada paso)

Sigue exactamente lo descrito en `plan-v0.2-mejoras.md` §F7.5: backup del `config.yaml` real →
`init-llamaswap --resident gemma3-4b --swap llama31-8b,qwen25-coder-14b --ttl-resident 600
--ttl-swap 300 --vram-gb 16` → mostrar el desglose de `check-llamaswap` antes de aplicar →
aplicar y reiniciar llama-swap → comandos `nvidia-smi` para verificar reposo (~3 GB) y pico
(~13 GB) → rollback al `.bak` si OOM o >15 GB. `qwen35-2b` se decide en el momento (probablemente
se une al grupo `swap` también, o se deja fuera del catálogo gestionado por groups si no se usa
seguido — a discutir con el desglose de VRAM en mano).

---

## Criterio de aceptación F7

- `uv run pytest` y `uv run ruff check .` en verde con los tests nuevos.
- Sin el extra `[llamaswap]` instalado, el paquete completo (MCP + tools) se comporta
  EXACTAMENTE igual que hoy — ninguna tool ni `local_status` fallan por su ausencia.
- `check-llamaswap` detecta correctamente los 3 escenarios de fixture (cabe/no cabe/justo en el
  margen) con exit codes correctos.
- `init-llamaswap` nunca escribe si el check falla, nunca sobreescribe sin `--force`, siempre dejando `.bak` cuando sobreescribe.
- Checkbox F7 marcado en `plan-v0.2-mejoras.md` al cerrar el paquete (F7.1–F7.7). F7.8 (ritual
  personal) se ejecuta y valida después, con tu OK explícito paso a paso, y no bloquea el cierre
  del paquete en sí.

## F7.9 — Guardrail de RAM de sistema (extensión, iniciativa del usuario durante F7.8)

Durante el ritual de aplicación (F7.8) el usuario notó su RAM de sistema al 93% mientras
verificaba VRAM, y preguntó por la causa: `llama-server` mapea el GGUF también en RAM (mmap)
aunque el cómputo sea 100% GPU (`-ngl` alto) — confirmado en vivo, un GGUF de 8.37 GiB usó
~7.46 GB de RAM residente real. Como el guardrail de F7 solo cubría VRAM, se extendió con el
mismo patrón para RAM, opt-in y retrocompatible:

- `llamaswap_config.py`: `estimate_model_ram()` (pesos del archivo, sin KV — asume offload
  completo a GPU, documentado como límite inferior si `-ngl` es parcial). La aritmética de
  peor caso por grupo se generalizó a `worst_case_gb()` (alias `worst_case_vram_gb` para
  compat) porque VRAM y RAM comparten la misma lógica swap→max / sin-swap→suma: llama-swap
  libera ambos recursos juntos al descargar un modelo (mata el proceso completo).
- `cli.py`: `--ram-gb`/`--ram-margin-gb` opcionales en ambos comandos (default de margen 2.0
  GiB); sin pasarlos, comportamiento idéntico a 0.4.0. `init-llamaswap` no escribe si falla
  VRAM **o** RAM.
- `local_status`: línea best-effort de RAM de sistema (`_ram_info()`, Windows vía `ctypes`
  `GlobalMemoryStatusEx`, Linux vía `/proc/meminfo`, macOS no implementado).
- Verificado en vivo contra el catálogo real: estimación 10.69 GiB vs. ~10.30 GB medidos con
  `Get-Process` (gemma3-4b + qwen25-coder-14b cargados a la vez) — conservador, igual que VRAM.
- Release 0.5.0 (CHANGELOG, README, recipe actualizados, `uv build` OK, 113 tests en verde).

## Checklist

- [x] F7.1 `llamaswap_config.py` (estimador + parser/emisor YAML + import guard)
- [x] F7.2 CLI `check-llamaswap`
- [x] F7.3 CLI `init-llamaswap`
- [x] F7.4 confirmación de visibilidad runtime (ya cubierta; línea de groups activos añadida)
- [x] F7.5 tests (32 tests nuevos en `test_llamaswap_config.py` + 5 en `test_core.py`/`test_smoke.py`)
- [x] F7.6 dispatcher de CLI en `main()` + `cli.py`
- [x] F7.7 extra opcional + doc recipe + bump 0.4.0 + CHANGELOG + README + `uv build`
- [x] F7.8 ritual de aplicación personal — aplicado sobre el config.yaml real, verificado con
  nvidia-smi (peor caso VRAM real 11.69 GiB vs. estimado 12.71 GiB) y TTL auto-unload
  confirmado en vivo (qwen25-coder-14b se descargó solo a los 300s).
- [x] F7.9 guardrail de RAM de sistema (extensión post-F7.8) — 0.5.0

## Discrepancias encontradas durante la ejecución

- **Estimador de VRAM (F7.1):** el plan maestro proponía `file_size * 1.15 + kv_estimate(...)`
  como aproximación "documentada" sin más detalle. Verificado con los GGUF reales del usuario
  que un factor plano único (`*1.2`) subestima hasta 1.4 GiB en el peor caso (contexto grande,
  KV sin cuantizar) — ver discusión en la conversación de la sesión. Se implementó en su lugar
  un parser de header GGUF (arquitectura real: capas, cabezas KV, dimensión de cabeza) que
  calcula el KV cache exacto cuando hay `--ctx-size` en el `cmd`, con el factor plano como
  fallback explícito (marcado como tal, nunca silencioso).
- **Helper de test con archivos "dispersos" (sparse):** el primer intento de simular GGUF de
  varios GiB con `seek()+write()` esperando semántica de archivo disperso **llenó el disco del
  usuario dos veces** (146 GB primero, luego de nuevo antes del segundo intento) — en este
  filesystem (acceso vía la capa POSIX de git-bash/MSYS sobre NTFS) el hueco se materializó
  como bytes reales en vez de quedar disperso. Solución final: mockear `Path.stat()` para la
  ruta puntual del GGUF de test (dejando el header real, pequeño, sin tocar) en vez de escribir
  contenido de tamaño real — cero bytes de más a disco. Ambas limpiezas de disco fueron
  autorizadas explícitamente por el usuario antes de ejecutarse.
