# Result review: La espera ciega sin turno cuenta en la explicación del plazo agotado (#575 + #579)

## Review level

- Level: standard
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: no aplica (sin entrada externa nueva ni datos en el log)
- Verdict: conforms-with-notes (los dos jueces)

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | fases internas `turn_unusable` y `blind` en `QUEUE_PHASES` |
| REQ-002 | sí | sí | `log_fields` sigue filtrando por `PHASES`; test con conjunto literal |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | `verification.md` sin rellenar y sin fila de REQ-002 | sí | sí | confirmed | rellenado |
| F2 | Margen justo: la espera de la segunda se contaba desde el arranque, no desde que hace cola | sí | sí | confirmed | el primer envío espera (con tope) a que la otra esté en cola antes de dormir 1,6 s |
| F3 | El assert del log comparaba con `concurrency.PHASES`: un mutante que publique `blind` pasaba | no | sí | suspected | conjunto literal; mutante comprobado |
| F4 | La nota puede superar `turn_wait_ms` con un daemon lento en fallar; el comentario del test lo daba por general | sí | sí | confirmed | comentario corregido, CHANGELOG matizado y tests unitarios de cada fase sola |
| F5 | Sin caso de fase interna bajo 1 s | no | sí | suspected | test parametrizado añadido |
| F6 | Spec decía 1,3 s y el test 1,6 s; docstring de `_go_blind` mal partido | sí | sí | confirmed | alineados |
| F7 | La nota suma esperas de trozos anteriores | sí | no | suspected | aceptado: ya era así en #575 |

## Required follow-up

- Ninguno.
