# Ola A8b — JS del panel, ids del DOM y parte Python de `web/metrics.py`

- Rama: `sdd/english-names-a8b`, desde `main` en `d8fe747` (A8a-2 mezclada) · PR: (lo abre la sesión principal) · Commit: pendiente, con el borrador en `waves/A8b-commit-msg.txt` (firmado y sin coautoría)
- Quién: un agente hizo el mapping (fase 1). Tras la aprobación de la sesión principal (decisiones 1-8), el mismo agente lo aplicó y lo verificó (fase 2).
- REQ cubiertos: REQ-009 (identificadores propios del JS e ids del DOM), REQ-015 (identificadores internos de la parte Python de `web/metrics.py`) y REQ-017 (ningún assert cambia de sentido)
- Ficheros poseídos: `src/local_delegate/web/metrics.py` (parte Python :226-:860, `<script>`, CSS y marcado), `tests/test_dashboard_ui.py` (CRLF), `tests/test_dashboard_js.py` y `scripts/extract_dashboard_js.py` (sin cambios: no tiene nombres en español). Lo de fuera, en «Desviaciones»
- EOL: `evidence/A8b/eol-check.txt` (`git ls-files --eol`): ningún fichero cambia de EOL. `metrics.py`, `server.py` y `test_dashboard_ui.py` siguen CRLF y el resto LF. Todas las ediciones, con Python y `newline=""`
- Mapping: `waves/A8b-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 148 filas. Filas `pycharm`: 0, así que tampoco hay filas `rename_refactoring`, porque el JS vive dentro de una cadena Python. Filas `search_edit`: 148, cada una con su motivo. Hay 35 Python, que aplica `make_mapping.py apply` (124 reemplazos), y 113 JS/DOM, que aplica el script de tokens `a8b/apply_js.py` (363 tokens, 36 ids, 8 `data-group`, 7 estados y 2 de la clase `dimmed`)
- Tests recogidos: antes 2567 (la misma HEAD que A8a-2) → después 2567 (2565 pasan y 2 saltados), +0 −0
- Suite: `evidence/A8b/pytest-full.log` (`pytest -q -n auto --dist loadgroup` como en el CI, con `pesado.sh`). Sale verde: 2565 pasan, 2 saltados y el aviso ya conocido de `BlockingPortal`, en 56 s
- Playwright: `evidence/A8b/playwright.log` (`test_dashboard_ui.py`, `test_panel_estados.py` y `test_panel_coste.py`). Pasan 78 y se salta 1 (`test_dashboard_ui.py:1319`, que solo aplica al CI)
- `ruff check` y `ruff format --check` sobre `src tests scripts tools`: limpios (`evidence/A8b/ruff-check.txt`, 187 ficheros)
- Detector (`evidence/A8b/detector-after.json`, con `--exceptions rename-exceptions.md`). Los hallazgos únicos bajan de 6760 a 6611 (−149) y los de fuera de la lista, de 6753 a 6602 (−151). En `web/metrics.py` quedan:
  - `meterHTML` y `quotaMeter`, en excepciones;
  - la clave `desconocido`, que queda pendiente;
  - 9 `js_string`, que son textos visibles (`montado`, `cargando`, `descargando`, `procesando`, `remoto`/`Remoto`, `llamada`, `fallo`) y el locale `de-DE`.
  Ya no queda ningún `dom_id` (eran 19). Las 5 palabras «sin clasificar» nuevas son inglesas: `aim`, `decimals`, `dimmed`, `negatives` y `paint`
- Tamaño: 12 ficheros, +491 −481 líneas (`git diff -M --numstat --ignore-cr-at-eol`)

## Alcance de A8b

- **Qué entró:**
  - las 34 variables locales Python de `web/metrics.py` que la respuesta 11 cedió desde A8a, más `por_ext`→`by_ext`, que el detector no ve;
  - 88 nombres del `<script>`: funciones, constantes, variables, parámetros y claves de objetos propios del panel (`vista`→`view`, `estado`→`status`, `texto`→`text`, `clase`→`cls`, `atenuada`→`dimmed`…);
  - los 19 ids del DOM, con sus `getElementById`, el `#id` del CSS y los `data-section`;
  - los `data-group` `coste`/`sistema`→`cost`/`system`;
  - los estados internos `conectado`/`comprobando`/`caido`→`connected`/`checking`/`down`;
  - la clase CSS `.mrow.atenuada`→`.mrow.dimmed`.
- **Excluido a propósito:**
  - los textos visibles (rótulos, los textos de estado de los modelos y las claves de `DOT`, que son ese texto);
  - la clave `desconocido` (decisión 6);
  - la clave legada `'sin dato'` de `LABELS.effort`;
  - `meterHTML` y las clases `.meter*` (decisión 7);
  - los nombres `test_*` y las variables propias de los tests (A9);
  - el JS propio de `scripts/dev/capture_dashboard.py` (A10);
  - los datos de prueba del detector (`KNOWN_SPANISH`).

## Qué se hizo

1. **`make_mapping.py apply`** con el CSV aprobado: 124 reemplazos en `web/metrics.py`, con las filas `function_local` acotadas a su función. Después, a mano, el `def _lista`→`def _as_list` de la función anidada, que `apply` no reescribe.
2. **`a8b/apply_js.py`**, que usa el tokenizador de A0 con la posición de cada nombre (la misma fuente con una línea cambiada):
   - reemplaza tokens enteros dentro del `<script>` en todos sus roles: nombre suelto, `.propiedad` y `clave:` (363);
   - con `to`/`toRep` solo dentro de `acct`;
   - los estados, solo en `status:'…'` y `status==='…'` (7), porque `'conectado'` y `'comprobando…'` siguen siendo el texto visible del indicador del backend;
   - la cadena `' atenuada'`, el selector `.mrow.atenuada`, los 8 `data-group` y los ids como palabra entera en todo el fichero (36).
   - `node --check` del JS extraído: ok.
3. **A mano**, las citas de nombres en comentarios y docstrings:
   - en `metrics.py`, el comentario del diálogo (`costText/quotaText/imagesText`), `renderTestsInfo`, `claudeTokens` (×2), `fmtSec` y `opts.withNegatives`;
   - en los tests, con `a8b/apply_tests.py` (nombres distintivos como palabra entera, sin tocar los `test_*` ni las variables Python);
   - las claves y estados de `test_panel_estados.py`, línea a línea: `.estado`, `state.vista`, `{modelo:`, `vista:` y `["texto"]`/`["clase"]`/`["atenuada"]`, y los estados que se afirman en :122-125 y :602. No se tocaron los `"conectado"` que afirman el texto del indicador;
   - `test_detect_spanish_names.py:61` (`JS_CONTROL_NAMES`);
   - las citas de `tokensClaude` en `server.py:885`, `docs/wiki/Savings-and-metrics.md:158` y `scripts/dev/capture_dashboard.py:132`.
4. **`rename-exceptions.md`**: sección nueva «Palabra inglesa que el léxico toma por española», con `meterHTML` y `quotaMeter`, y su motivo añadido a la lista de motivos válidos (decisión 7; ver «Desviaciones»).
5. **Barrido final** (`a8b/final_sweep.py`):
   - Python: ningún nombre viejo de las filas `function_local` queda en el AST de `metrics.py`;
   - JS: solo queda `to` como token, en las claves de rango (`{from, to}`, fuera de `acct`), que es la excepción aprobada;
   - cadenas: solo queda `'conectado'` como texto visible del indicador;
   - ninguno de los 19 ids viejos aparece en `metrics.py`.

## Cadenas que no debían cambiar

`evidence/A8b/strings-check.txt`. Literales del `<script>` (cadenas y trozos de plantilla, por el tokenizador de A0) de HEAD frente al árbol: 1149 y 1149. Difieren 21, todos previstos: 13 ids pasados a `getElementById`, 7 estados internos y `' atenuada'`→`' dimmed'`. **Ningún texto visible cambió.**

## Controles positivos

| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_metrics.py::test_paridad_acct_entre_python_y_el_js_del_panel` | `acct` renombrada solo en el test: `_acct_en_js` extrae `"function account(e){"` | no es un assert: `:1082`, `fuente.index(cabecera)` → `ValueError: substring not found`. La paridad no corre con una cabecera que el panel no tiene | sí (sha256 `3a09cee4cc50`) |
| `tests/test_metrics.py::test_paridad_acct_entre_python_y_el_js_del_panel` | renombrado parcial simulado en `acct`: `tOutRep ? tOut :`→`tOutRep ? tIn :` | `assert js.get(campo_js) == py[campo_py]` → `AssertionError: ('tokens_out', …)`, `assert 1100 == 90` | sí (sha256 `3a09cee4cc50`) |
| `tests/test_panel_coste.py` (8 tests) | control natural: primera corrida de la suite con `"function dolares("` sin cambiar en el test | no es un assert: `ValueError: substring not found` en `_extraer` de `test_panel_coste.py`, en los 8 tests que montan `costText`/`costCells`. Pasan al corregirlo | — (estado intermedio real, ver «Desviaciones») |

Detalle en `evidence/A8b/mutants.txt`. Tras restaurar, la suite completa está en verde.

## Hallazgos

- **El detector solo ve el primer nombre de una declaración con comas** (`const a = …, b = …`): `js_declared_names` toma el nombre que sigue a `const`/`let`. Se le escapaban `todos`, `aFichero`, `hayImg` y `enRango`, que entraron porque la fase 1 barrió todos los tokens. **Propuesta:** arreglarlo antes del cierre del frente A, porque ese cierre exige que el detector dé 0.
- **Los nombres de cabecera en minúsculas se le escaparon a la lista de tests de la fase 1** (`"function dolares("` en `test_panel_coste.py`). El arrastre a los tests buscó solo nombres camelCase y en mayúsculas. Lo cazó la suite. Lección: buscar `function <old>(`, `_f("<old>")` y `const <old> =` de **todos** los nombres viejos en los tests que leen `metrics.HTML`.
- **Capturas** (`scripts/dev/capture_dashboard.py` y `a8b/capture_a8b.py`, contra `metrics.app` del árbol en el 9494, no contra el daemon, con los mocks deterministas):
  - el panel se ve completo en oscuro y en claro;
  - el indicador dice «conectado» y `state.view.status` vale `connected`;
  - las tarjetas de coste e imágenes se pintan; la de cuota, oculta, como corresponde a una cuota sin calibrar;
  - los diálogos de coste (`dlgCost`, `dlgQuota`, `dlgImages`) y de sistema (`dlgSystem`) se abren con su título y su texto;
  - 0 errores de página o de consola.
  No hizo falta marcar ninguna ventana de prueba: no se habló con el daemon ni se delegó nada.
- **`lint_files` de PyCharm** da 3 «Unresolved reference» en `test_panel_coste.py:433/:480` y `test_metrics.py:440`. Son cadenas de `monkeypatch.setattr` que A8b no tocó: falsos positivos que ya estaban.

## Llamadas `local_*` (sesión principal y cada agente)

| Quién | Tool | Para qué | Resultado (útil / corregido / descartado) |
| --- | --- | --- | --- |
| agente A8b (aplicación) | `local_lint_summary(path=a8b/suite.txt)` (primer intento) | resumir la suite | descartado: se lanzó antes de que existiera el fichero y devolvió error |
| agente A8b (aplicación) | `local_lint_summary(path=a8b/suite.txt)` | resumir la suite completa (copiada en `evidence/A8b/pytest-full.log`) | útil: solo los 12 avisos de `BlockingPortal`, sin fallos |
| agente A8b (mapping) | ninguna | — | motivo: todo pedía texto literal (nombres, líneas y contexto para elegir los nombres nuevos) y se resolvió con scripts y lecturas por franjas |

El mensaje de commit se escribió a mano: `local_commit_msg` sale en inglés y truncado (lección de A0-A2).

## Llamadas `mcp__pycharm__*`

| Quién | Tool | Símbolo o patrón | Resultado |
| --- | --- | --- | --- |
| agente A8b (mapping) | search_regex | `estadoVisible\|textoCoste\|aplicarBackend\|costeBody\|tokensClaude\|fmtSeg`, fuera de `.sdd`, CHANGELOG y benchmarks | destapó 4 ficheros más de `tokensClaude` (`server.py:885`, `test_densidad.py:69`, la wiki y `capture_dashboard.py`), añadidos a la cabecera del mapping |
| agente A8b (aplicación) | lint_files | los 8 ficheros Python cambiados (`metrics.py` y los 7 tests), severidad error | 3 falsos positivos que ya estaban (cadenas de `monkeypatch`), ninguno en líneas de A8b |

No hay filas `rename_refactoring`: el mapping no tiene filas `pycharm`.

## Desviaciones

1. **Ficheros fuera de «posee»** (consecuencia mecánica, aprobados en la cabecera del mapping):
   - `tests/test_panel_estados.py`, `tests/test_panel_coste.py`, `tests/test_detect_spanish_names.py:61`, `tests/test_metrics.py:1270-1271` y `tests/test_densidad.py:69`;
   - las citas de `src/local_delegate/server.py:885`, `docs/wiki/Savings-and-metrics.md:158` y `scripts/dev/capture_dashboard.py:132`;
   - `rename-exceptions.md`.
2. **`"function dolares("` de `tests/test_panel_coste.py:161/:621`**: no estaba en la lista de la cabecera. Es una cabecera literal que extrae el test, así que es consecuencia mecánica de `dolares`→`dollars`. Se corrigió tras la primera corrida (ver «Controles positivos»).
3. **`quotaMeter` también va a excepciones.** Es el nombre nuevo aprobado de `medidorCuota` y trae el mismo falso positivo que `meterHTML` («meter»). **Pide visto bueno.** La alternativa es `quotaGauge`, sin excepción.
4. **Motivo nuevo en `rename-exceptions.md`** («palabra inglesa que el léxico toma por española»), porque la lista de REQ-016 no lo preveía. Se aplicó con la decisión 7. **Pide visto bueno** de la enmienda.

## Pendientes

- **Sin ola (decisión 6):** la clave `desconocido`. La emite el servidor como cliente por defecto (`web/metrics.py:365`), la traduce `LABELS.client` (:1897) y la afirman `test_metrics.py:1624` y `test_dashboard_ui.py:936`. Si se traduce, van servidor, JS y tests a la vez, con lectura dual si llega a persistirse. La sesión principal decide su destino.
- **A9:**
  - los nombres `test_fmtHace_cambia_de_unidad_en_las_fronteras` y `test_acct_convierte_solo_con_tokensClaude`;
  - las variables Python de los tests: `_SONDEO`, `_texto_pruebas`, `_TEXTO_PRUEBAS`, `clase, texto` de `test_panel_estados.py:183` y la clave `modelo` de los casos de `test_panel_estados.py` (`c.modelo`, :238);
  - los objetos JS propios de `test_dashboard_ui.py` (`texto:`, `const coste`, `const fila`, `const sistema`).
- **A10:** el JS propio de `scripts/dev/capture_dashboard.py` (`porPath`, `densidadDe`, `celda`, `clase`, `DENSIDAD`, `CLASE_TOOL`…).
- **Cierre del frente A:** el hueco del detector con las declaraciones con comas (ver «Hallazgos»).
