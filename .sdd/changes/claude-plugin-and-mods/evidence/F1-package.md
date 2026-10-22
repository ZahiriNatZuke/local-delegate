# Evidencia — Plugin empaquetado y metadatos de versión (F1-package)

Fecha: 2026-10-21. Worktree `D:/Projects/ld-wt-f1-package`, rama `feat/f1-package`.

## Qué se hizo

- Plugin en `src/local_delegate/resources/claude-plugin/`: marketplace local
  (`.claude-plugin/marketplace.json`, nombre `local-delegate`, fuente `./local-delegate`) y raíz del
  plugin `local-delegate/` con `.claude-plugin/plugin.json` (`userConfig`: `ld_bin` obligatoria sin
  `default`, `language` opcional) y `hooks/hooks.json`. Sin `bin/`.
- Marketplace del repo en `/.claude-plugin/marketplace.json`, que apunta a la misma carpeta.
  Id del plugin: **`local-delegate@local-delegate`** (lo usarán install/doctor/update).
- `hooks.json`: cinco entradas (`UserPromptSubmit`; `PreToolUse` sobre `mcp__local-delegate__.*`,
  `Read`, `mcp__.+__(read_[a-z_]*|get_file_contents)` y `Bash|PowerShell`), todas en forma exec:
  `command: ${user_config.ld_bin}`, `args: [-I, -m, local_delegate.hook, <prompt|record-call|read|mcp-read|shell>]`,
  `timeout: 30`. Vía B de T0.
- `scripts/bump_version.py`: escribe y comprueba la versión en `plugin.json` y en los dos
  marketplaces (todo o nada: si falta uno de los tres, error).
- CI: job `plugin` en los tres SO (CLI 2.1.292 por pnpm `--ignore-scripts`), en `EXPECTED_JOBS`.

## Pruebas

| Prueba | Resultado |
|---|---|
| Tests nuevos en rojo antes del cambio | 11 fallos + 3 errores, por ficheros/atributos ausentes |
| `test_plugin_package.py` (5 + 4 de JSON sin BOM), `test_release_metadata.py::test_plugin_json_version_matches_pyproject`, `test_bump_version.py` (3 nuevos), `test_ci_gate.py::test_the_plugin_job_is_required_on_every_os` | verdes |
| Suite completa `pytest -n 2` | 4196 pasan; 1 falla: `test_detect_spanish_names` (palabras sin clasificar `plugin`, `marketplace`, `delivery`; el léxico no es de este lote) |
| `ruff check` / `ruff format --check` | limpios |
| `bump_version.py --check` | OK 0.39.0 en todos los sitios |

Mutantes (cada uno dispara el assert previsto):

| Mutante | Falla |
|---|---|
| `command: local-delegate` en una entrada | `test_every_hook_entry_is_fail_open` |
| matcher `Bash` en vez de `Bash\|PowerShell` | `test_hooks_json_matches_settings_delivery_0_39` |
| `mcp-read` → `read` | `test_hooks_json_matches_settings_delivery_0_39` |
| `plugin.json` en 0.38.0 | `test_plugin_version_matches_package`, `test_plugin_json_version_matches_pyproject`, `test_check_passes_on_the_real_repo` |
| fuente del marketplace del repo mal | `test_marketplace_points_at_plugin_folder` |
| `bump_version` se salta el plugin | `test_bump_writes_plugin_and_marketplace_versions`, `test_a_missing_plugin_file_is_an_error…` |
| quitar `plugin (macos-latest)` del gate | `test_the_expected_jobs_are_exactly_those_of_ci_yml`, `test_the_plugin_job_is_required_on_every_os` |
| `ld_bin.required: false` | `test_every_hook_entry_is_fail_open` |

## CLI real (2.1.292, binario de T0, `CLAUDE_CONFIG_DIR` del scratchpad)

- `plugin validate --strict --json` de `.`, del marketplace del paquete y del plugin: `success: true`,
  sin errores ni avisos. Control negativo: `hooks.json` truncado → `success: false`, salida 1;
  hook sin `command` → aviso (falla en `--strict`).
- `marketplace add` + `plugin install local-delegate@local-delegate --scope user --config ld_bin=…`
  → `outcome: ok`; `plugin list --json` lo lista en 0.39.0. Listado de `~/.claude/plugins` real
  antes y después: idéntico.
- `claude -p … --output-format stream-json --verbose` (PowerShell, ventana de prueba
  `w-20261022T002349Z`, abierta y cerrada): el `init` lista `local-delegate` y no trae
  `plugin_errors`. Con `hooks.json` roto por `--plugin-dir`, el `init` trae
  `plugin_errors: [{type: hook-load-failed, …}]`. El comprobador del CI da 0 y 1 respectivamente.
- Rueda (`uv build --wheel`): contiene los tres JSON del plugin; no hizo falta tocar `pyproject.toml`.

## Socket

`@anthropic-ai/claude-code@2.1.292`: supplyChain 92, vulnerability 100, quality 85, license 70.
Binarios `-linux-x64`, `-darwin-arm64`, `-win32-x64`: quality 38 y license 50 (binario propietario
oficial; solo en CI, no viaja en el paquete). `pnpm@11.17.0`: todo ≥ 80.
