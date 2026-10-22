# Evidencia — `doctor` con plugin (F1-doctor)

Fecha: 2026-10-22. Worktree `D:/Projects/ld-wt-f1-doctor`, rama `feat/f1-doctor`.

## Qué se hizo (REQ-009, REQ-008 c, REQ-012)

- `src/local_delegate/checks_plugin.py` (nuevo): cinco sondas registradas en `checks.CHECKS`.
  - `claude.delivery` (entorno): la vía de `install-state.json`; sin estado, `unknown`; en WSL,
    settings.
  - `plugin.ld_bin` y `hooks.duplicates` (andamiaje): leen `settings.json`
    (`pluginConfigs.<id>.options.ld_bin` y `enabledPlugins`), sin lanzar `claude`.
  - `claude.version` y `plugin.installed` (servicios): lanzan `claude --version` y
    `claude plugin list --json`. Van en `service` porque el reporte de `install` (entorno y
    andamiaje) no lanza nada.
- `checks.py`: colaboradores nuevos del `Context` (`claude_which`, `claude_runner`, `environ`,
  `expected_ld_bin`, `bridge_token`), con default real que se busca al llamar; el runner por defecto
  convierte cualquier fallo en `OSError` («no se pudo comprobar»). `scaffold.hook_settings` y
  `scaffold.hook_files` dependen de la vía: con plugin, ningún hook en settings es `ok` y uno nuestro
  es `warn`; los scripts sueltos en `hooks/local-delegate/` son huérfanos (`warn`, lo arregla
  `update`). `service.desktop_auth`: la entrada del puente comprueba el ejecutable y prueba el token
  que lee el puente; un token escrito en la entrada (cabecera o `env`) o un `${…}` da `warn` aunque el
  daemon lo acepte, sin imprimirlo.
- Contador de 27 a 32: docstring de `checks.py`, comentario de `doctor.py`, `_NUMBER_WORDS` (hasta 34),
  asserts de `test_doctor.py` y `test_doctor_english.py`, `_CHECK_COUNT_WORDS` de `test_wiki.py` y la
  wiki.
- Wiki: filas nuevas en `Integration-install.md` (con las mínimas de la pestaña Code 2.1.286 y VS Code
  2.1.299 como límite documentado) y dos secciones en `Troubleshooting.md`.

## Tests primero

`tests/test_checks_plugin.py` (11 tests). Con las sondas vacías (`unknown`) fallaron todos por el
assert de estado (`assert 'unknown' == 'warn'` / `== 'missing'`), no por import.

## Mutante

Script en el scratchpad (`mutant.py`): cambia `if ours and plugin_enabled(settings):` por
`if ours and False:` en `probe_hook_duplicates` (se comprueba `text != text0`) y lo revierte (bytes
idénticos). Falla `test_doctor_flags_hooks_in_settings_and_plugin` en
`assert result.status == checks.WARN` (`'ok' == 'warn'`).

## Suite

`pesado.sh uv run pytest -n 2 -q`: 4301 passed, 28 skipped. `ruff check .` y
`ruff format --check .` limpios.

## Desviaciones

- El test del plan `test_desktop_literal_token_not_printed` se llama
  `test_desktop_literal_token_not_shown`: el detector de nombres en español no tiene `printed` en el
  léxico, y el léxico no es de este lote.
- Las pistas `claude update` y `claude plugin enable …` van por catálogo con una frase delante
  (`doctor.hint.*`), porque el guardián de textos sin catálogo no las admite como literales.
- Tests de Desktop de `test_checks.py` cambiados por REQ-012: token literal aceptado, `${VAR}` con
  valor en este shell y `Bearer` dentro de la variable pasan de `ok` a `warn`.
- Fuera de Windows no hay puente: un token literal en la entrada de la Mac da `warn` con una pista
  que no es `install --desktop`.

## Llamadas `local_*`

- `local_lint_summary(path=pytest.log)` ×1: primer fallo de la suite completa.
- `local_commit_msg(path=diff)` ×1: borrador del commit.
