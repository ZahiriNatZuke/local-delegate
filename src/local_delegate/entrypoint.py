"""Punto de entrada del binario: el único módulo que conoce al CLI **y** al servidor.

Vivía dentro de `server.py`, y ahí cerraba un ciclo de importación real: `server` importaba `cli`
—para despachar los subcomandos— y `cli` volvía a `server` y a `daemon`, que a su vez importa
`server`. Los imports diferidos lo hacían funcionar, pero el grafo seguía teniendo el ciclo, con
seis alertas del analizador estático apuntándolo, y sobre todo contradecía lo que el propio
docstring de `cli.py` afirma: **`server` no debe conocer al CLI**.

La forma correcta es la de siempre para esto: quien despacha va *por encima* de los dos. Un punto
de entrada puede conocer al CLI y al servidor; el servidor no tiene por qué saber que existe un
CLI. Con `main()` aquí, `server.py` deja de importar `cli` y el ciclo desaparece de verdad, no
escondido tras un import perezoso.

El import de `cli` sigue siendo diferido, pero ahora por la razón que siempre debió ser la única:
**coste de arranque**. Sin argumentos esto es un servidor MCP y no hay que pagar el parser.
"""

from __future__ import annotations

import sys

from . import autostart, config, server


def _aviso_de_terminal_interactiva() -> None:
    """Dice por qué no pasa nada cuando una persona escribe el comando a secas.

    Sin argumentos esto es un servidor MCP stdio, que se queda esperando mensajes JSON-RPC:
    para quien lo escribió en su terminal es idéntico a un cuelgue. El aviso va por **stderr**
    a propósito —stdout es el canal del protocolo— y solo cuando stdin es una TTY, que es lo
    único que distingue a una persona de un host MCP. No cambia nada: el servidor arranca igual.

    Detalle de Windows, comprobado en vivo y no obvio: redirigiendo desde ``/dev/null`` en Git
    Bash **sí** sale el aviso, porque MSYS lo traduce a ``NUL``, que es un dispositivo de
    carácter y hace que ``isatty()`` devuelva ``True``. No es un fallo del criterio: un host MCP
    no redirige desde ``NUL``, usa una **tubería**, y con una tubería no sale nada (verificado).
    """
    try:
        interactiva = sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        return  # bajo un host MCP stdin puede estar cerrado o no ser un fichero de verdad
    if not interactiva:
        return
    print(
        "local-delegate: sin subcomando, esto arranca el servidor MCP stdio y espera por stdin.\n"
        "               Si buscabas los comandos: local-delegate --help",
        file=sys.stderr,
    )


def main() -> None:
    """Punto de entrada del binario (usado por [project.scripts] local-delegate).

    Una sola frontera: **con argumentos es un CLI, sin argumentos es un servidor MCP stdio.**

    Aquí hubo una lista literal de subcomandos que decidía el despacho, y todo lo que no
    estuviera en ella —``--help`` incluido— caía al servidor MCP y se colgaba esperando stdin.
    Quien sabe qué subcomandos existen es el parser de ``cli.py``, así que se le entregan todos
    los argumentos y él responde: ayuda, subcomando válido, o «invalid choice» con código 2.
    Importar ``cli`` es seguro sin el extra ``[llamaswap]``: ``llamaswap_config`` resuelve su
    ``import yaml`` en un ``try/except``.

    Sin argumentos no cambia nada, y es deliberado: así es como lo lanzan los hosts MCP.
    """
    if len(sys.argv) > 1:
        from . import cli

        sys.exit(cli.run(sys.argv[1:]))

    _aviso_de_terminal_interactiva()
    # Auto-arranque del backend solo si el usuario lo pidió explícitamente (opt-in).
    if config.AUTOSTART:
        autostart.ensure_backend(wait=0)
    # Web de métricas embebida en un hilo daemon: vive y muere con este proceso MCP.
    # Si el puerto ya está ocupado (otra instancia de Claude), run_in_thread devuelve None.
    if config.WEB_ENABLED:
        try:
            from .web import metrics

            metrics.run_in_thread(host=config.WEB_HOST, port=config.WEB_PORT)
        except Exception:
            pass  # la web nunca debe impedir que arranque el MCP

    # Ctrl+C es la forma NORMAL de parar esto cuando se lanza a mano en una terminal, no un
    # fallo. Sin esta captura el `KeyboardInterrupt` sube por `mcp.run()` y Python imprime el
    # traceback — y como el SDK corre sobre anyio, lo que se ve no es una línea sino un
    # `ExceptionGroup` anidado con el rastro de las tareas del grupo. Un servidor que al pararse
    # a propósito escupe eso parece roto, y ya se reportó como tal.
    #
    # `daemon.serve` lleva esta misma captura desde hace tiempo, con su comentario y todo; el
    # camino stdio se quedó fuera. Dos caminos hasta el mismo `Ctrl+C` y solo uno preparado.
    #
    # Y con Ctrl+Break pasaba lo mismo un nivel más abajo: son dos eventos de consola distintos y
    # el `except` de aquí solo veía uno. `preparar_ctrl_break` los iguala antes de servir.
    server.preparar_ctrl_break()
    try:
        server.mcp.run()
    except KeyboardInterrupt:
        # Silencio deliberado: el usuario acaba de pedir el cierre, ya sabe que paró el proceso.
        # Se sale por 0 porque parar a mano no es un fallo, y un gestor de servicios que mire el
        # código de salida no debe apuntarse una caída.
        return
