# Specification: Ctrl+C sobre el MCP stdio sale limpio en vez de con traceback

## Summary

Parar el proceso con `Ctrl+C` termina en silencio y con código 0 **por los dos caminos** —el MCP
stdio y el daemon—, porque pararlo a mano es la forma normal de pararlo y no un fallo.

## Requirements

- **REQ-001:** Un `KeyboardInterrupt` durante `mcp.run()` no escapa de `server.main()`.
- **REQ-002:** Ese cierre no imprime traceback.
- **REQ-003:** `daemon.serve()` mantiene su comportamiento: devuelve 0.
- **REQ-004:** Un test comprueba los **dos** caminos en la misma corrida.
- **REQ-005:** La captura se acota a la llamada bloqueante, no envuelve la inicialización.

## Acceptance scenarios

### Scenario: se para el MCP lanzado a mano

- **Given** `local-delegate` corriendo en una terminal
- **When** llega `Ctrl+C`
- **Then** el proceso termina sin traceback y con código 0

### Scenario: los dos caminos coinciden

- **Given** una interrupción inyectada en la llamada bloqueante de cada camino
- **When** se ejecutan los dos
- **Then** ninguno propaga y ninguno imprime traceback

## Edge cases and failure behavior

- **Interrupción durante el arranque** (antes de `mcp.run()`): **no** se captura, y es deliberado.
  Silenciarla escondería un fallo de inicialización detrás de un cierre aparentemente normal.
- **`CTRL_BREAK_EVENT` en Windows:** no genera `KeyboardInterrupt`, así que este arreglo no lo
  cubre. Queda anotado en el backlog con sus códigos medidos.

## Non-functional requirements

- **Silencio en el cierre:** quien pulsó `Ctrl+C` ya sabe que paró el proceso; un mensaje de
  despedida es ruido.
- **Código 0:** un gestor de servicios que mire la salida no debe apuntarse una caída.

## Non-goals

- Diagnosticar el `rc 3` de `serve` ante `CTRL_BREAK`.
- El ruido `HTTP Request: … 401` de `httpx2`, que aparece en la misma salida y es otra cosa.

## Traceability

| Requisito | Trabajo | Evidencia |
| --- | --- | --- |
| REQ-001 | `server.main()` | `test_ctrl_c_en_el_mcp_stdio_*` + mutante |
| REQ-002 | idem | el mismo test, sobre `capsys` |
| REQ-003 | — (sin cambios) | `test_ctrl_c_en_el_daemon_tampoco` |
| REQ-004 | `tests/test_ctrl_c.py` | `test_los_dos_caminos_tratan_igual_el_ctrl_c` |
| REQ-005 | `server.main()` | revisión: el `try` rodea solo `mcp.run()` |
