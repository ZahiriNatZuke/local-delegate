# Ola B1b — `doctor` en dos idiomas

Segundo PR de B1 (`waves/B1-proposal.md`, «Decisiones aprobadas»; plan, «#### B1», partición).
Rama `sdd/english-names-b1b`, sobre `origin/main` `2167b9d` (B1a mezclada como #311). Sin commit ni
push: los hace la sesión principal.

- **REQ:** 022 (títulos, estados, detalles, remedios, cabeceras y resumen de `doctor`; ids y grupos
  sin cambios), 019 (idioma, origen, `language.json` y avisos en la cabecera de `doctor`), 026
  (números de `doctor`), 032 (`test_wiki` contra los títulos españoles del catálogo), 034 (humo en
  inglés de `doctor`), 045 (se cierra la superficie `doctor` y sale `probes.py`) y el remedio de D11.
- **Resultado:** suite **2814 passed, 2 skipped** con `LANG=en_US.UTF-8` y con `LANG=es_ES.UTF-8`
  (antes 2794), las dos con `-n 4 --dist loadgroup`; `ruff` limpio; guardián de textos en verde;
  detector de nombres del frente A **0 fuera de la lista y 0 sin clasificar**, corrido al final,
  después de escribir los tests; 8 controles positivos, los 8 disparan el assert esperado.

## Qué se hizo

| Fichero | EOL | Cambio |
| --- | --- | --- |
| `src/local_delegate/resources/i18n/{es,en}/doctor.json` (nuevos) | LF | 224 claves por idioma: títulos de los 25 checks (`doctor.check.<id>`), estados (`doctor.status.*`: `[FALT]` en español y `[MISS]` en inglés, seis columnas), pistas (`doctor.hint.*`), nombres de producto de los clientes (`doctor.client.*`), cabeceras, leyenda, resumen, línea del idioma y los detalles de cada probe (`doctor.probe.<área>.*`). Todos los valores son cp1252 (la consola de Windows) |
| `src/local_delegate/checks.py` | LF | todo texto por `i18n.t`; `Check.title` pasa a ser la propiedad que traduce `title_key` (el tercer campo; con una clave que no existe devuelve el propio texto, así que `Check("test.broken", "cliente", "roto", …)` de `test_checks.py` sigue valiendo); `STATUS_LABEL` guarda claves y `status_label()` traduce; las pistas con prosa pasan de constantes a funciones (`cli_hint()`, `update_hooks_hint()`, `serve_hint()`, `restart_hint()`, `credential_hint()`, `daemon_token_hint()`, `residency_hint()`, `affinity_hint()`; `INSTALL_HINT` y `RECOMPUTE_HINT`, que solo son comandos, se quedan); `_client_name()` saca «Claude Code», «Codex» y «opencode» del catálogo (el guardián toma «Claude Code» por prosa); frases por trozos reescritas enteras («habla/hablan», « y », « ni ») y conteos con `format_number` |
| `src/local_delegate/doctor.py` | LF | cabeceras de grupo por clave con `group_heading()`, `status_legend()` armada con los mismos rótulos que las líneas, `language_lines()` (REQ-019 y D11), y el resto de la salida por el catálogo |
| `src/local_delegate/probes.py` | LF | motivos de versión no detectada, línea de comparación de versiones y respuestas del sondeo de credencial; el prefijo `[..] componente:` de `_compare_line` se queda (es de máquina: `checks._version_result` lo quita) |
| `src/local_delegate/resources/hooks/hook_common.py` | LF | `LanguageResolution.stored_source` (decisión 5): con origen «preferencia», el origen que `install` guardó en `language.json` si es `variable`, `system` o `fallback`; si no, `None`. Añadido solo ASCII |
| `src/local_delegate/i18n.py` | LF | `catalog()` lee con `read_bytes` y no con `read_text`: `test_checks.py::test_unreadable_file_is_unknown_via_read_helpers` dobla `Path.read_text` y rompía el catálogo |
| `src/local_delegate/cli.py` | CRLF | el reporte de `install` usa `doctor.status_legend()` y `doctor.group_heading()`; `checks.cli_hint()`. Sale la clave `cli.install.report.status_legend` de `cli.json` (la leyenda es una sola, la de `doctor`) |
| `tests/test_doctor_english.py` (nuevo) | LF | 19 casos (ver «Controles positivos») |
| `tests/test_doctor.py`, `tests/test_checks.py` | LF | `group_heading()` en vez del diccionario; las pistas, por sus funciones |
| `tests/test_wiki.py` | LF | compara la tabla de la wiki con `t_lang("es", check.title_key)`: la wiki sigue en español sea cual sea el idioma de la máquina |
| `tests/test_no_uncatalogued_text.py` | LF | `CLOSED_SURFACES = {"doctor"}` (decisión 9): el test exige los pendientes de las superficies abiertas y que ninguna lista esté vacía |
| `tests/data/uncatalogued_pending/doctor.json` | — | borrado; de `cli.json` sale `probes.py` |
| `tests/data/uncatalogued_exceptions.json` | LF | `Claude` (segmento de ruta de Claude Desktop, `path`) y `Authorization` (cabecera HTTP, `machine_name`) en `checks.py` |
| `scripts/data/spanish_lexicon.json` | LF | 4 palabras inglesas: `catalogs`, `export`, `fragments`, `remedy` |

La línea del idioma va en la cabecera, junto a `LLAMASWAP_*`, `Backend BASE_URL` y `HOME` (decisión 4):
`Idioma:           es (preferencia; <ruta de language.json>)`, una línea `aviso:` por cada aviso de
la regla del idioma (textos de `common.language.warning.*` de B0a) y, si lo guardado vino de la
variable, `para volver a seguir al sistema, borra `<ruta>` y ejecuta `local-delegate install``
(D11). No es un check: el total sigue en 25 y el código de salida no cambia.

## Controles positivos

Cada mutante se aplicó, se corrió su test, se anotó el assert y se restauró el fichero (sha256 igual
antes y después). Log: `evidence/B1b/mutants.log`.

| Mutante | Test | Assert que dispara |
| --- | --- | --- |
| N1 `[MISS]` inglés vuelve a `[FALT]` | `test_the_missing_label_is_translated` | `assert ('[MISS]' in "…")` |
| N2 `doctor` sin la línea del idioma | `test_doctor_in_english_has_no_spanish[complete-home]` | `assert ('Language:' in "…")` |
| N3 remedio de D11 con la condición al revés | `test_d11_remedy_when_the_stored_language_came_from_the_variable` | `assert 'para volver a seguir al sistema, borra …' in …` |
| N4 `resolve_language` no informa el origen guardado | `test_resolve_language_reports_the_stored_source[stored0-variable]` | `assert None == 'variable'` |
| N5 título de `es/doctor.json` cambiado sin su fila de la wiki | `test_wiki.py::test_the_doctor_table_lists_every_check` | `comprobaciones sin fila en la wiki: ['versión publicada X']` |
| N6 un detalle de probe en español literal | `test_doctor_in_english_has_no_spanish[complete-home]` | `AssertionError: ['hay', 'prueba', 'ventanas']` |
| N7 el origen del idioma siempre «variable» | `test_doctor_shows_the_preference_and_its_path` | `assert False` (el `startswith("Language:         en (preference; ")`) |
| N8 `Check.title` devuelve la clave sin traducir | `test_the_ids_and_order_do_not_change_with_the_language` | `assert ['doctor.check.cli.path', …] != [ … ]` |

Además, `test_doctor_in_english_has_no_spanish` lleva su control positivo permanente (la misma
salida en español sí tiene palabras distintivas) y la guarda de camino (los dos idiomas corren los
25 checks con el mismo código de salida).

## Corridas

| Corrida | Resultado | Log |
| --- | --- | --- |
| Suite, `LANG=en_US.UTF-8`, `-n 4 --dist loadgroup`, bajo `pesado.sh` | 2814 passed, 2 skipped, 4 warnings (`DeprecationWarning` de starlette, ya existente) | `evidence/B1b/suite-runs.txt` |
| Suite, `LANG=es_ES.UTF-8`, igual | 2814 passed, 2 skipped, 4 warnings | `evidence/B1b/suite-runs.txt` |
| `ruff check .` y `ruff format --check .` | limpios (207 ficheros) | — |
| Detector de nombres con `rename-exceptions.md`, al final | 0 fuera de la lista, 0 sin clasificar | — |
| Grafo de imports (todos, también los de dentro de funciones) desde `i18n`, `config`, `deprecations`, `deprecation_notices`, `checks`, `doctor`, `probes`, `cli` y `hook_common` | un solo ciclo, `checks → update → checks`, que ya estaba en `main` (`checks.py:248` y `:666`, imports diferidos de antes de B1); B1b no añade ninguno | — |
| Globales e imports sin usar en los ficheros tocados | `ruff` (F401) limpio; un script que cuenta referencias de cada nombre de módulo en `src/`, `tests/` y `scripts/` solo encuentra `probes.latest_github`, anterior a B1b y sin tocar | — |

## Revisión a mano de la salida inglesa (decisión 10)

Volcados de `doctor` con el entorno doblado de la suite (`_stub_environment`), en los dos idiomas,
con el HOME completo y vacío: `evidence/B1b/doctor_{en,es}_{complete,empty}.txt`. Leídos enteros:

- Los 25 checks, en el mismo orden y grupo; `[MISS]` en inglés y `[FALT]` en español, también en la
  leyenda y en el resumen.
- Quedan en español cuatro textos que `doctor` imprime pero redactan módulos de olas posteriores:
  `sin residente (recomendado)` (`residency.py`, B1c), `el daemon no responde` (`llamaswap_api.py`,
  B1c), `sin LLAMASWAP_CONFIG` (`topology.py`, B1c) y `sin residente (no se sabe: …)` (`chains.py`,
  B2). `test_doctor_english.PENDING_FRAGMENTS` los aparta de la búsqueda, y
  `test_the_pending_fragments_still_live_in_their_modules` falla en cuanto su ola los traduzca,
  para que salgan de la lista.
- Ajustes al borrador de `local_translate`: «turno del daemon» salía como *shift* (queda *turn*),
  «relleno» como *padding* (queda *backfill*), «andamiaje» como *Scaffold* (queda *Scaffolding*),
  «entrada MCP» como *input* (queda *entry*), la mayúscula inicial que el original no tiene,
  `benchmarks/afinidad-2026-10` traducido (es una ruta: se queda) y «ni … ni» de opencode
  (queda *is in neither {files}*, con `nor` entre los nombres).

## Desviaciones

- **`i18n.py`** (de B0): `catalog()` lee con `read_bytes`. Sin esto, un test que dobla
  `Path.read_text` rompía la lectura del catálogo.
- **`hook_common.py`** (de B0/B3): el campo `stored_source`, aprobado como decisión 5.
- **`cli.py`** (de B1a): el reporte de `install` toma la leyenda y las cabeceras de `doctor`; se
  quita su copia de la leyenda (`cli.install.report.status_legend`).
- **Pistas de `checks.py` de constantes a funciones:** una constante evaluada al importar fijaría
  el idioma de la importación; los tests que las comparaban llaman ahora a la función.
- **Nombres de producto en el catálogo** (`doctor.client.*`), iguales en los dos idiomas: el
  guardián los tomaba por prosa y una excepción con dos palabras corrientes no se admite.
- **`_UNNAMED`** de los clientes observados pasa a una clave interna (`"\0unnamed"`); el rótulo
  «(sin identificar)» sale del catálogo al describirla.
- **Prueba en vivo accidental:** al preparar el volcado, un script fuera de la suite corrió
  `doctor` sin el fixture `real_daemon_down` e hizo un `GET /api/llamaswap/status` de solo lectura
  contra el daemon de esta PC. No escribió nada; los volcados de la evidencia se rehicieron dentro
  de la suite, con el entorno doblado.

## Pendientes para B1c y siguientes

- B1c: `residency.py`, `llamaswap_api.py` y `topology.py`, y con ellos tres de los
  `PENDING_FRAGMENTS` de `test_doctor_english.py`; la ayuda de `benchmark` y la raíz en inglés en
  `test_cli_english.py`.
- B2: `chains.residents_text()` (el cuarto fragmento) y `failures` (detalles y pistas del backend
  que `doctor` imprime tal cual).
- B5: la página de la wiki sobre el idioma (D11), y `install` escribiendo `language.json` con su
  `source`, que es lo que lee `stored_source`.

## Llamadas `local_*`

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente B1b | `local_translate(path=tr_in_0..2.txt)` ×3 | borrador inglés de las 224 claves de `doctor.json`, por lotes de 75; revisado entero («Revisión a mano») |
| Agente B1b | `local_lint_summary(path=suite_en.txt)` | resumen de la corrida en inglés: solo las 4 `DeprecationWarning` de starlette |
| Agente B1b | `local_commit_msg(path=b1b.diff)` | borrador del commit; salió de una línea y genérico («feat(i18n): externalizar textos estáticos y habilitar traducciones»), así que el mensaje final se redactó a mano |

## Llamadas `mcp__pycharm__*`

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente B1b | ninguna | motivo: no hubo renombrados de símbolos con referencias repartidas; los cambios fueron reemplazos exactos por script con su conteo de coincidencias, las referencias a las pistas se cambiaron con búsqueda en `src/`, `tests/` y `scripts/`, y todo se verificó con `ruff check .` y la suite entera en los dos `LANG` |
