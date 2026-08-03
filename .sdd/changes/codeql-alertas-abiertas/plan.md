# Implementation plan: Cerrar las 10 alertas abiertas de CodeQL: 6 arreglos y 4 descartes

## Approach

Dos vías separadas, y el orden entre ellas importa: **primero los arreglos en código** (rama, PR,
CI verde, merge), **después los descartes** por API. Aplicar los descartes antes del merge dejaría
alertas cerradas sobre código que aún va a cambiar.

El criterio para elegir vía por alerta es el mismo en las diez: **se arregla si el código queda
mejor; se descarta si el único beneficio sería que la herramienta calle.** Por eso #11/#12 y #13 se
descartan aunque sean "arreglables": tocar imports Windows-only o el manejo de un hilo lector para
satisfacer una regla de estilo es meter riesgo a cambio de nada.

Los dos tests (#1, #18) se refuerzan de verdad, con control positivo: cada uno se prueba contra un
mutante que introduce el defecto que dice cubrir. Si el test no falla con el mutante, el test no
sirve y se revierte a descarte — es la trampa que este repo ya ha pagado cuatro veces
(`probar-la-pieza-no-es-probar-el-uso`).

## Ordered tasks

1. **Capturar la salida de referencia del extractor (control positivo de REQ-001)**
   - Files or modules: ninguno (solo lectura); salida al scratchpad
   - Requirements covered: REQ-001
   - Verification: `uv run python scripts/extract_dashboard_js.py <scratch>/antes.js` y guardar hash
   - Rollback or recovery: n/a, no escribe en el repo

2. **#20: `re.IGNORECASE` en el extractor**
   - Files or modules: `scripts/extract_dashboard_js.py` (línea 17, exclusivo)
   - Requirements covered: REQ-001
   - Verification: regenerar la salida, comparar hash con `antes.js` (debe ser idéntico) y
     `node --check` sobre el resultado
   - Rollback or recovery: revertir una línea

3. **#17, #15, #3: comentario explicativo en los tres `except`**
   - Files or modules: `src/local_delegate/resources/hooks/hook_common.py:36`,
     `src/local_delegate/daemon.py:86`, `src/local_delegate/server.py:159` (exclusivos, una línea
     de comentario cada uno; **sin cambiar el flujo de control**)
   - Requirements covered: REQ-002
   - Verification: suite completa verde; revisión de que ningún `except` cambió de tipo ni de cuerpo
   - Rollback or recovery: revertir; son comentarios, no hay efecto funcional

4. **#1: reforzar `test_web_fonts_can_be_disabled_for_zero_third_party_requests`**
   - Files or modules: `tests/test_metrics.py` (función de la línea 474, exclusivo)
   - Requirements covered: REQ-003
   - Verification: **mutante** — parchear `render_index` para que ignore `WEB_FONTS=False` y
     comprobar que el test falla, y que falla por el assert de ausencia
   - Rollback or recovery: si CodeQL sigue marcándolo, se deja el test reforzado igual (es mejor) y
     la alerta pasa a la lista de descartes

5. **#18: reforzar el test de concurrencia del semáforo**
   - Files or modules: `tests/test_core.py` (función que termina en la línea 619, exclusivo)
   - Requirements covered: REQ-004
   - Verification: **mutante** — quitar la liberación del semáforo / permitir 3 slots y comprobar
     que el test falla por el assert nuevo
   - Rollback or recovery: igual que el anterior

6. **Suite completa y push**
   - Files or modules: ninguno
   - Requirements covered: REQ-006
   - Verification: `uv run pytest` local; tras el push, `gh run list` **completo** (todos los
     workflows, no solo CI — regla del repo `feedback-verify-full-ci-before-done`)
   - Rollback or recovery: no mergear si algo va en rojo

7. **PR, revisión del usuario y merge**
   - Files or modules: ninguno
   - Requirements covered: REQ-006
   - Verification: CI verde en la PR, incluido el propio job de CodeQL sobre la rama
   - Rollback or recovery: cerrar la PR sin mergear

8. **Los cuatro descartes (#19, #13, #11, #12) — solo tras el merge**
   - Files or modules: ninguno en el repo; `PATCH /repos/.../code-scanning/alerts/{n}` con
     `dismissed_reason` y `dismissed_comment`
   - Requirements covered: REQ-005
   - Verification: `gh api ...?state=open` devuelve `[]`
   - Rollback or recovery: reversible — `PATCH` con `state: open` reabre cualquiera

## Test strategy

- **Unit:** la suite existente del proyecto (`uv run pytest`), que ya cubre metrics, core, daemon y
  hooks.
- **Integration:** el extractor ejecutado de verdad contra `metrics.HTML` real, no un stub, con
  comparación de hash antes/después.
- **End-to-end o manual:** `node --check` sobre el JS extraído.
- **Control positivo (obligatorio aquí):** los dos tests reforzados se validan contra un mutante
  cada uno. Un test que no falla con el defecto inyectado no cuenta como cubierto.
- **Security and secret scanning:** el propio job de CodeQL corre sobre la PR (`pull_request` está
  en los triggers del workflow); es la comprobación definitiva de REQ-001..REQ-004.

## Migration and compatibility

Sin migración. Sin cambio de API pública, CLI ni formato de datos. No procede bump de versión ni
release: nada de esto es visible para el usuario del paquete. Los tres comentarios en `except` y el
flag de la regex no alteran ningún camino de ejecución.

## Plan review

- [x] Every requirement maps to at least one task and verification step — REQ-001→t2, REQ-002→t3,
      REQ-003→t4, REQ-004→t5, REQ-005→t8, REQ-006→t6/t7.
- [x] Risky or destructive operations have safeguards and rollback — el único paso que escribe fuera
      del repo (t8) va después del merge, con revisión previa del usuario, y es reversible.
- [x] Dependencies and configuration changes are explicit — ninguna; no se toca `pyproject.toml` ni
      el workflow de CodeQL.
- [x] The plan does not include unrelated work — los non-goals de la spec excluyen la suite de
      queries, el refactor de `ctypes` y el `BaseException` del canario.

### Hallazgos de la revisión adversarial

- **"¿Y si el mutante de t4 no puede fallar?"** — el assert de ausencia (`not in html`) solo falla si
  `render_index` emite la URL con `WEB_FONTS=False`. El mutante hace exactamente eso. Distinguible.
- **"¿El hash idéntico de t2 prueba algo?"** — prueba que no hubo regresión, no que el flag sirva.
  Es el objetivo correcto: el flag es defensa futura, no un arreglo de un fallo actual. Queda dicho
  en la spec (REQ-001 pide "el mismo bloque", no "un bloque distinto").
- **"¿Y si un comentario en `except` no basta para la regla?"** — `py/empty-except` acepta cualquier
  comentario dentro del bloque. Si aun así siguiera marcando, el job de CodeQL de la PR lo dirá
  antes del merge, y esas alertas pasarían a descarte.
