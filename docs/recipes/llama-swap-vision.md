# Recipe: visión local (imagen→texto) con llama-swap

Añade un rol de **visión** (`local_describe_image`) al setup de referencia de
[`llama-swap-blackwell.md`](llama-swap-blackwell.md): un modelo GGUF más con `--mmproj`,
servido por el mismo `llama-swap` en `127.0.0.1:9292`, con hot-swap igual que los demás roles.

> **Multimodal en llama.cpp sigue siendo experimental.** El soporte de imágenes (`libmtmd`,
> `--mmproj`) es relativamente reciente y el formato interno de tokenización de imagen ha
> cambiado entre versiones. Esta recipe fija la versión de `llama-server` **probada de verdad**
> (abajo). Si actualizas tu binario de llama.cpp, **reprueba el flujo** (una llamada real a
> `local_describe_image` + revisar `usage.jsonl`) antes de confiar en él en producción — no
> asumas que sigue funcionando igual solo porque el flag no cambió de nombre.

## Modelo por defecto (desde la 0.54.1)

El rol de visión usa por defecto `qwen36-35b-a3b-vision`: el mismo GGUF de Qwen3.6 35B-A3B del rol
`code` con su proyector `--mmproj`. En la medición de #699 (2026-11-23, capturas de UI con una
pregunta sugerente) inventó 0 de 9 defectos de layout; `gemma4-12b`, 5 de 9. Cuesta ~14 GB de RAM
privada y ~11 GB de VRAM, y unos 30 s de carga en frío.

```yaml
models:
  qwen36-35b-a3b-vision:
    cmd: >
      D:\Projects\llms\llamacpp\llama-server.exe --port ${PORT} --host 127.0.0.1
      --model D:\Projects\llms\models\qwen36-35b-a3b\Qwen3.6-35B-A3B-UD-IQ4_XS.gguf
      --mmproj D:\Projects\llms\models\qwen36-35b-a3b\mmproj-F16.gguf
      -ngl 99 -ncmoe 20 --ctx-size 8192 --jinja --reasoning off
    ttl: 30
```

**Alternativa ligera:** `gemma4-12b` (Gemma 4 12B con su `--mmproj`, ~10 GB de RAM y ~9 GB de VRAM)
para máquinas con menos VRAM, o si tu catálogo no tiene la entrada de arriba: pon
`LOCAL_DELEGATE_MODEL_VISION=gemma4-12b`. `local-delegate doctor` lo propone si tu backend sirve `gemma4-12b` y
no `qwen36-35b-a3b-vision`. `init-llamaswap` no crea estas entradas: agrupa las que ya tienes.

El resto de esta receta es la de la primera versión del rol (Qwen3-VL-8B) y vale como esquema.

## Versión de llama-server probada

- `version: 9743 (c57607016)`, build CUDA (Clang 20.1.8 para Windows x86_64).
- Confirmado con `llama-server --help`: soporta `-mm, --mmproj FILE`, `--mmproj-offload` y
  `--image-min-tokens`/`--image-max-tokens`. El build incluye `llama-mtmd-cli.exe`,
  `llama-qwen2vl-cli.exe`, `llama-minicpmv-cli.exe`, `llama-gemma3-cli.exe` (soporte multimodal
  completo, no parcial).
- Arquitectura Qwen3-VL mergeada en `ggml-org/llama.cpp` PR #16780 (30-oct-2025); un build de
  esa fecha o posterior la soporta.

## Modelo elegido: Qwen3-VL-8B-Instruct

| | |
|---|---|
| Repo | `Qwen/Qwen3-VL-8B-Instruct-GGUF` (Hugging Face) |
| LM | `Qwen3VL-8B-Instruct-Q4_K_M.gguf` — 5.03 GB |
| mmproj | `mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf` — 752 MB |
| Total VRAM (peso) | **~5.78 GB** — holgado bajo el objetivo de 6 GB en una GPU de 16 GB |

### Descarga (referencia — ejecuta tú los comandos, revisa antes de correrlos)

```bash
# con huggingface-cli / hf, hacia D:\Projects\llms\models\qwen3-vl-8b\
hf download Qwen/Qwen3-VL-8B-Instruct-GGUF Qwen3VL-8B-Instruct-Q4_K_M.gguf \
  --local-dir D:\Projects\llms\models\qwen3-vl-8b
hf download Qwen/Qwen3-VL-8B-Instruct-GGUF mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf \
  --local-dir D:\Projects\llms\models\qwen3-vl-8b
```

### Entrada en `config.yaml` de llama-swap

Mismo esquema que el resto del catálogo (ver `llama-swap-blackwell.md`): un `cmd` con
`--mmproj` apuntando al proyector, `ttl` para liberar VRAM tras inactividad.

```yaml
models:
  qwen3-vl-8b:
    cmd: >
      D:\Projects\llms\llamacpp\llama-server.exe --port ${PORT} --host 127.0.0.1
      --model D:\Projects\llms\models\qwen3-vl-8b\Qwen3VL-8B-Instruct-Q4_K_M.gguf
      --mmproj D:\Projects\llms\models\qwen3-vl-8b\mmproj-Qwen3VL-8B-Instruct-Q8_0.gguf
      -ngl 99 --ctx-size 8192 --jinja
    ttl: 30
```

- `--mmproj-offload` está habilitado por defecto (sube el proyector a GPU también); no hace
  falta pasarlo explícito salvo que quieras forzar `--no-mmproj-offload` para ahorrar VRAM a
  costa de latencia.
- `ttl: 30` sigue el mismo criterio que el resto del catálogo (buen equilibrio para delegación
  desde Claude — ver la sección "Descarga de VRAM" de `llama-swap-blackwell.md`). La **primera**
  carga con mmproj puede ser algo más lenta que un modelo sin visión: mide con `nvidia-smi` y
  anota el número real en vez de asumirlo.

### `local-delegate` (env vars)

```json
"env": {
  "LOCAL_DELEGATE_MODEL_VISION": "qwen3-vl-8b",
  "LOCAL_DELEGATE_MAX_IMAGE_MB": "8"
}
```

El tope de 8 MB es el default del paquete; el id de visión por defecto es `qwen36-35b-a3b-vision`
(ver arriba): solo hace falta esto si usas otro id o quieres otro tope de tamaño.

## Formato de la petición (para referencia, ya lo arma `local_describe_image`)

`llama-server` expone el formato OpenAI-compatible de "content array" en
`/chat/completions`, sin flag propio — basta con que el modelo tenga `--mmproj` cargado:

```json
{
  "model": "qwen3-vl-8b",
  "messages": [
    {"role": "system", "content": "..."},
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "Describe esta imagen con detalle."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KG..."}}
      ]
    }
  ]
}
```

## Alternativa documentada: MiniCPM-V 4.5

| | |
|---|---|
| Repo | `openbmb/MiniCPM-V-4_5-gguf` (Hugging Face) |
| LM | `MiniCPM-V-4_5-Q4_K_M.gguf` (o `ggml-model-Q4_K_M.gguf`) — 5.03 GB |
| mmproj | `mmproj-model-f16.gguf` — 1.1 GB (no hay variante Q8_0 del proyector) |
| Total VRAM (peso) | ~6.13 GB — algo por encima del objetivo de 6 GB, pero cabe holgado en 16 GB |

Construido sobre Qwen3-8B + SigLIP2-400M. Mismo esquema de `cmd` que arriba, cambiando
`--model` y `--mmproj` por los archivos de este repo. Úsalo si Qwen3-VL-8B no da buenos
resultados para tu caso de uso concreto (p. ej. OCR de documentos densos, donde algunos
benchmarks de MiniCPM-V destacan).

## Guardrail de alcance

`local_describe_image` es **solo imagen→texto**: describir, leer texto visible (OCR simple),
responder una pregunta puntual. El paquete **no** ofrece generación ni edición de imágenes con
ningún modelo de este catálogo, y no está pensado para eso.
