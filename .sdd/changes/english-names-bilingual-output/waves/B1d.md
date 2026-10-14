# Ola B1d — los tres scripts en dos idiomas

Cuarto PR de B1 (`waves/B1-proposal.md`, «Decisiones aprobadas»; plan, «#### B1», partición).
Rama `sdd/english-names-b1d`, sobre `origin/main` `5c7e275` (B1c mezclada como #313). Sin commit ni
push: los hace la sesión principal.

- **REQ:** 021 (salidas y ayudas de `measure_cooldown.py`, `pair_sheet.py` y `analyze_benchmark.py`,
  con el armazón de argparse de D8), 026 (números con los separadores del idioma en lo que lee una
  persona; fechas en ISO 8601 UTC), 034 (humo en inglés de los informes y de la hoja) y 045 (se
  cierra la superficie `cli`: se borra `uncatalogued_pending/cli.json`); decisión 7 de B1 (`pair_sheet`
  escribe `tie` y lee `empate` para siempre).
- **Resultado:** suite **2848 passed, 2 skipped** con `LANG=en_US.UTF-8` y con `LANG=es_ES.UTF-8`
  (antes 2834), las dos con `-n 4 --dist loadgroup`; `ruff` limpio; guardián de textos en verde con
  `cli` en `CLOSED_SURFACES`; detector de nombres del frente A **0 fuera de la lista y 0 sin
  clasificar**, corrido al final, después de escribir los tests; 11 controles positivos, los 11
  disparan el assert esperado.

## Qué se hizo

| Fichero | EOL | Cambio |
| --- | --- | --- |
| `src/local_delegate/resources/i18n/{es,en}/cli.json` | LF | 251 claves nuevas por idioma bajo `cli.script.*`: `measure_cooldown` (informe, reglas de P-4, ayuda), `pair_sheet` (hojas `.md` de P-15 y de commit, textos de la página, errores, ayuda, «puedes parar»/«sigue») y `analyze_benchmark` (informes de `decide` y `cp3`, tabla del veredicto, motivos de §6/§7, `NoData`, ayuda). Solo añadidos |
| `scripts/script_i18n.py` (nuevo) | LF | el catálogo para los scripts que **no** importan el paquete (ver «Desviaciones»): `lang()` con `hook_common.resolve_language` cargado por ruta, `t`, `t_lang`, `format_number` y `argparse_in_language()`, todo con la biblioteca estándar |
| `scripts/measure_cooldown.py` | LF | `report(m)` arma el informe por el catálogo (antes, `print` por línea); `RULES` guarda claves y `rule_text()` las dice; enteros con `format_number`; la hora del informe en ISO 8601 UTC (`2026-10-14T18:27Z`); el `--json` no cambia (`(todo)` y `(ahora)` siguen siendo sus marcadores, y el informe los dice con `all`/`now`) |
| `scripts/pair_sheet.py` | LF | hojas `.md` (P-15 y commit) y página HTML en el idioma del proceso; el lector acepta las dos formas (`## Par`/`## Pair`, `Mejor`/`Better`, `Inventa`/`Invents`, `Lo principal`/`Main point`, `Específico`/`Specific`, `Hoja:`/`Sheet:`, `[opcional]`/`[optional]`, `s/n`/`y/n`; valores `si`, `sí`, `yes`, `y`, `parcial`, `partial`, `empate`, `tie`, `=`); `unblind --json` escribe `tie` (`HUMAN_TIE`) en `human`; `can_stop` devuelve `CAN_STOP`/`GO_ON` y `stop_text()` los dice; la página recibe sus textos en un `<script id="textos">` y el `logica` no cambia (lo prueba node) |
| `scripts/analyze_benchmark.py` | LF | todo por el catálogo; `pairs_for_role` suma `tie` y `empate`; `_fmt` con `format_number`; los valores de máquina (`criterion`, motivos de CP-3, `report` del veredicto, `state`) no cambian y el informe los dice con `_label()`; el orden de los tipos de caso ya no depende de la traducción (`_kind_order`) |
| `tests/test_scripts_english.py` (nuevo) | LF | 14 casos (ver «Controles positivos») |
| `tests/test_pair_sheet.py` | LF | `human` es `{"tie": 2}`; `_stopped` compara el texto de `stop_text(can_stop(...))` |
| `tests/conftest.py` | LF | la fixture que olvida el idioma también reinicia `script_i18n` si algún test lo cargó |
| `tests/test_no_uncatalogued_text.py` | LF | `CLOSED_SURFACES = {"doctor", "cli"}` |
| `tests/data/uncatalogued_pending/cli.json` | — | borrado (quedan `hooks`, `install`, `mcp` y `panel`, de B2–B5) |
| `tests/data/uncatalogued_exceptions.json` | LF | 10 excepciones: 6 `verbatim` de `analyze_benchmark` (valores de `criterion`, motivos de CP-3 y `report` de `verdict.json`) y la plantilla HTML de `pair_sheet` (`verbatim`); `sí` y dos expresiones regulares de `pair_sheet` (`machine_name`) |
| `scripts/data/spanish_lexicon.json` | LF | 11 palabras inglesas: `badly`, `defect`, `downloaded`, `grew`, `inc`, `lowercase`, `nodata`, `replacements`, `some`, `unmeasured`, `you` |
| `rename-exceptions.md` | LF | las 7 filas de «Entrada de interfaz escrita por una persona» pasan a «Lectura de formato viejo» (la sección queda vacía, con su nota); 13 filas nuevas: 9 de `tests/test_scripts_english.py` (la hoja, la clave, las respuestas y las reglas congeladas) y 4 de `analyze_benchmark.py` (`calidad`, `techo`, `velocidad`, `empate`: valores de `criterion` de `decide --json`) |

`scripts/medir_enfriamiento.py` no se toca (excepción registrada): sigue llamando a
`measure_cooldown.main()` con las opciones viejas, y sus tests (`test_the_old_options_translate_to_the_new_ones`,
`test_the_documented_p4_command_still_works`, `test_the_old_wrapper_prints_the_same_report_with_the_spanish_result`)
pasan en las dos corridas.

## Controles positivos

Cada mutante se aplicó, se corrió su test, se anotó el assert y se restauró el fichero (sha256 igual
antes y después; el script comprueba que el mutante cambia el fichero). Log: `evidence/B1d/mutants.log`.

| Mutante | Test | Assert que dispara |
| --- | --- | --- |
| M1 el lector deja de aceptar «empate» | `test_the_frozen_spanish_sheet_is_read_with_the_process_in_english` | `SystemExit: pair 04: the value 'empate' is not valid for preference (accepts A, B, =)` |
| M2 `unblind` vuelve a escribir `empate` en `human` | `test_pair_sheet.py::test_unblind_writes_the_json_for_decide_only_with_the_whole_sheet` | `assert {'empate': 2} == {'tie': 2}` |
| M3 `analyze` deja de leer `empate` | `test_analyze_reads_tie_and_the_old_word` | `assert (4, 1, 2) == (4, 1, 5)` |
| M4 el lector de la hoja `.md` solo entiende español | `test_an_english_sheet_is_read_with_the_process_in_spanish` | `assert ['par 01: inventa A', …] == []` |
| M5 `script_i18n` con el idioma fijo | `test_script_i18n_gives_the_same_as_the_package[en]` | `assert 'es' == 'en'` |
| M6 `measure_cooldown` sin separador de miles | `test_the_reports_in_english_have_no_spanish` | `assert 'Delegations:               20,027' in …` |
| M7 un texto de `pair_sheet.py` fuera del catálogo | `test_no_uncatalogued_text_outside_pending` | `scripts/pair_sheet.py:1291 [context] 'ok: hoja completa'` |
| M8 la página siempre en español | `test_the_page_follows_the_language[en-…]` | `AssertionError: lang="en"` |
| M9 `_fmt` vuelve al punto decimal fijo | `test_the_same_reports_in_spanish_do_trip_the_detector` | `assert '\| x \| 1,000 \| 0,500 \| -0,500 \| 0,125 \| si \|' in …` |
| M10 el título de CP-3 en español literal | `test_the_reports_in_english_have_no_spanish` | `AssertionError: cp3: ['contra']` |
| M11 los scripts sin el parche de argparse | `test_the_argparse_frame_of_the_scripts_follows_the_language[es-…]` | `AssertionError: usage: measure_cooldown.py read-commit …` |

`test_the_reports_in_english_have_no_spanish` lleva su control positivo permanente (los mismos
informes en español sí tienen palabras distintivas y coma decimal) y guardas de camino.
`test_the_frozen_spanish_sheet_is_read_with_the_process_in_english` usa los ficheros reales del corpus
congelado (`hoja-1.md`, `clave-1.json`, `respuestas-1.json`, `reglas.json`): rellena la hoja española
con «si», «no», «parcial» y «empate» (control: dos preferencias son `empate`), la lee con el proceso
en inglés y comprueba que da el mismo juicio que las respuestas de la página.

## Corridas

| Corrida | Resultado | Log |
| --- | --- | --- |
| Suite, `LANG=en_US.UTF-8`, `-n 4 --dist loadgroup`, bajo `pesado.sh` | 2848 passed, 2 skipped, 4 warnings (`DeprecationWarning` de starlette, ya existente) | `evidence/B1d/suite-runs.txt` |
| Suite, `LANG=es_ES.UTF-8`, igual | 2848 passed, 2 skipped, 4 warnings | `evidence/B1d/suite-runs.txt` |
| `ruff check .` y `ruff format --check .` | limpios (210 ficheros) | — |
| Detector de nombres con `rename-exceptions.md`, al final | 0 fuera de la lista, 0 sin clasificar | — |
| Ciclos de imports | ninguno nuevo: `script_i18n` solo importa la biblioteca estándar y carga `hook_common` por ruta; ningún módulo del paquete importa los scripts | — |
| Globales e imports sin usar en `scripts/` y `tests/` tocados | `ruff` (F401) limpio; un script que cuenta las referencias de cada nombre de módulo de los cuatro scripts en `scripts/` y `tests/` no encuentra ninguno sin usar (salen `_RESULT_LABELS`, `_VERDICT_LABELS`, `_QUESTION_LABELS`, `_INSTRUCTIONS`, `_KIND_LABELS`, `_PAIRS_VERDICT_LABELS`, `_CP3_REASON_LABELS` y `_STATE_LABELS`, sin referencias que queden) | — |

## Revisión a mano de la salida inglesa (decisión 10)

Volcados dentro de la suite (entorno doblado, sin daemon): `evidence/B1d/smoke_{en,es}.txt` (informe de
`measure_cooldown`, `cp3`, tabla del veredicto, «puedes parar», hoja `.md` de commit, cabecera y
textos de la página, y las ayudas de los tres scripts). Leídos enteros:

- Sin español ni tildes en inglés; números con coma en español (`20.027`, `1,000`, `R: 0,75`) y con
  punto en inglés; fechas en ISO 8601 UTC.
- El armazón de argparse sale en el idioma vigente («uso:»/«usage:») en los tres scripts.
- Se quedan igual: opciones, subcomandos, `--json` (claves y valores de máquina: `criterion`,
  motivos de CP-3, `state`, `report`, los marcadores `(todo)`/`(ahora)`), nombres de fichero del
  corpus (`fuentes/`) y los valores de las respuestas en el JSON de la página (`s`, `n`, `p`).
- Ajustes al borrador de `local_translate`: «puntuación» salía como *punctuation* (queda *score*),
  «anulada» como *cancelled* (queda *voided*), «vigente» como *current* (queda *incumbent*, como en
  el JSON), «sin base» como *no basis* (queda *no baseline*, como `no_baseline`), «al vencer» como
  *when it won* (queda *when it expired*), «espera INICIO,FIN» como *ignores* (queda *expects*),
  «Tramo» dejado a medias como *Tram*, la ayuda del corpus de P-15 traducida por párrafos sueltos,
  y la mayúscula inicial que el original no tiene en casi todas las líneas. Las claves de
  `pair_sheet` se redactaron a mano directamente en los dos idiomas.

## Desviaciones

- **`scripts/script_i18n.py` en lugar de importar `local_delegate.i18n`** (la propuesta, §1.6, decía
  que los scripts importan el paquete). `pair_sheet.py` y `analyze_benchmark.py` no lo importan a
  propósito (lo dicen sus comentarios: importar `local_delegate` carga `entrypoint` y con él
  `server`), así que leen el mismo catálogo y resuelven el idioma con la misma regla
  (`hook_common`, cargado por ruta como ya hacían con `legacy_names`). `test_script_i18n_gives_the_same_as_the_package`
  y `test_script_i18n_follows_the_language_file_like_the_package` vigilan que no se separen.
  `measure_cooldown.py`, que sí importa el paquete, usa `local_delegate.i18n`.
- **Armazón de argparse en los scripts**: la propuesta no lo pedía para los scripts; se añade con
  `script_i18n.argparse_in_language()` (las mismas claves `argparse.*` de B1a) porque sin él la ayuda
  española salía con «usage:» y «options:».
- **Prosa dentro del `--json` de `decide`** (`reasons`): se redacta en el idioma del proceso. En
  español es **byte a byte la de antes** (se conservan las cadenas sin tilde y los números en formato
  de máquina, y los tests de siempre lo comprueban); en inglés sale en inglés. Las claves y los
  valores de máquina no cambian. **Para revisar en la sesión principal** si el contrato del `--json`
  debe fijar también esa prosa en español.
- **`criterion` de `decide --json`** (`calidad`, `techo`, `velocidad`, `empate`, `techo sin
  medir`) y **`report` de `verdict.json`** (`repetir hoja`…) son valores de máquina en español que el
  frente A no vio (no estaban en claves). No se cambian (contrato); el informe los dice con
  `_label()` y el detector los tiene como «lectura de formato viejo».
- **`can_stop`** devuelve `CAN_STOP`/`GO_ON` en vez del texto; lo que imprime `read-commit --partial`
  sigue siendo «puedes parar»/«sigue» en español.
- **Cadenas de los mensajes de error sin tildes** donde los tests las buscan («valida», «minuscula»,
  «puntuacion», «comparacion», «si»…), para no tocar tests de otras olas; las cadenas nuevas sí
  llevan tilde.
- **`rename-exceptions.md`**: la sección «Entrada de interfaz escrita por una persona» queda vacía,
  con una nota.

## Pendientes para B1e y siguientes

- B1e: el control del detector de idioma (60 + 60 frases) sobre el catálogo ya mezclado.
- B2: `chains.residents_text()` y `server.py` con `topology.reason_text()` (anotado por la sesión
  principal tras B1c).
- Fuera de B1: `tests/fake_llamaswap.py` sigue con sus etiquetas españolas de la vigía (doble de
  prueba), y `scripts/ci_gate.py` tiene `_STATE_LABELS` en español (no es de esta superficie).

## Llamadas `local_*`

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente B1d | `local_translate(path=tr_b1d_0..2.txt)` ×3 | borrador inglés de las 146 claves de `measure_cooldown` y `analyze_benchmark`; revisado entero («Revisión a mano») |
| Agente B1d | `local_lint_summary(path=b1d_suite_es.txt)` | resumen de la corrida en español: solo las 4 `DeprecationWarning` de starlette |
| Agente B1d | `local_commit_msg(path=b1d.diff)` | borrador del commit; salió de una línea y genérico («internationalize benchmark and pair sheet scripts»), el mensaje final se redactó a mano |

## Llamadas `mcp__pycharm__*`

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente B1d | ninguna | motivo: no hubo renombrados de símbolos con referencias repartidas; los cambios fueron reemplazos exactos por script con su conteo de coincidencias, las referencias a lo que salió se buscaron en `scripts/`, `tests/` y `src/`, y todo se verificó con `ruff check .` y la suite entera en los dos `LANG` |
