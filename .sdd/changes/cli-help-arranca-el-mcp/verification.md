# Verificación — el CLI responde a `--help`

## Environment

- Revisión base: `620a585` (`main`, limpia), rama de trabajo `fix/cli-help-no-arranca-el-mcp`
- Windows 11, Python 3.11 (`.venv` del repo) y Python 3.12 en el CLI instalado con `uv tool install`
- 322 tests, 1 skip (antes del change: 316)

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | `python -m local_delegate --help < /dev/null` | **OK** | exit 0, `usage: local-delegate [-h] {benchmark,check-llamaswap,init-llamaswap,doctor,serve,install,uninstall}` por stdout, **0 bytes** en stderr |
| REQ-002 | `python -m local_delegate doctro` | **OK** | exit 2, stderr: `error: argument command: invalid choice: 'doctro'`; termina solo, no espera en stdin |
| REQ-003 | `python -m local_delegate doctor --home <vacío>` | **OK** | exit 0, diagnóstico impreso; test `test_main_dispatches_known_cli_subcommand` (preexistente) sigue verde |
| REQ-004 | binario sin argumentos con stdin **por tubería** | **OK** | exit 0, 0 bytes en stderr, el servidor arrancó y salió al EOF — igual que antes del change |
| REQ-005 | `_aviso_de_terminal_interactiva()` con stdin doblado | **OK** | con `isatty()` falso: stderr vacío. Con verdadero: la línea con `local-delegate --help`, y **stdout limpio** |
| REQ-006 | `grep -rn "_CLI_COMMANDS\|KNOWN_COMMANDS" src/ tests/ docs/ scripts/` | **OK** | sin resultados; test `test_los_subcomandos_estan_definidos_una_sola_vez` asserta que ninguno de los dos atributos existe |
| REQ-007 | recorrer `build_parser()` y despachar cada subcomando registrado | **OK** | los 7 nombres del parser llegan a `cli.run` sin estar dados de alta en ningún otro sitio |

### Los tests se verificaron al revés

Reintroducido el filtro por lista literal en `server.main()`, **4 tests fallan**:
`test_main_dispatches_known_cli_subcommand`, `test_help_imprime_la_ayuda_y_no_arranca_el_servidor`,
`test_subcomando_desconocido_falla_en_vez_de_colgarse` y
`test_los_subcomandos_estan_definidos_una_sola_vez`.

El de `--help` falla con su propia aserción (`--help no debe arrancar el servidor MCP`), no por
reventar arrancando un servidor de verdad: el doble sobre `mcp.run` funciona.

### Hallazgo por ejecución: `/dev/null` en Windows no sirve para probar el caso del host MCP

La primera verificación de REQ-004 se hizo con `< /dev/null` y **el aviso de TTY salió igual**, que
era justo lo contrario de lo esperado. Causa: Git Bash traduce `/dev/null` a `NUL`, que en Windows
es un **dispositivo de carácter**, así que `sys.stdin.isatty()` devuelve `True` —comprobado
directamente: `NUL isatty = True`—. Un host MCP no redirige desde `NUL`, usa una tubería; repetida
la prueba con una tubería real, stderr queda en 0 bytes. Queda escrito en el docstring de
`_aviso_de_terminal_interactiva` para que nadie lo tome por un fallo del criterio.

## Quality checks

- [x] `uv run ruff check .` — All checks passed
- [x] `uv run ruff format --check .` — 48 files already formatted
- [x] `uv run pytest -q --basetemp=<temp propio>` — 322 passed, 1 skipped
- [x] `extract_dashboard_js.py` + `node --check` — OK
- [x] Sin secretos: el change no lee ni escribe credenciales, ficheros del usuario ni variables de
      entorno.
- [x] Sin cambios ajenos: el diff toca `server.py`, `cli.py`, `tests/test_smoke.py` y `CHANGELOG.md`.
      Los terminadores de línea se conservaron (`git diff --stat` acotado a las líneas del cambio).

## Deviations and residual risk

- **Un cambio de comportamiento deliberado:** `local-delegate <argumento-desconocido>` pasa de
  arrancar el servidor MCP en silencio a fallar con código 2. Es el arreglo. Ninguna entrada MCP
  generada por `install.mcp_entry` pasa argumentos al programa (modo `stdio`: los argumentos son de
  `uvx`), así que ningún cliente configurado se ve afectado.
- **Se añadió algo fuera de la lista de tareas del plan:** la descripción del parser, que decía que
  el CLI era solo para los groups de llama-swap. Es la primera línea que lee quien por fin consigue
  que `--help` funcione; dejarla mintiendo era entregar el arreglo a medias.
- **Fuera de alcance, anotado:** las líneas `HTTP Request: ... 401` que salen cuando el servidor sí
  arranca son logging de `httpx2` a nivel INFO. Ya no aparecen en `--help`, pero siguen ensuciando
  el arranque legítimo. Va al backlog.
- **Sin cubrir:** el comportamiento en una terminal real de macOS/Linux (el aviso de TTY). Se cubre
  con doble y con el razonamiento del `isatty`, que no es específico de plataforma; el riesgo es
  cosmético porque va por stderr y no altera el arranque.
