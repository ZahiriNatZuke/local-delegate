---
name: delegacion-local
description: Regla y catálogo para delegar pasos mecánicos (resumir, clasificar, extraer, boilerplate, mensaje de commit desde un diff, traducir texto o archivo, resumir salida de lint/tests/CI, explicar código, describir una imagen, verificar si el backend local está disponible) a modelos locales vía las tools local_* del MCP local-delegate, para conservar cuota de la suscripción. Consúltala cuando vayas a resumir/clasificar/extraer de archivos o texto largos, generar boilerplate de código, describir/leer una imagen, o hacer una primera pasada mecánica — antes de generarlo tú mismo.
---

# Delegación a modelos locales (MCP `local-delegate`)

Tienes un servidor MCP (`local-delegate`) que expone modelos corriendo en una GPU propia
(vía llama-swap, Ollama, LM Studio o vLLM) como herramientas **texto/imagen→texto**. Delegar
a ellas **conserva cuota de la suscripción**: la generación verbosa y los inputs grandes (o
una imagen entera) se quedan fuera de tu contexto.

## Regla de oro

> **¿Puedo describir el paso en UNA frase con un formato de salida explícito?**
> → **sí** → usa una tool `local_*`.
> → **no** (necesita razonamiento, arquitectura, criterio, multi-fuente) → **hazlo tú**.

## El mayor ahorro: `path` en vez de `text`

Para archivos/documentos grandes, pasa **`path`** (no leas el archivo tú primero). Las
tools que aceptan `path` **leen el archivo del lado del servidor**, así el contenido
completo **nunca entra a tu contexto** — solo recibes el resultado corto.

## El coste de no delegar

Leer un archivo de 100 KB con `Read` cuesta ≈ 25 000 tokens de tu contexto. La misma
tarea con `local_summarize(path=…)` cuesta ≈ 200 tokens (solo el resumen que vuelve).
Esa diferencia es la que se pierde cada vez que se lee un archivo grande a mano en vez
de delegarlo.

## Catálogo de tools

| Tool | Cuándo | Args clave | Devuelve |
|---|---|---|---|
| `local_summarize` | Resumir texto o archivo largo | `path` **o** `text`, `max_words` | Resumen (prosa) |
| `local_classify` | Etiquetar en categorías fijas | `text`, `labels[]` | Una etiqueta |
| `local_extract` | Sacar campos estructurados | `fields[]`, `path` **o** `text` | JSON |
| `local_boilerplate` | Generar código repetitivo | `spec`, `language` | Código (sin fences) |
| `local_delegate` | Escape genérico texto→texto | `task`, `input`, `output_format`, `model?`, `chunk?` | Texto |
| `local_lint_summary` | Resumir salida de lint/tests/CI | `path` **o** `text`, `max_words` | Resumen agrupado por archivo |
| `local_commit_msg` | Mensaje de commit desde un diff | `diff` **o** `path`, `style?` | Mensaje (revísalo siempre) |
| `local_translate` | Traducir texto o archivo | `target_lang`, `text` **o** `path` | Traducción |
| `local_explain_code` | Explicar qué hace un código | `code` **o** `path`, `question?` | Explicación (prosa) |
| `local_describe_image` | Describir una imagen o responder una pregunta sobre ella | `path`, `question?` | Descripción (prosa) |
| `local_status` | Diagnóstico de solo lectura | — | Backend/catálogo/log/VRAM |

Los ids de modelos del catálogo (mecánico/largo/código/rápido/visión) son configurables por
env y pueden cambiar entre máquinas: consulta `local_status` para ver el catálogo
activo en vez de asumir nombres fijos. `local_describe_image` es **solo imagen→texto**
(describir, leer texto visible, responder una pregunta puntual) — nunca genera ni edita
imágenes.

## Documentos largos

`local_translate` (y `local_delegate` con entradas largas) parten el texto por límites
naturales —headers Markdown, párrafos— y procesan cada trozo en su propia llamada,
concatenando las salidas en orden. Un documento de 20 000+ caracteres vuelve **completo**,
sin el aviso `[salida truncada]`. Esa estrategia sirve para transformar todo el texto
(traducir, reescribir, reformatear); para tareas de reducción sobre el conjunto (contar,
elegir el máximo, un único resumen global) usa `local_summarize` o `chunk='off'`.

## Cuándo SÍ delegar (ejemplos)
- Resumir un log/archivo grande para saber qué contiene → `local_summarize(path=…)`.
- Clasificar un issue/mensaje en bug/feature/pregunta → `local_classify`.
- Extraer `{nombre, error, endpoint}` de un texto → `local_extract`.
- Generar el esqueleto de un CLI/argparse, un dataclass, un parser → `local_boilerplate`.
- Resumir la salida de un lint/test/build largo volcada a fichero → `local_lint_summary(path=…)`.
- Redactar el mensaje de commit a partir de un `git diff` → `local_commit_msg`.
- Traducir un texto o archivo → `local_translate`.
- Explicar qué hace un archivo de código antes de tocarlo → `local_explain_code(path=…)`.
- Describir una captura de pantalla o leer texto de una imagen → `local_describe_image(path=…)`.
- Verificar que el backend local está vivo antes de delegar en masa, o diagnosticar un
  fallo → `local_status`.
- Primera pasada mecánica antes de tu revisión fina.

## Cuándo NO delegar
- Diseño/arquitectura, decisiones de trade-offs, refactors amplios.
- Research multi-fuente o razonamiento encadenado.
- Cualquier cosa donde la calidad del resultado dependa de criterio, no de formato.
- Código crítico o sutil: úsalo como borrador y **revísalo siempre**.

## Notas
- Las tools devuelven **solo texto**; el modelo local no usa tool-calling.
- Si una tool devuelve `[local-delegate error] …`, es que el backend no respondió;
  cae de vuelta a hacerlo tú y avisa. Usa `local_status` para diagnosticar por qué.
- La primera llamada a un modelo puede tardar unos segundos (cold-load del swap).
- El dashboard (`http://127.0.0.1:9393`) muestra el ahorro acumulado, las delegaciones en
  curso y si el cómputo corrió en el backend local o en uno remoto.
