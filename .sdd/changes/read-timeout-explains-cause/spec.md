# Specification: Un read_timeout dice si fue cola, carga o generación y en qué trozo (#572)

## Summary

El mensaje de un `read_timeout` y su evento de uso dicen en qué trozo falló, si el modelo se estaba
cargando (y a los cuántos segundos quedó listo) y cuánto esperó turno antes del envío. Los plazos no
cambian.

## Requirements

- **REQ-001** — En una operación troceada (más de un trozo), el texto de un `read_timeout` nombra el
  trozo que falló («trozo X de N», o la reducción final) y el evento lleva `read_timeout_piece` y
  `pieces`.
  - Request: "nº de trozo en curso de cuántos"
  - Verify: test tests/test_read_timeout_explains.py
- **REQ-002** — Si durante el envío se vio el modelo pedido cargándose y después listo, el texto lo
  dice (listo a los ~S s, quedaban ~R s del plazo) en lugar de «estaba cargado», y el evento lleva
  `read_timeout_load_ms`. `read_timeout_cause` no cambia de valor.
  - Request: "que el error diga cuál fue la causa con lo que el servidor ya sabe (tiempo esperando turno vs generando"
  - Verify: test tests/test_read_timeout_explains.py
- **REQ-003** — Si la operación esperó turno o plaza del daemon al menos 1 s antes del envío, el
  texto dice cuánto y que esa espera no cuenta para el plazo.
  - Request: "tiempo esperando turno vs generando"
  - Verify: test tests/test_read_timeout_explains.py
- **REQ-004** — Sin esa información el texto es exactamente el de hoy, y los plazos no cambian.
  - Request: "No subas plazos a ciegas"
  - Verify: test tests/test_read_timeout_cause.py

## Acceptance scenarios

### Scenario: el primer trozo de un commit grande agota el plazo con el modelo recién cargado

- **Given** un diff en varios trozos y un backend que tarda en cargar el modelo y no responde a tiempo
- **When** se llama a `local_commit_msg`
- **Then** el error dice «trozo 1 de N», que el modelo se estaba cargando y cuándo quedó listo

## Edge cases and failure behavior

- Modelo nunca listo: no se añade la frase de carga (los textos `model_swap`/`read_timeout` ya lo cubren).
- La observación falla: el texto de hoy.

## Non-functional requirements

- es+en en el catálogo i18n; nada de contenido del usuario en el log.

## Non-goals

- Cambiar `HTTP_TIMEOUT`, ver la cola de otra máquina dentro de llama-swap.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
