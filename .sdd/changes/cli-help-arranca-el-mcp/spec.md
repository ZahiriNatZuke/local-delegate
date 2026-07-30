# Especificación — el CLI responde a `--help` en vez de arrancar el servidor MCP

## Summary

Un solo criterio ordena el despacho del binario: **con argumentos es un CLI, sin argumentos es un
servidor MCP stdio.** Hoy la frontera la decide una lista literal de siete nombres, y todo lo que
no está en ella —`--help` incluido— arranca el servidor y se cuelga. Después del cambio, argparse
ve todos los argumentos y responde a lo que sabe; lo que no sabe lo rechaza en voz alta.

## Requirements

- **REQ-001:** `local-delegate --help` y `local-delegate -h` imprimen la ayuda del parser por
  **stdout** y terminan con código **0**, sin abrir ninguna conexión de red y sin arrancar el
  servidor MCP.
- **REQ-002:** Un primer argumento que no sea un subcomando conocido (`local-delegate doctro`) hace
  fallar a argparse: mensaje de error por **stderr** y código **2**. No arranca el servidor MCP.
- **REQ-003:** Un subcomando conocido con sus argumentos sigue delegando en `cli.run(sys.argv[1:])`
  y devolviendo su código de salida, exactamente como hoy.
- **REQ-004:** `local-delegate` **sin argumentos** arranca el servidor MCP stdio con el mismo
  comportamiento de hoy, incluidos el auto-arranque opt-in del backend y el hilo de la web de
  métricas. Es el contrato con los hosts MCP y no cambia.
- **REQ-005:** Cuando se invoca sin argumentos **y stdin es una TTY** —o sea, lo escribió una
  persona, no un host MCP—, se imprime **por stderr** una línea que dice que está arrancando el
  servidor MCP stdio y que la ayuda está en `local-delegate --help`. Es informativa: el servidor
  arranca igual. Nunca se escribe por stdout, que es el canal del protocolo.
- **REQ-006:** El conjunto de nombres de subcomandos existe **una sola vez** en el código, en las
  llamadas a `sub.add_parser(...)`. `server._CLI_COMMANDS` y `cli.KNOWN_COMMANDS` desaparecen.
- **REQ-007:** Añadir un subcomando nuevo al parser no exige tocar ningún otro sitio para que sea
  invocable. (Es la propiedad que necesita el change B, que añade `update`.)

## Acceptance scenarios

### Escenario: la ayuda

- **Dado** el paquete instalado y el backend inaccesible o rechazando la credencial
- **Cuando** se ejecuta `local-delegate --help`
- **Entonces** sale el listado de subcomandos por stdout, código 0, y **cero** peticiones HTTP al
  backend

### Escenario: el subcomando mal escrito

- **Cuando** se ejecuta `local-delegate doctro`
- **Entonces** stderr dice `invalid choice: 'doctro'`, el código de salida es 2 y el proceso
  termina solo, sin esperar en stdin

### Escenario: el host MCP

- **Dado** la entrada MCP que genera `install.mcp_entry` en modo `stdio`
- **Cuando** el host lanza el programa sin argumentos y con stdin redirigido
- **Entonces** arranca el servidor MCP stdio igual que antes del cambio, y **no** se imprime la
  línea de aviso de REQ-005

### Escenario: la persona que lo escribe a pelo

- **Cuando** se ejecuta `local-delegate` en una terminal interactiva
- **Entonces** stderr avisa de que está arrancando el servidor MCP stdio y señala
  `local-delegate --help`; stdout queda limpio

## Edge cases and failure behavior

- **Extra `[llamaswap]` ausente:** despachar al CLI importa `cli`, que importa `llamaswap_config`.
  Ese módulo hace `import yaml` en un `try/except` y deja `yaml = None`, así que el import no puede
  fallar; solo fallan `check-llamaswap` e `init-llamaswap` al ejecutarse, con su mensaje de siempre.
- **`--version`:** no existe hoy como flag del parser, así que cae en REQ-002 (código 2). Añadirla
  queda fuera de este change; lo que no puede es colgarse.
- **Argumentos después de un subcomando válido:** los gestiona el subparser, sin cambios.

## Non-functional requirements

- **Sin dependencias nuevas.** El cambio quita código, no añade.
- **Compatibilidad:** la única invocación que cambia de comportamiento es la que hoy arranca el
  servidor por error (argumentos desconocidos). Ninguna entrada MCP generada por el instalador pasa
  argumentos al programa.
- **Terminadores de línea:** `server.py`, `cli.py` y `CHANGELOG.md` están en CRLF en git; el diff
  debe tocar solo las líneas del cambio.

## Non-goals

- No se añade `--version` ni ningún subcomando.
- No se toca el logging de `httpx2` que produce las líneas `HTTP Request: ... 401`.
- No se publica a PyPI.

## Traceability

| Req | Trabajo previsto | Verificación |
|---|---|---|
| REQ-001, 002, 003, 004 | `server.main()`: despachar por presencia de argumentos | tests en `tests/test_smoke.py` + ejecución real de los cuatro casos |
| REQ-005 | aviso por stderr con `sys.stdin.isatty()` | test con stdin doblado en los dos sentidos |
| REQ-006, 007 | borrar `server._CLI_COMMANDS` y `cli.KNOWN_COMMANDS` | `grep` sin resultados + test de que un nombre nuevo del parser es invocable sin tocar nada más |
