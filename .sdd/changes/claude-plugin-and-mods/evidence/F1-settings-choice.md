# F1-settings-choice — `update` respeta la vuelta atrás a settings

Lote corto de corrección (2026-10-22), sobre `main` en 65be4fd (#402).

## Problema 1: la vuelta atrás duraba hasta el siguiente `update`

El plan da `install --claude-delivery settings` como vuelta atrás de una instalación migrada, pero
`update` (F1-update) migra al plugin toda instalación por settings que cumpla REQ-005, y el estado no
distinguía «elegí settings» de «instalación vieja». Había dos caminos que deshacían la elección:
la migración de `_plan_migration` y las reparaciones de los hooks de settings, que llaman a
`plan_install` con `claude_delivery=None` y, por tanto, también eligen el plugin.

Cambio:

- `install_state`: campo **opcional** `claude_delivery_explicit: true` (`EXPLICIT_FIELD`),
  `delivery_explicit()` y `with_delivery_explicit()`. `schema` sigue en 1: un estado de hoy sin
  el campo se lee como «no elegido».
- `install._claude_hook_actions` envuelve la última acción de la entrega de Claude Code
  (`_with_delivery_choice`): tras ejecutarse, `--claude-delivery settings` escribe la marca (y crea
  el estado si no lo había); cualquier otra cosa la quita. Sin estado y sin elección no escribe
  nada, para que una instalación vieja siga siendo vieja.
- `update.repair_install_options`: con la marca, pasa `claude_delivery="settings"` a todas las
  opciones de `install` que construye. Eso cierra los dos caminos a la vez: `decide` devuelve
  settings, `_plan_migration` no planifica nada y las reparaciones reponen settings (y vuelven a
  marcar).

Tests (en `tests/test_update_plugin.py`, salvo el último):

| Test | Antes del cambio | Después |
|---|---|---|
| `test_update_respects_explicit_settings_choice[intact]` | FALLA: `'install' not in [... 'marketplace_add', 'install', ...]` | pasa |
| `test_update_respects_explicit_settings_choice[broken]` (hooks quitados de settings.json: corre la reparación) | FALLA: el mismo assert | pasa |
| `test_install_without_explicit_settings_removes_the_choice[None]` (CLI vieja, se queda en settings) | FALLA: `'claude_delivery_explicit' not in {...}` | pasa |
| `test_install_without_explicit_settings_removes_the_choice[plugin]` | FALLA: el mismo assert (`apply_plugin_delivery` copiaba el estado con la marca) | pasa |
| `test_old_settings_install_without_mark_still_migrates` | pasa (guarda de REQ-008 a: lo de hoy no debe cambiar) | pasa |
| `tests/test_install_state.py::test_explicit_delivery_is_optional_and_keeps_schema` | — | pasa |

Mutante: `repair_install_options` ignora la marca (`if False and …`). Fallan los dos
`test_update_respects_explicit_settings_choice` por `assert 'install' not in fake.steps()`; los
otros tres siguen en verde. Restaurado y comprobado con `git diff`.

## Problema 2: ¿reinstalar con `--config` vuelve a aplicar las opciones?

Medido con la CLI real **2.1.307** en un `CLAUDE_CONFIG_DIR` aislado del scratchpad, con el
marketplace local `src/local_delegate/resources/claude-plugin` y las argv de `claude_plugin`:

1. `plugin marketplace add <dir>` → 0.
2. `plugin install local-delegate@local-delegate --scope user --config ld_bin=… --config language=es --json`
   → `"outcome":"ok","configApplied":true`; `settings.json` → `pluginConfigs["local-delegate@local-delegate"].options.language == "es"`.
3. La misma orden con `language=en` sobre el plugin ya instalado → `"outcome":"ok"`, mensaje
   «is already installed … loads in place», **`"configApplied":true`**; `pluginConfigs…language == "en"`.
4. (Comparación) `plugin configure <id> --values-stdin` también existe y guarda; no hace falta.

Conclusión: **sí se reaplica**. No se cambia la acción de reparación. Se añade al script de CI
`scripts/check_plugin_install.py` el paso 4b (reinstalar con el otro idioma vía `install`, con
`LOCAL_DELEGATE_LANG`, y comprobar `pluginConfigs`) y, en el paso 5, que el estado guarde la marca.
El script completo corrió en verde aquí contra la CLI real («language: es -> en»).

`~/.claude.json` real copiado antes y después de cada corrida: `mcpServers` idéntico; en la
medición solo cambiaron contadores de `pluginUsage` de otros plugins (pyright-lsp, warp) por las
sesiones abiertas; en la corrida del script, ninguna clave.

## Verificación

- Suite completa (`pytest -n 2`): 4355 pasados, 28 saltados, 1 fallo: el detector de nombres en
  español marcó `cleared`/`clears` en los tests nuevos; se renombraron (`removed`,
  `..._removes_the_choice`) y el detector y los tests tocados pasan (68 pasados).
- `ruff check` y `ruff format --check`: limpios. Fines de línea iguales que en `main`.
