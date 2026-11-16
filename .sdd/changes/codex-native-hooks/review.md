# Result review: Entrega Codex nativa: hooks de usuario, instalador y diagnóstico (#669, núcleo; la atribución por sesión va aparte)

## Review level

- Level: deep
- Judges: result-reviewer-a, result-reviewer-b
- Security reviewer: yes
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | reconocimiento anclado al intérprete; `command_windows` también excluye |
| REQ-002 | yes | yes | esquemas oficiales con `jsonschema`; control con los textos de Claude |
| REQ-003 | yes | yes | el test por `cmd.exe /C` falla en vez de saltarse con `CI` definido |
| REQ-004 | yes | yes | temporal propio por proceso en la marca de despacho |
| REQ-005 | yes | yes | BOM o clave rechazada: lo dice y no cuenta como fallo |
| REQ-006 | yes | yes | `update` sale con 0 ante un fichero que Codex rechaza |
| REQ-007 | yes | yes | `uninstall` quita los nuestros también de un fichero con BOM |
| REQ-008 | yes | yes | textos comparados enteros; `warn` por `timeout` distinto |
| REQ-009 | yes | yes | frases corregidas (`config.toml`, texto del aviso, `-I -m`) |
| REQ-010 | yes | yes | script en vivo con todas sus comprobaciones como `expect` |
| REQ-011 | yes | no | la aprobación en `/hooks` la hace la persona; pasos en `handoff.md` y la wiki |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| R1 | Un `hooks.json` que Codex rechaza hacía fallar `update` y saltar el paso del daemon | bloqueante | no visto | confirmed | `CodexHooksRefused`: la acción lo dice y no falla; test de `update` con BOM |
| R2 | `command_windows` no excluía el grupo | sí | no visto | confirmed | `WINDOWS_KEYS`; caso en el test |
| R3 | Asserts del texto de `doctor` que no discriminan | sí | sí | confirmed | comparación con el texto entero |
| R4 | Test por `cmd.exe /C` saltado | sí | sí | confirmed | falla con `CI`; se mira el run de Windows del PR |
| R5 | Script en vivo sin comprobar avisos, clave ajena, `untrusted` y aviso de BOM | sí | sí | confirmed | añadidos como `expect`; 0 fallos |
| R6 | `uninstall` rechazaba un fichero con BOM | sí | no visto | confirmed | ya no lo rechaza; test |
| R7 | `.bak` con solo lo nuestro tras una reparación | sí | no visto | suspected | riesgo residual aceptado: se queda `{"hooks": {}}` y el `.bak` |
| R8 | Temporal de la marca con nombre fijo | sí | no visto | confirmed | nombre con pid y sufijo aleatorio |
| R9 | `merge` compara el intérprete por texto y `doctor` con `same_path` | sí | no visto | suspected | riesgo residual: solo en un `install` manual; el mensaje pide aprobar otra vez |
| R10 | Wiki menos estricta que el código | sí | no visto | confirmed | corregida |
| R11 | `enabled = false` en `[hooks.state]` no se mira | sí | no visto | suspected | al siguiente PR |
| R12 | La rama «difiere de `entries()`» sin test | no visto | sí | confirmed | test con `timeout` distinto e intérprete existente |
| R13 | Pasos de la prueba de confianza incompletos | no visto | sí | confirmed | instalar la rama, subagente, «0 de 2» es fallo, vuelta atrás |
| R14 | «`uninstall` nunca toca `config.toml`» | no visto | sí | confirmed | «quitar los hooks no toca tus aprobaciones» |
| R15 | Carpeta existente sin `.exe` | no visto | sí | confirmed | caso añadido |
| R16 | Ruta con apóstrofo en POSIX | no visto | sí | confirmed | reconocimiento anclado; `install` no escribe una ruta que no sabe releer |
| R17 | Wiki promete nombrar la tool | no visto | sí | confirmed | frase ajustada |
| R18 | Suite completa no corrida sobre el árbol final | no visto | sí | confirmed | corrida; ver `verification.md` |

## Required follow-up

- Prueba de confianza de la persona (REQ-011) y el siguiente PR de #669 (atribución por sesión).
