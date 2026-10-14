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

## Pendiente

| Nombre | Fichero | Motivo |
| --- | --- | --- |
