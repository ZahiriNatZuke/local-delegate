# Verification: local_extract: aviso de valor cruzado entre claves y subida al rol long en tablas (#586)

## Environment

- Revision: `ff8f1efc` (rama `feat/usage-log-project-t5`); nada de este cambio instalado ni escrito en `src/`.
- Relevant runtime and tool versions: daemon y segundo proceso con el paquete publicado
  `local-delegate-mcp` 0.50.0 (`uv tool`); backend local `127.0.0.1:9292`; `gemma3-4b` (rol
  `mechanical`) y `gemma4-26b-a4b` (rol `long`); Python 3.14 para los scripts de `gate/`.

## Puerta (T1)

Medida el 2026-11-10 entre las 12:24 y las 12:35 (hora de Uruguay), dentro de la ventana de prueba
`w-20261110T152416Z` (etiqueta `sdd-586-t1`, 33 filas, cerrada a las 12:34:01). Una llamada cada
vez y al menos 3 s entre llamadas (comprobado en las horas de las filas del log).

### Veredicto (tabla «Puertas» de la spec, aplicada literalmente)

| Puerta | Criterio | Medido | Resultado |
| --- | --- | --- | --- |
| Enrutado | REQ-001 (1): cruce en 1 caso como mucho de los 8 que cruzaron con `gemma3-4b` | 0 de 8 casos; 0 claves cruzadas de 39 | pasa |
| Enrutado | REQ-001 (2): 1 clave fallada como mucho de 44 en los 8 limpios | 0 de 44 | pasa |
| Enrutado | REQ-001 (3): ninguna respuesta con `error`/`raw` | 0 de 16 | pasa |
| Enrutado | REQ-003: mediana de inferencia ≤ 6,5 s | 2,944 s (mín. 1,918 s; máx. 6,085 s) | pasa |
| Enrutado | REQ-007: la fuente congelada de `extraer-toml-2k` no trae tabla y `tests/test_corpus.py` pasa sin tocar | `has_table` = `False`; 63 passed | pasa |
| Aviso | REQ-004 (1): 0 avisos sobre las respuestas anotadas a mano | **1 aviso** (`c01/price`) | **falla** |
| Aviso | REQ-004 (2): 0 avisos sobre las respuestas de `gemma3-4b` en las claves sin cruce | **1 aviso** (`c01/price`, valor correcto) | **falla** |

**Enrutado: pasa. Aviso: falla.** Combinación «Pasa / Falla» de la spec: el enrutado sigue y se
publica; el aviso no entra en esta versión y vuelve a diseño en un cambio SDD nuevo con su propia
puerta. Las enmiendas que eso pide (Non-goals, transición en `state.json`, `[-]` en T4 y en el
commit del aviso de T5) son de la sesión coordinadora; T1 no las hace.

El aviso en falso, dicho con el caso: en `c01` (hervidor, inglés, HTML) la clave `price` vale `39`
y su fila es «Retail cost (USD)», que no comparte ninguna palabra con `price`; el mismo `39` está en
la fila «Noise level (dB)», que casa con la clave pedida `noise_level`. La regla estricta lo marca
como `{"row": "Noise level (dB)", "other_key": "noise_level"}`. Es exactamente el cupo «número
repetido en dos filas con la fila propia de etiqueta sinónima» que la revisión había anticipado. El
umbral es 0 y no se ajusta: un solo caso basta para que falle.

### Versión del detector que se congela

- `gate/detector_frozen.py`: copia byte a byte de `detector.py`, `sha256`
  `0b940737e792a6787ef96c02f64227046225ca08446f621b77fab67a359a18d7`; variante estricta,
  `LONG_CELL_CHARS = 60`.
- Comprobación: sobre las cuatro corridas grabadas marca exactamente lo mismo que
  `outputs/evaluation.json` (idéntico en `g3-extract`, `g3-proxy`, `g4-proxy` y `g4-extract`).
- **La corrección de plurales no se aplicó ni se midió.** La spec dice dos veces (REQ-004 y
  «Traceability») que esa corrección «solo puede hacerse antes de congelar el conjunto nuevo», y
  `holdout/` ya estaba congelado (11:14) cuando empezó T1; el paso 2 del plan la coloca después del
  conjunto. Se siguió la spec. No cambia el veredicto: el único aviso en falso es de número
  repetido, no de plurales, y la corrección de plurales no lo toca.

### Conjunto nuevo (`holdout/`, REQ-004 y REQ-005)

- `sha256sum -c SHA256SUMS`: 25 de 25 `OK` (el `cases.json` y los 24 ficheros de `inputs/`),
  antes de usarlo. No se modificó.
- 24 casos, 115 pares (caso, clave) distintos, 113 con valor no nulo, en español y en inglés.
- Cupos contados por programa sobre las respuestas a mano (`gate/gate_offline.py`): número repetido
  con etiqueta sinónima 2 casos (c01, c02); subcadena de la fila de otra clave 2 (c03, c04); celda
  propia de más de 60 caracteres 2 (c05: 79, c06: 81); plurales `-ies` 2 (c07, c08); plurales `-es`
  2 (c09, c10); tablas con claves parecidas 4 (c11 a c14); JSON con prosa 2 (c15, c16); líneas
  `etiqueta: frase` 2 (c17, c18); CSV 2 (c19, c20) y un TSV (c21). Todos llegan al mínimo; en
  ningún cupo el valor anotado difiere del valor del cupo.

| Pasada | Claves sin cruce | Avisos (falsos) | Cruces reales | Cruces marcados |
| --- | --- | --- | --- | --- |
| 1. Sin modelo, respuestas anotadas a mano | 115 | 1 (`c01/price`) | — | — |
| 2. `gemma3-4b` por el producto | 115 | 1 (`c01/price`) | 0 entre claves pedidas | 0 |
| Control positivo: respuestas cruzadas a mano (`crossed`, no cuenta) | — | 1 (`c01/price`) | 49 | 27 |

Respuestas de `gemma3-4b` sobre el conjunto nuevo (`outputs/gate-g3-holdout.json`, puntuadas en
`outputs/gate-g3-holdout-score.json`): 110 de 115 exactas; 0 `error`/`raw`; 0 cruces entre claves
pedidas. Las 5 que no coinciden, con veredicto a mano tras leer la fuente: `c08/fleet_size` `22`
por «22 vans» y `c12/descuento` `10` por «10 %» (fila propia, sin unidad); `c22/seeds_optional`
`true` por «yes» (fila propia); `c19/basic_plus_support` `"email"` por «email and chat» (trozo de la
celda propia y, a la vez, la celda entera de la fila «Basic»: ambiguo); `c20/precio_rebajado_pantalon_m`
`"39,90"` donde la celda está vacía (el valor es la columna «precio» de la misma fila, que nadie
pidió).

**REQ-005 (CSV):** en `c20` el modelo rellenó una celda vacía con la celda vecina de su fila, una
celda que nadie pidió: cruza, aunque no con otra clave pedida. En `c19` no hay cruce claro (el caso
ambiguo de arriba). Pasa al issue de seguimiento de REQ-039; la regla no cambia en este cambio.

### Un solo campo (REQ-002)

`gemma3-4b` por el MCP del daemon, una clave por llamada (`outputs/gate-g3-single.json`),
puntuadas con `evaluate.classify` y la anotación de `cases/cases.json`:

| Caso / clave | Esperado | Respuesta | Veredicto |
| --- | --- | --- | --- |
| 01 y 02 / `licensed_user_limits` | `null` | `"1–5, 1–3 per region, 600, 6 000, 30 days, 365 days"` | cruce (fila «Custom domains») |
| 06 / `limite_usuarios_con_licencia` | `null` | `75` | cruce (fila «Límite de usuarios activos») |
| 12 / `ip_allowlist` | `null` | `null` | bien |
| 21 / `storage_per_user` | `null` | `"2 TB"` | cruce (fila «Storage per workspace») |
| 21 / `api_requests_per_day` | `null` | `"6 000"` | cruce (fila «API requests per minute») |
| 22 / `almacenamiento_por_usuario` | `null` | `"25 GB"` | cruce (fila «Almacenamiento por proyecto») |
| 23 / `puestos_adicionales` | `null` | `"5"` | cruce (fila «Puestos incluidos») |
| 26 / `enterprise_seats` | `null` | `250` | cruce (fila «factory seats») |

1 de 8 bien, 7 mal: el enrutado dispara también con un campo. **`_TABLE_LONG_MIN_FIELDS = 1`.**
Por el plan («Mutantes»), con el mínimo en 1 el mutante del mínimo y su test se retiran.

### Tanda con `gemma4-26b-a4b` (REQ-001, REQ-003)

`outputs/gate-g4-research.json` (respuestas, filas del log temporal y puntuación con
`evaluate.classify`):

| Caso | Grupo | Claves | Acertadas | Cruzadas | Falladas | Inferencia (ms) |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | cruzó con `gemma3-4b` | 5 | 5 | 0 | 0 | 6085 |
| 02 | cruzó | 3 | 3 | 0 | 0 | 2352 |
| 06 | cruzó | 5 | 5 | 0 | 0 | 3156 |
| 12 | cruzó | 5 | 5 | 0 | 0 | 2403 |
| 21 | cruzó | 5 | 5 | 0 | 0 | 3176 |
| 22 | cruzó | 5 | 5 | 0 | 0 | 2943 |
| 23 | cruzó | 5 | 5 | 0 | 0 | 3240 |
| 26 | cruzó | 6 | 6 | 0 | 0 | 2404 |
| 07 | limpio | 6 | 6 | 0 | 0 | 2945 |
| 08 | limpio | 6 | 6 | 0 | 0 | 3373 |
| 09 | limpio | 6 | 6 | 0 | 0 | 4046 |
| 10 | limpio | 4 | 4 | 0 | 0 | 1918 |
| 11 | limpio | 4 | 4 | 0 | 0 | 2088 |
| 17 | limpio | 6 | 6 | 0 | 0 | 2473 |
| 24 | limpio | 6 | 6 | 0 | 0 | 3690 |
| 25 | limpio | 6 | 6 | 0 | 0 | 2822 |

Las 16 filas del log temporal llevan `tool: local_extract`, `model: gemma4-26b-a4b`,
`remote_turn: granted`, `json_schema: used` y `finish_reason: stop`; ninguna respuesta trae
`error` ni `raw`. Mediana de inferencia 2944 ms (mín. 1918, máx. 6085). La puntuación discrimina:
el mismo `evaluate.classify` marca como cruce 7 de las 8 respuestas de un campo de `gemma3-4b`.

### Vía de la tanda grande (REQ-006)

- Visto bueno del usuario: dado hoy para la vía A (segundo proceso del producto que hereda la
  credencial con una tarea programada temporal creada desde una copia del lanzador seguro).
- Copia del lanzador: solo cambia el entorno (`LOCAL_DELEGATE_LONG_INPUT_CHARS=0`, `LOG_DIR` y
  `LOG` temporales, `LOCAL_DELEGATE_WEB_PORT=9394`, `LOCAL_DELEGATE_TURN_URL=http://127.0.0.1:9393/`,
  `LOCAL_DELEGATE_REMOTE_WEB_TOKEN` desde la variable de usuario del token web, `Remove-Item
  Env:LLAMASWAP_CONFIG`) y el comando (`pythonw -I gate/run_g4.py`). La credencial la resolvió el
  mismo mecanismo DPAPI del original; nadie la leyó ni la imprimió. En el `LOG_DIR` temporal, copias
  de `backend-params.json` (mismo `sha256` que el del daemon) y de `language.json` (preferencia de
  idioma, para que el proceso hable igual que el daemon).
- Entorno visto por el proceso: versión 0.50.0, `LONG_INPUT_CHARS=0`, `WEB_PORT=9394`, `TURN_URL`
  a `127.0.0.1:9393`, sin `LLAMASWAP_CONFIG`, token remoto presente.
- Llamada de validación sin tabla (`name`, `city` sobre una frase): fila del log temporal con
  `remote_turn: granted`, `model: gemma4-26b-a4b`, `model_swap: true`; a la vez el `inflight.json`
  del daemon mostró la entrada `remote:<host>/46640-1` con `tool: local_extract`, `source: remote`,
  `host_via: lease`. Pasa.
- Al acabar, una llamada pequeña sin tabla por el MCP del daemon fue a `gemma3-4b` y `local_status`
  mostró `llama-swap /running: gemma3-4b (ready)`.

### Cambios de modelo en el backend compartido

| Hora (Uruguay) | Cambio | Por qué |
| --- | --- | --- |
| 12:24:27 | carga en frío de `gemma3-4b` (no había ningún modelo montado) | primera llamada de la tanda 3 |
| 12:31:02 | `gemma3-4b` → `gemma4-26b-a4b` | llamada de validación del segundo proceso |
| 12:33:44 | `gemma4-26b-a4b` → `gemma3-4b` | llamada de comprobación por el MCP al acabar |

Dos cambios de modelo provocados (ida y vuelta) y una carga inicial.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | 16 casos con `gemma4-26b-a4b` por `local_extract` en el segundo proceso | pass | `outputs/gate-g4-research.json`; 0 de 8 casos cruzan, 0 de 44 claves falladas, 0 `error`/`raw` |
| REQ-002 | 8 claves solas con `gemma3-4b` por el MCP del daemon | pass (valor fijado: 1) | `outputs/gate-g3-single.json`; 1 de 8 bien → `_TABLE_LONG_MIN_FIELDS = 1` |
| REQ-003 | mediana de inferencia de los 16 casos | pass | 2944 ms (1918–6085) ≤ 6500 ms |
| REQ-004 | detector congelado sobre `holdout/`, sin modelo y con `gemma3-4b` | puerta del aviso, fuera de esta versión | 1 aviso en falso en cada pasada (`c01/price`); `outputs/gate-offline.json`, `outputs/gate-g3-holdout-score.json` |
| REQ-005 | caso CSV con `gemma3-4b` | puerta del aviso, fuera de esta versión | `c20`: celda vacía rellenada con la vecina no pedida; `c19`: ambiguo; va al seguimiento de REQ-039 |
| REQ-006 | vía A con validación del turno | pass | fila temporal `remote_turn: granted` y entrada `remote:<host>/46640-1` en el daemon |
| REQ-007 | `has_table` del prototipo sobre `extraer-toml-2k.toml` y `tests/test_corpus.py` | pass | `False` (`outputs/gate-offline.json`); `63 passed` |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `sha256sum -c SHA256SUMS` (en `holdout/`) | 2026-11-10 12:2x | 25 OK | salida de la sesión |
| `python -I gate/gate_offline.py` | sí | REQ-004 pasada 1, cupos, REQ-007, cordura | `outputs/gate-offline.json` |
| `python -I gate/score_holdout.py` | sí | REQ-004 pasada 2, REQ-005 | `outputs/gate-g3-holdout-score.json` |
| `python -I gate/score_g4.py <out> <log temporal>` | sí | REQ-001, REQ-003 | `outputs/gate-g4-research.json` |
| `pesado.sh .venv/Scripts/python.exe -m pytest tests/test_corpus.py -q -n 2` | sí | 63 passed | salida de la sesión |

## Quality checks

- [ ] Project-native tests pass.
- [ ] Lint, formatting, type checking, and build checks pass where applicable.
- [ ] Secret scanning passes.
- [ ] No unrelated changes are present.

## Deviations and residual risk

- La corrección de plurales no se aplicó (ver «Versión del detector que se congela»): la spec y el
  plan no coinciden en cuándo se decide; se siguió la spec. No cambia el veredicto.
- El segundo proceso no prueba la capa MCP por HTTP, el middleware de cancelación ni las plazas
  compartidas con otras sesiones (ver el plan); para la pregunta de la puerta es el mismo código.
- `gemma3-4b` no cruzó entre claves pedidas en el conjunto nuevo, así que la pasada 2 solo mide
  avisos en falso, no aciertos del detector.
