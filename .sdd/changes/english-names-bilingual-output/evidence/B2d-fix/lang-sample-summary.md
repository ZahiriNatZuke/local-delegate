# B2d-fix — idioma de summarize y lint_summary: resumen de las dos tandas

Medido el 2026-10-15 con la rama `sdd/english-names-b2d` en `71846c1` instalada en el daemon
(`local-delegate v0.35.0`, `LOCAL_DELEGATE_STRUCTURED_SUMMARY=1`). Cada tool se llamó una vez por
documento, en serie, por el MCP vivo, con `path=<ruta absoluta>` y valores por defecto.

| Tanda | Producto | Idioma pedido | Ventana de pruebas | Detalle |
|---|---|---|---|---|
| 1 | `es` | inglés | `w-20261015T150634Z` | `lang-sample-batch1.json` |
| 2 | `en` | español | `w-20261015T152547Z` | `lang-sample-batch2.json` |

Juez: `scripts/detect_language.py`, `detect(min_tokens=20, min_margin=0.15)`, sobre la respuesta
literal menos las líneas propias del producto (`(leído/read server-side: …)`,
`[local-delegate warning: …]`, `(sin resumir)`/`(not summarized)`). Los títulos y etiquetas
copiados del documento **sí** cuentan. Criterio: ≥ 90 % en el idioma pedido por tool y tanda,
0 en el idioma contrario y 0 secciones duplicadas.

Conjuntos: el 2 es `B2d-fix/lang-sample-docs-2.json` (sha256 `a7b333a448731b4574d2e58e34a4466267ffc78211d914faa1846d1486543a22`, verificado; los
20 documentos con su sha256 congelado intacto); el 1 es `B2d/lang-sample-docs.json` (los mismos
documentos que la medición de antes, `B2/lang-sample.json`).

## Resultado por tool, conjunto y tanda

| Tool | Conjunto | Tanda 1 (pide inglés) | Tanda 2 (pide español) | Contrario | Duplicadas |
|---|---|---|---|---|---|
| `local_summarize` | 2 | 3/5 (60 %) | 5/5 (100 %) | 0 | 0 |
| `local_summarize` | 1 | 4/5 (80 %) | 5/5 (100 %) | 0 | 0 |
| `local_lint_summary` | 2 | 3/5 (60 %) | 5/5 (100 %) | 0 | — |
| `local_lint_summary` | 1 | 5/5 (100 %) | 4/5 (80 %) | 0 | — |

Cumplen el criterio: summarize en la tanda 2 (los dos conjuntos) y lint_summary en la tanda 1 del
conjunto 1 y en la tanda 2 del conjunto 2. No lo cumplen: summarize en la tanda 1 (60 % y 80 %),
lint_summary en la tanda 1 del conjunto 2 (60 %) y en la tanda 2 del conjunto 1 (80 %).

## Total combinado frente a la medición de antes

Mismos documentos (conjunto 1) y mismas combinaciones que `B2/lang-sample.json`:

| Tool | Antes (B2) | Ahora (B2d-fix, conjunto 1) | Ahora, los dos conjuntos |
|---|---|---|---|
| `local_summarize` | 8/10 (80 %) | 9/10 (90 %) | 17/20 (85 %) |
| `local_lint_summary` | 6/10 (60 %) | 9/10 (90 %) | 17/20 (85 %) |
| summarize + lint_summary | 14/20 (70 %) | 18/20 (90 %) | 34/40 (85 %) |

El total de antes, 34/40, sumaba también `local_explain_code` (10/10) y `local_describe_image`
(10/10), que esta ronda no vuelve a medir; la comparación justa es la fila de summarize + lint_summary
(14/20 antes, 18/20 ahora). Ninguna de las 40 respuestas sale en el idioma contrario, y ninguna
respuesta de summarize repite sección (ni `Introducción` + `Introduction`).

## Los fallos

Todos son «desconocido» por margen bajo; ninguno es una respuesta en el idioma equivocado.

| Tanda | Conjunto | Tool | Documento | Causa |
|---|---|---|---|---|
| 1 | 2 | summarize | `es-doc-docs_Investigacion-empaquetado-publicacion-MCP.md` | títulos y etiquetas en español copiados del documento |
| 1 | 2 | summarize | `es-doc-docs_plans_plan-f6-vision.md` | títulos y etiquetas en español copiados del documento |
| 1 | 1 | summarize | `docs/wiki/Daemon.md` | títulos y etiquetas en español copiados del documento |
| 1 | 2 | lint_summary | `es-log-B1b_doctor_es_complete.txt` | etiquetas de chequeo en español en líneas telegráficas, pocas palabras funcionales |
| 1 | 2 | lint_summary | `es-log-B1b_doctor_es_empty.txt` | etiquetas de chequeo en español copiadas del informe |
| 2 | 1 | lint_summary | `resume-ruff-cinco-reglas.txt` | respuesta en español de 37 tokens; los códigos de regla y palabras clave cuentan como inglés: `I001` → «i» (×3), `UP006` → «up», «`if`s anidados» → «if» (×2) |

El fallo de la tanda 2 **no** es de títulos ni etiquetas copiados: es un artefacto del detector con
textos muy cortos llenos de códigos. Quitando títulos y etiquetas empeora (pasa a «inglés», 23 tokens).

## Diagnóstico aparte (no oficial): sin títulos `#` ni etiquetas `**…**`

| Tanda | Conjunto | summarize | lint_summary |
|---|---|---|---|
| 1 | 2 | 5/5 | 3/5 (`doctor_es_complete` sigue desconocido; `en-log-pytest` cae a 16 tokens) |
| 1 | 1 | 5/5 | 5/5 |
| 2 | 2 | 5/5 | 5/5 |
| 2 | 1 | 5/5 | 4/5 (`resume-ruff-cinco-reglas` pasa a «inglés») |

En la tanda 1 los fallos de summarize desaparecen al quitar los títulos y etiquetas copiados; en la
tanda 2 no hay ninguno que explicar por esa vía.

## Cotejo de las copias con el log del daemon

Cada respuesta guardada se contrastó con `chars_out` de su fila en
`%LOCALAPPDATA%\local-delegate\usage-202610.jsonl` (misma tool y misma ruta). `chars_out` es la
longitud del texto antes de que se añada la línea final `(leído/read server-side: …)`, así que la
comparación es «longitud de la copia sin esa línea = `chars_out`».

- Tanda 2: 20 de 20 cuadran.
- Tanda 1 (copiada a mano en su día, sin rehacer): 20 de 20 cuadran.

## Otras observaciones

- Dos respuestas de lint_summary de la tanda 2 llegan a `max_tokens` (`es-log-B2c_corpus-affinity-check.txt`
  y `lint-9k.txt`, servidas por `gemma4-26b-a4b`); el aviso de truncado es línea del producto y no se juzga.
- El resumen de `httpx2` deja un título `## Release Information` vacío seguido del aviso
  «1 section not summarized».
