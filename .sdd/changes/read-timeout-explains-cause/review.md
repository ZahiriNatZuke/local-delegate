# Result review: Un read_timeout dice si fue cola, carga o generación y en qué trozo (#572)

## Review level

- Level: standard
- Judges: result-reviewer-1, result-reviewer-2
- Security reviewer: no aplica (sin entrada externa nueva; solo textos y campos de log)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | trozo 1 (commit), trozo 2 (resumen y traducción), reducción, sin trozos; el reagrupado cae en «al combinar» sin test propio |
| REQ-002 | sí | sí | carga vista y lista, lista solo en la sonda del plazo (tras la revisión), lista desde el principio, `model_swap` sin nota |
| REQ-003 | sí | sí | 2,4 s nombrado, 0,4 s no; el texto dice que es el total de la operación (tras la revisión) |
| REQ-004 | sí | sí | `tests/test_read_timeout_cause.py` intacto; `HTTP_TIMEOUT` y valores de `read_timeout_cause` sin cambios |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Modelo listo entre la última muestra de la vigilancia y la sonda del plazo: seguía saliendo «estaba cargado» | importante | — | suspected | Arreglado: texto `read_timeout_loaded_at_end` y `load_ms` = momento de la sonda (cota); test con control positivo |
| F2 | Tests de carga dependían del reloj (0,15 s) y podían fallar con la máquina cargada | — | importante | suspected | Arreglado: `/running` decide por hilo (primera consulta de la vigilancia), márgenes 0,2/0,6–0,7 s |
| F3 | La espera de turno es la acumulada de la operación y el texto decía «antes del envío» | menor | importante | confirmed | Arreglado: «antes de sus envíos la operación esperó N s en total el turno o una plaza» |
| F4 | Nota de carga con `model_swap` podía contradecir el texto base | menor | menor | confirmed | Arreglado: con `model_swap` no se añade; test |
| F5 | «Ya está cargado» promete de más; «cargándose» incluye esperar el cambio de modelo | — | menor | suspected | Arreglado: «aún no estaba listo (cargándose o esperando a que llama-swap cambiara de modelo)» y «ahora está cargado; si sigue así…» |
| F6 | Wiki fijaba «180 s» | — | menor | suspected | Arreglado: `LOCAL_DELEGATE_TIMEOUT`, 180 s por defecto |
| F7 | `load_ms` se asignaba antes del texto | menor | — | suspected | Arreglado: se asigna después |
| F8 | El turno remoto (`_remote_wait`) no pasa por la fase `turn`: no se nombra | — | menor | suspected | Aceptado: omisión, no texto falso |
| F9 | Sin tests del reagrupado ni de la nota con causa `None` | menor | menor | confirmed | Aceptado: comportamiento correcto por lectura; queda como límite |

## Required follow-up

- Ninguno obligatorio; queda opcional una prueba en vivo con un plazo agotado de verdad. Revisión antes de mezclar: la de resultado con dos jueces de esta tabla (`conforms-with-notes`), cuyos ajustes F1–F7 se aplicaron en el segundo commit de la rama; en el PR no consta otra revisión independiente (sin reviews ni comentarios). Mezclado en `main` como `fae612c7` (PR #575) con 19 de 22 checks en verde: `test (macos-latest)` y `plugin (macos-latest)` cancelados a los ~20 min y, por ellos, `ci-gate` en rojo; en el CI de `main` de `fae612c7` los dos de macOS también se cancelaron y `ci-gate` quedó en rojo. El usuario autorizó expresamente esta mezcla sin macOS el 2026-11-04 (bypass temporal del ruleset `protect-main`, restaurado después; consta en el relevo de la jornada). El CI de `main` vuelve a verde en `576344b5` y en `cf1474d8`.
