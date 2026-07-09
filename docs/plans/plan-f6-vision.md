# Plan F6 — Visión local (imagen→texto)

> Sesión aparte tras validar v0.2 en producción (ver checklist F1-F5 en
> `plan-v0.2-mejoras.md`). Alcance: SOLO F6. F7 (groups de llama-swap) no se toca aquí.

## Paso 0 — Verificación contra el entorno real (hecha antes de escribir este plan)

- **llama-server instalado:** `D:\Projects\llms\llamacpp\llama-server.exe`, `version: 9743
  (c57607016)`, build CUDA con Clang 20.1.8. El directorio incluye binarios `llama-mtmd-cli.exe`,
  `llama-minicpmv-cli.exe`, `llama-qwen2vl-cli.exe`, `llama-gemma3-cli.exe` → build con soporte
  multimodal completo (libmtmd).
- **Flag `--mmproj`:** confirmado en `llama-server --help` (`-mm, --mmproj FILE`, env
  `LLAMA_ARG_MMPROJ`), junto con `--mmproj-offload`/`--no-mmproj-offload` y
  `--image-min-tokens`/`--image-max-tokens`. El formato OpenAI-compatible de `content` como
  array (`[{"type":"text",...},{"type":"image_url","image_url":{"url":"data:...;base64,..."}}]`)
  es el estándar que expone `llama-server` en `/chat/completions`; no tiene flag propio, es
  automático en cuanto el modelo tiene mmproj cargado.
- **Soporte de arquitectura Qwen3-VL:** mergeado en `ggml-org/llama.cpp` PR #16780 (30-oct-2025,
  `LLM_ARCH_QWEN3VL`/`LLM_ARCH_QWEN3VLMOE`). Nuestro build (9743) es muy posterior → soportado.
- **GPU:** RTX 5060 Ti 16 GB (Blackwell), confirmado por `nvidia-smi`. Un modelo residente a la
  vez en el `config.yaml` actual de llama-swap (sin `matrix`).

### Candidatos de modelo (tamaños confirmados en Hugging Face, jul-2026)

| Modelo | LM (Q4_K_M) | mmproj | Total | Notas |
|---|---|---|---|---|
| **Qwen3-VL-8B-Instruct-GGUF** (`Qwen/Qwen3-VL-8B-Instruct-GGUF`) | 5.03 GB | `mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf` — 752 MB | **~5.78 GB** | Elegido — margen cómodo bajo el objetivo de 6 GB |
| MiniCPM-V-4.5 (`openbmb/MiniCPM-V-4_5-gguf`) | 5.03 GB | `mmproj-model-f16.gguf` — 1.1 GB (no hay Q8_0 de mmproj) | ~6.13 GB | Alternativa documentada — algo por encima del objetivo de 6 GB pero cabe holgado en 16 GB |

**Elegido: Qwen3-VL-8B-Instruct Q4_K_M + mmproj Q8_0 (~5.78 GB).** Motivo: bajo el objetivo de
6 GB con margen, arquitectura ya validada en el build instalado, mmproj cuantizado disponible
(MiniCPM-V solo publica mmproj en F16, más pesado).

- Descarga (referencia, requiere tu OK — ver "Cambios en tu máquina" abajo):
  - `Qwen3VL-8B-Instruct-Q4_K_M.gguf` — 5.03 GB
  - `mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf` — 752 MB
  - Repo: `https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF`

### Discrepancia con el enunciado de la sesión

El mensaje de arranque decía default `qwen3-vl-8b`; se mantiene ese id de rol en llama-swap
(consistente con el resto del catálogo, que usa ids cortos tipo `gemma3-4b`).

### Advertencia (a documentar en la recipe)

Multimodal en llama.cpp **sigue marcado como experimental** por el propio proyecto (libmtmd es
relativamente nuevo, cambios de formato de tokenización de imagen entre versiones). La recipe
fija la versión de `llama-server` probada (9743 / c57607016) y advierte que un upgrade de
llama.cpp puede requerir reprobar el flujo antes de confiar en él en producción.

---

## Fases de implementación

### F6.1 — `config.py`
- `MODEL_VISION = _env("LOCAL_DELEGATE_MODEL_VISION", "qwen3-vl-8b")`.
- `MAX_IMAGE_MB = _env_int("LOCAL_DELEGATE_MAX_IMAGE_MB", 8)`.
- `MODEL_VISION` **no** entra en `ALLOWED_MODELS` (ese set es para el escape genérico
  `local_delegate`, que es texto→texto puro; no tiene sentido seleccionar el modelo de visión
  ahí porque no arma el payload multimodal). Se documenta la razón inline si hace falta.

### F6.2 — `server.py`: tool `local_describe_image`
- Firma: `local_describe_image(path: str, question: str | None = None, max_words: int = 200) -> str`.
- Validaciones, en este orden: `_check_allowed_dir(path)` (reutiliza el guardrail de F5) →
  extensión permitida (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, case-insensitive) → el archivo
  existe (`ValueError` si no) → tamaño ≤ `MAX_IMAGE_MB` (leído con `Path.stat().st_size` antes de
  cargar el archivo entero en memoria, para no leer un archivo gigante solo para rechazarlo).
- Lee el archivo en binario, lo codifica en base64, arma:
  ```python
  content = [
      {"type": "text", "text": user_prompt},
      {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
  ]
  ```
  con `mime` derivado de la extensión (`image/png`, `image/jpeg`, `image/webp`, `image/gif`).
- Reutiliza `_chat`, pero `_chat` hoy arma `messages` con `content` como `str` fijo
  (`server.py:329-338`). Se extiende `_chat` para aceptar `user` como `str | list[dict]` (Union)
  en vez de añadir una función paralela — evita duplicar el manejo de inflight/log/feedback.
- `source="path"` siempre (la tool no acepta `text`/imagen inline en base64 del usuario: el
  guardrail de scope es "solo lee del disco server-side"). `chars_in` = bytes del archivo
  (`raw_len`/tamaño en disco, no longitud del base64). El ahorro real mostrado en el feedback usa
  `result.tokens_in` (tokens de imagen que YA no entraron al contexto de Claude); si el backend no
  los da, no se estima con `chars/4` (esa heurística no aplica a tokens de imagen) — se omite la
  línea de feedback en ese caso.
- Docstring con el patrón "PREFIERE esta tool en vez de adjuntar/leer la imagen cuando solo
  necesitas descripción o lectura de texto de la imagen, no la imagen en sí en tu contexto." +
  guardrail explícito: "Solo imagen→texto (describir, leer texto/OCR simple, responder una
  pregunta puntual sobre la imagen). NUNCA genera ni edita imágenes."
- `_inflight_start`/`_inflight_end` igual que las demás tools (ya genérico, no necesita cambios).

### F6.3 — Recipe `docs/recipes/llama-swap-vision.md`
- Entrada de `config.yaml` (`qwen3-vl-8b`) con `--mmproj`, quant elegido, rutas de ejemplo.
- Versión de `llama-server` probada: **9743 (c57607016)** — pin explícito + advertencia de
  "reprobar tras upgrade" (multimodal experimental).
- `ttl` igual que el resto del catálogo (30s) salvo que el usuario prefiera más para imágenes
  (primera carga con mmproj es más lenta — medir y anotar el número real, no estimarlo).
- Alternativa documentada: MiniCPM-V-4.5 (mismo esquema de `cmd`, mmproj F16).

### F6.4 — Actualizaciones colaterales
- `tests/test_smoke.py`: `EXPECTED_TOOLS` → 11 tools (+ `local_describe_image`), `len(tools) == 11`.
- `local_status`: añadir el rol `vision` a la tabla de catálogo (mismo formato que los otros 4,
  pero sin `max_chars` porque no aplica del mismo modo — o mostrar el de `question` si se cotiza
  un tope).
- `~/.claude/skills/delegacion-local` (fuera del repo, en `~/.claude`): backup antes de editar,
  añadir la entrada de `local_describe_image` a la regla/catálogo.
- `docs/recipes/update_agents.py`: añadir `mcp__local-delegate__local_describe_image` a
  `NEW_TOOLS`; correr con `--dry` primero y enseñar el diff antes de aplicar.
- `README.md`: fila nueva en la tabla de tools + `LOCAL_DELEGATE_MODEL_VISION` /
  `LOCAL_DELEGATE_MAX_IMAGE_MB` en la tabla de env vars.
- Wiki (si existe fuera del repo — confirmar ruta) y `CHANGELOG.md` (`[Unreleased]` → entrada bajo
  `## [0.3.0]` al cerrar).

### F6.5 — Tests (`tests/test_core.py` o nuevo `tests/test_vision.py`)
Con `respx`/`monkeypatch` y un fixture de PNG diminuto (1x1 px, generado inline con bytes crudos
de PNG mínimo válido, no un asset binario en el repo):
- Payload multimodal correcto: `content` es una lista con `type=text` y `type=image_url`,
  `image_url.url` empieza con `data:image/png;base64,`.
- Archivo inexistente → `ValueError`/mensaje de error, sin llamar al backend.
- Extensión inválida (p. ej. `.txt`, `.bmp`) → error claro, sin llamar al backend.
- Archivo > `MAX_IMAGE_MB` → error claro (con un `MAX_IMAGE_MB` bajo vía monkeypatch para no
  crear un archivo grande de verdad en el test).
- Ruta fuera de `LOCAL_DELEGATE_ALLOWED_DIRS` → `ValueError` (reutiliza `_check_allowed_dir`,
  mismo patrón que los tests de F5 existentes).
- `usage.jsonl`: `tokens_in`/`tokens_out` reales de la respuesta mockeada quedan en el log
  (reutiliza el patrón de `test_post_chat_ok_with_usage_and_finish_reason`).
- `uv run pytest` y `uv run ruff check .` en verde antes de cerrar.

---

## Cambios en TU máquina (fuera del repo — requieren tu OK explícito antes de ejecutarlos)

1. Descargar (varios GB) a `D:\Projects\llms\models\qwen3-vl-8b\`:
   - `Qwen3VL-8B-Instruct-Q4_K_M.gguf` (5.03 GB)
   - `mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf` (752 MB)
   - Comando propuesto (`huggingface-cli` o `hf` según lo que tengas instalado) — te lo muestro
     justo antes de ejecutarlo, no antes.
2. Backup de `D:\Projects\llms\llama-swap\config.yaml` (copia `.bak` con timestamp) antes de
   añadir la entrada `qwen3-vl-8b`.
3. Edición del `config.yaml`: te enseño el diff exacto, esperas tu OK, aplico.
4. Prueba manual post-cambio: `local_status` (o llamada directa) para confirmar que el rol
   `vision` responde; una llamada real a `local_describe_image` con una imagen de prueba;
   `nvidia-smi` antes/durante/después para anotar el pico de VRAM real (no estimado).

---

## Criterios de aceptación F6

- [ ] `uv run pytest` en verde (tests nuevos incluidos).
- [ ] `uv run ruff check .` en verde.
- [ ] `local_status` muestra el rol `vision`.
- [ ] `EXPECTED_TOOLS` en tests = 11, todas registradas.
- [ ] Recipe `llama-swap-vision.md` con la versión de llama-server pineada y el quant elegido.
- [ ] README, skill, `update_agents.py`, CHANGELOG actualizados.
- [ ] Verificación manual real (post-implementación, con el usuario): backend arriba, imagen de
  prueba descrita correctamente, `usage.jsonl` con tokens reales de imagen, VRAM real anotada.
- [ ] Bump `0.3.0` en `pyproject.toml` + entrada en `CHANGELOG.md` + `uv build` sin errores.
- [ ] Checkbox F6 marcado en `plan-v0.2-mejoras.md`.
- [ ] Ningún push ni publicación a PyPI sin confirmación explícita del usuario.

## Discrepancias plan-maestro vs. código real (a anotar también en `plan-v0.2-mejoras.md` al cerrar)

- Ninguna detectada aún en el código existente relevante a F6 (F1-F5 ya están en verde según el
  checklist). Si aparece alguna durante la implementación, se registra aquí y en el plan maestro.
