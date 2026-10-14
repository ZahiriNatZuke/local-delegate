# Excepciones del detector de nombres en español (REQ-016)

Lista de nombres en español que pueden quedar en el repo al cerrar el frente A, cada uno con su
motivo. La lee `scripts/detect_spanish_names.py --exceptions <este fichero>`: toma las filas de las
tablas (`| Nombre | Fichero | Motivo |`) y aparta un hallazgo cuando coinciden el nombre y el
fichero (los dos admiten comodines, `*` para cualquiera; el nombre distingue mayúsculas; el
comodín del nombre funciona desde el cierre del frente A, lote 4).

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
- texto de salida que traduce el frente B (enmienda del 2026-10-14, cierre del frente A, decisión 1
  de la sesión principal, como desviación de REQ-016): rótulos y motivos que ve una persona y que
  el detector toma por nombres de máquina (rótulos del JS del panel, `sin_cruce` de `recompute`,
  `pruebas` de `excluded_by_reason`); cada fila nombra la ola B que lo traduce;
- **pendiente**: lo que el frente A renombra pero se publica en el B (las subclaves y marcadores
  de REQ-010, que salen en B2).

Al cerrar el frente A, la sección «Pendiente» solo puede tener lo de REQ-010; al cerrar el cambio,
tiene que estar vacía, igual que «Texto de salida que traduce el frente B».

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
| LD_HOOK_READ_BLOQUEAR | src/local_delegate/config.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del interruptor del bloqueo que leen el daemon y los hooks, y los tests que la prueban (cierre del frente A, lote 4) |
| LD_HOOK_READ_BLOQUEAR | src/local_delegate/deprecations.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del interruptor del bloqueo que leen el daemon y los hooks, y los tests que la prueban (cierre del frente A, lote 4) |
| LD_HOOK_READ_BLOQUEAR | src/local_delegate/resources/hooks/hook_common.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del interruptor del bloqueo que leen el daemon y los hooks, y los tests que la prueban (cierre del frente A, lote 4) |
| LD_HOOK_READ_BLOQUEAR | tests/test_cli_renamed_names.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del interruptor del bloqueo que leen el daemon y los hooks, y los tests que la prueban (cierre del frente A, lote 4) |
| LD_HOOK_READ_BLOQUEAR | tests/test_hook_legacy_names.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del interruptor del bloqueo que leen el daemon y los hooks, y los tests que la prueban (cierre del frente A, lote 4) |
| LD_HOOK_READ_BLOQUEAR | tests/test_environment_isolation.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del interruptor del bloqueo que leen el daemon y los hooks, y los tests que la prueban (cierre del frente A, lote 4) |
| LD_HOOK_READ_INTERRUPTOR | src/local_delegate/config.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable de la ruta del interruptor, y los tests que la prueban (cierre del frente A, lote 4) |
| LD_HOOK_READ_INTERRUPTOR | src/local_delegate/deprecations.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable de la ruta del interruptor, y los tests que la prueban (cierre del frente A, lote 4) |
| LD_HOOK_READ_INTERRUPTOR | src/local_delegate/resources/hooks/hook_common.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable de la ruta del interruptor, y los tests que la prueban (cierre del frente A, lote 4) |
| LD_HOOK_READ_INTERRUPTOR | tests/test_cli_renamed_names.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable de la ruta del interruptor, y los tests que la prueban (cierre del frente A, lote 4) |
| LD_HOOK_READ_INTERRUPTOR | tests/test_hook_legacy_names.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable de la ruta del interruptor, y los tests que la prueban (cierre del frente A, lote 4) |
| LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO | src/local_delegate/config.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del resumen estructurado, y los tests que la prueban (cierre del frente A, lote 4) |
| LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO | src/local_delegate/deprecations.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del resumen estructurado, y los tests que la prueban (cierre del frente A, lote 4) |
| LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO | tests/test_cli_renamed_names.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del resumen estructurado, y los tests que la prueban (cierre del frente A, lote 4) |
| LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO | tests/test_structured_summary.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del resumen estructurado, y los tests que la prueban (cierre del frente A, lote 4) |
| LOCAL_DELEGATE_COSTE_RESPALDO | src/local_delegate/config.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del coste de respaldo, y los tests que la prueban (cierre del frente A, lote 4) |
| LOCAL_DELEGATE_COSTE_RESPALDO | src/local_delegate/deprecations.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del coste de respaldo, y los tests que la prueban (cierre del frente A, lote 4) |
| LOCAL_DELEGATE_COSTE_RESPALDO | tests/test_cli_renamed_names.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del coste de respaldo, y los tests que la prueban (cierre del frente A, lote 4) |
| LOCAL_DELEGATE_COSTE_RESPALDO | tests/test_density.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); variable del coste de respaldo, y los tests que la prueban (cierre del frente A, lote 4) |
| recalcular-coste | src/local_delegate/cli.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); subcomando viejo de `recompute-cost`, y el test que lo prueba (cierre del frente A, lote 4) |
| recalcular-coste | src/local_delegate/deprecations.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); subcomando viejo de `recompute-cost`, y el test que lo prueba (cierre del frente A, lote 4) |
| recalcular-coste | tests/test_cli_renamed_names.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); subcomando viejo de `recompute-cost`, y el test que lo prueba (cierre del frente A, lote 4) |
| recalcular-coste | tests/test_cli_english.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); el humo en inglés comprueba que su aviso sale en inglés (frente B, ola B1a) |
| reiniciar-calibracion | tests/test_cli_renamed_names.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); opción vieja `--reiniciar-calibracion` de `--reset-calibration`, que el test usa (cierre del frente A, lote 4) |
| local-delegate-bloqueo-apagado | src/local_delegate/deprecations.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); fichero de `~/.claude/` que apaga el bloqueo; lo lee el hook (REQ-012) (cierre del frente A, lote 4) |
| local-delegate-bloqueo-apagado | src/local_delegate/resources/hooks/hook_common.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); fichero de `~/.claude/` que apaga el bloqueo; lo lee el hook (REQ-012) (cierre del frente A, lote 4) |
| enfriamiento.json | src/local_delegate/deprecations.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); escritura doble (`legacy_write`) de `cooldown.json` con el nombre viejo, para que los hooks de versiones anteriores vean los modelos enfriados (REQ-005) (cierre del frente A, lote 4) |
| enfriamiento.json | src/local_delegate/resources/hooks/hook_common.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); escritura doble (`legacy_write`) de `cooldown.json` con el nombre viejo, para que los hooks de versiones anteriores vean los modelos enfriados (REQ-005) (cierre del frente A, lote 4) |
| enfriamiento.json | tests/test_cooldown.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); escritura doble (`legacy_write`) de `cooldown.json` con el nombre viejo, para que los hooks de versiones anteriores vean los modelos enfriados (REQ-005) (cierre del frente A, lote 4) |
| enfriamiento.json | tests/test_fallback.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); escritura doble (`legacy_write`) de `cooldown.json` con el nombre viejo, para que los hooks de versiones anteriores vean los modelos enfriados (REQ-005) (cierre del frente A, lote 4) |
| enfriamiento.json | tests/test_f1_conformance.py | alias de compatibilidad (REQ-001, REQ-002): nombre viejo registrado en `deprecations.DEPRECATED_NAMES` (`introduced` 0.35.0), que avisa y se retira en la 0.38.0 (ola R); escritura doble (`legacy_write`) de `cooldown.json` con el nombre viejo, para que los hooks de versiones anteriores vean los modelos enfriados (REQ-005) (cierre del frente A, lote 4) |
| anotar_llamada.py | tests/test_install.py | alias de compatibilidad permanente (REQ-012), como la fila de `install.py`: los tests que comprueban que `install` sobre una 0.34 retira el hook viejo `anotar_llamada.py` (cierre del frente A, lote 4) |
| test_*anotar_llamada* | tests/test_install.py | alias de compatibilidad permanente (REQ-012), como la fila de `install.py`: los tests que comprueban que `install` sobre una 0.34 retira el hook viejo `anotar_llamada.py` (cierre del frente A, lote 4) |

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
| trampas.json | tests/test_pair_sheet.py | lectura de formato viejo (decisión 6 de A10): el `trampas.json` congelado, que `REAL_SETS` lee normalizado y el test de formato viejo en crudo (ola A10b-6) |
| reglas.json | tests/test_pair_sheet.py | lectura de formato viejo (decisión 6 de A10): el `reglas.json` congelado de la hoja 1, que `read_rules` sigue leyendo (ola A10b-4; fila añadida en A10b-6) |
| calidad | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): valor viejo de `kind` del corpus y de los resultados congelados, escrito a mano en `_OLD_KINDS` para comprobar que los cargadores lo dan como `quality` (ola A10b-5) |
| techo | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): mismo test; valor viejo de `kind` del sondeo de techo, que se lee como `ceiling` (ola A10b-5) |
| ruta | tests/test_affinity.py | lectura de formato viejo (cierre del frente A, lote 1): clave de la huella del `veredicto.json` congelado que el test lee a propósito para comprobar que sale como `path` |
| tamano_bytes | tests/test_affinity.py | lectura de formato viejo (cierre del frente A, lote 1): mismo test; sale como `size_bytes` |
| ruta | tests/test_analyze_benchmark.py | lectura de formato viejo (cierre del frente A, lote 1): clave de la huella del `huellas.json` congelado que el test lee a propósito para comprobar que sale como `path` |
| tamano_bytes | tests/test_analyze_benchmark.py | lectura de formato viejo (cierre del frente A, lote 1): mismo test; sale como `size_bytes` |
| huellas.json | tests/test_analyze_benchmark.py | lectura de formato viejo (decisión 6 de A10): `huellas.json` congelado, que `footprints_file` sigue leyendo si falta `footprints.json` (ola A10b-2; fila añadida en A10b-5) |
| generado | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 3): valor viejo de `provenance` de los corpus congelados, escrito a mano en `_OLD_PROVENANCES` para comprobar que se lee como `generated` |
| inventado | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 3): mismo test; se lee como `made_up` |
| texto | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 3): valor viejo de `media_type` de los corpus congelados (`_OLD_MEDIA`); se lee como `text` |
| imagen | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 3): mismo test; se lee como `image` |
| trampa | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 3): valor viejo de `sheet_role` del corpus de afinidad congelado (`_OLD_SHEET_ROLES`); se lee como `trap` |
| rol_en_hoja | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 3): mismo test; clave vieja de `sheet_role` que el test lee en crudo del congelado |
| techo | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 3): valor viejo de `scorer.kind` del corpus de afinidad congelado (`_OLD_SCORER_KINDS`); se lee como `ceiling` |
| hoja | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 3): mismo test; se lee como `sheet` |
| privacidad | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 5): clave vieja de `selection.privacy` del corpus de afinidad congelado; el test comprueba que su valor viejo sale traducido (`exclude`) |
| trampas | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 5): clave vieja de `selection.traps` del corpus de afinidad y de cada juego del `trampas.json` congelados, que el test lee en crudo para comprobar que la fecha y el origen del cuerpo salen traducidos |
| juegos | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 5): mismo test; clave vieja de `sets` del `trampas.json` congelado |
| cuerpo_origen | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 5): mismo test; clave vieja de `source_body`, cuyo valor viejo sale como `written`/`real-rewritten` |
| generado | tests/test_benchmark.py | lectura de formato viejo (cierre del frente A, lote 3): valor viejo de `provenance` del corpus congelado, escrito a mano para comprobar que `load_corpus` lo da como `generated` |
| inventado | tests/test_benchmark.py | lectura de formato viejo (cierre del frente A, lote 3): mismo test; sale como `made_up` |
| tipo | tests/test_pair_sheet.py | lectura de formato viejo (cierre del frente A, lote 3): clave vieja del par de `clave-1.json` congelado, que el test lee en crudo para comprobar que el par `trampa` sale como `trap` |
| * | src/local_delegate/legacy_names.py | lectura de formato viejo: es la tabla de nombres viejos que se traducen al leer (claves y valores de cada formato persistido) (cierre del frente A, lote 4) |
| * | tests/test_recompute_legacy.py | lectura de formato viejo (REQ-005, REQ-006, REQ-008): siembra a propósito `coste-agregados.json` y el registro del statusline con los nombres viejos para probar su lectura (cierre del frente A, lote 4) |
| * | tests/test_deprecations.py | lectura de formato viejo: prueba la API de `legacy_names` (`read_key`, `normalize`) con claves y valores viejos (cierre del frente A, lote 4) |
| fallos | src/local_delegate/resources/hooks/hook_common.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| fallos | tests/test_cooldown.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| fallos | tests/test_fallback.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| fallos | tests/test_f1_conformance.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| fallos | tests/test_fallback_observability.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| espera_s | src/local_delegate/resources/hooks/hook_common.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| espera_s | tests/test_cooldown.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| espera_s | tests/test_fallback.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| espera_s | tests/test_f1_conformance.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| espera_s | tests/test_fallback_observability.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| hasta | src/local_delegate/resources/hooks/hook_common.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| hasta | tests/test_cooldown.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| hasta | tests/test_fallback.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| hasta | tests/test_f1_conformance.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| hasta | tests/test_fallback_observability.py | lectura de formato viejo (REQ-005): claves viejas de `enfriamiento.json` (`COOLDOWN_STATE_KEYS`), que el hook lee y escribe y los tests siembran (cierre del frente A, lote 4) |
| enfriamiento-eventos.jsonl | tests/test_cooldown.py | lectura de formato viejo (REQ-005): registro viejo de eventos de enfriamiento que el test siembra (cierre del frente A, lote 4) |
| local-delegate-bloqueos.jsonl | src/local_delegate/resources/hooks/hook_common.py | lectura de formato viejo (REQ-012): registro y carpeta de los hooks de la 0.34, que el hook sigue leyendo (cierre del frente A, lote 4) |
| local-delegate-bloqueos.jsonl | tests/test_hook_legacy_names.py | lectura de formato viejo (REQ-012): registro y carpeta de los hooks de la 0.34, que el hook sigue leyendo (cierre del frente A, lote 4) |
| local-delegate-llamadas | src/local_delegate/resources/hooks/hook_common.py | lectura de formato viejo (REQ-012): registro y carpeta de los hooks de la 0.34, que el hook sigue leyendo (cierre del frente A, lote 4) |
| local-delegate-llamadas | tests/test_hook_legacy_names.py | lectura de formato viejo (REQ-012): registro y carpeta de los hooks de la 0.34, que el hook sigue leyendo (cierre del frente A, lote 4) |
| toolu_viejo | tests/test_hook_legacy_names.py | lectura de formato viejo (REQ-012): llamada sembrada en la carpeta vieja de los hooks (cierre del frente A, lote 4) |
| toolu_viejo.json | tests/test_hook_legacy_names.py | lectura de formato viejo (REQ-012): llamada sembrada en la carpeta vieja de los hooks (cierre del frente A, lote 4) |
| cuota-statusline.jsonl | tests/test_dashboard_cost.py | lectura de formato viejo (REQ-033): nombre viejo del registro del statusline, que se sigue leyendo (cierre del frente A, lote 4) |
| cuota-statusline.jsonl | tests/test_recompute.py | lectura de formato viejo (REQ-033): nombre viejo del registro del statusline, que se sigue leyendo (cierre del frente A, lote 4) |
| bloqueo_id | tests/test_metrics.py | lectura de formato viejo (REQ-007, REQ-008): filas de log y bloqueos con claves y clases de error viejas que el test siembra (cierre del frente A, lote 4) |
| secciones | tests/test_metrics.py | lectura de formato viejo (REQ-007, REQ-008): filas de log y bloqueos con claves y clases de error viejas que el test siembra (cierre del frente A, lote 4) |
| fallo_conexion | tests/test_metrics.py | lectura de formato viejo (REQ-007, REQ-008): filas de log y bloqueos con claves y clases de error viejas que el test siembra (cierre del frente A, lote 4) |
| b-viejo | tests/test_metrics.py | lectura de formato viejo (REQ-007, REQ-008): filas de log y bloqueos con claves y clases de error viejas que el test siembra (cierre del frente A, lote 4) |
| timeout_lectura | tests/test_metrics.py | lectura de formato viejo (REQ-007, REQ-008): filas de log y bloqueos con claves y clases de error viejas que el test siembra (cierre del frente A, lote 4) |
| backend_ausente | tests/test_metrics.py | lectura de formato viejo (REQ-007, REQ-008): filas de log y bloqueos con claves y clases de error viejas que el test siembra (cierre del frente A, lote 4) |
| mcp_ajeno | tests/test_hooks_telemetry_api.py | lectura de formato viejo (REQ-008): telemetría de hooks en el formato viejo que el test siembra (cierre del frente A, lote 4) |
| prosa_grande | tests/test_hooks_telemetry_api.py | lectura de formato viejo (REQ-008): telemetría de hooks en el formato viejo que el test siembra (cierre del frente A, lote 4) |
| entradas | tests/test_attribution.py | lectura de formato viejo (REQ-005): relleno viejo (`_old_backfill`) que el test siembra (cierre del frente A, lote 4) |
| banco | tests/test_attribution.py | lectura de formato viejo (REQ-005): relleno viejo (`_old_backfill`) que el test siembra (cierre del frente A, lote 4) |
| cruce | tests/test_attribution.py | lectura de formato viejo (REQ-005): relleno viejo (`_old_backfill`) que el test siembra (cierre del frente A, lote 4) |
| sin_cruce | tests/test_attribution.py | lectura de formato viejo (REQ-005): relleno viejo (`_old_backfill`) que el test siembra (cierre del frente A, lote 4) |
| causa | tests/test_checks.py | lectura de formato viejo: claves viejas que `checks.py` lee con `read_key` (cierre del frente A, lote 4) |
| detalle | tests/test_checks.py | lectura de formato viejo: claves viejas que `checks.py` lee con `read_key` (cierre del frente A, lote 4) |
| n_por_mes | src/local_delegate/valuation.py | lectura de formato viejo (REQ-006): claves viejas de `coste-agregados.json` que `valuation.py` lee con `read_key` (cierre del frente A, lote 4) |
| plazo_dias | src/local_delegate/valuation.py | lectura de formato viejo (REQ-006): claves viejas de `coste-agregados.json` que `valuation.py` lee con `read_key` (cierre del frente A, lote 4) |
| config.rol_retirado | tests/test_fast_role_retired.py | lectura de formato viejo: id de check retirado que el test comprueba que ya no sale (cierre del frente A, lote 4) |
| celdas | tests/test_affinity.py | lectura de formato viejo (cierre del frente A, lote 1): claves viejas de `veredicto.json` congelado que el test lee en crudo para comprobar que siguen viejas y se normalizan (cierre del frente A, lote 4) |
| huella | tests/test_affinity.py | lectura de formato viejo (cierre del frente A, lote 1): claves viejas de `veredicto.json` congelado que el test lee en crudo para comprobar que siguen viejas y se normalizan (cierre del frente A, lote 4) |
| huella_rol | tests/test_affinity.py | lectura de formato viejo (cierre del frente A, lote 1): claves viejas de `veredicto.json` congelado que el test lee en crudo para comprobar que siguen viejas y se normalizan (cierre del frente A, lote 4) |
| congelado | tests/test_benchmark.py | lectura de formato viejo (cierre del frente A, lote 3): valores viejos de `provenance` del corpus congelado, escritos a mano para comprobar que se leen como `frozen` y `reconstructed` (cierre del frente A, lote 4) |
| congelado | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 3): valores viejos de `provenance` del corpus congelado, escritos a mano para comprobar que se leen como `frozen` y `reconstructed` (cierre del frente A, lote 4) |
| reconstruido | tests/test_benchmark.py | lectura de formato viejo (cierre del frente A, lote 3): valores viejos de `provenance` del corpus congelado, escritos a mano para comprobar que se leen como `frozen` y `reconstructed` (cierre del frente A, lote 4) |
| reconstruido | tests/test_corpus.py | lectura de formato viejo (cierre del frente A, lote 3): valores viejos de `provenance` del corpus congelado, escritos a mano para comprobar que se leen como `frozen` y `reconstructed` (cierre del frente A, lote 4) |

## Envoltorio de REQ-046

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| medir_enfriamiento | scripts/medir_enfriamiento.py | envoltorio de REQ-046: nombre del script y opciones `--desde`/`--hasta`/`--excluir` del comando de P-4; se retira tras la medición de los 90 días (~2026-12-14, backlog 1.6) (ola A10a-3) |
| medir_enfriamiento | tests/test_measure_cooldown.py | envoltorio de REQ-046: los dos tests que cargan el envoltorio; se retiran con él (ola A10a-3) |
| medir_enfriamiento.py | tests/test_measure_cooldown.py | envoltorio de REQ-046: ruta del envoltorio en esos dos tests (ola A10a-3) |

## Dato de un tercero

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| de-DE | src/local_delegate/web/metrics.py | dato de un tercero: etiqueta de idioma BCP 47 que se pasa a `toLocaleString` y a Chart.js; `de` es alemán (cierre del frente A, lote 4) |

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
| test_the_calibrated_quota_appears_as_a_meter | tests/test_dashboard_ui.py | «meter» = medidor (inglés), mismo caso que `meterHTML` (cierre del frente A, lote 4) |
| nobody-blocked-me.md | tests/test_correlation.py | «me» es el pronombre inglés; el léxico lo tiene como el pronombre español (cierre del frente A, lote 4) |

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
| resultados-sin-idioma | tests/test_analyze_benchmark.py | dato congelado de corpus o caso: directorio de resultados congelado en `benchmarks/afinidad-2026-10/`; el test lee sus filas del techo con el `via` viejo (cierre del frente A, lote 5) |
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
| clave-falsa | tests/test_residency.py | dato congelado de corpus o caso: marcador con que las copias congeladas de configs reales (`tests/fixtures/residency/*.yaml`) sustituyen las claves; el test comprueba la sustitución y no se reescriben las copias (cierre del frente A, lote 2) |
| clave-falsa-1 | tests/test_residency.py | dato congelado de corpus o caso: la clave sustituida que llevan esas copias congeladas (cierre del frente A, lote 2) |
| estado.json | tests/test_corpus.py | dato congelado de corpus o caso: identificador sacado del diff de un commit real del historial (`commit-diff-19k`), contenido del caso (ola A10b-6) |
| resumen-estructurado | tests/test_structured_summary.py | dato congelado de corpus o caso: directorio del corpus congelado `benchmarks/resumen-estructurado/` y clave de su `MANIFEST.json`, que no se reescriben (cierre del frente A, lote 4) |
| ficheros | tests/test_structured_summary.py | dato congelado de corpus o caso: directorio del corpus congelado `benchmarks/resumen-estructurado/` y clave de su `MANIFEST.json`, que no se reescriben (cierre del frente A, lote 4) |

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

## Texto de salida que traduce el frente B

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| montado | src/local_delegate/web/metrics.py | texto de salida que traduce el frente B (B4): rótulo del JS del panel (cierre del frente A, lote 4) |
| cargando | src/local_delegate/web/metrics.py | texto de salida que traduce el frente B (B4): rótulo del JS del panel (cierre del frente A, lote 4) |
| descargando | src/local_delegate/web/metrics.py | texto de salida que traduce el frente B (B4): rótulo del JS del panel (cierre del frente A, lote 4) |
| procesando | src/local_delegate/web/metrics.py | texto de salida que traduce el frente B (B4): rótulo del JS del panel (cierre del frente A, lote 4) |
| remoto | src/local_delegate/web/metrics.py | texto de salida que traduce el frente B (B4): rótulo del JS del panel (cierre del frente A, lote 4) |
| Remoto | src/local_delegate/web/metrics.py | texto de salida que traduce el frente B (B4): rótulo del JS del panel (cierre del frente A, lote 4) |
| llamada | src/local_delegate/web/metrics.py | texto de salida que traduce el frente B (B4): rótulo del JS del panel (cierre del frente A, lote 4) |
| fallo | src/local_delegate/web/metrics.py | texto de salida que traduce el frente B (B4): rótulo del JS del panel (cierre del frente A, lote 4) |
| pruebas | tests/test_metrics.py | texto de salida que traduce el frente B (B4; B2 para `local_status`): motivo de `excluded_by_reason` («pruebas», hermano de «no es Claude») que muestran `/api/stats` y el panel; el test comprueba el texto de hoy (cierre del frente A, lote 4) |
| pruebas | tests/test_valuation.py | texto de salida que traduce el frente B (B4; B2 para `local_status`): motivo de `excluded_by_reason` («pruebas», hermano de «no es Claude») que muestran `/api/stats` y el panel; el test comprueba el texto de hoy (cierre del frente A, lote 4) |

## Catálogo de textos (frente B)

Valores que el detector toma por nombres y que no lo son: el texto de salida del catálogo español
y los códigos de idioma con los que se prueba la regla del idioma. Nacen en la ola B0a.

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| * | src/local_delegate/resources/i18n/es/*.json | texto de salida del catálogo español (REQ-030): el detector toma por término de máquina los valores de una sola palabra («preferencia», «sistema»), que son rótulos para personas con su par en `en/` (ola B0a) |
| es[-_]* | tests/conftest.py | código de idioma (`es-ES`, BCP 47) del `locale` del navegador de los tests del panel (REQ-043), no un nombre en español (ola B0a) |
| es[-_]* | tests/test_language.py | códigos de idioma (`es-ES`, `es_ES`, `es_ES.UTF-8`) que son la entrada de los casos de la regla del idioma (REQ-018), no nombres en español (ola B0a) |

## Pendiente

| Nombre | Fichero | Motivo |
| --- | --- | --- |
| respaldo | src/local_delegate/server.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` que pasa a `fallback` (cierre del frente A, lote 4) |
| respondio | src/local_delegate/server.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` que pasa a `fallback.answered_by` (cierre del frente A, lote 4) |
| en_lugar_de | src/local_delegate/server.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` que pasa a `fallback.instead_of` (cierre del frente A, lote 4) |
| motivo | src/local_delegate/server.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` que pasa a `fallback.reason` (cierre del frente A, lote 4) |
| clase | src/local_delegate/server.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` que pasa a `fallback.class` (cierre del frente A, lote 4) |
| truncado | src/local_delegate/server.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` que pasa a `truncated` (cierre del frente A, lote 4) |
| aviso | src/local_delegate/server.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` que pasa a `warning` (cierre del frente A, lote 4) |
| leido_server_side | src/local_delegate/server.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` que pasa a `read_server_side` (cierre del frente A, lote 4) |
| tokens_aprox | src/local_delegate/server.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` que pasa a `read_server_side.approx_tokens` (cierre del frente A, lote 4) |
| crudo | src/local_delegate/server.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` que pasa a `raw` (cierre del frente A, lote 4) |
| crudo | tests/test_core.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate`; el test comprueba la salida de hoy (cierre del frente A, lote 4) |
| truncado | tests/test_core.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate`; el test comprueba la salida de hoy (cierre del frente A, lote 4) |
| aviso | tests/test_core.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate`; el test comprueba la salida de hoy (cierre del frente A, lote 4) |
| leido_server_side | tests/test_core.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate`; el test comprueba la salida de hoy (cierre del frente A, lote 4) |
| respaldo | tests/test_fallback.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` (`fallback.*`); el test comprueba la salida de hoy (cierre del frente A, lote 4) |
| respondio | tests/test_fallback.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` (`fallback.*`); el test comprueba la salida de hoy (cierre del frente A, lote 4) |
| en_lugar_de | tests/test_fallback.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` (`fallback.*`); el test comprueba la salida de hoy (cierre del frente A, lote 4) |
| motivo | tests/test_fallback.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate` (`fallback.*`); el test comprueba la salida de hoy (cierre del frente A, lote 4) |
| tokens_aprox | tests/test_density.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate`; el test comprueba la salida de hoy (cierre del frente A, lote 4) |
| leido_server_side | tests/test_density.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate`; el test comprueba la salida de hoy (cierre del frente A, lote 4) |
| tokens_aprox | tests/test_dashboard_cost.py | pendiente (REQ-010, sale en B2): subclave de `_local_delegate`; el test lee el bloque de `local_extract` para comprobar el texto (cierre del frente A, lote 4) |
