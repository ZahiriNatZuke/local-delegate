# Investigación del repo — SDD `cli-completion`

Fecha: 2026-10-20. Solo lectura sobre `main` (`465fc97`, 0.37.0). Sin usar el MCP `local-delegate`.
Las rutas son relativas a `D:\Projects\local-delegate`.

## 1. Estructura del parser

**Construcción.** Un solo punto: `build_parser()` en `src/local_delegate/cli.py:1334-1521`. Crea el
`ArgumentParser(prog="local-delegate")` (`cli.py:1335-1338`), añade `--version` (`cli.py:1348-1353`)
y el `add_subparsers(dest="command", required=True)` raíz (`cli.py:1355`). Delega en ayudantes:
`benchmark.add_parser(sub)` (`cli.py:1357`, definido en `src/local_delegate/benchmark.py:1477`),
`_add_llamaswap_parser` (`cli.py:1271-1331`, subparsers en 1276), `_add_test_window_parser`
(`cli.py:460-478`, subparsers en 465), `_add_backend_params_parser` (`cli.py:586-602`, subparsers en
588) y `_add_install_parsers` (`cli.py:1610-1693`). `run(argv)` (`cli.py:1713-1716`) envuelve el
parseo en `_argparse_in_language()` (`cli.py:1696-1710`), que parchea `argparse._`/`ngettext` para
traducir el armazón («usage:», errores) y lo restaura al salir.

**Sin efectos secundarios: sí, casi.** `build_parser()` no arranca el MCP, no sale a la red ni lee la
config de llama-swap: solo construye objetos. Lo único que toca disco es la resolución del idioma que
dispara el primer `t()`: `i18n.current()` → `hook_common.resolve_language(config.LOG_DIR)`
(`src/local_delegate/i18n.py:33-36`), que mira `LOCAL_DELEGATE_LANG`, el `language.json` del
directorio de datos y el locale del sistema (`docs/wiki/Language.md:14-22`), y el catálogo
empaquetado (`i18n.py:43-54`). Comprobado por ejecución: un script que recorre
`cli.build_parser()` con el `.venv` imprime el árbol entero sin más efectos.

**Coste de arranque (importa para el diseño).** Importar el paquete ya arrastra el servidor:
`local_delegate/__init__.py:9` importa `entrypoint`, y `entrypoint.py:22` importa `server` (SDK MCP,
`server.py:34-37`) a nivel de módulo. Medido aquí con `-X importtime`: ~0,69 s solo en
`local_delegate.entrypoint`; `local-delegate.exe --version` tarda **0,88-1,08 s** (3 medidas).
Conclusión: completar llamando a Python en cada Tab (estilo `argcomplete`) es inviable, y emitir el
script en cada arranque de shell (`local-delegate completion powershell | Invoke-Expression` en el
perfil) costaría ~1 s por shell. Lo razonable es **script estático** generado una vez (fichero
cacheado o bloque en el perfil) y regenerado por `install`/`update`.

**El cambio previo `cli-help-arranca-el-mcp`** (`.sdd/changes/cli-help-arranca-el-mcp/handoff.md`,
cerrado, PR #63): el despacho es «con argumentos = CLI, sin argumentos = MCP stdio»
(`entrypoint.py:47-66`). Por tanto `local-delegate completion …` va por el parser sin tocar el MCP.
Hay un test que recorre el parser y despacha **todos** los subcomandos registrados
(`tests/test_smoke.py:215-233`): un subcomando nuevo dado de alta en `build_parser` queda cubierto
sin otra lista.

**Inventario (sacado recorriendo el parser en ejecución).** Opciones raíz: `-h/--help`, `--version`.

| Subcomando | Opciones / posicionales | `choices` |
|---|---|---|
| `benchmark` | `--model --label --cases --case --role --input-control --runs --seed --quantization --context-size --n-cpu-moe --load-mode --llama-swap-version --llama-server-version --reasoning-effort --reasoning-budget --endpoint --timeout --sample-interval --probe-process --gpu-luid --output --append --save-responses` (+ `--api-key` oculta) | `--role` = `mechanical long code vision` (`benchmark.py:1491`, `_ROLES` en 1002); `--reasoning-effort` = `off minimal low medium high xhigh max` (`benchmark.py:1522-1527`, 994) |
| `check-llamaswap` | `--config --vram-gb --margin-gb --ram-gb --ram-margin-gb --allow-ungrouped` (`cli.py:1359-1390`) | — |
| `init-llamaswap` | `--config --out --resident --swap --add-model --server-exe --ttl-resident --ttl-swap --vram-gb --margin-gb --ram-gb --ram-margin-gb --store-path --force --dry-run --allow-ungrouped` (`cli.py:1392-1465`) | — |
| `llamaswap residency` | `--config --none --pin --restore --ttl --group --vram-gb --reserve-gb --vram-model --dry-run --now` (`cli.py:1277-1331`; `--none/--pin/--restore` mutuamente excluyentes, 1290) | — |
| `doctor` | `--config --online --home` (`cli.py:1469-1488`) | — |
| `serve` | `--host --port --log-level` (`cli.py:1490-1502`) | `--log-level` = `critical error warning info debug` (1498) |
| `recompute-cost` | `--reset-calibration --claude-dir` (+ `--reiniciar-calibracion` oculta) (`cli.py:1528-1547`) | `--reset-calibration` = `five_hour seven_day` (1531) |
| `test-window start/stop/add/list` | `start --label`; `stop [id]`; `add start end --label`; `list --json` (`cli.py:460-478`) | — |
| `backend-params show/set/unset/reset` | `show --json`; `set role key value`; `unset role key`; `reset [role]` (`cli.py:586-602`) | **ninguno** (ver abajo) |
| `install` | comunes (`--clients --target --home --dry-run --python --no-hooks --no-skill --no-memory --no-mcp --agents --no-client-cli`, `cli.py:1550-1607`) + `--enable-read-hook --mcp-mode --base-url --api-key-env --web-token-env --no-web-token-env --pin-version --force-mcp-codex` (`cli.py:1617-1666`) | `--clients` = `auto claude codex opencode` (1554); `--target` = `claude codex opencode all` (1561); `--mcp-mode` = `stdio http` (1624) |
| `update` | `--dry-run --home --version --restart-backend --no-restart` (`cli.py:1668-1686`) | — |
| `uninstall` | solo las comunes (`cli.py:1688-1693`) | igual que `install` |

Detalles que el generador debe tratar:

- **Opción con valor vs bandera**: `nargs == 0` = bandera (`store_true/false/const`); el resto toma
  valor. Ojo: `update --version` **toma valor** (`cli.py:1675-1679`) mientras que la raíz `--version`
  es una acción `version` sin valor (`cli.py:1348-1353`).
- **Repetibles** (`action="append"`): `--clients`, `--target`, `--role`, `--case`, `--ttl`,
  `--vram-model`, `--add-model`. No hay que dejar de ofrecerlas tras usarlas una vez.
- **Mutuamente excluyentes**: `residency --none|--pin|--restore` (`cli.py:1290`),
  `install --web-token-env|--no-web-token-env` (`cli.py:1640-1655`). Filtrarlas es opcional.
- **`backend-params`: valores fijos que el parser NO declara.** `role` y `key` son posicionales sin
  `choices` (`cli.py:592-597`), aunque la lista cerrada existe: `backend_params.ROLES`
  (`src/local_delegate/backend_params.py:34`) y `ALLOWED_KEYS` (`backend_params.py:77-100`, 21
  claves; `reasoning_effort` con su enumeración `REASONING_EFFORTS`, `backend_params.py:56`). Un
  generador que solo mire `choices` no los verá. Poner `choices=` en el parser **cambiaría** el
  rechazo actual, que tiene textos propios del catálogo (`_BACKEND_PARAMS_REFUSALS`, `cli.py:480-485`:
  `unknown_role`, `unknown_key`…), por un error genérico de argparse. Opción limpia: un atributo
  propio en la `Action` (p. ej. `action.completion_choices = …`) que lea solo el generador. Decisión
  de la spec. El `value` de `set` depende de la clave (bool, enum) — probablemente fuera de alcance.
- **Valores dinámicos**: ids de `test-window stop` (vienen del log), modelos de `--pin`/`--model`,
  grupos, rutas (`--config`, `--home`, `--output`, `--claude-dir`). Los ids y modelos exigirían
  llamar a Python en cada Tab: **fuera de alcance**. Las rutas pueden dejarse al completado de
  ficheros nativo del shell.
- **Opciones sin `help`**: `--quantization`, `--context-size`, `--n-cpu-moe`, `--llama-swap-version`,
  `--llama-server-version`, `--timeout`, `--sample-interval`, `--append` (`benchmark.py:1512-1550`):
  no ocultas, pero sin descripción.
- **Metavar traducido**: `init-llamaswap --add-model` usa `metavar=t(...)` (`cli.py:1411`).

**Ocultos que no deben ofrecerse.**

- `recalcular-coste`: alias viejo sin `help` (`cli.py:1510-1513`), listado en
  `_HIDDEN_COMMANDS` (`cli.py:1525`) y quitado del `metavar` (`cli.py:1519-1520`). Criterio
  mecánico fiable: un subparser cuyo nombre no está en `_SubParsersAction._choices_actions` no tiene
  `help` → oculto (comprobado por ejecución: es el único).
- `--reiniciar-calibracion` (`cli.py:1536-1542`) y `benchmark --api-key` (`benchmark.py:1536`):
  `help=argparse.SUPPRESS`. Filtrar por `action.help == argparse.SUPPRESS`.
- Fuente de verdad de los nombres retirados: `deprecations.py:58-59` (`cli_command`
  `recalcular-coste`, `cli_option` `--reiniciar-calibracion`, retirada en 0.35.0+). `legacy_names.py`
  es lectura dual de datos en disco, no del CLI (`tests/data/uncatalogued_exceptions.json`, entrada de
  `legacy_names.py`).
- `--target` es «histórico» según la wiki (`docs/wiki/Integration-install.md:112`) pero tiene `help`
  y sale en la ayuda: se ofrecería salvo decisión contraria.

## 2. i18n

- Todo texto de salida pasa por `t(key)` (`i18n.py:72-74`) con catálogo JSON plano por idioma y
  superficie: `src/local_delegate/resources/i18n/{es,en}/{argparse,cli,common,doctor,install,mcp,panel,tools}.json`.
  Falta en un idioma → español; falta en los dos → la clave (`i18n.py:64-69`).
- **Los `help=` del parser SÍ pasan por el catálogo** (`t("cli.help.…")` en todo `cli.py:460-1693`
  y `benchmark.py:1477-1556`) y **cambian según el idioma** del proceso. El armazón de argparse
  también (`i18n.argparse_gettext`, `i18n.py:195-212`; catálogo `argparse.json`).
- Consecuencia para el script: si incluye descripciones (PowerShell `CompletionResult` con
  `ToolTip`, zsh `_describe`), saldrán en el idioma de quien lo generó, y quedarían congeladas en el
  fichero/perfil hasta regenerarlo. Alternativas: sin descripciones (bash no las muestra de todos
  modos), o regenerarlas al cambiar de idioma (`install`/`update` ya reescriben cosas en el idioma
  vigente, `install.py:1310-1315`). Decisión de la spec.
- **Guardianes**:
  - `tests/test_no_uncatalogued_text.py`: recorre por AST el paquete y marca literales «para
    personas» en contextos de salida: llamadas `print/write/…` (`:86-88`), argumentos `help=`,
    `description=`… (`:90-104`) y **constantes de módulo con literal** (`:113-115`). `is_human_text`
    (`:133-148`) considera prosa dos o más palabras corrientes: una plantilla de bash/zsh escrita como
    constante Python (`local cur`, `then`, `done`, `compdef`…) **lo dispararía**. Salidas: guardar las
    plantillas como **recursos no Python** (p. ej. `resources/completion/*.ps1|.zsh|.bash`, empaquetados
    porque hatch incluye todo `src/local_delegate`, `pyproject.toml:86-87`) o registrar excepciones
    `verbatim`/`machine_name` en `tests/data/uncatalogued_exceptions.json`.
  - `tests/test_i18n_parity.py`: misma clave en es/en, placeholders iguales, y toda clave literal usada
    en el código existe (`:97`, `:136`).
  - `tests/test_cli_english.py`: la ayuda de cada ruta de `HELP_PATHS` (`:34-56`, **lista a mano**)
    sale sin texto del otro idioma (`:149-172`); `_machine_names()` (`:95-110`) recorre el parser y
    exime nombres de subcomandos/opciones. Hay que añadir `["completion"]` a `HELP_PATHS` (nada lo
    obliga, pero si no la ayuda del subcomando nuevo queda sin vigilar). Lo corre además el job
    `cli-python-matrix` en cada Python admitido (`.github/workflows/ci.yml:232-252`).
  - `tests/test_detect_spanish_names.py:237-247`: cero nombres en español en el repo fuera de la lista
    de excepciones → nombres de código en inglés (`completion`, `powershell`, `zsh`, `bash`).

## 3. `install` / `uninstall` / `update`

**Dónde.** Parser en `cli.py:1550-1693`; orquestación en `_run_install` (`cli.py:189-248`);
traducción de flags a `install.Options` en `_install_options` (`cli.py:88-111`); plan y escritura en
`src/local_delegate/install.py` (`Options` en `install.py:996-1025`, `plan_install` en
`install.py:1304`, `plan_uninstall` en `install.py:1715`, `apply` en `install.py:1880-1901`).

**Cómo se añade un flag.** Dos patrones:
- componente que se excluye: `--no-hooks/--no-skill/--no-memory/--no-mcp` con `dest` y
  `set_defaults(... = True)` (`cli.py:1572-1607`);
- componente opt-in: `--agents` (`store_true`, `cli.py:1593-1601`) con su justificación: «son
  ficheros del usuario, no andamiaje nuestro». El perfil del shell es exactamente eso → encaja con
  **opt-in**. Los componentes se deducen de `_ALL_COMPONENTS` (`cli.py:35`) por `getattr`
  (`cli.py:92`): un componente nuevo ahí entra automáticamente en `install` **y** `uninstall`, porque
  comparten `_add_common_install_args` (`cli.py:1616`, `1692`).
- Flags solo de `install` se leen con `getattr(args, …, default)` (`cli.py:98-103`) y van a campos de
  `Options`.

**Escritura en ficheros del usuario (reutilizable tal cual).**
- Docstring con las garantías: idempotente, reversible, bloques con marcadores, `.bak`
  (`install.py:14-22`).
- Marcadores: `MD_BEGIN/MD_END` = `<!-- local-delegate:begin/end -->` y `TOML_BEGIN/TOML_END` =
  `# local-delegate:begin/end` (`install.py:43-47`). Para un perfil de shell sirve la variante con
  `#` (válida en PowerShell, bash y zsh); conviene un marcador propio (p. ej.
  `# local-delegate completion:begin`) para no chocar con otros usos.
- `upsert_block` (`install.py:285-292`): reemplaza o añade al final, nunca duplica.
  `managed_block` (`install.py:295-299`): lee lo de dentro (sirve para «¿está al día?»).
  `remove_block` (`install.py:417-421`): quita el bloque y los blancos que deja.
- `_write_text` (`install.py:254-259`): crea el directorio, **conserva el fin de línea** del fichero
  (`_detect_newline`, `install.py:240-251`) y deja `.bak` (`_backup`, `install.py:235-237`).
  `_read_text` devuelve `""` si no existe o no es UTF-8 (`install.py:262-266`).
- Ejemplo completo a imitar, instalar: bloque de memoria (`install.py:1397-1421`, con «ya al día» si
  no cambia); desinstalar: `install.py:1775-1791`.
- `Action` con `literal` para que `--dry-run` muestre el texto exacto (`install.py:222-232`,
  `apply` lo imprime en `install.py:1880-1893`).
- El «bloque gestionado que mantiene `local-delegate install`» del `CLAUDE.md` global es este mismo
  mecanismo (`MD_BEGIN/MD_END` sobre `~/.claude/CLAUDE.md`, `install.py:11`, `1399-1421`).

**Trampas de `install` para este cambio.**
- **Sin clientes no se escribe nada**: con `auto` y ningún cliente detectado, `_run_install` sale con
  0 antes de planificar (`cli.py:203-212`). Si el perfil del shell es un componente más, en una
  máquina sin Claude/Codex/opencode no se instalaría. Hay que decidir si el autocompletado depende de
  los clientes (no debería).
- `--home` simulado: `is_simulated_home` (`install.py:150-161`) apaga lo global. El perfil de
  PowerShell vive en `Documents\PowerShell\…` (aquí: `C:\Users\Yohan\Documents\PowerShell\Microsoft.PowerShell_profile.ps1`,
  medido con `pwsh -NoProfile -c $PROFILE`), y `Documents` puede estar redirigida (OneDrive), así que
  no siempre es `home/Documents`. Con `--home` habría que derivar la ruta del HOME simulado; sin él,
  preguntar a la carpeta conocida o a `pwsh`. Windows PowerShell 5.1 usa otro perfil
  (`Documents\WindowsPowerShell\…`). zsh: `$ZDOTDIR/.zshrc` o `~/.zshrc`; bash: `~/.bashrc` (en macOS
  las shells de login leen `~/.bash_profile`).
- Codificación: `_write_text` escribe UTF-8 sin BOM; un perfil con BOM lo conserva porque se lee como
  `\ufeff` y se reescribe. Si el bloque es ASCII puro, Windows PowerShell 5.1 (que lee sin BOM como
  ANSI) no tiene problema. Conviene un test.

**`update`.** `src/local_delegate/update.py`: mira con `checks.run_all`, decide con la tabla
`REPAIRS` (`update.py:154-221`) y arregla llamando a `install.plan_install` por par
(componente, cliente) (`update.py:274-330`), con deduplicación (`update.py:332`). Solo repone lo que
un check marca `missing`/`warn` (`update.py:288-291`), y opciones de la instalación previa se
**infieren** del disco (p. ej. `enable_read_hook=install.read_hook_registered(...)`,
`update.py:309`) — así se cerró el fallo de «`update` no reponía los hooks» (hooks viejos en `warn`,
comentario en `update.py:158-162`). Para el autocompletado: si el script queda congelado en el perfil
o en un fichero, un subcomando nuevo en una versión futura no aparecerá hasta regenerarlo. Opciones:
(a) un check `scaffold.completion` (`warn` si el bloque difiere del generado) + entrada en `REPAIRS`
reparando solo si el bloque ya existe (opt-in inferido del disco, como el hook de lectura); o
(b) que `update` lo regenere siempre que encuentre el marcador. (a) arrastra la tabla de la wiki
(ver §7).

## 4. Entry points

- `pyproject.toml:71-75`: **dos ejecutables** al mismo `local_delegate:main`: `local-delegate-mcp`
  (para `uvx local-delegate-mcp`) y `local-delegate` (alias corto).
- `local_delegate/__init__.py:9` reexporta `entrypoint.main`; `__main__.py` permite
  `python -m local_delegate` (`src/local_delegate/__main__.py:1-8`); `entrypoint.main()`
  (`entrypoint.py:47-66`) despacha a `cli.run(sys.argv[1:])` si hay argumentos.
- En esta PC, `uv tool` deja `local-delegate.exe` y `local-delegate-mcp.exe` en `~/.local/bin`
  (comprobado con `ls`). Para PowerShell: `Register-ArgumentCompleter -Native -CommandName` debería
  cubrir `local-delegate`, `local-delegate.exe` y, si se decide, `local-delegate-mcp(.exe)`. El
  `prog` del parser es siempre `local-delegate` (`cli.py:1336`). En zsh/bash, `compdef`/`complete`
  sobre `local-delegate` (y el alias si se decide).

## 5. Tests y CI

- **Patrón de tests de subcomandos**: llamar a `cli.run([...])` con `capsys` y `monkeypatch`, p. ej.
  `tests/test_cli_backend_params.py:37-40`, `tests/test_test_windows_cli.py`,
  `tests/test_residency_cli.py`. Idioma: `monkeypatch.setenv("LOCAL_DELEGATE_LANG", ...)`
  (`test_cli_backend_params.py:32-34`). Ayuda en los dos idiomas: `tests/test_cli_english.py`.
- **Aislamiento de entorno**: `tests/conftest.py:23-47` borra todas las variables del paquete
  (`config.ENVIRONMENT_VARIABLES`, alimentada por las lecturas reales de `config.py`) y fija
  `LOCAL_DELEGATE_LANG=es`; `conftest.py:49-62` aísla `LOG_DIR` por test y resetea el idioma. Los
  guardianes del inventario están en `tests/test_environment_isolation.py:21-38` (el nombre viejo
  `test_aislamiento_entorno.py` ya no existe). Si el cambio lee variables nuevas (p. ej. `ZDOTDIR`,
  que no es del paquete), no entran en ese inventario: los tests deben fijarlas con `monkeypatch`.
- **HOME simulado**: `make_home` (`conftest.py:231`) y `snapshot` (`conftest.py:332`) para comparar
  antes/después de `install`/`uninstall`.
- **E2E del instalador**: `scripts/check_install_e2e.py` corre `python -m local_delegate install`
  dos veces y `uninstall` contra un HOME temporal y verifica idempotencia y reversibilidad
  (`check_install_e2e.py:1-17`, `41-49`, `80+`). Lo ejecuta el CI en los **tres sistemas**
  (`.github/workflows/ci.yml:177-179`). Es el sitio natural para «instalado en el perfil» con perfil
  temporal.
- **CI** (`.github/workflows/ci.yml`): `lint` en ubuntu (`:27`); `test` en matriz
  `ubuntu-latest, windows-latest, macos-latest` (`:131-133`) con `pytest -n auto --dist loadgroup` y
  `timeout-minutes: 10` (`:159-161`); `test-lang-es` en ubuntu con locale español (`:186-220`);
  `cli-python-matrix` (`:232-252`); wheel limpio + handshake (`:267-288`). Los límites de tiempo
  están atados a `tests/test_ci_gate.py:324-368`: añadir un paso nuevo con su propio
  `timeout-minutes` no rompe ese test, pero cambiar el del paso `Tests (pytest)` sí.
- **Shells en los runners** (no verificado desde aquí; según las imágenes de GitHub, a confirmar en el
  primer run): ubuntu-latest trae `bash` y `pwsh`, **no `zsh`** (haría falta `apt-get install zsh`);
  macos-latest trae `zsh`, `pwsh` y **bash 3.2** (sin `compopt`, sin `mapfile`: el script bash debe
  ser compatible); windows-latest trae `pwsh`, Windows PowerShell 5.1 y Git Bash, sin `zsh`. En esta
  PC: `pwsh` 7.6.6, Windows PowerShell 5.1 y Git Bash 5.3; **no hay `zsh`** (la prueba zsh real será
  en CI macOS o en la Mac del usuario).
- Ningún test actual lanza `pwsh`/`bash` para probar completado; el precedente de lanzar PowerShell
  es `tests/fake_llamaswap.py:141`.

## 6. Documentación a tocar

- `README.md` (CRLF): «Instalación rápida» (`README.md:32`) y la sección de integración
  (`README.md:298`); el detalle de `install` se remite a la wiki (`README.md:66`).
- `docs/wiki/Integration-install.md` (CRLF): tabla de «Opciones» (`:105-123`) para el flag nuevo de
  `install`, «Qué instala» (`:20`) y «Garantías» (`:52`) si el perfil pasa a ser algo que instala.
  Es la página que documenta `install`/`uninstall`; no hay una página de «CLI» general (índice en
  `docs/wiki/Home.md:10-11`). El subcomando `completion` podría ir ahí o en una sección nueva; si se
  crea una página, `tests/test_wiki.py:123` exige enlazarla desde el índice.
- `docs/wiki/Language.md` si las descripciones del script dependen del idioma.
- `CHANGELOG.md` (LF): `## [Unreleased]` vacío en `CHANGELOG.md:7`.
- Fines de línea: `cli.py`, `install.py`, `README.md` y la wiki en CRLF; `CHANGELOG.md`,
  `tests/test_cli_english.py`, `scripts/check_install_e2e.py` y los JSON del catálogo en LF
  (`git ls-files --eol`).

## 7. Guardianes que obligan a registrar el subcomando en otros sitios

- **Ninguna lista literal de subcomandos que lo exija**: `tests/test_smoke.py:215-233` asegura que
  no existen `KNOWN_COMMANDS`/`_CLI_COMMANDS` y despacha todo lo registrado.
- `tests/test_cli_english.py:34-56` `HELP_PATHS`: lista a mano; no falla si falta, pero hay que
  añadir `["completion"]` para que la ayuda nueva quede vigilada en los dos idiomas.
- `tests/test_i18n_parity.py`: cada clave nueva (`cli.help.completion…`, mensajes de `install`) en
  `es` y `en`, en el fichero de su superficie (`:97-105`).
- `tests/test_no_uncatalogued_text.py`: plantillas de shell como constantes Python → excepción o
  recursos aparte (§2).
- `tests/test_detect_spanish_names.py:237-247`: nombres de código en inglés.
- Si se añade un check de `doctor`: `tests/test_wiki.py:219-262` compara la tabla del doctor de
  `Integration-install.md` con el registro real y el número de checks escrito en palabras
  (`_CHECK_COUNT_WORDS`, `test_wiki.py:36+`); habría que tocar la tabla y la cifra. Más
  `tests/test_doctor*.py` y `tests/test_checks.py`.
- Si el autocompletado es un componente de `_ALL_COMPONENTS`: `update.install_options`
  (`update.py:224-234`) pasa `components=set()` y la deduplicación de `REPAIRS` por `(kind, target)`
  (`update.py:332`) obliga a un `kind` de `Action` distinto (p. ej. `profile`) para no colisionar con
  `markdown`/`toml`.
- `scripts/check_install_e2e.py` cuenta hooks con `EXPECTED_HOOKS = len(install._HOOK_EVENTS)`
  (`:38`): no se rompe por un componente nuevo, pero es donde añadir la verificación del perfil.

## Riesgos y preguntas abiertas

1. **Script congelado vs versiones nuevas.** Con un script estático (obligado por el ~1 s de arranque,
   §1), un subcomando nuevo no se completa hasta regenerar. ¿Lo regenera `update` siempre que vea el
   marcador, o vía check `warn` + `REPAIRS` (más coste en wiki y tests)?
2. **Bloque en el perfil vs fichero aparte.** ¿El bloque contiene el script entero, o solo una línea
   que carga un fichero generado (p. ej. en el directorio de datos)? Con fichero aparte el perfil
   cambia una vez y `update` solo reescribe el fichero; con script entero no hay fichero huérfano
   tras `uninstall`.
3. **Descripciones e idioma.** Los `help` dependen del idioma (§2): ¿se incluyen? Si sí, quedan en el
   idioma de quien generó.
4. **Valores de `backend-params`.** No hay `choices` en `role`/`key`: ¿atributo propio en la `Action`
   o fuera de alcance? No poner `choices=` (cambiaría los rechazos traducidos).
5. **Ruta del perfil de PowerShell**: `Documents` redirigible; pwsh 7 vs Windows PowerShell 5.1
   (¿uno, los dos, o el de quien ejecuta?); `--home` simulado. zsh con `ZDOTDIR`; bash en macOS
   (`.bash_profile`) y bash 3.2.
6. **`install` sin clientes sale antes** (`cli.py:203-212`): el autocompletado no debería depender
   de que haya Claude/Codex/opencode.
7. **Opt-in y qué shell**: ¿`--shell-completion powershell|zsh|bash|auto`? `auto` exige detectar la
   shell (en Windows, PowerShell; en macOS, `$SHELL`). `uninstall` debe quitar el bloque aunque no se
   pase la opción (como `remove_block` es inocuo si no está, se puede hacer siempre).
8. **Nombres del ejecutable**: ¿registrar también `local-delegate-mcp`? (`pyproject.toml:74-75`).
9. **CI**: `zsh` no está en ubuntu ni en windows; la prueba zsh instalada solo en macOS. Los tests de
   integración con shells reales deben saltarse con motivo cuando la shell no exista, pero el CI de
   cada sistema debe tener al menos una que no se salte (si no, el control no discrimina).
10. **Probar «instalado» en PowerShell** requiere invocar el completer real
    (`TabExpansion2` sobre una línea) con `-NoProfile` y cargando el perfil temporal a mano, sin tocar
    el `$PROFILE` real del usuario (brief).

---

Procesos: no dejé nada vivo; solo lancé comandos cortos en primer plano (`python`, `pwsh -c`,
`--version`). El script auxiliar temporal que usé para recorrer el parser ya está borrado.
