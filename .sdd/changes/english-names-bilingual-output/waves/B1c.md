# Ola B1c — llama-swap y `benchmark` en dos idiomas

Tercer PR de B1 (`waves/B1-proposal.md`, «Decisiones aprobadas»; plan, «#### B1», partición).
Rama `sdd/english-names-b1c`, sobre `origin/main` `90f0780` (B1b mezclada como #312). Sin commit ni
push: los hace la sesión principal.

- **REQ:** 021 (salidas de `llamaswap residency`, de la vigía y de `benchmark`, y la ayuda de
  `benchmark` y la raíz), 026 (GiB con coma decimal en español y punto en inglés en el CLI), 034
  (humo en inglés de lo que imprimen estos módulos) y 045 (salen del guardián los siete módulos de
  la ola).
- **Resultado:** suite **2834 passed, 2 skipped** con `LANG=en_US.UTF-8` y con `LANG=es_ES.UTF-8`
  (antes 2814), las dos con `-n 4 --dist loadgroup`; `ruff` limpio; guardián de textos en verde;
  detector de nombres del frente A **0 fuera de la lista y 0 sin clasificar**, corrido al final,
  después de escribir los tests; 10 controles positivos, los 10 disparan el assert esperado.

## Qué se hizo

| Fichero | EOL | Cambio |
| --- | --- | --- |
| `src/local_delegate/resources/i18n/{es,en}/cli.json` | LF | 169 claves nuevas por idioma: `cli.residency.*` (errores de la edición, vista, cambios del `--dry-run`, `--pin`), `cli.llamaswap_api.*` (salidas de la vigía, negativas, errores del daemon y de llama-swap), `cli.topology.*` (errores de forma y de `load.go`, y `cli.topology.reason.*`), `cli.llamaswap_config.*` (detalle del estimador), `cli.turn.*`, `cli.benchmark.*` y `cli.help.benchmark.*`. Solo añadidos: ninguna clave existente cambia |
| `src/local_delegate/residency.py` | LF | todo texto por `i18n.t`; `_gib` usa `format_number(value, 2)` (antes fijaba la coma); `error_yaml(who, e)` recibe `yaml`/`config`/`copy` y no un trozo de frase; salen `UNKNOWN`, `CHANGE_DURING_EDIT` y `TTL_ZERO_EXPLANATION` (el CLI usa sus claves); las frases por trozos (`no cabe como residente`, `--none necesita --ttl`, la cabecera de cada cambio) son una entrada entera con marcadores. Aquí `t` es un parámetro (el texto del YAML), así que se llama siempre `i18n.t` |
| `src/local_delegate/topology.py` | LF | errores de forma y de `load.go` por el catálogo; `reason_text(reason)` dice un motivo de REQ-002 en el idioma vigente. **Los motivos (`NO_CONFIG`…) no cambian**: son valores de máquina (ver «Desviaciones») |
| `src/local_delegate/llamaswap_api.py` | LF | `OUTCOME_TEXT` pasa a `OUTCOMES` (los valores del JSON del daemon) y `outcome_text(outcome)`; negativas en singular y plural con una clave cada una (antes `_plural` pegaba trozos); los segundos con `format_number(…, None)`. Las frases del log de llama-swap (`PHRASE_*`) se quedan tal cual |
| `src/local_delegate/llamaswap_config.py` | LF | detalle del estimador con `format_number(…, 2)` («8,37» / «8.37»; antes salía con punto también en español), `extra_missing()` en lugar de `_EXTRA_INSTALL_MSG` (lo usan `residency` y `topology`) |
| `src/local_delegate/turn.py` | LF | los cinco errores de invariante por el catálogo (`from .i18n import t`) |
| `src/local_delegate/benchmark.py` | LF | errores del corpus, mensajes de `run_benchmark` y la ayuda del subcomando por el catálogo; `error` del JSONL como valor de máquina (`unexpected_response: <tipo>`, `null_content`) |
| `src/local_delegate/cli.py` | CRLF | `llamaswap_api.OUTCOMES`/`outcome_text`, `cli.residency.unknown_delegations` y `cli.residency.changed_during_edit`, y `topology.reason_text` en `cli.residency.unreadable` |
| `src/local_delegate/checks.py` | LF | `doctor` dice los motivos de REQ-002 con `topology.reason_text` (residencia y turno) |
| `tests/test_llamaswap_english.py` (nuevo) | LF | 16 casos (ver «Controles positivos») |
| `tests/test_cli_english.py` | LF | `benchmark` entra en `HELP_PATHS` y la ayuda raíz se comprueba también en inglés |
| `tests/test_doctor_english.py` | LF | salen de `PENDING_FRAGMENTS` «sin residente (recomendado)» y «el daemon no responde»; «sin LLAMASWAP_CONFIG» se queda, ahora por `chains.py` (B2) |
| `tests/test_llamaswap_api.py` | LF | `outcome_text()` en vez del diccionario |
| `tests/test_no_uncatalogued_text.py` | LF | clase de excepción `verbatim` (`PROSE_KINDS`) y su test |
| `tests/data/uncatalogued_exceptions.json` | LF | 16 excepciones `verbatim` (ver «Desviaciones») |
| `tests/data/uncatalogued_pending/cli.json` | LF | salen los siete módulos de la ola; quedan los tres scripts de B1d |
| `scripts/data/spanish_lexicon.json` | LF | 8 palabras inglesas: `addend`, `garbled`, `heads`, `may`, `outcomes`, `such`, `unfinished`, `verbatim` |

Los textos de `matrix.py` eran todos entradas congeladas del corpus de afinidad: no se tocan
(excepciones `verbatim`).

## Controles positivos

Cada mutante se aplicó, se corrió su test, se anotó el assert y se restauró el fichero (sha256 igual
antes y después; el script comprueba además que el mutante cambia el fichero). Log:
`evidence/B1c/mutants.log`.

| Mutante | Test | Assert que dispara |
| --- | --- | --- |
| N1 un error de `topology` en español literal | `test_the_b1c_outputs_in_english_have_no_spanish` | `AssertionError: topology: ['del', 'grupo', 'miembro', 'modelo', 'ningun']` |
| N2 `_gib` con la coma fija de antes | `test_gib_use_the_language_separators[en-8.38 GiB]` | `assert '8,38 GiB' == '8.38 GiB'` |
| N3 `reason_text` devuelve el valor de máquina | `test_reason_text_says_the_reason_in_the_language[en-…]` | `assert 'sin LLAMASWAP_CONFIG' == 'no LLAMASWAP_CONFIG'` |
| N4 el valor de máquina del motivo traducido | `test_machine_values_do_not_change_with_the_language[es]` | `assert 'no LLAMASWAP_CONFIG' == 'sin LLAMASWAP_CONFIG'` |
| N5 `doctor` imprime el motivo crudo | `test_doctor_says_the_reason_in_english` | `assert 'no turn: no LLAMASWAP_CONFIG (according to' in …` |
| N6 un texto de `residency.py` fuera del catálogo | `test_no_uncatalogued_text_outside_pending` | `residency.py:420 [context] 'no hay bloque de grupos donde crear el nuevo'` |
| N7 la clase `verbatim` deja de admitir prosa | `test_text_exceptions_are_live_and_machine_text` | `llamaswap_api.py: 'reloading configuration': es texto para personas, no una excepción` (y las otras 15) |
| N8 una ayuda de `benchmark` en español literal | `test_help_in_english_has_no_spanish_catalog_text[benchmark]` | `texto español en la ayuda inglesa: ['salida']` |
| N9 la salida de la vigía, cruda | `test_outcome_text_in_both_languages[es-recargó]` | `assert 'reloaded' == 'recargó'` |
| N10 el `error` del JSONL vuelve al español | `test_benchmark_writes_machine_errors_in_the_jsonl` | `assert 'respuesta inesperada: TypeError' == 'unexpected_response: TypeError'` |

`test_the_b1c_outputs_in_english_have_no_spanish` lleva su control positivo permanente (las mismas
salidas en español sí tienen palabras distintivas) y guardas de camino (cada salida es la que se
quería: la vista con residentes, el `--pin` que no cabe, las negativas en singular y plural, el
nodo en estilo flujo, el error de `turn`).

## Corridas

| Corrida | Resultado | Log |
| --- | --- | --- |
| Suite, `LANG=en_US.UTF-8`, `-n 4 --dist loadgroup`, bajo `pesado.sh` | 2834 passed, 2 skipped, 4 warnings (`DeprecationWarning` de starlette, ya existente) | `evidence/B1c/suite-runs.txt` |
| Suite, `LANG=es_ES.UTF-8`, igual | 2834 passed, 2 skipped, 4 warnings | `evidence/B1c/suite-runs.txt` |
| `ruff check .` y `ruff format --check .` | limpios (208 ficheros) | — |
| Detector de nombres con `rename-exceptions.md`, al final | 0 fuera de la lista, 0 sin clasificar (tras las 8 palabras del léxico) | — |
| Grafo de imports del paquete (todos, también los diferidos) | un solo ciclo, `checks → update → checks`, que ya estaba en `main`; B1c no añade ninguno (`topology → llamaswap_config → i18n` no vuelve) | — |
| Globales e imports sin usar en lo tocado | `ruff` (F401) limpio; salen `_plural`, `OUTCOME_TEXT`, `UNKNOWN`, `CHANGE_DURING_EDIT`, `TTL_ZERO_EXPLANATION` y `_EXTRA_INSTALL_MSG` sin referencias que queden | — |

## Revisión a mano de la salida inglesa (decisión 10)

Volcados hechos dentro de la suite, con el entorno doblado (`real_daemon_down` autouse; ninguna
llamada a `127.0.0.1` fuera de ella): `evidence/B1c/smoke_{en,es}.txt` (vista de residencia con y
sin residentes, `--pin` que no cabe, negativas, salidas de la vigía, errores de topología, motivos,
detalle del estimador, nodo en estilo flujo, error de `turn`, `benchmark --help` y la ayuda raíz).
Leídos enteros:

- Sin español ni tildes en inglés; los números con punto decimal («10.29 + 9.88 … 6.17 GiB short»)
  y con coma en español («10,29 + 9,88 … faltan 6,17 GiB»).
- Se quedan igual en los dos idiomas los valores de máquina: `swap`, `exclusive`, `persistent`,
  `TTL`, `mmproj`, `preload` (claves del YAML de llama-swap), opciones, ids de modelo y de grupo,
  y la frase de llama-swap que cita la vigía («reloading configuration»).
- Ajustes al borrador de `local_translate`: «vigías» salía como *watchers* (queda *watches*, como
  en B1a), «foto `inflight`» como *photo* (queda *snapshot*), «reserva» como *reservation* (queda
  *reserve*), «plaza» como *space* (queda *slot*), «residencia» como *residence* (queda
  *residency*), «se descarga» como *downloaded* (queda *unloaded*), «fusión de mapas» como *map
  fusion* (queda *map merge*), «ilegible» como *illegible* (queda *unreadable*),
  `LLAMASWAP_CONFIG` reescrito como `LLAMA-SWAP_CONFIG`, `fuentes/` traducido como `/sources/`
  (es una carpeta del corpus: se queda), «Gib» por «GiB», «x1,2» por «x1.2» en inglés, el
  `{package}` puesto en lugar de «PyYAML», «no selected case», «a state that does not
  understand», y la ayuda de `benchmark` en imperativo («Run…») cuando las demás de la raíz van en
  tercera persona («Runs…», «Checks…»).

## Desviaciones

- **Clase de excepción `verbatim` en el guardián** (`tests/test_no_uncatalogued_text.py`, de B0b):
  el guardián rechazaba cualquier excepción con prosa, y B1c tiene texto que se compara, se hashea
  o se ejecuta tal cual contra algo de fuera y que traducir rompería: las cuatro frases del log de
  llama-swap que busca la vigía, las siete entradas congeladas del corpus de afinidad de
  `matrix.PROMPT_INPUTS` (su sha256 es la huella de las celdas aprobadas), los dos motivos de
  REQ-002 con dos palabras (`dos sintaxis`, `no cumple load.go`), el arnés Python de `benchmark` y
  los dos nombres de contador de `typeperf`. `verbatim` admite prosa pero exige motivo; un test lo
  prueba y el mutante N7 lo vigila. **Para revisar en la sesión principal:** es una regla nueva del
  guardián; B1d (las expresiones regulares de `pair_sheet`) puede necesitarla.
- **Los motivos de REQ-002 se quedan como valores de máquina en español** (`sin LLAMASWAP_CONFIG`,
  `dos sintaxis`…): viajan en `turn_reason` de `GET /api/llamaswap/status` y
  `checks._no_turn_is_fine` los compara entre procesos (un daemon y un `doctor` con idiomas
  distintos tienen que entenderse). Se dicen con `topology.reason_text`. Pasarlos a inglés sería un
  cambio de contrato del daemon, de los que hizo el frente A; no se hace aquí.
- **`chains.py` y `server.py` (B2) siguen imprimiendo el motivo crudo** («sin residente (no se
  sabe: sin LLAMASWAP_CONFIG)», «Turno: no (…)»). Por eso «sin LLAMASWAP_CONFIG» se queda en
  `PENDING_FRAGMENTS` de `test_doctor_english.py`, apuntando a `topology.py`; B2 tiene que llamar a
  `topology.reason_text` y quitarlo.
- **`error` del JSONL de `benchmark`** pasa de «respuesta inesperada: X» y «content nulo» a
  `unexpected_response: X` y `null_content`, como `http_500`: es un valor de máquina escrito en un
  fichero, y con `t()` dependería del idioma. Ningún lector lo interpreta (`analyze_benchmark` no lo
  usa); las filas ya escritas se quedan como están (REQ-033). El `TypeError("message no es un
  objeto")`, que nunca se mostraba, desaparece: la comprobación devuelve el error directamente.
- **`checks.py`** (de B1b) y **`cli.py`** (de B1a): solo para usar `reason_text`, `OUTCOMES`,
  `outcome_text` y las claves de `residency` que salieron del módulo.
- **Acentos en el catálogo español de `benchmark`** («inválido», «ningún», «análisis»…): el módulo
  era ASCII; los textos de `topology` se dejan tal cual estaban («raiz», «validos», «ningun») porque
  hay tests que los buscan.

## Pendientes para B1d y siguientes

- B1d: los tres scripts (`measure_cooldown.py`, `analyze_benchmark.py`, `pair_sheet.py`), que son
  lo único que queda en `uncatalogued_pending/cli.json`; al vaciarse, la superficie `cli` pasa a
  `CLOSED_SURFACES`.
- B2: `chains.residents_text()` y el «Turno: no (…)» de `local_status` con `topology.reason_text`, y
  quitar «sin LLAMASWAP_CONFIG» de `PENDING_FRAGMENTS`; el motivo `server.NO_TURN_REMOTE_BACKEND`
  necesita su propio texto (`reason_text` lo deja pasar tal cual).
- Fuera de B1: `tests/fake_llamaswap.py` lleva sus propias etiquetas en español de las salidas de
  la vigía (es un doble de prueba, no imprime a nadie), y `benchmark._HARNESS` tiene nombres de
  variable en español dentro del código que ejecuta (excepción `verbatim`).

## Llamadas `local_*`

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente B1c | `local_translate(path=tr_in_0..2.txt)` ×3 | borrador inglés de las 169 claves, por lotes de 60; revisado entero («Revisión a mano») |
| Agente B1c | `local_lint_summary(path=b1c_suite_en.txt)` | resumen de la corrida en inglés: solo las 4 `DeprecationWarning` de starlette |
| Agente B1c | `local_commit_msg(path=b1c.diff)` | borrador del commit (ver `waves/B1c-commit-msg.txt`, redactado a mano sobre él) |

## Llamadas `mcp__pycharm__*`

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente B1c | ninguna | motivo: no hubo renombrados de símbolos con referencias repartidas; los cambios fueron reemplazos exactos por script con su conteo de coincidencias (cada reemplazo exige una sola), las referencias a lo que salió (`OUTCOME_TEXT`, `UNKNOWN`, `_EXTRA_INSTALL_MSG`…) se buscaron en `src/`, `tests/` y `scripts/`, y todo se verificó con `ruff check .` y la suite entera en los dos `LANG` |
