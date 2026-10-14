# Cierre del frente A — fase 1: inventario y propuesta (2026-10-14)

Rama `sdd/english-names-a-close` (desde `main` `dc5081b`, A0–A10 mezcladas). Esta fase **no toca
código ni datos**: inventaría lo que queda, propone cómo cerrarlo y para. Todo lo que se cita está en
`evidence/A-close/` y en los tres mappings `A-close-1` a `A-close-3` de `waves/` (el registro cita con ruta solo los lotes ya aplicados, que son los que cuenta `check_wave_records.py`).

## 0. Qué exige el cierre (plan §A10b y spec)

- **Plan, «Cierre del frente A (al final de A10b)»**: primera corrida del detector de REQ-016 en
  `evidence/A-close/detector.json`; tiene que dar **0 fuera de `rename-exceptions.md`**, con la
  sección «Pendiente» **solo con REQ-010** y **sin palabras «sin clasificar»**; los tests de control
  de REQ-044 en verde.
- **REQ-016**: el detector sobre `src/`, `tests/`, `scripts/` y el JS del panel (identificadores,
  claves de cadena, **valores de enumeración persistidos**, ids del DOM), los `.json` de
  `src/**/resources` y los nombres de fichero da 0 fuera de la lista. Motivos válidos: alias de
  compatibilidad (con versión de retirada), lectura de formato viejo, envoltorio de REQ-046, dato de
  un tercero, dato de prueba del detector, y las tres enmiendas ya aprobadas (palabra inglesa que el
  léxico toma por española; dato congelado de corpus o caso; entrada de interfaz escrita por una
  persona), más **pendiente** (solo las subclaves y marcadores de REQ-010, que salen en B2).
- **REQ-044**: las palabras «sin clasificar» bloquean el cierre de REQ-016.
- **REQ-010**: `_local_delegate` pasa a `truncated`, `warning`, `read_server_side.{chars,
  approx_tokens}`, `fallback.{answered_by, instead_of, reason, class}` y `raw`; se publica en B
  (B2), sin emisión doble.

## 1. Estado de hoy (antes de cerrar)

| Control | Hoy | ¿Cumple? |
| --- | --- | --- |
| Detector con la lista (`evidence/A-close/detector-before.json`) | 960 únicos, **741 fuera de la lista** | No |
| Palabras «sin clasificar» | **777** (776 inglesas + `aprobada`) | No |
| Sección «Pendiente» | **vacía**, pero las 29 apariciones de REQ-010 no están en ninguna fila | No |
| Tests de control de REQ-044 (`tests/test_detect_spanish_names.py`) | **41 passed** (`evidence/A-close/req044-tests-before.txt`) | Sí |
| Tests recogidos (`evidence/A-close/collect-before.txt`) | **2601** | Base |

Comando: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/detect_spanish_names.py
--exceptions .sdd/changes/english-names-bilingual-output/rename-exceptions.md --json
.sdd/changes/english-names-bilingual-output/evidence/A-close/detector-before.json`.

## 2. Clasificación de los 741 hallazgos

Por reglas explícitas (scratchpad `a-close/classify.py`), fila a fila en
`evidence/A-close/detector-before-classified.csv` (columnas `class, category, file, line, name, why`).

| Clase | Hallazgos | Qué son |
| --- | ---: | --- |
| (a) renombrar | **288** (283 filas únicas nombre+fichero) | 15 de producto (claves de huella, `trozo`, `desconocido`, `residente` en test) y 268 datos de prueba propios de los tests |
| (b) excepción legítima sin registrar | **393** | 275 de `legacy_names.py`; alias de variables, comando y fichero viejos; tests que escriben a propósito el formato viejo; ficheros y claves de la 0.34 que se leen/escriben aún; 2 de corpus congelado |
| (b) pendiente REQ-010 | **29** | subclaves de `_local_delegate` en `server.py` y sus tests |
| (c) falso positivo | **20** | 16 por un **fallo del detector** con el comodín `*` en el nombre; 4 palabras inglesas (`suspicion`×2, `meter`, locale `de-DE`) |
| (d) texto de salida → frente B | **11** | rótulos del JS del panel (`montado`, `cargando`, `descargando`, `procesando`, `remoto`, `Remoto`, `llamada`, `fallo`), `sin_cruce` de `recompute._MATCH_LABEL` (rótulo), y `pruebas` en 2 tests (motivo de `excluded_by_reason`) |
| **Total** | **741** | |

### 2.1 Hallazgos que cambian el plan

1. **El comodín de nombre no funciona.** `is_excepted` compara `e.name == finding.name`, así que la
   fila `* | tests/test_detect_spanish_names.py` no aparta nada (16 hallazgos) y `* | scripts/data/*`
   solo «funciona» porque esos `.json` no se escanean. Arreglo: `fnmatch(finding.name, e.name)` y un
   test de control (una fila `*` aparta todo el fichero; una fila con nombre no aparta otro nombre).
2. **El detector no ve valores de una sola palabra.** Solo cuenta como `string_value` las cadenas
   con separador (`_`, `-`, `.`). REQ-016 incluye los «valores de enumeración persistidos», y muchos
   son de una palabra: `"pruebas"`, `"residente"`, `"desconocido"` (valor), `"truncado"`,
   `"congelado"`, `"imagen"`, `"trampa"`, `"techo"`… Barrido complementario por AST (scratchpad
   `a-close/singleword.py`): **69** en `src/` y **134** en `scripts/`
   (`evidence/A-close/singleword-src.txt`, `singleword-scripts.txt`). La mayoría son prosa o
   rótulos (frente B) o contenido de casos del corpus; los que se guardan y se releen están en los
   lotes 1 y 3. Ver la pregunta 5.
3. **Dos palabras reservadas ya salen en el repo.** `comment` (`tests/test_price_watcher.py:494`,
   `clients.py:61`) e `identity` (`checks.py:1194`) están en `scripts/data/reserved_words.json`
   (control de heurísticas: no pueden entrar en el léxico) y por eso quedan «sin clasificar» para
   siempre. Ver la pregunta 3.
4. **Comas en declaraciones JS** (pendiente de A8b): confirmado que `js_declared_names` solo ve el
   primer nombre de `const a = 1, b = 2`. Un barrido aproximado por regex de `metrics.py`,
   `capture_dashboard.py` y `pair_sheet.py` no encuentra nombres españoles escondidos, pero el
   control sigue ciego: hay que arreglarlo con su test.

## 3. Pendientes conocidos sin ola

Comprobado en los lectores reales y en los datos de esta PC (`%LOCALAPPDATA%\local-delegate`:
`usage-*.jsonl`, `clients.jsonl`, `attribution-*.json`, `cost-aggregates.json`, `daemon.json`,
`inflight.json`, `test-windows.json`; solo conteos, sin leer contenido privado).

| Pendiente | Quién escribe | Quién lee | Datos persistidos | Propuesta |
| --- | --- | --- | --- | --- |
| Claves de huella `ruta`, `tamano_bytes` (y `modelo` de `_SHAPES`) | `footprint.footprint()`; `scripts/dev/affinity_batch.py` las guarda en `huellas.json`/`footprints.json`; `analyze_benchmark` las copia al veredicto | `matrix.footprint_differences`, `checks.py:1534/1546` (doctor de afinidad), `tests/test_affinity.py:512-518` compara `matrix.CELLS` con `veredicto.json` congelado | Sí: `benchmarks/afinidad-2026-10/huellas.json`, `veredicto.json`, `veredicto-mecanicas.json` (congelados); `matrix.py` las lleva como constantes. 0 en logs de usuario | **Regla 1**: `path`, `size_bytes`, `model`; lectura dual en `legacy_names` (tabla de claves de la huella, aplicada en `affinity_verdict` a `footprint`, y en las huellas que lee `analyze_benchmark`); constantes de `matrix.py` en inglés; test con una huella vieja. Lote 1 |
| `respaldo`, `respondio`, `en_lugar_de` (+ `motivo`, `clase`) de `server.py:1101` y `:2308` | `_fallback_info` | `_fallback_notice` (texto del aviso), `meta["respaldo"]` en la salida de `local_extract` (`server.py:3650`), `tests/test_fallback.py:557-559` | No: el log de uso guarda `fallback_reason`/`fallback_class` (inglés, `server.py:2338`); 0 en `usage-*.jsonl`. El panel no las lee | **Son las subclaves `fallback.*` de REQ-010** → no se tocan en A; filas en «Pendiente». La clave interna `trozo` de `self.hop` (`:2308`, `:2351`) no es contrato: **renombrar a `chunk`** en el lote 1 |
| Cliente `desconocido` | `web/metrics.py:365` (cubeta de `by_client` para filas sin `client`) | JS del panel (`LABELS.client`, `:1897`), `scripts/dev/capture_dashboard.py:329`, `tests/test_metrics.py:1620`, `tests/test_dashboard_ui.py:936` | No: se calcula al leer; 0 en logs. El panel y la API los sirve el mismo daemon | **`unknown`** en Python, JS, captura y tests (lote 1). El texto visible «Desconocido» sigue (frente B) |
| Nombres de fichero de la hoja de commits (`clave-<n>.json`, `hoja-<n>.html/.md`, `respuestas-<n>.json`, `respuestas-parcial-<n>.json`; carpetas por defecto `hoja/`, `clave/`; clave de `localStorage` `hoja-commit-<id>`) | `pair_sheet.write_sheet` (`:906-913`) y la página (`:798`, `:871-875`) | `read_commit` recibe rutas **explícitas** (`--answers`, clave); `tests/test_pair_sheet.py:1092-1094` lee la hoja 1 congelada por ruta | Sí: la hoja 1 congelada en `benchmarks/afinidad-2026-10/{hoja,clave}/`. Ningún lector busca por patrón | Escribir `sheet-<n>.*`, `key-<n>.json`, `answers-<n>.json`, `answers-partial-<n>.json`; por defecto `sheet/` y `key/` (no mezclar con la hoja 1 congelada). **No hace falta lectura dual** en código; el test de la hoja 1 sigue leyendo sus rutas viejas (fila «dato congelado»). La clave de `localStorage` cambia: pierde el progreso de una hoja a medias abierta con la versión vieja (hoy no hay ninguna). Va con el lote 3. Ver pregunta 4 |
| `--help` que falla en cp1252 | `scripts/measure_slowness.py` | — | — | Causa: la `Σ` del docstring (`:30`), que `argparse` imprime con `description=__doc__` (`:437-438`) y cp1252 no codifica (`UnicodeEncodeError … 'Σ'`). Arreglo mínimo: cambiar `Σ` por «suma de» (es el único script con ese problema: barrido de los `scripts/*.py` con `PYTHONIOENCODING=cp1252`). Efecto lateral visto: `extract_dashboard_js.py` y `clean_watcher_fixtures.py` no tienen `--help` (toman `--help` como ruta) |
| Valores congelados sin tabla (pendiente 4 de A10b) | `scripts/build_corpus.py` (`provenance`: `congelado`, `generado`, `reconstruido`, `inventado`; `media_type`: `texto`, `imagen`; `sheet_role`/`kind` del par: `trampa`; `scorer.kind`: `techo`, `hoja`); `benchmark.py` (`outcome` `truncado`, `retry_reason` `anulada`) | `benchmark.py:53-54/1048/1267/1353`, `analyze_benchmark.py:71/169`, `pair_sheet.py`, tests | Sí: corpus y `resultados/*.jsonl` de `benchmarks/` | **Regla 1**: inglés (`frozen`, `generated`, `reconstructed`, `made_up`, `text`, `image`, `trap`, `ceiling`, `sheet`, `truncated`) con tablas de valores en `legacy_names` y test con el valor viejo; `anulada`→`voided` sin lectura dual (nadie lo relee). El escritor sigue vivo, así que el motivo «dato congelado» no encaja. Lote 3 (37 filas) |
| Clave `pruebas` (A9c) | `attribution.TEST_CLIENTS`, `attribution.test_reason` | `valuation.excluded_by_reason` → `/api/stats` | No (0 en `attribution-*.json` y `cost-aggregates.json`) | Es un motivo que se muestra, hermano de «no es Claude» (con espacios): **frente B** (regla 2) |
| Grupo `residente` (`residency.RESIDENT_GROUP`, no estaba en ninguna lista) | `residency` lo escribe en la config de llama-swap del **usuario** | Nadie lo busca por nombre (`:984` solo evita choques) | En la config del usuario si ya usó `residency` | Pregunta 2 |
| Envoltorio de REQ-046 y `control_t4.py` archivado (A10a) | — | — | — | Sin cambio: el envoltorio ya tiene sus filas y se retira tras P-4 de 90 días; `control_t4.py` se deja como registro |
| Comandos del vault que citan scripts viejos (A10a §10, A10b §7) | — | — | — | Fuera del repo: tarea de la sesión principal en `projects/local-delegate/` |
| Restos de A9b (`fake_llamaswap`/`test_fake_llamaswap`) | — | — | — | Ya hechos en A9c-1: solo queda un `print` de prosa en `test_fake_llamaswap.py:72` |

## 4. Propuesta de ejecución

Orden (los lotes 1–3 son independientes entre sí; el 4 va al final porque los renombres meten
palabras inglesas nuevas):

1. **A-close-1, producto** (`waves/A-close-1-mapping.csv`, 19 filas): huella con lectura dual,
   `trozo`→`chunk`, `desconocido`→`unknown`, `residente` (según la pregunta 2). Añade a
   `legacy_names.py` la tabla de claves de la huella y un test con huella vieja.
2. **A-close-2, datos de prueba** (`A-close-2-mapping.csv`, 268 filas): rutas de `tmp_path`,
   fixtures, ids de `parametrize` y claves de mocks en español, todo `search_edit` salvo los kwargs
   `ajeno`/`raro`/`roto` de `test_agents.py` (pycharm). Sin datos persistidos. Incluye el mock viejo
   `causa`/`etiqueta`/`detalle` de `test_dashboard_ui.py:1204` (el producto ya emite
   `cause`/`label`/`detail`). Precedente: A10b-1 renombró `LD_SECRETO_DE_PRUEBA`.
3. **A-close-3, valores congelados sin tabla y hoja de commits** (`A-close-3-mapping.csv`,
   37 filas, una por valor y fichero con su número de líneas): cada literal se revisa a mano porque
   `"texto"` también es `output_format` en tests y prosa en casos.
4. **A-close-4, detector y léxico**: (i) comodín en `is_excepted` + test; (ii) comas en
   declaraciones JS + test; (iii) `--help` de `measure_slowness.py`; (iv) volver a sacar las
   palabras (`--dump-words`) **después** de 1–3 y clasificar a mano las sin clasificar (hoy 776
   inglesas y `aprobada` española; `suspicion` pasa a `en` y quita los 2 falsos positivos);
   (v) resolver `comment`/`identity` (pregunta 3); (vi) añadir las excepciones de §5; (vii) corrida
   final a `evidence/A-close/detector.json` (0 fuera de la lista, «Pendiente» solo REQ-010, 0 sin
   clasificar) y los tests de REQ-044 en verde.

Control de cada lote: tests recogidos = 2601 más los añadidos registrados; suite completa con el
cerrojo `pesado.sh`.

## 5. Excepciones de (b) que hay que añadir a `rename-exceptions.md`

Con las 393 + 29 apariciones de (b) agrupadas en filas (el comodín de fichero ya funciona; el de
nombre, tras el arreglo de §4).

**Alias de compatibilidad** (retirada en 0.38.0, ola R):

| Nombre | Fichero |
| --- | --- |
| LD_HOOK_READ_BLOQUEAR, LD_HOOK_READ_INTERRUPTOR | `src/local_delegate/config.py`, `src/local_delegate/deprecations.py`, `src/local_delegate/resources/hooks/hook_common.py`, `tests/test_cli_renamed_names.py`, `tests/test_hook_legacy_names.py`, `tests/test_environment_isolation.py` |
| LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO | `config.py`, `deprecations.py`, `tests/test_cli_renamed_names.py`, `tests/test_structured_summary.py` |
| LOCAL_DELEGATE_COSTE_RESPALDO | `config.py`, `deprecations.py`, `tests/test_cli_renamed_names.py`, `tests/test_density.py` |
| recalcular-coste, reiniciar-calibracion | `src/local_delegate/cli.py`, `deprecations.py`, `tests/test_cli_renamed_names.py` |
| local-delegate-bloqueo-apagado | `deprecations.py`, `hook_common.py` |
| enfriamiento.json (escritura doble `legacy_write`) | `deprecations.py`, `hook_common.py`, `tests/test_cooldown.py`, `tests/test_fallback.py`, `tests/test_f1_conformance.py` |
| anotar_llamada.py y los dos `test_*anotar_llamada*` | `tests/test_install.py` (permanente, como la fila de `install.py`) |

**Lectura de formato viejo:**

| Nombre | Fichero |
| --- | --- |
| `*` | `src/local_delegate/legacy_names.py` (275 apariciones: es la tabla de nombres viejos) |
| `*` | `tests/test_recompute_legacy.py`, `tests/test_deprecations.py` |
| fallos, espera_s, hasta | `hook_common.py` (`COOLDOWN_STATE_KEYS`), `tests/test_cooldown.py`, `tests/test_fallback.py`, `tests/test_f1_conformance.py`, `tests/test_fallback_observability.py` |
| enfriamiento-eventos.jsonl | `tests/test_cooldown.py` |
| local-delegate-bloqueos.jsonl, local-delegate-llamadas | `hook_common.py`, `tests/test_hook_legacy_names.py` |
| toolu_viejo, toolu_viejo.json | `tests/test_hook_legacy_names.py` |
| cuota-statusline.jsonl | `tests/test_dashboard_cost.py`, `tests/test_recompute.py` |
| bloqueo_id, secciones, fallo_conexion, b-viejo, timeout_lectura, backend_ausente | `tests/test_metrics.py` |
| mcp_ajeno, prosa_grande | `tests/test_hooks_telemetry_api.py` |
| entradas, banco, cruce, sin_cruce | `tests/test_attribution.py` (`_old_backfill`) |
| causa, detalle | `tests/test_checks.py` (lo que lee `checks.py:203-205` con `read_key`) |
| n_por_mes, plazo_dias | `src/local_delegate/valuation.py` (`read_key` de `coste-agregados.json`) |
| config.rol_retirado | `tests/test_fast_role_retired.py` (id retirado que ya no debe salir) |

**Dato congelado de corpus o caso:** `resumen-estructurado`, `ficheros` en
`tests/test_structured_summary.py`; y, tras el lote 3, `clave-1.json`, `respuestas-1.json`,
`hoja-1.*` en `tests/test_pair_sheet.py` si el detector los llega a ver.

**Dato de un tercero:** `de-DE` en `src/local_delegate/web/metrics.py` (etiqueta de idioma BCP 47
de Chart.js).

**Palabra inglesa que el léxico toma por española:** `test_the_calibrated_quota_appears_as_a_meter`
en `tests/test_dashboard_ui.py` (mismo caso que `meterHTML`).

**Pendiente (REQ-010, sale en B2):** `respaldo`, `respondio`, `en_lugar_de`, `motivo`, `clase`,
`truncado`, `aviso`, `leido_server_side`, `tokens_aprox`, `crudo` en `src/local_delegate/server.py`,
`tests/test_core.py`, `tests/test_fallback.py`, `tests/test_density.py`,
`tests/test_dashboard_cost.py`.

**(d) Texto de salida** (11): no tiene motivo válido; ver la pregunta 1.

## 6. Preguntas para la sesión principal

1. **Textos de salida que ve el detector** (11 en (d): rótulos JS del panel, `sin_cruce` de
   `recompute`, `pruebas`). REQ-016 no tiene motivo para ellos y «Pendiente» solo admite REQ-010.
   *Recomendación:* enmienda como las anteriores, «texto de salida que traduce el frente B», con la
   ola B que lo traduce en cada fila, y que tenga que estar vacía al cerrar el cambio, igual que
   «Pendiente».
2. **Grupo `residente`** que `residency` escribe en la config de llama-swap del usuario. Nada lo
   relee por nombre, pero es un nombre que el usuario ve y escribe (`--group`). *Recomendación:*
   renombrar el valor nuevo a `resident` sin lectura dual (los grupos ya creados siguen valiendo
   porque nadie los busca por nombre), comprobando que los fixtures de `test_residency.py` ya usan
   un grupo `resident` y ajustar el test para que no choque. Alternativa: dejarlo como texto que el
   usuario ve (frente B).
3. **`comment` e `identity`**, palabras reservadas del control de heurísticas que ya salen en el
   repo. *Recomendación:* cambiarlas en `reserved_words.json` por dos inglesas que no salgan en el
   repo y que sigan pareciéndose a los sufijos (el test `test_no_reserved_word_is_in_the_lexicon`
   sigue valiendo). Alternativa: que el detector no informe como «sin clasificar» las reservadas
   (cambia la regla de REQ-044).
4. **Hoja de commits en inglés**: ¿escribir `sheet-<n>`, `key-<n>.json`, `answers-<n>.json` y
   carpetas por defecto `sheet/` y `key/`, y aceptar que la clave de `localStorage` cambie?
   *Recomendación:* sí; no hay hoja abierta y los lectores reciben rutas explícitas.
5. **Ceguera del detector a valores de una palabra.** *Recomendación:* no ampliar el detector en
   este cierre (metería cientos de rótulos y prosa); dejar el barrido complementario
   (`evidence/A-close/singleword-*.txt`) como evidencia firmada del cierre, con su clasificación, y
   registrarlo como limitación conocida de REQ-016 en `verification.md`.
6. **Valores congelados sin tabla (lote 3)**: ¿regla 1 (inglés + lectura dual) o registrar como
   «dato congelado»? *Recomendación:* regla 1, porque `build_corpus.py` sigue escribiéndolos y un
   corpus nuevo saldría en español.

## 7. Herramientas de la fase 1 (las tablas que lee `check_wave_records.py` están al final)

- `local_summarize` ×7 (pendientes de `A8a`, `A8b`, `A9a`, `A9b`, `A9c`, `A10a`, `A10b`): 5 útiles;
  las de `A10a` y `A10b` agotaron los 300 s (se lanzaron 7 en paralelo) y se sustituyeron por `grep`
  de las secciones «Pendientes» y lectura de ese tramo.
- `local_extract`, `local_lint_summary`, `local_explain_code`: 0. La clasificación necesitaba el
  literal de cada línea y criterio; las salidas de pytest eran de 3 líneas.
- `mcp__pycharm__search_text` ×1 (`desconocido` en todo el repo, sin `.sdd/` ni `benchmarks/`):
  útil; confirmó `docs/wiki/Savings-and-metrics.md:74/569/584` (prosa, frente B) y destapó un
  fichero `--help` suelto en la raíz (abajo). `search_regex`: 0, los barridos fueron por AST.

## 8. Incidencias de esta fase

- Para buscar el `--help` que falla corrí `--help` sobre todos los `scripts/*.py`. Los que no usan
  `argparse` hicieron otra cosa: `extract_dashboard_js.py` escribió el JS del panel en un fichero
  llamado `--help` en la raíz (**borrado**; `git status` vuelve a estar limpio salvo los ficheros de
  esta fase), `check_install_e2e.py` instaló contra un HOME temporal (`ld-e2e-*`),
  `check_install_handshake.py` arrancó el servidor contra un backend inexistente en un directorio
  temporal y `ci_gate.py` salió por falta de variables. Ninguno tocó `~/.claude` ni los datos del
  usuario.

## Decisiones de la sesión principal (2026-10-14)

Los tres mappings llevan su `# approved-by-main: 2026-10-14`. Se aceptan las 6 recomendaciones de
§6; la 2, con condición: `residente`→`resident` solo si ningún test usa los dos como grupos
distintos. Las claves `fallback.*` (`respaldo`, `respondio`, `en_lugar_de`, `motivo`, `clase`) van
a «Pendiente» por REQ-010 y las cambia B2.

## A-close-1 — producto: huella con lectura dual, `trozo`, `desconocido`, `residente` y la `Σ`

Mapping `waves/A-close-1-mapping.csv` (19 filas, todas `search_edit`, 0 `pycharm`), con su línea
`# Fase 2`. Rama `sdd/english-names-a-close`, sin commit: borrador en
`waves/A-close-1-commit-msg.txt`. Evidencia en `evidence/A-close-1/`.

### Qué se hizo

- **Huella**: `footprint._SHAPES["modelo"]`→`"model"` (y su `pop`), las claves de salida
  `ruta`→`path` y `tamano_bytes`→`size_bytes`; las constantes de `matrix.CELLS`, la tupla de
  `footprint_differences` y `checks.py:1534/1546` con las claves nuevas. Consecuencia visible: el
  aviso de `doctor` de una celda sin base dice `size_bytes` donde decía `tamano_bytes`.
- **Lectura dual** (regla 1) en `src/local_delegate/legacy_names.py`: `FORMATS["footprint"]`
  (`ruta`→`path`, `tamano_bytes`→`size_bytes`), `normalize_footprint()`, y
  `normalize_affinity_verdict` normaliza `footprint` y `role_footprint` de cada celda (se añade
  `huella_rol`→`role_footprint` a `affinity_verdict`, que antes quedaba sin traducir).
  `scripts/analyze_benchmark._footprint` normaliza lo que lee de `huellas.json`.
- **Tests nuevos** (2), con los congelados reales:
  `tests/test_affinity.py::test_frozen_verdict_footprints_with_old_keys_are_read_with_the_new_ones`
  (`veredicto.json`, con guarda de que sigue en formato viejo) y
  `tests/test_analyze_benchmark.py::test_frozen_footprints_with_old_keys_reach_the_verdict_with_the_new_ones`
  (`huellas.json`). `test_matrix_cells_are_the_approved_cells_of_the_verdict` ya comparaba
  `matrix.CELLS` (nuevas) con el `veredicto.json` congelado (viejo).
- **`trozo`→`chunk`**: clave interna de `self.hop` en `server.py` (`:2308`, `:2351`).
- **`desconocido`→`unknown`**: cubeta de `by_client` en `web/metrics.py:365`, la clave de
  `LABELS.client` del JS (el texto visible sigue «Desconocido»), los dos comentarios que la citan,
  `scripts/dev/capture_dashboard.py:329`, `tests/test_metrics.py:1620` y
  `tests/test_dashboard_ui.py:936`. El `row('desconocido', …)` de `:2294` es el texto de la fila de
  un modelo sin backend: frente B, no se toca.
- **`residente`→`resident`** (`residency.RESIDENT_GROUP`) y sus 6 literales de grupo en
  `tests/test_residency.py`. Condición comprobada: los únicos fixtures con un grupo `resident`
  (`pre-b10909-20260915.yaml`, `pre-no-resident-20261006.yaml`) solo lo borran (`--none`) o lo
  reutilizan (`--pin` de un miembro que ya está en él); ningún test crea el grupo nuevo en una
  config que ya tenga `resident`, así que nunca conviven como grupos distintos. Los grupos
  `resident` de esas configs reales coinciden ahora con el nombre que propone el producto. Los
  textos «sin residente» y «residente: a» son salida (frente B).
- **`measure_slowness.py`**: «Σ tokens de salida / Σ ms de generacion» → «suma de tokens de
  salida / suma de ms de generacion». `--help` con `PYTHONIOENCODING=cp1252` sale con rc 0
  (`evidence/A-close-1/measure_slowness-help-cp1252.txt`; el script usa `argparse`, comprobado
  antes de ejecutarlo).
- `rename-exceptions.md`, «Lectura de formato viejo»: 4 filas (`ruta` y `tamano_bytes` en
  `tests/test_affinity.py` y `tests/test_analyze_benchmark.py`) por los tests nuevos.

Cómo: `make_mapping.py apply --dry-run` aplica 0 (no hay filas `function_local` ni
`unreferenced_test`; `evidence/A-close-1/make_mapping-apply-dry-run.txt`, vacío); las 19 filas, con
un script de reemplazos con recuento exacto por fichero (scratchpad `a-close/edit1.py`,
`newline=""`). Sin homónimos, sin `rename_refactoring` y sin `git mv`; PyCharm no reescribió nada
en `.sdd/`.

### Verificación

- EOL: los ficheros tocados conservan el suyo (`server.py`, `web/metrics.py` y
  `test_dashboard_ui.py` en CRLF; el resto en LF); modo sin cambios.
- `--collect-only`: **2603** = 2601 + 2 tests nuevos (`evidence/A-close-1/collect.txt`).
- Suite `-n auto --dist loadgroup` (Playwright incluido): **2601 passed, 2 skipped**, sin
  intermitentes (`evidence/A-close-1/pytest-full.log`).
- `ruff check` y `ruff format --check`: limpios (`evidence/A-close-1/ruff.txt`).
- CodeQL (`scratchpad a10/codeql_like.py` y `codeql_more.py` sobre los 16 `.py` tocados): los
  mismos 16 hallazgos que en `HEAD`, nada nuevo (`evidence/A-close-1/codeql-like.txt`).
- Panel: la tarjeta «Quién delegó», servida desde el código del repo con 4 filas con `client` y 2
  sin él, sale «Claude Code 4» y «Desconocido 2» en claro y en oscuro
  (`evidence/A-close-1/clients-light.png`, `clients-dark.png`, `clients-card-rows.txt`).
- Detector con la lista: fuera de la lista **741 → 731**; de los nombres del lote solo quedan los de
  `legacy_names.py` y los de las filas nuevas (`evidence/A-close-1/detector.json`).

### Desviaciones

1. **`huella_rol`→`role_footprint`** en la tabla `affinity_verdict`: no estaba en el mapping, pero
   sin ella la huella del rol de cada celda del congelado no se podía normalizar.
2. Las 4 filas nuevas de `rename-exceptions.md` (lectura de formato viejo de los tests nuevos).

### Pendientes para los lotes siguientes

- Lotes `A-close-2`, `A-close-3` y `A-close-4` (§4), con las respuestas de la sesión principal.

## A-close-2 — datos de prueba propios de los tests

Mapping `waves/A-close-2-mapping.csv` (268 filas: 266 aplicadas y 2 discrepancias), con su línea
`# Fase 2`. Rama `sdd/english-names-a-close-2`, encima de `30b05f7` (lote 1, mezclado en `main`
como `eafd3a2`). Sin commit: borrador en `waves/A-close-2-commit-msg.txt`. Evidencia en
`evidence/A-close-2/`.

### Interrupción y estado al retomar

Un reinicio de la PC cortó el lote después de aplicar los reemplazos y los arreglos a mano, y antes
de la verificación. Al retomar: 60 tests modificados, todos compilan (`py_compile`), conservan el EOL
de `HEAD` (`git ls-files --eol`), terminan en salto de línea y el diff era de líneas sustituidas
(431/431, sin truncados). El aplicador en seco daba 0 pendientes salvo las 3 apariciones que se
dejaron a propósito (abajo). Lo que faltaba: verificación, mutante, mapping, registro y mensaje.

### Qué se hizo

- **Aplicador por tokens de cadena** (scratchpad `a-close/apply2.py`, `newline=""`): los nombres
  con separador (`no-existe`, `toolu_calla.json`, `codigo-401`…) se cambian acotados dentro de
  cualquier literal (cadena, bytes, f-string, docstring), de más largo a más corto; las palabras
  sueltas (`otro`, `puerto`, `remoto`, `causa`…) solo cuando el literal es exactamente esa palabra,
  para no tocar prosa ni textos del producto. 441 sustituciones en 60 ficheros.
- **A mano** (`a-close/fix2.py`, `fix2b.py`):
  - los kwargs `ajeno=`/`raro=`/`roto=` de `_agents_dir(tmp_path, **files)` en `test_agents.py`
    pasan a `foreign=`/`odd=`/`broken=` (dan nombre al `.md` que el test lee), y `name: ajeno` del
    agente de prueba, a `name: foreign`. Eran las 3 filas `pycharm`: el MCP de PyCharm estaba caído
    (ECONNREFUSED) y `rename_refactoring` no renombra claves de `**kwargs`, así que pasan a
    `search_edit` (anotado en la fila y en `# Fase 2`);
  - contenido que el aplicador no ve como literal propio: las tablas TOML de `test_install.py`
    (`[mcp_servers.otro]`→`other`, `[otra.cosa]`→`[another.thing]`,
    `[projects.proyecto]`→`project`), el JSON del mock de `test_core.py` (`"puerto"`→`"port"`) y su
    documento, las dos cadenas de `test_map_reduce.py` con un `\n` delante (`END-MARK`,
    `ERROR-THAT-MATTERS`), `"coletilla de imagen"`→`"image_tail_note"`, y el token con sufijo de
    `test_web_auth.py`;
  - los rótulos que el panel deriva de las claves desconocidas renombradas (`test_dashboard_ui.py`:
    «Odd new key», «Reason that does not exist», «New client»).
- **Revertido**: el segundo elemento de `_REFUSALS["anchor"]` en `test_residency.py` vuelve a
  `"ancla"`: es el texto de la negativa del producto («ancla `&c` en la línea…»), frente B.
- **No aplicado (2 discrepancias)**: `clave-falsa` y `clave-falsa-1` en `test_residency.py`. Son el
  marcador con que las copias congeladas de configs reales (`tests/fixtures/residency/*.yaml`)
  sustituyen las claves, y el test comprueba esa sustitución. Van a «Dato congelado de corpus o
  caso» de `rename-exceptions.md`. Los `fake-key-N` de `test_metrics`, `test_llamaswap_api` y
  `test_residency_cli` son independientes de esos fixtures y sí se renombran.
- `ruff format` en 5 tests cuyas líneas cambiaron de longitud.
- Quedan sin tocar, a propósito: prosa en comentarios y docstrings (`otro`, `ajeno`, `etiqueta`…),
  rutas de prueba dentro de cadenas sin fila en el mapping (`/otro/hook.py` en `test_checks.py`,
  `C:/docs/notas.md`), y valores en ficheros fuera del lote que el detector no ve.

### Verificación

- `--collect-only`: **2603**, igual que tras el lote 1 (`evidence/A-close-2/collect.txt`).
- Suite `-n auto --dist loadgroup` (Playwright incluido): **2601 passed, 2 skipped**
  (`evidence/A-close-2/pytest-full.log`). La primera corrida dio 1 fallo en
  `test_fake_llamaswap.py::test_a_ttl_counts_from_request_end`, el intermitente de tiempo ya
  conocido (A9b/A9c): el lote solo cambió ids de `parametrize` y un nombre de modelo en ese fichero,
  y el fichero pasó 3 veces seguidas solo (`evidence/A-close-2/pytest-full-1-intermitente.log`).
- `ruff check` y `ruff format --check`: limpios (`evidence/A-close-2/ruff.txt`).
- CodeQL (`scratchpad a10/codeql_like.py` y `codeql_more.py` sobre los 60 `.py` tocados): los
  mismos hallazgos que en `HEAD` (`evidence/A-close-2/codeql-like.txt`).
- Detector con la lista: fuera de la lista **731 → 462**; **0** hallazgos de las filas del lote
  (`evidence/A-close-2/detector.json`). Palabras sin clasificar 777 → 783 (inglesas nuevas: para el
  lote 4).

### Desviaciones

1. Las 3 filas `pycharm` se hicieron a mano (`search_edit`) por el MCP de PyCharm caído.
2. 2 discrepancias (`clave-falsa`, `clave-falsa-1`) con fila nueva en `rename-exceptions.md`.
3. Asserts de rótulos derivados (`test_dashboard_ui.py`) cambiados con los datos: es el mismo
   control con el dato nuevo, no un cambio de sentido.

| Control positivo del lote 2 | Mutante | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_dashboard_ui.py::test_no_table_shows_internal_keys` (datos renombrados `odd_new_key`, `reason_that_does_not_exist`, `new_client`) | `web/metrics.py:1908`, el respaldo de rótulos sin quitar los `_` (`.replace(/_/g, '_')`) | `test_dashboard_ui.py:981` `assert not bad` con `['Odd_new_key', 'Reason_that_does_not_exist', 'New_client']` (`evidence/A-close-2/mutante.log`) | desde copia; sha256 `778ba0eb00f6` antes y después |

## Controles positivos

| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_affinity.py::test_matrix_cells_are_the_approved_cells_of_the_verdict`, `test_frozen_verdict_footprints_with_old_keys_are_read_with_the_new_ones` y `tests/test_analyze_benchmark.py::test_frozen_footprints_with_old_keys_reach_the_verdict_with_the_new_ones` (lote 1; lectura dual de la huella) | `src/local_delegate/legacy_names.py` con `FORMATS["footprint"]` sin `"ruta": "path"` | `test_affinity.py:518` `assert dict(cell.footprint) == footprints[...]` (AssertionError); `test_affinity.py:541` y `test_analyze_benchmark.py:1565` `KeyError: 'path'`; 3 failed, 156 passed (`evidence/A-close-1/mutant-footprint-dual.txt`) | desde copia; sha256 `ae60e98d…` antes y después |
| `tests/test_dashboard_ui.py::test_no_table_shows_internal_keys` (lote 2; datos renombrados `odd_new_key`, `reason_that_does_not_exist`, `new_client`) | `src/local_delegate/web/metrics.py:1908`, el respaldo de rótulos sin quitar los `_` | `test_dashboard_ui.py:981` `assert not bad` con `['Odd_new_key', 'Reason_that_does_not_exist', 'New_client']` (`evidence/A-close-2/mutante.log`) | desde copia; sha256 `778ba0eb00f6` antes y después |

## Llamadas `local_*` (sesión principal y cada agente)

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente A-close (fase 1) | `local_summarize(path=waves/A8a.md, A8b.md, A9a.md, A9b.md, A9c.md)` | pendientes para el cierre de cada registro; útiles (5) |
| Agente A-close (fase 1) | `local_summarize(path=waves/A10a.md, A10b.md)` | agotaron los 300 s (7 en paralelo); sustituidas por `grep` de «Pendientes» y lectura de ese tramo |
| Agente A-close-1 | `local_lint_summary(path=evidence/A-close-1/pytest-full.log)` | resumen de la suite: solo los 12 `DeprecationWarning` de starlette; sirvió |
| Agente A-close-2 | `local_lint_summary(path=evidence/A-close-2/pytest-full-1-intermitente.log)` | resumen de la primera corrida: 1 fallo de `test_fake_llamaswap.py` (el intermitente de tiempo) y los avisos de starlette; sirvió |

## Llamadas `mcp__pycharm__*`

| Agente | Tool | Símbolo / fichero | Resultado |
| --- | --- | --- | --- |
| A-close (fase 1) | `search_text` | `desconocido` en todo el repo, sin `.sdd/` ni `benchmarks/` | útil: ubicó los usos de producto, la prosa de la wiki y el fichero `--help` suelto |
| A-close-1 | `get_file_problems` | `src/local_delegate/legacy_names.py` (solo errores) | 0 errores |
| A-close-1 | `get_file_problems` | `scripts/analyze_benchmark.py` (solo errores) | 0 errores |
| A-close-1 | `get_file_problems` | `src/local_delegate/footprint.py` (solo errores) | 0 errores |
| A-close-2 | (ninguna) | MCP de PyCharm caído (ECONNREFUSED) tras el reinicio | motivo: las 3 filas `pycharm` se hicieron a mano y la comprobación de problemas la cubren `py_compile`, ruff y la suite |
