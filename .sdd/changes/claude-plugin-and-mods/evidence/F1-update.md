# F1-update — `update` con plugin

Lote de la ola 2b. REQ-008 a, REQ-010 y REQ-012 (la ruta del puente). Worktree
`D:/Projects/ld-wt-f1-update`, rama `feat/f1-update` desde `main` (`7e678f1`).

## Qué hace

- `update.plan_repairs` decide primero la entrega de Claude Code (`plan_claude_delivery`):
  - **Con plugin** (el estado dice `plugin`, o `settings.json` lo tiene habilitado: el caso de bajar
    a la 0.39 sin `uninstall`): `plugin.installed` en `warn` → `claude plugin marketplace update
    local-delegate` y después `claude plugin update local-delegate@local-delegate`; en `missing`, con
    `ld_bin` en `missing`/`warn`, con el idioma guardado distinto del de la sesión, o habilitado sin
    estado → la acción de `install` (`install._plugin_delivery_action` →
    `plugin_migration.apply_plugin_delivery`), que reaplica `--config ld_bin=… --config language=…`.
    Hooks nuestros en `settings.json` o su carpeta → `plugin_migration.remove_settings_hooks` (si no
    hay reinstalación, que ya los quita). Las reparaciones `scaffold.hook_files`, `hook_settings` y
    `hook_orphans` **no se planifican nunca** con plugin; los huérfanos de la raíz se podan con la
    acción de `install`.
  - **Por settings que cumple REQ-005** (hooks nuestros en settings, o un check de hooks fallando, y
    `claude_plugin.decide` dice plugin): la misma acción de `install`, que conserva el interruptor;
    avisa de reiniciar las sesiones abiertas.
  - Si `decide` cae a settings: con plugin, un aviso y nada más; sin plugin, como hasta ahora.
- `plan_desktop_bridge`: si el estado registra `desktop_entry` y la entrada sigue teniendo la forma
  del puente pero con otro ejecutable (que existe), la reescribe con `install._desktop_action`.
- `plan_pin` y `service.daemon_auth` no cambian.
- El ciclo `checks` ↔ `update` **se quitó dentro de `update.py`**: `checks` se resuelve por nombre
  con `import_module` (como `install._sibling`); es el mismo objeto de módulo.
- `update.Options` gana los colaboradores de `claude` y Desktop (`claude_runner`, `claude_which`,
  `claude_ld_bin`, `platform`, `desktop_dir`, `desktop_executable`), que pasan a `checks.Context` y a
  `install.Options` (`repair_install_options`, una sola construcción para todas las reparaciones).

## Tests (`tests/test_update_plugin.py`, 13 casos)

Los nueve del plan, con sus nombres, más tres controles (`test_current_plugin_is_left_alone`,
`test_settings_install_stays_when_plugin_not_possible`, `test_desktop_bridge_same_path_untouched`);
`test_update_never_restores_settings_hooks_under_plugin` va parametrizado (`state`, `enabled_only`).

- **Antes del cambio**: 10 fallan, por el assert de comportamiento (p. ej. `marketplace_update` no
  está en los pasos; `[enabled_only]` planifica una acción `copy`/`settings` de hooks: la trampa).
- **Mutante 1** (no saltar las reparaciones de hooks de settings): falla
  `never_restores…[enabled_only]` en `assert [...] == []` con `Action(kind='copy', …hooks/local-delegate)`,
  y `duplicates_are_removed_not_restored` en `'install' not in steps`.
- **Mutante 2** (no planificar la retirada): falla `duplicates_are_removed_not_restored` en
  `_our_hooks(home) == []` (quedan `UserPromptSubmit`, …). Restaurado y comprobado con `cmp`.

## Comandos y resultados

- `bash ~/.claude/scripts/pesado.sh uv run pytest -n 2 -q` → **4347 passed, 28 skipped** (0 fallos).
  La primera pasada dio 1 fallo: el detector de nombres en español marcaba `handled`,
  `orchestration`, `reapplied`, `reinstall` (inglés legítimo, añadidos a `en` del léxico) e `iopts`
  (renombrado a `install_opts`).
- `uv run ruff check .` y `uv run ruff format --check .` → limpios.
- `git ls-files --eol` de los tocados: LF, igual que en `main`; los nuevos, LF.

## Llamadas `local_*`

- `local_lint_summary(path=<log de pytest>)`: 1.
- `local_commit_msg(path=<diff>)`: 1 (borrador del commit).
