# Especificación (lite): la banda del mod solo dice DELEGANDO en la sesión que delega

Issue #442. Con varias sesiones de Claude Code abiertas contra el mismo daemon, una delegación de
una sesión ponía ` ◐ DELEGANDO ` (con herramienta, tiempo y trozos) en la banda de **todas**.

## Causa

- `_inflight_start` (`server.py`) no guardaba quién pidió la delegación.
- `/api/inflight` (`web/metrics.py`) devolvía las entradas de todas las sesiones sin marca.
- `statusSnapshot` (`mod/status.js`) pintaba `busy` con cualquier entrada.

## Decisión

- **Identificador**: el mod ya tiene `$.session.id()` y ya lo manda a `/api/stats?session=<id>`; el
  daemon lo convierte en la clave de un solo sentido `hook_common.session_key` y la compara con
  `caller_session_key` de la línea del log. Se usa **la misma cadena** para `inflight.json`: la nota
  del hook `record-call` (PreToolUse, por `tool_use_id`) ya lleva la clave; `_inflight_start` la lee
  (`attribution.current_session_key`, solo la nota, sin transcript ni memo por petición) y la guarda
  como `caller_session_key`. El id en claro nunca se guarda ni sale.
- **Por qué no el `pid`**: en modo http (el de esta PC) todas las sesiones comparten el proceso del
  daemon; el `pid` no distingue sesiones y el mod no lo conoce.
- **Respaldo**: una entrada sin clave (cliente sin el hook, nota vencida, entrada de un daemon
  anterior) no es de nadie: nunca se pinta como propia.
- **API**: `/api/inflight` sin parámetro responde lo mismo que antes (la clave se quita siempre).
  Con `?session=<id>` cada entrada lleva `mine` y la respuesta `mine_count` (aditivo).
- **Mod**: `busy` solo con entradas propias (la tarea y el `+N` salen solo de ellas). Si solo hay
  ajenas, estado nuevo `shared`: el punto y el color de `ready` (` ● LISTO `) y una nota tenue «en
  uso por otra sesión» / «in use by another session», sin herramienta, tiempo ni trozos, en las tres
  superficies (barra, línea y Desktop). Con un daemon anterior (sin `mine_count`) se conserva el
  comportamiento de antes. El sondeo rápido sigue mientras hay `shared` para quitar la nota a tiempo,
  y «terminó mi última delegación» (que relee las cifras) mira solo las propias.

## Criterios de aceptación

1. Con dos sesiones, la que lanzó la delegación ve ` ◐ DELEGANDO ` con su herramienta; la otra ve
   ` ● LISTO ` + «en uso por otra sesión», sin herramienta, tiempo ni trozos (es y en; barra, línea
   y Desktop).
2. Una entrada sin sesión conocida nunca se pinta como propia.
3. `/api/inflight` sin parámetro: mismas claves por entrada que antes y sin `mine_count`.
4. `inflight.json` lleva la clave de un solo sentido y nunca el id.

## Verificación

- `tests/test_inflight_per_session.py`: nota del hook → `_inflight_start` → `inflight.json` →
  `/api/inflight?session=` con dos sesiones y una sin sesión; panel sin cambios; entrada vieja;
  nota vencida. Control positivo: con `server.py`, `metrics.py` y `attribution.py` de `main` fallan
  4 de 5 (el quinto es la guarda de compatibilidad, que pasa a propósito en ambos).
- `mod/status.test.ts`: bloque «several sessions» (8 tests) con un daemon falso que marca `mine`
  según el `session` que llega en la URL. Control positivo: con `status.js` de `main` fallan los 8
  (y el de la URL de `/api/inflight`).
- Suite completa y `claude plugin test`.
