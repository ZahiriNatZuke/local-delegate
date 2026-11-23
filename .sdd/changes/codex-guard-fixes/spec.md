# Specification: Codex: guard de escritura y lecturas, huecos de la revisión (#706, #707)

## Summary

El hook `codex-tool-guard` (`src/local_delegate/codex_reads.py`) cierra los huecos que encontró la
revisión de resultado del SDD `codex-read-summary-write-guard` (F1 a F10 de su `review.md`): una
lectura literal levanta siempre el guard, la denegación y la cuenta de tramos siguen la spec, el
plazo del resumen es total, las rutas de un parche se sacan en tiempo lineal y el estado viejo se
borra. Esta spec precisa la redacción de REQ-002 y REQ-006 de aquel SDD donde se quedaba corta.

## Requirements

- **REQ-001** — Las rutas de un parche (`_PATCH_PATH`) se sacan en tiempo lineal: una cabecera
  `*** Update File: a` seguida de 40 000 espacios y una `b` se analiza en menos de 1 s de CPU
  (antes, unos 5 s), y la ruta sale sin los espacios del final ni el `\r` de un fin de línea CRLF.
  - Request: "#706: la expresión _PATCH_PATH tarda tiempo cuadrático con muchos espacios; hay que hacerla lineal"
  - Verify: test tests/test_codex_reads.py
- **REQ-002** — Con el interruptor de lectura distinto de `on` (apagado, inactivo o con el backend
  caído), y también cuando el mismo comando escribe otro fichero (la escritura gana como acceso
  principal), una lectura literal por shell de un fichero levanta el guard de ese fichero para su
  agente y deja su marca como con el interruptor encendido (REQ-003: entera, tramo o parcial; los
  tramos de un subagente levantan pero no suman); la lectura pasa sin resumen ni nota y
  `apply_patch` sobre el fichero pasa después.
  - Request: "con la lectura apagada o el backend caído, decide sale antes de note_real_read() y una lectura literal no levanta el guard, así que apply_patch se rechaza en bucle"
  - Verify: test tests/test_codex_reads.py
- **REQ-003** — Solo se deniega (se sustituye por el resumen) un comando cuyas partes, quitando
  `cd`/`Set-Location` delante, son todas lecturas de UN mismo fichero con UN fichero operando cada
  una (por familia, con `_operands` y `_VALUE_FLAGS`; el guion de `sed` no es un fichero), sin
  redirección, heredoc ni sustitución, y cuya única tubería posible es un filtro de franja (`head`,
  `Select-Object`) detrás de la lectura. Con varios operandos (`cat a.md b.py`) o con otra tubería
  (`cat f.md | cat`, `| grep`) la lectura pasa literal con la nota `codex.read.warn.large` y cuenta
  como lectura literal. Qué deja una lectura literal, por alcance del clasificador: entera marca el
  fichero como leído; un tramo suma sus líneas; parcial (`| cat`, `| grep`, `tail`) solo levanta el
  guard; una búsqueda o lo no clasificable (`grep x f`, `awk`) no deja nada. De `cat a.md b.md` el
  clasificador solo ve el primer fichero: el segundo no cuenta ni levanta su guard (límite aceptado).
  - Request: "además los huecos con tuberías"
  - Verify: test tests/test_codex_reads.py
- **REQ-004** — `Get-Content f | Select-Object -Skip N -First M` se cuenta como las líneas
  N+1..N+M, y `| Select-Object -Skip N` sin `-First` como N+1 hasta el final (en el clasificador
  compartido, `read_classifier.classify_shell`); con `-Last` o `-Index` sigue como lectura parcial.
  - Request: "Select-Object -Skip"
  - Verify: test tests/test_read_classifier.py
- **REQ-005** — Todos los tramos de un mismo fichero en un comando compuesto suman a la cobertura:
  `sed -n 1,300p f; sed -n 301,400p f` sobre un fichero de 500 líneas llega al 80 % y se resume (es
  solo lectura, REQ-003), y la cabecera nombra el tramo de la primera línea pedida a la última; en
  un comando compuesto con otras órdenes la lectura pasa con la nota y todos sus tramos quedan
  contados para la siguiente.
  - Request: "rangos en comando compuesto"
  - Verify: test tests/test_codex_reads.py
- **REQ-006** — El plazo del resumen (`SUMMARY_TIMEOUT_S`, 150 s) es total para toda la
  conversación con el daemon, no por operación de socket: un daemon que contesta cada petición a
  tiempo pero se pasa del plazo entre todas da `None` y la lectura pasa.
  - Request: "el plazo por operación de socket que lista el issue"
  - Verify: test tests/test_codex_reads.py
- **REQ-007** — Una lectura por una tool MCP ajena nunca levanta el guard ni suma tramos (el hook no
  ve qué parte del fichero entra): la wiki (`docs/wiki/Integration-install.md`, sección del guard de
  Codex) lo dice y un test lo fija.
  - Request: "derived: #707 punto 6, una lectura MCP literal no levanta nunca el guard; no lo dicen ni la spec ni la wiki"
  - Verify: test tests/test_codex_reads.py
- **REQ-008** — Los ficheros de estado `<datos>/codex-read/*.jsonl` sin cambios en 30 días se borran
  al abrir una sesión nueva (el primer evento de un fichero que aún no existe); los recientes, lo
  que no sea un fichero regular `*.jsonl` (enlaces incluidos) y el de la sesión actual se quedan, y
  un fallo al borrar no cambia la decisión del hook.
  - Request: "derived: #707 punto 7, `<datos>/codex-read/*.jsonl` no se limpia nunca"
  - Verify: test tests/test_codex_reads.py
- **REQ-009** — Tests de las vías que faltaban: `Get-Content -TotalCount` (tramo), `Set-Content` y
  `Out-File` (escritura rechazada con guard), `mv` con el fichero guardado como destino, tubería,
  varios ficheros y un comando de varias líneas.
  - Request: "derived: #707 punto 8, faltan tests de Get-Content -TotalCount, Set-Content/Out-File, mv, tubería, varios ficheros y comandos de varias líneas"
  - Verify: test tests/test_codex_reads.py

- **REQ-010** — Hallazgos de la revisión de seguridad de este cambio: una cabecera de parche con
  espacios o tabuladores delante sigue guardada; una lectura cuya salida acaba en un fichero
  (`cat f | head > out`, `| Out-File out`) no levanta el guard (marca `to_file` del clasificador,
  que Claude Code no usa); y `\"` fuera de comillas es parte de la palabra, así que 20 000 de ellas
  se trocean en menos de 1 s de CPU (antes, unos 30 s) y la escritura que las sigue se ve.
  - Request: "derived: revisión personal-security-reviewer del diff (P5 del encargo)"
  - Verify: test tests/test_codex_reads.py

## Acceptance scenarios

### Scenario: guard levantado con el interruptor apagado

- **Given** `notes.md` grande resumido (guard puesto) con el interruptor en `on`
- **When** el interruptor pasa a apagado y el agente lee `sed -n '1,40p' notes.md`
- **Then** la lectura pasa y un `apply_patch` sobre `notes.md` pasa

### Scenario: dos tramos en un comando

- **Given** `notes.md` de 500 líneas sin leer
- **When** el agente pide `sed -n 1,300p notes.md; sed -n 301,400p notes.md`
- **Then** se deniega con el resumen y la cabecera de rangos (80 %)

## Edge cases and failure behavior

- Todo fallo del resumen sigue abriendo la lectura (REQ-003 del SDD anterior).
- Si el hilo del resumen sigue vivo al vencer el plazo, se abandona (hilo `daemon`) y el hook sale.
- Un fallo al borrar un fichero viejo no afecta a la lectura ni al guard.
- Reanudar una sesión con más de 30 días sin uso empieza sin su guard (falla en abierto, como el
  resto del hook).
- Esta spec precisa REQ-002, REQ-005 y REQ-006 de `.sdd/changes/codex-read-summary-write-guard/`.

## Non-functional requirements

- El estado sigue sin contenido (solo rutas, tramos y marcas).
- Sin dependencias nuevas. Los tests de tiempo miden CPU (`time.process_time()`), no reloj, salvo el
  del plazo del daemon, que por naturaleza es de reloj y lleva holgura.

## Non-goals

- El origen de un `mv` (mover el fichero guardado a otro sitio) no se trata como escritura: queda
  como en el clasificador compartido, que solo da el destino.
- F8 (rango más allá del final), F11 (fixtures reales) y F12 (orden de entradas) quedan como los
  resolvió la revisión anterior.
- No se toca la instalación de hooks de Codex ni el daemon.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
