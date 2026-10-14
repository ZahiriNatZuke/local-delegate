# Excepciones del detector de nombres en español (REQ-016)

Lista de nombres en español que pueden quedar en el repo al cerrar el frente A, cada uno con su
motivo. La lee `scripts/detect_spanish_names.py --exceptions <este fichero>`: toma las filas de las
tablas (`| Nombre | Fichero | Motivo |`) y aparta un hallazgo cuando coinciden el nombre y el
fichero (el fichero admite comodines, `*` para cualquiera).

Los únicos motivos válidos (REQ-016):

- alias de compatibilidad (REQ-001, REQ-002, REQ-012), con su versión de retirada;
- lectura de formato viejo (excepción de REQ-005, REQ-006, REQ-007, REQ-008);
- envoltorio de REQ-046;
- dato de un tercero que no controla el paquete;
- dato de prueba del propio detector: nombres en español que sus tests y su léxico necesitan como
  entrada (enmienda del 2026-10-12 tras la ola A0);
- palabra inglesa que el léxico del detector clasifica como española (enmienda del 2026-10-13,
  ola A8b, aprobada por la sesión principal): `meter` es «medidor» en inglés y el verbo «meter» en
  español; el nombre está en inglés y no se renombra;
- dato congelado de corpus o caso (enmienda del 2026-10-13, ola A10, aprobada por la sesión
  principal como desviación de REQ-016): ids, contenido y valores ya escritos en corpus o copias
  congeladas (`benchmarks/`, `tests/fixtures/`) que no se reescriben;
- entrada de interfaz escrita por una persona (enmienda del 2026-10-14, ola A10b-5, aprobada por la
  sesión principal como desviación de REQ-016): las respuestas que la persona escribe a mano en
  una hoja `.md` en español (`si`, `parcial`, `empate`), y lo que el programa guarda de ellas; se
  traducen en el frente B, que lee las dos formas;
- **pendiente**: lo que el frente A renombra pero se publica en el B (las subclaves y marcadores
  de REQ-010, que salen en B2).

Al cerrar el frente A, la sección «Pendiente» solo puede tener lo de REQ-010; al cerrar el cambio,
tiene que estar vacía.

Estado al terminar la ola A0: **lista vacía**. Cada ola añade aquí las filas que necesite, en la
sección de su motivo.

## Alias de compatibilidad

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| delegacion-local | src/local_delegate/install.py | alias de compatibilidad permanente (REQ-012/013): nombre de la skill hasta la 0.34.0 en `_RETIRED_SKILLS`; sin retirada, porque quien salte desde una 0.34 sigue teniendo la copia vieja (ola A6, respuesta 7) |
| anotar_llamada.py | src/local_delegate/install.py | alias de compatibilidad permanente (REQ-012): nombre del hook hasta la 0.34.0 en `_RETIRED_SCRIPTS`; misma razón (ola A2, apuntado en A6, respuesta 7) |
| delegacion-local | tests/* | alias de compatibilidad (REQ-012): instalación 0.34.0 simulada en los tests de `install`/`update` y de la retirada de la skill (ola A6) |
| ld_sesion | tests/test_web_auth.py | alias de compatibilidad (REQ-012): cookie de la 0.34.0 que tiene que dar 401 (ola A6) |
| --desde | scripts/measure_adoption.py | alias de compatibilidad (decisión 10 de A10a): nombre de antes de `--since`, por los comandos escritos en la wiki y en el `verification.md` de `delegacion-precisa-y-fiable`; el test lo usa en una de las dos llamadas a `main` (ola A10a-4) |
| --desde | tests/test_measure_adoption.py | alias de compatibilidad (decisión 10 de A10a): nombre de antes de `--since`, por los comandos escritos en la wiki y en el `verification.md` de `delegacion-precisa-y-fiable`; el test lo usa en una de las dos llamadas a `main` (ola A10a-4) |

## Lectura de formato viejo

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| residente | src/local_delegate/chains.py | lectura de formato viejo (REQ-022): `_OBSOLETE_SYNONYMS` acepta `residente` (y `resident`) como sinónimo obsoleto del paso `loaded` en `LOCAL_DELEGATE_FALLBACK_<ROL>`, con aviso de `doctor`; hoy el detector no lo marca, la fila deja escrito por qué sigue (ola A8a-1, respuesta 4) |
| modelo | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): clave del registro viejo de enfriamiento y clase de error vieja que el test escribe a propósito para probar la lectura dual (ola A10a-3) |
| evento | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): clave del registro viejo de enfriamiento que el test escribe a propósito (ola A10a-3) |
| clase | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): clave del registro viejo de enfriamiento que el test escribe a propósito (ola A10a-3) |
| espera_s | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): clave del registro viejo de enfriamiento que el test escribe a propósito (ola A10a-3) |
| tras_vencer | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): clave del registro viejo de enfriamiento que el test escribe a propósito (ola A10a-3) |
| entra | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): valor de evento del registro viejo que el test escribe a propósito (ola A10a-3) |
| limpia | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): valor de evento del registro viejo que el test escribe a propósito (ola A10a-3) |
| timeout_lectura | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): clase de error vieja que el test escribe a propósito (ola A10a-3) |
| capacidad_o_carga | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): clase de error vieja que el test escribe a propósito (ola A10a-3) |
| peticion | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): clase de error vieja que el test escribe a propósito (ola A10a-3) |
| enfriamiento | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): clase de salto vieja que el test escribe a propósito (ola A10a-3) |
| enfriamiento-eventos.jsonl | tests/test_measure_cooldown.py | lectura de formato viejo (REQ-007): nombre del fichero viejo de eventos, que el script sigue leyendo (ola A10a-3) |
| motivo | tests/test_measure_adoption.py | lectura de formato viejo (REQ-006): clave de la telemetría vieja de hooks que el escenario escribe a propósito; `test_new_or_mixed_rows_give_the_same_measure_as_the_old_ones` exige que esté (ola A10a-4) |
| camino | tests/test_measure_adoption.py | lectura de formato viejo (REQ-006): clave vieja de la telemetría de hooks (`route` en la nueva) que el escenario escribe a propósito (ola A10a-4) |
| prosa_grande | tests/test_measure_adoption.py | lectura de formato viejo (REQ-006): valor viejo de `motivo` en el escenario (ola A10a-4) |
| acotada | tests/test_measure_adoption.py | lectura de formato viejo (REQ-006): valor viejo de `motivo` en el escenario (ola A10a-4) |
| no_es_volcado | tests/test_measure_adoption.py | lectura de formato viejo (REQ-006): valor viejo de `motivo` en el escenario (ola A10a-4) |
| bloqueo_id | tests/test_measure_adoption.py | lectura de formato viejo (REQ-006): clave del log de uso de la 0.34.0 que el escenario escribe a propósito; `test_the_new_block_id_counts_the_same_as_the_old_bloqueo_id` la traduce y compara (ola A10a-4) |
| test_the_new_block_id_counts_the_same_as_the_old_bloqueo_id | tests/test_measure_adoption.py | lectura de formato viejo (REQ-006): el nombre del test cita la clave vieja `bloqueo_id` que prueba (ola A10a-4) |
| sesiones | tests/test_test_sessions.py | lectura de formato viejo (decisión 6 de A10a): el fichero de ventanas excluidas que el test escribe en el formato viejo para probar que `merge` lo lee y lo devuelve en el nuevo (ola A10a-4) |
| ventanas | tests/test_test_sessions.py | lectura de formato viejo (decisión 6 de A10a): el fichero de ventanas excluidas que el test escribe en el formato viejo para probar que `merge` lo lee y lo devuelve en el nuevo (ola A10a-4) |
| inicio | tests/test_test_sessions.py | lectura de formato viejo (decisión 6 de A10a): el fichero de ventanas excluidas que el test escribe en el formato viejo para probar que `merge` lo lee y lo devuelve en el nuevo (ola A10a-4) |
| fin | tests/test_test_sessions.py | lectura de formato viejo (decisión 6 de A10a): el fichero de ventanas excluidas que el test escribe en el formato viejo para probar que `merge` lo lee y lo devuelve en el nuevo (ola A10a-4) |
| ventanas-excluidas.json | scripts/test_sessions.py | lectura de formato viejo (decisión 6 de A10a): nombre de antes de `benchmarks/excluded-windows.json`, que `merge` lee si el nuevo no existe y nunca escribe; el congelado de `benchmarks/` no se renombra (ola A10a-4) |
| ventanas-excluidas.json | tests/test_test_sessions.py | lectura de formato viejo (decisión 6 de A10a): nombre de antes de `benchmarks/excluded-windows.json`, que `merge` lee si el nuevo no existe y nunca escribe; el congelado de `benchmarks/` no se renombra (ola A10a-4) |
| sesiones | tests/test_adoption_experiment.py | lectura de formato viejo (decisión 7 de A10a): el fichero de ventanas excluidas en el formato de antes, que el test escribe a propósito para probar que `_banco_claude.anotar_ventana` lo lee y escribe el nuevo (ola A10a-5) |
| ventanas | tests/test_adoption_experiment.py | lectura de formato viejo (decisión 7 de A10a): el fichero de ventanas excluidas en el formato de antes, que el test escribe a propósito para probar que `_banco_claude.anotar_ventana` lo lee y escribe el nuevo (ola A10a-5) |
| inicio | tests/test_adoption_experiment.py | lectura de formato viejo (decisión 7 de A10a): el fichero de ventanas excluidas en el formato de antes, que el test escribe a propósito para probar que `_banco_claude.anotar_ventana` lo lee y escribe el nuevo (ola A10a-5) |
| fin | tests/test_adoption_experiment.py | lectura de formato viejo (decisión 7 de A10a): el fichero de ventanas excluidas en el formato de antes, que el test escribe a propósito para probar que `_banco_claude.anotar_ventana` lo lee y escribe el nuevo (ola A10a-5) |
| motivo | tests/test_adoption_experiment.py | lectura de formato viejo (decisión 7 de A10a): el fichero de ventanas excluidas en el formato de antes, que el test escribe a propósito para probar que `_banco_claude.anotar_ventana` lo lee y escribe el nuevo (ola A10a-5) |
| tanda | tests/test_adoption_experiment.py | lectura de formato viejo (decisión 7 de A10a): el fichero de ventanas excluidas en el formato de antes, que el test escribe a propósito para probar que `_banco_claude.anotar_ventana` lo lee y escribe el nuevo (ola A10a-5) |
| ventanas-excluidas.json | tests/test_adoption_experiment.py | lectura de formato viejo (decisión 7 de A10a): el fichero de ventanas excluidas en el formato de antes, que el test escribe a propósito para probar que `_banco_claude.anotar_ventana` lo lee y escribe el nuevo (ola A10a-5) |
| bloqueo | tests/test_adoption_experiment.py | lectura de formato viejo (REQ-006): clave de la telemetría vieja de hooks (`bloqueo: encendido`) que el test da a `corrida_valida` a propósito (ola A10a-5) |
| apagado_fichero | tests/test_adoption_experiment.py | lectura de formato viejo (REQ-006): valor viejo de `bloqueo` en la misma fila (ola A10a-5) |
| ficheros | tests/test_adoption_experiment.py | lectura de formato viejo: el `MANIFEST.json` del test copia el congelado de `benchmarks/resumen-estructurado/`, que `source_text` traduce con la tabla `sources_manifest` (ola A10a-5) |
| origen | tests/test_adoption_experiment.py | lectura de formato viejo: mismo `MANIFEST.json` del test (ola A10a-5) |
| resultados.jsonl | scripts/adoption_experiment.py | lectura de formato viejo: `--resume` sigue en el `resultados.jsonl` de una tanda empezada antes del renombrado; sus filas se leen con la tabla `adoption_runs` (ola A10a-5) |
| descartada | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): el test nuevo cuenta las filas `descartada` del resultado congelado (`benchmarks/afinidad-2026-10/resultados/gemma3-4b.jsonl`) para comprobar que los tres cargadores las dan como `discarded` (ola A10b-1) |
| descartada_motivo | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): mismo test; comprueba que no queda la clave vieja (ola A10b-1) |
| rechazo_por_contexto | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): valor viejo de `outcome` que el test escribe a propósito para probar la traducción (ola A10b-1) |
| truncado_repetido | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): valor viejo de `score.zero_by` que el test escribe a propósito (ola A10b-1) |
| descartada | tests/test_affinity_batch.py | lectura de formato viejo (decisión 6 de A10): el test nuevo cuenta las filas `descartada` del resultado congelado para comprobar `_read_rows` (ola A10b-1) |
| inicio_utc | tests/test_affinity_batch.py | lectura de formato viejo (decisión 6 de A10): clave de `ventanas-tanda.json` congelado que el test compara con la traducida (ola A10b-1) |
| ventanas-tanda.json | tests/test_affinity_batch.py | lectura de formato viejo (decisión 6 de A10): nombre del fichero de ventanas de antes de `batch-windows.json`, del que parte `register_window` (ola A10b-1) |
| huellas.json | tests/test_affinity_batch.py | lectura de formato viejo (decisión 6 de A10): nombre de las huellas de antes de `footprints.json`, con las que `write_footprints` compara una tanda empezada antes (ola A10b-1) |
| procedencia | tests/test_benchmark.py | lectura de formato viejo (decisión 6 de A10): el test nuevo comprueba que el corpus congelado dice `procedencia` y `load_corpus` lo da como `provenance` (ola A10b-1) |
| veredicto.json | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): el test del ciclo copia el veredicto congelado y comprueba que se lee si falta `verdict.json` (ola A10b-2) |
| solo_mecanicas | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): clave vieja del veredicto que el test exige que ya no se escriba (ola A10b-2) |
| reglas_sha256 | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): clave vieja del veredicto que el test exige que ya no se escriba (ola A10b-2) |
| rol_comparado | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): clave vieja de la celda que el test exige que ya no se escriba (ola A10b-2) |
| pares | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): el juicio de la hoja de commits en el formato de `hoja_pares` de antes, escrito a mano en `_OLD_NAMES` (ola A10b-2) |
| reglas.json | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): `reglas.json` congelado, que `read_affinity_rules` y `rules_file` siguen leyendo (ola A10b-2) |
| humano | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): fila de `hoja_pares.py destapar --json` de antes, que `merge_unblinded_pairs` suma (ola A10b-2) |
| celdas | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): celda del `veredicto.json` de antes, escrita a mano, con la que el test comprueba que el estado viejo se lee en inglés (ola A10b-3) |
| estado | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): mismo test; clave vieja del estado de la celda (`aprobada`/`rechazada`/`sin base`), que el lector traduce a `state` (ola A10b-3) |
| pares | tests/test_pair_sheet.py | lectura de formato viejo (decisión 6 de A10): control de que la `clave-1.json` congelada sigue con el formato viejo antes de leerla con `read_commit` (ola A10b-4) |
| respuestas | tests/test_pair_sheet.py | lectura de formato viejo (decisión 6 de A10): control de que la `respuestas-1.json` congelada sigue con el formato viejo (ola A10b-4) |
| respuestas-1.json | tests/test_pair_sheet.py | lectura de formato viejo (decisión 6 de A10): nombre de las respuestas congeladas de la hoja 1, que el test lee (ola A10b-4) |
| clave-1.json | tests/test_pair_sheet.py | lectura de formato viejo (decisión 6 de A10): nombre de la clave congelada de la hoja 1, que el test lee (ola A10b-4) |
| juegos | tests/test_pair_sheet.py | lectura de formato viejo (decisión 6 de A10): control de que el `trampas.json` congelado sigue con el formato viejo (ola A10b-4) |
| cobertura | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): señal vieja de `reference_signal` que el test exige en el `cases.json` congelado antes de comprobar que se lee en inglés (ola A10b-4) |
| prohibido | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): mismo test: señal vieja del corpus congelado (ola A10b-4) |
| json_valido | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): mismo test: señal vieja del corpus congelado (ola A10b-4) |
| json_campos | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): mismo test: señal vieja del corpus congelado (ola A10b-4) |
| ejecucion | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): mismo test: señal vieja del corpus congelado (ola A10b-4) |
| conteos | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): mismo test: señal vieja del corpus congelado (ola A10b-4) |
| eventos_local | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): control de que el `conteos-log.json` congelado sigue con las claves viejas (ola A10b-4) |
| seleccion | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): control de que el corpus de afinidad congelado sigue con las claves viejas (ola A10b-4) |
| puntuador | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): mismo test: clave vieja de cada caso del corpus de afinidad congelado (ola A10b-4) |
| procedencia | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): mismo test: el caso normalizado ya no la lleva (ola A10b-4) |
| tipo | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): mismo test: el puntuador normalizado ya no la lleva (ola A10b-4) |
| excluir | tests/test_corpus.py | lectura de formato viejo (decisión 6 de A10): valor de `privacy` del corpus de afinidad congelado (lo escribió `--privacy excluir`) (ola A10b-4) |
| trampas.json | tests/test_pair_sheet.py | lectura de formato viejo (decisión 6 de A10): el `trampas.json` congelado, que `REAL_SETS` lee normalizado y el test de formato viejo en crudo (ola A10b-6) |
| reglas.json | tests/test_pair_sheet.py | lectura de formato viejo (decisión 6 de A10): el `reglas.json` congelado de la hoja 1, que `read_rules` sigue leyendo (ola A10b-4; fila añadida en A10b-6) |
| calidad | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): valor viejo de `kind` del corpus y de los resultados congelados, escrito a mano en `_OLD_KINDS` para comprobar que los cargadores lo dan como `quality` (ola A10b-5) |
| techo | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): mismo test; valor viejo de `kind` del sondeo de techo, que se lee como `ceiling` (ola A10b-5) |
| huellas.json | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): `huellas.json` congelado, que `footprints_file` sigue leyendo si falta `footprints.json` (ola A10b-2; fila añadida en A10b-5) |

## Envoltorio de REQ-046

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| medir_enfriamiento | scripts/medir_enfriamiento.py | envoltorio de REQ-046: nombre del script y opciones `--desde`/`--hasta`/`--excluir` del comando de P-4; se retira tras la medición de los 90 días (~2026-12-14, backlog 1.6) (ola A10a-3) |
| medir_enfriamiento | tests/test_measure_cooldown.py | envoltorio de REQ-046: los dos tests que cargan el envoltorio; se retiran con él (ola A10a-3) |
| medir_enfriamiento.py | tests/test_measure_cooldown.py | envoltorio de REQ-046: ruta del envoltorio en esos dos tests (ola A10a-3) |

## Dato de un tercero

| Nombre | Fichero | Motivo |
| --- | --- | --- |

## Dato de prueba del detector

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| * | tests/test_detect_spanish_names.py | casos de control positivo del detector (REQ-044) |
| * | scripts/data/* | léxico congelado y palabras reservadas del detector (REQ-044) |

## Palabra inglesa que el léxico toma por española

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| meterHTML | src/local_delegate/web/metrics.py | «meter» = medidor (inglés): pinta las barras `.meter` de la tarjeta Sistema; el léxico lo lee como el verbo español (ola A8b, decisión 7) |
| quotaMeter | src/local_delegate/web/metrics.py | «meter» = medidor (inglés): nombre nuevo de `medidorCuota` en A8b, mismo falso positivo que `meterHTML` |

## Dato congelado de corpus o caso

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| nonce-neutro | scripts/clean_watcher_fixtures.py | dato congelado de corpus o caso: valor neutro (`NEUTRAL_NONCE`) que el limpiador ya escribió en las copias de `tests/fixtures/vigilante/*.html`; cambiarlo obligaría a reescribir esas copias (ola A10a-1) |
| catalogo-2026-09 | tests/test_resource_probe.py | dato congelado de corpus o caso: directorio del corpus congelado en `benchmarks/` (ola A10a-3) |
| clasificar-53 | tests/test_resource_probe.py | dato congelado de corpus o caso: id de un caso del corpus congelado (ola A10a-3) |
| adopcion-directa | scripts/adoption_experiment.py | dato congelado de corpus o caso: directorio del corpus congelado en `benchmarks/` (ola A10a-5) |
| tareas.json | scripts/adoption_experiment.py | dato congelado de corpus o caso: `benchmarks/adopcion-directa/tareas.json`, que no reescribe nadie; `load_tasks` traduce sus claves (ola A10a-5) |
| wiki-instalacion | scripts/adoption_experiment.py | dato congelado de corpus o caso: id de una tarea del corpus congelado (ola A10a-5) |
| wiki-instalacion | tests/test_adoption_experiment.py | dato congelado de corpus o caso: id de una tarea del corpus congelado (ola A10a-5) |
| experimento-adopcion | scripts/adoption_experiment.py | dato congelado de corpus o caso: etiqueta de las tandas ya anotadas en el fichero congelado de ventanas excluidas (ola A10a-5) |
| resumen-estructurado | scripts/measure_structured_summary.py | dato congelado de corpus o caso: directorio del corpus congelado en `benchmarks/` (copias fijas, `MANIFEST.json` y resultados ya escritos) (ola A10a-6) |
| afinidad-2026-10 | scripts/analyze_benchmark.py | dato congelado de corpus o caso: directorio del corpus congelado en `benchmarks/` (ola A10b-1) |
| afinidad-2026-10 | scripts/dev/affinity_batch.py | dato congelado de corpus o caso: directorio del corpus congelado en `benchmarks/` (ola A10b-1) |
| afinidad-2026-10 | tests/test_affinity.py | dato congelado de corpus o caso: directorio del corpus congelado en `benchmarks/` (ola A10b-1) |
| afinidad-2026-10 | tests/test_affinity_batch.py | dato congelado de corpus o caso: directorio del corpus congelado en `benchmarks/` (ola A10b-1) |
| catalogo-2026-09 | tests/test_benchmark.py | dato congelado de corpus o caso: directorio del corpus congelado en `benchmarks/` (ola A10b-1) |
| clasificar-53 | tests/test_benchmark.py | dato congelado de corpus o caso: id de un caso del corpus congelado (ola A10b-1) |
| describir-dashboard | tests/test_benchmark.py | dato congelado de corpus o caso: id de un caso del corpus congelado (ola A10b-1) |
| leer-cifras-dashboard | tests/test_benchmark.py | dato congelado de corpus o caso: id de un caso del corpus congelado (ola A10b-1) |
| resumen-md-2k | tests/test_benchmark.py | dato congelado de corpus o caso: id de un caso del corpus congelado (ola A10b-1) |
| techo-resumen-103k | tests/test_benchmark.py | dato congelado de corpus o caso: id de un caso del corpus congelado (ola A10b-1) |
| techo-commit-156k | scripts/analyze_benchmark.py | dato congelado de corpus o caso: id del caso de techo del corpus congelado; resultados, hojas y claves lo citan (ola A10b-1) |
| techo-commit-156k | scripts/dev/affinity_batch.py | dato congelado de corpus o caso: id del caso de techo del corpus congelado (ola A10b-1) |
| LD_HOOK_READ_BLOQUEAR | scripts/build_corpus.py | dato congelado de corpus o caso: término esperado de un caso congelado (el caso que resume la nota de la variable vieja) (ola A10b-4) |
| a_favor | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| abstenciones | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| afinidad-2026-10 | scripts/build_corpus.py | dato congelado de corpus o caso: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) (ola A10b-4) |
| afinidad-2026-10 | scripts/pair_sheet.py | dato congelado de corpus o caso: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) (ola A10b-4) |
| asistentes | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| catalogo-2026-09 | scripts/build_corpus.py | dato congelado de corpus o caso: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) (ola A10b-4) |
| clasifica-bug-con-etiquetas-en-ingles | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| clasifica-deportes | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| clasifica-economia | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| clasifica-idioma-aleman | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| clasifica-ironia | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| clasifica-lenguaje-de-programacion | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| clasifica-negacion-reenvio | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| clasifica-peticion-de-funcion | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| clasificar-53 | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| cliente | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| correo | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| delega-contar-palabras | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| delega-fecha-iso | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| delega-lista-a-csv | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| delega-mayusculas | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| delegar-56 | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| describir-dashboard | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| en_contra | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| explicar-install-20k | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| explicar-metrics-15k | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| extrae-acta-con-cifras | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| extrae-correo-sin-telefono | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| extrae-factura | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| extrae-linea-de-acceso-web | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| extrae-linea-de-log-con-numeros | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| extrae-producto-sin-existencias | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| extrae-reunion-sin-organizador | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| extrae-toml-sin-licencia | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| extraer-toml-2k | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| extraer-uvlock-48k | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| factura | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| fecha | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| hora | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| leer-cifras-dashboard | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| lugar | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| metodo | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| moneda | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| nivel | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| organizador | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| precio | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| real-reescrito | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| resume-ruff-cinco-reglas | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| resume-ruff-tres-reglas | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| resume-ruff-un-solo-archivo | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| resumen-changelog-7k | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| resumen-md-10k | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| resumen-md-2k | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| ruta | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| servicio | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| socios | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| talla | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| techo-commit-156k | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| techo-resumen-103k | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| telefono | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| traduce-guia-de-inicio | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| traduce-lista-de-version | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| traduce-registro-de-cambios | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| traduce-solucion-de-problemas | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| traducir-42 | scripts/build_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-4) |
| latencia_ms | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| `nombre` | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado de un caso congelado (contenido del documento en español que el modelo extrae) (ola A10b-4) |
| asunto | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado del caso `extrae-correo-sin-telefono` (contenido del documento en español que el modelo extrae); el `asunto` de las trampas sí pasa a `subject` (ola A10b-4) |
| codigo | scripts/build_corpus.py | dato congelado de corpus o caso: campo esperado del caso `extrae-linea-de-acceso-web` (contenido del documento en español que el modelo extrae); el `codigo` del puntuador sí pasa a `code` (ola A10b-4) |
| primer_paquete | scripts/build_corpus.py | dato congelado de corpus o caso: campo que el caso `extraer-uvlock-48k` pide extraer; va en su prompt congelado y en `expected_json_fields` del corpus (ola A10b-4) |
| catalogo-2026-09 | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) (ola A10b-5) |
| afinidad-2026-10 | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) (ola A10b-5) |
| techo-gemma4-26b-a4b.jsonl | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: fichero de resultados del sondeo de techo congelado en `benchmarks/afinidad-2026-10/resultados/` (no se reescribe) (ola A10b-5) |
| clasificar-53 | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-5) |
| describir-dashboard | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-5) |
| explicar-install-20k | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-5) |
| explicar-metrics-15k | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-5) |
| extraer-uvlock-48k | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-5) |
| resumen-changelog-7k | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-5) |
| resumen-md-10k | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-5) |
| resumen-md-2k | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-5) |
| techo-resumen-103k | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-5) |
| catalogo-2026-09 | tests/test_corpus.py | dato congelado de corpus o caso: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) (ola A10b-6) |
| afinidad-2026-10 | tests/test_corpus.py | dato congelado de corpus o caso: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) (ola A10b-6) |
| afinidad-2026-10 | tests/test_pair_sheet.py | dato congelado de corpus o caso: nombre de directorio de un corpus congelado en `benchmarks/` (no se reescribe) (ola A10b-6) |
| clasifica-bug-con-etiquetas-en-ingles | tests/test_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-6) |
| clasificar-53 | tests/test_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-6) |
| explicar-install-20k | tests/test_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-6) |
| explicar-metrics-15k | tests/test_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-6) |
| resumen-changelog-7k | tests/test_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-6) |
| resumen-md-10k | tests/test_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-6) |
| resumen-md-2k | tests/test_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-6) |
| techo-resumen-106k | tests/test_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-6) |
| techo-resumen-120k | tests/test_corpus.py | dato congelado de corpus o caso: id de caso de un corpus congelado en `benchmarks/` (resultados, hojas y claves lo citan; no se reescribe) (ola A10b-6) |
| clasificar-53.txt | tests/test_corpus.py | dato congelado de corpus o caso: fichero de `fuentes/` de un corpus congelado en `benchmarks/` (no se reescribe) (ola A10b-6) |
| resumen-md-2k.md | tests/test_corpus.py | dato congelado de corpus o caso: fichero de `fuentes/` de un corpus congelado en `benchmarks/` (no se reescribe) (ola A10b-6) |
| real-reescrito | tests/test_corpus.py | dato congelado de corpus o caso: valor de `source_body` de la trampa de la misma zona en el `trampas.json` congelado (ola A10b-6) |
| real-reescrito | tests/test_pair_sheet.py | dato congelado de corpus o caso: valor de `source_body` de la trampa de la misma zona en el `trampas.json` congelado (ola A10b-6) |
| estado.json | tests/test_corpus.py | dato congelado de corpus o caso: identificador sacado del diff de un commit real del historial (`commit-diff-19k`), contenido del caso (ola A10b-6) |

## Entrada de interfaz escrita por una persona

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| si | scripts/pair_sheet.py | entrada de interfaz escrita por una persona; se traduce en el frente B con lectura de las dos formas: respuesta que la persona escribe en la hoja `.md` (en español, como la hoja) (ola A10b-4; sale de «Pendiente» en A10b-5) |
| parcial | scripts/pair_sheet.py | entrada de interfaz escrita por una persona; se traduce en el frente B con lectura de las dos formas: respuesta que la persona escribe en la hoja `.md` (ola A10b-4; sale de «Pendiente» en A10b-5) |
| empate | scripts/pair_sheet.py | entrada de interfaz escrita por una persona; se traduce en el frente B con lectura de las dos formas: respuesta que la persona escribe en la hoja `.md`, y la elección que `unblind` imprime y escribe en su `--json` (ola A10b-4; sale de «Pendiente» en A10b-5) |
| EMPATE | scripts/pair_sheet.py | entrada de interfaz escrita por una persona; se traduce en el frente B con lectura de las dos formas: la misma respuesta escrita en mayúsculas (ola A10b-4; sale de «Pendiente» en A10b-5) |
| empate | tests/test_analyze_benchmark.py | entrada de interfaz escrita por una persona; se traduce en el frente B con lectura de las dos formas: la elección «empate» que `pair_sheet.py unblind --json` escribe en `human` y `pairs_for_role` suma; el test la escribe como la escribe `unblind` (ola A10b-5) |
| empate | tests/test_pair_sheet.py | entrada de interfaz escrita por una persona; se traduce en el frente B con lectura de las dos formas: la elección «empate» que `unblind --json` escribe en `human` (ola A10b-6) |
| Inventa | tests/test_pair_sheet.py | entrada de interfaz escrita por una persona; se traduce en el frente B con lectura de las dos formas: la etiqueta de la pregunta en la hoja `.md` que la persona contesta a mano (ola A10b-6) |

## Pendiente

| Nombre | Fichero | Motivo |
| --- | --- | --- |
