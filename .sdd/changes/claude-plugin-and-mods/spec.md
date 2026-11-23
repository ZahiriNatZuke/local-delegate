# Especificación v2: local-delegate como plugin de Claude Code, con mods, y entrada del chat de Desktop

> v2 (2026-10-21): incorpora `review-spec.md` (26 hallazgos) y la decisión del usuario de dejar el
> **MCP fuera del plugin**. Con eso caen los bloqueos 1, 2 y 4: las tools no cambian de nombre, la
> Mac (modo stdio) sigue igual y la entrada del chat de Desktop se llama `local-delegate`, como la
> de `~/.claude.json`, así que en la pestaña Code gana una sola y no hay duplicado.
>
> v2.1 (2026-10-21, al aprobar `plan.md`): cambian de letra REQ-003 y REQ-023 (sección «Cambios de
> letra de la spec» del plan; `review-plan.md`, segunda pasada). La intención no cambia.
>
> - **REQ-003**: cada hook invoca el punto de entrada `hook` del paquete instalado por ruta absoluta
>   (el ejecutable o el intérprete del entorno de `uv tool`), sin depender del `PATH`; `ld_bin` sale
>   solo de una instalación de `uv tool`. El resto de REQ-003 no cambia.
> - **REQ-023**: en 0.41, con entrega por plugin, el hook de lectura se aparta en las vías que el mod
>   cubre en esa sesión; si el mod no actúa, actúa el hook. Se mantienen F4 apagada por defecto hasta
>   cumplir REQ-022 en vivo y el aviso de `doctor` cuando los dos actúan sobre la misma vía.

## Resumen

local-delegate se entrega a Claude Code (terminal, pestaña Code de Claude Desktop y VS Code) como
**un plugin con los hooks y un mod**. El MCP sigue en `~/.claude.json` escrito por `install` (http o
stdio, como hoy) y la skill y el bloque de `CLAUDE.md` los sigue escribiendo el CLI. El mod deja las
tools principales siempre cargadas, añade comandos que delegan sin turno del modelo, muestra cuota y
ahorro, y sustituye la parte `Read` del bloqueo de lectura por una lectura delegada con elección. El
**chat** de Claude Desktop recibe su entrada MCP desde `install` si se pide. **Codex, OpenCode y WSL
siguen con la entrega por settings.** Hechos: `research.md`.

## Decisiones de diseño (con su motivo)

- **MCP fuera del plugin** (usuario): evita el renombrado de tools, permisos y 54 agentes, y no rompe
  la Mac en stdio.
- **Skill y bloque de `CLAUDE.md` por el CLI**: el CLI los escribe en el idioma vigente (es/en); un
  plugin trae un fichero fijo y el bloque de `CLAUDE.md` no lo puede escribir.
- **El plugin sale del paquete instalado**: el marketplace es la carpeta del plugin dentro del
  paquete Python instalado (`uv tool`), así la versión del plugin es siempre la del paquete auditado.
  El repo también publica `.claude-plugin/marketplace.json` en GitHub para quien quiera solo el
  plugin, pero `install` usa la carpeta local.
- **Comandos en inglés** (`/local-summarize`, `/local-commit`, `/local-lint`): los comandos no
  admiten `:` y los nombres del proyecto van en inglés; los textos que muestran, en es/en.

## Fases y entregas

| Fase | Contenido | Release |
|---|---|---|
| F1 | Plugin con hooks; migración en `install`/`doctor`/`update`/`uninstall`; estado de instalación; chat de Desktop opcional | — |
| F2 | Mod: tools fijas + comandos | **0.40.0** (F1+F2) |
| F3 | Mod: cuota y ahorro | — |
| F4 | Mod: lectura delegada (sustituye la entrada `Read` del bloqueo) | **0.41.0** (F3+F4; coincide con la retirada de los 7 nombres) |

## Requisitos

### F1 — Plugin, migración y estado

- **REQ-001** — Plugin en el paquete. El paquete incluye la carpeta del plugin `local-delegate`
  (`.claude-plugin/plugin.json`, `hooks/hooks.json`, el mod desde F2; sin `bin/` en su raíz) y un
  `marketplace.json` que la publica. La versión del plugin es la del paquete; `bump_version.py` la
  escribe y `tests/test_release_metadata.py` la comprueba. Pasa `claude plugin validate --strict`.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_plugin_package.py::test_plugin_version_matches_package`, `test_release_metadata.py::test_plugin_json_version_matches_pyproject`, job `plugin` (`validate --strict`, rueda)
- **REQ-002** — Hooks del plugin. En 0.40, `hooks.json` declara los mismos eventos y filtros que la
  0.39 escribe en `settings.json`: los dos de siempre (`UserPromptSubmit` y `record_call` sobre
  `mcp__local-delegate__.*`) y las tres entradas del bloqueo de lectura (`Read`, `read_*` de otros
  MCP y `Bash|PowerShell`). En 0.41 cambia solo lo que dice REQ-023.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_plugin_package.py::test_hooks_json_matches_settings_delivery_0_39`
- **REQ-003** — Hooks por subcomando, rápidos y que no bloquean. Cada hook invoca
  `local-delegate hook <nombre>` por su ruta absoluta (`${user_config.ld_bin}`, rellenada por
  `install`), sin depender de `python` ni del `PATH` de la app (macOS). p95 ≤ 300 ms por invocación
  (20 invocaciones medidas en Windows). Un nombre de hook desconocido sale con 0 sin texto. Si el
  subcomando falla o no arranca, el hook **deja pasar** (nunca bloquea un prompt ni una tool por un
  fallo propio). Los scripts actuales siguen para la entrega por settings.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test Control positivo y negativo de B-1 en `evidence/T0.md`, `test_plugin_package.py::test_every_hook_entry_is_fail_open`, `test_hook_entry.py::test_hook_crash_lets_the_call_through`, `::test_hook_path_does_not_import_server`, `measure_hook_latency.py`
- **REQ-004** — Interruptor del bloqueo de lectura. El estado vive en la configuración de
  local-delegate (fichero como `language.json`); `install --enable-read-hook` lo enciende. Precedencia:
  `~/.claude/local-delegate-block-off` (apagado en caliente, nombre vigente desde 0.38) >
  `LD_HOOK_READ_BLOCK` > fichero de estado. Los hooks escriben la misma telemetría que hoy
  (`blocks.jsonl`), para no cortar la serie de la ventana P-4.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_read_switch.py::test_active_layer_state_file_or_enabled_env`, `::test_block_state_values_unchanged`, `test_plugin_migration.py::test_migration_carries_read_switch_on/off`
- **REQ-005** — Entrega por plugin por defecto, con fallback. Con `claude` en el `PATH` y versión
  ≥ `MIN_CLAUDE_PLUGIN_VERSION` (constante; el plan fija el número), HOME real y fuera de WSL,
  `install` usa la entrega por plugin: `claude plugin marketplace add <carpeta del paquete>` y
  `claude plugin install local-delegate@local-delegate --scope user --config ld_bin=<ruta>`, no
  interactivo. Flag `--claude-delivery plugin|settings`. En los demás casos (versión menor, sin CLI,
  HOME simulado sin `CLAUDE_CONFIG_DIR` comprobado, WSL), entrega por settings como hoy, con aviso.
  `--dry-run` muestra los comandos `claude plugin …` sin ejecutarlos.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_claude_plugin.py::test_min_version_gate`, `::test_simulated_home_passes_claude_config_dir`, `test_install_plugin_delivery.py::test_falls_back_to_settings_with_warning`
- **REQ-006** — Migración sin duplicados. En el mismo paso que instala el plugin, `install` retira de
  `settings.json` (con una copia) los hooks que escribía la entrega por settings y borra
  `~/.claude/hooks/local-delegate/`. La entrada MCP, la skill y el bloque de `CLAUDE.md` no se tocan.
  Nada ajeno se toca. Idempotente.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_plugin_migration.py::test_migration_removes_every_settings_hook_we_wrote`, `::test_backup_is_pre_install_bytes`, `::test_migration_is_idempotent` (+ mutantes)
- **REQ-007** — Estado de la instalación. Un fichero de estado en la configuración de local-delegate
  registra la vía de entrega de Claude Code, la versión, y qué piezas escribió `install` (plugin,
  marketplace, entrada del chat de Desktop) con fecha. `doctor`/`update`/`uninstall` lo leen en vez
  de adivinar; una pieza que existía antes y no figura en el estado no se borra.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_install_state.py::test_missing_state_means_unknown_not_empty`, `::test_state_follows_language_dir_rule`
- **REQ-008** — Migración desde la 0.39 y vuelta atrás. (a) `update` en una instalación por settings
  que cumple REQ-005 migra al plugin con REQ-006 y avisa de reiniciar las sesiones abiertas.
  (b) `install --claude-delivery settings` con el plugin puesto lo desinstala y repone settings en el
  mismo paso. (c) Bajar a la 0.39 exige `uninstall` antes; la CHANGELOG y la wiki lo dicen, y
  `doctor` de la 0.40 avisa si encuentra hooks en settings y plugin a la vez. Una prueba por punto en
  HOME simulado (`CLAUDE_CONFIG_DIR`).
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test a: `test_update_plugin.py::test_settings_install_migrates_carries_switch_and_warns_restart`; b: `test_plugin_migration.py::test_revert_to_settings_in_one_step`; c: `test_checks_plugin.py::test_doctor_flags_hooks_in_settings_and_plugin`. Las tres en HOME simulado con `CLAUDE_CONFIG_DIR`
- **REQ-009** — `doctor`. Checks nuevos: vía de entrega (según el estado); plugin instalado,
  habilitado y con la versión del paquete; `ld_bin` apunta a un ejecutable que existe; versión de
  `claude` ≥ la mínima; **duplicados** (hooks de local-delegate en `settings.json` y en el plugin a la
  vez); estado del mod (cargado o no, desde F2). En la pestaña Code de Desktop y VS Code no se puede
  medir la versión desde el CLI: la wiki dice las mínimas (Desktop ≥ 2.1.286, VS Code ≥ 2.1.299).
  Dentro de WSL no se espera plugin. Textos es/en, filas en la wiki y contador al día.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_checks.py::test_check_ids_exact`, `test_checks_plugin.py::test_mod_loaded_from_heartbeat`
- **REQ-010** — `update`. Con plugin: tras subir el paquete, `claude plugin marketplace update` y
  `claude plugin update local-delegate@local-delegate`, en ese orden; repara el plugin si falta; si
  encuentra duplicados, **retira** los de settings (no los repone). Con settings: como hoy. `plan_pin`
  y `service.daemon_auth` no cambian (el MCP sigue en `~/.claude.json`).
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_update_plugin.py::test_marketplace_update_before_plugin_update`, `::test_update_never_restores_settings_hooks_under_plugin`
- **REQ-011** — `uninstall`. Desinstala el plugin y el marketplace si los puso `install` (según el
  estado), la entrada del chat de Desktop si la escribió `install`, y deshace lo de `--agents` (hoy no
  lo hace). Nada ajeno.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_uninstall_plugin.py::test_removes_only_what_state_lists`, `test_agents_uninstall.py::test_uninstall_undoes_agents_edit`

### F1 — Chat de Claude Desktop (opcional)

- **REQ-012** — Entrada del chat por un puente propio, con flag. Medido el 2026-10-21
  (`research-r5-desktop-env-and-mcp-errors.md`): Desktop **no** pasa su entorno a los MCP (solo una
  lista fija de variables del sistema más el `env` literal de la entrada) y **no** expande `${VAR}`
  en `claude_desktop_config.json`. Por eso: un subcomando nuevo `local-delegate desktop-bridge`
  (MCP por stdio que reenvía al daemon HTTP) lee él mismo el token (variable de usuario del registro
  en Windows / la fuente que use el daemon en macOS) y nunca se escribe en la config.
  `install --desktop` escribe solo la clave `local-delegate` con la ruta absoluta del ejecutable y
  `desktop-bridge`; sin `npx` ni `mcp-remote`. Copia previa única y rotada, con permisos solo del
  usuario. Si la clave ya existía y no la escribió `install` (en esta PC: `mcp-remote` con token
  literal, puesta a mano), solo la reemplaza con `--desktop`, avisando. Desktop lanza cada servidor
  dos veces (chat y Cowork/Code): el puente lo soporta. `doctor`: entrada con `${…}` → warn (no se
  expande); token literal en la entrada → warn sin imprimirlo; puente que no autentica → warn.
  `update` reescribe la ruta si cambia el ejecutable.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_desktop_bridge.py::test_bridge_against_real_daemon_app`, `test_install_desktop.py::test_desktop_flag_on_macos_refuses_cleanly`, `test_desktop_config.py::test_detects_literal_token_without_printing`, puente contra el daemon real en `evidence/F2-live.md`

### F2 — Mod: tools fijas y comandos

- **REQ-013** — Tools siempre cargadas. El mod saca de ToolSearch una lista configurable
  (`userConfig`) de tools `mcp__local-delegate__*`, con 4 por defecto: `local_summarize`,
  `local_extract`, `local_lint_summary`, `local_commit_msg` (~2 000 tokens). Lista vacía = apagado.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `pinned-tools.test.ts` (job `plugin`)
- **REQ-014** — Comandos sin turno del modelo. `/local-summarize <ruta>`, `/local-commit` (diff
  preparado → `local_commit_msg`; **solo muestra** el mensaje) y `/local-lint <fichero|comando>`. 0
  turnos del modelo; la salida queda como contexto del siguiente turno. `/local-lint` con comando usa
  `$.process.run` (argumentos partidos con las reglas de Windows y POSIX, tope 30 s); donde
  `process.run` no está disponible o un admin lo veta, acepta solo un fichero y lo dice. Si el daemon
  no responde, error claro. Textos en el idioma de salida de local-delegate.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `commands.test.ts` (`lint_without_process_run_accepts_only_file`, `commit_temp_file_removed`)
- **REQ-015** — Delegaciones del mod separables. Las llamadas del mod llevan `tool_use_id`
  `toolu_plugin_…` y `caller_src: "hook"` (medido en vivo: vault
  `investigacion-mods-claude-code-2026-10-21.md` §3). El panel y el script de medición las separan
  por ese prefijo de `tool_use_id`. Se vuelve a verificar en vivo en F2 con una llamada del mod y una
  del modelo en la misma sesión.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_dashboard_states.py::test_mod_calls_shown_apart`, `evidence/F2-live.md`
- **REQ-016** — Mod acotado y degradable. El mod solo lee la variable `LOCAL_DELEGATE_WEB_TOKEN`
  (nombre literal), solo habla con `127.0.0.1`, nunca registra el token. Si el mod falla o la API
  cambia, los hooks y el MCP siguen funcionando (probado desactivando el mod). Cada pieza del mod se
  puede apagar por `userConfig`.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_mod_static.py::test_mod_reads_only_the_token_variable`, `::test_register_loads_pieces_dynamically_inside_try`; en vivo, piezas a `off` y `register.js` que lanza

### F3 — Cuota y ahorro

- **REQ-017** — Barra de estado. % de cuota de la sesión (`session.measure`) y ahorro de la sesión
  según el daemon (`/api/stats` con el token del entorno). Si el daemon no responde, se oculta sin
  error. Apagable por `userConfig`.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_metrics_session_filter.py::test_stats_filters_by_session`, `status.test.ts` (`hides_when_daemon_down`)

### F4 — Lectura delegada

> F4 absorbe el backlog §1.5 (decisión del usuario, 2026-10-21): el modelo lee por muchas vías
> (`Read` entero o por franjas, `cat`/`type`/`Get-Content`/`head`/`tail`, `sed -n`, `awk`, `grep`
> amplio, `python -c "open(…)"`, tuberías, y tools de lectura de otros MCP); el 2026-10-13 el hook de
> shell clasificó 1 681 lecturas como «no es un volcado» y los agentes bloqueados releyeron por
> franjas. Cubrir solo `Read` repetiría ese error.

- **REQ-018** — Medir antes por qué vías se lee. Script versionado que recorre los transcripts
  recientes (sin pasar su contenido por el contexto) y cuenta las lecturas de ficheros por vía:
  `Read` entero y por franjas, cada forma de comando de shell (incluidas tuberías), `Grep` con salida
  grande y tools de lectura de otros MCP (`filesystem`, `obsidian`, `github`, `markitdown`…), con
  tamaño del fichero. Se ejecuta antes de diseñar F4 y fija qué vías cubre F4 por volumen; la tabla
  queda en la evidencia.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_measure_read_paths.py::test_counts_each_path_kind`, `evidence/F4-read-paths.md`
- **REQ-019** — Un solo clasificador de lectura. Un único módulo decide si una llamada es «leer el
  fichero X» y con qué alcance (entero, franja, volcado parcial, no clasificable). Lo usan el mod y
  los hooks de la entrega por settings (Codex). Cubrir una vía nueva es tocar solo ese módulo. Tests
  con un corpus de comandos reales sacado de REQ-018.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_read_classifier.py::test_corpus` (+ mutantes), `::test_classifier_change_moves_fingerprint`
- **REQ-020** — Lectura acumulada por fichero. El mod lleva en la sesión cuánto de cada fichero se ha
  leído y por qué vías; si las franjas o volcados parciales suman ≥ un umbral del fichero (el plan lo
  fija con los datos de REQ-018), cuenta como lectura entera.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `read.test.ts` (`accumulates_ranges_to_whole`)
- **REQ-021** — Lectura con elección. Con entrega por plugin y el interruptor de REQ-004 encendido,
  para las vías **clasificables con seguridad** y por encima de los umbrales: en sesión con diálogo,
  botones «resumir con el modelo local / leer entero» (resumir llama a `local_summarize` y entrega el
  resumen como resultado); sin diálogo (`-p`, subagentes), **el mod resume él mismo y entrega el
  resumen como resultado**, sin denegar ni sugerir (decisión del usuario, 2026-10-22: la delegación
  no puede depender de que el modelo obedezca una sugerencia; tres mediciones dieron cero). La
  lectura real sigue disponible solo por franjas por debajo del umbral (REQ-020) y REQ-022 protege
  las escrituras. Para las vías **no clasificables con seguridad**: solo aviso y registro, nunca
  bloqueo. Telemetría de REQ-004 por vía.

  > **Enmienda (2026-10-28, 0.44.2, #472).** Excepciones a «la lectura real sigue disponible solo
  > por franjas por debajo del umbral»: (a) en un subagente, una lectura por rango nunca se resume
  > ni suma a la cobertura compartida del fichero, igual que el principio del #443; (b) en el hilo
  > principal, un fichero corto (≤ 200 líneas y < 32 KB) pasa literal; (c) un rango que empieza
  > después de la última línea del fichero pasa literal. El texto de los REQ no cambia.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `read.test.ts` (`buttons_when_dialog`, `denies_without_dialog`, `unclassifiable_only_warns`, `respects_read_switch_off`)

- **REQ-022** — Nunca escribe sobre un resumen. Tras una lectura resumida de un fichero (por
  cualquier vía), el mod rechaza `Edit`, `Write`, `NotebookEdit` y escrituras de shell reconocibles
  sobre ese fichero con el mensaje «léelo con `offset`/`limit` antes de modificarlo» hasta que haya
  una lectura real. Verificable en `-p`: control positivo (sin mod, `Write` pasa) y negativo (con mod,
  `Write` se rechaza y el hash del fichero no cambia). `--resume` tras una lectura resumida: probado o
  límite documentado.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `read.test.ts` (`blocks_write_after_summary`, `guard_survives_resume`); control positivo y negativo en `evidence/F4-live.md`
- **REQ-023** — Sustitución de los hooks de lectura. En 0.41, con entrega por plugin, `hooks.json`
  deja de declarar las entradas de lectura que el mod cubre (según REQ-018/019); las que no cubra
  siguen como hooks con el mismo interruptor. F4 sale **apagada por defecto** hasta cumplir REQ-022 en
  vivo; mientras, los hooks de lectura siguen como en 0.40. `doctor` avisa si el mod de lectura y un
  hook de lectura cubren la misma vía a la vez.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_hook_step_aside.py::test_read_hook_steps_aside_when_mod_active`, `::test_read_hook_does_not_step_aside_for_another_session`, `::test_no_gap_when_active_but_not_blocking`, `::test_read_hook_acts_when_mod_off_or_stale`, `test_checks_plugin.py::test_read_mod_and_read_hook_overlap_warns`

### Medición

- **REQ-024** — Medición fijada antes. Script versionado (de `scratchpad/r4/baseline_sessions.py`),
  que cuenta por `tool_use_id` sin depender del prefijo de las tools: % de sesiones interactivas de
  Claude Code con ≥ 1 delegación decidida por el modelo (sin `toolu_plugin_` ni ventanas de prueba).
  Base: recalculada **solo desde el 2026-10-08** (antes faltan `tool_use_id`). Se mide 14 días tras
  instalar la 0.40.0 aquí. Éxito: ≥ +10 puntos con ≥ 30 sesiones. Mide el efecto conjunto de la 0.40
  (no se puede atribuir solo a las tools fijas); sin control de Codex (no discrimina: 0
  delegaciones). Si no sube: se apagan las tools fijas y se quedan los comandos.
  - Request: derived: spec v2 aprobada por el usuario el 2026-10-21 (gate `spec`)
  - Verify: test `test_measure_plugin_adoption.py::test_counts_sessions_not_calls`, `::test_plugin_calls_excluded`; la lectura con fecha

## Tabla pieza × verbo (entrega por plugin)

| Pieza | install | doctor | update | uninstall |
|---|---|---|---|---|
| Entrada MCP `~/.claude.json` | como hoy | como hoy | como hoy (`plan_pin`) | como hoy |
| Hooks | plugin; retira los de settings | plugin ok, duplicados, `ld_bin` | `plugin update`; retira duplicados | desinstala plugin |
| Scripts en `~/.claude/hooks/local-delegate/` | borra | huérfanos → warn | borra | borra |
| Skill `local-delegation` | como hoy (CLI, es/en) | como hoy | como hoy | como hoy |
| Bloque de `CLAUDE.md` | como hoy | como hoy | como hoy | como hoy |
| `--agents` | como hoy | — | — | **deshace** (nuevo) |
| Mod (F2–F4) | dentro del plugin | cargado | con el plugin | con el plugin |
| Interruptor de lectura | fichero de estado | precedencia | — | borra el fichero |
| Chat de Desktop | `--desktop` (puente) | `${…}`, token literal, puente | ruta del ejecutable | si lo escribió install |
| Estado de instalación | escribe | lee | actualiza | borra |

## Pruebas exigidas

- CI sin cuenta, en los tres SO: `claude plugin validate --strict`; instalación y migración en
  config aislada (`CLAUDE_CONFIG_DIR`); `claude -p` sin sesión para los hooks de inicio; versión de
  Claude Code fijada y auditada con Socket.
- Latencia de los hooks (REQ-003) y fallo del subcomando → deja pasar.
- En vivo en Windows (la Mac la prueba el usuario): `claude -p --plugin-dir … --max-turns 1` **desde
  PowerShell**, en ventana de prueba; F4 en sesión interactiva.
- Mutantes que demuestren los tests de duplicados, migración y REQ-019.
- La release toca `CHANGELOG.md`, `README.md` y `docs/wiki/`.

## Fuera de alcance

Codex, OpenCode y WSL (siguen por settings, aunque sus hooks usan el clasificador de REQ-019); `.mcpb`; la skill en el chat de Desktop (se sube a mano
en claude.ai); panel lateral del mod; MCP dentro del plugin.

## Preguntas que resuelve el plan

- T0 resuelto: Desktop no hereda ni expande variables (research-r5); de ahí el puente.
- `MIN_CLAUDE_PLUGIN_VERSION` exacta.
- Si `claude plugin` respeta `CLAUDE_CONFIG_DIR` para las pruebas con HOME simulado.
- Si `$.process.run` funciona en la pestaña Code de Desktop.
