# Implementation plan: Ctrl+C sobre el MCP stdio sale limpio en vez de con traceback

## Approach

**Aplicar en el camino stdio la misma captura que `daemon.serve` ya tenía**, acotada a la llamada
bloqueante.

No se inventa nada: el patrón existe, está comentado y está probado en el otro camino. El trabajo
de diseño real es doble y va en el test, no en el arreglo:

1. **Acotar la captura a `mcp.run()`** y no a toda `main()`. Envolver la inicialización
   escondería un fallo de arranque detrás de un cierre aparentemente normal.
2. **Probar los dos caminos juntos.** El defecto no fue no saber qué hacer, fue arreglarlo en un
   sitio y darlo por cerrado. Un test que mire solo el camino nuevo repetiría el error.

## Ordered tasks

1. **Capturar la interrupción**
   - Ficheros: `src/local_delegate/server.py`
   - Requisitos: REQ-001, REQ-002, REQ-005
   - Verificación: mutante que la quita.
   - Rollback: revertir el `try`.

2. **El test de los dos caminos**
   - Ficheros: `tests/test_ctrl_c.py`
   - Requisitos: REQ-003, REQ-004
   - Verificación: con el mutante puesto, la suite cae.
   - Rollback: borrar el módulo.

3. **CHANGELOG y backlog**
   - El `rc 3` de `CTRL_BREAK` se anota como pendiente, no se arregla a ciegas.

## Test strategy

- **Unit:** interrupción inyectada en la llamada bloqueante de cada camino, con los colaboradores
  externos doblados (puerto, autostart, uvicorn, la web).
- **Verificación al revés:** sustituir `except KeyboardInterrupt` por `except SystemExit` y
  comprobar que la suite cae.
- **Manual, y queda pendiente del usuario:** un `Ctrl+C` real en una terminal. En Windows no se
  puede mandar `CTRL_C_EVENT` a un hijo concreto sin afectar al propio grupo de procesos.
- **Secretos:** no aplica.

## Migration and compatibility

Ninguna. Solo cambia qué se imprime al parar el proceso a mano; el código de salida ya era 0 en el
único camino que lo definía.

## Plan review

- [x] Cada requisito mapea a tarea y verificación.
- [x] Nada destructivo.
- [x] Sin dependencias nuevas.
- [x] Sin trabajo ajeno: el `rc 3` y el ruido de `httpx2` quedan fuera y anotados.
