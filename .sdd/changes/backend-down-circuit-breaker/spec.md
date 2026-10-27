# Corte por backend inalcanzable (issue #436, punto 3)

Modo: lite.

## Qué pasa

Con el backend inalcanzable (VPN corporativa en la Mac: el nombre de la tailnet no resuelve) cada
`local_*` falla en ~22 ms, pero el agente las sigue llamando porque las instrucciones dicen que
delegue: 14 intentos fallidos en una sesión. Los hooks de sugerencia siguen empujando a delegar.

## Decisión

- Se reutiliza `cooldown.CooldownState` (estado en fichero bajo bloqueo, compartido entre el daemon
  y los procesos stdio, con espera que se dobla hasta un tope y registro de episodios), con su
  propio fichero `backend-breaker.json`, su registro `backend-breaker-events.jsonl` y una sola clave
  (`host[:puerto]` del backend). `CooldownState` gana tres parámetros (`counting`, `events_file`,
  `legacy_file`), `record_skip` y el campo `since` (inicio de la racha).
- Solo suma un fallo con `connection_failure`. Cualquier otra respuesta (éxito, 5xx,
  `capacity_or_load`, plazo de lectura, error del modelo) dice que el backend contesta y limpia.
- Con el corte abierto, `_chat`, `_chat_chunked` y `_chat_map_reduce` devuelven al momento un
  error accionable (es/en, `mcp.error.backend_down`): desde hace X min, no reintentes hasta HH:MM,
  hazlo tú, `local_status` comprueba. No se llama al backend, no se abre entrada en vuelo y **no se
  escribe en el log de uso** (ni delegación ni fallo): una línea `skip` en el registro del corte.
- Recuperación (half-open): al vencer, la siguiente llamada va de verdad; si falla, vuelve a cortar
  con la espera doblada; un sondeo bueno de `probe_backend` (`local_status`, panel) lo cierra.
- Defectos: 3 fallos, 60 s, tope 600 s. Variables `LOCAL_DELEGATE_BACKEND_BREAKER{,_FAILURES,_S,_MAX_S}`.
- Hooks: `hook_common.backend_down()` lee el fichero (ante la duda, False). Los hooks de `Read`,
  shell y prompt callan con `reason: "backend_down"`. El mod de lectura no se toca: `hook classify`
  devuelve `read_switch: "backend_down"` en vez de `on`, y el mod solo actúa con `on`.

## Criterios de aceptación

1. 2 fallos de conexión no cortan; el 3.º sí; la 4.ª llamada no llega al backend y el log de uso
   sigue con 3 eventos.
2. Errores con respuesta (500, 503) y una respuesta entre fallos no cortan.
3. Al vencer, una llamada prueba: con éxito cierra; con fallo, vuelve a cortar con 120 s.
4. `local_status` con el backend vivo cierra el corte.
5. Un corte abierto por otro proceso se ve aquí; los hooks lo ven y callan (control: sin corte,
   sugieren/bloquean).
6. Operaciones troceadas y map-reduce también se cortan.

## Verificación

`tests/test_backend_breaker.py` (22 tests) y `tests/test_cooldown.py`; suite completa; control
positivo con mutantes (corte desactivado, hooks a False, contar todo fallo).
