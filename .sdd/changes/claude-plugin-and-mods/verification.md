# Verification: local-delegate como plugin de Claude Code y Claude Desktop, con mods

## Environment

- Revision: `0253b630` (`main`, 2026-11-23); código publicado en la 0.40.0, la 0.41.0 y la 0.41.1
- Relevant runtime and tool versions: `uv run --locked pytest`; tests del mod con `claude plugin test` (job `plugin` del CI)

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_plugin_package.py::test_plugin_version_matches_package`, `test_release_metadata.py::test_plugin_json_version_matches_pyproject`, job `plugin` (`validate --strict`, rueda) | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: Plugin empaquetado |
| REQ-002 | `test_plugin_package.py::test_hooks_json_matches_settings_delivery_0_39` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: Plugin empaquetado |
| REQ-003 | Control positivo y negativo de B-1 en `evidence/T0.md`, `test_plugin_package.py::test_every_hook_entry_is_fail_open`, `test_hook_entry.py::test_hook_crash_lets_the_call_through`, `::test_hook_path_does_not_import_server`, `measure_hook_latency.py` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); evidencia en vivo citada en la prueba; lote: T0 · Plugin empaquetado · Subcomando de hooks · F2-live |
| REQ-004 | `test_read_switch.py::test_active_layer_state_file_or_enabled_env`, `::test_block_state_values_unchanged`, `test_plugin_migration.py::test_migration_carries_read_switch_on/off` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: Subcomando de hooks · Estado y orquestación |
| REQ-005 | `test_claude_plugin.py::test_min_version_gate`, `::test_simulated_home_passes_claude_config_dir`, `test_install_plugin_delivery.py::test_falls_back_to_settings_with_warning` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: Estado y orquestación · Instalar |
| REQ-006 | `test_plugin_migration.py::test_migration_removes_every_settings_hook_we_wrote`, `::test_backup_is_pre_install_bytes`, `::test_migration_is_idempotent` (+ mutantes) | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: Estado y orquestación · Instalar |
| REQ-007 | `test_install_state.py::test_missing_state_means_unknown_not_empty`, `::test_state_follows_language_dir_rule` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: Estado y orquestación |
| REQ-008 | a: `test_update_plugin.py::test_settings_install_migrates_carries_switch_and_warns_restart`; b: `test_plugin_migration.py::test_revert_to_settings_in_one_step`; c: `test_checks_plugin.py::test_doctor_flags_hooks_in_settings_and_plugin`. Las tres en HOME simulado con `CLAUDE_CONFIG_DIR` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: Estado y orquestación · Instalar · `doctor` · `update` |
| REQ-009 | `test_checks.py::test_check_ids_exact`, `test_checks_plugin.py::test_mod_loaded_from_heartbeat` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: `doctor` · Esqueleto del mod |
| REQ-010 | `test_update_plugin.py::test_marketplace_update_before_plugin_update`, `::test_update_never_restores_settings_hooks_under_plugin` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: `update` |
| REQ-011 | `test_uninstall_plugin.py::test_removes_only_what_state_lists`, `test_agents_uninstall.py::test_uninstall_undoes_agents_edit` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: Instalar |
| REQ-012 | `test_desktop_bridge.py::test_bridge_against_real_daemon_app`, `test_install_desktop.py::test_desktop_flag_on_macos_refuses_cleanly`, `test_desktop_config.py::test_detects_literal_token_without_printing`, puente contra el daemon real en `evidence/F2-live.md` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); evidencia en vivo citada en la prueba; lote: Puente · Instalar · `doctor` · `update` · F2-live |
| REQ-013 | `pinned-tools.test.ts` (job `plugin`) | pass | tests del mod (`*.test.ts`) en el job `plugin` del CI de `0253b630` (Windows, macOS y Linux en verde); lote: Esqueleto del mod |
| REQ-014 | `commands.test.ts` (`lint_without_process_run_accepts_only_file`, `commit_temp_file_removed`) | pass | tests del mod (`*.test.ts`) en el job `plugin` del CI de `0253b630` (Windows, macOS y Linux en verde); lote: Comandos |
| REQ-015 | `test_dashboard_states.py::test_mod_calls_shown_apart`, `evidence/F2-live.md` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); evidencia en vivo citada en la prueba; lote: Separables · F2-live |
| REQ-016 | `test_mod_static.py::test_mod_reads_only_the_token_variable`, `::test_register_loads_pieces_dynamically_inside_try`; en vivo, piezas a `off` y `register.js` que lanza | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: Esqueleto del mod · F2-live |
| REQ-017 | `test_metrics_session_filter.py::test_stats_filters_by_session`, `status.test.ts` (`hides_when_daemon_down`) | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); tests del mod (`*.test.ts`) en el job `plugin` del CI de `0253b630` (Windows, macOS y Linux en verde); lote: Cuota y ahorro |
| REQ-018 | `test_measure_read_paths.py::test_counts_each_path_kind`, `evidence/F4-read-paths.md` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); evidencia en vivo citada en la prueba; lote: Medir vías |
| REQ-019 | `test_read_classifier.py::test_corpus` (+ mutantes), `::test_classifier_change_moves_fingerprint` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: Clasificador |
| REQ-020 | `read.test.ts` (`accumulates_ranges_to_whole`) | pass | tests del mod (`*.test.ts`) en el job `plugin` del CI de `0253b630` (Windows, macOS y Linux en verde); lote: Mod de lectura |
| REQ-021 | `read.test.ts` (`buttons_when_dialog`, `denies_without_dialog`, `unclassifiable_only_warns`, `respects_read_switch_off`) | pass | tests del mod (`*.test.ts`) en el job `plugin` del CI de `0253b630` (Windows, macOS y Linux en verde); lote: Mod de lectura |
| REQ-022 | `read.test.ts` (`blocks_write_after_summary`, `guard_survives_resume`); control positivo y negativo en `evidence/F4-live.md` | pass | tests del mod (`*.test.ts`) en el job `plugin` del CI de `0253b630` (Windows, macOS y Linux en verde); evidencia en vivo citada en la prueba; lote: Mod de lectura · F4-live |
| REQ-023 | `test_hook_step_aside.py::test_read_hook_steps_aside_when_mod_active`, `::test_read_hook_does_not_step_aside_for_another_session`, `::test_no_gap_when_active_but_not_blocking`, `::test_read_hook_acts_when_mod_off_or_stale`, `test_checks_plugin.py::test_read_mod_and_read_hook_overlap_warns` | pass | pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); lote: Coordinación de hooks |
| REQ-024 | `scripts/measure_plugin_adoption.py --install 2026-10-22T11:07:06Z` (y `--include-self`), corrido el 2026-11-23; `test_measure_plugin_adoption.py` en 0253b630 | skip | no concluyente (`status: too_few_sessions`): sin el propio repo, base 0 de 4 sesiones (0 %) y después 0 de 6 (0 %), delta 0 puntos; con el propio repo, base 11 de 28 (39,3 %) y después 4 de 26 (15,4 %), delta −23,9 puntos. Ninguno llega a las 30 sesiones del criterio, así que no es éxito ni fracaso medido |

### Lectura de la adopción (REQ-024), 2026-11-23

Comando, tal cual: `uv run --locked python scripts/measure_plugin_adoption.py --install 2026-10-22T11:07:06Z`
(por defecto `--exclude-self`) y el mismo con `--include-self`. Base desde el 2026-10-08 hasta la
instalación; después, los 14 días siguientes (hasta el 2026-11-05T11:07:06Z). Solo hilo principal de
sesiones interactivas.

| Corte | Base: sesiones | Base: con delegación | Base % | Después: sesiones | Después: con delegación | Después % | Delta | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Sin el propio repo (por defecto) | 4 | 0 | 0 % | 6 | 0 | 0 % | 0 | `too_few_sessions` |
| Con el propio repo | 28 | 11 | 39,3 % | 26 | 4 | 15,4 % | −23,9 | `too_few_sessions` |

Columnas aparte, sin el propio repo: delegación por subagente en 3 sesiones de la base y 3 del
después; delegación del mod en 0 y 4. Con el propio repo: subagente 24 y 16; mod 0 y 15.

**Veredicto: no concluyente.** El criterio fijado antes (≥ 30 sesiones en el después y ≥ +10 puntos)
no se puede evaluar: el después tiene 6 y 26 sesiones. No es éxito. El dato que sí se ve es que el hilo
principal no delega fuera del propio repo (0 de 6), lo mismo que encontró la auditoría de sesgo del
2026-11-08 (0 de 11), y que dentro del repo el porcentaje bajó en vez de subir.

**Qué hacer con `pinned_tools`.** El plan decía «si no sube, un commit pone `pinned_tools` vacío por
defecto». La medición no dice «no sube» con el mínimo de sesiones, y cambiar el valor por defecto es una
decisión de producto: queda como tarjeta en el Project 3, fuera de este SDD.

## Quality checks

- [x] Project-native tests pass (pytest de los ficheros Python citados en `0253b630`: 1172 passed, 1 skipped (2026-11-23); CI completo de `0253b630` en verde).
- [x] Lint, formatting, type checking, and build checks pass where applicable (jobs `lint`, `plugin`, `install-smoke`).
- [x] Secret scanning passes (job `secrets`).
- [x] No unrelated changes are present.

## Deviations and residual risk

- REQ-024 queda en `skip`: la medición se hizo, pero con menos de 30 sesiones no puede dar éxito ni fracaso. Se cierra con ese dato, como se acordó.
- La 0.41.0 dejó escrito como pendiente verificar en una sesión interactiva de terminal los botones «resumir / leer entero» y la guarda tras `--resume`. En `-p` sí se comprobó (`evidence/F4-live.md`). No hay constancia de la prueba interactiva en esta carpeta.
- La sobrecarga del mod de lectura en `Bash` no cumplió en las dos primeras mediciones y sí en la tercera y la cuarta (`evidence/F4-live.md`).

