# Research: Ctrl+C sobre el MCP stdio sale limpio en vez de con traceback

## Current behavior

- `server.main()` termina en `mcp.run()` **sin protección** (`server.py:1955` antes del cambio).
- `daemon.serve()` sí la tiene, y su comentario explica el porqué: *«Algunos runners (incluido
  uvicorn sobre asyncio en Windows) vuelven a propagar Ctrl+C después de cerrar limpiamente el
  lifespan»*.
- `__main__.py` llama a `server.main()` directamente, sin envolverla.

### Reproducción

Inyectando `KeyboardInterrupt` en la llamada bloqueante de cada camino, con `LOG_DIR` propio y el
puerto libre para que los dos se ejerzan de verdad:

```
=== camino: stdio ===
@@ EL KeyboardInterrupt SALIO SIN CAPTURAR
Traceback (most recent call last):
  File "D:\...\server.py", line 1955, in main
    mcp.run()
KeyboardInterrupt

=== camino: serve ===
local-delegate daemon -> http://127.0.0.1:9499/mcp
@@ TERMINO SIN EXCEPCION, devolvio 0
```

**Los dos primeros intentos de reproducción no probaron nada** y hubo que rehacerlos: en uno el
argumento de prueba se coló como subcomando del CLI y el proceso ni llegó a `mcp.run()`; en el
otro, `serve` salió antes por el `FileLock` del daemon real. Un no-resultado sin comprobar que el
camino se ejerció no es evidencia.

### Medido de pasada, no diagnosticado

Mandando `CTRL_BREAK_EVENT` a un proceso real: `serve` cierra ordenado (imprime
`StreamableHTTP session manager shutting down`) pero devuelve **3**, y el MCP stdio muere con
`0xC000013A` (`STATUS_CONTROL_C_EXIT`). `CTRL_BREAK` **no es** `CTRL_C` —Python solo convierte el
segundo en `KeyboardInterrupt`—, así que estos números describen otro camino. Van al backlog.

## Impact map

| Área | Responsabilidad actual | Impacto esperado | Evidencia |
| --- | --- | --- | --- |
| `server.main()` | Arranca el MCP stdio | Captura la interrupción | `server.py:1955` |
| `daemon.serve()` | Sirve el daemon | **Sin cambios**: ya lo hacía | `daemon.py:214-217` |
| `tests/test_ctrl_c.py` | — (nuevo) | Ata los dos caminos | — |

## Existing conventions

- **Degradar en silencio lo que no es un fallo.** El repo ya lo hace con la web embebida (`except
  Exception: pass  # la web nunca debe impedir que arranque el MCP`).
- **Los comentarios explican el porqué y la historia del defecto**, no lo que hace la línea.
- **Cuando hay dos caminos al mismo sitio, se prueban los dos.** Es la lección más repetida de este
  repo, y aquí el defecto es literalmente esa lección sin aplicar.

## Dependencies and integrations

- Ninguna. Es una captura de excepción y un módulo de tests.

## Risks and unknowns

- **Confirmado por ejecución:** la asimetría entre los dos caminos, y que el arreglo la cierra.
- **Confirmado por mutante:** quitar la captura tumba la sesión de pytest entera.
- **No verificado en una consola real con `Ctrl+C` de verdad.** En Windows solo `CTRL_C_EVENT`
  produce `KeyboardInterrupt` y no puede dirigirse a un hijo concreto sin afectar al propio grupo
  de procesos. La interrupción se inyectó en el punto exacto donde el sistema la entrega, que es
  lo que este arreglo necesita, pero la comprobación final la da el usuario en su terminal.
