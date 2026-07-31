# Verification: Detectar y retirar los scripts de hooks huerfanos de instalaciones anteriores

## Environment

- **Revisión:** rama `feat/hooks-huerfanos`, sobre `main` en `02eb48c`.
- **Máquina:** Windows 11, Python 3.11 (uv). **Tiene el caso real**: cuatro huérfanos en
  `~/.claude/hooks/`, conviviendo con `telemetry.jsonl`, `__pycache__/` y la instalación buena.
- **Suite:** 463 tests, 1 skipped (451 al empezar el change; **+12**).

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | Check en el registro, grupo `andamiaje` | OK | `scaffold.hook_orphans`, tras `scaffold.hook_files` |
| REQ-002 | Los tres estados | OK | tests de `WARN` (con huérfanos), `OK` (sin) y `UNKNOWN` (sin Claude Code) |
| REQ-003 | Cuántos y dónde | OK | **ejecución real**: `[WARN] hooks huérfanos: 4 script(s) … sueltos en C:\Users\Yohan\.claude\hooks (hook_common.py, suggest_delegate_prompt.py, suggest_delegate_read.py, suggest_lint_summary.py)` |
| REQ-004 | La lista sale del paquete | OK | `packaged_hook_names()` lee `resources/hooks/*.py`; `test_los_nombres_de_hooks_salen_del_paquete_y_no_de_una_constante` comprueba que incluye `hook_common.py` —que `_SCRIPT_NAMES` **no** tiene— y que `__pycache__` no se cuela |
| REQ-005 | El probe no escribe | OK | el test de árbol byte a byte del registro sigue verde |
| REQ-006 | Solo la raíz | OK | `test_la_instalacion_buena_no_se_reporta_como_huerfana` + verificación al revés (abajo) |
| REQ-007, REQ-008 | Borrado quirúrgico | OK | `test_install_retira_los_huerfanos_y_no_toca_nada_mas`: compara **qué sobrevivió** (`telemetry.jsonl`, `__pycache__/`, `hook_de_terceros.py`) contenido a contenido |
| REQ-009 | `--dry-run` no borra | OK | test con `snapshot()` **y ejecución real contra el HOME de verdad**: el árbol de `~/.claude/hooks` quedó con el mismo SHA-256 (`80a1bc3e985135be`) |
| REQ-010 | Idempotencia | OK | `test_sin_huerfanos_no_se_planifica_el_retirado` |
| REQ-011 | Un fichero no borrable no tumba el install | OK | `try/except OSError` por fichero, con el motivo en el detalle |
| REQ-012 | `update` lo repara | OK | `test_warn_de_hooks_huerfanos_planifica_el_retirado` |
| REQ-013 | Los cuatro textos del tamaño | OK | `test_el_docstring_dice_cuantos_checks_hay_de_verdad` verde con `len(CHECKS) == 14` |
| REQ-014 | CHANGELOG, CRLF | OK | `CRLF=912, LF sueltos=0` |
| REQ-015 | Wiki | OK | fila nueva en la tabla y «trece piezas» → «catorce» |

### Ejecución real en la máquina afectada

```
$ local-delegate doctor
  [WARN] hooks huérfanos: 4 script(s) de una instalación anterior sueltos en
         C:\Users\Yohan\.claude\hooks (hook_common.py, suggest_delegate_prompt.py,
         suggest_delegate_read.py, suggest_lint_summary.py); no se ejecutan, pero confunden
         arréglalo con: local-delegate install

$ local-delegate install --dry-run
  [dry-run] [prune] C:\Users\Yohan\.claude\hooks — retira scripts de hooks de una instalación anterior

árbol de hooks antes=80a1bc3e985135be  después=80a1bc3e985135be   → IDÉNTICO
```

El `install` real **no se ha ejecutado** en esta máquina: borra ficheros del HOME del usuario y
esa autorización se pide aparte. Los cuatro huérfanos siguen ahí.

### Verificación al revés — las dos permutaciones peligrosas

**R-1, la peor: mirar el subdirectorio en vez de la raíz.** Cambiado
`claude_dir/"hooks"` por `claude_dir/"hooks"/HOOKS_SUBDIR`, caen **cinco** tests, entre ellos los
dos que existen justo para esto:

```
FAILED tests/test_checks.py::test_la_instalacion_buena_no_se_reporta_como_huerfana
FAILED tests/test_checks.py::test_complete_home_is_all_ok
FAILED tests/test_install.py::test_install_retira_los_huerfanos_y_no_toca_nada_mas
FAILED tests/test_install.py::test_sin_huerfanos_no_se_planifica_el_retirado
FAILED tests/test_checks.py::test_un_fichero_ajeno_en_la_raiz_no_cuenta_como_huerfano
```

**R-2: quitar el `is_file()`.** Aquí la verificación al revés **encontró un test que no probaba
nada**. La primera versión de `test_un_directorio_con_nombre_de_script...` solo comprobaba que un
directorio homónimo sobreviviera, y **pasaba igual con el `is_file()` quitado**: `unlink` sobre un
directorio lanza `OSError` y el `except` del propio retirado se lo traga. Se corrigió el test para
aseverar sobre `orphan_hook_scripts()` —sin `is_file()`, el directorio entra en la lista y el
`doctor` avisaría de un huérfano inexistente— y **entonces sí falla**:

```
FAILED tests/test_install.py::test_un_directorio_con_nombre_de_script_ni_se_cuenta_ni_se_toca
```

## Quality checks

- [x] **Tests:** `uv run pytest -q` → **463 passed, 1 skipped**.
- [x] **Lint:** `uv run ruff check .` → *All checks passed!*
- [x] **Formato:** `uv run ruff format --check .` → *53 files already formatted*
- [x] **JS del dashboard:** `extract_dashboard_js.py` + `node --check` → OK.
- [x] **Secretos:** sin credenciales, sin red, sin subprocesos, sin dependencias.
- [x] **Sin cambios ajenos:** `checks.py`, `install.py`, `update.py`, tres ficheros de test,
      `CHANGELOG.md`, `docs/wiki/Integration-install.md` y la traza SDD.

## Deviations and residual risk

- **Un test existente codificaba una regla que el check nuevo rompe con razón.**
  `test_empty_home_reports_missing_with_fix_hint` afirmaba que **todos** los checks de `andamiaje`
  son `missing` en un HOME vacío. `hook_orphans` nunca puede serlo: pregunta si **sobra** algo, no
  si falta, y en un HOME vacío la respuesta correcta es `ok`. Se añadió a la exclusión que ya
  tenía `scaffold.memory`, con el porqué escrito.
- **El borrado no deja `.bak`**, a diferencia del resto de escrituras de `install`. Decisión
  consciente y anotada en el plan: lo borrado son **copias de recursos empaquetados** que el
  propio `install` repone en el sitio correcto, no configuración editada por el usuario.
- **`__pycache__` de la raíz no se limpia**, aunque contenga los `.pyc` de los huérfanos: borrarlo
  tocaría también los de un hook de terceros que viva ahí.
- **`install` real pendiente de autorización** en esta máquina. El cambio está verificado end-to-end
  contra árboles simulados y con `--dry-run` contra el HOME real.
- **No verificado en macOS ni Linux** más allá del CI del PR. No hay nada específico de plataforma.
