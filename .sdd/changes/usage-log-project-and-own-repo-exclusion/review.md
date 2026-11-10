# Result review: Log de uso con proyecto (hash y tipo) y mediciones que apartan el propio repo

## Review level

- Level: deep
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: yes — sin hallazgos explotables (recorrido con `session_id`, fuga de rutas o nombres, carrera de la sal, entorno de la petición, XSS del panel, DoS)
- Verdict: conforms-with-notes
- Resolution (2026-11-10): the only blocker, U1, was resolved by amending REQ-024 (measurement scripts out of scope, recorded in spec.md and verification.md); the verdict before that was does-not-conform.

Revisión del 2026-11-10 sobre el diff mezclado en `main` (`a19817e6`, PR #637, sin `.sdd/`), la
spec, el plan y `verification.md` con la prueba en vivo ya hecha. Compatibilidad comprobada por la
sesión que consolida: `git diff --diff-filter=MDR a19817e6^ a19817e6 -- tests` vacío; las firmas
nuevas (`transcripts.read(log_dir=)`, `entry_for(session_key=)`) son opcionales y por nombre; filas
y eventos sin los campos se leen como antes (REQ-022).

El código cumple 31 de los 32 requisitos. **REQ-024 no se cumple en los scripts de medición** (U1):
es el único bloqueante y no pide tocar el código de producción, pero sí una decisión antes de la
puerta `conformance`.

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | `project_identity` léxico; ver U8 |
| REQ-002 | yes | yes | tramos, normalización, tope de 64 KiB |
| REQ-003 | yes | yes | `os.link` atómico, reparación bajo cerrojo; permisos en Windows por la ACL heredada (U14) |
| REQ-004 | yes | yes | en `resolve_call`; mutante 14 equivalente (U8) |
| REQ-005 | yes | yes | solo hash y tipo; test de punta a punta |
| REQ-006 | yes | yes | `try` propio, sin disco |
| REQ-007 | yes | yes | `_with_project` pone el par junto; ver U4 |
| REQ-008 | yes | yes | `caller_column` con el mod primero |
| REQ-009 | yes | yes | pruebas primero, propio repo después |
| REQ-010 | yes | yes | `session=` no aparta, también en vivo |
| REQ-011 | yes | yes | el coste sigue el filtro |
| REQ-012 | yes | yes | ver U6 |
| REQ-013 | yes | yes | interruptor y `ld-self` |
| REQ-014 | yes | yes | las cuatro columnas suman `calls` |
| REQ-015 | yes | yes | capturas fuera del repo, miradas de nuevo al cierre (U7) |
| REQ-016 | yes | yes | raíz y sal del proceso, tope de 50 ms; ver U2 y U5 |
| REQ-017 | yes | yes | ver U3 y U12 |
| REQ-018 | yes | yes | la suma por hilo es `total_delegations` |
| REQ-019 | yes | yes | `excluded_self_sessions` |
| REQ-020 | yes | yes | `pct` solo del hilo principal |
| REQ-021 | yes | yes | la línea solo sale si no es cero |
| REQ-022 | yes | yes | CI del PR #637 en verde |
| REQ-023 | yes | yes | la nota no cambia de formato |
| REQ-024 | yes | yes | panel y `local_status` sí; scripts fuera por la enmienda de U1 |
| REQ-025 | yes | yes | los cuatro sitios; ver U11 |
| REQ-026 | yes | yes | 31/1/32 en vez de 1/1/2 por la ventana compartida (U9) |
| REQ-027 | yes | yes | criterios (a) a (d) |
| REQ-028 | yes | yes | 66 mutantes; solo sobrevive el 14, equivalente |
| REQ-029 | yes | yes | la wiki da las dos órdenes del corte de 90 días |
| REQ-030 | yes | yes | solo altas en `tests/` |
| REQ-031 | yes | yes | D14 |
| REQ-032 | yes | yes | `classify_text` sin tocar; mutante 50 |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| U1 | REQ-024: `scripts/measure_adoption.py` imprime líneas nuevas solo en español y fuera del catálogo, su ayuda nueva va solo en español y la de `measure_plugin_adoption.py` solo en inglés; el guardián no mira `scripts/` y `verification.md` decía `pass` | yes | no | suspected | **bloqueante, pendiente de decisión**. Comprobado por la sesión que consolida (`scripts/measure_adoption.py:375-404`; los textos de antes del cambio ya eran solo en español y sin catálogo). Dos salidas: catalogar las cadenas nuevas, o enmendar REQ-024 para dejar fuera los scripts de medición (no van en el paquete) y registrarlo como desviación. `verification.md` ya da `fail` |
| U2 | `_SESSION_UUID` con `$` acepta un salto de línea final (`"<uuid>\n"`); no hay recorrido, pero la spec dice que otra forma no forma ruta | no | yes | suspected | lo confirma también el revisor de seguridad; seguimiento: `fullmatch` o `\Z` y el caso en el test |
| U3 | `measure_adoption.py`: un bloqueo `other` o `unknown` cuya delegación quedó `self` deja de contar como aceptado (`accepted` 25 frente a 23 en las copias A y B) | no | yes | suspected | seguimiento: calcular los ids delegados antes del filtro del propio repo, o escribir la decisión en la wiki |
| U4 | `cost.merge_row` rellena hash y tipo por separado: una fila sellada solo con tipo puede tomar el hash del relleno | no | yes | suspected | seguimiento: copiar el hash solo si el tipo coincide o falta |
| U5 | La caché `_SESSION_TRANSCRIPTS` del daemon crece sin tope | no | yes | suspected | aceptado: cientos de entradas en la práctica; seguimiento opcional (LRU) |
| U6 | `/api/hooks` y `measure_adoption.py` dan cifras distintas del propio repo en eventos viejos (el panel no resuelve por sesión, como pide REQ-012) | no | yes | suspected | seguimiento: decirlo en la wiki junto a la tarjeta de hooks |
| U7 | Las capturas de REQ-015 solo están en el directorio temporal de la sesión | yes | yes | confirmed | resuelto: miradas de nuevo al cierre y anotado en `verification.md` |
| U8 | `project_directory` toma el primer directorio bajo la raíz, no `parent.name` como dice D1; por eso el mutante 14 es equivalente | yes | no | suspected | aceptado: desviación documentada en `verification.md` |
| U9 | REQ-026: se midió 31/1/32 en vez de 1/1/2 | yes | no | suspected | aceptado: ventana compartida con la prueba en vivo del otro cambio; se cumple lo que el criterio comprueba; anotado en «Deviations» |
| U10 | La lista de palabras del léxico decía 23 y el diff añade 29 | yes | no | suspected | resuelto en `verification.md` |
| U11 | `docs/wiki/Savings-and-metrics.md:128` no dice que el nombre va en minúsculas en el hash | yes | no | suspected | seguimiento: una palabra en la wiki |
| U12 | `excluded_self.hooks` cuenta todos los eventos y `unknown_project.hooks` solo las lecturas | yes | no | suspected | seguimiento: decirlo en la wiki; ya anotado en «Deviations» |
| U13 | Cinco tests usan `D--Projects-local-delegate`, copia del nombre real del checkout (sin usuario) | yes | no | suspected | aceptado: no lleva datos personales; opcional cambiarlo |
| U14 | No hay prueba de los permisos de `project-salt` en Windows | no | yes | suspected | aceptado: el revisor de seguridad lo cubre con la ACL heredada del perfil |

Notas del revisor de seguridad sin camino de ataque: la caché por `session_id` distingue mayúsculas
(entradas duplicadas en Windows, no explotable) y un `match` no hasheable en una fila haría un 500
en `/api/stats` (filas escritas por el propio servidor).

## Required follow-up

- **Antes de la puerta `conformance`**: decidir U1 (catalogar o enmendar REQ-024) y dejarlo escrito
  en la spec o en `verification.md`; con la enmienda, la fila de REQ-024 pasa a `pass` con la nota.
- Antes de cerrar T11: borrar las copias de la instantánea (`t1/`, `t11/`) del directorio temporal.
- Seguimiento sin bloqueo: U2, U3, U4, U6, U11 y U12.
