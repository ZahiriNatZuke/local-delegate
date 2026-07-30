# Brief: `local-delegate --help` arranca el servidor MCP en vez de imprimir la ayuda

## Problem

El usuario escribió `local-delegate --help` en su terminal y el comando **no imprimió nada**: se
quedó colgado hasta que dio Ctrl+C, y el Ctrl+C escupió un traceback de `anyio` de 60 líneas por
la consola. Antes del traceback salieron dos líneas de log `GET /v1/models 401 Unauthorized`.

Causa, verificada por ejecución (no leyendo el comentario):

```
$ LOCAL_DELEGATE_AUTOSTART=0 LOCAL_DELEGATE_WEB_ENABLED=0 uv run python -m local_delegate --help < /dev/null
EXIT=0
--- stdout ---   (vacío)
--- stderr ---   (vacío)
```

Exit 0, cero bytes de ayuda. No es que la ayuda saliera mal: es que **nunca se llamó a argparse**.

`server.main()` (`server.py:1877`) despacha al CLI **solo** si `sys.argv[1]` está en un conjunto
literal de siete nombres, `_CLI_COMMANDS`:

```python
if len(sys.argv) > 1 and sys.argv[1] in _CLI_COMMANDS:
    from . import cli
    sys.exit(cli.run(sys.argv[1:]))
# ...y si no, arranca el servidor MCP stdio
```

`--help` no es uno de esos siete nombres, así que cae al servidor MCP stdio, que se queda
esperando mensajes JSON-RPC por stdin. Con stdin redirigido muere en silencio con exit 0; en una
terminal se cuelga. Lo mismo le pasa a `-h`, a `--version` y a **cualquier subcomando mal escrito**:
`local-delegate doctro` no dice «invalid choice», se cuelga.

Los dos `401` son ruido colateral del mismo camino: al no despachar al CLI se ejecuta
`autostart.ensure_backend()` (`server.py:1883`), que consulta el backend dos veces. Con el
despacho arreglado, `--help` no llega ahí.

### El agravante: la lista de subcomandos está escrita tres veces

- `server._CLI_COMMANDS` (`server.py:1857`) — la que decide el despacho.
- `cli.KNOWN_COMMANDS` (`cli.py:26`) — **código muerto**: `grep -rn KNOWN_COMMANDS src/ tests/ docs/
  scripts/` devuelve una sola línea, su propia definición. Nadie la lee.
- Las llamadas reales a `sub.add_parser(...)` en `cli.py` y `benchmark.py` — la única verdad.

Hoy las tres coinciden por casualidad (siete nombres). Es la misma forma del fallo que ya costó
una sesión: *contar las superficies antes de arreglar una*. El change B añade el subcomando
`update`, que con este diseño habría que dar de alta en dos sitios y que, olvidando uno, se
colgaría exactamente igual.

## Desired outcome

- `local-delegate --help`, `-h` y `--version` imprimen lo que deben y terminan.
- Un subcomando desconocido falla con el mensaje de argparse y código 2, no se cuelga.
- `local-delegate` **sin argumentos** sigue arrancando el servidor MCP stdio, byte por byte igual
  que hoy: es como lo invocan los hosts MCP (`uvx --from local-delegate-mcp local-delegate-mcp`,
  sin argumentos) y romperlo dejaría a todos los clientes sin MCP.
- La lista de subcomandos deja de estar duplicada.

## In scope

- El despacho de `server.main()`.
- Borrar las dos copias muertas o redundantes de la lista de subcomandos.
- Tests que fijen las cuatro invocaciones (`--help`, desconocido, subcomando válido, sin argumentos).
- Entrada en `CHANGELOG.md` bajo `Unreleased`.

## Out of scope

- El ruido `HTTP Request: ... 401` cuando el daemon sí arranca (es logging de `httpx2` a nivel
  INFO en el camino legítimo del servidor; se anota en el backlog, no se toca aquí).
- Cualquier cambio en los subcomandos existentes o en sus flags.
- El change B (`update`) y el C (`install --clients`).
- Publicar a PyPI.

## Constraints and risks

- **Riesgo principal: romper el arranque MCP.** Un `local-delegate` sin argumentos que deje de
  arrancar el servidor deja sin MCP a Claude Code y a Codex. El test de la invocación desnuda es
  obligatorio.
- **Cambio de comportamiento acotado:** hoy `local-delegate loquesea` arranca el servidor MCP en
  silencio; después dará error 2. Es lo correcto (fallar ruidoso en vez de mudo) y ninguna entrada
  MCP generada por `install.mcp_entry` pasa argumentos al programa — verificado en
  `install.py:262-284`: en modo `stdio` los argumentos son de `uvx` (`--from`, el paquete), y el
  programa se ejecuta sin ninguno.
- **`cli.py` se puede importar siempre**: importa `llamaswap_config`, que hace `import yaml` dentro
  de un `try/except` y deja `yaml = None` si falta el extra `[llamaswap]`. Despachar al CLI sin
  filtrar por nombre no puede fallar por una dependencia opcional ausente.
- **Terminadores de línea:** `server.py`, `cli.py` y `CHANGELOG.md` están en **CRLF** dentro de git
  (`core.autocrlf=false`, el blob del repo ya es CRLF). Escribirlos desde Windows con un writer que
  normalice a LF ensuciaría el fichero entero. Comprobar con `git diff --stat` que solo cambian las
  líneas tocadas.

## Open questions

Ninguna abierta. Una considerada y **descartada**: que `local-delegate` sin argumentos imprima la
ayuda cuando stdin es una TTY (un host MCP nunca tiene TTY). Se descarta porque el modo de fallo
si la heurística se equivoca es peor que el problema que arregla —un host con stdin de tipo pty
se quedaría sin servidor MCP—, y es exactamente la clase de suposición «lo moderno es mejor» que
provocó el incidente de los hooks. En su lugar, cuando stdin es una TTY se imprime **por stderr**
una línea de aviso antes de arrancar el servidor, que no cambia ningún comportamiento.
