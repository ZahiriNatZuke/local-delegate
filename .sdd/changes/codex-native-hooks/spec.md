# Specification: Entrega Codex nativa: hooks de usuario, instalador y diagnóstico (#669, núcleo; la atribución por sesión va aparte)

Nivel: standard. Disparador: escribe configuración de un cliente externo (`~/.codex/hooks.json`)
que convive con hooks del usuario y con la revisión de confianza de Codex.

**Alcance partido (revisión del plan, hallazgos 4 y 11).** Este cambio entrega el núcleo: los
hooks consultivos de Codex y su ciclo `install`/`update`/`doctor`/`uninstall`. La atribución por
sesión de las llamadas MCP de Codex (hook `PreToolUse` de nota, lectura de `_meta.callId`, y
apartar las filas de Codex del relleno a posteriori, del panel y del resumen por sesión) queda
como siguiente paso, descrita en «Non-goals» y en `handoff.md`: toca el log de uso, el relleno y
el panel, y se revisa mejor aparte.

## Summary

`local-delegate install` con destino Codex añade a `~/.codex/hooks.json` dos hooks consultivos
propios en el formato que acepta Codex 0.169.0, sin mover ni tocar los grupos del usuario;
`update` los repone si no son los empaquetados, `doctor` dice por separado si están configurados,
aprobados y vistos despachar, y `uninstall` quita solo los suyos sin cambiar la posición (y por
tanto la aprobación) de los del usuario. Ningún hook bloquea nada ni depende del backend.

## Requirements

- **REQ-001** — `codex_hooks.entries(python)` da exactamente dos manejadores `command` sin `args`
  ni `commandWindows`: `UserPromptSubmit` sin matcher → `codex-prompt` y `SubagentStart` sin
  matcher → `codex-subagent-start`, con comando `<intérprete citado> -I -m local_delegate.hook
  <nombre>` y `timeout` 30. El fichero que resulta pasa `codex_plugin.check_hooks_file` sin
  hallazgos.
  - Request: "Definir un adaptador/entrega Codex con la forma de hooks realmente soportada; no copiar modules ni suponer que el payload Claude es idéntico."
  - Verify: test tests/test_codex_hooks.py
- **REQ-002** — Con payloads de la forma oficial (campos requeridos de los esquemas
  `hooks/schema/generated` de `rust-v0.169.0`): `codex-prompt` emite, para un prompt mecánico, un
  JSON que cumple el esquema de salida de `UserPromptSubmit` con un texto `codex.prompt.mechanical`
  sin la palabra «Claude», y nada para un prompt no mecánico o un evento de sistema;
  `codex-subagent-start` emite un JSON que cumple el esquema de salida de `SubagentStart` sin
  mencionar `ToolSearch`. Control negativo: la salida de los hooks de Claude para el mismo evento
  no cumple el texto de Codex (nombra Claude o `ToolSearch`).
  - Request: "Fixtures con payloads oficiales/observados de Bash, apply_patch, MCP y code mode; controles negativos que detecten matcher equivocado y campos ausentes." (Aquí: campos ausentes; Bash, `apply_patch`, MCP, code mode y matcher pasan al siguiente PR, ver «Non-goals».)
  - Verify: test tests/test_codex_hooks.py
- **REQ-003** — Fallo en abierto: los dos `codex-*` salen con 0 y sin texto con stdin vacío, no
  JSON o no objeto, y con `LD_HOOK_ENABLED=0`; con el backend marcado como caído no emiten
  consejo. Control positivo: un manejador `codex-*` que lanza una excepción o `SystemExit(2)` sale
  con 0 y deja una línea en `hook-failures.jsonl` solo con el tipo. El comando generado, lanzado
  como lo lanza Codex (`cmd.exe /C "<comando>"` en Windows, `sh -lc` en POSIX), da la salida
  esperada; con un intérprete inexistente sale con un código distinto de 2, que Codex trata como
  fallo que no bloquea.
  - Request: "Arranque y herramientas normales siguen funcionando con backend caído y con todos los modelos descargados; errores del adaptador fallan abiertos y quedan diagnosticables."
  - Verify: test tests/test_codex_hooks.py
- **REQ-004** — Los hooks `codex-*` no escriben en la telemetría de hooks (la serie de la ventana
  P-4 es de Claude Code) y cada despacho deja en `LOG_DIR/codex-hooks-seen.json` solo
  `{nombre: hora UTC}`, sin nada del payload.
  - Request: "Documentar diferencia entre telemetría global del daemon y atribución por sesión. No registrar ids o rutas sensibles en claro ni credenciales."
  - Verify: test tests/test_codex_hooks.py
- **REQ-005** — `install` con destino `codex` y componente `hooks` fusiona `~/.codex/hooks.json`:
  un grupo es nuestro solo si tiene exactamente un manejador `command`, sin `commandWindows`, cuyo
  comando termina en `-m local_delegate.hook codex-<nombre>`; los nuestros que ya están se
  reescriben en su mismo índice y los que faltan ocupan el primer grupo vacío `{"hooks": []}` sin
  matcher del evento (el hueco que deja `uninstall`, sin manejadores ni clave de confianza) o, si
  no hay, se añaden al final; así desinstalar e instalar devuelve cada hook a su índice, no
  acumula huecos y, con el mismo hash, la aprobación anterior vuelve a valer sin que
  `local-delegate` escriba ningún `trusted_hash`; los grupos ajenos
  conservan orden, contenido e índice (y con ello su clave de confianza). Un duplicado nuestro se
  sustituye por un grupo vacío `{"hooks": []}` si hay grupos detrás (Codex lo cuenta en el índice y
  no carga nada) y se quita si es el último. La segunda pasada no escribe; se guarda
  `hooks.json.bak` una vez si el fichero existía; se conserva el final de línea; `--dry-run`
  imprime el JSON de nuestros grupos y no escribe. No escribe, y lo dice, con un fichero ilegible,
  con BOM (Codex lo rechaza entero: `fs::read_to_string` + `serde_json`), con claves que Codex
  rechaza, o sin intérprete de `uv tool`.
  - Request: "Integrarlo en install/update/doctor/uninstall, con descubrimiento explícito del destino, dry-run, idempotencia, respaldos y coexistencia con configuración ajena."
  - Verify: test tests/test_codex_hooks_install.py
- **REQ-006** — `update` repone nuestros hooks de Codex cuando `codex.hooks` está en `warn` por
  entradas nuestras que difieren de `entries()` (comando, matcher o timeout), que faltan o cuyo
  intérprete no existe, y dice que hay que volver a aprobarlas en `/hooks`; con las entradas al día
  no reescribe nada; nunca los añade a un Codex donde no hay ninguno nuestro.
  - Request: "Integrarlo en install/update/doctor/uninstall"
  - Verify: test tests/test_codex_hooks_install.py
- **REQ-007** — `uninstall` con destino `codex` y componente `hooks` quita solo nuestros grupos:
  cada uno con grupos detrás pasa a `{"hooks": []}` (los ajenos no cambian de índice ni de
  aprobación) y los del final se quitan; un evento que queda solo con grupos vacíos nuestros se
  quita; el fichero se borra solo si no queda nada y no había `.bak`; no toca `config.toml`.
  - Request: "Desinstalar retira solo lo gestionado por local-delegate."
  - Verify: test tests/test_codex_hooks_install.py
- **REQ-008** — Check `codex.hooks` (grupo `scaffold`, solo lectura): `unknown` sin `~/.codex` o
  con el fichero ilegible; `ok` «no instalados (opcionales)» sin entradas nuestras; `ok` con las
  dos al día, diciendo por separado configurado (fichero), aprobado (cuántas de nuestras claves
  `"<ruta>:<evento>:<grupo>:<manejador>"` tienen `trusted_hash` en `[hooks.state]`, sin afirmar que
  siga vigente) y visto despachar (`codex-hooks-seen.json`), y avisando si `[hooks]` de
  `config.toml` tiene grupos de eventos (sin contar `state`), que Codex avisa al cargar los dos;
  `warn` con `local-delegate update` si falta alguna, difiere de `entries()` o su intérprete no
  existe, diciendo que tras reparar hay que aprobar otra vez; `warn` si Codex rechazaría el fichero
  entero (claves ajenas o BOM). El árbol del HOME queda igual byte a byte. 37 checks.
  - Request: "Los checks distinguen configurado, cargado y probado."
  - Verify: test tests/test_codex_hooks_doctor.py
- **REQ-009** — CHANGELOG («Unreleased»), README y wiki declaran qué eventos cubre la entrega
  Codex y cuáles no (en este PR no hay hook sobre herramientas: ni llamadas MCP, ni code mode, ni
  Bash ni `apply_patch`; llamadas MCP, code mode y atribución por sesión: siguiente paso; lecturas, shell,
  `apply_patch`: #670; interfaz y comandos: #671), la diferencia entre la telemetría global del
  daemon y la atribución por sesión, y los pasos de aprobación en `/hooks`; recuentos al día;
  textos es/en.
  - Request: "declarar exactamente qué eventos y herramientas quedan cubiertos, incluido code mode"
  - Verify: test tests/test_checks.py tests/test_wiki.py tests/test_doctor.py tests/test_doctor_english.py tests/test_i18n_parity.py
- **REQ-010** — Con Codex 0.169.0 real y un `CODEX_HOME` temporal, el `hooks.json` que escribe
  `install` (HOME simulado, con un grupo ajeno previo) carga por `hooks/list` con nuestros dos
  manejadores, el ajeno con su clave intacta, `warnings` y `errors` vacíos y `trustStatus`
  `untrusted`; tras `uninstall` con un grupo ajeno añadido detrás, ese grupo conserva su clave; un
  `hooks.json` con BOM da un aviso de Codex y cero hooks. Los `~/.codex/config.toml` y
  `~/.codex/hooks.json` reales tienen el mismo hash antes y después. El script queda en
  `scripts/dev/` y su salida en `verification.md`.
  - Request: "Codex real: configuración estricta sin warning, evento que realmente despacha el hook y delegación MCP identificada correctamente; las fixtures solas no bastan."
  - Verify: cmd scripts/dev/codex_hooks_live.py contra codex 0.169.0 (registrado en verification.md)
- **REQ-011** — El despacho real de los hooks en Codex queda como prueba manual del usuario, con
  pasos exactos (aprobar en `/hooks`, escribir un prompt mecánico, comprobar
  `codex-hooks-seen.json` y `doctor`), porque exige su aprobación de confianza.
  - Request: "No generar trusted_hash ni saltarse revisión de confianza; conservar permisos y secretos referenciados por variable."
  - Verify: manual pasos en handoff.md y en la wiki; resultado del usuario pendiente

## Acceptance scenarios

### Scenario: instalar junto a hooks del usuario

- **Given** `~/.codex/hooks.json` con un grupo `PreToolUse/Bash` del usuario
- **When** se corre `local-delegate install --clients codex`
- **Then** el grupo del usuario sigue el primero y sin cambios, los nuestros van detrás, existe
  `hooks.json.bak` y una segunda pasada no reescribe nada

### Scenario: desinstalar sin quitarle la aprobación al usuario

- **Given** nuestro grupo `UserPromptSubmit` en el índice 0 y uno del usuario en el 1
- **When** se corre `local-delegate uninstall --clients codex`
- **Then** el índice 0 queda `{"hooks": []}` y el del usuario sigue en el 1

### Scenario: volver a instalar tras desinstalar

- **Given** el fichero que deja el escenario anterior (hueco en el 0, grupo del usuario en el 1)
- **When** se corre otra vez `local-delegate install --clients codex`
- **Then** nuestro grupo vuelve al índice 0, el del usuario sigue en el 1 y no queda ningún hueco

### Scenario: backend caído

- **Given** el backend sin responder
- **When** el usuario escribe un prompt mecánico en Codex
- **Then** el hook sale con 0 sin consejo y Codex sigue

## Edge cases and failure behavior

- `hooks.json` con JSON roto, no UTF-8, BOM o claves de primer nivel ajenas: `install` no
  escribe (lo dice) y `doctor` da `unknown` o `warn`; nunca se pisa.
- Un manejador nuestro dentro de un grupo con otros manejadores, o con `commandWindows`: no se
  considera nuestro y no se toca.
- `[hooks]` de `config.toml` con grupos de eventos: Codex avisa de las dos representaciones;
  `doctor` lo dice y `install` sigue. Solo `[hooks.state]` (lo que escribe Codex al aprobar) no
  cuenta.
- Reescribir un grupo nuestro que difería cambia su hash: Codex lo verá `Modified` y hay que
  aprobarlo otra vez; los mensajes lo dicen.

## Non-functional requirements

- Seguridad: no se genera ni copia `trusted_hash`; no se tocan permisos ni `config.toml` de Codex;
  ni secretos ni ids en claro en la marca de despacho.
- Compatibilidad: reglas de Codex 0.169.0 (`codex_plugin.CODEX_VERSION_CHECKED`); el camino de
  Claude Code no cambia.
- Operabilidad: todo hook falla en abierto; `doctor` no lanza `codex` ni sale a la red.

## Non-goals

- **Siguiente paso de #669 (otro PR):** hook `PreToolUse` sobre `^mcp__local[-_]delegate__` con
  nota de Codex (prefijo propio en el nombre del fichero), lectura de `_meta.callId` solo de
  `codex-mcp-client`, decisión sobre `_meta.sessionId`, y filas de Codex fuera del relleno a
  posteriori, `excluded` en el coste y con columna propia en el panel y el resumen por sesión.
  De la petición de REQ-002 pasan también a ese PR los fixtures de `PreToolUse` (Bash,
  `apply_patch`, MCP y code mode, con ids `exec-<uuid>`) y los controles negativos del matcher
  (matcher equivocado o sin ancla); aquí solo hay `UserPromptSubmit` y `SubagentStart`, sin matcher.
- Resumen automático de lecturas, guard de escritura, hooks de shell o de `apply_patch` (#670).
- Comandos sin modelo, barra de estado, herramientas fijadas, matriz de capacidades (#671).
- Plugin de Codex, marketplace o caché de plugins. Medir el esfuerzo (no viene en el payload).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
