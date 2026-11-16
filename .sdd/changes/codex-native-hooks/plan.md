# Implementation plan: Entrega Codex nativa: hooks de usuario, instalador y diagnóstico (#669, núcleo; la atribución por sesión va aparte)

## Approach

- **Alcance partido** tras la revisión del plan (`plan-review-1.md`, hallazgos 4 y 11): aquí van
  los hooks consultivos y su ciclo de vida; la atribución por sesión de las llamadas MCP de Codex
  es el siguiente PR (ver spec, «Non-goals»).
- **Hooks de usuario, no plugin.** `~/.codex/hooks.json` es la capa de usuario que Codex lee
  siempre (research, `load_hooks_json`), es JSON (fusión fiable) y no exige marketplace, caché ni
  `codex plugin add`. Un plugin de Codex añadiría su propio hash de contenido a la confianza
  (`plugin_trust.rs`) y otra superficie que instalar y retirar.
- **Un módulo nuevo, `codex_hooks.py`**: (a) configuración pura (`entries`, `command`, `merge`,
  `strip`, `inspect` para `doctor`); (b) manejadores `run_prompt` y `run_subagent_start`, que
  `hook_entry` despacha para los nombres `codex-*` y que solo cargan los módulos sueltos de
  `resources/hooks` (`hook_common`, `suggest_delegate_prompt`) como hacen los scripts. No importa
  `server`.
- **Confianza estable.** Intérprete del entorno `uv tool` (`claude_plugin.resolve_ld_bin`), que
  conserva su ruta en `uv tool upgrade`; comando sin versión. Grupo nuestro = un único manejador
  `command`, sin `commandWindows`, cuyo comando termina en `-m local_delegate.hook codex-<nombre>`.
  Se reescribe en su índice; lo que falta ocupa el primer `{"hooks": []}` sin matcher del evento
  (el hueco de un `uninstall` previo) o va al final; lo que sobra (duplicados, o al
  desinstalar) pasa a `{"hooks": []}` si tiene grupos detrás, porque Codex cuenta ese grupo en el
  índice y no carga nada (`discovery.rs`, `append_hook_events`, `enumerate` sobre los grupos), y se
  quita si queda al final. Así un grupo ajeno nunca cambia de clave. En Windows el comando va
  `"C:/…/python.exe" -I -m …` (Codex lo pasa a `cmd.exe /C "…"`); en POSIX, `shlex.quote`.
- **BOM = fichero rechazado.** Codex no se salta el BOM (`fs::read_to_string` +
  `serde_json::from_str`): `install` no escribe y `doctor` da `warn`.
- **«Distinta de la empaquetada»** = comando, matcher o timeout distintos de `entries()`; ese es el
  `warn` que repara `update`, y sus mensajes dicen que hay que aprobar otra vez en `/hooks`.
- **`[hooks]` de `config.toml`** solo cuenta si tiene grupos de eventos: `[hooks.state]` lo escribe
  Codex al aprobar y no provoca su aviso (`protocol/src/hooks.rs`, `discovery.rs`).
- **Sin telemetría de hooks.** Los manejadores Codex no llaman a `hook_common.record`: la serie P-4
  es de Claude Code. Cada despacho reescribe `LOG_DIR/codex-hooks-seen.json` (`{nombre: hora}`).
- **Textos.** Claves `codex.prompt.mechanical` y `codex.subagent.start` en `HOOK_TEXTS` (ASCII,
  es/en), sin «Claude» ni `ToolSearch`.
- **install/update/doctor/uninstall.** `plan_install` emite `Action("codex-hooks", …)` con literal;
  `plan_uninstall`, la simétrica. El intérprete sale de `Options.claude_ld_bin` (el mismo del entorno `uv tool`, que `update` ya pasa y los tests ya doblan; desviación registrada en `verification.md`), no de una opción nueva. `doctor`:
  check `codex.hooks` en `scaffold`. `update`: `Repair("codex.hooks", (WARN,), {"hooks"},
  {"codex"})`; con un fichero que Codex rechaza la acción no escribe y lo dice.

## Ordered tasks

- [x] T1 — Fixtures y tests primero: payloads de la forma oficial y esquemas de salida (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: tests/fixtures/codex_hooks/ (payloads `UserPromptSubmit` y `SubagentStart` y esquemas de entrada y salida copiados de `rust-v0.169.0`, con su procedencia en un README), tests/test_codex_hooks.py; validación con `jsonschema`, declarada en el grupo `dev` de `pyproject.toml` con versión exacta (la del lock) tras comprobarla en Socket (nota mínima 0.7), para no depender de que el SDK MCP la siga arrastrando
  - Verification: pytest tests/test_codex_hooks.py falla antes de T2 por la razón esperada (módulo ausente)
  - Depends on: none
- [x] T2 — `codex_hooks.py` y manejadores; despacho en `hook_entry`; textos en `hook_common` (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: src/local_delegate/codex_hooks.py (nuevo), src/local_delegate/hook_entry.py, src/local_delegate/resources/hooks/hook_common.py
  - Verification: pytest tests/test_codex_hooks.py tests/test_hook_entry.py tests/test_i18n_parity.py; comando real por `cmd.exe /C` en el test; mutante (texto de Claude en lugar del de Codex) detectado
  - Depends on: T1
- [x] T3 — `install`/`uninstall` y `update` (REQ-005, REQ-006, REQ-007)
  - Files or modules: src/local_delegate/install.py, src/local_delegate/update.py, src/local_delegate/resources/i18n/es/install.json, src/local_delegate/resources/i18n/en/install.json, tests/test_codex_hooks_install.py (nuevo)
  - Verification: pytest tests/test_codex_hooks_install.py tests/test_install.py tests/test_update.py; casos con grupo ajeno detrás, duplicado, BOM, `commandWindows`, CRLF, y desinstalar e instalar (mismo índice, sin huecos acumulados)
  - Depends on: T2
- [x] T4 — Check `codex.hooks` y recuento 37 (REQ-008)
  - Files or modules: src/local_delegate/checks.py, src/local_delegate/doctor.py, src/local_delegate/resources/i18n/es/doctor.json, src/local_delegate/resources/i18n/en/doctor.json, tests/test_codex_hooks_doctor.py (nuevo), tests/test_checks.py, tests/test_doctor.py, tests/test_doctor_english.py
  - Verification: pytest de esos ficheros; instantánea del HOME; casos `[hooks.state]` solo (no avisa) y `[hooks]` con eventos (avisa)
  - Depends on: T2
- [x] T5 — Documentación (REQ-009, REQ-011)
  - Files or modules: CHANGELOG.md, README.md, docs/wiki/Integration-install.md, tests/test_wiki.py, scripts/data/spanish_lexicon.json si el detector lo pide
  - Verification: pytest tests/test_wiki.py tests/test_checks.py tests/test_detect_spanish_names.py
  - Depends on: T3, T4
- [x] T6 — Prueba con Codex 0.169.0 real y `CODEX_HOME` temporal (REQ-010)
  - Files or modules: scripts/dev/codex_hooks_live.py (nuevo), .sdd/changes/codex-native-hooks/verification.md
  - Verification: `hooks/list` tras `install --home <tmp>`, tras `uninstall` con un grupo ajeno detrás y con BOM; hashes del `~/.codex` real antes y después
  - Depends on: T3
- [x] T7 — Suite completa, revisión de regresiones y pasos de la prueba manual (REQ-011)
  - Files or modules: .sdd/changes/codex-native-hooks/verification.md, handoff.md, review.md
  - Verification: `pesado.sh` pytest -n 2; ruff; `personal-harness sdd check codex-native-hooks`
  - Depends on: T1, T2, T3, T4, T5, T6

## Test strategy

- Unit: entradas, fusión/retirada sobre ficheros con grupos ajenos (delante, detrás, mezclados,
  con `commandWindows`), textos y salida validada con `jsonschema` contra los esquemas oficiales.
- Integration: `plan_install`/`apply`/`plan_uninstall` y `update.plan_repairs` sobre HOME simulado
  (`use_cli=False`); el check sobre HOME simulado con instantánea.
- End-to-end or manual: comando generado lanzado por `cmd.exe /C` (Windows) o `sh -lc` (POSIX);
  Codex 0.169.0 real con `CODEX_HOME` temporal (T6); prueba de confianza del usuario.
- Controles que pueden fallar: excepción y `SystemExit(2)` dentro del manejador; texto de Claude
  sustituido por el de Codex; grupo ajeno detrás (índice).
- Security and secret scanning: sin ids ni rutas en la marca de despacho; escaneo antes del commit.

## Migration and compatibility

- Quien corra `install` con Codex en el destino recibe los dos hooks; no corren hasta que los
  apruebe en `/hooks`. `update` no los añade donde no estaban.
- `doctor` pasa de 36 a 37 checks; sin hooks de Codex el check nuevo es `ok`.
- Tests existentes que cambian a propósito: recuentos 36 → 37 y lista de ids.
- El camino de Claude Code no cambia.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
