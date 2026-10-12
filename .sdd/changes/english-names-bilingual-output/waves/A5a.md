# Ola A5a — Atribución (`atribucion`→`attribution`)

- Rama: `sdd/english-names-a5a` · PR: (lo abre la sesión principal) · Commit(s): (pendiente; borrador en `waves/A5a-commit-msg.txt`, firmado y sin coautoría)
- REQ cubiertos: REQ-005 (caché `attribution-*`, se escribe solo el formato nuevo), REQ-006 (lectura doble, siembra una sola vez con la regla de mejor cruce, viejo intacto) y REQ-014 (control de `test_reason` con `scripts/medir_adopcion.py`)
- Ficheros poseídos (según plan.md §1.2 A5a): `atribucion.py`→`attribution.py`, `transcripts.py`, `legacy_names.py`, `scripts/medir_adopcion.py`, `tests/test_atribucion.py`, `tests/test_transcripts.py`, y la línea de import de `checks.py`, `server.py`, `web/metrics.py`, `coste.py`, `recalcular.py` y `valoracion.py`. Tocados fuera de la lista, todos aprobados por la sesión principal (respuesta 3 al mapping): ver «Desviaciones»
- EOL: `evidence/A5a/eol-check.txt` sobre todo el diff (26 ficheros), con el `git mv` del módulo seguido a mano (git no lo empareja porque se reescribió más de la mitad). Siguen en CRLF `server.py`, `web/metrics.py` y `docs/wiki/Integration-install.md`. Resultado: 0 diferencias (sí)
- Mapping: `waves/A5a-mapping.csv` aprobado (`# approved-by-main`), un solo lote de 217 filas; filas `pycharm` 80 = filas `rename_refactoring` 80; filas `search_edit` 137, cada una con su motivo (113 variables locales aplicadas con `make_mapping.py apply`, el módulo por `git mv` y las filas a mano de fichero, claves, valores, tablas, lector doble, siembra y consecuencias fuera de «posee»)
- Tests recogidos: antes 2538 → después 2544 (+6, −0)
- Suite: `evidence/A5a/pytest-full.log` (con `pesado.sh`), resultado verde (2542 pasan, 2 saltados)
- `ruff check .` y `ruff format --check .`: limpios
- Detector (`evidence/A5a/detector-after.json`): hallazgos únicos 8312 → 8158 (−154); nombres en español únicos 4351 → 4309 (−42); ficheros con hallazgos 165 → 165

## Qué se hizo

- **Módulo `attribution`.** `atribucion.py` pasa a `attribution.py` (`git mv`, y un script por tokens que cambia `atribucion` por `attribution` en los imports y en `atribucion.<attr>`, fuera de cadenas y comentarios). Nombres: `read_note` y `NOTE_TTL_S` (los que dejó A2), `resolve_call`, `current_call`, `file_keys`, `backfill_path`, `read_backfill`, `write_backfill`, `exclusion_reason`, `cleanup_period_days`, `MATCH_RANK`, `DEFAULT_CLEANUP_DAYS`, `TEST_CLIENTS`, `NON_CLAUDE_CLIENTS`, `EXCLUDED_CLIENTS` y el resto del mapping.
- **`transcripts`.** `Index`, `Delegation` y `Thread` con sus campos (`thread`, `model`, `effort`, `bench`, `requests`, `compactions`, `delegations`, `threads`, `rejections`, `costs`, `files`, `unreadable_files`, `corrupt_lines`), `read`, `match_lines`, `entry_for`, `n_and_expiries`, `percentile`, `median`, `parse_instant`, `request_cost`, `needs_backfill`, `TOOL_PREFIX`, `MARGIN_BEFORE`/`MARGIN_AFTER`, `NO_RESULT_WINDOW` y `CHECK_FIELDS`.
- **Caché (`attribution-AAAAMM.json`).** Primer nivel `entries` y, en cada entrada, `match`, `bench` y `expiries`, con los cruces `exact`, `window`, `window+path`, `ambiguous` y `no_match`. Tablas en `legacy_names`: `FORMATS["attribution"]` (claves y valores de la entrada) y `ATTRIBUTION_FILE_PREFIXES` (aparte de `FILE_NAMES`, que está atada a `hook_common` por test y que los hooks no necesitan para esto).
- **Lectura doble y siembra.** `read_backfill` lee el nuevo; si no existe, lee `atribucion-AAAAMM.json` traducido con `normalize("attribution", …)`, sin escribir nada. `write_backfill` parte de esa lectura, así que la primera escritura de un mes siembra el nuevo desde el viejo con la regla de mejor cruce, y desde ahí solo se lee el nuevo. El viejo no se abre para escribir nunca. Un nuevo dañado cuenta como vacío y no provoca otra siembra.
- **Escritura solo en el formato nuevo.** `write_backfill` traduce también lo que recibe, así que quien le pase claves viejas escribe igualmente `match`/`bench`/`expiries`.
- **Lectores de la fila fundida.** `coste.CAMPOS_DEL_RELLENO` aporta `expiries`, `match` y `bench`; `_CRUCES_SIN_REMEDIO`, `tramo`, `recalcular` (exclusión y resumen «cruces») y `valoracion` (exclusión y `n_de`) leen los nombres nuevos.
- **`scripts/medir_adopcion.py`.** Import y docstring. Su corrida mínima sobre datos sintéticos aparta como prueba una fila marcada `banco` en un `atribucion-*.json` viejo, a través de la lectura doble.
- **Docs.** CHANGELOG `[Unreleased]`, `docs/wiki/Savings-and-metrics.md` (fichero, claves, valores y siembra; `attribution.test_reason`) y `docs/wiki/Integration-install.md` (fila del check de coste y relleno).

## Controles positivos
| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `test_la_siembra_ocurre_una_sola_vez` | sembrar desde el viejo en cada escritura | `AssertionError: assert 6 == 5` (`len(segunda) == len(primera)`: la entrada que una 0.34.0 añadió al viejo después de sembrar se vuelve a importar) | sí (sha256 igual) |
| `test_un_cruce_exacto_viejo_no_se_pierde_frente_a_una_ventana_nueva` | fundir sin la regla de mejor cruce (la nueva pisa siempre) | `AssertionError: assert 'window' == 'exact'` | sí |
| `test_sembrar_deja_el_fichero_viejo_intacto_byte_a_byte` | reescribir el viejo en el formato nuevo al sembrar | `assert b'{"entries":..."version": 1}' == b'{"entradas"..."version": 1}'` | sí |
| `test_el_relleno_viejo_se_lee_traducido_si_no_hay_nuevo` | `read_backfill` solo lee `attribution-*` | `KeyError: 'k1'` (en `leidas["k1"]`: no se leyó nada) | sí |
| `test_el_relleno_se_escribe_solo_en_el_formato_nuevo` | `write_backfill` no traduce lo que recibe | `AssertionError: "cruce"` (el bucle de claves viejas en disco) | sí |
| `test_con_los_dos_ficheros_manda_el_nuevo` | con los dos ficheros manda el viejo | `assert {'k1': {'benc...: 'no_match'}} == {'k1': {'match': 'window'}}` | sí |
| control de REQ-014 (`scripts/medir_adopcion.py`) | renombrar `attribution.test_reason` sin tocar el script | `--help` sale con 0 (no llega a llamarla); la corrida mínima sale con 1: `AttributeError: module 'local_delegate.attribution' has no attribute 'test_reason'` | sí |

Detalle y sha256 en `evidence/A5a/positive-controls.txt`. Cada mutante se aplicó, se corrió su test y se restauró el fichero byte a byte, con el sha256 comprobado antes y después. Los siete se corrieron dos veces, la segunda sobre el código final ya formateado, con el mismo resultado.

## Llamadas `local_*` (sesión principal y cada agente)
| Quién | Tool | Para qué | Resultado (útil / corregido / descartado) |
| --- | --- | --- | --- |
| agente A5a | `local_explain_code(path=src/local_delegate/atribucion.py)` | primera pasada: caché, regla de fusión y funciones públicas antes de leer franjas | útil (la regla de mejor cruce y los lectores, confirmados después en el código) |
| agente A5a | `local_lint_summary(path=evidence/A5a/pytest-full.log)` | resumen de la suite completa | útil (verde; un aviso de deprecación de Starlette ajeno a la ola) |
| agente A5a | `local_commit_msg(path=evidence/A5a/diff.patch)` | borrador del commit | corregido (salió en inglés y en una sola línea; reescrito en español) |

## Llamadas `mcp__pycharm__*`
| Quién | Tool | Símbolo o patrón | Resultado |
| --- | --- | --- | --- |
| agente A5a | search_regex | llamadas con palabra clave a los parámetros `cross_module` | verificación del mapping: solo `test_atribucion.py` (y `desde=` en `recalcular.py:255`) |
| agente A5a | search_regex | `(atribucion\|transcripts).<funciones y constantes>` | verificación de las filas `cross_module` |
| agente A5a | search_regex | `.<campos de Delegacion, Hilo e Indice>` | homónimos de otras clases localizados antes de renombrar (lección de A3) |
| agente A5a | search_regex | muestra de 20 `module_local` (semilla 20261012) fuera de su fichero | 0 referencias de código; 0 discrepancias |
| agente A5a | search_text | `_raiz_de_proyectos` | la fila `unresolved`: cadena de `monkeypatch` en `test_atribucion.py:406` |
| agente A5a | search_symbol | `Indice` | definición en `transcripts.py:82` |
| agente A5a | rename_refactoring | `VIGENCIA_DE_NOTA_S`→`NOTE_TTL_S` (`atribucion.py:33@<module>`) | ok |
| agente A5a | rename_refactoring | `COLA_BYTES`→`TAIL_BYTES` (`atribucion.py:36@<module>`) | ok |
| agente A5a | rename_refactoring | `PRESUPUESTO_S`→`BUDGET_S` (`atribucion.py:37@<module>`) | ok |
| agente A5a | rename_refactoring | `CLIENTES_NO_CLAUDE`→`NON_CLAUDE_CLIENTS` (`atribucion.py:40@<module>`) | ok |
| agente A5a | rename_refactoring | `CLIENTES_DE_PRUEBA`→`TEST_CLIENTS` (`atribucion.py:43@<module>`) | ok |
| agente A5a | rename_refactoring | `CLIENTES_EXCLUIDOS`→`EXCLUDED_CLIENTS` (`atribucion.py:47@<module>`) | ok |
| agente A5a | rename_refactoring | `RANGO_DE_CRUCE`→`MATCH_RANK` (`atribucion.py:50@<module>`) | ok |
| agente A5a | rename_refactoring | `PLAZO_POR_DEFECTO`→`DEFAULT_CLEANUP_DAYS` (`atribucion.py:53@<module>`) | ok (4; la constante homónima de `valoracion.py` no se tocó, solo su referencia) |
| agente A5a | rename_refactoring | `_VERSION_RELLENO`→`_BACKFILL_VERSION` (`atribucion.py:55@<module>`) | ok |
| agente A5a | rename_refactoring | `_valido`→`_valid_id` (`atribucion.py:61@<module>`) | ok |
| agente A5a | rename_refactoring | `directorio`→`directory` (`atribucion.py:65@leer_nota`) | ok |
| agente A5a | rename_refactoring | `leer_nota`→`read_note` (`atribucion.py:65@<module>`) | ok |
| agente A5a | rename_refactoring | `_raiz_de_proyectos`→`_projects_root` (`atribucion.py:89@<module>`) | ok (2; esta vez sí cambió la cadena del `monkeypatch.setattr` de `test_atribucion.py:406`) |
| agente A5a | rename_refactoring | `_ruta_segura`→`_safe_path` (`atribucion.py:93@<module>`) | ok |
| agente A5a | rename_refactoring | `raiz`→`root` (`atribucion.py:93@_ruta_segura`) | ok |
| agente A5a | rename_refactoring | `raiz`→`root` (`atribucion.py:108@_transcript_de`) | ok |
| agente A5a | rename_refactoring | `_modelo_de_la_linea`→`_model_from_line` (`atribucion.py:128@<module>`) | ok |
| agente A5a | rename_refactoring | `_buscar_modelo`→`_find_model` (`atribucion.py:151@<module>`) | ok |
| agente A5a | rename_refactoring | `abrir`→`opener` (`atribucion.py:152@_buscar_modelo`) | ok |
| agente A5a | rename_refactoring | `reloj`→`clock` (`atribucion.py:152@_buscar_modelo`) | ok |
| agente A5a | rename_refactoring | `_admite_esfuerzo`→`_supports_effort` (`atribucion.py:184@<module>`) | ok |
| agente A5a | rename_refactoring | `modelo`→`model` (`atribucion.py:184@_admite_esfuerzo`) | ok |
| agente A5a | rename_refactoring | `resolver_llamada`→`resolve_call` (`atribucion.py:192@<module>`) | ok |
| agente A5a | rename_refactoring | `notas`→`notes` (`atribucion.py:195@resolver_llamada`) | ok |
| agente A5a | rename_refactoring | `ahora`→`now` (`atribucion.py:196@resolver_llamada`) | ok |
| agente A5a | rename_refactoring | `reloj`→`clock` (`atribucion.py:197@resolver_llamada`) | ok |
| agente A5a | rename_refactoring | `abrir`→`opener` (`atribucion.py:198@resolver_llamada`) | ok |
| agente A5a | rename_refactoring | `proyectos`→`projects` (`atribucion.py:199@resolver_llamada`) | ok |
| agente A5a | rename_refactoring | `llamada_actual`→`current_call` (`atribucion.py:240@<module>`) | ok |
| agente A5a | rename_refactoring | `claves_del_fichero`→`file_keys` (`atribucion.py:261@<module>`) | ok |
| agente A5a | rename_refactoring | `mes`→`month` (`atribucion.py:283@ruta_de_relleno`) | ok |
| agente A5a | rename_refactoring | `ruta_de_relleno`→`backfill_path` (`atribucion.py:283@<module>`) | ok |
| agente A5a | rename_refactoring | `leer_relleno`→`read_backfill` (`atribucion.py:288@<module>`) | ok |
| agente A5a | rename_refactoring | `mes`→`month` (`atribucion.py:288@leer_relleno`) | ok |
| agente A5a | rename_refactoring | `_rango`→`_rank` (`atribucion.py:300@<module>`) | ok |
| agente A5a | rename_refactoring | `escribir_relleno`→`write_backfill` (`atribucion.py:304@<module>`) | ok |
| agente A5a | rename_refactoring | `mes`→`month` (`atribucion.py:304@escribir_relleno`) | ok |
| agente A5a | rename_refactoring | `excluida`→`exclusion_reason` (`atribucion.py:359@<module>`) | ok |
| agente A5a | rename_refactoring | `plazo_de_borrado`→`cleanup_period_days` (`atribucion.py:370@<module>`) | ok |
| agente A5a | rename_refactoring | `PREFIJO`→`TOOL_PREFIX` (`transcripts.py:30@<module>`) | ok |
| agente A5a | rename_refactoring | `ANTES`→`MARGIN_BEFORE` (`transcripts.py:36@<module>`) | ok |
| agente A5a | rename_refactoring | `DESPUES`→`MARGIN_AFTER` (`transcripts.py:37@<module>`) | ok |
| agente A5a | rename_refactoring | `SIN_RESULTADO`→`NO_RESULT_WINDOW` (`transcripts.py:38@<module>`) | ok |
| agente A5a | rename_refactoring | `CAMPOS_COTEJO`→`CHECK_FIELDS` (`transcripts.py:41@<module>`) | ok |
| agente A5a | rename_refactoring | `instante`→`parse_instant` (`transcripts.py:44@<module>`) | ok |
| agente A5a | rename_refactoring | `Delegacion`→`Delegation` (`transcripts.py:56@<module>`) | ok |
| agente A5a | rename_refactoring | `hilo`→`thread` (`transcripts.py:64@Delegacion`) | ok |
| agente A5a | rename_refactoring | `modelo`→`model` (`transcripts.py:66@Delegacion`) | ok (20; arrastró `.modelo` de otras clases en `tests/test_affinity.py` y `tests/test_cadenas.py`: repuestos con `git checkout`) |
| agente A5a | rename_refactoring | `esfuerzo`→`effort` (`transcripts.py:67@Delegacion`) | ok |
| agente A5a | rename_refactoring | `banco`→`bench` (`transcripts.py:69@Delegacion`) | ok |
| agente A5a | rename_refactoring | `Hilo`→`Thread` (`transcripts.py:75@<module>`) | ok |
| agente A5a | rename_refactoring | `peticiones`→`requests` (`transcripts.py:77@Hilo`) | ok |
| agente A5a | rename_refactoring | `Indice`→`Index` (`transcripts.py:82@<module>`) | ok |
| agente A5a | rename_refactoring | `delegaciones`→`delegations` (`transcripts.py:85@Indice`) | ok |
| agente A5a | rename_refactoring | `hilos`→`threads` (`transcripts.py:86@Indice`) | ok |
| agente A5a | rename_refactoring | `peticiones`→`requests` (`transcripts.py:88@Indice`) | ok |
| agente A5a | rename_refactoring | `rechazos`→`rejections` (`transcripts.py:90@Indice`) | ok |
| agente A5a | rename_refactoring | `costes`→`costs` (`transcripts.py:92@Indice`) | ok |
| agente A5a | rename_refactoring | `ficheros`→`files` (`transcripts.py:93@Indice`) | ok |
| agente A5a | rename_refactoring | `ficheros_ilegibles`→`unreadable_files` (`transcripts.py:94@Indice`) | ok |
| agente A5a | rename_refactoring | `lineas_corruptas`→`corrupt_lines` (`transcripts.py:95@Indice`) | ok |
| agente A5a | rename_refactoring | `coste_de_peticion`→`request_cost` (`transcripts.py:98@<module>`) | ok |
| agente A5a | rename_refactoring | `_leer_linea`→`_read_line` (`transcripts.py:125@<module>`) | ok |
| agente A5a | rename_refactoring | `banco`→`bench` (`transcripts.py:125@_leer_linea`) | ok |
| agente A5a | rename_refactoring | `hilo`→`thread` (`transcripts.py:125@_leer_linea`) | ok |
| agente A5a | rename_refactoring | `leer`→`read` (`transcripts.py:184@<module>`) | ok |
| agente A5a | rename_refactoring | `raiz`→`root` (`transcripts.py:184@leer`) | ok |
| agente A5a | rename_refactoring | `percentil`→`percentile` (`transcripts.py:248@<module>`) | ok |
| agente A5a | rename_refactoring | `mediana`→`median` (`transcripts.py:260@<module>`) | ok |
| agente A5a | rename_refactoring | `_mismo_path`→`_same_path` (`transcripts.py:267@<module>`) | ok |
| agente A5a | rename_refactoring | `_admite_esfuerzo`→`_supports_effort` (`transcripts.py:273@<module>`) | ok |
| agente A5a | rename_refactoring | `modelo`→`model` (`transcripts.py:273@_admite_esfuerzo`) | ok |
| agente A5a | rename_refactoring | `entrada_de`→`entry_for` (`transcripts.py:278@<module>`) | ok |
| agente A5a | rename_refactoring | `necesita_relleno`→`needs_backfill` (`transcripts.py:302@<module>`) | ok |
| agente A5a | rename_refactoring | `casar`→`match_lines` (`transcripts.py:307@<module>`) | ok |
| agente A5a | rename_refactoring | `desde`→`since` (`transcripts.py:308@casar`) | ok |
| agente A5a | rename_refactoring | `lineas`→`lines` (`transcripts.py:308@casar`) | ok |
| agente A5a | rename_refactoring | `n_y_caducidades`→`n_and_expiries` (`transcripts.py:221@<module>`) | ok |
| agente A5a | rename_refactoring | `_por_tool`→`_by_tool` (`transcripts.py:294@<module>`) | ok |
| agente A5a | rename_refactoring | `compactaciones`→`compactions` (`transcripts.py:78@Hilo`) | ok |
| agente A5a | lint_files | los 11 ficheros Python de `src/` y `scripts/` del diff | sin errores |
| agente A5a | lint_files | los 11 ficheros de test del diff | 4 errores, todos falsos positivos previos a la ola sobre cadenas de `monkeypatch.setattr` (`io.open` en `test_coste_doctor.py:196` y `test_panel_coste.py:405`, `httpx2.Client` en `test_metrics.py:440`, `socket.connect` en `test_panel_coste.py:452`); ninguno toca lo renombrado |

Los `rename_refactoring` de nombres repetidos en un mismo fichero (`raiz`, `abrir`, `reloj` y `mes` en `atribucion.py`; `hilo`, `banco`, `modelo` y `peticiones` en `transcripts.py`) se lanzaron de uno en uno, con un `grep` después de cada uno para ver qué definición había cambiado. Las variables locales se aplicaron ANTES con `make_mapping.py apply`, para que PyCharm no eligiera una local en vez del parámetro o el campo.

## Revisión del diff tras rename_refactoring
- **Atributos homónimos (lección de A3).** El rename del campo `Delegacion.modelo` arrastró `.modelo` de otra clase (los intentos de `cadenas`/`affinity`) en `tests/test_affinity.py` (6 líneas) y `tests/test_cadenas.py` (10 líneas). Se repusieron los dos ficheros con `git checkout`, porque no tenían otros cambios de la ola. Revisados después uno a uno los `.model`, `.thread`, `.bench`, `.requests`, `.files`, `.rejections` del diff: todos son de `Delegation`, `Thread` o `Index`. `args.banco` de `scripts/experimento_adopcion.py` y los `.modelo` de `server.py` no se tocaron.
- **`server.py` (lección de A4), línea a línea.** Solo cambian cuatro líneas: el import, el `from . import attribution` diferido, `attribution.current_call()` y `attribution.test_reason(rec)`. CRLF conservado; sin cambios de sangría. `web/metrics.py`: import, una llamada, un docstring y un comentario; CRLF conservado.
- **Documentos históricos de `.sdd/`.** Los renames tocaron `coste-api-y-cuota/` (`evidencias/T2.md`, `plan.md`, `review.md`, `verification.md`), `test-windows-out-of-metrics/` (`evidencias/T2.md`, `plan.md`, `research.md`) y `waves/A2.md`. Se repusieron con `git checkout`; `brief.md` no se tocó.
- **Cadenas y comentarios.** `make_mapping.py apply` no tocó cadenas: las claves persistidas (`"cruce"`, `"banco"`, `"caducidades"`, `"entradas"`) y los valores se cambiaron después, a propósito, con la tabla de D4. La clave `"modelo"` de `cost_state` se dejó (`keep`, pendiente de A5b). Los docstrings y comentarios que citaban nombres viejos (`raiz`, `COLA_BYTES`, `PRESUPUESTO_S`, `reloj`, `notas`, `proyectos`, `leer_nota`, `llamada_actual`, `resolver_llamada`, `excluida`, `sin_cruce`) se actualizaron a mano. No hay palabras inglesas coladas en prosa española.
- **Código inalcanzable.** `read_backfill` y `write_backfill` se reescribieron enteras. No queda nada detrás de ningún `return`.

## Scripts (REQ-014, solo olas que renombran en src/)
| Script | `--help` | Corrida mínima o `get_file_problems` |
| --- | --- | --- |
| `scripts/medir_adopcion.py` | 0 | `--desde 2026-10-01 --json` sobre datos sintéticos (`LOCAL_DELEGATE_LOG_DIR` y `LD_HOOK_TELEMETRY_LOG` en el scratchpad): 0, y aparta 2 filas como prueba, una de ellas por el `banco` de un `atribucion-*.json` viejo (`evidence/A5a/scripts-req014.txt`) |
| `local-delegate recompute-cost` (CLI) | 0 | `import` de `attribution`, `transcripts`, `coste`, `recalcular`, `valoracion`, `server`, `checks` y `web.metrics`: ok |
| resto de `scripts/` | — | ninguno importa `attribution` ni `transcripts` (`_banco_claude.py` importa `legacy_names`; `construir_corpus.py`, `benchmark`/`config`/`server`) |

## Desviaciones y nombres «(plan)» ajustados
- **Fuera de «posee», aprobado (respuesta 3):** `coste.py` (`CAMPOS_DEL_RELLENO`, `_CRUCES_SIN_REMEDIO`, `tramo` y dos docstrings), `recalcular.py` (exclusión, resumen «cruces», un docstring y un comentario), `valoracion.py` (exclusión y `n_de`), los datos de prueba de `test_densidad.py`, `test_coste_doctor.py`, `test_metrics.py`, `test_panel_coste.py`, `test_medir_adopcion.py`, `test_valoracion.py` y `test_recalcular.py`, y la wiki. Además, como consecuencia mecánica del rename: `tests/test_cuota.py` (`transcripts.read`, `.requests`, `.rejections`), `tests/test_hook_legacy_names.py` (`read_note`), comentarios en `checks.py`, `web/metrics.py` y `resources/hooks/hook_common.py` que citaban el módulo o la caché.
- **D4 ampliado (respuestas 1 y 2):** `caducidades`→`expiries` y `ventana+path`→`window+path`.
- **`write_backfill` traduce lo que recibe (respuesta 5).**
- **Fila del módulo.** Va como `search_edit` desde el mapping (`git mv` + script por tokens), porque PyCharm no renombra módulos (A3/A4).
- **API nueva no nombrada en el plan:** `attribution.legacy_backfill_path`, `attribution._load_entries` y `legacy_names.ATTRIBUTION_FILE_PREFIXES`.
- **El test de REQ-014 con `--help` no basta:** `medir_adopcion.py --help` no llama a `test_reason`, así que el control lo da la corrida mínima sobre datos sintéticos.
- **`tests/test_atribucion.py` conserva su nombre**: los módulos de test se renombran en A9.

## Pendientes
- **A5b:** la clave `"modelo"` de las filas de `transcripts.cost_state` (cotejo de precios; `keep` en el mapping); `valoracion.PLAZO_POR_DEFECTO`; la clave de salida `caducidades` de `valoracion` (`:125`, la lee `test_valoracion.py:78`); el resto de nombres de `coste`, `recalcular` y `valoracion` (`CAMPOS_DEL_RELLENO`, `_CRUCES_SIN_REMEDIO`, `tramo`…).
- **A5c:** `precios.CAMPOS_COTEJO` (en `transcripts` ya se usa con el alias `CHECK_FIELDS`).
- **Valores de motivo `pruebas` y `no es Claude`** de `test_reason`/`exclusion_reason`: son rótulos del tramo `excluido` que ve una persona; no entran en D4 (frente B o la ola que la sesión principal decida).
- **A9:** nombres de test en español de `test_atribucion.py`/`test_transcripts.py` (y el propio nombre del módulo de test). `tests/test_recalcular.py:256` comprueba que no se escribe `attribution-*.json`; no mira el nombre viejo, que nunca se escribe.
