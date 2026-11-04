# Specification: Hooks de la entrega por settings leen y escriben UTF-8 en Windows

## Summary

Con la entrega por `settings.json` (`python "<script>"`), los hooks de lectura, shell, prompt y
subagente leen su entrada y escriben su salida en UTF-8 aunque el intérprete arranque con la página
de códigos del sistema (cp1252 en Windows). El hook de lectura deja además una línea de telemetría
con motivo cuando no puede medir el fichero, en vez de callarse.

## Requirements

- **REQ-001** — Con stdin en cp1252, una lectura de un fichero de prosa grande cuya ruta tiene `ñ`
  o tildes se mide (aparece su línea de telemetría con `size_kb` y la huella de la ruta real).
  - Request: "una ruta con ñ/tildes llega como Ã±… y el hook de lectura sale sin bloquear ni telemetría"
  - Verify: test tests/test_hook_stdin_utf8.py::test_read_hook_finds_a_file_with_a_non_ascii_path
- **REQ-002** — Con stdin en cp1252, el prompt «Resume el diseño del panel» no recibe aviso de
  delegar (`_HOST_ONLY` casa con `diseñ`).
  - Request: "en el hook de prompt «diseño» no casa con _HOST_ONLY"
  - Verify: test tests/test_hook_stdin_utf8.py::test_prompt_hook_reads_accented_words_of_the_host_only_rule
- **REQ-003** — Una entrada con un carácter cuyo UTF-8 no existe en cp1252 (`Á` = C3 81) se lee
  entera: el hook decide y registra su línea.
  - Request: "un byte UTF-8 sin carácter en cp1252 (Á) rompe json.load"
  - Verify: test tests/test_hook_stdin_utf8.py::test_prompt_hook_survives_a_letter_outside_cp1252
- **REQ-004** — El arreglo vive en los scripts (no en el comando registrado): una instalación
  existente queda arreglada con `update`, que recopia los scripts, sin tocar `settings.json`.
  - Request: "que los scripts lean stdin en UTF-8 por sí mismos y funcione con las instalaciones existentes tras update"
  - Verify: review diff de install.py vacío; cmd prueba instalada (scratchpad installed_probe.py)
- **REQ-005** — Cuando el hook de lectura no puede medir el fichero (no existe o no se puede leer)
  registra `reason: "no_file"` con `suggested: false`, como ya hace el de shell.
  - Request: "que la salida temprana del hook de lectura deje una línea de telemetría con motivo (no_file)"
  - Verify: test tests/test_hook_stdin_utf8.py::test_read_hook_records_why_it_stops_when_the_file_is_missing
- **REQ-006** — La salida (stdout) del hook con tildes o caracteres fuera de cp1252 llega en UTF-8
  válido, con la ruta tal como la escribió el usuario.
  - Request: "comprobar que stdout con tildes llega bien"
  - Verify: test tests/test_hook_stdin_utf8.py::test_utf8_stdio_switches_a_cp1252_pipe_to_utf8
- **REQ-007** — Lanzados exactamente con el comando que deja `install` en un `settings.json` de un
  HOME temporal, con stdin UTF-8 en bytes, los tres casos fallan antes del arreglo y no después.
  - Request: "prueba instalada con HOME temporal"
  - Verify: cmd scratchpad/utf8hooks/installed_probe.py (before.txt / after.txt)
- **REQ-008** — El servidor, que importa `hook_common`, no ve cambiada la codificación de su stdio:
  la reconfiguración solo ocurre dentro del `main()` de cada hook.
  - Request: derived: el transporte MCP stdio del servidor no debe alterarse
  - Verify: review `utf8_stdio` no se llama al importar; test suite completa en verde
- **REQ-009** — `scripts/measure_adoption.py` no cuenta como lectura un evento con
  `reason: "no_file"` (de lectura ni de shell): no entra en `reads`, `by_side`, `by_reason` ni
  `by_path`, y se muestra aparte en `not_reads`. El resto de cifras no cambia.
  - Request: derived: revisión del PR #560 — la línea `no_file` nueva inflaría el denominador del tramo «después» en la medición de adopción del 2026-11-05
  - Verify: test tests/test_measure_adoption.py::test_a_file_the_hook_could_not_size_is_not_a_read
- **REQ-010** — Quitar `utf8_stdio()` solo del hook de shell o solo del de subagente hace fallar un test.
  - Request: derived: revisión del PR #560 — esos dos hooks no tenían test que discriminara
  - Verify: test tests/test_hook_stdin_utf8.py::test_shell_hook_finds_a_file_with_a_non_ascii_path y ::test_subagent_hook_writes_its_notice_in_utf8

## Acceptance scenarios

### Scenario: lectura de prosa en una carpeta con eñe

- **Given** el hook de lectura registrado por settings y stdin en cp1252
- **When** Claude Code manda en UTF-8 un `Read` de `ñandú/informe.md` (37 KB de prosa)
- **Then** el hook mide el fichero, decide (bloquea o sugiere) y deja su línea de telemetría

### Scenario: fichero que no existe

- **Given** el mismo hook
- **When** la ruta no existe
- **Then** no hay salida y la telemetría registra `reason: "no_file"`

## Edge cases and failure behavior

- Un stream sin `reconfigure` (tests que ponen un `StringIO`) se deja como está.
- Bytes que no son UTF-8 válido se sustituyen (`errors="replace"`), como ya hacía `record_call`.
- Si ya está en UTF-8 no se reconfigura.

## Non-functional requirements

- Sin dependencias nuevas; solo stdlib.
- La telemetría sigue sin rutas: solo la huella (`path_sha`).

## Non-goals

- Cambiar el comando registrado a `python -X utf8` (y la migración y el `doctor` que exigiría).
- La entrega por plugin (`hook_entry._utf8_streams`), que ya estaba bien.
- `record`/`_log_failure` de `hook_common.py` (otro cambio en paralelo).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
