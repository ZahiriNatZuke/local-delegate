# Plan de implementación — local-delegate v0.2 "mejoras"

> **Ejecutor:** Claude Code (Sonnet 5, effort high) en sesión limpia sobre `D:\Projects\local-delegate`.
> **Base:** paquete `local-delegate-mcp` v0.1.1 (Python 3.11+, uv, FastMCP, hatchling). Tests con pytest, lint con ruff, CI en GitHub Actions.
> **Origen:** `Investigacion-mejoras-local-delegate.md` (carpeta del proyecto Cowork) + veredicto de apuntes del usuario (2026-07-09).
> **Alcance global:** el MCP sigue siendo **texto→texto sin tool-calling local** (F6 visión añade imagen→texto, misma filosofía). Nada de routers/gateways que sustituyan la suscripción.

## Reglas para el ejecutor

1. Ejecutar las fases **en orden** (F1→F5 en esta sesión; F6 y F7 son sesiones aparte). Cada fase termina con: tests en verde (`uv run pytest`), `uv run ruff check .`, commit propio (`rtk git add` + `rtk git commit`, Conventional Commits) y checkbox marcado en este archivo.
2. No reformatear código no tocado; no reordenar imports fuera de lo que pida ruff.
3. Compatibilidad hacia atrás: env vars existentes conservan su semántica; `usage.jsonl` viejo debe seguir leyéndose; el dashboard debe tolerar eventos sin los campos nuevos.
4. Si algo del plan contradice el código real, gana el código: anota la discrepancia al final de este archivo y adapta.
5. Al terminar F5: bump a `0.2.0` en `pyproject.toml`, entrada en `CHANGELOG.md`, `uv build` sin errores. NO publicar a PyPI sin confirmación del usuario.

---

## F1 — Fiabilidad del núcleo

**Objetivo:** eliminar los fallos silenciosos (truncados invisibles, errores por dos canales) y loguear datos reales.

### F1.1 `_env_float` (config.py)
Crear `_env_float(name, default)` con el mismo patrón try/except de `_env_int`; usarlo en `HTTP_TIMEOUT`. Test: env `LOCAL_DELEGATE_TIMEOUT=abc` → 180.0, no excepción.

### F1.2 Resultado estructurado de `_post_chat` (server.py)
Reemplazar el retorno `str` por un dataclass:

```python
@dataclass
class ChatResult:
    text: str
    ok: bool
    error: str | None = None          # mensaje corto cuando ok=False
    finish_reason: str | None = None  # choices[0].finish_reason
    tokens_in: int | None = None      # usage.prompt_tokens si el backend lo da
    tokens_out: int | None = None     # usage.completion_tokens
```

`_post_chat` extrae `finish_reason` y `usage` de la respuesta (ambos pueden faltar → None). Los caminos de error devuelven `ChatResult(text="[local-delegate error] …", ok=False, error=...)` — el texto visible se mantiene idéntico al actual, pero `ok` ya no se deduce por sniffing de prefijo.

### F1.3 `_chat` usa el struct y avisa de truncado de salida
- Si `result.finish_reason == "length"`: anexar al texto `\n\n[local-delegate aviso: salida truncada por max_tokens]`.
- `_log_event` recibe los campos nuevos (F1.6).
- La firma pública de las tools no cambia (siguen devolviendo `str`).

### F1.4 Truncado de entrada visible (server.py)
`_read_input` pasa a devolver `tuple[str, bool, int]` → `(content, truncated, raw_len)`. Cada tool que la usa, cuando `truncated=True`, antepone al resultado final:
`[local-delegate: entrada truncada — procesados {len(content)} de {raw_len} chars]\n`.
Actualizar los call-sites (summarize, extract, lint_summary, commit_msg, translate, explain_code).

### F1.5 `_strip_think` (server.py)
Nueva helper que elimina bloques `<think>...</think>` y `<thinking>...</thinking>` (case-insensitive, DOTALL, también el caso "bloque sin cerrar al inicio"). Aplicarla en `_chat` sobre `result.text` ANTES de `_strip_fences` en las tools que lo usan. Protege contra modelos razonadores (Qwen3, R1-distill).

### F1.6 Log enriquecido (server.py `_log_event`)
Campos nuevos (todos opcionales, no romper lectores viejos): `tokens_in`, `tokens_out` (reales del backend; si None, el dashboard estima con chars/4), `error` (solo si ok=False), `finish_reason`, `truncated_in`, `truncated_out`, `raw_len`, `path` (ruta cuando source=path), `v` (versión del paquete vía `importlib.metadata.version`, cacheada a nivel de módulo).

### F1.7 Enrutado consistente en `local_extract`
Aplicar el mismo patrón probe/raw_len de `local_summarize`: si la entrada supera `LONG_INPUT_CHARS` → `MODEL_LONG` con su max_chars (48k). Documentar en la docstring que el probe usa bytes para `path` y chars para `text` (~5-10% de diferencia en UTF-8, aceptable).

### F1.8 Validación de `style` en `local_commit_msg`
Si `style not in {"conventional", "plain"}` → devolver error claro en vez de caer a "plain" en silencio.

### F1.9 Cliente httpx module-level
Un `httpx.Client(timeout=config.HTTP_TIMEOUT)` a nivel de módulo con lazy-init (keep-alive entre delegaciones). `httpx.Client` es thread-safe para requests concurrentes (FastMCP puede ejecutar tools sync en threadpool). Mantener el manejo de excepciones actual.

### F1.10 Tests de F1 (tests/test_core.py nuevo)
Con `monkeypatch`/`respx` (añadir `respx` al dependency-group dev):
- `_env_float` malformada → default.
- `_read_input`: text corto, path inexistente (ValueError), truncado (truncated=True, raw_len correcto), precedencia path>text.
- `_strip_think`: con/sin bloque, sin cerrar, anidado en texto.
- `_strip_fences`: fence simple, con lenguaje, sin fence.
- `_post_chat` con respx: 200 OK con usage y finish_reason=length; 500; ConnectError sin autostart; respuesta sin `usage` (tokens None).
- Enrutado de `local_extract` largo → MODEL_LONG (monkeypatch de `_chat` capturando el modelo).

**Criterio de aceptación F1:** todo con tests; salida truncada por max_tokens produce aviso visible; `usage.jsonl` nuevo contiene tokens reales en llamada real (verificación manual post-sesión con backend arriba).

---

## F2 — `local_status` + JSON garantizado

### F2.1 Tool `local_status()` (server.py)
Solo lectura. Devuelve texto compacto (no JSON crudo gigante) con:
- Backend: `config.BASE_URL`, ¿responde `/models`? (timeout 2s), lista de ids que expone.
- Catálogo de roles activo (mechanical/long/code/fast → id, max_chars).
- Log: ruta, nº de eventos del archivo del mes actual, tokens de contexto ahorrados acumulados (suma rápida de `source=path`).
- Versión del paquete y si la web de métricas está sirviendo (puerto).
- (F7 adelantado, best-effort) VRAM libre/total vía `nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader` si el binario existe; y modelo montado vía GET `{base sin /v1}/running` de llama-swap (timeout 1s, tolerar fallo).
Docstring: "Úsala para saber qué modelos locales hay disponibles y verificar que el backend está vivo antes de delegar en masa, o para diagnosticar por qué una tool local_* falló."
Actualizar `EXPECTED_TOOLS` en test_smoke (pasa a 10 tools).

### F2.2 `response_format` json_schema en `local_extract`
- Env nueva: `LOCAL_DELEGATE_JSON_SCHEMA` = `auto` (default) | `on` | `off`.
- En `auto`/`on`: el payload incluye `response_format: {"type": "json_object", "schema": {"type":"object", "properties": {campo: {} …}, "required": [campos]}}` (formato aceptado por llama-server; **verificar contra la doc actual de llama.cpp al implementar** — el formato `json_schema` anidado también existe).
- Si el backend responde 400 (no soporta) y estamos en `auto`: reintentar UNA vez sin `response_format` y loguear `json_schema:"fallback"` en el evento. En `on`: propagar el error.
- El system prompt SIGUE nombrando las claves (el schema solo restringe, no informa al modelo).
- Test respx: payload contiene response_format; 400 → fallback.

**Criterio F2:** `local_status` responde con backend caído (dice que está caído) y con backend arriba; `local_extract` devuelve JSON parseable con `json.loads` en llamada real.

---

## F3 — Awareness (que Claude delegue más, sin forzar)

### F3.1 Docstrings que compiten contra Read (server.py)
Reescribir las docstrings de las 6 tools que aceptan `path` añadiendo una línea de decisión explícita al inicio, patrón:
> "PREFIERE esta tool en vez de leer el archivo con Read cuando el archivo es grande (>200 líneas / >10 KB) y solo necesitas [resumen/campos/explicación], no el contenido literal."
Y en `local_lint_summary`: "Si ejecutaste un comando cuya salida es larga, vuélcala a un archivo y pasa `path`."

### F3.2 Línea de feedback de ahorro (server.py `_chat`)
Cuando `source=="path"` y `ok`: anexar `\n\n(leído server-side: {chars_in:,} chars ≈ {tokens:,} tokens que no entraron a tu contexto)` usando tokens reales si existen, estimación si no. Env `LOCAL_DELEGATE_FEEDBACK=1` default on, `0` la apaga.

### F3.3 CLAUDE.md global (`~/.claude/CLAUDE.md`) — backup antes de editar
- Mover la sección "Delegación a modelos locales" ARRIBA del bloque RTK.
- Conectar los dos sistemas: "Si un comando produce salida larga y rtk no tiene filtro para él → vuelca a fichero y usa `local_lint_summary(path=...)`."
- Comprimir el bloque RTK: conservar Golden Rule + tabla-resumen final, eliminar las secciones intermedias de ejemplos por categoría (~80 líneas menos). Mantener los marcadores `<!-- rtk-instructions v2 -->` … `<!-- /rtk-instructions -->` envolviendo el bloque comprimido.

### F3.4 Skill `delegacion-local` (`~/.claude/skills/delegacion-local/SKILL.md`)
- Catálogo completo: las 9 tools actuales + `local_status` (10).
- Eliminar ids de modelos hardcodeados; decir "consulta `local_status` para ver el catálogo activo".
- Description (frontmatter): añadir triggers "mensaje de commit desde un diff", "traducir texto o archivo", "resumir salida de lint/tests/CI", "explicar código", "verificar si el backend local está disponible".
- Añadir sección corta "El coste de no delegar": leer un archivo de 100 KB con Read ≈ 25k tokens de contexto; `local_summarize(path)` ≈ 200.

### F3.5 Permisos pre-aprobados (`~/.claude/settings.json`)
Añadir a `permissions.allow`: `"mcp__local-delegate__*"`. Leer el JSON existente, mergear sin pisar otras keys. Backup previo.

### F3.6 Recipe de hooks (`docs/recipes/claude-code-hooks.md` + `docs/recipes/hooks/`)
Nueva recipe con dos hooks (scripts Python sin dependencias, multiplataforma) y su bloque para `settings.json`:
- **PreToolUse matcher Read** (`suggest_delegate_read.py`): lee el JSON del hook por stdin; si `tool_input.file_path` existe y pesa > `LD_HOOK_READ_KB` (default 50 KB), emite additionalContext: "Este archivo pesa X KB. Si solo necesitas resumen/campos, local_summarize(path=...) o local_extract(path=...) lo procesan sin gastar tu contexto." NUNCA bloquea (no forzar; permissionDecision allow).
- **PostToolUse matcher Bash** (`suggest_lint_summary.py`): si el stdout del comando supera N líneas (default 120) y el comando matchea `lint|test|tsc|build|pytest|clippy|biome`, additionalContext sugiriendo `local_lint_summary`.
- **Verificar el formato exacto del JSON de hooks contra la doc oficial** (https://code.claude.com/docs/en/hooks) al implementar. Los hooks son opt-in: la recipe los documenta para cualquier usuario; en ESTA máquina, instalarlos en `~/.claude/settings.json` (con backup).

### F3.7 `update_agents.py` v2 (docs/recipes/update_agents.py)
Además de la línea `tools:`, mantener en cada agente delegador un bloque de prosa delimitado
`<!-- local-delegate:catalog:begin -->` … `<!-- local-delegate:catalog:end -->` con el catálogo resumido de las 10 tools y la regla de oro. Idempotente: si los marcadores existen, reemplaza el contenido; si no, inserta tras la sección de delegación existente. Probar `--dry` primero; luego aplicar sobre `~/.claude/agents/`.

**Criterio F3:** skill y CLAUDE.md coherentes entre sí; hooks instalados y probados manualmente (Read de archivo grande → aparece la sugerencia); agentes regenerados con `--dry` limpio antes de aplicar.

---

## F4 — Log por rango + rotación + dashboard con inflight

### F4.1 Rotación mensual (server.py)
- `_log_event` escribe SIEMPRE en `usage-YYYYMM.jsonl` (mes UTC actual) dentro del dir de logs. Compat: si el usuario definió `LOCAL_DELEGATE_LOG` (archivo), usar ese archivo tal cual SIN rotación; nueva `LOCAL_DELEGATE_LOG_DIR` para el modo rotado (default: dir de datos de usuario).
- El `usage.jsonl` legado NO se migra: se lee como fuente adicional (F4.2).

### F4.2 Loader por rango (web/metrics.py) — apunte del usuario integrado
- `_log_files()` → lista `[(path, ym|None)]`: todos los `usage-*.jsonl` + `usage.jsonl` legado (ym=None = siempre candidato).
- `_load(range_from, range_to)` abre SOLO los archivos cuyo mes interseca `[from, to]` (los ym=None siempre) y filtra eventos por `ts`. **La selección de archivos la dirige el rango pedido por la UI — nada de "últimos N fijos".**
- Cache en memoria `{path: (mtime, size, rows)}`; releer solo si mtime/size cambió (solo el archivo del mes actual cambia).
- `/api/events?from=ISO&to=ISO` y `/api/stats` igual (sin params → últimos 30 días). `meta.files_read` para auditar desde la UI.

### F4.3 UI: selector de rango (HTML embebido en metrics.py)
Presets (Hoy, 7d, 30d, Mes anterior, Todo) + inputs date. Cambiar rango → refetch con from/to. Los filtros tool/modelo siguen client-side dentro del rango cargado. Mostrar `files_read` y total de eventos en el pie.

### F4.4 Inflight — visibilidad de delegaciones en curso (apunte del usuario)
- server.py: registro global `_INFLIGHT: dict[int, dict]` (id → {tool, model, source, chars_in, started_at}) con `threading.Lock`; `_chat` registra al empezar y limpia en try/finally.
- web/metrics.py: `GET /api/inflight` → lista con `elapsed_s`. `GET /api/backend` → proxy best-effort de `{base sin /v1}/running` de llama-swap (timeout 1s; si falla `{"available": false}`).
- UI: tarjeta "En curso" con polling cada 2s (solo pestaña visible): tool, modelo, segundos, modelo montado en llama-swap. Documentar en la wiki la limitación: solo se ven las llamadas en vuelo del proceso que sirve la web.

### F4.5 Tests F4
- Rotación: monkeypatch de fecha → nombre correcto; env legacy → sin rotación.
- `_log_files`+`_load` con dir temporal de 3 meses → rango de 1 mes abre solo los archivos que tocan (`files_read` correcto).
- Inflight: `_post_chat` mockeado lento en thread → `/api/inflight` la lista; al terminar, vacío (TestClient de FastAPI).

**Criterio F4:** el dashboard filtra por rango releyendo solo los archivos necesarios; delegación larga visible en "En curso"; el log del mes se crea solo.

---

## F5 — Seguridad + concurrencia + release

### F5.1 `LOCAL_DELEGATE_ALLOWED_DIRS`
Env opcional, lista separada por `;` de raíces permitidas para `path` en todas las tools. Vacía/ausente = sin restricción (default actual, documentado). Validación en `_read_input` con `Path.resolve()` + `is_relative_to`. Error claro que incluye las raíces permitidas. Tests: dentro, fuera, resolve de rutas relativas.

### F5.2 Lock de escritura del log
Dependencia `filelock>=3`: en `_log_event`, `FileLock(str(logfile)+".lock", timeout=1)` alrededor del append. Timeout → escribir sin lock (best-effort, jamás romper la tool). Cubre Desktop + Code escribiendo a la vez.

### F5.3 Release 0.2.0
- `pyproject.toml` → 0.2.0; CHANGELOG (Added/Changed/Fixed mapeando F1–F5).
- README: tabla de 10 tools, env vars nuevas (`LOCAL_DELEGATE_JSON_SCHEMA`, `_FEEDBACK`, `_LOG_DIR`, `_ALLOWED_DIRS`), sección "Alcance / no-objetivos" (texto→texto deliberado; tool-calling local = no-objetivo; audio → companion `whisper-transcribe-mcp`), enlace a la recipe de hooks.
- Wiki: Savings-and-metrics (tokens reales, rango, inflight) y Configuration.
- `uv build` OK. Publicación a PyPI: **preguntar al usuario**.

**Criterio F5:** suite completa verde, ruff limpio, CHANGELOG y docs coherentes, build OK.

---

## F6 — Visión local (sesión aparte, tras validar v0.2)

- Rol `MODEL_VISION` (`LOCAL_DELEGATE_MODEL_VISION`, default `qwen3-vl-8b`) + `MAX_IMAGE_MB` (default 8).
- Tool `local_describe_image(path, question?, max_words=200)`: lee la imagen server-side, base64 → `content: [{type:"text",…},{type:"image_url", image_url:{url:"data:image/png;base64,…"}}]`. `source="path"` siempre; `chars_in` = bytes del archivo; ahorro real = `usage.prompt_tokens` del backend (tokens de imagen que no entraron al contexto de Claude).
- Recipe llama-swap: entrada con `--mmproj`; candidatos Qwen3-VL 8B (~6 GB Q4) y MiniCPM-V 4.5 (~5-6 GB). Multimodal en llama.cpp sigue experimental — fijar en la recipe la versión de llama-server probada.
- Guardrail de scope: imagen→texto solamente; nada de generación de imágenes.

## F7 — Groups de llama-swap COMO CAPACIDAD DEL PAQUETE (sesión aparte, opt-in, desactivado por defecto)

> Decisión del usuario (2026-07-09): en vez de ser solo un cambio de config personal, el soporte
> de groups vive en el paquete para que cualquier usuario lo tenga disponible. Matiz técnico:
> los groups se definen en el `config.yaml` de llama-swap (server-side); un cliente NO puede
> activarlos por API. Lo que el paquete SÍ puede hacer: generar y validar ese config con
> presupuesto de VRAM, y dar visibilidad runtime para operarlo sin sustos.

### F7.1 Módulo `llamaswap_config.py` (nuevo, opcional como `autostart.py`)
- Estimador de VRAM por modelo GGUF: tamaño del archivo + overhead de contexto (aprox. documentada: `file_size * 1.15 + kv_estimate(ctx, n_layers?)`; si no hay metadatos, usar `file_size * 1.2` y marcarlo como estimación gruesa). Nunca pretender precisión: es un guardrail, no un simulador.
- Parser/emisor YAML del config de llama-swap (dependencia `pyyaml` en extra opcional `[llamaswap]` → `pip install local-delegate-mcp[llamaswap]`).

### F7.2 CLI `local-delegate check-llamaswap --config <path> --vram-gb <N>`
Valida un config existente: suma el peor caso de VRAM por combinación de grupos residentes + el mayor modelo swappeable; avisa (exit code ≠ 0) si supera `--vram-gb` menos un margen de seguridad configurable (default 1.5 GB reservado al sistema). Reporta tabla por grupo. **Este es el guardrail anti-OOM que pidió el usuario.**

### F7.3 CLI `local-delegate init-llamaswap`
Generador de `config.yaml` con groups a partir de flags (`--models "id=path.gguf,vram=3"...` o un YAML de inventario), `--resident <ids>`, `--ttl-resident/--ttl-swap`, macros para rutas/flags repetidos. Corre `check-llamaswap` internamente antes de escribir; nunca sobreescribe sin `--force` (y con `--force` deja `.bak`).
**Verificar primero la semántica de la versión instalada** (`groups`, `swap`, `exclusive`, `persistent`, `globalTTL`) contra la doc del tag correspondiente de llama-swap; el generador emite config para esa semántica y la anota en un comentario del YAML.

### F7.4 Visibilidad runtime
Ya cubierta por F2.1/F4.4 (`local_status` con VRAM vía nvidia-smi + `/api/backend` con `/running`). Añadir a `local_status` una línea de advertencia si VRAM libre < 2 GB.

### F7.5 Aplicación personal (el ritual de validación sigue siendo manual)
1. Backup del `config.yaml` actual de `D:\Projects\llms\llama-swap`.
2. Generar con `init-llamaswap`: residente inicial = SOLO `gemma3-4b` (~3 GB); swap: `llama31-8b` (~5 GB), `qwen25-coder-14b` (~9-10 GB con KV). Peak esperado residente+coder ≈ 13 de 16 GB → margen ~2 GB tras reserva del sistema.
3. Probar: cargar residente → `nvidia-smi` (anotar) → forzar delegación de código → `nvidia-smi` en el pico → si OOM o >15 GB, rollback al backup.
4. Ajustar `ttl` (600s residente, 300s swap) y comprobar auto-unload.
5. Beneficio esperado: eliminar el cold-load (~4.5 s observados) de las delegaciones mecánicas.

### Doc
`docs/recipes/llama-swap-groups.md`: cuándo conviene, presupuesto VRAM, los dos comandos, el ritual de validación, y advertencia explícita de que un mal config puede provocar OOM/thrashing de VRAM — por eso el default del paquete es NO tocar nada (los comandos solo corren si el usuario los invoca).

---

## Checklist de fases (marcar al completar)

- [x] F1 Fiabilidad del núcleo
- [x] F2 local_status + json_schema
- [x] F3 Awareness (docstrings, feedback, CLAUDE.md, skill, permisos, hooks, agentes) — hooks: recipe+scripts listos, instalación en settings.json pendiente (ver Discrepancias)
- [x] F4 Log por rango + rotación + inflight
- [x] F5 Seguridad + lock + release 0.2.0
- [x] (aparte) F6 Visión — Qwen3-VL-8B Q4_K_M + mmproj Q8_0, tool `local_describe_image`,
  0.3.0. Ver detalle en `plan-f6-vision.md`.
- [x] (aparte) F7 Groups llama-swap en el paquete — CLIs `check-llamaswap`/`init-llamaswap`,
  extra opcional `[llamaswap]`, 0.4.0. Ritual de aplicación personal (F7.8) ejecutado y
  verificado en vivo contra el config.yaml real (VRAM y TTL auto-unload confirmados).
  Extensión F7.9: guardrail de RAM de sistema (`--ram-gb`), 0.5.0. Ver detalle en
  `plan-f7-groups.md`.

## Discrepancias encontradas durante la ejecución

- **F3.6 — hooks no instalados en `~/.claude/settings.json` automáticamente.** El
  clasificador de auto-mode del harness bloqueó la edición que añadía el bloque
  `"hooks"` (PreToolUse/Read + PostToolUse/Bash) por ser una auto-modificación
  "standing" (ejecuta scripts en cada Read/Bash futuro) no autorizada explícitamente.
  Los scripts (`docs/recipes/hooks/*.py`), la recipe (`docs/recipes/claude-code-hooks.md`)
  y las copias en `~/.claude/hooks/` SÍ se crearon y se probaron manualmente (stdin JSON
  simulado). Falta el paso final: pegar el bloque `"hooks"` del recipe en
  `C:\Users\Yohan\.claude\settings.json` — pendiente de que el usuario lo apruebe/haga
  él mismo. El permiso `mcp__local-delegate__*` (F3.5) sí se aplicó sin bloqueo.
