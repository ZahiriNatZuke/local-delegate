# Evidencia — Estado de instalación, vía y orquestación de la entrega (F1-delivery-core)

Fecha: 2026-10-21. Worktree `D:/Projects/ld-wt-f1-delivery-core`, rama `feat/f1-delivery-core`.

## Qué se hizo

- `src/local_delegate/install_state.py`: `install-state.json` con la regla de `language.json`
  (`install.data_dir_for`); fichero ausente o ilegible = `None` («no se sabe»).
- `src/local_delegate/claude_plugin.py`: `MIN_CLAUDE_PLUGIN_VERSION = "2.1.292"` (T0), decisión de
  vía (`decide`), `ld_bin` = intérprete del entorno de `uv tool` (vía B de T0; se rechaza `uvx`,
  editable y cualquier entorno que no sea `uv tool`), argv de `claude plugin …` y `--dry-run`.
  Runner inyectable; con HOME simulado el hijo recibe `CLAUDE_CONFIG_DIR=<home>/.claude`. Un HOME
  simulado solo va por plugin en las plataformas donde se comprobó `CLAUDE_CONFIG_DIR`
  (`CLAUDE_CONFIG_DIR_VERIFIED = {"win32"}`, por T0); el resto cae a settings con aviso.
- `src/local_delegate/plugin_migration.py`: `apply_plugin_delivery` (copia → `read-hook.json` →
  marketplace + install → `list --json` → retirada con `install.strip_hook_settings` → estado) y
  `revert_to_settings`.
- Catálogos `resources/i18n/{es,en}/plugin.json`.
- `tests/conftest.py`: guarda `real_claude_cli_forbidden` (borra `CLAUDE_CONFIG_DIR` y
  `CLAUDE_PLUGIN_*`; cualquier `Popen` del `claude` real lanza) y el doble `FakeClaude`.

## Forma real de `claude plugin list --json`

Medida con la CLI 2.1.307 en un `CLAUDE_CONFIG_DIR` del scratchpad (marketplace de prueba, sin
tocar `~/.claude`): lista de objetos con `id`, `version`, `scope`, `enabled`, `installPath`,
`readFromFolder`, `folderVersion`, `installedAt`, `lastUpdated`, `projectEnabled`,
`hasUserConfig`. `install --json` devuelve `{"command","outcome","pluginId","configApplied",…}`.

## Mutantes (control positivo)

Script: scratchpad `f1-delivery-core/mutants.py`; cada mutante se comprobó que cambia el texto
(`assert text != text0`) y se revirtió (el fichero queda idéntico al original).

| Mutante | Test | Assert que dispara |
|---|---|---|
| 1 dejar `record_call` sin retirar | `test_migration_removes_every_settings_hook_we_wrote` | `assert ours_left == []` |
| 2 retirar una entrada ajena (`Stop`) | `test_migration_keeps_foreign_hooks` | `assert hooks.get("Stop") == [...]` |
| 3 copia después de instalar | `test_backup_is_pre_install_bytes` | `assert backup.read_bytes() == original` |
| 4 no escribir el interruptor | `test_migration_carries_read_switch_on` | `assert data.get("active") is True` |
| 5 retirar antes de `list --json` | `test_plugin_failure_leaves_settings_untouched[list]` | `assert _settings_path(home).read_bytes() == before_settings` |

## Suite

`pesado.sh .venv/Scripts/python.exe -m pytest -n 2 -q`: 4215 passed, 28 skipped. `ruff check` y
`ruff format --check` limpios.

## Llamadas `local_*`

- `local_extract(path=evidence/T0.md)`: vía de B-1, versión mínima, comandos.
- `local_lint_summary(path=suite.txt)`: resumen del primer fallo de la suite.
