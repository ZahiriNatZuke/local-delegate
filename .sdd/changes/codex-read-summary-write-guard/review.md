# Result review: Codex: resumen de lecturas grandes y guard de escritura (#670)

## Review level

- Level: deep
- Judges: result-reviewer-a, result-reviewer-b
- Security reviewer: yes
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | matcher probado con nombres que casan y no casan; que Rust lo compile al despachar, solo con Codex real |
| REQ-002 | partial | partial | el código deniega también con tubería y con varios operandos (`cat a.md b.py`), contra la spec (F2); la forma del `command` en Windows, pendiente de Codex real |
| REQ-003 | yes | yes | fallo en abierto de la lectura con 9 resúmenes inválidos; ver F1 para el guard |
| REQ-004 | yes | yes | — |
| REQ-005 | yes | partial | borde 79/80 % discrimina; `Select-Object -Skip` y varios rangos en un comando compuesto lo esquivan (F3, F4) |
| REQ-006 | yes | partial | alcance por agente y otro proceso probados; la lectura literal no levanta el guard con el interruptor apagado o el backend caído (F1) |
| REQ-007 | yes | yes | nota sin bloqueo en lecturas MCP; no levantan el guard (F7, sin documentar) |
| REQ-008 | yes | partial | el plazo de 150 s es por operación de socket, no total (F5); igual falla en abierto |
| REQ-009 | yes | yes | sin contenido en estado ni log; revisor de seguridad: token solo en cabecera, sin proxy |
| REQ-010 | yes | yes | `hooks/list` sin avisos; turno real pendiente |
| REQ-011 | yes | partial | wiki y CHANGELOG al día; la prueba con centinela está escrita y falta hacerla (`.sdd/changes/codex-pasos-para-yohan.md`) |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Con el interruptor de lectura apagado o el backend caído, `decide` sale antes de `note_real_read` (`codex_reads.py:548-549`): la lectura literal pasa pero no levanta el guard y `apply_patch` se rechaza en bucle | A1 | — | suspected | confirmado leyendo el código; issue #707; se arregla antes del cierre |
| F2 | Denegación con tubería y con varios operandos; `cat f.md` encadenado a otro `cat` por tubería pasa como `partial` con el fichero entero | A3 | B1 | confirmed | issue #707 (alinear código y spec) |
| F3 | `Get-Content f` con tubería a `Select-Object -Skip N -First M` se cuenta como 1..M; `verification.md` dice lo contrario | — | B2 | suspected | issue #707 |
| F4 | Varios rangos en un comando compuesto suman un solo tramo y esquivan el 80 % | — | B3 | suspected | issue #707 |
| F5 | El plazo de 150 s es por operación de socket en cada petición, no total | A2 | B4 | confirmed | issue #707; sigue fallando en abierto |
| F6 | `_PATCH_PATH` (`codex_reads.py:86`) tarda un tiempo cuadrático con muchos espacios en la cabecera (medido: 40 000 espacios, 4,9 s) | — (seguridad S1) | — | confirmed | issue #706; baja, el hook falla en abierto |
| F7 | Una lectura MCP literal nunca levanta el guard; no está en spec ni wiki | A4 | B6 | confirmed | issue #707 (documentar) |
| F8 | Un rango más allá del final levanta el guard sin leer nada útil | — | B5 | suspected | aceptado: cumple la spec («un tramo») |
| F9 | `codex-read/*.jsonl` no se limpia nunca | A5 | B9 | confirmed | issue #707 |
| F10 | Faltan tests: `Get-Content -TotalCount`, `Set-Content`/`Out-File`, `mv`, tubería, varios ficheros, varias líneas | — | B7 | suspected | issue #707 |
| F11 | Fixtures hechos a mano (forma del esquema 0.169.0, no capturas reales) | — | B8 | suspected | la prueba real guarda los payloads reales como fixtures |
| F12 | Comentario «new entries go at the END» y `codex-tool-guard` va antes de `codex-mcp-call` | A6 | — | suspected | aceptado: los dos salieron juntos en 0.53.0 |

Seguridad (revisor `personal-security-reviewer`): sin bloqueantes. Descartados con su
comprobación: path traversal por `session_id` (`fullmatch` acotado), ficheros secretos enviados al
modelo (`summarizable` + `protected` + `path_guard` del daemon), inyección por el motivo
(`json.dumps`, plantillas fijas), filtrado del token, y saltarse `/hooks` o escribir `trusted_hash`.
Único hallazgo: F6.

## Required follow-up

- Prueba con Codex real (centinela, `apply_patch` rechazado y levantado, daemon parado):
  `.sdd/changes/codex-pasos-para-yohan.md`. Hasta entonces `conformance` no se aprueba.
- F1 (bucle del guard) arreglado con test antes de cerrar; el resto, en #706 y #707.
- 2026-11-23: F1 a F7, F9 y F10 (#706 y #707) quedan arreglados con tests por el SDD
  `.sdd/changes/codex-guard-fixes/`, que también precisa REQ-002, REQ-005 y REQ-006 de esta spec.
  Este SDD sigue en `result-review`: su conformidad espera la prueba con Codex real.
- 2026-11-23 19:35 (hora de Uruguay): prueba con Codex real hecha (`verification.md`, «Prueba con
  Codex real»); el hueco de las escrituras de shell (#724) lo cierra el SDD
  `.sdd/changes/codex-guard-shell-writes/`. Conformidad aprobada.
