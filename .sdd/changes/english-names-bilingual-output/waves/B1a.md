# Ola B1a — El armazón del CLI en dos idiomas

Primer PR de B1, partida en cinco el 2026-10-14 (`waves/B1-proposal.md`, «Decisiones aprobadas»;
plan, «#### B1», partición). Rama `sdd/english-names-b1`, sobre `origin/main` `3492ba5`. Sin
commit ni push: los hace la sesión principal.

- **REQ:** 021 (CLI salvo `benchmark` y llama-swap de B1c), 026 (números del CLI), 034 (humo en
  inglés del CLI), 045 (salen seis ficheros de `uncatalogued_pending/cli.json`) y D8 entero
  (parche, `argparse.json`, `test_argparse_msgids_covered` y `cli-python-matrix`).
- **Resultado:** suite **2794 passed, 2 skipped** con `LANG=en_US.UTF-8` y con `LANG=es_ES.UTF-8`
  (antes 2739 en `main`), las dos con `xdist` (`-n 4 --dist loadgroup`); los tests del CLI en verde
  en Python 3.11, 3.12, 3.13 y 3.14; `ruff check` y `ruff format --check` limpios; detector de
  nombres del frente A **0 fuera de la lista y 0 sin clasificar**; guardián de textos en verde;
  12 controles positivos, los 12 disparan el assert esperado.

## Qué se hizo

| Fichero | EOL | Cambio |
| --- | --- | --- |
| `src/local_delegate/resources/i18n/{es,en}/cli.json` (nuevos) | LF | 241 claves por idioma: ayudas (`cli.help.*`, 104), `install`/`update`/`uninstall` de `cli.py` (`cli.install.*`), `test-window`, `recompute-cost`, presupuesto de llama-swap, `llamaswap residency`, daemon, avisos de alias (`cli.deprecations.*`) y el aviso de terminal de `entrypoint` |
| `src/local_delegate/resources/i18n/{es,en}/argparse.json` (nuevos) | LF | 45 msgid: la unión de los de Python 3.11 a 3.15 (39, 40, 44, 34 y 34; `evidence/B1a/argparse-msgids-*.txt`) |
| `src/local_delegate/cli.py` | CRLF | todo texto por `t()` (179 apariciones del guardián, incluidas las 57 de `install`/`update`/`uninstall`, decisión 1); `_argparse_in_language()` instala `argparse._` y `argparse.ngettext` alrededor de `run()` y los restaura en `finally`; números con `i18n.format_number`; la pregunta `[s/N]` acepta `s`, `si`, `sí`, `y`, `yes` y en inglés dice `[y/N]`; el metavar `ID=RUTA[:VRAM_GB]` también se traduce; la constante `_RESIDENCY_HELP` pasa al catálogo |
| `src/local_delegate/i18n.py` | LF | `format_number(value, decimals=0, *, language=None, machine=False)`: `20.027`/`1,5` en español, `20,027`/`1.5` en inglés; `decimals=None` como `:g`; `machine=True` sin separador de miles y con punto, para B2 (desviación registrada, decisión 3) |
| `src/local_delegate/recompute.py` | LF | `summary_text` con frases enteras del catálogo y conteos con `format_number`; los cuatro diccionarios de rótulos apuntan a claves (`cli.recompute_cost.{status,verdict,match,discard}.*`) |
| `src/local_delegate/test_windows.py` | LF | los 16 errores y motivos de ilegible por el catálogo |
| `src/local_delegate/deprecations.py` | LF | `warning_text` y `parse_version` por el catálogo, con `import i18n` diferido (`config` importa este módulo e `i18n` importa `config`) |
| `src/local_delegate/daemon.py` | LF | los cuatro mensajes de consola (incluido «ya hay un daemon de este usuario», que el guardián no veía por ir en `_console_print`) |
| `src/local_delegate/entrypoint.py` | CRLF | el aviso de terminal interactiva |
| `tests/test_cli_english.py` (nuevo) | LF | 50 casos: msgid del argparse en ejecución, ayuda española sin armazón inglés (16 rutas), ayuda inglesa sin palabras distintivas del catálogo español ni tildes (15 rutas), restauración del parche (también tras un error), errores en los dos idiomas, humo en inglés de doce salidas con su guarda de camino, control positivo permanente en español, y números |
| `tests/test_smoke.py` | CRLF | dos asserts pasan del armazón inglés al español («uso: local-delegate», «opción no válida»): la suite corre en español (REQ-043) |
| `.github/workflows/ci.yml` | LF | trabajo `cli-python-matrix`: ubuntu, `python: ["3.11", "3.12", "3.13", "3.14", "3.15"]`, `fail-fast: false`, `uv sync --group dev`, sin Playwright, `test_cli_english.py` y `test_cli_renamed_names.py` |
| `scripts/ci_gate.py` | LF | cuatro celdas en `EXPECTED_JOBS` (3.11–3.14) y `PYTHON_WITHOUT_WHEELS = {"3.15": …}` con fecha y motivo |
| `tests/test_ci_gate.py` | LF | la coherencia resta las celdas sin wheels; tres tests nuevos: toda exclusión es una celda viva con motivo y no está en los esperados; la matriz empieza en el `requires-python`; los clasificadores de `pyproject.toml` son las celdas que bloquean |
| `pyproject.toml` | CRLF | clasificador 3.14 (decisión 8; 3.15 no, porque no se instala) |
| `tests/data/uncatalogued_pending/cli.json` | LF | salen `cli.py`, `daemon.py`, `deprecations.py`, `entrypoint.py`, `recompute.py` y `test_windows.py` (cada uno tenía apariciones antes; ahora, cero) |
| `tests/data/uncatalogued_exceptions.json` | LF | `sí` en `cli.py`, `machine_name`: es la respuesta que escribe la persona, no salida |
| `rename-exceptions.md` | LF | sale la fila `sin_cruce` de `recompute.py`; entra `recalcular-coste` en `tests/test_cli_english.py` (alias, el humo prueba su aviso en inglés) |
| `scripts/data/spanish_lexicon.json` | LF | 21 palabras inglesas nuevas (`callable`, `subparsers`, `uninstalling`…), mismo formato |

Tamaño: ~610 líneas nuevas en 5 ficheros (catálogos y test) y +850/−420 en 15 existentes. La
propuesta estimaba ~216 textos más ~45 msgid: salieron 241 claves (la tabla del guardián contaba
apariciones, y varias frases repetidas comparten clave mientras otras se partieron en dos, como
`clients_auto` y `clients_auto_none`) y 45 msgid.

**Tests que afirmaban decimales («8.37 GiB»):** cero en el alcance de B1a (búsqueda de
`[0-9]\.[0-9]+ GiB|Presupuesto|NO CABE|cabe con|peor caso` en `tests/`: solo comentarios y asserts
de palabras). Los decimales de `residency.py` y `llamaswap_config.py` llegan con B1c.

## Controles positivos

Cada mutante se aplicó al fichero, se corrió su test, se anotó el assert y se restauró el fichero
(sha256 igual antes y después, en el log). Salida completa: `evidence/B1a/mutants.log`.

| Mutante | Test | Assert que dispara |
| --- | --- | --- |
| M1 borrar `argparse.usage` del catálogo inglés | `test_argparse_msgids_covered` | `msgid de argparse sin clave en argparse.json: ['usage: ']` |
| M2 `run()` sin el parche | `test_help_in_spanish_has_no_english_frame[root]` | `assert 'uso: local-delegate' in 'usage: local-delegate …'` |
| M3 el parche no se restaura | `test_the_patch_is_restored` | `assert <function argparse_gettext> is <function gettext>` |
| M3 con la suite entera y `xdist` | toda la suite | solo los dos tests de restauración fallan (2792 passed): hoy ningún otro test depende del idioma de argparse, y son esos dos los que lo vigilan |
| M4 una ayuda sin catálogo (español literal) | `test_help_in_english_has_no_spanish_catalog_text[test-window]` | `texto español en la ayuda inglesa: ['abre', 'ahora', 'empieza', …]` |
| M5 separadores españoles cambiados por los ingleses | `test_number_format[es-20027-0-20.027]` | `assert '20,027' == '20.027'` |
| M6 el modo máquina se ignora | `test_machine_numbers_have_no_separators_in_any_language[es]` | `assert '20.027,5' == '20027.5'` |
| M7 el resumen de `recompute-cost` sin `format_number` | `test_a_real_cli_output_uses_the_language_separators[es-20.027]` | `assert ': 20.027 (' in '… Transcripts leídos: 20027 …'` |
| M8 una salida de `test-window` en español literal | `test_smoke_in_english` | la guarda de camino: `assert ('added' in 'w-… añadida')` |
| M8b `"abierta"` literal en vez de `t(...)` | `test_smoke_in_english` (el guardián **pasa**: una palabra ASCII en minúscula no es texto para él) | `AssertionError: list: ['abierta']` |
| M9 `3.16` en la matriz sin su celda esperada | `test_the_expected_jobs_are_exactly_those_of_ci_yml` | `assert {…'cli-python-matrix (3.16)'…} == {…}` |
| M10 `print("Hola")` en `cli.py` | `test_no_uncatalogued_text_outside_pending` | `Texto para personas fuera del catálogo …` |

M8b es el caso de la pregunta 10 de la propuesta: el residuo que el guardián no ve lo caza el humo
en inglés.

## Corridas

| Corrida | Resultado | Log |
| --- | --- | --- |
| Suite, `LANG=en_US.UTF-8`, `-n 4 --dist loadgroup`, bajo `pesado.sh` | 2794 passed, 2 skipped, 4 warnings (`DeprecationWarning` de starlette, ya existente) | `evidence/B1a/suite-runs.txt` |
| Suite, `LANG=es_ES.UTF-8`, igual | 2794 passed, 2 skipped, 4 warnings | `evidence/B1a/suite-runs.txt` |
| `test_cli_english.py` + `test_cli_renamed_names.py` en venvs aparte con Python 3.12, 3.13 y 3.14 (`uv sync --frozen`) | 71 passed en cada una | `evidence/B1a/suite-runs.txt` |
| `uv sync --group dev --python 3.15 --frozen` | falla al **instalar**: `pyyaml` 6.0.3 y `pydantic-core` 2.46.4 no tienen wheel cp315 y su compilación falla | `evidence/B1a/uv-sync-3.15.txt` |
| `ruff check .` y `ruff format --check .` | limpios | — |
| Detector de nombres con `rename-exceptions.md` | 0 fuera de la lista, 0 sin clasificar | — |
| Guardián, paridad, `test_ci_gate`, `test_detect_spanish_names`, `test_language` | 225 passed | — |

**Python 3.15.** Salió el 2026-10-09 (python.org). En esta PC `uv` solo instala la 3.15.0a7, así que
la comprobación local es con la alfa; el fallo es de instalación (sin wheel de dos dependencias
del lock), que es el único caso que admite la política de D8. **Pendiente para el CI del PR:**
confirmar en el log de la celda `cli-python-matrix (3.15)` que falla en «Sync deps» y no en un
test; si pasa entera, la 3.15 sale de `PYTHON_WITHOUT_WHEELS`, entra en `EXPECTED_JOBS` y en los
clasificadores en el mismo PR.

**Limitación (plan §4.2):** en Windows `LANG` no decide el idioma; las dos corridas no
discriminan por `LANG`. Sí discriminan los tests nuevos, que fijan `LOCAL_DELEGATE_LANG` en cada
caso.

## Revisión a mano de la salida inglesa (decisión 10)

Volcados: `evidence/B1a/english-help.txt` (ayuda de las 16 rutas) y
`evidence/B1a/english-smoke.txt` (quince salidas reales: `test-window` entero, `recompute-cost`, el
alias viejo, errores de `init-llamaswap`, `check-llamaswap`, `install`, opción desconocida y
subcomando no válido). Leídos enteros:

- Sin español salvo la línea de `benchmark` en la ayuda raíz («Ejecuta el corpus v2 …»), que es de
  B1c; por eso la ayuda raíz solo se comprueba en español en este PR.
- Valores de máquina intactos: subcomandos, opciones, `choices`, `--json`, ids de ventana, fechas
  ISO 8601.
- Ajustes hechos al revisar el borrador de `local_translate`: «vigía» salía como *bastion* (queda
  *watch*), «descargar modelos» como *download* (queda *unload*), `{why}` salía traducido como
  *Why* y varias frases con mayúscula inicial que el original no tiene.
- La leyenda de estados de `install` dice `[FALT]` también en inglés: los rótulos de estado son de
  `checks.py` (B1b), que cambiará los dos a la vez a `[MISS]`.

## Desviaciones

- **`format_number` en `i18n.py`** (fichero de B0), aprobada como decisión 3; con modo máquina
  para B2.
- **Fuente del catálogo:** el escáner del guardián y no `evidence/i18n-inventory.csv`, que es
  anterior al renombrado (aprobado con la propuesta, sección 1.1).
- **`tests/test_smoke.py`** (fuera de la lista de B1a): dos asserts del armazón inglés pasan al
  español; consecuencia directa del parche.
- **Léxico congelado:** 21 palabras inglesas nuevas, como en B0a y B0b.
- **Clasificador 3.15:** no se añade aunque la matriz la corra, porque el paquete no se instala en
  ella; lo exige `test_the_classifiers_are_the_blocking_cells_of_the_matrix`.
- **`judged` y `outside` del cotejo:** con `None` se imprimía `None`; ahora `0`.

## Pendientes para B1b y siguientes

- B1b: `[FALT]` → `[MISS]` en inglés en `checks.STATUS_LABEL` y en la leyenda `cli.install.report.status_legend`;
  `doctor._GROUP_HEADINGS` (lo usa `_scaffold_report` de `cli.py`); borrar
  `uncatalogued_pending/doctor.json` y que el guardián exija solo los pendientes de olas abiertas.
- B1c: la ayuda de `benchmark` y, con ella, la ayuda raíz en inglés en `test_cli_english.py`
  (`HELP_PATHS`); `llamaswap_api.OUTCOME_TEXT`, `residency.UNKNOWN` y
  `residency.CHANGE_DURING_EDIT`, que `cli.py` ya imprime a través del catálogo pero vienen en
  español de sus módulos; `est.detail`/`est.method` de `llamaswap_config`.
- CI del PR: la celda 3.15 («Corridas»).

## Llamadas `local_*`

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente B1 (fase 1) | `local_summarize(path=waves/B0a.md)` y `local_summarize(path=waves/B0b.md)` | desviaciones y pendientes de B0 |
| Agente B1 (fase 1) | `local_explain_code(path=cli.py)` | mapa del parser (truncó a 20 de 63 kB; el mapa se terminó con `grep`) |
| Agente B1a | `local_translate(path=tr_in_0..4.txt)` ×5 | borrador inglés de las 240 frases de `cli.json`, por lotes de 50; revisado entero («Revisión a mano») |
| Agente B1a | `local_lint_summary(path=suite_es.txt)` | resumen de la corrida en español: solo las 4 `DeprecationWarning` de starlette |
| Agente B1a | `local_commit_msg(path=b1a.diff)` | borrador del commit; salió de una línea («feat(i18n): internacionalizar CLI, daemon y recompute»), así que el mensaje final se redactó a mano |

## Llamadas `mcp__pycharm__*`

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente B1a | ninguna | motivo: no hubo renombrados de símbolos; los cambios fueron reemplazos exactos por script, cada uno con su conteo de coincidencias comprobado, y las referencias se verificaron con `ruff check .` y la suite entera en los dos `LANG` |
