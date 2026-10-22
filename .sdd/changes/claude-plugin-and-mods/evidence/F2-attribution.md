# F2-attribution — Delegaciones del mod separables y script de medición

Fecha: 2026-10-21 · Windows 11 · `.venv` del worktree `D:/Projects/ld-wt-f2-attribution` ·
REQ-015 y REQ-024.

## Qué se hizo

- `attribution.py`: `MOD_TOOL_USE_PREFIX = "toolu_plugin_"` e `is_mod_call(row)`, la única regla
  de «esta delegación la pidió el mod». La usan el panel y el script.
- `web/metrics.py`: `_aggregate` cuenta `mod_calls` por cliente y en total (`/api/stats` →
  `mod_calls`). Las del mod **siguen dentro** de `total.calls`: son uso, solo se dicen aparte.
  `renderClients` añade «· N del mod» en la celda de delegaciones (nada si es 0 o falta el campo).
  No cambia la contabilidad: el espejo JS de `_accounting` y las series por día no se tocan
  (`grep by_client|mod_calls|_accounting`: el único lector de `by_client` en el JS es `renderClients`).
- `panel.json` es/en: `panel.clients.mod_calls` («{n} del mod» / «{n} from the mod»).
- `scripts/measure_plugin_adoption.py` (de `evidence/baseline_sessions.py`): % de sesiones
  interactivas (`entrypoint` `cli` o `claude-desktop`) con ≥ 1 delegación decidida por el modelo,
  por `tool_use_id` en el transcript principal. Excluye `toolu_plugin_`, `test_reason`, ventanas de
  prueba, otros clientes, filas sin id, `caller_kind: subagent`, transcripts de `subagents/` y
  sesiones `sdk-cli` (`-p`). `since` nunca baja del 2026-10-08. Con `--install` compara la base
  con los 14 días siguientes e imprime el criterio (≥ +10 puntos, ≥ 30 sesiones, 14 días) con
  `status` (`no_install`, `too_early`, `too_few_sessions`, `met`, `not_met`). Solo lee; solo
  imprime cifras.

## Tests primero

Rojo con un esqueleto del script (para que fallaran por el assert y no por la importación):
los 6 de `test_measure_plugin_adoption.py` (los 5 del plan + `test_main_prints_the_criterion`,
que pasa por `main()`) y `test_dashboard_states.py::test_mod_calls_shown_apart` (`KeyError:
'mod_calls'`). Después, verdes.

## Mutantes (uno a uno, restaurando el fichero)

| Mutante | Test | Assert que dispara |
|---|---|---|
| `MOD_TOOL_USE_PREFIX = "toolu_"` | `test_mod_calls_shown_apart` | `assert 3 == 1` (`mod_calls`) |
| sin `return "plugin"` | `test_plugin_calls_excluded` | `assert 2 == 1` |
| sin ventanas de prueba | `test_test_windows_excluded` | `assert 2 == 1` |
| sin `max(…, BASE_START)` | `test_base_starts_2026_10_08` | `since` 2026-09-01 ≠ 2026-10-08 |
| `hit += len(matched)` | `test_counts_sessions_not_calls` | `(2, 3) == (2, 1)` |
| `rglob("*.jsonl")` (entran subagentes) | `test_subagent_and_print_sessions_excluded` | `assert 3 == 2` |
| `sdk-cli` interactivo | `test_subagent_and_print_sessions_excluded` | `assert 3 == 2` |
| sin `modCell` en el JS | `test_mod_calls_shown_apart` | `'1 del mod' in …` |
| sin `too_early` | `test_main_prints_the_criterion` | `'too_few_sessions' == 'too_early'` |

El de `rglob` sobrevivió la primera vez: el subagente de mentira no llevaba `entrypoint`. Los reales
sí lo llevan (medido: 199 de 200 cabeceras con `entrypoint`, `isSidechain: true` y `timestamp`), así
que el fixture se rehízo como ellos y el mutante murió.

## Suite y calidad

- `pesado.sh uv run pytest -n 2 -q`: 4360 passed, 28 skipped, 2 errores de
  `tests/test_dashboard_ui.py` por el puerto 9498 ocupado (`WinError 10048`, ajeno); repetidos
  solos: 2 passed. `test_dashboard_ui.py` entero antes: 65 passed, 1 skipped.
- `ruff check .` y `ruff format --check .`: limpios.
- Detector de nombres: `entrypoints`, `mpa` y `desk` sin clasificar → se renombraron
  (`INTERACTIVE_ENTRY_POINTS`, `measure_plugin_adoption`, `toolu_01Desktop`); el léxico no se tocó.

## Capturas

Tarjeta «Quién delegó» con un `by_client` de ejemplo (`mod_calls: 9`), Playwright contra la app de
métricas en el puerto 9495 con un `LOG_DIR` vacío, claro y oscuro: «74 · 9 from the mod» en gris
apagado, legible en los dos temas; Codex y Desconocido sin marca.

## Corrida contra los logs reales (solo lectura, 2026-10-22T02:44Z)

`uv run python scripts/measure_plugin_adoption.py` (sin `--install`: la 0.40.0 aún no está):
base desde el 2026-10-08, **28 sesiones interactivas (todas `cli`), 11 con delegación: 39,3 %**;
21 delegaciones del modelo en el log, las 21 encontradas en transcripts. Filas apartadas: 2122
`tests`, 423 `subagent`, 144 `test_window`, 4 `other_client`, 4 `no_tool_use_id`.

## Llamadas `local_*`

- `local_lint_summary(path=pytest.log)`: localizó el fallo del detector de nombres.
- Las demás lecturas eran cortas o necesitaban líneas exactas para editar.
