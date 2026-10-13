# Ola A9a — Tests `conftest.py`, fixtures de datos y módulos `a*`–`d*`

La subola se parte en 7 lotes (D13: 1788 filas, máximo 300 por lote y sin partir un módulo, salvo
la excepción aprobada del JS de `test_dashboard_ui.py`, que va al lote 7). Cada lote es un commit
que hace la sesión principal, en una rama apilada sobre el anterior. Este registro empieza por el
**lote 1**; los siguientes añaden su sección. Las tablas de controles positivos, `local_*` y PyCharm
de la primera sección son las del lote 1 (`check_wave_records.py` lee la primera tabla de cada
sección).

- Rama: `sdd/english-names-a9a`, desde `main` en `f4a869f` (A8b mezclada) · PR: (lo abre la sesión principal) · Commit del lote 1: pendiente, con el borrador en `waves/A9a-1-commit-msg.txt` (firmado y sin coautoría)
- Quién: un agente hizo los 7 mappings (fase 1). Tras la aprobación de la sesión principal (decisiones 1-8, con `esp`→`expected` y `clase`→`css_class`/`cls`/`content_class` según lo que nombre), el mismo agente aplicó el lote 1 (fase 2)
- REQ cubiertos por el lote 1: REQ-015 (nombres de `tests/conftest.py`, `tests/backend_mock.py`, `test_agents.py`, `test_aislamiento_entorno.py`→`test_environment_isolation.py` y `test_atribucion.py`→`test_attribution.py`, más los directorios de fixtures `residencia`→`residency` y `topologia`→`topology`) y REQ-017 (ningún assert cambia de sentido)
- Ficheros poseídos por el lote 1: `tests/conftest.py`, `tests/backend_mock.py`, `tests/test_agents.py`, `tests/test_aislamiento_entorno.py`, `tests/test_atribucion.py` y `tests/fixtures/{residencia,topologia}/`. Lo de fuera, en «Desviaciones»
- EOL: `evidence/A9a-1/eol-check.txt` (EOL de HEAD frente al de trabajo en cada fichero del diff, con los renombres seguidos): 0 diferencias. Todo LF salvo `residency/pre-b10909-20260915.yaml`, que sigue `mixed` y con `-text` en `.gitattributes`. Todas las ediciones desde fuera, con Python y `newline=""`
- Mapping: `waves/A9a-1-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 294 filas. Filas `pycharm` 37 = filas `rename_refactoring` 37. Filas `search_edit` 257, cada una con su motivo: 239 con `make_mapping.py apply` (601 reemplazos; más el `def` de 10 anidadas con `a9a/nested_defs.py`), 12 parámetros y atributos homónimos pasados de `pycharm` a `search_edit` en la fase 2 (`a9a/lineedit.py`), 2 módulos y 4 directorios o ficheros de fixtures con `git mv`
- Tests recogidos: antes 2567 (`evidence/A9a/collect-before.txt`) → después 2567 (`evidence/A9a-1/collect.txt`), +0 −0. Por fichero, iguales: `test_atribucion.py` 33 → `test_attribution.py` 33 y `test_aislamiento_entorno.py` 5 → `test_environment_isolation.py` 5
- Suite: `evidence/A9a-1/pytest-full.log` (`pytest -q -n auto --dist loadgroup` como el CI, con `pesado.sh`), verde: 2565 pasan, 2 saltados y el aviso ya conocido de Starlette (`BlockingPortal`, 12 veces, una por worker), en 59 s. Una corrida anterior (`pytest-full-run2-flaky.log`) dio 1 fallo en `test_dashboard_ui.py::test_la_unidad_de_los_kpis_no_se_corta[ancha]`, que no toca este lote: suelto pasó 3 de 3, y la corrida siguiente salió entera en verde
- `ruff check` y `ruff format --check` sobre `src tests scripts .sdd/changes/english-names-bilingual-output/tools`: limpios (`evidence/A9a-1/ruff-check.txt`, 187 ficheros). `ruff format` reajustó 4 ficheros a los que el rename cambió el largo de línea (`test_agents.py`, `test_attribution.py`, `test_observabilidad_respaldo.py`, `test_rol_fast_retirado.py`); esos 4 se volvieron a pasar después (73 pasan)
- Tamaño: 28 ficheros, +824 −813 (`git diff HEAD -M30% --numstat --ignore-cr-at-eol`). `test_atribucion.py`→`test_attribution.py` queda en el 46 % de similitud: git solo lo sigue como rename con `-M30%` (`git log --follow -M30%`)

## Controles positivos

| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_attribution.py::test_does_not_read_more_than_256_kb` (usa los renombrados `_ReadSpy`, `.reads`, `_stream`, `_spy`, `_projects`, `_write_note`, `_tool_use_line`) | `src/local_delegate/attribution.py`: `TAIL_BYTES = 256 * 1024` → `512 * 1024` (sha256 `32d9a7febbed` → `9d774322a27d`: el mutante muta) | `tests/test_attribution.py:383` `assert spy.reads <= 256 * 1024` → `assert 524288 <= (256 * 1024)`; la guarda `spy.reads > 0` de :382 pasa, así que el test llegó a leer (`evidence/A9a-1/mutant.txt`) | sí: `git checkout` devolvió la versión de HEAD y se repuso la cita de :17 de la ola; sha256 `32d9a7febbed`, igual que antes del mutante |

## Llamadas `local_*` (sesión principal y cada agente)

| Quién | Tool | Para qué | Resultado (útil / corregido / descartado) |
| --- | --- | --- | --- |
| agente A9a-1 | `local_lint_summary(path=evidence/A9a-1/pytest-full.log)` | resumen de la suite | útil: solo los 12 avisos de `BlockingPortal` de Starlette, ningún fallo |

Fase 1 (mappings): 0 llamadas, porque hacían falta líneas literales (contexto de cada nombre, reglas del brief) y las listas largas fueron a ficheros del scratchpad, leídos por franjas.

## Llamadas `mcp__pycharm__*`

| Quién | Tool | Símbolo o patrón | Resultado |
| --- | --- | --- | --- |
| agente A9a-1 | `rename_refactoring` | `conftest.recargar_config` → `reload_config` | 222 usos; tocó también 4 docs de `.sdd/` (devueltos con `git checkout`) |
| agente A9a-1 | `rename_refactoring` | `conftest.entorno_sin_variables_del_paquete` → `env_without_package_variables` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `conftest.sin_lista_de_modelos_guardada` → `no_saved_model_list` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `backend_mock._rutas` → `_routes` | 8 usos (también `test_cadenas.py:279`) |
| agente A9a-1 | `rename_refactoring` | `backend_mock._Llamadas` → `_Calls` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `backend_mock._Llamada` → `_Call` | 4 usos |
| agente A9a-1 | `rename_refactoring` | `backend_mock.Ruta` → `Route` | 6 usos |
| agente A9a-1 | `rename_refactoring` | `backend_mock.Ruta._coincide` → `_matches` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `backend_mock.Ruta._resolver` → `_resolve` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `backend_mock._activo` → `_active` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `test_agents.ANCLA` → `ANCHOR` | 3 usos |
| agente A9a-1 | `rename_refactoring` | `test_agents.AJENO` → `FOREIGN` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `test_agents.SIN_SECCION` → `NO_SECTION` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `test_agents.DELEGADOR` → `DELEGATOR` | 9 usos |
| agente A9a-1 | `rename_refactoring` | `_nombre_de_llamada` → `_call_name` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `_variables_que_leen_los_hooks` → `_variables_read_by_hooks` | 3 usos |
| agente A9a-1 | `rename_refactoring` | `con_alias` → `with_alias` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `AGENTE` → `AGENT` | 6 usos |
| agente A9a-1 | `rename_refactoring` | `_entorno_del_hook` → `_hook_env` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `_lanzar_hook` → `_launch_hook` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `_dir_notas` → `_notes_dir` | 3 usos |
| agente A9a-1 | `rename_refactoring` | `_entrada_hook` → `_hook_input` | 5 usos |
| agente A9a-1 | `rename_refactoring` | `_linea_tool_use` → `_tool_use_line` | 14 usos |
| agente A9a-1 | `rename_refactoring` | `_proyectos` → `_projects` | 9 usos |
| agente A9a-1 | `rename_refactoring` | `_escribir` → `_write` | 11 usos |
| agente A9a-1 | `rename_refactoring` | `_anotar` → `_write_note` | 17 usos |
| agente A9a-1 | `rename_refactoring` | `_Contador` → `_Counter` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `_EspiaDeLectura` → `_ReadSpy` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `log_y_notas` → `log_and_notes` | 0 usos (los parámetros ya los había renombrado `apply`) |
| agente A9a-1 | `rename_refactoring` | `_lineas` → `_lines` | 4 usos |
| agente A9a-1 | `rename_refactoring` | `_log_minimo` → `_minimal_log` | 4 usos |
| agente A9a-1 | `rename_refactoring` | `_en_peticion` → `_in_request` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `_Espia` → `_Spy` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `_peticiones` → `_requests` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `_relleno_viejo` → `_old_backfill` | 7 usos |
| agente A9a-1 | `rename_refactoring` | `ENTRADAS_VIEJAS` → `OLD_ENTRIES` | 8 usos |
| agente A9a-1 | `rename_refactoring` | `_temporal` → `_tmp_dir` | 3 usos |
| agente A9a-1 | `get_file_problems` | `tests/test_attribution.py`, `tests/backend_mock.py`, `tests/conftest.py` (solo errores) | 0 errores |

## Revisión del diff tras rename_refactoring

- PyCharm reescribió documentos de `.sdd/` (`daemon-reparte-el-backend/evidencias/renombrado.md`, `delegacion-precisa-y-fiable/plan.md` y `verification.md`, `english-names-bilingual-output/research-rename.md`, `review.md` y `waves/A1.md`, y `panel-cuentas-y-estados-honestos/verification.md`): devueltos con `git checkout`. Los 7 mappings A9a no los tocó (comparados byte a byte con la regeneración).
- No dejó palabras inglesas en prosa española. Comentarios que siguen citando `recargar_config` en `test_respaldo.py:127` y `test_topes_por_rol.py:23`: se cambiaron a mano. Citas entre comillas invertidas repuestas a mano: `conftest.py:75`, `test_environment_isolation.py:35` y `test_attribution.py:325`/`:427`.
- Las ediciones de `apply` hechas antes en disco siguieron ahí tras los renames (comprobado: `mocked_client`, `def wrapper`, `isolate_logs`).

## Scripts (REQ-014, solo olas que renombran en src/)

| Script | `--help` | Corrida mínima o `get_file_problems` |
| --- | --- | --- |
| (ninguno) | no aplica: el lote 1 solo toca comentarios de `src/` (`config.py:229`, `attribution.py:17`) | no aplica |

## Barrido final (lote 1)

- AST (`a9a/sweep_after.py`) sobre los 5 ficheros del lote: no queda ninguna definición con un `old` del lote ni ninguna en español según el detector. Uso de código con un `old`: solo la clave `roto=` de `_agents_dir(**files)` en `test_agents.py:162`, que genera el nombre de fichero `roto.md` (dato, como `delegador=`, decisión 6).
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 139 en textos (87 docstrings, 38 cadenas y 14 comentarios). Son prosa en español y datos de prueba (`"sesion-sintetica"`, `"relleno": "x"`, `"valida"`, los ids de parametrize…). Las citas entre comillas invertidas se repusieron.
- `git grep` en todo el repo (fuera de `.sdd/` y `benchmarks/`) de los nombres propios del lote (`test_aislamiento_entorno`, `test_atribucion`, `recargar_config`, las dos fixtures autouse, `fixtures/residencia`, `fixtures/topologia`, los `test_*` del lote): 0. Los nombres comunes (`_escribir`, `_lineas`, `_espia`, `Ruta`…) que salen en otros ficheros son definiciones homónimas de otros módulos (A9a lotes 2-7, A9b, A9c y A10) o prosa.
- `residencia`/`topologia` en tests: solo quedan prosa, la línea 1 del fixture (el nombre del `.bak` real, dato) y el subcomando `llamaswap residencia` de `test_residency.py:1159`.

## Desviaciones y nombres «(plan)» ajustados

1. **Fuera de los ficheros del lote, por consecuencia mecánica** (aprobado):
   - la fixture `recargar_config`→`reload_config` arrastra sus parámetros en `test_cadenas.py`, `test_checks.py`, `test_cli_renamed_names.py` (lotes 2-4), `test_observabilidad_respaldo.py`, `test_respaldo.py`, `test_rol_fast_retirado.py`, `test_slowness.py` y `test_topes_por_rol.py`. Por eso las filas `recargar_config` de los lotes 2-4 quedan sin efecto (`apply` no encontrará nada que cambiar);
   - `backend_mock._rutas` en `test_cadenas.py:279`; el kwarg `crudo=`→`raw=` de `write_claude_desktop` en `test_checks.py:1365` (el parámetro local `crudo` de `_con_desktop` es del lote 3);
   - rutas de fixtures en `test_cadenas.py`, `test_checks.py`, `test_doctor.py`, `test_panel_estados.py`, `test_residency.py`, `test_residency_cli.py`, `test_topology.py`, `test_turn_daemon.py` y `.gitattributes:27` (conserva `-text`);
   - citas del fichero de test en `src/local_delegate/config.py:229`, `src/local_delegate/attribution.py:17`, `tests/test_cadenas.py:214` y `tests/test_commit_language.py:72`.
2. **12 filas `pycharm` → `search_edit`** (parámetros y atributos homónimos: `crudo`, `metodo`, `_pila`, `modelo`, `sesion`, `lineas`, `caso`, `_flujo`, `_espia`, `leidos`, `llamadas`, `mes`). Lección de A5b-1: con homónimos PyCharm puede elegir otro símbolo. Se editaron por línea, acotadas a su función o clase, a sus llamadas por keyword y a la cadena de `parametrize("case")`. El CSV aprobado lo anota en una línea `# Fase 2`.
3. **La anidada `delega`→`delegates` es además el nombre de una tool MCP de prueba** (`@server.tool()` toma el nombre de la función). La primera corrida dio 2 fallos en `test_attribution.py` (`call_tool("delega")` → tool desconocida). Se cambió también la cadena `"delega"` de `call_tool` (`:516`): es un nombre interno del test, no del producto.
4. **Lecciones para los lotes 2-7:** `apply` no reescribe el `def` de las anidadas (lo hace `a9a/nested_defs.py`), ni los kwargs ni las cadenas de `parametrize`. Una anidada decorada como tool MCP lleva su nombre en una cadena.

## Pendientes

- **Tests nuevos sin renombrado** (respuesta de la sesión principal): el test de `no_credential` («Hallazgos» de A8a-1) va en el lote 3, porque su módulo es `test_checks.py`. El test que fija los esquemas de `elicitation` es de `test_preguntas.py`: va en A9b.
- **A9b:** `tests/fixtures/backend/*.json` (nombres en español, los usa `test_fallos_capturas.py`); `test_preguntas.py`; lo de `test_panel_estados.py` heredado de A8b.
- **Lotes 2-7:** aplicar sus mappings con las lecciones de arriba.
