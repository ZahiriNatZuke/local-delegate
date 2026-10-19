# Muestras de idioma que faltaban para cerrar REQ-028 (2026-10-19)

Encargo: los dos huecos de REQ-028 que dejó la revisión de conformidad: (a) ninguna respuesta del
modelo en vivo con `LOCAL_DELEGATE_OUTPUT_LANGUAGE=fr`; (b) `local_explain_code` y
`local_describe_image` con 1 documento por idioma, cuando la spec pide al menos 5.

Versión medida: la **0.36.0 publicada**, instalada con `uv tool` y servida por el daemon tal como
estaba (no se reinstaló ni se reinició).

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

| Tanda | Ventana de prueba | Tool | `requested` | Otro idioma | Errores | Veredicto |
|---|---|---|---|---|---|---|
| ES | `w-20261019T041119Z` (04:11:19Z–04:16:46Z) | `local_explain_code` | 15/15 (100 %) | 0 | 0 | CUMPLE |
| ES | `w-20261019T041119Z` | `local_describe_image` | 15/15 (100 %) | 0 | 0 | CUMPLE |
| EN | — | `local_explain_code`, `local_describe_image` | sin medir | | | PENDIENTE |
| FR | — | las cuatro | sin medir | | | PENDIENTE |

Respuestas literales: `answers/ES/*.txt`; veredictos: `answers/ES/judge.jsonl`; tiempos:
`answers/ES/live-runs.json`. Ninguna respuesta pasó por el contexto de Claude.

## Por qué EN y FR quedan sin medir: el idioma no se puede cambiar por llamada

- El idioma vigente se cachea al arrancar el proceso (`i18n.current()`, `functools.cache`) y sale
  de `LOCAL_DELEGATE_LANG` o de `language.json` (hoy `es`). `LOCAL_DELEGATE_OUTPUT_LANGUAGE` se lee
  en cada llamada (`i18n.response_language()`), pero del entorno **del daemon**, que es el de su
  lanzador. Ninguna tool acepta el idioma como argumento.
- B2d-2 y la pasada de la 0.36.0 lo cambiaron **reiniciando el daemon** (variables en el lanzador o
  `install` con otro `LOCAL_DELEGATE_LANG`). Este encargo prohibía reiniciarlo (tira el MCP de la
  sesión que orquesta), así que solo se pudo medir la tanda cuyo idioma coincide con el del daemon.
- Levantar un segundo servidor MCP con otro entorno contra el mismo backend necesita la credencial
  del backend que guarda el lanzador cifrada; no se tocó.

`run_samples.py` comprueba antes de llamar que `local_status` informa del idioma de respuesta que
pide la tanda, y para (código 3) si no coincide: así una tanda no puede medirse con el idioma
equivocado.

### Cómo cerrar las dos tandas pendientes (necesita reiniciar el daemon dos veces)

```bash
# Tanda EN: el lanzador con $env:LOCAL_DELEGATE_LANG = 'en'; reiniciar el daemon; /mcp en la sesión.
local-delegate test-window start --label "REQ-028 muestras en (explain_code, describe_image)"
bash ~/.claude/scripts/pesado.sh python run_samples.py --window EN --repeat 3
python judge_samples.py --window EN
local-delegate test-window stop <id>
# Tanda FR: el lanzador con $env:LOCAL_DELEGATE_OUTPUT_LANGUAGE = 'fr' (sin LANG); reiniciar.
local-delegate test-window start --label "REQ-028 muestras fr (4 tools)"
bash ~/.claude/scripts/pesado.sh python run_samples.py --window FR --repeat 3
python judge_samples.py --window FR
local-delegate test-window stop <id>
# Devolver el lanzador a su huella original y reiniciar.
```

Duración estimada por tanda: la ES (30 llamadas) tardó 5 min 27 s; la FR (60 llamadas, con
resúmenes y lint) unos 20–30 min.

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
`answers/ES/`.
