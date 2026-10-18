# Pasada en vivo de las 11 tools — 0.36.0 candidata, en inglés y en español

- Fecha: 2026-10-18. Rama `release/0.36.0` (desde `main` en `c61206d`, con la versión ya subida a
  0.36.0), instalada con `uv tool install --force --reinstall --no-cache ".[llamaswap]"` bajo
  `pesado.sh` con el daemon parado. El daemon se identifica como `local-delegate v0.36.0`.
- Requisitos: REQ-017 (las 11 tools responden y la salida al usuario está en su idioma), REQ-028
  (muestra D10 del idioma de respuesta del modelo), REQ-038 (ids de ventana), REQ-047
  (`local_status` con el mismo idioma, origen y ruta que `doctor`).
- Método: `run_tools.py` llama a cada tool una vez por el `/mcp` del daemon (cliente de
  `evidence/B2d-2/run_live.py`; la credencial la pone el daemon) y escribe la respuesta literal en
  `answers/<idioma>/<tool>.txt`, sin pasar por un contexto de Claude. El idioma lo decide el
  `language.json` que dejó `install` (primero `LOCAL_DELEGATE_LANG=en`, luego `=es`); el daemon lo
  reinicia el propio `install`. Antes de cada llamada, `run_tools.py` espera si hay menos de 4 GB
  de RAM libre.
- Juez de idioma «solo prosa» (`scripts/judge_response_language.py`, `judge.sh`) sobre las seis
  respuestas con prosa: `answers/<idioma>/judge.jsonl`.

## Ventanas de prueba

| Idioma | Ventana | Abierta | Cerrada | Filas apartadas |
| --- | --- | --- | --- | --- |
| en | `w-20261018T132615Z` | 13:26:15Z | 13:46:04Z | 10 |
| es | `w-20261018T134632Z` | 13:46:32Z | 13:58:48Z | 10 |

(`local_status` no escribe fila de uso: 10 de 11.)

## Resultado

| # | Tool | Modelo | en: resultado, idioma | es: resultado, idioma |
| --- | --- | --- | --- | --- |
| 1 | `local_status` | — | OK; `Language: en (preference; ~\AppData\Local\local-delegate\language.json)`, `Model response language: en (preference)`; juez: en | OK; `Idioma: es (preferencia; ~\AppData\Local\local-delegate\language.json)`, `Idioma de respuesta del modelo: es (preferencia)`; juez: es |
| 2 | `local_summarize(path=docs/wiki/Daemon.md)` | gemma4-26b-a4b | OK, 39,7 s; resumen por secciones en inglés; juez: en | OK, 25,6 s; títulos `## ` literales y prosa en español; juez: es |
| 3 | `local_classify` | gemma3-4b | OK: `bug` | OK: `bug` |
| 4 | `local_extract(path=pyproject.toml)` | gemma4-26b-a4b | OK; 3 campos correctos; marcador nuevo `_local_delegate.read_server_side.{chars, approx_tokens}` | OK; igual (el contrato no depende del idioma) |
| 5 | `local_boilerplate` | qwen36-35b-a3b | OK; `[written] … 10 lines, 295 chars (≈122 Claude tokens …)` | OK; `[escrito] … 10 líneas, 295 chars (≈122 tokens de Claude …)` |
| 6 | `local_delegate` (snake → camel) | gemma3-4b | OK: `readHookThreshold` / `structuredSummary` / `testWindowStop` | OK, igual |
| 7 | `local_lint_summary(path=ruff.log, 14 237 chars)` | gemma4-26b-a4b (rol largo, llamada única de B2f) | OK; 15 códigos de regla, todos con su cifra exacta; copia «Found 30 errors.»; juez: en | OK; 15 códigos nombrados (B2f funciona en español); copia «Found 30 errors.»; **dos cifras mal**: D101 6 (son 5) y D400 4 (son 3); juez: es |
| 8 | `local_commit_msg(path=diff de c61206d)` | qwen36-35b-a3b | OK; `feat(server): …` y 5 viñetas, en inglés (idioma del producto); juez: en | OK; primera línea y 5 viñetas en español; juez: es |
| 9 | `local_translate` | gemma3-4b | OK; es → inglés | OK; en → español |
| 10 | `local_explain_code(path=sections.py)` | qwen36-35b-a3b | OK, 56,8 s; troceado («summarized from 2 parts in 3 passes»); juez: en | OK, 55,8 s; troceado; juez: es |
| 11 | `local_describe_image(path=live-035/panel-claro.png)` | gemma4-12b | OK; «The labels in the image are in Spanish…», cifras del panel; juez: en | OK; «Las etiquetas de la interfaz están en español…»; juez: es |

**11 de 11 sin error en los dos idiomas.** Los recibos, avisos y marcadores salen en el idioma
del proceso; el contrato de `_local_delegate` en inglés en los dos.

## Muestra D10 (REQ-028): idioma de la respuesta del modelo

Juez «solo prosa», veredicto `requested` = en el idioma pedido:

| Tool | en | es |
| --- | --- | --- |
| `local_status` | requested | requested |
| `local_summarize` | requested | requested |
| `local_lint_summary` | requested | requested |
| `local_commit_msg` | requested | requested |
| `local_explain_code` | requested | requested |
| `local_describe_image` | requested | requested |

12 de 12 (100 %). Muestra de una respuesta por tool e idioma: confirma que la orden de idioma
llega, no mide la tasa (la tasa con repeticiones está en B2d/B2d-2).

## Observaciones (no bloquean)

- **Fidelidad de lint en español:** con el mismo log, el resumen inglés da todas las cifras bien y
  el español se equivoca en dos (D101 y D400, +1 cada una). Es el residuo de cifras inventadas ya
  medido en B2d-3 (media 3,67 por tanda tras el arreglo) y no un fallo del idioma ni de B2f. Va a
  la nota de backlog.
- **RAM:** tras cargar `qwen36-35b-a3b` o `gemma4-26b-a4b`, la RAM libre bajó a 0,4–1,4 GB
  **entre** llamadas (modelo cargado y en espera de su TTL); `run_tools.py` esperó en cada caso a
  tener 4 GB antes de seguir. Durante las llamadas, el mínimo registrado fue 1,6 GB (vigilancia
  cada 5 s) y el log de uso apunta `free_ram_mb: 1741` en `local_boilerplate` (inglés). No se
  bajó de 1,5 GB en ninguna llamada.
- Las cifras de los recibos van sin separador de miles en los dos idiomas («14237 chars»), como
  pide REQ-026; las del `local_describe_image` son las del propio panel (texto de la imagen).
