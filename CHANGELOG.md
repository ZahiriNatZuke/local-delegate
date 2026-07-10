# Changelog

Todos los cambios notables de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y el proyecto usa [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

## [0.6.0] - 2026-07-10

### Added
- Dashboard: endpoint `GET /api/status` (versión del MCP en ejecución, modelos que el backend
  expone de verdad vía `/v1/models` — antes la web solo enseñaba modelos con eventos en el
  log —, catálogo de roles y lista de tools MCP) y `GET /api/system` (RAM y VRAM de sistema
  con uso/total/% + consumo por proceso de los servicios de debajo del MCP: llama-swap,
  llama-server, ollama…, y el propio proceso MCP). Nuevo módulo `web/sysinfo.py`, todo
  best-effort y de solo lectura; la VRAM por proceso en Windows (WDDM) sale de los perf
  counters `GPU Process Memory` muestreados en un hilo de fondo con TTL, porque `nvidia-smi
  --query-compute-apps` no la reporta en ese modo.
- Dashboard: panel «Backend local» (estado del endpoint, los modelos disponibles con su rol
  del catálogo y su estado montado/frío en llama-swap, delegaciones en curso, tools MCP) y
  panel «Sistema» (barras de RAM/VRAM con umbrales de color, utilización de GPU y tabla de
  procesos). Versión del MCP visible en el header.

### Changed
- Dashboard: rango temporal por defecto ahora es **Hoy** (antes: últimos 30 días); la tabla
  de actividad reciente se pagina de 10 en 10 (antes: primeras 30 filas fijas); la
  explicación de «¿cómo se calcula el ahorro?» pasa de un `<details>` al pie a un diálogo
  modal accesible desde el icono «?» del header.
- Dashboard: iconografía rehecha en SVG — botones del header sin glifos de texto ↻/⟳/◐,
  iconos de KPI nuevos (escudo, rayo, chip, gauge) y el icono de información pasa de un
  círculo CSS con letra a un SVG nítido; marca/favicon rediseñados para leerse bien a 16px
  (cuerpo del chip al ~62% del viewBox, solo 2 pines gruesos por lado y doble chevrón » de
  delegación en el núcleo).

### Removed
- Dashboard: filas de chips de filtro Tools/Modelos — redundantes con el panel «Backend
  local» (que ya lista modelos y tools reales) y con el rango temporal server-side; los
  agregados vuelven a computarse sobre todos los eventos del rango.
- README: la imagen del demo apunta por URL absoluta a `raw.githubusercontent.com`, de modo
  que también se renderiza en la página del paquete en PyPI (los links relativos solo
  funcionan dentro de GitHub); captura regenerada con el dashboard nuevo.

## [0.5.0] - 2026-07-09

### Added
- Guardrail de **RAM de sistema** (F7.9), además del de VRAM: `check-llamaswap` e
  `init-llamaswap` ganan flags opcionales `--ram-gb`/`--ram-margin-gb` (default de margen 2.0
  GiB); si no se pasan, el comportamiento es idéntico al de 0.4.0 (compatibilidad hacia
  atrás). Motivo: verificado en vivo durante la aplicación del ritual F7.8 que `llama-server`
  mapea el GGUF también en RAM del sistema (mmap) aunque el cómputo sea 100% GPU — un
  catálogo que cabe holgado en VRAM puede igual agotar la RAM y afectar otras ejecuciones del
  MCP en máquinas con menos de 32 GB. Nuevo `estimate_model_ram()` en `llamaswap_config.py`
  (pesos del GGUF, sin KV — asume offload completo a GPU; documentado como límite inferior si
  el `-ngl` es parcial); la aritmética de peor caso por grupo se generalizó
  (`worst_case_gb()`, con `worst_case_vram_gb` como alias retrocompatible) porque es idéntica
  para VRAM y RAM (llama-swap libera ambos recursos juntos al descargar un modelo).
- `local_status` añade una línea best-effort de RAM de sistema (Windows vía `ctypes`
  `GlobalMemoryStatusEx`, Linux vía `/proc/meminfo`; macOS no implementado, nunca rompe la
  tool). Verificado en vivo: con `qwen25-coder-14b` + `gemma3-4b` cargados a la vez, el
  estimador dio 10.69 GiB de RAM peor-caso vs. ~10.30 GB medidos con `Get-Process` — conforme
  al mismo margen conservador que ya tenía el estimador de VRAM.

## [0.4.0] - 2026-07-09

### Added
- Dos CLIs opt-in (F7): `local-delegate check-llamaswap --config <path> --vram-gb <N>` valida
  el peor caso de VRAM de los `groups` de un config.yaml de llama-swap contra un presupuesto
  con margen de seguridad; `local-delegate init-llamaswap` genera/actualiza `groups` (patrón
  residente + swap) sobre un config existente, corriendo el mismo guardrail internamente antes
  de escribir (nunca escribe si no cabe, nunca sobreescribe sin `--force`, siempre deja `.bak`).
  Requieren el extra opcional `[llamaswap]` (`pip install "local-delegate-mcp[llamaswap]"`,
  dependencia `pyyaml`); sin el extra, el resto del paquete se comporta exactamente igual que
  antes. El paquete nunca toca `config.yaml` de llama-swap por su cuenta — estos comandos son
  100% opt-in.
- Módulo `llamaswap_config.py`: estimador de VRAM por modelo GGUF con dos vías. Cuando el GGUF
  trae metadatos de arquitectura (capas, cabezas KV, dimensión de cabeza) y el `cmd` del modelo
  tiene `--ctx-size` explícito, calcula pesos + KV cache real (respeta `--cache-type-k/v`); si
  falta cualquiera de las dos cosas, cae a una estimación gruesa documentada
  (`tamaño_archivo * 1.2`). Verificado contra los GGUF reales del catálogo de referencia: el
  factor plano por sí solo subestimaba hasta 1.4 GiB en el caso de contexto grande sin
  cuantizar el KV cache — de ahí la vía fina con parser de header GGUF.
- `local_status` añade una línea best-effort con los `groups` activos en `LLAMASWAP_CONFIG`
  (solo si el extra `[llamaswap]` está instalado y el archivo existe; nunca rompe la tool).
- Recipe `docs/recipes/llama-swap-groups.md`: semántica de `groups` verificada contra el
  código real de llama-swap (v235/c59816b), presupuesto de VRAM con ejemplo real, los dos
  comandos, ritual de aplicación, y por qué el paquete no toca `config.yaml` solo.

## [0.3.0] - 2026-07-09

### Added
- Nueva tool `local_describe_image(path, question=None, max_words=200)` (F6): describe una
  imagen o responde una pregunta sobre ella con un modelo local de visión. La imagen se lee
  server-side (respeta `LOCAL_DELEGATE_ALLOWED_DIRS`), valida extensión
  (png/jpg/jpeg/webp/gif) y tamaño (`LOCAL_DELEGATE_MAX_IMAGE_MB`, default 8) antes de leerla
  completa. 11 tools en total. Guardrail de alcance: solo imagen→texto, nunca genera ni edita
  imágenes.
- Rol de modelo `LOCAL_DELEGATE_MODEL_VISION` (default `qwen3-vl-8b`), fuera de
  `ALLOWED_MODELS` (ese set es solo para el escape genérico `local_delegate`, texto→texto).
- `_chat` acepta `content` multimodal (lista de bloques `text`/`image_url` OpenAI-compatible)
  además de `str`, sin duplicar el manejo de inflight/log/feedback.
- `local_status` muestra el rol `vision` en el catálogo.
- Recipe `docs/recipes/llama-swap-vision.md`: entrada de `config.yaml` con `--mmproj`
  (Qwen3-VL-8B-Instruct Q4_K_M + mmproj Q8_0, ~5.78 GB), versión de `llama-server` probada
  pineada (9743/c57607016) con advertencia de multimodal experimental, y MiniCPM-V-4.5 como
  alternativa documentada.

## [0.2.1] - 2026-07-09

### Fixed
- `local_extract`: el schema de `response_format` restringe cada propiedad a tipos
  primitivos (`string`/`number`/`boolean`/`null`) en vez de un sub-schema vacío. Con el
  sub-schema vacío, algunos modelos (verificado con `gemma3-4b`) anidaban el valor en
  vez de devolverlo plano — `{"campo": {"valor": "x"}}` en lugar de `{"campo": "x"}`.
  Encontrado verificando la 0.2.0 en producción contra el backend real.

## [0.2.0] - 2026-07-09

### Added
- Nueva tool `local_status` (solo lectura): estado del backend (`/models`), catálogo de
  roles activo con `max_chars`, stats del log del mes actual, estado de la web de
  métricas, y VRAM (`nvidia-smi`) + modelo montado en llama-swap (`/running`) best-effort.
  10 tools en total.
- `local_extract` pide `response_format` con JSON schema por defecto
  (`LOCAL_DELEGATE_JSON_SCHEMA=auto|on|off`); si el backend responde 400 en modo `auto`,
  reintenta una vez sin schema.
- Feedback de ahorro: `_chat` anexa "leído server-side: N chars ≈ M tokens que no
  entraron a tu contexto" cuando `source=path` (apagable con `LOCAL_DELEGATE_FEEDBACK=0`).
- Log rotado por mes (`usage-YYYYMM.jsonl` en `LOCAL_DELEGATE_LOG_DIR`); el `usage.jsonl`
  legado se sigue leyendo como fuente adicional, sin migrarlo.
- Dashboard: selector de rango real (Hoy/7d/30d/mes anterior/todo/personalizado) que
  refetch server-side (`GET /api/events?from=&to=`, `GET /api/stats?from=&to=`) en vez de
  filtrar client-side; solo abre los archivos de log que tocan el rango pedido.
- Visibilidad de delegaciones en curso: `GET /api/inflight` y `GET /api/backend` (proxy de
  `/running` de llama-swap), con una tarjeta "En curso" en el dashboard.
- `LOCAL_DELEGATE_ALLOWED_DIRS`: restringe opcionalmente el parámetro `path` de todas las
  tools a una lista de raíces permitidas (`;` como separador). Vacío = sin restricción.
- Docstrings de las tools que aceptan `path` indican explícitamente cuándo preferirlas
  sobre leer el archivo con `Read`.
- Recipe de hooks de Claude Code (`docs/recipes/claude-code-hooks.md` +
  `docs/recipes/hooks/`) que sugieren delegar sin bloquear nunca la tool original.
- `update_agents.py` v2: mantiene un bloque de catálogo en prosa en los agentes que
  delegan, además de la línea `tools:`.

### Changed
- `_post_chat` devuelve un `ChatResult` estructurado (`ok`, `error`, `finish_reason`,
  `tokens_in`, `tokens_out`) en vez de codificar el error en el propio texto; el log de
  uso ahora registra tokens reales del backend cuando están disponibles, `finish_reason`,
  `error`, truncados y la versión del paquete.
- Cliente `httpx` module-level con keep-alive entre delegaciones.
- Escritura del log protegida con `filelock` (best-effort: si no consigue el lock en 1s,
  escribe igual, nunca bloquea la tool).

### Fixed
- Salida truncada por `max_tokens` ahora produce un aviso visible en el texto devuelto
  (antes se truncaba en silencio); igual para la entrada truncada al leer un `path`.
- Bloques `<think>`/`<thinking>` de modelos razonadores (Qwen3, R1-distill) se eliminan
  de la salida antes de devolverla.
- `local_commit_msg` valida `style` en vez de caer a `'plain'` en silencio si el valor no
  es reconocido.
- `local_extract` enruta por tamaño de entrada (mecánico/largo) igual que las demás tools
  con `path`, en vez de usar siempre el modelo mecánico.

## [0.1.1] - 2026-07-08

### Fixed
- Dashboard: el sparkline del KPI "Contexto conservado" ya no dibuja una línea sobre el texto
  cuando el ahorro es 0; ahora se ancla al borde inferior (`y.min=0`).

### Added
- Recipes de backends en `docs/recipes/`: llama-swap (RTX 5060 Ti Blackwell) y Ollama.
- Sección *Demo* en el README con screenshot del dashboard de ahorro.
- Wiki en `docs/wiki/` (+ wiki nativa de GitHub): Architecture, Configuration, Savings & metrics, Publishing, Troubleshooting.

### Changed
- `publish.yml`: `uv publish --check-url` para hacer la publicación idempotente ante
  re-ejecuciones sobre un tag existente.

## [0.1.0] - 2026-07-07

### Added
- Servidor MCP stdio con 9 tools texto→texto (`local_summarize`, `local_classify`,
  `local_extract`, `local_boilerplate`, `local_delegate`, `local_lint_summary`,
  `local_commit_msg`, `local_translate`, `local_explain_code`).
- Cliente genérico de cualquier endpoint OpenAI-compatible (llama-swap, Ollama, LM Studio, vLLM),
  configurable por variables de entorno; sin rutas hardcodeadas (`platformdirs` para el log).
- Web de métricas embebida (dashboard de uso/ahorro) en un hilo daemon.
- Logging JSONL por llamada (`usage.jsonl`) para calcular el ahorro de contexto.
- Auto-arranque de llama-swap opcional (opt-in, `LOCAL_DELEGATE_AUTOSTART=0` por defecto).
- Empaquetado para PyPI (`local-delegate-mcp`) ejecutable con `uvx`; `server.json` para el
  registro oficial de MCP.

[Unreleased]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/ZahiriNatZuke/local-delegate/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/ZahiriNatZuke/local-delegate/releases/tag/v0.1.0
