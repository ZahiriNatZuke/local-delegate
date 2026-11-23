# Implementation plan: Ruido del CI arreglado de raíz: gate, tests de coste, E/S real, huellas y CodeQL

## Approach

Una regla por causa, no un parche por test:

- **Infraestructura sin máquina** → el gate lo distingue por los datos de la API (sin runner y sin
  pasos), no por el sistema ni por la duración.
- **Medir coste** → un solo helper (`tests/perf.py`, `perf_counter_ns`, ≥ 50 ms por lado, proporción
  entre dos tamaños con techo `size_ratio ** 1.5`), marcador `perf` y un job propio sin `-n`.
- **Esperar al mundo real con tope de pared** → marcador `real_io`, que sigue corriendo en los tres
  sistemas pero en serie, después del paso paralelo, con un reintento de los fallidos.
- **Que no vuelva** → guardián estático (`tests/timing_scan.py` + `test_timing_marker_guard.py`):
  todo tope sobre un reloj sin `perf`/`real_io` es rojo, y `process_time` está prohibido en `tests/`.
- **Lo que depende del autor del commit** → `scripts/check_local.py` en pre-commit, y
  `bump_version.py` regenera huellas y capturas al subir versión. Desviación razonada del pedido
  literal («que `release.py` regenere»): `release.py` corre en `main` ya mezclado y exige que local
  y remoto coincidan, así que lo que regenerase quedaría fuera de lo publicado. Regenera el paso que
  abre el PR de release (`bump_version.py X`) y `release.py` se niega si están viejas.
- **Después de mezclar** → `scripts/check_main.py`: checks del último commit de `main` y alertas
  abiertas de CodeQL de `main`.

## Ordered tasks

- [x] T1 — Gate: cancelado sin runner ni pasos = aviso; tests con el caso, el control con pasos y el control con runner (REQ-001)
  - Files or modules: scripts/ci_gate.py, tests/test_ci_gate.py
  - Verification: tests/test_ci_gate.py falla sin el cambio (el caso nuevo da BAD)
  - Depends on: none
- [x] T2 — Helper `tests/perf.py` y sus tests con coste lineal y cuadrático simulados (REQ-003)
  - Files or modules: tests/perf.py, tests/test_perf_helper.py
  - Verification: tests/test_perf_helper.py
  - Depends on: none
- [x] T3 — Guardián estático y sus controles (REQ-005)
  - Files or modules: tests/timing_scan.py, tests/test_timing_marker_guard.py
  - Verification: en rojo sobre el árbol sin marcar (lista de tests sin marcador), verde al terminar T4-T5
  - Depends on: none
- [x] T4 — Migrar los tests de coste al helper y a `perf`; borrar `tests/linear_cost.py` (REQ-004)
  - Files or modules: tests/test_codex_reads.py, tests/test_codex_guard_shell_writes.py, tests/test_explain_code_verified_lines.py, tests/test_extract_polarity.py, tests/test_lint_exact_paths.py, tests/test_lint_patterns_linear.py, tests/test_lint_pytest_failures.py, tests/test_locate_anchor.py, tests/test_locate_hostile_input.py, tests/test_locate_index_python.py, tests/test_locate_index_ts.py, tests/test_locate_markdown_ids.py, tests/test_read_classifier.py, tests/test_score_lint_fidelity_linear.py, tests/test_summarize_code_string_literals.py, tests/test_summarize_focus_coverage.py, tests/test_summarize_runner_totals.py, tests/test_table_detect.py, tests/test_test_summary_figures.py
  - Verification: pytest -m perf en serie; guardián verde
  - Depends on: T2, T3
- [x] T5 — Marcar `real_io` los tests de espera real (los que señala el guardián y los de red/procesos del análisis) (REQ-006)
  - Files or modules: tests/test_*.py señalados por tests/timing_scan.py, tests/test_daemon_dead_listener.py, tests/test_desktop_bridge.py, tests/test_hook_project.py, tests/test_read_timeout_explains.py
  - Verification: pytest -m real_io en serie; guardián verde
  - Depends on: T3
- [x] T6 — Marcadores en pyproject y reparto en ci.yml: paso paralelo sin perf/real_io, paso real_io en serie con reintento, job perf; EXPECTED_JOBS y límites (REQ-002)
  - Files or modules: pyproject.toml, .github/workflows/ci.yml, scripts/ci_gate.py, tests/test_ci_gate.py, scripts/ci_pytest_retry.sh
  - Verification: tests/test_ci_gate.py; CI del PR
  - Depends on: T4, T5
- [x] T7 — pwsh roto al arrancar: sonda, salto con versión y guarda de shells en aviso (REQ-007)
  - Files or modules: tests/completion_shells.py, tests/conftest.py, tests/test_completion_shell_startup.py
  - Verification: tests/test_completion_shell_startup.py con un pwsh falso que aborta al arrancar
  - Depends on: none
- [x] T8 — `scripts/check_local.py` en pre-commit; `bump_version.py X` regenera huellas y capturas; `release.py` se niega con ellas viejas (REQ-008)
  - Files or modules: scripts/check_local.py, .pre-commit-config.yaml, scripts/bump_version.py, scripts/release.py, tests/test_check_local.py
  - Verification: tests/test_check_local.py
  - Depends on: none
- [x] T9 — Descarga del navegador con reintento acotado (REQ-009)
  - Files or modules: scripts/ci_retry.sh, .github/workflows/ci.yml, tests/test_ci_gate.py
  - Verification: tests/test_ci_gate.py
  - Depends on: none
- [x] T10 — `scripts/check_main.py` y documentación tras mezclar (REQ-010)
  - Files or modules: scripts/check_main.py, tests/test_check_main.py, docs/wiki/Repo-hardening.md, CONTRIBUTING.md
  - Verification: tests/test_check_main.py con `gh` simulado
  - Depends on: none
- [x] T11 — CHANGELOG «Sin publicar» (REQ-011)
  - Files or modules: CHANGELOG.md
  - Verification: revisión
  - Depends on: T1-T10

## Test strategy

- Unit: veredicto del gate con jobs sintéticos; helper con costes simulados; escáner con fuentes sintéticos; `check_main` con `gh` simulado; sonda de pwsh con un ejecutable falso.
- Integration: la suite entera en local con `-n 2` y, aparte, `-m real_io` y `-m perf` en serie.
- End-to-end or manual: el CI del PR, relanzado dos veces más (3 de 3 en verde en los tres sistemas).
- Security and secret scanning: gitleaks (pre-commit y job `secrets`); `personal-security-check` antes del commit.

## Migration and compatibility

- En local `pytest` sin `-m` sigue corriendo todo; los marcadores solo reparten en el CI.
- El ruleset exige `ci-gate`, no los jobs: el job `perf` nuevo entra por `EXPECTED_JOBS` sin tocar el ruleset.
- Rollback: revertir el PR; no hay datos ni formatos que migrar.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
