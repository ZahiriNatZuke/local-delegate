# Ola A9b — Tests `e*`–`p*`

La subola se parte en 6 lotes (D13: 1507 filas, como mucho 300 por lote y sin partir un módulo):
`A9b-1-mapping.csv` a `A9b-6-mapping.csv` (en `waves/`), aprobados por la sesión principal el
2026-10-13 con las 8 decisiones de la fase 1 tal como se recomendaron. Cada lote es un commit que
hace la sesión principal, en una rama apilada sobre el anterior. Las tablas de controles positivos,
`local_*` y PyCharm son las de todos los lotes, porque `check_wave_records.py` lee la primera tabla
de cada sección; por ahora solo está el **lote 1**: 17 filas `rename_refactoring` = 17 filas
`pycharm` de `waves/A9b-1-mapping.csv`.

- Rama: lote 1 en `sdd/english-names-a9b-1`, apilada sobre `sdd/english-names-a9a-7` (`76fe954`, A9a
  completa) · Commit del lote 1: pendiente, con el borrador en `waves/A9b-1-commit-msg.txt` (firmado
  y sin coautoría)
- Quién: un agente hizo los 6 mappings (fase 1) y, tras la aprobación, aplicó el lote 1 (fase 2).
- Conteo base: `evidence/A9b/collect-before.txt`, 2569 tests.

## Controles positivos

| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_cooldown.py::test_three_consecutive_failures_cool_the_model_for_120_s` (lote 1; usa la fixture renombrada `clock`/`path`, `_state` y `_fail`) | `src/local_delegate/cooldown.py:167`: `>= self._failures` → `> self._failures` (enfría al fallo N+1) | `assert cooled is not None` → `assert None is not None` | sí, desde copia; sha256 igual al de antes (`evidence/A9b-1/mutant.txt`) |
| `tests/test_failure_captures.py::test_the_timeout_during_loading_is_capacity` (lote 1; usa `_capture`, `_classify_capture` y las claves nuevas del envoltorio) | en `_classify_capture`, la guarda vuelve a la clave vieja (`"excepcion" in doc`), que es el error que dejó el primer reemplazo | `KeyError: 'response'` en `doc["response"]` | sí, desde copia; sha256 igual |
| `tests/test_cooldown.py` (40 tests) | `_fail` registra un fallo menos (`range(times - 1)`) | 7 fallan; el primero, `assert cooled is not None` | sí, desde copia; sha256 igual |

## Llamadas `local_*` (sesión principal y cada agente)

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente A9b (fase 1) | `local_summarize(path=waves/A9a.md)` | lecciones y desviaciones de los 7 lotes de A9a, sin meter las 592 líneas al contexto |
| Agente A9b-1 | `local_lint_summary(path=evidence/A9b-1/pytest-full-run1.log)` | resumen de la primera corrida de la suite (3 fallos: 1 real del lote y 2 de tiempos de `test_fake_llamaswap`) |

## Llamadas `mcp__pycharm__*`

| Agente | Tool | Símbolo / fichero | Resultado |
| --- | --- | --- | --- |
| A9b-1 | `rename_refactoring` | `INICIO`→`START` (`test_enfriamiento.py`) | 7 usos |
| A9b-1 | `rename_refactoring` | `Reloj`→`Clock` | 2 usos |
| A9b-1 | `rename_refactoring` | `avanzar`→`advance` | 15 usos |
| A9b-1 | `rename_refactoring` | fixture `reloj`→`clock` | 83 usos (arrastra los 32 parámetros que la piden) |
| A9b-1 | `rename_refactoring` | fixture `ruta`→`path` | 96 usos (ídem; no toca los parámetros locales `ruta` de los ayudantes) |
| A9b-1 | `rename_refactoring` | `_estado`→`_state` | 34 usos |
| A9b-1 | `rename_refactoring` | `_fallar`→`_fail` | 48 usos |
| A9b-1 | `rename_refactoring` | `_eventos`→`_events` | 11 usos |
| A9b-1 | `rename_refactoring` | `_viejo`→`_old` | 2 usos |
| A9b-1 | `rename_refactoring` | `_nuevo`→`_new` | 6 usos |
| A9b-1 | `rename_refactoring` | `_mismo_estado`→`_same_state` | 4 usos; reescribió `waves/A4.md` (devuelto a HEAD) |
| A9b-1 | `rename_refactoring` | `_escribir`→`_write` | 3 usos, solo en su fichero |
| A9b-1 | `rename_refactoring` | `_respuesta_http`→`_http_response` (`test_fallos.py`) | 6 usos |
| A9b-1 | `rename_refactoring` | `_cuerpo`→`_body` | 11 usos |
| A9b-1 | `rename_refactoring` | `_captura`→`_capture` (`test_fallos_capturas.py`) | 6 usos |
| A9b-1 | `rename_refactoring` | `_modelo_cargado_al_terminar`→`_model_loaded_at_end` | 3 usos |
| A9b-1 | `rename_refactoring` | `_clasificar_captura`→`_classify_capture` | 5 usos |
| A9b-1 | `get_file_problems` | `test_cooldown.py`, `test_failures.py`, `test_failure_captures.py` | 0 errores salvo `Unresolved reference 'FileLock'` en la cadena de `monkeypatch.setattr(cooldown, "FileLock", …)`: falso positivo que ya existía (el atributo se resuelve en tiempo de ejecución) |

## A9b-1 — capturas de `tests/fixtures/backend`, `test_enfriamiento`, `test_fallos` y `test_fallos_capturas` (aplicado)

### A9b-1 · Qué se hizo

- 17 `rename_refactoring` (tabla de arriba), en los ficheros con su nombre viejo y antes de cualquier
  edición desde fuera (lección de A5b-1).
- `make_mapping.py apply` con una copia del CSV cuyas definiciones llevan ya los ámbitos renombrados
  por PyCharm (`Reloj.avanzar` → `Clock.advance`…; si no, `apply` no encuentra la función): 232 + 65 +
  47 = 344 reemplazos.
- A mano (`apply` no lo hace): la clase anidada `BloqueoOcupado`→`BusyLock`, la anidada
  `sin_disco`→`without_disk`, los argnames de 6 `parametrize` (`neutra`, `excepcion` ×3, `datos`,
  `viejo,nuevo`, `nombre`), el atributo `ahora`→`now` y los parámetros `reloj` de `_estado` y
  `clase`/`estado`/`modelo` de `_fallar`, con los 3 kwargs `clase=`→`failure_class=` de sus llamadas.
- `git mv` de 3 módulos (`test_cooldown.py`, `test_failures.py`, `test_failure_captures.py`) y de
  las 6 capturas (`load-error.json`, `length-with-reasoning.json`, `oom-with-profile.json`,
  `oom-without-profile.json`, `request-during-load.json`, `timeout-during-load.json`); dentro de
  ellas, 13 claves del envoltorio y el valor de `case` (67 cambios); en el test, 24 lecturas y nombres
  de captura. Los ids de modelo `cap-*` no se tocan (son los de la captura real).
- `ruff format` reflowó una línea de `test_cooldown.py` (`10 ** 7` cabe ahora en una línea).
- EOL: los ficheros tocados son LF y siguen LF (`git ls-files --eol`).

### A9b-1 · Fuera del lote (consecuencia mecánica, aprobada)

- `src/local_delegate/failures.py:73`: cita `tests/test_failure_captures.py`.
- `tests/test_fallos_integracion.py:5` (lote 2): cita `test_failures.py` en su docstring.

### A9b-1 · Barrido final

- AST de los 3 ficheros: ningún nombre de código con un `old` del lote; las cadenas con una clave
  vieja del envoltorio, 0.
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 67 en
  textos (38 docstrings, 17 comentarios y 12 cadenas): prosa en español y valores de prueba.
  Ninguna cita entre comillas invertidas de un nombre renombrado.
- En todo el repo (fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`): `test_enfriamiento`,
  `test_fallos_capturas`, `BloqueoOcupado`, `_clasificar_captura`, `muestras_running`,
  `clase_esperada`… 0. Quedan `cap-error-carga` y `cap-oom-con-perfil` dentro de las capturas: son
  ids de modelo, datos (decisión 7).
- `--collect-only`: 2569 (`evidence/A9b-1/collect.txt`), los mismos 40 + 50 + 10 tests por módulo.
- Suite: 2567 passed, 2 skipped (`evidence/A9b-1/pytest-full.log`). `ruff check` y
  `ruff format --check` en verde (`evidence/A9b-1/ruff-check.txt`).
- CodeQL (aproximación AST de `a9b/codeql_like.py` sobre los 3 ficheros renombrados): 0 patrones.
  Los dos `except OSError: pass` con comentario de la fase 1 están en `test_panel_coste.py:486` y
  `test_precios.py:201`: no son de este lote, se miran en el lote que renombra esos ficheros.

### A9b-1 · Desviaciones

1. **37 filas `pycharm` → `search_edit`**, anotado en la línea `# Fase 2` del CSV: los 32 parámetros
   `reloj` de los tests (los arrastró el `rename_refactoring` de la fixture), el atributo homónimo
   `ahora` (también existe en `_Mezcla` de `test_metrics.py`) y los parámetros homónimos de `_estado`
   y `_fallar`.
2. **Una clave del envoltorio se escapó al reemplazo por `["clave"]`**: `if "excepcion" in doc` en
   `_classify_capture` y `assert "excepcion" not in doc`. La primera hizo fallar
   `test_the_timeout_during_loading_is_capacity` (`KeyError: 'response'`). La segunda **pasaba**
   igual y había dejado de comprobar nada. Se cambiaron las dos. Lección para los lotes siguientes:
   buscar también `"clave" in` / `not in`, no solo `["clave"]` y `.get(`.
3. Primera corrida de la suite: además, 2 fallos de tiempos en `test_fake_llamaswap.py`
   (`t_unload` 4,23 > 4,0 y un 500 en vez de 502 bajo carga). Pasaron sueltos y en la segunda
   corrida completa; no son de este lote (`evidence/A9b-1/pytest-full-run1.log`).

## Pendientes

1. Lotes A9b-2 a A9b-6, cada uno con su sección.
2. En el lote 6: el test nuevo de los esquemas de `elicitation` y el arreglo de la carrera de
   `test_turn_wait_shown_in_panel_as_local_wait` (cabecera de `A9b-6-mapping.csv`).
3. Para los lotes que tocan claves en cadenas: buscar también `"clave" in doc` (desviación 2).
