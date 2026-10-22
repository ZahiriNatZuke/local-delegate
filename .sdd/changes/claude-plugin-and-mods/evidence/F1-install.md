# Evidencia — Instalar y desinstalar con plugin (F1-install)

Fecha: 2026-10-21. Worktree `D:/Projects/ld-wt-f1-install`, rama `feat/f1-install`, sobre `main` =
`5fbffcf`.

## Qué se entrega (REQ-005, 006, 008 b y doc de c, 011, 012)

- `install.Options` gana `claude_delivery`, `disable_read_hook` y `desktop`; el CLI, las opciones
  `--claude-delivery plugin|settings`, `--disable-read-hook` (excluyente con `--enable-read-hook`)
  y `--desktop`, y el subcomando `desktop-bridge [--url]`.
- `install`: la vía la decide `claude_plugin.decide`; plugin → `plugin_migration.apply_plugin_delivery`
  (no reimplementa pasos); `--claude-delivery settings` con el plugin puesto →
  `revert_to_settings`; plugin puesto e inutilizable → se deja como está, sin hooks en settings.
  `--enable-read-hook`/`--disable-read-hook` escriben `read-hook.json` (`active` true/false).
- `install --desktop`: en Windows escribe la entrada del puente en `claude_desktop_config.json`
  (en HOME simulado, bajo `<home>/AppData/Roaming`), reemplaza una entrada ajena avisando y
  guarda en el estado si la reemplazó y dónde quedó la copia. Fuera de Windows sale con 2 sin
  escribir nada.
- `uninstall` lee `install-state.json`: quita plugin y marketplace, entrada de Desktop y lo que
  `--agents` añadió (`agents.revert`) solo si figuran; no repone una entrada ajena de Desktop
  reemplazada y dice en qué copia está; borra `read-hook.json` y el estado.
- `claude_plugin.CLAUDE_CONFIG_DIR_VERIFIED` pasa a `{"win32", "linux", "darwin"}`: Linux y macOS
  quedaron comprobados por el job `plugin` del PR #392.
- `scripts/check_plugin_install.py` y su paso en el job `plugin` de `ci.yml` (tres sistemas).
- Wiki `docs/wiki/Claude-plugin.md` y su enlace en `Home.md`; línea en `CHANGELOG.md`.
- Catálogos `resources/i18n/{es,en}/plugin_install.json` y claves nuevas de `cli.json`.

## Tests nuevos: 24 en verde

`tests/test_install_plugin_delivery.py` (11), `tests/test_uninstall_plugin.py` (4),
`tests/test_install_desktop.py` (6, uno parametrizado ×2), `tests/test_agents_uninstall.py` (3).
Están todos los del plan, más casos de borde (CLI que no arranca, migración fallida, idempotencia,
estado desconocido, edición del usuario tras `install --agents`).

```
pesado.sh uv run pytest -q -p no:randomly tests/test_install_plugin_delivery.py \
  tests/test_uninstall_plugin.py tests/test_install_desktop.py tests/test_agents_uninstall.py
24 passed in 0.66s
```

## Mutantes (control positivo)

Script del scratchpad `mutants.py` (luego lo sobrescribió otro agente que comparte el scratchpad): cada mutante comprueba que el original aparece una sola vez y
que el texto cambia; el fichero se restaura en `finally` (el `git diff --stat` queda igual).

| Mutante | Test que falla | Assert que dispara |
|---|---|---|
| M1 `--disable-read-hook` escribe `active=True` | `test_disable_read_hook_turns_active_layer_off` | `:155 assert True is False` (`active` del interruptor) |
| M2 `uninstall` quita el plugin aunque el estado no lo liste | `test_preexisting_piece_not_in_state_is_kept`, `test_unknown_state_removes_no_plugin` | `:89` y `:100 assert 'uninstall' not in steps()` |
| M3 `agents.revert` no quita el bloque del catálogo | `test_uninstall_undoes_agents_edit`, `test_user_edit_after_install_survives_uninstall` | `:69` y `:87`, igualdad del fichero: sobra el bloque `local-delegate:catalog` |
| M4 `--desktop` reemplaza la entrada ajena sin avisar | `test_replaces_foreign_entry_only_with_flag_and_warns` | `:98 assert any(...)` sobre las líneas de salida (falta el aviso con la copia) |

## `check_plugin_install.py` contra la CLI real

`claude` 2.1.307 del PATH, HOME simulado en `%TEMP%\ld-plugin-*` (borrado al acabar):

```
pesado.sh uv run python scripts/check_plugin_install.py <claude.exe>   → rc=0
== 1. Siembra una 0.39 por settings con el bloqueo encendido y un hook ajeno
== 2. install: entrega por plugin
== 3. La orden de prompt del hooks.json instalado, con una muestra
   …\.venv\Scripts\python.exe -I -m local_delegate.hook prompt -> 0
== 4. Segunda pasada idéntica
== 5. --claude-delivery settings: vuelta atrás
== 6. uninstall   ([mcp] claude — quita el servidor MCP 'local-delegate': no estaba registrado)
OK: entrega por plugin, idempotencia, vuelta atrás y uninstall
```

`~/.claude.json` real copiado antes y después y comparado como JSON: `mcpServers` idéntico (con la
entrada `local-delegate`), ninguna clave de primer nivel cambiada, ningún proyecto cambiado. El
`use_cli=False` de las opciones hace su trabajo: el `uninstall` del paso 6 buscó la entrada MCP en
el HOME simulado y no en el real.

## Suite

`pesado.sh uv run pytest -n 2 -q`: **4315 passed, 28 skipped** en 167 s (con la wiki nueva ya
escrita; `test_wiki` incluido). `pesado.sh uv run ruff check .` y `ruff format --check .` limpios.

## CI del PR #398: tres arreglos

- `lint` (ruff `EXE001`): `scripts/check_plugin_install.py` tiene *shebang* y no era ejecutable;
  modo `100755` en git (en Windows ruff no lo ve).
- `test (ubuntu|macos)`: `test_replaced_foreign_desktop_entry_not_restored_and_backup_reported`
  pasaba solo en Windows, porque `--desktop` solo se planifica en `win32`; el test fija
  `platform="win32"` en sus opciones, como ya hacía `test_install_desktop.py`.
- CodeQL `py/cyclic-import` (4 alertas en `install.py`): `install_state`, `claude_plugin` y
  `plugin_migration` importan `install`, y `install` los importaba dentro de sus funciones.
  Ahora los resuelve por nombre al llamar (`_sibling`, con `import_module`), como hace
  `completion.render` con `cli` (ec2ad2c). Suite repetida: 4314 passed y un fallo, la palabra
  `sibling` sin clasificar, que va al léxico. Tras rebasar sobre `44b10a1` (#399, conflicto solo en
  `CHANGELOG.md`, se conservan las dos líneas): **4322 passed, 28 skipped**. `check_plugin_install.py` pasó en los tres `plugin`.

## Ficheros fuera de la lista «Posee»

- `src/local_delegate/claude_plugin.py`: solo `CLAUDE_CONFIG_DIR_VERIFIED` (ver arriba), y
  `tests/test_claude_plugin.py`, cuyo caso «otro SO» pasa de `linux` a `freebsd14`.
- `tests/test_install_clients.py`: el espía del `claude` real ignora las llamadas con
  `CLAUDE_CONFIG_DIR` en el entorno (las de `claude plugin`/`--version` en HOME simulado, que T0
  midió aisladas); sigue vigilando `claude mcp add-json`.
- `tests/test_completion_posix.py`, `tests/test_completion_powershell.py`: el prefijo `--cl` ya
  es ambiguo (`--clients`, `--claude-delivery`) y el número de raíces del autocompletado sube a 14
  (`desktop-bridge`).
- `tests/data/uncatalogued_exceptions.json` (`Roaming`, segmento de ruta) y
  `scripts/data/spanish_lexicon.json` (`cleanly`, `disable`, `preexisting`, `undoes`).
- `CHANGELOG.md` (admitido por las reglas).

## Llamadas `local_*`

- `local_lint_summary(path=pytest.log)`: resumen de la suite completa.
- `local_commit_msg(path=f1-install.diff)`: borrador del mensaje de commit (99 KB de diff que no
  entraron al contexto; se reescribió el asunto al estilo del repo).
- `plan.md` no se resumió: bastaron dos rangos de líneas concretos (reglas y lote).
