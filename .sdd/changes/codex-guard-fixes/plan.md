# Implementation plan: Codex: guard de escritura y lecturas, huecos de la revisión (#706, #707)

## Approach

Todo en `codex_reads.py` salvo REQ-004, que vive en el clasificador compartido (`read_classifier`)
porque el mismo `| Select-Object -Skip` se cuenta mal también para Claude Code y la condición tiene
una sola implementación. Tests primero (rojos sin el arreglo), luego el arreglo mínimo.

- REQ-001: `([^\n]*)$` en lugar de `(.+?)\s*$`; el `.strip()` ya quita espacios y `\r`; se descartan
  las rutas vacías.
- REQ-002: `decide` saca las lecturas literales de TODO el comando (`literal_reads`, de
  `read_classifier.accesses` + `resolve`, solo shell) antes de la salida por `kind != read` o
  `read_switch != on`, y las anota (`note_real_read`) antes de salir.
- REQ-003 y REQ-005: `read_parts` exige un fichero operando por parte (`_file_operands`) y solo
  filtros de franja en la tubería, y devuelve cuántas partes hay; se deniega solo si cada parte es
  una lectura del mismo fichero. `_Call.note_real_read` registra todas las lecturas del comando; la
  cobertura usa todos los tramos del fichero y la cabecera su envolvente (`_outer_span`).
- REQ-006: `daemon_summarize` corre la llamada en un hilo `daemon` y espera con `join(timeout)`.
- REQ-008: `_record` barre `codex-read/*.jsonl` de más de 30 días cuando crea el fichero de la sesión.
- REQ-007: test y párrafo en la wiki.

## Ordered tasks

- [x] T1 — Tests rojos de REQ-001..REQ-009 (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-009)
  - Files or modules: tests/test_codex_reads.py, tests/test_read_classifier.py
  - Verification: corren rojos sobre main (salvo los de REQ-007 y REQ-009, que fijan lo que ya va bien)
  - Depends on: none
- [x] T2 — Expresión lineal de rutas de parche (REQ-001)
  - Files or modules: src/local_delegate/codex_reads.py
  - Verification: test de CPU < 1 s con 40 000 espacios
  - Depends on: T1
- [x] T3 — Lectura literal con el interruptor apagado levanta el guard (REQ-002)
  - Files or modules: src/local_delegate/codex_reads.py
  - Verification: tests de interruptor apagado y backend caído
  - Depends on: T1
- [x] T4 — Denegación solo de lecturas puras y todos los tramos de un comando (REQ-003, REQ-005)
  - Files or modules: src/local_delegate/codex_reads.py
  - Verification: tests de tubería, varios operandos y tramos compuestos
  - Depends on: T1, T3 (los dos tocan `decide` y `_Call`)
- [x] T5 — `Select-Object -Skip` en el clasificador compartido (REQ-004)
  - Files or modules: src/local_delegate/resources/hooks/read_classifier.py
  - Verification: tests del clasificador y de cobertura en Codex
  - Depends on: T1
- [x] T6 — Plazo total del resumen y limpieza del estado (REQ-006, REQ-008)
  - Files or modules: src/local_delegate/codex_reads.py
  - Verification: test con daemon lento por pasos y con ficheros viejos
  - Depends on: T1
- [x] T7 — Wiki (tabla del guard de Codex: compuesto, tubería, varios ficheros, interruptor apagado y lectura MCP), CHANGELOG y nota en el review del SDD anterior (REQ-002, REQ-003, REQ-005, REQ-007, REQ-008, REQ-009)
  - Files or modules: docs/wiki/Integration-install.md, CHANGELOG.md, .sdd/changes/codex-read-summary-write-guard/review.md
  - Verification: review del diff; `sdd check`
  - Depends on: T2, T3, T4, T5, T6

- [x] T8 — Hallazgos de la revisión de seguridad: cabecera con espacios, lectura a fichero (`to_file`) y troceado lineal con `\"` (REQ-010)
  - Files or modules: src/local_delegate/codex_reads.py, src/local_delegate/resources/hooks/read_classifier.py
  - Verification: tests rojos sobre el código anterior (6) y verdes ahora
  - Depends on: T7

## Test strategy

- Unit: `tests/test_codex_reads.py` y `tests/test_read_classifier.py` con datos que distinguen
  (ficheros de 400-800 líneas, bordes del 80 %), control positivo en cada test nuevo.
- Integration: el proceso real del hook (`_hook`) ya cubierto; la suite completa con `pytest -n 2`
  bajo `pesado.sh`.
- End-to-end or manual: la prueba con Codex real sigue pendiente del SDD anterior.
- Security and secret scanning: revisión `personal-security-reviewer` del diff; skill
  `personal-security-check` antes del commit.

## Migration and compatibility

- El estado en disco no cambia de forma; los ficheros viejos se borran a los 30 días.
- El cambio de `Select-Object -Skip` afecta también a Claude Code (mod y hook de lectura): cuenta
  mejor una franja que antes se contaba desde la línea 1.
- Un test existente (antes `test_backend_down_lets_it_through_but_keeps_the_guard`, ahora
  `test_backend_down_lets_it_through_and_the_literal_read_lifts_the_guard`) fijaba el fallo de #707 y
  se invierte de forma explícita; `test_a_compound_command_is_never_denied_for_a_read` pasa a
  `..._with_other_commands_...`, porque un compuesto de solo lecturas del mismo fichero sí se deniega.
- La limpieza solo borra ficheros regulares `*.jsonl` de `codex-read/`, sin seguir enlaces y nunca
  el de la sesión actual. Vuelta atrás: revertir el PR; el formato del estado no cambia.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
