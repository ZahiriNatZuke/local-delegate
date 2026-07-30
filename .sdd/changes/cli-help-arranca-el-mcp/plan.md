# Plan de implementación — el CLI responde a `--help`

## Approach

El cambio **quita** una condición, no añade maquinaria. `server.main()` deja de preguntar «¿este
nombre está en mi lista?» y pasa a preguntar «¿hay argumentos?»:

```python
if len(sys.argv) > 1:
    from . import cli
    sys.exit(cli.run(sys.argv[1:]))
```

Con eso, argparse —que ya sabe qué subcomandos existen porque es quien los registra— resuelve
`--help`, `-h`, los subcomandos válidos y los inválidos. La lista literal sobra, y borrarla es lo
que da REQ-006 y REQ-007 gratis: el parser vuelve a ser la única definición de qué comandos hay.

Se conserva intacto el camino sin argumentos, que es el contrato con los hosts MCP. El único
añadido es una línea de aviso por **stderr** cuando stdin es una TTY, que no cambia ningún
comportamiento: el servidor arranca igual, con TTY o sin ella.

Por qué el import de `cli` puede ser incondicional: `cli` importa `llamaswap_config`, y ese módulo
resuelve `import yaml` dentro de un `try/except` dejando `yaml = None`. Sin el extra `[llamaswap]`
el import sigue siendo válido; solo fallan los dos subcomandos que lo usan, al ejecutarse.

## Ordered tasks

1. **`server.main()`: despachar por presencia de argumentos**
   - Ficheros: `src/local_delegate/server.py`
   - Requisitos: REQ-001..REQ-004
   - Contenido: sustituir la condición por `len(sys.argv) > 1`; reescribir el docstring, que hoy
     describe el filtro por lista.
   - Verificación: ejecución real de los cuatro casos + tests
   - Rollback: revertir el bloque (son 3 líneas)

2. **El aviso de TTY**
   - Ficheros: `src/local_delegate/server.py`
   - Requisitos: REQ-005
   - Contenido: antes de arrancar el servidor, si `sys.stdin` existe y `isatty()`, escribir por
     `sys.stderr` una línea sin caracteres fuera de cp1252 (la consola de Windows revienta con una
     flecha `→`, y aquí el destinatario es justamente alguien en una terminal). Envuelto en
     `try/except` porque bajo un host MCP `sys.stdin` puede ser `None` o no tener `isatty`.
   - Verificación: test con stdin doblado en los dos sentidos
   - Rollback: quitar la llamada

3. **Borrar las dos copias de la lista**
   - Ficheros: `src/local_delegate/server.py` (`_CLI_COMMANDS`), `src/local_delegate/cli.py`
     (`KNOWN_COMMANDS`)
   - Requisitos: REQ-006, REQ-007
   - Contenido: eliminar ambas constantes. Comprobar antes que nadie más las lee.
   - Verificación: `grep -rn "_CLI_COMMANDS\|KNOWN_COMMANDS" src/ tests/ docs/ scripts/` sin
     resultados; suite completa en verde
   - Rollback: git

4. **Tests**
   - Ficheros: `tests/test_smoke.py`
   - Requisitos: todos
   - Contenido: cinco tests —`--help` sale 0 e imprime «usage»; subcomando desconocido sale 2;
     subcomando válido delega con el argv correcto (el que ya existe, `test_main_dispatches_known_cli_subcommand`,
     se conserva); sin argumentos **no** llama a `cli.run` y sí llega al arranque del servidor; el
     aviso de TTY aparece solo con `isatty()` verdadero y va a stderr.
     El test del camino sin argumentos dobla `mcp.run` para no arrancar nada de verdad.
   - Rollback: fichero versionado

5. **CHANGELOG**
   - Ficheros: `CHANGELOG.md`, sección `Unreleased`
   - Contenido: entrada de `Fixed` describiendo el síntoma (se colgaba) y el alcance.
   - Verificación: la entrada cae en `Unreleased` y no dentro de una versión publicada; el fichero
     es CRLF y el diff no debe pasar de las líneas añadidas.

## Test strategy

- **Unit:** los cinco tests de `tests/test_smoke.py` descritos arriba, con `monkeypatch` sobre
  `sys.argv`, `cli.run`, `sys.stdin` y `mcp.run`. Ningún test arranca un servidor ni sale a la red.
- **End-to-end manual, en esta máquina:** los cuatro casos por ejecución real contra el repo
  (`uv run python -m local_delegate ...`) comprobando código de salida y stdout/stderr, y **además**
  con el CLI instalado (`local-delegate --help`), que es donde el usuario vio el fallo.
- **Regresión del contrato MCP:** comprobar que el daemon y la entrada `stdio` siguen funcionando;
  el daemon de esta máquina corre por HTTP, así que el camino `stdio` se verifica lanzando el
  binario sin argumentos con stdin cerrado y viendo que sale limpio, como antes del cambio.
- **Seguridad y secretos:** el change no lee ni escribe credenciales ni ficheros del usuario.
- **Checks del proyecto:** los cuatro pasos del CI antes del push (`ruff check .`,
  `ruff format --check .`, `pytest -q` con basetemp propio, y `extract_dashboard_js.py` +
  `node --check`).

## Migration and compatibility

- Aditivo salvo en un caso: `local-delegate <argumento-desconocido>`, que hoy arranca el servidor
  MCP en silencio y pasará a fallar con código 2. Es el arreglo, no un daño colateral.
- Ninguna entrada MCP generada por el instalador pasa argumentos al programa (`install.py:262-284`),
  así que ningún cliente configurado se ve afectado.
- Va a `Unreleased`. Publicar exige confirmación explícita del usuario.

## Plan review

- [x] Cada requisito tiene tarea y verificación (tabla de trazabilidad de la spec).
- [x] El riesgo destructivo real —romper el arranque MCP— tiene test dedicado y rollback de 3 líneas.
- [x] No hay dependencias ni configuración nuevas.
- [x] No entra trabajo ajeno: el ruido de logs 401 y el subcomando `update` quedan fuera por escrito.
