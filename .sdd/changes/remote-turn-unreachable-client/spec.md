# Specification: Turno remoto inalcanzable: en serie, corte y aviso (#577)

## Summary

Cuando el turno remoto (el daemon de la máquina del backend) no responde, el cliente ya no compite
a ciegas por el backend: las operaciones que siguen sin turno van **de una en una** en este
proceso; si una de ellas agota su plazo en el backend, se abre un **corte de turno remoto** y las
que esperaban (y las nuevas) fallan al momento con un aviso claro; y el error de una llamada sin
turno dice que no había turno.

Decisión (con evidencia en `research` de `brief.md`): **seguir sin turno, en serie**, y no fallar
siempre rápido. El daemon parado con el backend sano es un caso real y medido (#512, prueba en vivo
del 2026-10-30: la delegación salió bien sin turno); fallar siempre lo rompería. El corte solo se
abre cuando hay prueba de que el backend no da abasto (un plazo agotado sin turno).

## Requirements

- **REQ-001** — Una operación cuyo turno remoto acaba `unreachable` sigue sin turno, pero solo una
  a la vez por URL de turno en este proceso; las demás esperan su sitio (cancelables) y el evento
  sigue diciendo `remote_turn: "unreachable"`.
  - Request: "seguir sin turno pero serializado en local (concurrencia 1)"
  - Verify: test tests/test_remote_turn_unreachable.py
- **REQ-002** — Un intento al backend sin turno (`unreachable`) que falla con clase `read_timeout`
  o `capacity_or_load` abre el corte de turno remoto (fichero compartido como el corte por backend,
  `remote-turn-cut.json`) durante `LOCAL_DELEGATE_REMOTE_TURN_CUT_S` (120 s; dobla hasta `_MAX_S`,
  600 s). Lo cierra un intento sin turno que sale bien o un turno remoto concedido.
  - Request: "un «corte» de turno análogo al de backend inalcanzable (N fallos → durante X s fallar rápido o ir en serie)"
  - Verify: test tests/test_remote_turn_unreachable.py
- **REQ-003** — Con el corte abierto, una operación que se queda sin turno por `unreachable` falla
  al momento, sin llamar al backend, con un error es+en que dice que el turno remoto no responde,
  que el backend puede estar ocupado por otra máquina y que reintentar ahora no sirve; las que ya
  esperaban su sitio salen igual en cuanto se abre (no se lanza la siguiente tras el plazo agotado).
  - Request: "Que las llamadas que ya esperan en cola vean el enfriamiento/corte cuando las primeras fallan por plazo"
  - Verify: test tests/test_remote_turn_unreachable.py
- **REQ-004** — El error de un intento que fue al backend sin turno (`unreachable`) y falló lleva una
  nota es+en: no había turno remoto y reintentar ahora no sirve. `error` y `error_class` no cambian.
  - Request: "Que el error diga que no había turno."
  - Verify: test tests/test_remote_turn_unreachable.py
- **REQ-005** — Varias esperas de turno simultáneas contra la misma URL: cuando una la declara
  inutilizable, las demás salen en su siguiente vuelta del bucle en vez de terminar su propio sondeo.
  - Request: "sin esperar 55 s por llamada"
  - Verify: test tests/test_remote_turn_unreachable.py
- **REQ-006** — El evento de una operación cortada lleva `ok: false`,
  `error: "remote_turn_unreachable"` y `remote_turn: "unreachable"`.
  - Request: derived: el panel y el log deben contar el fallo y su causa (#476).
  - Verify: test tests/test_remote_turn_unreachable.py
- **REQ-007** — Sin cambios fuera de este caso: turno concedido, otras razones (`unsupported`,
  `bad_response`, `self`, `no_turn`, `unauthorized`…), operaciones locales y suite existente igual.
  - Request: "tests existentes intactos"
  - Verify: cmd pytest completo

## Acceptance scenarios

### Scenario: cuatro llamadas a la vez con el turno caído y el backend saturado

- **Given** un turno remoto que no responde y un backend que agota el plazo
- **When** llegan cuatro operaciones a la vez
- **Then** solo una va al backend; al agotar su plazo se abre el corte y las otras tres fallan al
  momento con el aviso, sin llamar al backend

### Scenario: daemon parado con el backend sano (#512)

- **Given** un turno remoto inalcanzable y un backend que responde
- **When** llegan dos operaciones
- **Then** las dos salen bien, una detrás de otra, y no se abre corte

## Edge cases and failure behavior

- Cancelar mientras se espera el sitio sale con `CallCancelled` y no deja el sitio cogido.
- Si el fichero del corte no se puede leer, se sigue como sin corte (igual que `cooldown`).
- `LOCAL_DELEGATE_REMOTE_TURN_CUT=0` apaga el corte; la serie queda.

## Non-functional requirements

- Sin plazos nuevos más largos; nada se espera más que antes.
- El fichero del corte solo guarda `host[:puerto]` del backend, contadores y fechas.

## Non-goals

- El servidor del turno (#576) y el endpoint `/api/turn/*`.
- Serializar entre procesos distintos de la misma máquina (el corte sí es compartido).
- Cambiar la clasificación de `read_timeout`/`capacity_or_load` o el enfriamiento por modelo.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
