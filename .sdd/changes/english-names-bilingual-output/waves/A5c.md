# Ola A5c — Precios, densidad, `resources/datos/`, vigilante y `vendor.json` (`precios`→`pricing`)

- Rama: `sdd/english-names-a5c` · PR: (lo abre la sesión principal) · Commit(s): (pendiente; borrador en `waves/A5c-commit-msg.txt`, firmado y sin coautoría), encima de `7b5761c` (A5b-2)
- Quién: un agente hizo el mapping (fase 1) y, tras la aprobación de la sesión principal con las respuestas 1-9, lo aplicó (fase 2): renombrados, ficheros, claves, consumidores, tests, docs, evidencias, este registro y el borrador del commit.
- REQ cubiertos: REQ-005 (ficheros del paquete con claves en inglés, sin lectura doble porque viajan con su lector), REQ-009 (campos de `/api/stats` y `/api/events` que salen de las tablas, con su JS y la paridad node) y REQ-014 (control de `scripts/check_vendor.py` y `scripts/vigilante_precios.py` con corrida mínima)
- Ficheros poseídos (plan.md A5c): `precios.py`→`pricing.py`, `resources/datos/`→`resources/data/` con `precios.json`→`prices.json` y `densidad.json`→`density.json`, `resources/vendor/vendor.json`, `scripts/vigilante_precios.py` (solo claves y ruta), `.github/workflows/vigilante-precios.yml`, `scripts/check_vendor.py`, `.github/workflows/vendor-audit.yml` (sin cambio), `pyproject.toml` (sin cambio: hatch empaqueta `src/local_delegate` entero), y los tests `test_vigilante.py`, `test_vendor.py` (CRLF), `test_precios.py` y `test_densidad.py`. Tocados fuera de la lista, aprobados en el mapping como consecuencia mecánica: ver «Desviaciones»
- EOL: `evidence/A5c/eol-check.txt` sobre todo el diff (25 entradas, con los tres `git mv`): 0 diferencias (sí). Siguen en CRLF `web/metrics.py` y `tests/test_vendor.py`; los JSON y el resto, en LF
- Mapping: `waves/A5c-mapping.csv` aprobado (`# approved-by-main`), 124 filas; filas `pycharm` 25 = filas `rename_refactoring` 25 (tras el ajuste de método registrado en la cabecera del CSV y en «Desviaciones»); filas `search_edit` 99, cada una con su motivo (variables locales con `make_mapping.py apply`, el módulo por `git mv` y script por tokens, y las filas a mano de ficheros, claves, valores, vigilante, workflows y empaquetado)
- Tests recogidos: antes 2555 → después 2556 (+1, −0): `test_panel_coste.py::test_families_are_said_in_words`
- Suite: `evidence/A5c/pytest-full.log` (con `pesado.sh`), resultado verde (2554 pasan, 2 saltados; 1 aviso de Starlette ya conocido). Después de la suite solo cambiaron registros y evidencias de `.sdd/` y el método de 8 filas del CSV: el árbol de código es el de `evidence/A5c/diff.patch`
- `ruff check src tests scripts` y `ruff format --check src tests scripts`: limpios (183 ficheros)
- Detector (`evidence/A5c/detector-after.json`): hallazgos únicos 7559 → 7385 (−174); nombres en español únicos 4179 → 4140 (−39); ficheros con hallazgos 165 → 155. Ya no queda ningún `json_key` ni `json_value` en español en `src/**/resources`, ni hallazgos en `pricing.py`, `check_vendor.py`, `cost.py` y `transcripts.py`. Sube en 1 `js_identifier` (`FAMILIA`, el diccionario de rótulos nuevo del panel, igual que `DESCARTE`: lo renombra A8b)

## Qué se hizo

- **Módulo `pricing`.** `git mv precios.py pricing.py` y 12 renombrados con PyCharm (`CHECK_FIELDS`, `MIN_JUDGED_COST`, `_DATE_SUFFIX`, `_read_table`, `load_prices`, `load_density`, `normalize_id`, `entry`, `family`, `_judge`, `check_rows`, `verdict`); variables locales con `make_mapping.py apply` (46 reemplazos); imports y `precios.<attr>` por script de tokens en los 8 ficheros que importan el módulo, más las dos cadenas de `monkeypatch.setattr`. `transcripts` usa `pricing.CHECK_FIELDS` directamente: el alias `CHECK_FIELDS` desaparece (respuesta 8).
- **Tablas del paquete.** `git mv` de `resources/datos/` a `resources/data/` y de los dos JSON a `prices.json` y `density.json`. Claves de `prices.json`: `_note`, `source`, `consulted`, `web_search_per_1000`, `models`, y por modelo `input`, `cache_read` (respuesta 4), `output`, `family` y `supports_effort`; `w5m` y `w1h` no cambian. Claves de `density.json`: `_note`, `measured_on`, `families`, `measured_with`, las columnas `unnumbered` y `read_format` y las clases `prose`, `code` y `structured` (`log` y `diff` ya eran inglés). Familias `new` y `previous` (respuesta 2). La nota `_note` sigue en español y cita los nombres nuevos.
- **Pendientes cedidos por A5a y A5b.** La clave `modelo` de `transcripts.cost_state` pasa a `model` (en memoria; no se persiste). `check_rows` responde `inside|outside|unpriced` y `verdict` `pass|fail`, así que `recompute._check` guarda `pricing.verdict(results)` sin traducir y desaparece `_VERDICT_VALUES`; la tabla `cost_aggregates_check` de `legacy_names` se queda para leer el `coste-agregados.json` viejo. La clase sin extensión conocida pasa de `otro` a `other`. `cost-aggregates.json` no cambia de formato (`verdict` ya era `pass|fail`; `table_version` es una fecha).
- **Consumidores.** `cost.py` (clases, columnas, familia por defecto `new`, `families`/`measured_with`), `transcripts.py` (precios y `supports_effort`), `attribution.py` (`supports_effort`), `valuation.py` (`cache_read`, `consulted`, `source`), `recompute.py` (`consulted`, resultados del cotejo) y `web/metrics.py` (import y comentario de `density_table`).
- **Panel.** `textoCoste` dice las familias con el diccionario `FAMILIA = {new:'nueva', previous:'anterior'}` (respuesta 3): el panel nunca enseña `new`/`previous` crudo. Test nuevo `test_families_are_said_in_words`.
- **Vigilante (solo ruta y claves).** `RUTA_PRECIOS` apunta a `resources/data/prices.json`; los valores de `COLUMNAS`, `CAMPOS` y `PROVISIONAL_NUEVO`, las claves que lee y escribe (`models`, `web_search_per_1000`, `consulted`), la línea literal `'  "models": {'` del serializador y el texto del PR para modelos nuevos (`family` y `supports_effort`). Identificadores, fixtures y nombre del script, intactos (A10a). Workflow `vigilante-precios.yml`: solo el comentario con la ruta.
- **Vendor.** `vendor.json` documenta con `_about` y `_provenance`. `scripts/check_vendor.py` pasa a inglés entero (respuesta 1): 13 nombres de módulo con PyCharm, el parámetro `lines` a mano y 41 variables locales con `apply` (159 reemplazos); `tests/test_vendor.py` (CRLF, editado con `newline=""`) usa los nombres nuevos (`check_vendor.<attr>` y la cadena de `monkeypatch`).
- **Docs.** CHANGELOG `[Unreleased]` (cuatro entradas: tablas y claves, `/api/stats` y `/api/events`, módulo `pricing` y cotejo, `vendor.json`) y wiki: Repo-hardening (ruta, `prices.json`, `consulted`) y Savings-and-metrics (rutas, `source`/`consulted`, familia `new`, clase `other`). El README no nombra rutas ni claves afectadas.

## Controles positivos
| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `test_precios.py::test_la_tabla_cubre_los_13_ids` | `prices.json` conserva la clave vieja `entrada` en `claude-opus-5-5` | `:116: AssertionError: claude-opus-5-5 — Extra items in the left set: 'entrada'; in the right set: 'input'` | sí (sha256 igual) |
| `test_vigilante.py::test_el_ensayo_tiene_diff_aunque_consultado_ya_sea_hoy` (y `::test_el_ensayo_pisa_la_marca_que_ya_trae_la_tabla`) | el mismo | `scripts/vigilante_precios.py:321: KeyError: 'input'` (desde `test_vigilante.py:555` y `:576`) | sí (sha256 igual) |
| `test_panel_coste.py::test_families_are_said_in_words` | `FAMILIA` del JS con la clave vieja `nueva` | `:591: assert 'familia de tokenizador (nueva 2, anterior 1)' in 'Equivalente estimado…'` | sí (sha256 igual) |
| `test_metrics.py::test_paridad_acct_entre_python_y_el_js_del_panel` | `density` renombrado solo en el JS (`e.densidad`) | `:1240: assert 0 == 179` (`returned` de `local_summarize`) | sí (sha256 igual) |

Detalle de cada mutante en `evidence/A5c/mutants.txt`.

## Llamadas `local_*` (sesión principal y cada agente)
| Quién | Tool | Para qué | Resultado (útil / corregido / descartado) |
| --- | --- | --- | --- |
| agente A5c (mapping) | local_summarize | `tests/test_vigilante.py` (752 líneas): qué tests dependen de las claves, la ruta y el serializador | útil (confirmó la comprobación del workflow, cuyo nombre no cambia) |
| agente A5c (aplicación) | local_lint_summary | `evidence/A5c/pytest-full.log` | útil (verde; 1 aviso de Starlette conocido) |
| agente A5c (aplicación) | local_commit_msg | `evidence/A5c/diff.patch` (112 KB, 9 trozos) | corregido: salió en inglés y genérico; el borrador se reescribió a mano en español |

## Llamadas `mcp__pycharm__*`
| Quién | Tool | Símbolo o patrón | Resultado |
| --- | --- | --- | --- |
| agente A5c (mapping) | search_regex | `\bprecios\b` en `**/*.py` | ~130 apariciones (incluye las de identificadores del vigilante, de A10a) |
| agente A5c (mapping) | search_regex | `\bprecios\.(CAMPOS_COTEJO\|_leer_tabla\|cargar_precios\|…)\b` | 37 referencias; verificación de las filas `cross_module` |
| agente A5c (mapping) | search_symbol | `cargar_precios`, `CAMPOS_COTEJO`, `comprobar_integridad` | definiciones confirmadas |
| agente A5c (aplicación) | rename_refactoring | `CAMPOS_COTEJO`→`CHECK_FIELDS` (`precios.py:26@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `COSTE_MINIMO_JUZGABLE`→`MIN_JUDGED_COST` (`precios.py:36@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `_SUFIJO_FECHA`→`_DATE_SUFFIX` (`precios.py:38@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `_leer_tabla`→`_read_table` (`precios.py:41@<module>`) | ok (la cadena de `monkeypatch` se cambió a mano) |
| agente A5c (aplicación) | rename_refactoring | `cargar_precios`→`load_prices` (`precios.py:47@<module>`) | ok (ídem en `test_valoracion.py`) |
| agente A5c (aplicación) | rename_refactoring | `cargar_densidad`→`load_density` (`precios.py:53@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `normalizar_id`→`normalize_id` (`precios.py:58@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `entrada`→`entry` (`precios.py:63@<module>`) | ok (revisado: no tocó la clave `"entrada"`) |
| agente A5c (aplicación) | rename_refactoring | `familia`→`family` (`precios.py:72@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `_juzgar`→`_judge` (`precios.py:78@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `cotejar`→`check_rows` (`precios.py:100@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `veredicto`→`verdict` (`precios.py:110@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `RAIZ`→`ROOT` (`check_vendor.py:47@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `MANIFIESTO_POR_DEFECTO`→`DEFAULT_MANIFEST` (`check_vendor.py:48@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `FALLO_INTEGRIDAD`→`INTEGRITY_FAILURE` (`check_vendor.py:55@<module>`) | ok (test a mano) |
| agente A5c (aplicación) | rename_refactoring | `FALLO_VULNERABILIDAD`→`VULNERABILITY_FAILURE` (`check_vendor.py:56@<module>`) | ok (test a mano) |
| agente A5c (aplicación) | rename_refactoring | `FALLO_MANIFIESTO`→`MANIFEST_FAILURE` (`check_vendor.py:57@<module>`) | ok (test a mano) |
| agente A5c (aplicación) | rename_refactoring | `ServicioNoDisponible`→`ServiceUnavailable` (`check_vendor.py:60@<module>`) | ok (test y dos docstrings a mano) |
| agente A5c (aplicación) | rename_refactoring | `_pedir_json`→`_fetch_json` (`check_vendor.py:71@<module>`) | ok (cadena de `monkeypatch` a mano) |
| agente A5c (aplicación) | rename_refactoring | `consultar_osv`→`query_osv` (`check_vendor.py:93@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `consultar_npm`→`query_npm` (`check_vendor.py:104@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `_clave_version`→`_version_key` (`check_vendor.py:113@<module>`) | ok (test a mano) |
| agente A5c (aplicación) | rename_refactoring | `cargar_manifiesto`→`load_manifest` (`check_vendor.py:125@<module>`) | ok |
| agente A5c (aplicación) | rename_refactoring | `comprobar_integridad`→`check_integrity` (`check_vendor.py:135@<module>`) | ok (test a mano) |
| agente A5c (aplicación) | rename_refactoring | `_escribir_summary`→`_write_summary` (`check_vendor.py:193@<module>`) | ok |
| agente A5c (aplicación) | lint_files | los 18 ficheros Python del diff (solo errores) | 4 avisos, todos falsos positivos conocidos de cadenas de `monkeypatch.setattr` (`socket.socket.connect`, `io.open`, `httpx2.Client`); ningún error real |

## Revisión del diff tras rename_refactoring
- **Documentos históricos de `.sdd/`.** PyCharm reescribió `coste-api-y-cuota/verification.md`, `english-names-bilingual-output/waves/A5a.md` y `vigilante-vendorizado/handoff.md`; se devolvieron con `git checkout`. `brief.md` sin tocar.
- **Nombres viejos.** Ninguno de los 25 nombres de módulo ni de las variables locales queda como identificador en `pricing.py` y `check_vendor.py`, ni ninguna referencia `precios.<attr>` o `check_vendor.<nombre viejo>` en `src/`, `tests/` ni `scripts/` (búsqueda por texto y detector). Las claves viejas solo quedan en las tablas de `legacy_names.py`, en `tests/test_recalcular_legacy.py` (formato viejo), en `tests/test_detect_spanish_names.py:205` (dato sintético que tiene que seguir en español) y en entradas ya publicadas del CHANGELOG.
- **Código inalcanzable.** No se reescribió ninguna función; en `recompute._check` solo se quitó la traducción del veredicto.
- **Prosa.** Docstrings y comentarios citan los nombres nuevos entre comillas invertidas; la prosa sigue en español.

## Scripts (REQ-014, solo olas que renombran en src/)
| Script | `--help` | Corrida mínima o `get_file_problems` |
| --- | --- | --- |
| `scripts/check_vendor.py` | 0 | corrida real (integridad offline, OSV y npm): 0, «chart.js 4.5.1 está al día» (`evidence/A5c/scripts-req014.txt`) |
| `scripts/vigilante_precios.py` | 0 | sin red: `RUTA_PRECIOS` existe, la tabla extraída de la página guardada trae `models` (13) y `web_search_per_1000` con los campos `input`, `cache_read`, `output`, `w5m`, `w1h`, y el serializador da `prices.json` byte a byte: 0 (`evidence/A5c/scripts-req014.txt`) |
| `scripts/dev/capture_dashboard.py` | — | no se ejecuta (abre un navegador headless); `ruff` limpio y `lint_files` sin errores |

## Desviaciones y nombres «(plan)» ajustados
- **Fuera de «posee», aprobado en el mapping como consecuencia mecánica:** `cost.py`, `transcripts.py`, `attribution.py`, `valuation.py`, `recompute.py`, `web/metrics.py`, `scripts/dev/capture_dashboard.py` (lee `data/density.json` y `prices.json` con las claves nuevas y resuelve en JS con `families.new`, `unnumbered`, `read_format` y las clases nuevas), los tests `test_valoracion.py`, `test_metrics.py`, `test_panel_coste.py` (con el test nuevo de familias), CHANGELOG y dos páginas de la wiki.
- **`tests/test_transcripts.py:324`** (`fila["modelo"]` → `fila["model"]`): el mapping listaba la clave en `transcripts.py` pero no este test; consecuencia mecánica de la misma fila.
- **Método de 8 filas del CSV ajustado al aplicar:** 7 filas de `check_vendor.py` (`FALLO_*`, `ServicioNoDisponible`, `_pedir_json`, `_clave_version`, `comprobar_integridad`) se renombraron con PyCharm en el script y a mano en el test, así que pasan de `search_edit` a `pycharm`; el parámetro `lineas` de `_escribir_summary` se hizo a mano (`search_edit`). Anotado en la cabecera del CSV.
- **Texto del PR del vigilante para modelos nuevos:** cita ahora `family` y `supports_effort` y lee `PROVISIONAL_NUEVO['family']`; no estaba en el mapping (las claves con comilla simple dentro de una f-string se le escaparon) y lo cazó la suite.
- **Respuestas 1-9 de la sesión principal:** `check_vendor.py` en A5c (1); `new|previous` (2); rótulos en el JS (3); `cache_read` (4); `check_rows` (5); `_ensayo` y compañía a A10a (6); `_acerca_de` de los manifiestos de captura a A10 (7); sin alias de `CHECK_FIELDS` (8); `test_detect_spanish_names.py:205` sin tocar (9).
- **PR #248 del vigilante (límites):** no toca ficheros ni formatos de A5c (solo `.github/vigilante/limites-de-uso.txt`); no hace falta cerrarlo antes de mezclar.

## Pendientes
- **A10a:** el nombre del script `vigilante_precios.py` y de su workflow, sus identificadores (`RUTA_PRECIOS`, `CAMPOS`, `PROVISIONAL_NUEVO`, `serializar_precios`…), los fixtures `tests/fixtures/vigilante/precios.html` y `limites.html`, la clave `_ensayo` (`CLAVE_ENSAYO`), la entrada `ensayo` del workflow, `VIGILANTE_ENSAYO`, las ramas `vigilante/precios|limites|ensayo`, los jobs `precios|limites` y `.github/vigilante/limites-de-uso.txt`.
- **A10 (scripts de captura):** `_acerca_de` de los manifiestos de captura (`scripts/dev/capture_dashboard.py:100`, `scripts/dev/capture_icons.py:82`, `docs/assets/dashboard.json`, `tests/test_captura.py:127`) y las variables `datos`, `densidad`, `precios`, `DENSIDAD`, `PRECIOS_CONSULTADO` de `capture_dashboard.py`.
- **A8b:** el identificador JS `FAMILIA` (con `DESCARTE`, `textoCoste`…).
- **A9:** nombres de los ficheros de test `test_precios.py`, `test_densidad.py`, `test_valoracion.py` y sus nombres `test_*` en español.
