# Verification: Registro unico de comprobaciones del andamiaje y doctor que ve el sistema entero

## Environment

- Revisión: rama `feat/checks-andamiaje` sobre `main` en `6a1dabc`.
- Windows 11, Python 3.11 (uv), venv editable del repo. Daemon vivo (0.13.1, pid 27032);
  backend llama-swap **caído** durante la verificación, lo que resultó útil: probó el camino
  degradado en vivo.
- Suite: **309 tests** (antes 277) + 1 skip esperado (chmod no quita lectura en Windows).

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `checks.py` con `Check`/`Result`/`Context` y `CHECKS` | OK | `test_registry_has_the_eleven_checks_with_unique_ids` |
| REQ-002 | cuatro estados con detalle de una línea | OK | `test_every_status_has_a_label_and_only_warn_and_missing_count` |
| REQ-003 | cliente ausente y permisos → `unknown` | OK | `test_absent_client_is_unknown_not_missing`, `test_unreadable_file_is_unknown_not_missing` (POSIX), `test_unreadable_file_is_unknown_via_read_helpers` (toda plataforma), `test_invalid_json_is_unknown` |
| REQ-004 | los once elementos | OK | `len(CHECKS) == 11`; ejecución real en esta PC muestra los once agrupados |
| REQ-005 | hooks propios vs ajenos vía `install._is_ours` | OK | `test_foreign_hook_is_not_counted_as_ours`, `test_our_hook_alongside_a_foreign_one_is_ok` |
| REQ-006 | sin red el comando no falla | OK | `test_run_doctor_without_network_does_not_fail` (GitHub, backend y daemon caídos → exit 1, sin excepción) |
| REQ-007 | timeouts acotados | OK | `query_daemon` 1 s, `_port_taken` 1 s, `/models` 2 s, GitHub 5 s; `doctor` real responde en ~2 s |
| REQ-008 | once checks agrupados, estilo y exit code | OK | ejecución real (salida abajo); `test_run_doctor_exit_0_when_everything_is_in_place`, `..._exit_1_when_outdated` |
| REQ-009 | `missing` cuenta, `unknown` no | OK | HOME totalmente vacío → 11 `[ -- ]` y el único aviso es el backend caído; `test_undetected_version_is_unknown_not_missing` |
| REQ-010 | no desaparece ninguna salida previa | OK | `test_run_doctor_keeps_the_previous_output`; `--online` real conserva el sufijo de GitHub, la compuerta de soak y los issues `[HOLD]` |
| REQ-011 | `--home DIR` | OK | `local-delegate doctor --home <tmp>` ejecutado en dos formas (HOME vacío y HOME con clientes vacíos) |
| REQ-012 | qué comando lo arregla | OK | `arréglalo con: local-delegate install` / `local-delegate serve` en la salida real |
| REQ-013 | `doctor` no escribe | OK | `test_run_doctor_writes_nothing_in_the_simulated_home`, `..._in_an_empty_home`, `test_no_probe_writes_anything` (árbol byte a byte); comprobado además en vivo: el HOME simulado quedó con 0 entradas |
| REQ-014 | `install` intacto | OK | `tests/test_install.py` sin tocar y verde |

### Ejecución real en esta PC (`local-delegate doctor`)

Encontró tres cosas ciertas que nadie veía antes:

1. `[FALT] hooks copiados` — los scripts viven en `~/.claude/hooks/` (instalación **heredada**),
   no en `~/.claude/hooks/local-delegate/`.
2. `[WARN] hooks registrados: 3 de 3 en el formato heredado con 'args', que Claude Code no
   ejecuta` — las tres entradas están **muertas**. Sin este matiz el check habría dicho `ok`
   sobre hooks que no corren: el falso `ok` más caro del registro.
3. `[WARN] MCP en Codex: entrada http … puesta a mano (sin marcadores)` — coherente con la
   edición manual del PR #51.

## Quality checks

- [x] `uv run pytest -q --basetemp=<temp propio>` → 309 passed, 1 skipped.
- [x] `uv run ruff check .` → All checks passed.
- [x] `uv run ruff format --check .` → 48 files already formatted.
- [x] `uv run python scripts/extract_dashboard_js.py && node --check dashboard.js` → JS OK.
- [x] Sin secretos: ningún probe lee `auth.json` ni imprime rutas de credenciales; la entrada MCP
      solo se reporta por tipo y URL/comando.
- [x] Sin cambios ajenos: `install.py` no se tocó. Único extra, pedido por el usuario a mitad de
      la tarea: `.idea/` añadido al `.gitignore`.

## Deviations and residual risk

- **Un bug encontrado por ejecución, no por lectura:** la flecha `→` del `fix_hint` reventaba la
  consola de Windows (`UnicodeEncodeError`, cp1252) — el diagnóstico moría justo cuando algo
  estaba mal. Se quitó; toda la salida se mantiene dentro de cp1252.
- **Matiz sobre el escenario «HOME limpio» de la spec:** con un HOME *totalmente* vacío los once
  checks salen `[ -- ]`, no `[FALT]`, porque no hay ni `~/.claude` ni `~/.codex` y manda REQ-003
  (regla) sobre el ejemplo del escenario. Los `[FALT]` con su pista aparecen en cuanto el
  directorio del cliente existe pero el andamiaje no — verificado con `--home` en esa forma.
- **Ampliación deliberada respecto al plan:** el check de hooks registrados distingue el formato
  heredado (`args`) y lo reporta `warn`. No estaba en el plan; salió de la ejecución real y cabe
  en REQ-002 («está pero no como debería»). Son cinco líneas, no un mecanismo nuevo.
- **Cambio de comportamiento consciente:** el backend caído ahora cuenta como aviso (exit 1),
  donde antes no. Lo pide el escenario de aceptación («exit 0 si el backend también está sano»);
  queda anotado en el CHANGELOG.
- **No verificado:** el comportamiento en macOS/Linux del check de permisos solo está cubierto por
  el test que dobla `read_text`; el que usa `chmod` se salta en Windows y correrá en el CI.
