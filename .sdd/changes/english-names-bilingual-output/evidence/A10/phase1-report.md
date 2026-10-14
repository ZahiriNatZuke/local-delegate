# A10, fase 1: mappings de los scripts (pendientes de aprobación)

Rama `sdd/english-names-a10`, sin cambios en `scripts/`, `tests/`, `src/` ni `.github/`. Solo se
escribieron los 12 mappings en `waves/`, esta nota y `evidence/A10/collect-before.txt`.

## Lotes

Todos con 300 filas o menos, EOL LF, cabecera `# wave=… Pendiente de aprobación`, `# Cómo se generó:`,
ficheros del lote, NOT-OWNED, «NO se tocan» y, si toca, las excepciones propuestas del lote.

| Lote | Filas | pycharm / search_edit | Ficheros |
| --- | --- | --- | --- |
| A10a-1 | 250 | 110 / 140 | vigilante_precios, limpiar_fixtures_vigilante, workflow vigilante-precios.yml |
| A10a-2 | 286 | 80 / 206 | test_vigilante, ci_gate (kwargs y constantes cedidos por A9) |
| A10a-3 | 290 | 59 / 231 | medir_enfriamiento (+ envoltorio de REQ-046), su test, sonda_recursos, test_resource_probe, bump_version (1 fila), macos_mcp_canary, dev/capture_icons, dev/measure_ttl_race |
| A10a-4 | 284 | 30 / 254 | medir_adopcion, sesiones_de_prueba, measure_slowness (claves cedidas), sus tests, dev/medir_salidas_bash, dev/capture_dashboard (JS cedido), test_capture |
| A10a-5 | 281 | 41 / 240 | experimento_adopcion, su test, check_install_e2e, check_install_handshake |
| A10a-6 | 288 | 71 / 217 | medir_resumen_estructurado, su test, _banco_claude, build_site, release, sync_wiki |
| A10b-1 | 225 | 28 / 197 | analizar_benchmark (identificadores), test_affinity, test_affinity_batch, test_benchmark, dev/affinity_batch, src/local_delegate/benchmark.py (claves cedidas por A8a) |
| A10b-2 | 207 | 43 / 164 | analizar_benchmark (cadenas y CLI), hoja_revision |
| A10b-3 | 227 | 32 / 195 | construir_corpus (identificadores) |
| A10b-4 | 273 | 70 / 203 | construir_corpus (cadenas y CLI), hoja_pares (con su JS y CSS) |
| A10b-5 | 293 | 34 / 259 | test_analisis_benchmark |
| A10b-6 | 284 | 22 / 262 | test_corpus, test_hoja_pares |

Total 3188 filas: 2290 identificadores (variable 1193, function 464, param 404, constant 140,
attribute 31, method 19, class 16, module 22, import_alias 1), 647 claves, 55 valores, 78 nombres de
fichero en cadenas, 13 cadenas con nombre de módulo, 49 opciones del CLI y 56 nombres de JS (5 también
clase CSS). Ámbito: function_local 1461, module_local 786, cross_module 732, unreferenced_test 209.
Método: pycharm 620, search_edit 2568.

## Cómo se generó (scratchpad `a10\`)

1. `make_mapping.py build --wave A10` sobre `scripts/*.py`, `scripts/dev/*.py`, los tests de A10 y
   `src/local_delegate/benchmark.py`: 2270 filas.
2. Barrido AST (`sweep.py`): 20 filas más (palabras sueltas `sin`/`con`, `diff_de_commit`,
   `sin_troceo`, `por_id`, `del_tool`, `que`, `en_tmax`, `_en_h1/_en_h2/_en_sup`,
   `CHECK_WORKFLOWS`, `repartos`…). La `o` de `test_analisis_benchmark.py:1214` se queda (es
   inglés, como la `_o` de A9c).
3. Detector de A0 con `--json` para claves, valores y nombres de fichero en cadenas: una fila por
   (nombre, fichero), con la primera línea y el número de apariciones.
4. Opciones del CLI por AST de `argparse`; JS en cadenas con el tokenizador de A0 (`jsscan.py`).
5. `new`: la tabla de A9 (`names_c.G`) más `names_a10.py` y `strings_a10.py`; los 215 `test_*`
   están en `tests_tr.txt`. Se corrigieron heredados que aquí tienen otro sentido (`hoja`→sheet y no
   stylesheet, `salidas`→outputs, `FUENTES`→SOURCES_DIR, `peticion`→request…) y los que tapaban un
   builtin (`filtro`, `todos`, `al_reves`).
6. Choques por ámbito, `test_*` repetidos y módulos destino ya existentes (`gen.py`): **0** tras
   resolver 17 (ver «Colisiones»).
7. Decisión renombrar / lectura dual / excepción, cargando todos los `benchmarks/**/*.json(l)`
   (`persist.py`).

## Opciones del CLI (49 filas)

- `medir_adopcion`: `--desde`→`--since`, **con alias `--desde`** (comando de la wiki y del
  `verification.md` del SDD vigente `delegacion-precisa-y-fiable`).
- `medir_enfriamiento`→`measure_cooldown`: `--desde/--hasta/--excluir`→`--since/--until/--exclude`;
  `scripts/medir_enfriamiento.py` queda como **envoltorio** (REQ-046) con las opciones viejas.
- `analizar_benchmark`: `decidir`→`decide`; `--salida/--pequeno/--grande/--par/--pares`→
  `--output/--small/--large/--pair/--pairs`; metavar ROL/VIGENTE/CANDIDATO; dest `modo`→`mode`.
- `construir_corpus`: `--destino`→`--dest`, `--comprobar`→`--check`.
- `experimento_adopcion`: `--banco --repeticiones --semilla --coste-por-corrida --reanudar --piloto
  --variantes --fuentes --si --solo-informe` → `--bench --repetitions --seed --cost-per-run --resume
  --pilot --variants --sources --yes --report-only`.
- `hoja_pares` y `hoja_revision`: `generar`/`destapar`→`generate`/`unblind`; `--hoja --clave --caso
  --semilla --pequeno --grande --salida`→`--sheet --key --case --seed --small --large --output`.
- `medir_resumen_estructurado`: `--etiqueta/--salidas`→`--label/--outputs`. `sesiones_de_prueba`:
  `--dia --proyectos --salida --motivo`→`--day --projects --output --reason`. `sync_wiki`: posicional
  `destino`→`destination`. `vigilante_precios`: `trabajo {precios,limites}`→`job {prices,limits}` (lo
  pasa el workflow).
- Sin alias salvo los dos de medición (los scripts no se publican).

## Datos persistidos

- **Lectura dual (402 filas)**: claves y valores que aparecen en `benchmarks/**/*.json(l)` y leen
  los scripts. Propuesta: tablas `BENCHMARK_KEYS`/`BENCHMARK_VALUES` en
  `src/local_delegate/legacy_names.py` y una función que normaliza viejo→nuevo **al cargar**
  (`benchmark.load_corpus`, `leer_corpus`, `leer_jsonl`, `leer_elecciones`, los lectores de
  huellas/reglas/trampas/veredicto y de `ventanas-excluidas.json`); se escribe solo lo nuevo. Incluye
  lo cedido por A8a: `procedencia`→provenance con `congelado/generado/reconstruido/inventado`→
  frozen/generated/reconstructed/made_up, `descartada(_motivo)`→discarded(_reason),
  `truncado_repetido`, `rechazo_por_contexto`, `_CORPUS_MEDIA` `texto/imagen`→text/image,
  `_CORPUS_KINDS` `calidad/techo`→quality/ceiling, y las claves que exporta la hoja HTML
  (`respuestas-N.json`). Ficheros de `benchmarks/` (`huellas.json`, `reglas.json`, `trampas.json`,
  `veredicto*.json`, `conteos-log.json`, `tareas.json`, `ventanas-excluidas.json`,
  `ventanas-tanda.json`, `clave-N.json`): se escribe el nombre nuevo y se lee el que exista.
- **Ficheros temporales del arnés** (`generado.py`, `comprobaciones.json`): no se guardan, así que
  se renombran sin lectura dual.
- **Informes `--json`** de `medir_*`, `measure_slowness` y `experimento_adopcion` (incluidos `cumple`,
  `faltan` y `eventos_pc`, cedidos por A9b): se imprimen y no se guardan, así que se renombran. El
  informe de P-4 cambia de claves; el comando sigue igual (REQ-046).
- **Excepciones propuestas (117)**, todas «lectura de formato viejo»: 75 ids de casos de corpus
  congelados (`resumen-md-2k`, `clasifica-*`, `extrae-*`, `techo-*`…), 20 campos esperados de los
  casos de extracción (`factura`, `telefono`, `a_favor`…: contenido del documento en español), 15
  nombres de directorio (`afinidad-2026-10`, `catalogo-2026-09`, `adopcion-directa`,
  `resumen-estructurado`) y 7 filas o valores viejos que los tests escriben a propósito
  (`bloqueo_id`, `capacidad_o_carga`, `timeout_lectura`, `tras_vencer`, `enfriamiento`,
  `enfriamiento-eventos.jsonl` y el `LD_HOOK_READ_BLOQUEAR` del caso congelado). Además: el
  envoltorio `medir_enfriamiento.py` y sus opciones (motivo «envoltorio de REQ-046») y el alias
  `--desde` de `measure_adoption` (motivo «alias de compatibilidad»). La clave `pruebas` de
  `capture_dashboard` es del producto: queda para el cierre del frente A. Tabla completa al final.

## Fuera de los ficheros del alcance que tocaría la aplicación

`src/local_delegate/legacy_names.py` (tabla dual), `src/local_delegate/cooldown.py:22,56`,
`sections.py:14` y `legacy_names.py:215` (citan el nombre del script),
`.github/workflows/vigilante-precios.yml` (nombre y argumentos), `docs/wiki/` (Backend-versions,
Configuration, Repo-hardening, Savings-and-metrics), `benchmarks/catalogo-2026-09/README.md`
(congelado: solo nota), las notas fechadas de REQ-046 en
`.sdd/changes/delegacion-precisa-y-fiable/verification.md` y
`.sdd/changes/daemon-reparte-el-backend/verification.md`, y la entrada del backlog. Tests de A9 por
consecuencia: `test_ci_gate.py` (kwargs `leer/reloj/dormir/escribir`, `estado/motivo`),
`test_resource_probe.py`, `test_affinity*.py`, `test_benchmark.py`, `test_capture.py`. El detalle por
lote está en la línea NOT-OWNED de cada CSV (los documentos propios de este SDD que salen ahí son
historia del plan y no se tocan).

## Colisiones resueltas

- `_banco_claude`: `correr` (función) y `corrida` iban a `run` → `corrida`→`run_result`.
- `analizar_benchmark`: `banda_del_caso`/`banda_caso` y `pares_del_rol`/`pares_rol` → las funciones
  pasan a `band_for_case` y `pairs_for_role`.
- `construir_corpus`: `fichero` (función)→`file_source`; `capturar`, con un local `capture` en el
  llamador, → `capture_case`; `captura`→`captured`; `comprobacion`→`check_result`;
  `mala`/`malo`→`bad_answer`/`bad_signals`.
- `limpiar_fixtures_vigilante`: `limpio`→`cleaned`; `test_vigilante`: `camino`→`url_path`.
- `que` con dos sentidos: `subject` en experimento_adopcion y `kind` en medir_enfriamiento; `sin`/`con`
  del test de adopción → `without_tests`/`with_tests`.
- Builtins evitados: `filtro`→`window_filter`, `todos`→`all_episodes`, `al_reves`→`is_reversed`.
- Ningún `test_*` repetido; ningún módulo destino existe ya.

## CodeQL

`main` no tiene alertas abiertas en `scripts/`. En el alcance solo está `tests/test_affinity.py:210`
(`py/catch-base-exception`), y ese fichero no cambia de nombre: no reaparece. Barrido AST de los
patrones pedidos sobre los 22 ficheros que cambian de nombre: un único candidato,
`tests/test_vigilante.py:408` (`m` sin usar en la comprensión de `despachados`). Propuesta: cambiarlo
por `_` al renombrar, por si CodeQL lo marca en el fichero nuevo.

## Decisiones dudosas (con recomendación)

1. Los scripts de `scripts/` que el plan no lista (build_site, check_install_*, release, sync_wiki,
   macos_mcp_canary, dev/*, más 1 fila de bump_version) entran en A10a, porque el plan da a A10 todo
   `scripts/` y el cierre exige 0 hallazgos. Recomiendo aceptarlo.
2. `dev/medir_salidas_bash.py`→`measure_bash_outputs.py`, que no estaba en la partición. Recomiendo
   aceptarlo.
3. `_banco_claude` pasa a A10a-6, porque solo lo usa experimento_adopcion (A10a) y sus claves las lee
   `test_experimento_adopcion`. Recomiendo moverlo a A10a.
4. analizar_benchmark (319 filas) y construir_corpus (345) no caben en un lote: cada uno se parte en
   identificadores (pycharm) y cadenas/CLI (search_edit). Recomiendo aceptarlo; la otra opción es
   romper D13.
5. vigilante_precios y test_vigilante van en lotes distintos (250 + 242 filas): A10a-1 tendrá que
   tocar claves en test_vigilante como NOT-OWNED. Recomiendo aplicar A10a-1 y A10a-2 seguidos.
6. La lectura dual de `benchmarks/` cubre 402 filas porque marca dual toda clave que aparece en algún
   JSON congelado, aunque su uso en el script sea otro. Recomiendo que la fase 2 recorte la tabla a lo
   que lee cada cargador.
7. La tabla dual iría en `src/local_delegate/legacy_names.py` (fuera de `scripts/`), junto a las demás.
   Recomiendo aceptarlo; la alternativa es un módulo propio en `scripts/`.
8. Las 117 excepciones usan «lectura de formato viejo» para ids de casos y para el contenido de los
   casos congelados; ninguno de los motivos de REQ-016 nombra eso tal cual. Recomiendo una enmienda
   corta: «id o contenido de un corpus congelado de `benchmarks/`».
9. `sesiones_de_prueba`→`test_sessions` **(plan)** crea un `scripts/test_sessions.py` que parece un
   test (`testpaths=["tests"]` evita que pytest lo recoja). Recomiendo mantener el nombre del plan; la
   alternativa es `sdk_test_sessions`.
10. Alias `--desde` también en `measure_adoption`, que REQ-046 no pide. Recomiendo tenerlo: es la otra
    medición documentada.
11. El workflow `vigilante-precios.yml`→`price-watcher.yml`: hay que comprobar que ninguna regla de
    protección pida su nombre (los checks van por nombre de job). Recomiendo comprobarlo antes de
    mezclar.
12. Las claves `quieto`/`anonimo`/`mapeado` del programa hijo de `test_resource_probe`, que A9c dejó,
    ahora se renombran con su script. Recomiendo renombrarlas.

## Conteo base

`evidence/A10/collect-before.txt`: **2572** tests recogidos (con `pesado.sh`).

## Llamadas

`local_*`: 0. Motivo: lo que hacía falta eran literales con su línea exacta (opciones, claves,
choques), y salían por AST y `git grep` en scripts propios; ningún resumen habría sustituido esa
lectura. `mcp__pycharm__*`: 0 (la verificación con `analyze_calls`/`search_symbol` es de la fase 2).

## Excepciones propuestas (tabla para `rename-exceptions.md`)

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| LD_HOOK_READ_BLOQUEAR | scripts/construir_corpus.py | lectura de formato viejo: fila o valor del formato viejo que el test escribe a prop�sito para probar la lectura dual |
| a_favor | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| abstenciones | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| adopcion-directa | scripts/experimento_adopcion.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| afinidad-2026-10 | scripts/analizar_benchmark.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| afinidad-2026-10 | scripts/construir_corpus.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| afinidad-2026-10 | scripts/dev/affinity_batch.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| afinidad-2026-10 | scripts/hoja_pares.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| afinidad-2026-10 | tests/test_affinity.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| afinidad-2026-10 | tests/test_affinity_batch.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| afinidad-2026-10 | tests/test_corpus.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| afinidad-2026-10 | tests/test_hoja_pares.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| asistentes | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| bloqueo_id | tests/test_medir_adopcion.py | lectura de formato viejo: fila o valor del formato viejo que el test escribe a prop�sito para probar la lectura dual |
| capacidad_o_carga | tests/test_medir_enfriamiento.py | lectura de formato viejo: fila o valor del formato viejo que el test escribe a prop�sito para probar la lectura dual |
| catalogo-2026-09 | scripts/construir_corpus.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| catalogo-2026-09 | tests/test_analisis_benchmark.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| catalogo-2026-09 | tests/test_benchmark.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| catalogo-2026-09 | tests/test_corpus.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| catalogo-2026-09 | tests/test_resource_probe.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| clasifica-bug-con-etiquetas-en-ingles | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasifica-bug-con-etiquetas-en-ingles | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasifica-deportes | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasifica-economia | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasifica-idioma-aleman | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasifica-ironia | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasifica-lenguaje-de-programacion | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasifica-negacion-reenvio | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasifica-peticion-de-funcion | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasificar-53 | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasificar-53 | tests/test_analisis_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasificar-53 | tests/test_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasificar-53 | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasificar-53 | tests/test_resource_probe.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| clasificar-53.txt | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| cliente | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| correo | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| delega-contar-palabras | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| delega-fecha-iso | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| delega-lista-a-csv | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| delega-mayusculas | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| delegar-56 | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| describir-dashboard | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| describir-dashboard | tests/test_analisis_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| describir-dashboard | tests/test_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| en_contra | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| enfriamiento | tests/test_medir_enfriamiento.py | lectura de formato viejo: fila o valor del formato viejo que el test escribe a prop�sito para probar la lectura dual |
| enfriamiento-eventos.jsonl | tests/test_medir_enfriamiento.py | lectura de formato viejo: fila o valor del formato viejo que el test escribe a prop�sito para probar la lectura dual |
| experimento-adopcion | scripts/experimento_adopcion.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| explicar-install-20k | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| explicar-install-20k | tests/test_analisis_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| explicar-install-20k | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| explicar-metrics-15k | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| explicar-metrics-15k | tests/test_analisis_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| explicar-metrics-15k | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| extrae-acta-con-cifras | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| extrae-correo-sin-telefono | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| extrae-factura | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| extrae-linea-de-acceso-web | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| extrae-linea-de-log-con-numeros | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| extrae-producto-sin-existencias | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| extrae-reunion-sin-organizador | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| extrae-toml-sin-licencia | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| extraer-toml-2k | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| extraer-uvlock-48k | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| extraer-uvlock-48k | tests/test_analisis_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| factura | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| fecha | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| hora | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| leer-cifras-dashboard | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| leer-cifras-dashboard | tests/test_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| lugar | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| metodo | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| moneda | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| nivel | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| organizador | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| precio | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| real-reescrito | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| real-reescrito | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| real-reescrito | tests/test_hoja_pares.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resume-ruff-cinco-reglas | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resume-ruff-tres-reglas | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resume-ruff-un-solo-archivo | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resumen-changelog-7k | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resumen-changelog-7k | tests/test_analisis_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resumen-changelog-7k | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resumen-estructurado | scripts/medir_resumen_estructurado.py | lectura de formato viejo: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) |
| resumen-md-10k | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resumen-md-10k | tests/test_analisis_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resumen-md-10k | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resumen-md-2k | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resumen-md-2k | tests/test_analisis_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resumen-md-2k | tests/test_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resumen-md-2k | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| resumen-md-2k.md | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| ruta | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| servicio | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| socios | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| talla | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| techo-commit-156k | scripts/analizar_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| techo-commit-156k | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| techo-commit-156k | scripts/dev/affinity_batch.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| techo-resumen-103k | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| techo-resumen-103k | tests/test_analisis_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| techo-resumen-103k | tests/test_benchmark.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| techo-resumen-106k | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| techo-resumen-120k | tests/test_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| telefono | scripts/construir_corpus.py | lectura de formato viejo: campo esperado de un caso congelado (contenido del documento en espa�ol que el modelo extrae) |
| timeout_lectura | tests/test_medir_enfriamiento.py | lectura de formato viejo: fila o valor del formato viejo que el test escribe a prop�sito para probar la lectura dual |
| traduce-guia-de-inicio | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| traduce-lista-de-version | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| traduce-registro-de-cambios | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| traduce-solucion-de-problemas | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| traducir-42 | scripts/construir_corpus.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| tras_vencer | tests/test_medir_enfriamiento.py | lectura de formato viejo: fila o valor del formato viejo que el test escribe a prop�sito para probar la lectura dual |
| wiki-instalacion | scripts/experimento_adopcion.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| wiki-instalacion | tests/test_experimento_adopcion.py | lectura de formato viejo: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) |
| medir_enfriamiento | scripts/medir_enfriamiento.py | envoltorio de REQ-046 (nombre y opciones `--desde/--hasta/--excluir`); retirada tras la medición de P-4 de los 90 días (~2026-12-14) |
| desde | scripts/measure_adoption.py | alias de compatibilidad de la opción `--desde` (nueva `--since`); retirada en la tercera versión menor tras la que la renombra |
