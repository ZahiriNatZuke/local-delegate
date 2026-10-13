# Ola A8a — Resto de `src/` (Python): `checks`, `cadenas`, `estado_json`, `preguntas`, `sondas` y diez módulos más

La ola se parte en dos suboles con un PR cada una (D13: 392 filas en total, y el máximo es 300
por lote). **A8a-1** (`checks.py` y `cadenas.py`→`chains.py`) está mezclada (#269). **A8a-2** (el
resto, más las 8 filas de `A8a-extra.csv` de la respuesta 11) está aplicada y registrada en la
sección «A8a-2», al final. Las tablas de controles positivos, `local_*` y PyCharm son las de las dos
suboles, porque `check_wave_records.py` lee la primera tabla de cada sección: 19 + 73 = 92 filas
`rename_refactoring` = 92 filas `pycharm` de los dos mappings.

- Rama: A8a-1 en `sdd/english-names-a8a`, mezclada en `main` con el PR #269 (`0d49cbf`); A8a-2 en `sdd/english-names-a8a-2`, encima de `0d49cbf` · PR de A8a-2: (lo abre la sesión principal) · Commit de A8a-2: pendiente, con el borrador en `waves/A8a-2-commit-msg.txt` (firmado y sin coautoría)
- Quién: un agente hizo los dos mappings (fase 1). Tras la aprobación de la sesión principal, con las respuestas 1-11, aplicó A8a-1 (fase 2).
- REQ cubiertos por A8a-1: REQ-014 (módulo `cadenas`→`chains`, de D3), REQ-015 (identificadores internos de `checks.py` y `chains.py`) y REQ-017 (ningún assert cambia de sentido)
- Ficheros poseídos por A8a-1: `src/local_delegate/checks.py`, `src/local_delegate/cadenas.py`→`chains.py`, sus tests y la fila de `residente` de `rename-exceptions.md` (respuesta 4). Lo de fuera, en «Desviaciones»
- EOL: `evidence/A8a-1/eol-check.txt` (`git ls-files --eol` antes y después sobre todo el repo). La única diferencia es el rename `cadenas.py`→`chains.py`, LF en los dos. Todas las ediciones desde fuera, con Python y `newline=""`
- Mapping: `waves/A8a-1-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 151 filas. Filas `pycharm` 19 = filas `rename_refactoring` 19. Filas `search_edit` 132, cada una con su motivo: 125 con `make_mapping.py apply` (420 reemplazos), 6 con el renombrador por AST `a8a/ren.py` y 1 de módulo (`git mv` + `a8a/modren.py`)
- Tests recogidos: antes 2567 (`evidence/A8a-1/collect-before.txt`) → después 2567 (2565 pasan + 2 saltados en `pytest-full.log`), +0 −0
- Suite: `evidence/A8a-1/pytest-full.log` (con `pesado.sh`, en serie), verde: 2565 pasan, 2 saltados y el aviso ya conocido de Starlette (`BlockingPortal`), en 4 min 17 s
- `ruff check src tests scripts .sdd/changes/english-names-bilingual-output/tools` y `ruff format --check` sobre lo mismo: limpios (`evidence/A8a-1/ruff-check.txt`, 187 ficheros). `ruff format` volvió a juntar en una línea la tupla `targets` de `_probe_memory`, que se quedaba corta con los nombres nuevos
- Detector (`evidence/A8a-1/detector-after.json`, con `--exceptions rename-exceptions.md`): hallazgos únicos 7072 (tras A7b) → 6966 (−106); fuera de la lista 7065 → 6959. En `checks.py` y `chains.py` solo queda la clave de huella `"ruta"` de `checks.py:1534`, que es un pendiente abierto (respuesta 8)
- Tamaño: 9 ficheros, 389 líneas cambiadas (`git diff -M --numstat --ignore-cr-at-eol`)
- **A8a-2** (detalle en su sección): mapping `waves/A8a-2-mapping.csv` aprobado, 241 filas (233 + 8 de la respuesta 11); `pycharm` 73 = `rename_refactoring` 73; `search_edit` 168 (160 con `apply`, 511 reemplazos; 5 con `ren.py`; 3 módulos). Tests 2567 → 2567; suite verde (`evidence/A8a-2/pytest-full.log`, 2565 pasan y 2 saltados); `ruff` limpio; EOL sin cambios salvo los tres renames de módulo; detector 6966 → 6764 (−202), fuera de la lista 6959 → 6757; 53 ficheros, 785 líneas cambiadas

## Alcance de A8a-1

- **Qué entró:** todos los identificadores en español de `checks.py` (125 filas: locales de los probes, `_oldest_pending` con sus parámetros, `_entry_auth`, `_desktop_connection`, `_client_dirs`, `_REFERENCED_VARIABLE`, `_MCP_REMOTE_VARIABLE`, `_LOCAL_HOSTS`, `_BACKFILL_MARGIN`, `_UNNAMED`, `_MIN_TS`, `_instant`, `_describe`) y de `cadenas.py`→`chains.py` (26 filas: `Chain` con `role`/`steps`/`ignored`/`models`, `resolve`, `describe`, `TEXT_ROLES`, `DEFAULT_CHAINS`, `_NO_FALLBACK_VALUES`, `_steps`).
- **Excluido a propósito:**
  - los usos de `sondas` en `checks.py` (:39, :117, :119, :213-237, :1401-1409), que toca A8a-2 (respuesta 1);
  - la cita `` `cadenas.py` `` de `config.py:357`, porque el fichero es de A8a-2: queda pendiente para esa subola;
  - textos de salida, prompts y docstrings (B2), salvo las citas de nombres;
  - los nombres `test_*` y las variables propias de los tests (A9);
  - los datos de prueba del detector.

## Qué se hizo (A8a-1)

1. **`make_mapping.py apply`** con el CSV aprobado: 420 reemplazos (checks 363, cadenas 57). Fue antes que nada, porque localiza cada función por su nombre viejo.
2. **`a8a/ren.py`** (`a8a/ops-1.json`; es la copia de A7b con la op `param` generalizada a cualquier fichero):
   - los parámetros solo-por-nombre `ahora`/`plazo_dias` de `_pendiente_mas_vieja` (4 + 4 apariciones y su `nombre=` en :1810);
   - los campos `rol`/`pasos`/`ignorados` de `Cadena` en `chains.py`, `checks.py`, `server.py:2135`, `tests/test_cadenas.py`, `test_checks.py` y `test_rol_fast_retirado.py`;
   - `.modelos` en `tests/test_cadenas.py` (8).
3. **PyCharm, 19 `rename_refactoring`.** Antes, `search_text` confirmó que PyCharm veía en disco lo de `apply` y `ren.py` (`period_days` en `checks.py`, `.steps` en `server.py`). Después, el barrido AST (`a8a/leftover.py`) confirmó que **no** se deshizo nada: en `chains.py` y `checks.py` solo quedaban las ediciones a mano previstas.
4. **Módulo:** `git mv src/local_delegate/cadenas.py src/local_delegate/chains.py` y `a8a/modren.py`, que cambia por tokens los imports y los `cadenas.` en `checks.py`, `server.py` y cinco tests (78 cambios). A mano, los dos casos que el script no ve: el `cadenas,` del import en varias líneas de `server.py:40` y `monkeypatch.setattr(cadenas, …)` de `tests/test_affinity.py:122`.
5. **A mano** (`a8a/manual1.py`, 13 ediciones con su número de apariciones comprobado, más las 4 del punto 4 y la de la desviación 1):
   - el `def modelos`→`def models`;
   - el `as configuracion`→`as config_module` (`checks.py:1620`);
   - `"sin_credencial"`→`"no_credential"`: 3 en código y 1 en el docstring (respuesta 9). Antes, `git grep` confirmó que solo vive en `checks.py`: no sale en `doctor --json`, en ningún texto, en los tests ni en el log;
   - las citas viejas del docstring de `chains.py` (respuesta 6): `config.VARIABLES_ROL_RETIRADO`→`config.RETIRED_FAST_ROLE_VARIABLES`, `topologia.residentes()`→`topology.residents()`, `fallido`→`has_failed`, `propios`→`own_items` y la firma `(tool, fallido, propios, nobody_else, rol)` del comentario de `LoadedProvider`;
   - las citas `` `cadenas` `` de `checks.py:1616` y `server.py:2021`, y la `(cliente, estado)` del docstring de `_entry_auth`;
   - la fila de `docs/wiki/Architecture.md:179`;
   - la fila de `residente` en «Lectura de formato viejo» de `rename-exceptions.md` (respuesta 4).
6. **Barrido final:** `a8a/leftover.py` y `git grep -w` de todos los `old` de nivel de módulo en `src/`, `tests/`, `scripts/`, `docs/` y README. No queda ninguno como identificador. Solo quedan en prosa española («las cadenas de respaldo», «describir imágenes»), en `config.py:357` (A8a-2), en el léxico del detector y en las variables propias de los tests (A9).

## Cadenas que no debían cambiar

`evidence/A8a-1/strings-check.txt`. Líneas con cada marcador en literales de `src/` y `tests/` (`git grep -c -F`, HEAD `42b420d` frente al árbol de A8a-1):

| Patrón | Antes | Después |
| --- | --- | --- |
| `local-delegate aviso` | 10 | 10 |
| `local-delegate respaldo` | 1 | 1 |
| `"aviso"` | 10 | 10 |
| `"respaldo"` | 2 | 2 |
| `"truncado"` | 15 | 15 |
| `_local_delegate` | 22 | 22 |

Contando la subcadena dentro de cualquier literal (tokenize, con docstrings): `aviso` 105 → 105, `respaldo` 72 → 72, `truncado` 30 → 30 y `_local_delegate` 17 → 17.

**Textos de `doctor` y `local_status`** (`evidence/A8a-1/output-text-check.txt`). No se corrió `local-delegate doctor`, porque sondea el backend y el daemon y aquí no se hacen pruebas en vivo. En su lugar se compararon por AST las partes literales de todas las cadenas, sin docstrings, de `checks.py` (597 antes y 597 después) y de `cadenas.py`→`chains.py` (30 y 30): **idénticas**, salvo las tres apariciones del valor interno `"sin_credencial"`→`"no_credential"`. Las partes variables de los f-string cambian de nombre, no de valor (`{chain.role.upper()}`). Lo cubren `tests/test_checks.py`, `test_doctor.py`, `test_coste_doctor.py` y `test_cadenas.py`, que afirman los textos y están en verde.

## Controles positivos

| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_cadenas.py::test_las_cadenas_por_defecto_son_las_de_la_spec` | campo `Chain.steps` devuelto a `pasos`, solo en la definición (`chains.py:64`) | `:70`, `assert chains.resolve("code").steps == (chains.LOADED, LARGO)` → `AttributeError: 'Chain' object has no attribute 'steps'` | sí (sha256 `a523f6a35a07`) |
| `tests/test_coste_doctor.py::test_comando_nunca_lanzado_y_pendientes_de_21_dias` | la palabra clave de la llamada a `_oldest_pending` devuelta a `plazo_dias=` (`checks.py:1810`) | no es un assert: `:87` (`r = _probe(...)`) → `TypeError: _oldest_pending() got an unexpected keyword argument 'plazo_dias'`, antes de los asserts de `:88-90` | sí (sha256 `31594fc35d1e`) |
| (ninguno) `tests/test_checks.py` + `test_doctor.py` | el `return (client, "no_credential")` de `_entry_auth` devuelto a `"sin_credencial"` | **no dispara** (163 pasan): ver «Hallazgos» | sí (sha256 `31594fc35d1e`) |
| A8a-2: `tests/test_aislamiento_entorno.py::test_config_solo_lee_el_entorno_por_la_puerta_registrada` | control natural: tras renombrar `config._leer`→`_read`, la cadena del guardián (`nodo.name != "_leer"`, :148) todavía sin cambiar | `:155`, `assert culpables == []` → `assert ['_read'] == []` («Estas lecturas se saltan `_leer`…»); con la cadena en `"_read"`, pasa | — (no hubo mutante: es el estado intermedio real) |
| A8a-2: `tests/test_post_chat_caminos.py::test_todos_los_caminos_devuelven_un_resultado[dice que sí y arranca]` | `answer.start` devuelto a `answer.arrancar` (`server.py:1315`) | no es un assert: `:123` → `AttributeError: '_RespuestaDelUsuario' object has no attribute 'arrancar'` | sí (sha256 `ded71889007c`) |
| A8a-2: `tests/test_web_auth.py::test_sin_cabecera_no_entra_por_ninguna_ruta[/mcp]` | `self.duration = …` devuelto a `self.duracion = …` (`web/auth.py:190`) | no es un assert: `:80` → `AttributeError: 'PortToken' object has no attribute 'duration'` | sí (sha256 `0812e6ab504d`) |
| A8a-2: (cotejo `evidence/A8a-2/schemas-check.txt`, no la suite) | `model: str = Field(title="Modelo")` sin el `Field` (`questions.py`) | el esquema de `ChooseModel` pasa a `"title": "Model"`: el cotejo daría DISTINTOS. Ningún test fija estos esquemas (ver «A8a-2 · Hallazgos») | sí (sha256 `e6d23c91a8bd`) |

Detalle en `evidence/A8a-1/mutants.txt` y `evidence/A8a-2/mutants.txt`. Tras restaurar, la suite completa está en verde.

## Hallazgos

- **El valor `"no_credential"` no lo protege ningún test.** Con el mutante M1, una entrada HTTP sin cabecera cae en la rama de «variable sospechosa». Esa rama da también `WARN` con «Claude Code», «401» y el mismo `DAEMON_TOKEN_HINT`, así que `test_una_entrada_http_sin_cabecera_contra_un_daemon_con_token_avisa` no distingue las dos ramas. No es una regresión de A8a-1 (el rename es coherente: tres sitios en el mismo fichero), pero el control no discrimina. **Propuesta:** que ese test afirme también «sin cabecera de autorización» en `result.detail`; se puede hacer en A9 o en una ola de tests.
- **Dos nombres viejos de la misma función acabaron con el mismo nombre nuevo** (`motivo` y `razon` → `reason` en `_opencode_mcp_entry`). La comprobación AST de la fase 1 solo miraba si el nombre nuevo ya existía, no si dos filas convergían en él. Lo cazó `ruff` (PLW0127, `reason = reason`) y se corrigió: ver «Desviaciones». `a8a/build.py` ya tiene la comprobación «MISMO NEW», y el mapping de A8a-2 da 0 casos.

## Llamadas `local_*` (sesión principal y cada agente)

| Quién | Tool | Para qué | Resultado (útil / corregido / descartado) |
| --- | --- | --- | --- |
| agente A8a (mapping) | `local_explain_code(path=src/local_delegate/web/auth.py)` | segunda opinión sobre los nombres de `web/auth.py` (A8a-2) | útil en parte: se adoptó `is_request_authorized`; se descartaron `PortTokenMiddleware`, `validate_session` (la función devuelve la caducidad, no un booleano) y `send_message` |
| agente A8a-1 (aplicación) | `local_lint_summary(path=evidence/A8a-1/pytest-full.log)` | resumir la suite completa | útil: solo el aviso de Starlette (`BlockingPortal`), sin fallos |
| agente A8a-1 (aplicación) | `local_lint_summary(path=evidence/A8a-1/ruff-check.txt)` | resumir `ruff check` y `ruff format --check` | útil: sin problemas, 187 ficheros |
| agente A8a-1 (aplicación) | `local_commit_msg(path=a8a/a8a1.diff)` | borrador del commit | descartado: salió en inglés y con una línea («rename chains module and i18n to English», además inexacta); el mensaje se escribió a mano en español |
| agente A8a-2 (aplicación) | `local_lint_summary(path=evidence/A8a-2/pytest-full.log)` | resumir la suite completa | útil: solo el aviso de Starlette (`BlockingPortal`), sin fallos |
| agente A8a-2 (aplicación) | `local_lint_summary(path=evidence/A8a-2/ruff-check.txt)` | resumir `ruff check` y `ruff format --check` | útil: sin problemas, 187 ficheros |

## Llamadas `mcp__pycharm__*`

| Quién | Tool | Símbolo o patrón | Resultado |
| --- | --- | --- | --- |
| agente A8a (mapping) | search_regex | los 36 nombres cross_module de la ola en `src/`, `tests/` y `scripts/` | coinciden con `git grep -w` y el AST; además, homónimos ajenos (`CAMPOS` de `vigilante_precios.py`) |
| agente A8a (mapping) | search_regex | muestra D13 de 19 module_local (semilla 8) fuera de su fichero | 0 discrepancias (solo las citas y la cadena `"_leer"` ya anotadas, y un `_pares` homónimo de `test_analisis_benchmark.py`) |
| agente A8a-1 (aplicación) | search_text | `period_days` en `checks.py` y `.resolver(role).steps` en `server.py` | PyCharm ve en disco lo de `apply` y `ren.py` antes de renombrar |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:78` `_VARIABLE_REFERENCIADA`→`_REFERENCED_VARIABLE` | ok, 2 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:511` `_clientes`→`_client_dirs` | ok, 3 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:526` `_SIN_NOMBRE`→`_UNNAMED` | ok, 2 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:530` `_TS_MINIMO`→`_MIN_TS` | ok, 3 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:533` `_momento`→`_instant` | ok, 2 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:556` `_describir`→`_describe` | ok, 1 uso |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:1112` `_autenticacion_de_la_entrada`→`_entry_auth` | ok, 4 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:1211` `_VARIABLE_DE_MCP_REMOTE`→`_MCP_REMOTE_VARIABLE` | ok, 4 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:1212` `_HOSTS_LOCALES`→`_LOCAL_HOSTS` | ok, 2 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:1215` `_desktop_conexion`→`_desktop_connection` | ok, 2 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:1767` `_MARGEN_DEL_RELLENO`→`_BACKFILL_MARGIN` | ok, 3 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `checks.py:1770` `_pendiente_mas_vieja`→`_oldest_pending` | ok, 6 usos (con documentos de `.sdd/`, devueltos) |
| agente A8a-1 (aplicación) | rename_refactoring | `cadenas.py:38` `ROLES_DE_TEXTO`→`TEXT_ROLES` | ok, 6 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `cadenas.py:45` `_SIN_RESPALDO`→`_NO_FALLBACK_VALUES` | ok, 3 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `cadenas.py:47` `CADENAS_POR_DEFECTO`→`DEFAULT_CHAINS` | ok, 4 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `cadenas.py:61` `Cadena`→`Chain` | ok, 7 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `cadenas.py:121` `_pasos`→`_steps` | ok, 1 uso |
| agente A8a-1 (aplicación) | rename_refactoring | `cadenas.py:130` `resolver`→`resolve` | ok, 25 usos |
| agente A8a-1 (aplicación) | rename_refactoring | `cadenas.py:161` `describir`→`describe` | ok, 5 usos |
| agente A8a-1 (aplicación) | lint_files | los 8 ficheros Python del diff (solo errores) | 1 aviso, el falso positivo conocido `"yaml"` de `monkeypatch.setattr(topology, "yaml", None)` en `test_cadenas.py:124` |
| agente A8a-2 (aplicación) | rename_refactoring | `benchmark.py:53` `_CORPUS_PROCEDENCIAS`→`_CORPUS_PROVENANCES` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `benchmark.py:178` `_ARNES`→`_HARNESS` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `cli.py:109` `_hay_terminal`→`_has_terminal` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `cli.py:118` `_codex_mcp_puesto_a_mano`→`_codex_mcp_set_by_hand` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `cli.py:133` `_decide_sobre_el_codex_ajeno`→`_decide_on_foreign_codex` | ok, 4 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `cli.py:160` `_reporte_del_andamiaje`→`_scaffold_report` | ok, 4 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `cli.py:250` `_deja_el_daemon_arriba`→`_leave_daemon_up` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `cli.py:269` `_avisa_si_el_cli_no_esta_en_el_path`→`_warn_if_cli_not_on_path` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `cli.py:822` `_pares`→`_pairs` | ok, 2 usos; el `_pares` homónimo de `tests/test_analisis_benchmark.py` no cambió |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:52` `SUFIJO_ROTADO`→`ROTATED_SUFFIX` | ok, 5 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:57` `CAMPOS`→`FIELDS` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:61` `_Identidad`→`_Identity` | ok, 4 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:73` `_VISTOS`→`_SEEN` | ok, 5 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:83` `_CLIENTE_ACTUAL`→`_CURRENT_CLIENT` | ok, 4 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:88` `cliente_actual`→`current_client` | ok, 3 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:105` `CLAVE_TOOL_USE_ID`→`TOOL_USE_ID_KEY` | ok, 4 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:107` `_TOOL_USE_ID_ACTUAL`→`_CURRENT_TOOL_USE_ID` | ok, 6 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:115` `_MEMORIA_PETICION`→`_REQUEST_MEMORY` | ok, 6 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:120` `tool_use_id_actual`→`current_tool_use_id` | ok, 4 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:125` `memoria_de_peticion`→`request_memory` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:130` `_tool_use_id_de`→`_tool_use_id_from` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:145` `nombres_capabilities`→`capability_names` | ok, 6 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:161` `_rotar_si_toca`→`_rotate_if_due` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:187` `_escribir_linea`→`_write_line` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:200` `ruta_registro`→`log_path` | ok, 7 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:212` `rutas_para_leer`→`paths_to_read` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:227` `registrar`→`record` | ok, 12 usos; con las dos cadenas de monkeypatch de `test_clients.py` |
| agente A8a-2 (aplicación) | rename_refactoring | `clients.py:294` `observar_cliente`→`observe_client` | ok, 15 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `config.py:32` `_VARIABLES_LEIDAS`→`_READ_VARIABLES` | ok, 6 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `config.py:35` `_leer`→`_read` | ok, 10 usos; la cadena del guardián (`test_aislamiento_entorno.py:148`), no: a mano |
| agente A8a-2 (aplicación) | rename_refactoring | `config.py:110` `TIMEOUT_SONDA_CONEXION`→`PROBE_CONNECT_TIMEOUT` | ok, 8 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `config.py:111` `TIMEOUT_SONDA_LECTURA`→`PROBE_READ_TIMEOUT` | ok, 7 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `config.py:115` `TIMEOUT_CONEXION_DELEGACION`→`DELEGATION_CONNECT_TIMEOUT` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `config.py:315` `MAX_CHARS_POR_ROL`→`MAX_CHARS_BY_ROLE` | ok, 6 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `config.py:322` `modelos_por_rol`→`models_by_role` | ok, 10 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `config.py:365` `rol`→`role` | ok, 3 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `config.py:415` `_lectura`→`_reader` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `config.py:525` `VARIABLES_DE_ENTORNO`→`ENVIRONMENT_VARIABLES` | ok, 30 usos; no tocó el dato de prueba de `tests/test_detect_spanish_names.py:44` |
| agente A8a-2 (aplicación) | rename_refactoring | `daemon.py:226` `daemon_registrado`→`registered_daemon` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `estado_json.py:16` `leer_json`→`read_json` | ok, 4 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `estado_json.py:26` `escribir_json_atomico`→`write_json_atomic` | ok, 5 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `install.py:587` `_REFERENCIA_RE`→`_REFERENCE_RE` | ok, 3 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `install.py:590` `cabecera_existente`→`existing_header` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `install.py:619` `_con_cabecera`→`_with_header` | ok, 3 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `install.py:673` `_sin_secretos`→`_without_secrets` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `install.py:781` `_escanear_jsonc`→`_scan_jsonc` | ok, 3 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `install.py:836` `tiene_comentarios`→`has_comments` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `install.py:1351` `_OPENCODE_NO_TOCADO`→`_OPENCODE_UNTOUCHED` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `install.py:1358` `_leer_config_opencode`→`_read_opencode_config` | ok, 4 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `install.py:1375` `_motivo_para_no_escribir`→`_reason_not_to_write` | ok, 3 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `preguntas.py:42` `ModeloT`→`ModelT` | ok, 3 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `preguntas.py:46` `CTX_ACTUAL`→`CURRENT_CTX` | ok, 11 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `preguntas.py:49` `recordar_contexto`→`remember_context` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `preguntas.py:60` `puede_preguntar`→`can_ask` | ok, 8 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `preguntas.py:83` `preguntar`→`ask` | ok, 19 usos; con 12 cadenas de monkeypatch `"preguntar"`→`"ask"` (la de `test_post_chat_caminos.py:105`, a mano) |
| agente A8a-2 (aplicación) | rename_refactoring | `preguntas.py:135` `ArrancarBackend`→`StartBackend` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `preguntas.py:141` `ElegirModelo`→`ChooseModel` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `preguntas.py:147` `ElegirFormato`→`ChooseFormat` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `residency.py:241` `_par`→`_pair` | ok, 4 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `topology.py:225` `_usa_matrix`→`_uses_matrix` | ok, 3 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `topology.py:526` `usa_matrix`→`uses_matrix` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `update.py:614` `_sigue_sirviendo`→`_still_serving` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `web/auth.py:54` `DURACION_POR_DEFECTO`→`DEFAULT_DURATION` | ok, 5 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `web/auth.py:57` `_token_presentado`→`_presented_token` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `web/auth.py:85` `peticion_autorizada`→`is_request_authorized` | ok, 7 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `web/auth.py:100` `es_basic`→`is_basic` | ok, 1 uso |
| agente A8a-2 (aplicación) | rename_refactoring | `web/auth.py:113` `_firma`→`_sign` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `web/auth.py:120` `crear_sesion`→`create_session` | ok, 15 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `web/auth.py:126` `sesion_valida`→`valid_session` | ok, 9 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `web/auth.py:182` `TokenPuerto`→`PortToken` | ok, 3 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `web/auth.py:192` `_entregando_sesion`→`_delivering_session` | ok, 2 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `web/auth.py:254` `proteger`→`protect` | ok, 6 usos |
| agente A8a-2 (aplicación) | rename_refactoring | `entrypoint.py:25` `_aviso_de_terminal_interactiva`→`_interactive_terminal_warning` | ok, 8 usos; con la cadena de monkeypatch de `test_ctrl_c.py:43` |
| agente A8a-2 (aplicación) | search_text | `self.duration` en `web/auth.py` y `model_answer.model` en `server.py` | PyCharm ve en disco lo de `apply` y `ren.py` antes de renombrar |
| agente A8a-2 (aplicación) | lint_files | 20 ficheros Python del diff (solo errores) | 1 aviso, el falso positivo conocido `"Client"` de `monkeypatch.setattr(httpx2, "Client", …)` en `test_doctor.py:399` |

## Revisión del diff tras rename_refactoring

- **Documentos históricos de `.sdd/`.** PyCharm reescribió 4: `coste-api-y-cuota/evidencias/T7.md`, `coste-api-y-cuota/review.md`, `daemon-reparte-el-backend/evidencias/T12.md` y `english-names-bilingual-output/research-i18n.md`. Se devolvieron con `git checkout`.
- **Homónimos.** `.modelos` de `scripts/construir_corpus.py`, las variables propias de los tests (`cadena`, `ruta`, `texto`…) y el léxico del detector no cambiaron.
- **Marcadores.** Ver «Cadenas que no debían cambiar».
- **Código inalcanzable.** No se reescribió ninguna función; solo cambiaron nombres, más la corrección de la desviación 1.
- **Prosa.** Los docstrings y comentarios citan los nombres nuevos entre comillas invertidas y la prosa sigue en español. No se coló ninguna palabra inglesa: las ediciones de citas fueron explícitas, y PyCharm no tocó prosa en los ficheros de la ola.

## Scripts (REQ-014, solo olas que renombran en src/)

| Script | `--help` | Corrida mínima o `get_file_problems` |
| --- | --- | --- |
| CLI `local-delegate` (usa `checks`, que importa `chains`) | `uv run local-delegate --help`: ok (`evidence/A8a-1/smoke.txt`) | `chains.resolve` sobre `TEXT_ROLES` da `mechanical/long/code`; `import local_delegate.cadenas` da `ModuleNotFoundError` (sin alias, como se aprobó); `lint_files` en los 8 ficheros |

## Desviaciones y nombres «(plan)» ajustados

1. **`razon`→`read_error`, no `reason`** (`checks.py:1012`, `_opencode_mcp_entry`). Con el nombre aprobado chocaba con `motivo`→`reason` de la misma función: `apply` produjo `if reason and reason is None: reason = reason`, una autoasignación que rompía la lógica («el primer motivo gana»). La cazó `ruff` (PLW0127). Se corrigió a mano, con la fila del CSV actualizada y su motivo. La suite pasó después del arreglo. **Pide visto bueno** del nombre `read_error`.
2. **Fuera de «posee», por consecuencia mecánica** (ya listado en la cabecera del CSV aprobado): `src/local_delegate/server.py` (el import en varias líneas de :40, :1640, :1995, :2021 cita, :2030, :2135, :2137, :2167 y :4459) y `docs/wiki/Architecture.md:179`. Tests: `test_affinity.py`, `test_cadenas.py`, `test_checks.py`, `test_respaldo.py` y `test_rol_fast_retirado.py`.
3. **Registro de la ola.** Mientras A8a-2 no estaba aplicada, este fichero citaba solo el mapping de A8a-1 (19 = 19). Con A8a-2 cita los dos: 92 = 92.
4. **El control del guardián `"_leer"`** de `tests/test_aislamiento_entorno.py:148` no es de A8a-1: `_leer` vive en `config.py`, que es de A8a-2. Pasa a esa subola, con su control positivo.

## Pendientes

- **A8b:** el JS y los ids del DOM de `web/metrics.py`, y las **34 filas** de la parte Python de `web/metrics.py` (:226-:804: `estado`, `filas`, `ventanas`, `por_evento`, `_lista`…), según la respuesta 11. El build está en `a8a/A8a-extra.csv` del scratchpad.
- **A9:** los nombres `test_*`, las variables propias de los tests (p. ej. la lista local `preguntas` de `test_checks.py:1435` y los parámetros `mensaje`/`modelo` de los dobles), los ficheros `test_cadenas.py` y `test_preguntas.py`, el test de `no_credential` de «Hallazgos» y un test que fije los esquemas de `elicitation` (hallazgo de A8a-2).
- **A10 (respuesta 3):** las claves y valores persistidos de `benchmark.py`: `"procedencia"` (:108, :119, :1284) con `congelado/generado/reconstruido/inventado`, `"descartada"`/`"descartada_motivo"` (:1310-1311), `"truncado_repetido"` (:330), `"rechazo_por_contexto"` (:1103), `_CORPUS_MEDIA = {"texto", "imagen"}` y los ficheros temporales del arnés (`generado.py`, `comprobaciones.json`). Los leen `scripts/analizar_benchmark.py` y `construir_corpus.py` y los guardan los corpus congelados de `benchmarks/`: van con lectura dual o a la lista de excepciones.
- **Abierto, sin ola (respuesta 8):** las claves de huella `"ruta"`, `"tamano_bytes"` y `"modelo"` de `matrix.py:64-65`, `footprint.py:29/138-139` y `checks.py:1534`. No se tocan; la sesión principal decide su destino.

---

## A8a-2 — resto de `src/` (aplicada)

- Rama: `sdd/english-names-a8a-2`, encima de `0d49cbf` (`main` con A8a-1, #269)
- REQ cubiertos: REQ-014 (módulos `estado_json`→`json_state`, `preguntas`→`questions` y `sondas`→`probes`, de D3), REQ-015 (identificadores internos de `install`, `cli`, `clients`, `web/auth`, `config`, `benchmark`, `daemon`, `update`, `topology`, `residency`, `entrypoint`, `footprint`, `llamaswap_config` y `test_windows`) y REQ-017
- Ficheros poseídos: los de plan.md A8a menos `checks.py` y `cadenas.py`, más `entrypoint.py`, `footprint.py`, `llamaswap_config.py` y `test_windows.py` (respuesta 11), con sus tests. Lo de fuera, en «A8a-2 · Fuera de “posee”»
- Mapping: `waves/A8a-2-mapping.csv` aprobado, **241 filas**: las 233 de la fase 1 más las 8 de `A8a-extra.csv` que no son de `web/metrics.py`, con los nombres de la sesión principal. Filas `pycharm` 73 = filas `rename_refactoring` 73. Filas `search_edit` 168, cada una con su motivo: 160 con `make_mapping.py apply` (511 reemplazos), 5 con `a8a/ren.py` (`a8a/ops-2.json`: `procedencia` de `CorpusCase`, `arrancar`/`modelo`/`formato` de los tres formularios y `self.duracion` de `PortToken`) y 3 de módulo (`git mv` + `a8a/modren.py`)
- Antes de aplicar se repitió la comprobación AST sobre `main` con A8a-1 (`a8a/check2.py`: la línea de cada definición contiene `old`; el nombre nuevo no choca en su ámbito; dos `old` del mismo ámbito no van al mismo `new`): **1 choque**, que se corrigió (desviación 1), y después 0
- EOL: `evidence/A8a-2/eol-check.txt`. Solo cambian las líneas de los tres renames de módulo, cada uno con su EOL: `estado_json.py`→`json_state.py` LF, `sondas.py`→`probes.py` LF y `preguntas.py`→`questions.py` CRLF. Todas las ediciones desde fuera, con Python y `newline=""`; `ruff format` conserva el EOL
- Tests recogidos: antes 2567 (`evidence/A8a-2/collect-before.txt`) → después 2567 (2565 pasan + 2 saltados), +0 −0
- Suite: `evidence/A8a-2/pytest-full.log` (con `pesado.sh`, en serie), verde: 2565 pasan, 2 saltados y el aviso conocido de Starlette, en 4 min 18 s
- `ruff check` y `ruff format --check` (mismo alcance que A8a-1): limpios (`evidence/A8a-2/ruff-check.txt`). Antes, `ruff check --select I --fix` reordenó 5 bloques de imports que el rename de módulos desordenó, y `ruff format` reformateó 5 ficheros por longitud de línea
- Detector (`evidence/A8a-2/detector-after.json`): 6966 → 6764 (−202); fuera de la lista 6959 → 6757. En los ficheros de la subola solo quedan: las claves y valores persistidos de `benchmark.py` (pendiente de A10), los alias de nombres viejos de `config.py`/`cli.py` (variables y `recalcular-coste`, ya decididos) y las claves de huella de `footprint.py` (pendiente abierto)
- Tamaño: 53 ficheros, 785 líneas cambiadas (`git diff -M --numstat --ignore-cr-at-eol`)

### A8a-2 · Qué se hizo

1. **`apply`** (511 reemplazos en 15 ficheros), antes que nada.
2. **`ren.py`**: 1+1+1 en `benchmark.py` (campo, `ctor` y `case.provenance`); los campos de los tres formularios en `questions.py` y sus accesos en `server.py` (1 + 2 + 2); el `self.arrancar` del doble de `tests/test_post_chat_caminos.py:28`; y 7 `self.duracion` en `web/auth.py`.
3. **PyCharm, 73 `rename_refactoring`.** Antes, `search_text` confirmó que PyCharm veía en disco lo de `apply` y `ren.py`. PyCharm cambió también 12 de las 13 cadenas `"preguntar"` de monkeypatch, `"registrar"`, `"_escribir_linea"`, `"_VARIABLES_LEIDAS"`, `"modelos_por_rol"` y `"_aviso_de_terminal_interactiva"`. Reescribió **29** documentos de `.sdd/`, que se devolvieron con `git checkout`; también el `A8a.md` de `main`, que luego se rehízo con este registro. El barrido AST posterior (`a8a/leftover.py`) confirmó que no deshizo nada de `apply` ni de `ren.py`.
4. **Módulos:** `git mv` de los tres y `a8a/modren.py` para imports y prefijos. A mano, lo que el script no ve:
   - los imports en varias líneas de `server.py:45/51` y `checks.py:48`;
   - los primeros argumentos de `monkeypatch.setattr(<módulo>, …)` y `server.preguntas,` en siete tests.

   El script cambió por error la lista local `preguntas` de `tests/test_checks.py:1438` (`preguntas.append`), que no es el módulo; se devolvió a mano. Esa lista es de A9.
5. **A mano** (`a8a/manual2.py`, 36 ediciones con su número de apariciones comprobado, más 32 líneas de citas):
   - los `def` de las anidadas: `send_wrapper`, `_with_timeout`, `_kept` y `_detail`;
   - `{motivo}`→`{reason}` y `motivo=`→`reason=` (respuesta 7);
   - `TypeVar("ModelT")` y los cuatro nombres de `ContextVar` (respuesta 5): `"current_ctx"`, `"local_delegate_current_client"`, `"local_delegate_current_tool_use_id"` y `"local_delegate_request_memory"`;
   - el guardián `"_leer"`→`"_read"`;
   - `model = LARGO` del doble `_Eleccion`;
   - los formularios con `Field(title=…)` y `model_config = ConfigDict(title=…)` (ver «A8a-2 · Esquemas»);
   - las citas viejas (respuesta 6): `foto()`→`snapshot()` ×2, `cadenas.py`→`chains.py` (la de `config.py:357` que dejó A8a-1), `coste.py`→`cost.py`, `fundir`→`cost.merge`, `nuevo`→`new` y `recordar_contexto`/`preguntar` en `questions.py`;
   - las citas de los módulos renombrados en `checks.py`, `doctor.py`, `probes.py`, `server.py`, `tests/test_preguntas.py` y la wiki;
   - 32 líneas con citas de los nombres de esta subola, en `src/` (`attribution`, `checks`, `clients`, `config`, `daemon`, `install`, `llamaswap_api`, `matrix`, `update`, `web/metrics`) y en tests (`conftest`, `test_aislamiento_entorno`, `test_atribucion`, `test_checks`, `test_clients`, `test_commit_language`, `test_ctrl_c`, `test_metrics`, `test_preguntas`, `test_web_auth`).

   Se quedan, a propósito, la ruta histórica `.sdd/changes/elicitation-preguntar-en-vez-de-fallar/` (`questions.py:9`) y el léxico y los datos de prueba del detector.
6. **Barrido final:** `a8a/leftover.py` con todos los `old` del mapping sobre todo `src/`: no queda ninguno como identificador, salvo las variables propias de la parte Python de `web/metrics.py`, que son de A8b. Y `git grep -w` de los cuatro nombres de módulo: solo quedan en prosa española («las sondas», «dos preguntas») y en la lista local de `test_checks.py`.

### A8a-2 · Esquemas de los formularios (respuesta 2)

`evidence/A8a-2/schemas-before.txt`, `schemas-after.txt` y `schemas-check.txt`: `model_json_schema()` de cada formulario, antes con el nombre viejo y después con el nuevo.

| Antes → después | Propiedad | `required` | Título del campo (visible) | `title` del esquema | Resto |
| --- | --- | --- | --- | --- | --- |
| `ArrancarBackend` → `StartBackend` | `arrancar` → `start` | `["arrancar"]` → `["start"]` | «Arrancar» → «Arrancar» | `ArrancarBackend` → `ArrancarBackend` | igual |
| `ElegirModelo` → `ChooseModel` | `modelo` → `model` | `["modelo"]` → `["model"]` | «Modelo» → «Modelo» | `ElegirModelo` → `ElegirModelo` | igual |
| `ElegirFormato` → `ChooseFormat` | `formato` → `format` | `["formato"]` → `["format"]` | «Formato» → «Formato» | `ElegirFormato` → `ElegirFormato` | igual |

El cotejo normaliza solo la clave de la propiedad y `required`, y da **IGUALES** en los tres. El `title` raíz del esquema sale en pydantic del nombre de la **clase**. Para que no cambiara al renombrar la clase hizo falta `model_config = ConfigDict(title="<nombre viejo>")`, además del `Field(title=…)` de cada campo: ver desviación 2. `python -W error` sobre `model_json_schema()` no da avisos: el campo `model` no choca con el espacio protegido `model_` de pydantic.

### A8a-2 · Cadenas protegidas y textos de salida

`evidence/A8a-2/strings-check.txt`. Por líneas (`git grep -c -F`), sin cambios: `local-delegate aviso` 10/10, `local-delegate respaldo` 1/1, `"aviso"` 10/10, `"respaldo"` 2/2, `"truncado"` 15/15 y `_local_delegate` 22/22. Por subcadena dentro de literales: `respaldo` 72/72, `truncado` 30/30 y `_local_delegate` 17/17. **`aviso` pasa de 105 a 104**: el único literal que la perdió es la cadena de monkeypatch `"_aviso_de_terminal_interactiva"` de `tests/test_ctrl_c.py:43`, que es el nombre de la función renombrada (`_interactive_terminal_warning`), no un marcador. Comprobado con `git diff` de las líneas con `aviso`.

`evidence/A8a-2/output-text-check.txt`: partes literales de las cadenas, sin docstrings, de los 25 ficheros de `src/` tocados, por AST. **Idénticas en 21.** Las diferencias, todas previstas:
- `questions.py`: los títulos `Field`/`ConfigDict` añadidos, el `TypeVar` y el `ContextVar`;
- `clients.py`: los tres nombres de `ContextVar`;
- `install.py`: `{motivo}`→`{reason}` dentro del texto de `_OPENCODE_UNTOUCHED`, que es el nombre del campo de formato y no se ve en la salida.

### A8a-2 · Fuera de «posee» (consecuencia mecánica, lista cerrada de la cabecera del CSV)

`src/local_delegate/server.py` (imports y usos de `json_state`, `questions`, `clients`, `config`), `checks.py` (import y usos de `probes` y sus citas, respuesta 1; y `clients.paths_to_read`, `config.PROBE_*` y `config.models_by_role`), `cooldown.py:42` (import), `doctor.py` (import, `probes.` y citas), `attribution.py:242/245/248`, `chains.py:138` (`config.models_by_role`), `llamaswap_api.py:72-73`, `matrix.py:129` (cita), `web/metrics.py:917/926/928`, `scripts/construir_corpus.py:692`, `docs/wiki/Architecture.md:67/68/173` y `docs/wiki/Backend-versions.md:17`. Tests: `conftest.py`, `test_affinity.py`, `test_aislamiento_entorno.py`, `test_atribucion.py`, `test_cadenas.py`, `test_checks.py`, `test_cli_renamed_names.py`, `test_clients.py`, `test_commit_language.py`, `test_ctrl_c.py`, `test_delegacion_conexion.py`, `test_densidad.py`, `test_deprecations.py`, `test_doctor.py`, `test_fallos_integracion.py`, `test_install_opencode.py`, `test_metrics.py`, `test_post_chat_caminos.py`, `test_preguntas.py`, `test_respaldo.py`, `test_rol_fast_retirado.py`, `test_smoke.py`, `test_turn_daemon.py` y `test_web_auth.py`.

### A8a-2 · Scripts (REQ-014)

| Script | `--help` | Corrida mínima o `get_file_problems` |
| --- | --- | --- |
| CLI `local-delegate` | `uv run local-delegate --help`: ok (`evidence/A8a-2/smoke.txt`) | `json_state.read_json`, `questions.ask` y `probes.RECOMMENDED_VERSIONS` se importan; `local_delegate.estado_json`/`preguntas`/`sondas` dan `ModuleNotFoundError` (sin alias, como se aprobó); `lint_files` en 20 ficheros |

### A8a-2 · Desviaciones

1. **`ahora`→`now_s`, no `now`** (`test_windows.py:142`, `Windows.find`). El nombre decidido chocaba con el parámetro `now` de la misma función: `ahora` son los segundos epoch de ese instante. Está anotado en la columna `reason` y en la cabecera del CSV. **Pide visto bueno.**
2. **`model_config = ConfigDict(title="ArrancarBackend"|"ElegirModelo"|"ElegirFormato")`** en los tres formularios. Sin eso, el `title` raíz del esquema cambiaba con el nombre de la clase (`StartBackend`…), y la respuesta 2 pedía que solo cambiara la clave. Así quedan en el código tres cadenas en español (el detector no las marca hoy). Son texto del formulario: van con los títulos de campo al frente B (B2), que decide si los traduce. **Pide visto bueno.**
3. **Corrección de `modren.py`**: la lista local `preguntas` de `tests/test_checks.py:1438` se renombró por error y se devolvió a mano (ver «Qué se hizo», punto 4).

### A8a-2 · Hallazgos

- **Ningún test fija los esquemas de `elicitation`.** Con el mutante M3 (sin `Field(title="Modelo")`), el título visible pasa a «Model» y la suite sigue verde. Solo lo detecta el cotejo de `evidence/A8a-2/schemas-check.txt`. **Propuesta para A9:** un test que fije `model_json_schema()` de los tres formularios.
- **El guardián del aislamiento del entorno sí discrimina.** En el estado intermedio real (función ya renombrada y cadena todavía vieja) falla con `['_read']`.
