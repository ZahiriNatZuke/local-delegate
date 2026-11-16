# Result review: Doctor detecta el plugin de Claude importado en Codex: hooks.json con modules rechazado (#668)

## Review level

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: no — el cambio solo lee ficheros locales de Codex y no toca autenticación, secretos ni permisos; el juez B revisó la entrada no confiable (nombres de carpeta, JSON hostil) y la pista de comando
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | `type` no textual ahora es rechazo (A2, B1) |
| REQ-002 | sí | sí | evidencia de Codex real escrita en verification.md (A1) |
| REQ-003 | sí | sí | |
| REQ-004 | sí | sí | tabla sin `enabled` cuenta como habilitado, citado de loader.rs (A5) |
| REQ-005 | sí | sí | JSON hondo, no UTF-8 y carpetas ilegibles ya no tumban el check (B2, B4, B5) |
| REQ-006 | sí | sí | |
| REQ-007 | sí | sí | |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | verification.md seguía en plantilla; REQ-002 sin evidencia escrita | bloqueante | no bloqueante | confirmed | rellenado con la medición en Codex real y el hash de config.toml |
| F2 | `type` lista u objeto lanzaba TypeError y el check salía unknown | no bloqueante | no bloqueante | confirmed | se exige texto; test de rechazo; también el check sale warn |
| F3 | textos `dropped`, `disabled_incompatible` y `rejected` afirmaban causas que no siempre eran ciertas | no bloqueante | no visto | suspected | textos genéricos; la mención al mod de Claude solo cuando falla `modules`; test sin `modules` |
| F4 | ilegible daba unknown aunque el plugin no estuviera habilitado | no bloqueante | no bloqueante | confirmed | se mira primero si está habilitado; no UTF-8 es rechazo, como en Codex |
| F5 | sin entrada en config.toml tomado como no habilitado sin fuente; tabla sin `enabled` | no bloqueante | no visto | suspected | citado de loader.rs; una tabla sin `enabled` cuenta como habilitada, con test |
| F6 | RecursionError de JSON o TOML hondo no se atrapaba | no visto | no bloqueante | suspected | atrapado; test con 100 000 niveles |
| F7 | un error de permisos en una carpeta ocultaba todos los marketplaces | no visto | no bloqueante | suspected | lectura por carpeta; test con fichero donde va carpeta |
| F8 | nombre de marketplace sin filtrar en el comando sugerido | no visto | no bloqueante | suspected | sin pista si el id lleva caracteres fuera de letras, dígitos, punto, guion, guion bajo y arroba; test |
| F9 | ramas sin test y un test de config.toml roto que no discriminaba | no visto | no bloqueante | suspected | tests añadidos; el de config.toml habilita primero y comprueba el warn |
| F10 | el probe solo mira hooks/hooks.json y no un `hooks` del manifiesto | nota | no visto | suspected | aceptado: el plugin.json empaquetado no declara `hooks`; escrito |

## Required follow-up

- Ninguno obligatorio. La entrega Codex nativa es el issue #669.
