# Specification: Doctor detecta el plugin de Claude importado en Codex: hooks.json con modules rechazado (#668)

Nivel: lite. Disparador: una comprobación nueva de `doctor` (cambia el número de checks y su
contrato de ids) y reglas copiadas de un parser externo que hay que citar. No sube a standard: el
cambio solo lee `~/.codex`; `install` no escribe nada nuevo en Codex.

## Summary

Codex CLI importa marketplaces de Claude Code, así que el plugin de local-delegate puede acabar
habilitado en Codex a mano. Codex 0.169.0 rechaza entero su `hooks/hooks.json` por el campo
`modules` y solo lo dice con un aviso al arrancar. `doctor` lo detecta, explica por qué no carga y
da el comando que lo quita sin tocar la entrada MCP. Las reglas del formato de Codex quedan en un
módulo propio, con fixtures negativas y una positiva comprobadas en un Codex real.

## Requirements

- **REQ-001** — `codex_plugin.check_hooks_file` marca como rechazo de fichero entero toda clave de
  primer nivel distinta de `description` y `hooks` (como `modules`), un `type` de manejador
  desconocido y las formas que no son objeto o lista donde Codex las espera; y como pérdida
  silenciosa los eventos que Codex no conoce, los campos desconocidos de manejador o de grupo
  (como `args`) y `${user_config.…}` en un comando. Un fichero en el formato de Codex no da nada.
  - Request: "Fixtures negativas para modules y positivas para el formato Codex soportado."
  - Verify: test tests/test_codex_plugin.py
- **REQ-002** — Las fixtures de `tests/fixtures/codex_plugin` y el `hooks.json` empaquetado del
  plugin de Claude dan en el validador lo mismo que dio un Codex 0.169.0 real al cargarlos como
  plugin con un `CODEX_HOME` temporal (cero hooks y aviso con `modules` o tipo desconocido; un hook
  con `${user_config.ld_bin}` sin argumentos; dos hooks sin aviso con el formato de Codex).
  - Request: "Investigar y registrar la carga real; no basarse solo en plugin list, enabled o presencia en caché."
  - Verify: cmd scratchpad live_fixtures.py contra codex 0.169.0 (registrado en verification.md)
- **REQ-003** — El check `codex.plugin` (grupo `scaffold`, solo lectura) da `warn` cuando una
  versión en caché de `local-delegate` está habilitada en `config.toml` y Codex rechaza o pierde
  parte de su `hooks.json`; el detalle nombra el plugin, la versión y qué falla, y la pista es
  `codex plugin remove local-delegate@<marketplace>`.
  - Request: "detectar y explicar incompatibilidad al diagnosticar una importación Claude en Codex"
  - Verify: test tests/test_codex_plugin.py
- **REQ-004** — `codex.plugin` da `ok` sin plugin en caché, con el plugin deshabilitado o sin
  entrada en `config.toml` (diciendo si sería incompatible), sin fichero de hooks, y con un
  `hooks.json` en el formato de Codex sin afirmar que cargue (remite a `/hooks` de Codex); da
  `unknown` sin `~/.codex`, como todo check de un cliente ausente.
  - Request: "No presentar enabled/caché/exit 0 como prueba de carga."
  - Verify: test tests/test_codex_plugin.py
- **REQ-005** — `codex.plugin` no escribe nada: el árbol del HOME queda igual byte a byte, y un
  `config.toml` roto o un `hooks.json` ilegible no tumban el check.
  - Request: "Mantener intacta la entrada MCP funcional y los hooks propios del usuario."
  - Verify: test tests/test_codex_plugin.py
- **REQ-006** — `install` con destino Codex no escribe plugin, marketplace ni caché de plugins en
  `~/.codex`.
  - Request: "que lo que local-delegate instale/genere para Codex sea un manifiesto que Codex CLI acepte"
  - Verify: test tests/test_codex_plugin.py
- **REQ-007** — El registro pasa a 36 checks y lo dicen el docstring de `checks.py`, los tests de
  contrato, la wiki (`Integration-install.md`, con su fila) y el CHANGELOG; el README explica que el
  plugin de Claude no sirve en Codex. Textos en español e inglés.
  - Request: "Una release toca CHANGELOG, README y docs/wiki/"
  - Verify: test tests/test_checks.py tests/test_wiki.py tests/test_doctor_english.py

## Acceptance scenarios

### Scenario: plugin de Claude importado y habilitado

- **Given** `~/.codex/plugins/cache/local-delegate/local-delegate/0.52.0/hooks/hooks.json` con `modules` y `[plugins."local-delegate@local-delegate"] enabled = true`
- **When** se corre `local-delegate doctor`
- **Then** `codex.plugin` sale `warn`, nombra `modules` y da `codex plugin remove local-delegate@local-delegate`

### Scenario: sin plugin en Codex

- **Given** un HOME con `~/.codex` y solo la entrada MCP
- **When** se corre `doctor`
- **Then** `codex.plugin` sale `ok` y el exit code no cambia por él

## Edge cases and failure behavior

- Dos marketplaces con el plugin: gana el peor y el detalle solo nombra los de ese estado.
- JSON ilegible en `hooks.json`: Codex también lo rechaza, así que es `warn`.
- `config.toml` ilegible: no hay habilitados que leer; el check no falla.

## Non-functional requirements

- Solo lectura; no lanza `codex` ni sale a la red. Sin datos personales en textos ni fixtures.
- No genera `trusted_hash` ni toca la revisión de confianza de Codex.

## Non-goals

- Entrega Codex nativa (plugin o hooks propios, instalador, desinstalación, atribución): issue #669.
- Migrar o deshabilitar el plugin automáticamente.
- Portar el mod (`register.js`) a Codex.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
