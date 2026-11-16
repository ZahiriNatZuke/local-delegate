# Implementation plan: Doctor detecta el plugin de Claude importado en Codex: hooks.json con modules rechazado (#668)

## Approach

Un módulo nuevo de solo lectura, `codex_plugin.py`, copia las reglas del parser de Codex CLI
0.169.0 (`openai/codex`, etiqueta `rust-v0.169.0`): `HooksFile` en
`codex-rs/config/src/hook_config.rs` (`deny_unknown_fields`, solo `description` y `hooks`),
`HookEventsToml`, `MatcherGroup` y `HookHandlerConfig` en `codex-rs/protocol/src/hooks.rs`, el
fichero por defecto `hooks/hooks.json` y el aviso `failed to parse plugin hooks config` en
`codex-rs/core-plugins/src/loader.rs`, la caché `plugins/cache` en
`codex-rs/core-plugin-common/src/installed.rs` y las variables de entorno del hook en
`codex-rs/hooks/src/engine/discovery.rs` (ninguna expande `${user_config.…}`). Cada hallazgo dice
si Codex rechaza el fichero entero o pierde una pieza en silencio.

`checks._probe_codex_plugin` recorre `~/.codex/plugins/cache/<marketplace>/local-delegate/<versión>`,
cruza con `[plugins."local-delegate@<marketplace>"] enabled` de `config.toml` (con `tomllib`) y da
un veredicto por versión; gana el peor. Está en `scaffold` porque solo lee el HOME y no lanza
`codex`, así `install` también lo muestra. La pista es `codex plugin remove …`, comprobado en un
`CODEX_HOME` temporal: quita `[plugins.…]` y la caché y deja `[mcp_servers.local-delegate]`.

No se cambia el `hooks.json` del plugin de Claude: quitar `modules` rompería el mod en Claude Code
y aun así Codex perdería los `args` y no expandiría `${user_config.ld_bin}` (medido). La entrega
nativa para Codex es el issue #669.

## Ordered tasks

- [x] T1 — Reproducir en Codex real y fijar las reglas del parser (REQ-001, REQ-002)
  - Files or modules: src/local_delegate/codex_plugin.py, tests/fixtures/codex_plugin/*.json, tests/test_codex_plugin.py
  - Verification: script de scratchpad que carga cada fixture con `codex plugin marketplace add` + `codex plugin add` y pregunta `hooks/list` al app-server, con `CODEX_HOME` temporal; pytest tests/test_codex_plugin.py
  - Depends on: none
- [x] T2 — Check `codex.plugin` y sus textos es/en (REQ-003, REQ-004, REQ-005)
  - Files or modules: src/local_delegate/checks.py, src/local_delegate/resources/i18n/es/doctor.json, src/local_delegate/resources/i18n/en/doctor.json, tests/test_codex_plugin.py, tests/test_checks.py
  - Verification: pytest tests/test_codex_plugin.py tests/test_checks.py tests/test_doctor_english.py
  - Depends on: T1
- [x] T3 — Guarda de que `install` no pone el plugin en Codex (REQ-006)
  - Files or modules: tests/test_codex_plugin.py
  - Verification: pytest tests/test_codex_plugin.py
  - Depends on: none
- [x] T4 — Recuento a 36 y documentación (REQ-007)
  - Files or modules: src/local_delegate/checks.py, src/local_delegate/doctor.py, tests/test_checks.py, tests/test_doctor.py, tests/test_doctor_english.py, tests/test_wiki.py, docs/wiki/Integration-install.md, README.md, CHANGELOG.md
  - Verification: pytest tests/test_checks.py tests/test_wiki.py tests/test_doctor.py; suite entera
  - Depends on: T2

## Test strategy

- Unit: validador contra cada fixture, el `hooks.json` empaquetado y formas sueltas; control
  positivo con todos los eventos y tipos de Codex para que un hallazgo signifique algo.
- Integration: el check sobre HOME simulados (`make_home`) con caché y `config.toml` escritos como
  los deja `codex plugin add`; instantánea del árbol antes y después.
- End-to-end or manual: Codex 0.169.0 real con `CODEX_HOME` temporal (no toca `~/.codex`; hash de
  `~/.codex/config.toml` igual antes y después).
- Security and secret scanning: sin secretos ni rutas personales en fixtures ni textos.

## Migration and compatibility

- `doctor` pasa de 35 a 36 checks. Un `warn` nuevo puede subir el exit code a 1 en quien tenga el
  plugin de Claude habilitado en Codex: es el caso que el issue pide señalar.
- Tests existentes modificados a propósito: recuentos 35 → 36, lista de ids con `codex.plugin`, y
  `codex.plugin` apartado del test de HOME vacío (no puede faltar algo que `install` no escribe).

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
