# Verification: Ctrl+C sobre el MCP stdio sale limpio en vez de con traceback

## Environment

- Base `87b5d93` (`main`, tras el PR #110); rama `fix/ctrl-c-limpio`.
- Windows 11, `uv run`.

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | interrupción en `mcp.run()` | ✅ | `server.main()` retorna en vez de propagar |
| REQ-002 | salida capturada | ✅ | sin `Traceback` en stdout ni stderr |
| REQ-003 | `serve` sigue devolviendo 0 | ✅ | `test_ctrl_c_en_el_daemon_tampoco` |
| REQ-004 | los dos en la misma corrida | ✅ | `[('stdio', 'limpio'), ('serve', 'limpio')]` |
| REQ-005 | captura acotada | ✅ | el `try` rodea solo `mcp.run()` |

### Antes del arreglo, medido

```
=== camino: stdio ===          === camino: serve ===
@@ SALIO SIN CAPTURAR          local-delegate daemon -> …
Traceback (most recent call    @@ TERMINO SIN EXCEPCION,
  last):                          devolvio 0
  … server.py:1955, in main
    mcp.run()
KeyboardInterrupt
```

**Los dos primeros intentos de reproducción no probaron nada**: en uno el argumento se coló como
subcomando del CLI (el proceso ni llegó a `mcp.run()`), en el otro `serve` salió antes por el
`FileLock` del daemon real. Se rehizo con `LOG_DIR` propio y `sys.argv` limpio hasta que los dos
caminos se ejercieron de verdad. Un no-resultado sin comprobar que la búsqueda podía encontrar
algo no es evidencia — y es la tercera vez en esta sesión que ese mismo patrón muerde.

### Verificación al revés

Sustituido `except KeyboardInterrupt` por `except SystemExit`:

```
!!!!!!!!!!!!!!!!!!!! KeyboardInterrupt !!!!!!!!!!!!!!!!!!!!
tests\test_ctrl_c.py:32: KeyboardInterrupt
no tests ran in 1.25s
```

Cazado de la forma más contundente posible: sin la captura, la interrupción **tumba la sesión de
pytest entera**.

## Quality checks

- [x] `uv run pytest -q` → suite completa en verde.
- [x] `ruff check` / `ruff format --check` → limpios.
- [x] Sin secretos.
- [x] Sin cambios ajenos.

## Deviations and residual risk

- **No se ha probado un `Ctrl+C` real en una consola.** En Windows solo `CTRL_C_EVENT` produce
  `KeyboardInterrupt`, y no puede dirigirse a un hijo concreto sin afectar al grupo del propio
  proceso que lo manda. La interrupción se inyectó en el punto exacto donde el sistema la entrega,
  que es lo que el arreglo necesita, pero **la comprobación final es del usuario en su terminal**.
- **En una consola real el ruido de antes era mayor** que en el arnés: el SDK corre sobre anyio y
  Python imprime un `ExceptionGroup` anidado, no la línea suelta que se ve arriba. El arreglo lo
  cubre igual —captura la excepción antes de que llegue al intérprete— pero conviene saber que lo
  medido es una versión reducida del síntoma.
- **Queda un pendiente nuevo, medido y sin diagnosticar:** `serve` devuelve **3** ante
  `CTRL_BREAK_EVENT`, y el MCP stdio muere con `0xC000013A`. `CTRL_BREAK` no es `CTRL_C`, así que
  es otro camino. Anotado en el backlog en vez de arreglado a ciegas.
