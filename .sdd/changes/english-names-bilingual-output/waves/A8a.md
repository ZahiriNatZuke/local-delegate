# Ola A8a — Resto de `src/` (Python): `checks`, `cadenas`, `estado_json`, `preguntas`, `sondas` y diez módulos más

La ola se parte en dos suboles con un PR cada una (D13: 384 filas, y el máximo es 300 por lote).
**A8a-1** (`checks.py` y `cadenas.py`→`chains.py`) está aplicada y registrada aquí. **A8a-2** (el
resto) tiene el mapping aprobado, pero todavía no se ha aplicado: su sección es un borrador. Este
registro cita solo el mapping de la subola aplicada. Cuando se aplique A8a-2, su sección añadirá
el suyo con la ruta completa y sus 72 `rename_refactoring`, para que las cuentas de
`check_wave_records.py` sigan cuadrando.

- Rama: `sdd/english-names-a8a` · PR: (lo abre la sesión principal) · Commit(s): A8a-1 pendiente, con el borrador en `waves/A8a-1-commit-msg.txt` (firmado y sin coautoría), encima de `42b420d` (`main` con A7b mezclada, #268)
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

Detalle en `evidence/A8a-1/mutants.txt`. Tras restaurar, la suite completa está en verde.

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
3. **Registro de la ola.** Este fichero cita solo el mapping de A8a-1, para que `check_wave_records.py` compare 19 = 19. El de A8a-2 se nombra sin ruta hasta que se aplique.
4. **El control del guardián `"_leer"`** de `tests/test_aislamiento_entorno.py:148` no es de A8a-1: `_leer` vive en `config.py`, que es de A8a-2. Pasa a esa subola, con su control positivo.

## Pendientes

- **A8a-2** (borrador abajo): `estado_json`, `preguntas`, `sondas` (con sus usos en `checks.py`) y los otros once módulos, más la cita `` `cadenas.py` `` de `config.py:357`.
- **A8b:** el JS y los ids del DOM de `web/metrics.py`, y las **34 filas** de la parte Python de `web/metrics.py` (:226-:804: `estado`, `filas`, `ventanas`, `por_evento`, `_lista`…), según la respuesta 11. El build está en `a8a/A8a-extra.csv` del scratchpad.
- **A9:** los nombres `test_*`, las variables propias de los tests, los ficheros `test_cadenas.py` y `test_preguntas.py`, y el test de `no_credential` de «Hallazgos».
- **A10 (respuesta 3):** las claves y valores persistidos de `benchmark.py`: `"procedencia"` (:108, :119, :1284) con `congelado/generado/reconstruido/inventado`, `"descartada"`/`"descartada_motivo"` (:1310-1311), `"truncado_repetido"` (:330), `"rechazo_por_contexto"` (:1103), `_CORPUS_MEDIA = {"texto", "imagen"}` y los ficheros temporales del arnés (`generado.py`, `comprobaciones.json`). Los leen `scripts/analizar_benchmark.py` y `construir_corpus.py` y los guardan los corpus congelados de `benchmarks/`: van con lectura dual o a la lista de excepciones.
- **Abierto, sin ola (respuesta 8):** las claves de huella `"ruta"`, `"tamano_bytes"` y `"modelo"` de `matrix.py:64-65`, `footprint.py:29/138-139` y `checks.py:1534`. No se tocan; la sesión principal decide su destino.

---

## A8a-2 — borrador (mapping aprobado, sin aplicar)

- **Mapping:** `A8a-2-mapping.csv` (233 filas; pycharm 72; search_edit 161 = `apply` 153 + `ren.py` 5 + módulos 3; function_local 153, cross_module 44, module_local 36). En la fase 1, `apply --dry-run` dio 480 reemplazos y el ensayo completo en una copia del repo, 43 ficheros y 653 líneas cambiadas.
- **Respuestas que aplican:**
  - (2) los campos del formulario pasan a `start`/`model`/`format` **con `Field(title=…)`**, que conserva el título visible actual: el JSON schema de cada modelo tiene que quedar igual salvo la clave, y se compara antes y después;
  - (5) los nombres de los `ContextVar` se renombran con sus constantes;
  - (6) las citas viejas en docstrings (`topology.py` `foto()`, `config.py` `coste.py`, `cli.py` `fundir` y `nuevo`), a mano;
  - (7) `{motivo}`→`{reason}` y `reason=` en `install.py:1353/1471`, a mano;
  - (11) entran las 8 filas de `entrypoint.py` (`_aviso_de_terminal_interactiva`, `interactiva`), `footprint.py` (`actual`), `llamaswap_config.py` (`tamanos`) y `test_windows.py` (`tope`, `ahora`, `fin`, `abiertas`): su `new` se rellena en esa fase y la sesión principal lo revisa.
- **Antes de aplicar:** volver a correr `a8a/build.py`, que ya comprueba «MISMO NEW», sobre el árbol con A8a-1 mezclada. Los números de línea de `checks.py` no cambiaron, pero `server.py` sí cambió en A8a-1.
- **A mano en A8a-2:** el guardián `"_leer"` de `tests/test_aislamiento_entorno.py:148`, con su control positivo; los `def` de las anidadas `enviar`, `_con_plazo`, `_conservada` y `_detalle`; `modelo = LARGO` del doble `_Eleccion` (`tests/test_respaldo.py:431`); las cadenas de monkeypatch (`"preguntar"` ×13, `"registrar"` ×2, `"_escribir_linea"`, `"_VARIABLES_LEIDAS"`, `"modelos_por_rol"`) y `TypeVar("ModeloT")`.
- **Fuera de «posee»** (lista cerrada en la cabecera del CSV): `server.py`, `cooldown.py`, `doctor.py`, `attribution.py`, `llamaswap_api.py`, `matrix.py` (cita), `web/metrics.py:917/926/928`, `scripts/construir_corpus.py:692`, `docs/wiki/Architecture.md:67/68/173`, `Backend-versions.md:17`, y `checks.py` en sus usos de `sondas` (respuesta 1).
