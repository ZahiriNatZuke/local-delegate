# Verification: preguntar en vez de fallar seco

## Environment

- Revisión: rama `feat/elicitation-preguntar` sobre `main` en `3f46041`.
- Runtime: Python 3.11 (uv), `mcp` 2.0.0, Windows 11.

## Quality checks

- [x] `uv run pytest -q` → **539 passed, 1 skipped** (519 antes + 20 nuevos).
- [x] `uv run ruff check .` → `All checks passed!`
- [x] `uv run ruff format --check .` → `61 files already formatted`
- [x] `extract_dashboard_js.py` + `node --check` → `node --check OK`
- [x] Secret scanning — sin credenciales; hay test que asevera que las preguntas **no** llevan el
      input ni rutas del disco.
- [x] No unrelated changes.

## Los tests, verificados al revés

Ocho defectos, introducidos uno a uno, suite completa por cada uno, fichero restaurado y comprobado
byte a byte:

| Defecto introducido | Resultado |
| --- | --- |
| el plazo puesto **mal** (alrededor de `from_thread.run`) | 2 tests fallan |
| no comprobar el canal de vuelta | `test_con_capability_pero_sin_canal_tampoco` falla |
| no comprobar la capability | `test_sin_la_capability_no_se_puede` falla |
| ignorar el interruptor de configuración | `test_apagado_por_configuracion` falla |
| no validar la respuesta contra el catálogo | `test_respuesta_que_no_esta_en_el_catalogo_tampoco_vale` falla |
| no preguntar con `output_format` en blanco | `test_output_format_en_blanco_se_pregunta` falla |
| **tratar `decline`/`cancel` como aceptación** | **al principio no rompía nada** → ver abajo |
| *(el anterior, tras añadir el test que faltaba)* | `test_un_decline_no_se_cuela_como_aceptacion` falla |

### El hueco que encontró el ejercicio

Tratar un «no» del usuario como un «sí» **pasaba los 19 tests**. El motivo es sutil y es justo lo
que un test decorativo esconde: un `decline` no trae `content`, y validar `{}` contra un modelo de
campos obligatorios falla igual — así que el rechazo ocurría, **pero por la razón equivocada**. Con
un modelo cuyos campos tengan `default`, `{}` sí valida y el usuario diría que no mientras el
servidor entiende que sí.

Se añadió `test_un_decline_no_se_cuela_como_aceptacion`, que usa exactamente ese modelo. Con el
defecto puesto, ahora falla.

## Evidence

| Requirement | Check | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | pregunta con el backend caído | pass | `_post_chat`; `test_el_usuario_responde` end-to-end |
| REQ-002 | acepta → arranca y reintenta; no → error de hoy | pass | tests de accept/decline/cancel |
| REQ-003 | ofrece los modelos válidos | pass | `test_modelo_invalido_con_respuesta_continua_con_el_elegido` |
| REQ-003b | sin respuesta → error ya y **sin backend** | pass | `test_modelo_invalido_sin_respuesta_falla_ya_y_sin_tocar_el_backend` asevera `vistos == []` |
| REQ-004 | `output_format` en blanco | pass | tests con `"   "` y con formato |
| REQ-005 | capability **y** canal, por separado | pass | tres tests, uno por combinación |
| REQ-006 | plazo real | pass | ver abajo |
| REQ-007 | degradación ante excepción | pass | `test_una_sesion_que_revienta_no_propaga` |
| REQ-008 | variable de entorno | pass | `test_apagado_por_configuracion` |
| REQ-009 | ninguna tool expone el contexto | pass | `test_ninguna_tool_expone_ctx_en_su_schema` sobre las 11 |

### Sobre REQ-006, que es el que más fácil se falsea

El test **no corta desde fuera**: mide que la tool **vuelve sola** dentro del plazo, y además que
**no vuelve antes** —si volviera al instante, sería que ni llegó a preguntar—. Las dos aserciones
juntas son las que distinguen la implementación buena de la mala. La suite de este fichero tarda
4.2 s justamente porque esos dos tests consumen sus 2 s de plazo de verdad.

## Un defecto real que cazó un test

La primera implementación llamaba a `ctx.elicit(...)`. **`ServerRequestContext` —lo que ve un
middleware— no tiene ese método**: es del `Context` de alto nivel, que solo llega a las tools que lo
declaran en su firma. El `except` se tragaba el `AttributeError` y `preguntar()` devolvía `None`
siempre: el mecanismo no habría funcionado nunca, en silencio. Lo cazó
`test_el_plazo_se_agota_y_no_antes`, que falló con «volvió en 0.0 s». Se cambió a
`ctx.session.elicit_form(...)` con validación propia contra el modelo.

## Deviations and residual risk

- **No se ha probado contra Claude Code y Codex reales**, solo contra un `ClientSession` real del
  SDK. Está medido que ambos **declaran** la capability, pero **cómo presenta cada uno la pregunta
  al usuario** —y si un cliente en modo no interactivo declina o se queda callado— no se ha visto.
  El plazo cubre el peor caso; aun así es lo primero que conviene mirar en uso real.
- **El default activado tiene un peor caso conocido**: un cliente que declare `elicitation` y no
  atienda las preguntas verá cada fallo de backend tardar hasta 30 s de más. Por eso el plazo es
  corto y `LOCAL_DELEGATE_ASK=0` existe.
- **`chunk` y `style` quedaron fuera** por decisión de la revisión del plan: sus listas son fijas y
  documentadas, la de `model` sale de la configuración de cada instalación.
