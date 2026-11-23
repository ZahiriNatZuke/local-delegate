# Research: Ruido del CI arreglado de raíz: gate, tests de coste, E/S real, huellas y CodeQL

## Current behavior

Datos: 400 corridas de `ci.yml` del 2026-11-03 al 2026-11-23 (6 905 jobs: 6 439 `success`, 269
`cancelled`, 197 `failure`), recogidas con `gh api` en el scratchpad de la sesión que lanzó el
cambio (`jobs.json`, `failed_tests.txt`, `logs/`). Las causas de los rojos, de más a menos:

1. **`ci-gate` cuenta cualquier `cancelled` como fallo** (`scripts/ci_gate.py:155-157`). 71 jobs de
   macOS (`test` 37, `plugin` 34) salieron `cancelled` **sin runner asignado y sin pasos**; 31 de los
   90 rojos de `ci-gate` son eso. No es código del repo: GitHub nunca les dio máquina. La memoria
   `ci-pytest-xdist.md` ya lo describía («un job de macOS `cancelled` a los 15:00 con 0 pasos y
   `BlobNotFound` es el cuelgue de GitHub: relanzar»), y la respuesta era relanzar a mano.
2. **Tests con un tope absoluto en segundos o en CPU** (~28 corridas rojas, casi todas Windows):
   `test_table_detect` (9), `test_locate_hostile_input` (5), `test_summarize_code_string_literals`
   (4), `test_read_timeout_explains` (4), `test_aborted_delegations` (3), `test_locate_anchor` y
   `test_locate_index_ts` (2 cada uno), `test_questions` (1). Dos mecanismos medidos:
   `time.process_time` avanza en Windows a saltos de 15,6 ms, y la proporción entre dos medidas de
   pocos ticks se dispara (27-45 para costes de 10-12 en #723); `-n auto` pone a los workers a
   competir por los núcleos y el reloj de pared mide la carga. Ya había un helper parcial
   (`tests/linear_cost.py`, con `process_time`) usado por 3 ficheros.
3. **Tests de red y procesos reales** (12): `test_daemon_dead_listener` (8, Windows, `WinError
   10061`), `test_completion_powershell` (28 fallos en 2 corridas, `pwsh exit=-6` en Ubuntu:
   `System.IO.FileLoadException` al arrancar pwsh, imagen del runner), `test_desktop_bridge`
   (daemon real), `test_hook_project` (`KeyError: 'project_kind'`, presupuesto de tiempo del
   recorrido de proyectos bajo carga).
4. **Huellas y versión desactualizadas** (7): `test_hook_boundaries` («corre `bump_version.py
   --boundaries`») y `test_capture` (la captura del README con la versión anterior, en los PR de
   release 0.49.0 y 0.52.0). **Detector de nombres en español y catálogo de textos** (~10):
   `test_detect_spanish_names`, `test_no_uncatalogued_text`. Fallan en el CI porque nada los corre
   antes del push: `.pre-commit-config.yaml` solo lleva gitleaks y ruff.
5. **Instalación del navegador**: desde el 2026-11-11 apt va por
   `scripts/ci_playwright_system_packages.sh` con reintentos y el navegador con `actions/cache`;
   la descarga de Chromium (`uv run playwright install chromium`) sigue sin reintento.
6. **Alertas de CodeQL en `main`** (#228, #231, nivel bajo) que nadie vio: tras mezclar solo se
   miraban los checks y los hilos del PR, nunca `code-scanning/alerts` de `main`.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `scripts/ci_gate.py` | veredicto del run por los pasos | cancelado sin runner = aviso | `ci_gate.py:149-177` |
| `.github/workflows/ci.yml` | jobs del gate | `-m "not perf and not real_io"`, paso `real_io`, job `perf`, reintento del navegador | `ci.yml:203-207,290-292` |
| `pyproject.toml` | marcadores de pytest | registra `perf` y `real_io` | `pyproject.toml:197-206` |
| `tests/linear_cost.py` | helper de coste con `process_time` | lo sustituye `tests/perf.py` | 3 usuarios |
| ficheros de tests de coste | topes en segundos | crecimiento entre dos tamaños + `perf` | lista en `plan.md` |
| ficheros de tests con espera real | topes de pared bajo `-n auto` | `real_io`: en serie, con reintento | `tests/timing_scan.py` |
| `tests/completion_shells.py`, `tests/conftest.py` | shells reales exigidas | pwsh roto al arrancar = salto con aviso | `completion_shells.py:88-97`, `conftest.py:675-717` |
| `.pre-commit-config.yaml`, `scripts/check_local.py` | — | huellas, nombres, catálogo, captura antes del commit | `.pre-commit-config.yaml` |
| `scripts/bump_version.py`, `scripts/release.py` | versión y release | huellas y capturas siempre al subir versión; release se niega con ellas viejas | `bump_version.py:385-430` |
| `scripts/check_main.py`, `docs/wiki/Repo-hardening.md`, `CONTRIBUTING.md` | — | checks y alertas de CodeQL de `main` tras mezclar | — |

## Existing conventions

- `tests/test_ci_gate.py` ata `EXPECTED_JOBS` a los jobs de `ci.yml` por conjuntos iguales, la firma
  20:00 del cuelgue y los límites de cada paso del navegador y de `test-lang-es` (`< MAX_WAIT_S`).
- La guarda de shells exigidas (`conftest.py`) falla la sesión si una shell de
  `COMPLETION_TEST_REQUIRE_SHELLS` no tuvo ningún test aprobado: la variable va solo en el paso
  principal de pytest, o la sesión `real_io` (sin tests de shell) fallaría.
- Código en inglés, textos para personas en español; tests de scripts saltan si `scripts/` no está.
- Sin dependencias nuevas: el reintento se hace con `--lf` de pytest (`pytest-rerunfailures`
  añadiría una dependencia que Socket tendría que revisar sin necesidad).

## Dependencies and integrations

- API de Actions (`/actions/runs/{id}/jobs`): `runner_id`/`runner_name` vacíos y `steps: []` en un
  job que nunca tuvo máquina; un job con runner trae al menos `Set up job`.
- `gh api repos/{repo}/code-scanning/alerts?state=open&ref=refs/heads/main` y
  `commits/{sha}/check-runs` para el script de después de mezclar.
- Playwright y Chromium para regenerar la captura en `bump_version.py`.

## Risks and unknowns

- Dar por bueno un macOS cancelado sin runner deja ese run sin probar macOS: se acepta porque el
  runner nunca existió (no hay nada que mirar) y el aviso queda en el resumen; un cancelado con
  pasos sigue fallando.
- El job `perf` entra en el gate: si fuese ruidoso, volvería el ruido. Lo mitiga correr solo, sin
  `-n`, en Ubuntu, por proporción con techo `size_ratio ** 1.5`, primera ronda buena de cinco y un
  reintento de los fallidos.
- `timing_scan` es un análisis estático superficial: no sigue fixtures ni otros módulos. Lo cubre
  la regla textual (ningún `process_time` en `tests/`).
