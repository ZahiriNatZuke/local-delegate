# Pasada en vivo de las 11 tools — 0.35.0 candidata

- Fecha: 2026-10-13, llamadas entre 13:00:48Z y 13:02:57Z.
- Ventana de prueba: `w-20261013T123443Z` (abierta 12:34:43Z, cerrada 13:03:12Z con `local-delegate test-window stop`).
- Daemon: código de `main` previo a `5723ac9`, se identifica como `local-delegate v0.34.0`. Backend local `127.0.0.1:9292`, llama-swap grupo `swap`.
- Requisitos: REQ-017 (salida al usuario sigue en español) y REQ-038 (las tools responden tras el renombrado A0–A6).
- Latencias: `latency_ms` del log de uso (`~/AppData/Local/local-delegate/usage-202610.jsonl`). Incluyen la carga del modelo cuando hubo cambio.

| # | Tool | Resultado | Modelo | Latencia | Extracto de la respuesta |
|---|------|-----------|--------|----------|--------------------------|
| 1 | `local_status` | OK | — | inmediata | «Ventana de prueba abierta: w-20261013T123443Z desde 2026-10-13T12:34:43.060Z»; roles `mechanical`/`long`/`code`/`vision`; «Respaldo entre modelos: encendido (hasta 2 saltos)». |
| 2 | `local_summarize(path=docs/wiki/Daemon.md)` | OK | gemma4-26b-a4b | 21,2 s | Resumen por secciones: «## Por qué existe … ## Arranque … ## Autenticación del puerto …»; «(leído server-side: 17,094 chars ≈ 8,547 tokens de Claude que no entraron a tu contexto)». |
| 3 | `local_classify` | OK | gemma3-4b | 23,7 s (esperó turno: se lanzó junto a la 2) | «fallo, petición de función, pregunta» (tres líneas, una etiqueta por línea; la tool promete una sola). |
| 4 | `local_extract(path=…/prices.json)` | OK | gemma3-4b | 1,7 s | 13 modelos y 13 precios `input` correctos; marcador `"_local_delegate":{"leido_server_side":{"chars":2608,"tokens_aprox":1387}}`. |
| 5 | `local_boilerplate` (dataclass `ModelPrice`) | OK | qwen36-35b-a3b | 16,5 s | «[escrito] ~/…/scratchpad/model_price.py — 10 líneas, 281 chars (≈116 tokens de Claude que no entraron a tu contexto)». |
| 6 | `local_delegate` (snake_case → camelCase, 3 nombres) | OK funcional, calidad mala | gemma3-4b | 5,1 s | Devolvió los nombres sin convertir: «read_hook_threshold / structured_summary / test_window_stop». Fallo del modelo pequeño, no del renombrado. |
| 7 | `local_lint_summary(path=ruff.log)` | OK | gemma4-26b-a4b | 18,6 s | Agrupado por fichero y regla (D101, C901, E501…); «Conteo total: 24 errores», que coincide con el «Found 24 errors.» del log (ruff `--select ALL` sobre `sections.py`). |
| 8 | `local_commit_msg(path=git show 5723ac9)` | OK | qwen36-35b-a3b | 20,8 s | «fix(recompute): traduce rótulos de cruces en resumen de terminal» + 3 viñetas en español. |
| 9 | `local_translate` (es → inglés) | OK | qwen36-35b-a3b | 1,8 s | «The daemon saves each delegation in a monthly log. From there, the panel calculates how much context was saved…». |
| 10 | `local_explain_code(path=src/local_delegate/sections.py)` | OK | qwen36-35b-a3b | 11,8 s | «Este módulo gestiona la estructura de documentos Markdown para resúmenes por secciones, detectando títulos ATX y Setext…». |
| 11 | `local_describe_image(path=…/panel-claro.png)` | OK | gemma4-12b | 13,1 s | «Los rótulos están en español. … contexto conservado de 133.967 tokens, 6 delegaciones…»; «(leído server-side: 556,636 bytes imagen…)». |

## Cierre de la ventana

`local_status` tras el `stop`: ya no aparece «Ventana de prueba abierta»; el log cuenta «(20 de pruebas fuera)» frente a «(10 de pruebas fuera)» antes de la pasada, así que las 10 delegaciones de esta pasada quedaron apartadas como prueba.

## Regresiones de REQ-017

Ninguna. Toda la salida al usuario sigue en español; los textos que aparecen en inglés son nombres internos (roles, claves de rótulo) o contenido pedido en inglés (la traducción).

## Observaciones (no son regresiones)

- `local_status` avisa en ambas llamadas: «LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO está obsoleto: usa LOCAL_DELEGATE_STRUCTURED_SUMMARY (se retirará tres versiones menores después)». Es el alias de compatibilidad funcionando: el lanzador del daemon de esta PC aún usa el nombre viejo y conviene actualizarlo.
- El marcador de `local_extract` sigue con claves en español (`leido_server_side`, `tokens_aprox`), igual que `truncado`/`aviso`/`respaldo`.
- Los recibos de lectura usan coma de miles al estilo inglés («17,094 chars», «556,636 bytes imagen»); ya era así antes del renombrado (formato `{:,}` en `server.py`).
- «gemma4-12b sin referencia (1 muestras)» en `local_status`: concordancia de número, detalle menor.
- `local_translate` cayó en `qwen36-35b-a3b` y no en el modelo mecánico: el respaldo «mechanical: loaded → …» aprovecha el modelo ya cargado; no salió marcador de respaldo en la respuesta.
- Las llamadas 2 y 3 se lanzaron a la vez por error del agente (el encargo pedía de una en una); el turno las serializó sin fallo.
