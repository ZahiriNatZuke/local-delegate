# Result review: Hooks y bloque gestionado ante subagentes con lista cerrada de tools (#664)

## Review level

- Level: standard
- Judges: result-reviewer-a, result-reviewer-b
- Security reviewer: no aplica (lectura local de ficheros pequeños con topes, sin red ni escritura)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | `closed_agent_without_local_tools` en `hook_common.py` |
| REQ-002 | sí | sí | formas de YAML dudosas devuelven duda |
| REQ-003 | sí | sí | también el delta propio, tras la revisión |
| REQ-004 | sí | sí | `subagent_start.py` |
| REQ-005 | sí | sí | test propio del párrafo, tras la revisión |
| REQ-006 | sí | sí | prueba instalada con HOME simulado |
| REQ-007 | sí | sí | CHANGELOG y wiki |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | verification.md y review.md en plantilla | A1 | B-1 | confirmed | rellenados |
| F2 | REQ-003 sin probar con agent_id (uso del principal sin transcript propio) | A5 | B-2 | confirmed | test_own_transcript_decides_and_main_does_not |
| F3 | un delta propio con las local_* no ganaba a la definicion | no | B-3 | suspected | aceptado: el delta propio cuenta como presentes |
| F4 | formas de YAML (lista partida, bloque de texto, comentarios) daban un cerrado falso | A2 | no | suspected | aceptado: esas formas son duda; 14 casos en test |
| F5 | BOM y lista sin sangria daban duda | A3 | B-7 | confirmed | BOM quitado; lista sin sangria leida |
| F6 | los tipos raros no probaban la regex del nombre | no | B-5 | suspected | test con definiciones llamadas asi |
| F7 | el fixture world no quitaba CLAUDE_PROJECT_DIR ni CLAUDE_CONFIG_DIR | A7 | B-6 | confirmed | quitadas |
| F8 | se leia cada definicion entera y sin orden por nombre | A8 | B-7 | confirmed | primero el fichero del nombre y solo 16 KB de cabecera |
| F9 | la wiki decia nombre de fichero y el codigo busca por name | no | B-7 | suspected | wiki corregida |
| F10 | test de REQ-005 no discriminaba | A6 | no | suspected | test nuevo del parrafo en los dos idiomas |
| F11 | orden de carpetas aproxima el de Claude Code | A4 | B-3 | confirmed | aceptado como riesgo residual en verification.md |
| F12 | controles positivos de shell y cwd | no | B-4 | suspected | no se cambia: discriminan por el reason mcp_absent |

## Required follow-up

- Seguimiento fuera de este cambio: el mod (`mod/read.js`) sigue resumiendo la lectura completa de
  prosa grande en un subagente y le añade la nota de localizar con `local_*`; su evento solo trae
  `agentId`. En subagente la lectura por rango ya pasa literal, así que no deja sin salida. Se
  propone como tarjeta aparte.
