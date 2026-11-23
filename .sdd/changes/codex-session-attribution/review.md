# Result review: Atribución de cada delegación de Codex a su sesión (#669, segunda parte)

## Review level

- Level: deep
- Judges: result-reviewer-a, result-reviewer-b
- Security reviewer: yes
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | la clave `:pre_tool_use:1:0` sale ahora de un fichero fusionado con un grupo del usuario y de `inspect` (A-H5) |
| REQ-002 | yes | yes | controles sin `^` y modo exacto |
| REQ-003 | yes | yes | `agent_id` y `agent_type` con forma acotada (A-H6, seguridad) |
| REQ-004 | yes | yes | caso Codex con solo `claudecode/toolUseId` añadido (A-H1) |
| REQ-005 | yes | yes | casos «nota de otro id» y «`codex-<id>.json` sin `client: codex`» añadidos (A-H2, B3) |
| REQ-006 | yes | yes | control `claude-code` en cada caso |
| REQ-007 | yes | yes | `excluded_by_reason == {"not_claude": 1}` |
| REQ-008 | yes | yes | código y `/api/stats` probados; capturas claro/oscuro del 2026-11-23 (`docs/assets/dashboard.png` y `dashboard-light.png`, 0.53.0, contra el árbol con `scripts/dev/capture_dashboard.py`): la tarjeta «Quién delegó» enseña la columna «Codex» con 31 en la fila `Codex` y 0 en las demás |
| REQ-009 | yes | yes | `?session=` de Codex |
| REQ-010 | yes | yes | `codex` en `delegations_by_caller` |
| REQ-011 | yes | yes | `doctor` distingue el hook que falta (B1) y lo prueba el paso de dos a tres (B2); docstrings y lista de `caller_src` al día (B5, B6) |
| REQ-012 | yes | no | prueba con Codex real descrita en `handoff.md`; la hace la persona usuaria |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Falta el caso Codex con `claudecode/toolUseId` y sin `callId` | H1 | — | suspected | test añadido |
| F2 | Falta el caso «nota de otro id» | H2 | B3 (variante: `client`) | confirmed | dos casos añadidos |
| F3 | Fila de Codex sin nota recibe el respaldo de modelo de Claude en la fusión | H3 | — | suspected | aceptado: solo sirve a la densidad de filas ya excluidas del coste; el recibo en curso queda como antes a propósito (un fix no cambia otra cosa); si molesta en el panel, siguiente PR |
| F4 | Capturas claro/oscuro de REQ-008 pendientes | H4 | B4 | confirmed | hechas el 2026-11-23 (`docs/assets/dashboard.png`, `dashboard-light.png`; manifiestos con versión 0.53.0); la columna «Codex» se ve en los dos temas |
| F5 | `hook_key` del test no salía de un fichero fusionado | H5 | — | suspected | test reescrito con `merge` + `inspect` + `config.toml` |
| F6 | `agent_id`/`agent_type` sin forma ni tope | H6 | — | confirmed | `_shaped` con patrones acotados; test con control |
| F7 | `doctor` decía «no son de esta versión… aprobar otra vez» para el hook que falta | — | B1 | suspected | texto propio `doctor.probe.codex_hooks.missing` (es/en) |
| F8 | Sin test del paso de dos hooks a tres | — | B2 | suspected | `test_from_the_two_hooks_of_the_core_to_three` |
| F9 | Docstrings con «two hooks» | — | B5 | suspected | corregidos |
| F10 | La lista general de `caller_src` no nombraba `codex-hook` | — | B6 | suspected | wiki al día |
| S1 | Un cliente con token puede llamarse `codex-mcp-client` y mandar cualquier `callId`/`sessionId` | seguridad | — | suspected | solo cambia estadísticas de filas ya fuera del coste; igual que el cliente se declara hoy |
| S2 | En Linux con `/tmp` compartido, otro usuario puede crear antes el directorio de notas | seguridad | — | suspected | ya existía con las notas de Claude Code; fuera de alcance |

## Required follow-up

- Capturas del panel en claro y oscuro (F4): hechas el 2026-11-23.
- Prueba con Codex real (REQ-012), pasos en `handoff.md` y en `.sdd/changes/codex-pasos-para-yohan.md`;
  hasta entonces `conformance` no se aprueba. Los hooks ya están instalados en la PC (doctor:
  configurados 4 de 4, aprobados 0 de 4).
