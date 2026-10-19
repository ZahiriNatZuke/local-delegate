# Muestras de idioma que faltaban para cerrar REQ-028 (2026-10-19)

Encargo: los dos huecos de REQ-028 que dejó la revisión de conformidad: (a) ninguna respuesta del
modelo en vivo con `LOCAL_DELEGATE_OUTPUT_LANGUAGE=fr`; (b) `local_explain_code` y
`local_describe_image` con 1 documento por idioma, cuando la spec pide al menos 5.

Versión medida: la **0.36.0 publicada**, instalada con `uv tool` y servida por el daemon (no se
reinstaló; se reinició solo para cambiar el idioma, ver «Cómo se cambió el idioma de cada tanda»).

## Criterio, fijado antes de medir

En `manifest.json` (congelado con los sha256 de los documentos antes de la primera llamada, por
`build_manifest.py`): por tanda y tool, sobre las 15 respuestas (5 documentos distintos × 3
repeticiones), **al menos el 90 % con veredicto `requested` y 0 en otro idioma**; un error o un
`not_judgeable` cuenta como fallo. Es el umbral de REQ-028 («al menos 5 documentos por tool e
idioma, todos en el otro idioma, y al menos el 90 % de las respuestas en el idioma vigente»).

- Juez es/en: `scripts/judge_response_language.py` («solo prosa», reglas en
  `evidence/B2d-fix/judge-rules.md`), sin cambios. Imágenes contra un documento vacío, como en
  `evidence/live-036/judge.sh`.
- Juez fr: el detector versionado solo sabe es/en, así que se añadió `fr_judge.py` (solo
  evidencia): mismas reglas de prosa, mismos umbrales (20 palabras, margen 0,15) y una tercera lista
  cerrada de palabras funcionales francesas. Ver «Juez francés y sus controles».
- Aquí no hay cambio de prompt ni comparación A/B: las 3 repeticiones de cada documento llevan el
  prompt idéntico y sirven de control de ruido (una respuesta que cambie de idioma entre
  repeticiones se vería en `judge.jsonl`).

## Documentos (todos en el otro idioma)

| Tanda | Tool | Documentos |
|---|---|---|
| ES (pide español) | `local_explain_code` | código documentado en inglés: `src/local_delegate/lint_patterns.py`, `evidence/B2d-3/check_controls.py`, `evidence/B2f/compare.py`, `evidence/B2-affinity/scorer_v2_check.py`, `evidence/B2e/validate_counter.py` |
| ES | `local_describe_image` | capturas del panel en inglés: `B4/screenshots/dialog-cost-en-light.png`, `dialog-cost-en-dark.png`, `header-en-dark.png`, `panel-en-light.png`, `live-036/panel-en-US-dark.png` |
| EN (pide inglés) | `local_explain_code` | código documentado en español: `src/local_delegate/pricing.py`, `entrypoint.py`, `scripts/build_site.py`, `scripts/clean_watcher_fixtures.py`, `scripts/sync_wiki.py` |
| EN | `local_describe_image` | capturas en español: `B4/screenshots/dialog-cost-es-light.png`, `dialog-cost-es-dark.png`, `header-es-dark.png`, `panel-es-light.png`, `live-035/panel-claro.png` |
| FR (producto `es` + variable `fr`) | las cuatro tools | 5 documentos por tool, mezcla de es y en (ninguno en francés); lista en `manifest.json` |

Los ficheros de código tienen menos de 200 líneas (un solo trozo). Las capturas son las ya
publicadas en el repo (ninguna `pagina-es-*-1440.png`, que llevan datos de la PC).

## Resultado

| Tanda | Ventana de prueba | Tool | `requested` | Otro idioma | Errores | Veredicto (criterio congelado) |
|---|---|---|---|---|---|---|
| ES | `w-20261019T041119Z` (04:11:19Z–04:16:46Z) | `local_explain_code` | 15/15 (100 %) | 0 | 0 | CUMPLE |
| ES | `w-20261019T041119Z` | `local_describe_image` | 15/15 (100 %) | 0 | 0 | CUMPLE |
| EN | `w-20261019T043654Z` (04:36:54Z–04:41:46Z) | `local_explain_code` | 15/15 (100 %) | 0 | 0 | CUMPLE |
| EN | `w-20261019T043654Z` | `local_describe_image` | 15/15 (100 %) | 0 | 0 | CUMPLE |
| FR | `w-20261019T044210Z` (04:42:10Z–04:52:26Z) | `local_summarize` | 14/15 (93 %) | 0 | 0 | CUMPLE (1 `unknown`: FR-S03 r1, margen 0,135) |
| FR | `w-20261019T044210Z` | `local_lint_summary` | 12/15 (80 %) → **15/15 (100 %)** con R1 ampliado | 0 | 0 | NO CUMPLE con el juez de `main`; **CUMPLE** re-juzgado (ver abajo) |
| FR | `w-20261019T044210Z` | `local_explain_code` | 15/15 (100 %) | 0 | 0 | CUMPLE |
| FR | `w-20261019T044210Z` | `local_describe_image` | 15/15 (100 %) | 0 | 0 | CUMPLE |

Respuestas literales: `answers/<tanda>/*.txt`; veredictos: `answers/<tanda>/judge.jsonl`; tiempos:
`answers/<tanda>/live-runs.json`. En las tres tandas `run_samples.py` comprobó con `local_status`
que el idioma de respuesta del daemon era el de la tanda (`es`, `en`, `fr`) antes de llamar.

### El fallo de `local_lint_summary` en fr es del juez, no del modelo

Los 3 `unknown` son las tres repeticiones de FR-L02 (`en-log-pytest.txt`), respuesta idéntica de
503 chars. La prosa del modelo está en francés («Tests réussis : 15 tests ont été validés avec
succès»). Lo que inclina el recuento es la línea que añade el **producto**, «Sin mencionar (del
log, no los nombra el resumen): …», que va en el idioma de la interfaz (`es`, como manda REQ-028:
la variable de salida no cambia los textos de interfaz) y que la regla R1 del juez no conoce (R1
solo quita «(leído server-side: …)», los avisos y «(sin resumir)»). En una respuesta de 30 palabras
juzgables, esa línea baja el margen a 0,067.

Recuento secundario, **no** el veredicto oficial: quitando solo esa línea de producto (mismo
espíritu que R1), lint fr da 15/15, aunque FR-L02 queda con 21 palabras (el mínimo es 20). El
criterio se fijó antes de medir y no se cambia a la vista del fallo: el veredicto oficial sigue
siendo 12/15. Salida propuesta: un lote corto que añada a R1 la línea «Sin mencionar (…)» /
«Not mentioned (…)» (con su test y su mutante) y vuelva a juzgar estas respuestas, sin repetir
llamadas.

### Re-juicio con la regla R1 ampliada (sin llamadas nuevas)

Rama `fix/judge-r1-not-mentioned` (commit `769c3c2`, desde `origin/main`): R1 quita también la
línea «Sin mencionar (…): …» / «Not mentioned (…): …». Su texto sale del catálogo (claves
`mcp.lint.not_mentioned` y `mcp.explain.not_mentioned`, en todos sus idiomas: hoy es y en), no de
un literal. Tests: la línea se quita en cada idioma y clave; guarda de que el catálogo aporta es y
en; control positivo (el mismo texto dentro de una frase sí se juzga). Mutante (quitar la
comprobación en `prose()`): falla solo `test_r1_the_not_mentioned_line_is_dropped_in_every_language`,
en el assert de tokens (32 ≠ 19).

Las 120 respuestas guardadas se volvieron a juzgar con ese juez (`judge_samples.py --scripts-dir
D:/Projects/ld-wt-judge/scripts --out judge-r1.jsonl`); el criterio es el mismo.

- ES y EN: 0 cambios de veredicto y 0 cambios de recuento de palabras (60 filas).
- FR: cambian solo las 3 filas de FR-L02 (`unknown` → `requested`, 30 → 21 palabras juzgables);
  son las únicas respuestas de las tres tandas que llevan esa línea. Lint fr: **15/15**.
- Ninguna otra combinación cambia de veredicto. FR-L02 queda a 1 palabra del mínimo (20): es una
  respuesta corta de un log de pytest sin fallos.

`answers/<tanda>/judge.jsonl` es el juicio con el juez de `main` y `judge-r1.jsonl` el re-juicio.

## Cómo se cambió el idioma de cada tanda

El idioma vigente se cachea al arrancar el proceso (`i18n.current()`) y
`LOCAL_DELEGATE_OUTPUT_LANGUAGE` se lee del entorno del daemon, así que no hay forma por llamada.
Con permiso expreso del coordinador para estas dos tandas, el método fue el de B2d-2: una línea
temporal en el lanzador del daemon y reinicio por la tarea programada (`schtasks /End`, matar el
pid de `daemon.json`, `schtasks /Run`; el lanzador pone la credencial del backend, que no se leyó).

| Tanda | Línea temporal en el lanzador | pid del daemon |
|---|---|---|
| ES | ninguna (`language.json` = `es`) | 35336 |
| EN | `$env:LOCAL_DELEGATE_LANG = 'en'` | 41768 |
| FR | `$env:LOCAL_DELEGATE_OUTPUT_LANGUAGE = 'fr'` (producto `es`) | 58220 |
| restaurado | ninguna | 24316 |

Al terminar, el lanzador volvió a su huella original (sha256 `c96f022a…f69f69a`, idéntico byte a
byte a la copia previa) y, tras el último reinicio, `local_status` informa de `local-delegate
v0.36.0`, «Idioma: es (preferencia …)» e «Idioma de respuesta del modelo: es (preferencia)».

## Juez francés y sus controles

- `fr_judge.py` versión 2. La versión 1 solo quitaba de la lista francesa las palabras que
  comparte con es/en; el control positivo salió **8 de 8 `unknown`**
  (`fr-control-positive-v1.jsonl`): `de`, `la`, `le`, `en`, `que`, `un`, `les` contaban como
  español. La versión 2 quita esas palabras compartidas de las **tres** listas, que es lo mismo que
  ya hace el detector con las que comparten es y en. El juez del producto no se toca.
- Control positivo (`fr_control_positive.py`, ventana `w-20261019T041811Z`): 8 respuestas reales
  (4 de la tanda ES, 4 de B2d-2: resumen y lint, de documentos es y en) traducidas al francés con
  `local_translate`, en `fr-control/`. Versión 2: **8 de 8 `fr`**, margen 0,156–0,256.
- Control negativo (`fr_judge_controls.py`): 74 respuestas en es/en (44 de B2d-2 y las 30 de la
  tanda ES): **0 `fr`** (28 es, 23 en, 23 `unknown`; los `unknown` vienen de que, al quitar las
  palabras compartidas, la lista española pierde peso; para decidir «francés sí o no» da igual).

## Ficheros

`build_manifest.py`, `manifest.json`, `run_samples.py`, `judge_samples.py`, `fr_judge.py`,
`fr_control_positive.py`, `fr_judge_controls.py`, `fr-control/`, `fr-control-*.jsonl`,
`answers/ES/`, `answers/EN/`, `answers/FR/`.
