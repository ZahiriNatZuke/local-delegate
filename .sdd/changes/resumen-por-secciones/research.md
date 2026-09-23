# Research: local_summarize respeta la estructura del documento (resumen por secciones)

Fuentes: mapa de impacto de `personal-sdd-researcher` (2026-09-23) y medición propia sobre los
transcripts del piloto de T5 (`%TEMP%\banco-piloto-t5`) y el log de uso
(`%LOCALAPPDATA%\local-delegate\usage-202609.jsonl`, líneas 42-64). Sin gasto de cuota.

## Current behavior

**Camino de `local_summarize`** (`src/local_delegate/server.py:1935-1996`):

- Firma `local_summarize(text=None, path=None, max_words=150)`. `path` se lee del lado del servidor
  sin truncar (`_read_input`, `server.py:367-383`, `_NO_TRUNCATE`).
- Rol por tamaño (`_rol_por_tamano`, `server.py:1643-1650`): `long` (`gemma4-26b-a4b`) por encima
  de `LONG_INPUT_CHARS` = 6000 (`config.py:225`), `mechanical` (`gemma3-4b`) por debajo. El hook
  copia la regla en `hook_common.modelo_del_resumen` (`hook_common.py:295-307`), atada a
  `config.py` por `tests/test_conformidad_f1.py`.
- Prompt de sistema (`_guard`, `server.py:1891-1896`), literal: «Responde directo desde el input.
  NO uses herramientas, NO busques en internet. Output EXACTO: un resumen en prosa clara. Máximo
  {max_words} palabras. Nada fuera del formato.» Usuario: «Resume el siguiente contenido:\n\n…».
- Una sola llamada salvo que el contenido supere `max_chars_for_role` (largo 48 000,
  `config.py:230-235`); `max_tokens = 2·max_words + 64`, `temperature` 0,2.
- Por encima del tope: map-reduce (`_chat_map_reduce`, `server.py:1653-1857`). Trocea por
  diff → títulos Markdown (`_split_by_headers`, `(?m)(?=^#{1,6} )`, `server.py:1328`) → párrafos →
  líneas, y `_pack` **agrupa** varias secciones por trozo (presupuesto 0,8 × tope = 38 400). El
  reduce pide «un ÚNICO resumen global en prosa clara, sin repetir ni enumerar los fragmentos»
  (`server.py:1725-1735`). Ya existen `reduce_system`, `build_reduce` y `partial_max_words`
  (los usa `local_commit_msg`, `server.py:2388-2405`).
- La descripción que ve el cliente promete «el resumen corto» y no habla de estructura
  (`server.py:1941-1955`).

**Qué pasó en el piloto de T5** (medido en los transcripts; la cobertura es la fracción de
títulos `##` del documento que aparecen en el texto devuelto por la tool, con la misma
normalización del banco):

| Corrida | Llamada | `max_words` pedido | Palabras devueltas | Cobertura en la tool | Cobertura en la respuesta final |
| --- | --- | --- | --- | --- | --- |
| readme/v0 | summarize | 600 | 379 | 0,18 | 1,00 (tras 7 franjas) |
| readme/v1 | summarize | 500 | 348 | 0,27 | 0,91 |
| wiki-instalacion/v0 | summarize | 450 | 350 | 0,22 | 1,00 (tras franjas) |
| wiki-instalacion/v1 | summarize | 600 | 409 | 0,11 | 0,89 |
| wiki-instalacion/v2 | summarize | 600 | 434 | 0,22 | 0,78 |
| wiki-daemon/v0 | summarize | 600 | 361 | 0,20 | 1,00 (tras franja) |
| wiki-daemon/v1 | summarize | 500 | 347 | 0,20 | 1,00 (tras franja) |
| wiki-daemon/v2 | summarize ×5 | 600, 100, 120, 250, 250 | 72–368 | 0,00–0,20 | 1,00 (partió a mano) |

Además, 4 corridas recurrieron a `local_extract` con **un campo por sección**
(`resumen_seccion_por_que_existe`, …) para forzar la estructura: la cobertura en la tool subió a
0,27–0,40, todavía lejos.

Conclusiones con evidencia:

1. **Todas las llamadas del piloto fueron de una sola pasada** (13 913–17 960 caracteres, sin
   `chunks`, `finish_reason: stop`, modelo `gemma4-26b-a4b`). El troceado y el reduce no
   intervinieron.
2. **`max_words` no es la causa**: Claude pidió 450–600 palabras, la tool devolvió 350–430 y aun
   así nombró como mucho 3 de 11 títulos.
3. **La estructura se pierde en el prompt**, que pide «prosa clara» y «nada fuera del formato».
4. **Claude ya intenta imponer la estructura** (más palabras, `local_extract` por secciones,
   partir el fichero): la demanda es real, y la tool no tiene cómo expresarla.
5. En documentos de más de 48 000 caracteres el reduce va explícitamente **contra** la estructura.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `local_summarize` | prompt de prosa, una pasada o map-reduce | prompt estructurado cuando el documento tiene títulos; posible parámetro de enfoque | `server.py:1935-1996` |
| `_chat_map_reduce` | trocea por títulos y funde en prosa | usar `reduce_system`/`build_reduce` que conserven secciones en orden | `server.py:1653-1857`, precedente en `server.py:2388-2405` |
| `_split_by_headers` | separador del troceado, compartido | reutilizar sin cambiarlo; detectar títulos fuera de bloques de código si se cuentan | `server.py:1328`; comparte con `_chunk_text` |
| `max_tokens` | `2·max_words + 64` | margen para títulos y viñetas, o un tope por sección | `server.py:1983-1995` |
| Descripción de la tool | «resumen corto» | decir que conserva la estructura y el parámetro nuevo, si lo hay | `server.py:1941-1955` |
| Log de uso | un evento por llamada, `chunks` si > 1 | quizá un campo aditivo (modo o secciones); nunca N eventos por delegación | `server.py:475-552`, `_accounting` 560-624 |
| Hooks | `modelo_del_resumen` copia la regla de rol | sin cambios si el rol se sigue decidiendo por el tamaño del documento entero | `hook_common.py:295-307` |
| Benchmarks y corpus | copian el prompt actual literal | conservar el prompt actual para texto sin títulos o actualizar las copias | `benchmarks/catalogo-2026-09/cases.json`, `scripts/construir_corpus.py:210`, `tests/test_corpus.py:446-466` |
| Docs | wiki `Tools.md` describe el map-reduce en prosa; la skill dice «Resumen (prosa)» | actualizar | `docs/wiki/Tools.md:22,34-62`, `resources/skills/delegacion-local/SKILL.md:36` |
| Medición | el banco mide la cobertura en la respuesta final de Claude | medir también la cobertura **en la salida de la tool**, gratis y sin `claude -p` | `scripts/experimento_adopcion.py:141-152,249-252` |

## Existing conventions

- Parámetros opcionales de enfoque sin validar: `local_explain_code(question=)` lo inyecta en el
  sistema como «Enfócate en: …» (`server.py:2479,2496`); `local_describe_image(question=)`
  sustituye al prompt de usuario (`server.py:2520-2546`).
- Valores cerrados se validan devolviendo un texto de error, no una excepción
  (`local_delegate.chunk`, `server.py:2187-2188`; `local_commit_msg.style`, `server.py:2314-2317`).
- Una operación troceada escribe **un solo evento** con `chunks: N` y el ahorro se cuenta una vez
  (`server.py:565-567,1834-1852`). Los campos nuevos del log son aditivos y se omiten cuando no
  aplican.
- Los parámetros nuevos de una tool son opcionales: los clientes cachean el schema, pero el
  argumento nuevo llega al servidor igual (memoria del proyecto).

## Dependencies and integrations

- Backend OpenAI-compatible (llama-swap) con `gemma4-26b-a4b` (largo) y `gemma3-4b` (mecánico);
  semáforo `_chat_slots` para concurrencia (`MAX_CONCURRENT_REQUESTS` sin verificar).
- Clientes: Claude Code, Codex, opencode y Claude Desktop ven la descripción de la tool.
- Panel: `_accounting` tiene un espejo JS con test de paridad (`tests/test_dashboard_js.py`,
  contenido sin verificar); solo afecta si cambia la contabilidad.

## Risks and unknowns

**Confirmados:**

- Ningún test fija el prompt ni la forma de la salida de `local_summarize`: un cambio de
  comportamiento no pondría la suite en rojo (`tests/test_map_reduce.py` usa un mock que responde
  «RESUMEN»).
- Si se hace una llamada por sección con el enrutado por tamaño de la sección, las secciones de
  menos de 6000 caracteres irían al 4B (pasó en wiki-daemon/v2) y la copia del hook se desfasaría.
- `^#{1,6} ` también casa con comentarios `#` dentro de bloques de código.
- Cambiar el prompt por defecto rompe la comparabilidad con `cases.json` y el corpus.

**Por validar:**

- Si el 26B conserva la estructura con solo cambiar el prompt, en una pasada (lo más barato), o
  hace falta una llamada por sección. **Se puede medir sin cuota**: llamando la tool contra el
  backend real con los tres documentos del piloto y midiendo la cobertura en su salida.
- Cuánto crece la salida con 46 secciones (CHANGELOG) frente a `max_words` y `max_tokens`.
- Si una salida estructurada evita la relectura de Claude: solo lo mide el banco con `claude -p`
  (cuota).
- Que la cobertura de títulos refleje un buen resumen: hay que contrastarla con un juicio humano,
  porque se pasa poniendo solo los títulos.
