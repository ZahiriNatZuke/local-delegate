# Specification: Ruido del CI arreglado de raíz: gate, tests de coste, E/S real, huellas y CodeQL

## Summary

Un run de `ci.yml` sale rojo solo cuando algo del repo está mal. Lo que no depende del código (un
runner de macOS que GitHub no asignó, la carga de los workers de xdist sobre un reloj, un pwsh roto
en la imagen, una descarga lenta) deja un aviso y no un rojo; lo que sí depende (huellas, versión de
la captura, nombres, catálogo) falla antes, en local. Y tras mezclar se miran también las alertas de
CodeQL de `main`.

## Requirements

- **REQ-001** — `ci_gate.py` da por bueno, con aviso nombrado en el informe y en el resumen del job,
  un job `cancelled` sin runner asignado (`runner_id` vacío y `runner_name` vacío) y sin ningún paso
  ejecutado. Un `cancelled` con runner o con algún paso ejecutado, y todo `timed_out`, siguen siendo
  fallo.
  - Request: "un job cancelado SIN runner asignado (cancelado por infraestructura, sin pasos ejecutados) NO cuenta como fallo. Sale como aviso y macOS se sigue exigiendo cuando sí corre. Un cancelado con pasos ejecutados, o por timeout, sigue contando."
  - Verify: test tests/test_ci_gate.py
- **REQ-002** — `pyproject.toml` registra los marcadores `perf` y `real_io`. Los pasos de pytest de
  `test` y `test-lang-es` corren `-m "not perf and not real_io"` con `-n auto`; después, un paso
  corre `-m real_io` sin `-n` y, si falla, repite una vez solo los fallidos (`--lf`). Un job `perf`
  en Ubuntu corre `-m perf` sin `-n`, con el mismo reintento, y figura en `EXPECTED_JOBS`.
  - Request: "marcador `perf` en `pyproject.toml`. Los jobs del gate corren `-m \"not perf\"` y un job aparte en Ubuntu corre los `perf` sin `-n`, con un reintento."
  - Verify: test tests/test_ci_gate.py
- **REQ-003** — `tests/perf.py` mide con `time.perf_counter_ns` repitiendo cada lado hasta superar
  50 ms, compara dos tamaños y falla cuando la proporción supera `size_ratio ** 1.5`; un coste lineal
  simulado pasa y uno cuadrático simulado falla.
  - Request: "un helper común que mida con `perf_counter_ns` repetido hasta superar unos 50 ms (nunca `process_time`) y compruebe crecimiento (proporción entre dos tamaños con margen), nunca segundos fijos."
  - Verify: test tests/test_perf_helper.py
- **REQ-004** — Todo test que medía un coste de cómputo con un tope en segundos usa `tests/perf.py` y
  lleva `@pytest.mark.perf`; `tests/linear_cost.py` desaparece.
  - Request: "Migra los 26 ficheros al helper y al marcador."
  - Verify: test tests/test_timing_marker_guard.py
- **REQ-005** — Un guardián falla si un test compara con `<`, `<=`, `>` o `>=` una lectura de reloj
  (`time.time`, `perf_counter`, `process_time`, `monotonic`, también `_ns`) o usa `tests/perf.py` sin
  el marcador `perf` o `real_io`, y si aparece `process_time` en `tests/` fuera del propio guardián.
  Controles: un fuente sintético con tope y sin marcador se detecta; con marcador, o con el reloj
  solo como plazo de una espera, no.
  - Request: "Un guardián (test) que falle si un test nuevo usa `time.time`/`perf_counter`/`process_time` con un tope sin el marcador `perf`."
  - Verify: test tests/test_timing_marker_guard.py
- **REQ-006** — Los tests que esperan a procesos, sockets o relojes reales con un tope de pared
  (entre ellos `test_daemon_dead_listener`, `test_desktop_bridge` contra el daemon real y
  `test_hook_project` con el presupuesto del recorrido) llevan `real_io` y corren en serie en los
  tres sistemas, con un reintento.
  - Request: "Tests de red y procesos reales: en un `xdist_group` propio o con el marcador `perf`/`real_io` y reintento"
  - Verify: test tests/test_timing_marker_guard.py
- **REQ-007** — Un pwsh que se cae al arrancar (la sonda `$PSVersionTable` no responde) salta sus
  tests con un motivo que nombra la versión, y la guarda de shells exigidas lo convierte en aviso
  (`::warning::`) en vez de fallo; un pwsh que arranca y luego falla sigue en rojo.
  - Request: "`pwsh exit=-6`: comprobar la versión del pwsh del runner y saltar con aviso si se cae al arrancar."
  - Verify: test tests/test_completion_shell_startup.py
- **REQ-008** — `scripts/check_local.py`, enganchado en `.pre-commit-config.yaml`, corre en local
  las comprobaciones de huellas de los hooks, nombres en español, catálogo de textos y versión de la
  captura, y falla con el remedio. `bump_version.py <versión>` regenera siempre las huellas y las
  capturas; `release.py` se niega a publicar con huellas o capturas viejas.
  - Request: "un hook de pre-commit (o `scripts/check_local.py`, mira qué usa ya el repo) que corra `bump_version.py --boundaries` y el detector de nombres en español y el catálogo de textos, para que fallen en local; y que `scripts/release.py` regenere huellas y capturas siempre."
  - Verify: test tests/test_check_local.py
- **REQ-009** — En `lint` y `test-lang-es` la descarga del navegador se reintenta con un número
  acotado de intentos y un tope por intento que caben en el límite del paso; la caché y el
  reintento de apt siguen.
  - Request: "La instalación de dependencias del navegador en `lint` y `test-lang-es`, con caché y reintento."
  - Verify: test tests/test_ci_gate.py
- **REQ-010** — `scripts/check_main.py` lista los checks no verdes del último commit de `main` y las
  alertas abiertas de CodeQL de `main`, y sale con código distinto de 0 si hay alguno; la wiki
  (`Repo-hardening.md`) y `CONTRIBUTING.md` lo nombran como paso tras mezclar.
  - Request: "Un paso o script de comprobación tras mezclar que liste también las alertas abiertas de CodeQL en `main` (...) y documentarlo en la wiki de contribución."
  - Verify: test tests/test_check_main.py
- **REQ-011** — El CHANGELOG («Sin publicar») describe el cambio.
  - Request: "CHANGELOG «Sin publicar»"
  - Verify: review CHANGELOG.md

## Acceptance scenarios

### Scenario: macOS sin runner

- **Given** un run con todos los jobs en `success` salvo `test (macos-latest)` `cancelled`, sin runner y sin pasos
- **When** corre `ci-gate`
- **Then** sale 0 y el informe nombra ese job como cancelado por infraestructura

### Scenario: macOS cancelado tras arrancar

- **Given** el mismo run, pero el job tiene runner y `Set up job` en `success`
- **Then** `ci-gate` sale 1

### Scenario: test de coste nuevo con tope

- **Given** un test nuevo con `assert time.perf_counter() - start < 1.0` y sin marcador
- **When** corre la suite
- **Then** `test_timing_marker_guard` falla nombrando fichero, test y línea

## Edge cases and failure behavior

- Reintento: solo una vez y solo lo fallido (`--lf`); el paso falla si falla el reintento.
- Un job `perf` o un paso `real_io` sin tests seleccionados (código 5 de pytest) es un fallo: un
  marcador vacío es una regresión del reparto.
- `check_main.py` sin `gh` o sin red sale con código 3 y lo dice; no da verde sin mirar.

## Non-functional requirements

- Sin dependencias nuevas.
- El job `test` mantiene `timeout-minutes: 15` (la firma 20:00 sigue valiendo).

## Non-goals

- Arreglar las alertas #228 y #231 (otro cambio en curso).
- Reescribir los tests de espera real para que no esperen.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
