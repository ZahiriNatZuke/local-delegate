# Plan de implementación v2: local-delegate como plugin de Claude Code, con mods, y entrada del chat de Desktop

> v2 (2026-10-21): incorpora `review-plan.md` (2 bloqueantes, 18 importantes, 14 menores) y las
> decisiones de orquestación del 2026-10-21. La respuesta a cada hallazgo está al final.
> Plan de la spec v2 aprobada (`spec.md`, 24 REQ en F1–F4). Hechos de partida: `research.md` y
> `research-r1`…`r5`; riesgos de la spec: `review-spec.md`. Reglas comunes: `brief.md` §«Reglas para
> agentes» y la sección «Reglas de ejecución» de este plan.
>
> Abreviatura: `<plugin>/` = `src/local_delegate/resources/claude-plugin/local-delegate/`;
> `<i18n>/X.json` = `src/local_delegate/resources/i18n/{es,en}/X.json`.

## Enfoque

Cuatro fases, en el orden que fijó el usuario, repartidas en **olas**. Dentro de una ola los lotes
tienen ficheros **disjuntos** y van en paralelo, con un worktree y un PR por lote. Una ola empieza
cuando la anterior está mezclada en `main`. Si dos lotes necesitarían el mismo fichero, la pieza
nueva va a un **módulo nuevo** de una ola temprana, y cada fichero compartido (`install.py`,
`update.py`, `checks.py`, `cli.py`, `config.py`, `ci.yml`, `plugin.json`, `hooks.json`, la wiki)
tiene **un solo dueño por ola**. La disjunción se comprueba con un programa, no a ojo (ver «Reglas de
ejecución»).

Decisiones de diseño que toma el plan, además de las de la spec:

1. **El plugin vive dentro del paquete**, en `src/local_delegate/resources/claude-plugin/`. Esa
   carpeta es el marketplace local (`.claude-plugin/marketplace.json`) y `local-delegate/` es la
   raíz del plugin (`.claude-plugin/plugin.json`, `hooks/hooks.json` y, desde F2, `register.js` y
   `mod/`). No lleva `bin/` en la raíz del plugin. El repo publica además
   `/.claude-plugin/marketplace.json`, que apunta a la misma subcarpeta.
2. **Contrato de los hooks**: `hook prompt | record-call | read | shell | mcp-read` y, en F4,
   `hook classify`. Ningún hook nuestro necesita el código de salida 2: hoy los bloqueos se hacen
   con JSON `permissionDecision: deny` y salida 0 (`hook_common.py:134-155`). Por eso **cualquier
   salida distinta de 0 se puede convertir en «deja pasar» sin perder conducta**. Eso es lo que
   aprovecha la decisión 3.
3. **Un ejecutable viejo, ausente o roto nunca bloquea** (bloqueante B-1). La 0.39 responde con
   código 2 a `local-delegate hook prompt` (argparse), y en Claude Code ese código **bloquea el
   prompt**. El plugin queda en la caché aunque el paquete baje de versión, así que no basta con
   documentarlo. T0 mide tres vías con control positivo y negativo, y el plan toma **la primera que
   pase**, en este orden:
   - **A. `onFailure` del motor** (≥ 2.1.295) en las cinco entradas, si convierte el código 2, el
     ejecutable inexistente y el fallo de arranque en «deja pasar». Es la más fuerte: no depende del
     ejecutable ni del shell. Con A, `MIN_CLAUDE_PLUGIN_VERSION` sube a **2.1.295**.
   - **B. Intérprete del entorno de `uv tool` con `-I -m local_delegate.hook <nombre>`**: `ld_bin`
     pasa a ser la ruta absoluta del `python` de ese entorno. En la 0.39 el módulo no existe y Python
     sale con 1 (error no bloqueante), nunca con 2. Si falta el intérprete, falla el arranque, que
     T0 comprueba que no bloquea. El módulo nuevo envuelve todo y siempre sale con 0. Desvía la
     letra de REQ-003 («invoca `local-delegate hook <nombre>`») pero mantiene su intención (ruta
     absoluta, sin `python` del `PATH`, nunca bloquea). Si se elige, la spec se ajusta en ese
     punto antes de la ola 1.
   - **C. Forma shell con `|| exit 0`**: solo si A y B fallan, y solo si T0 demuestra en Windows
     qué shell usa el motor para los hooks y que el entrecomillado aguanta. Es la menos fiable
     (memoria `hooks-args-si-se-ejecutan`).

   Si ninguna pasa, el plan **no avanza a la ola 1**: vuelve a la sesión principal con la
   evidencia. No se acepta como límite.
4. **El atajo de los hooks no carga el servidor.** El despacho de `hook` va en `__init__.main`,
   con el import de `entrypoint` diferido; `__version__` pasa a ser perezoso (`__getattr__` del
   módulo). Con B, `local_delegate/hook.py` solo importa `hook_entry`. Un test vigila los
   `sys.modules`.
5. **Los textos nuevos van en catálogos nuevos**: `plugin.json`, `bridge.json`,
   `plugin_install.json` y `plugin_update.json`. El prefijo de cada clave coincide con el nombre
   del fichero, como exige `test_i18n_parity.py`.
6. **El clasificador de lectura (REQ-019) es un único módulo Python** de librería estándar:
   `resources/hooks/read_classifier.py`. Lo usan tres sitios: los scripts de la entrega por
   settings (sueltos en `~/.claude/hooks/`), el subcomando `hook` y el mod. El mod lo llama a través
   de `hook classify` (stdin JSON → stdout JSON) por `$.process.run`. El mod solo añade un filtro
   barato que **descarta** antes de llamar (nombre de tool y primer token); no clasifica.
7. **El mod es JavaScript plano, sin toolchain de Node.** `hooks/hooks.json` declara
   `"modules": ["./register.js"]`. **T0 midió que el motor rechaza `import()` dinámico** (en
   `validate` y al cargar; `evidence/T0.md`), así que `scripts/build_mod.py` concatena las piezas
   (`mod/common.js`, `pinned-tools.js`, `commands.js`, `status.js`, `read.js`) en `register.js` y
   envuelve el registro de **cada pieza en su propio `try`**: si la pieza falta, lanza o tiene su
   interruptor apagado, queda apagada y el resto sigue (REQ-016). Así los lotes de F2–F4 solo crean
   su fichero en `mod/`. La interfaz de `mod/common.js` queda fijada en la ola 3 (ver ese lote). El
   generado **no se commitea**: lo produce el job de empaquetado al construir la rueda, y un test
   comprueba que el script corre y que una pieza que lanza no tumba las demás.
8. **La `userConfig` del plugin se declara en dos tandas.** En la ola 1, `ld_bin` (obligatoria) y
   `language`. En la ola 3, `pinned_tools`, `commands_enabled`, `status_enabled` y
   `read_mod_enabled` (este, por defecto `false`). F3 y F4 no tocan `plugin.json`. `update` vuelve
   a aplicar `--config language=…` si cambió `language.json`.
9. **«Mod cargado» se sabe por un latido.** Al iniciar sesión, el mod escribe
   `<config>/plugins/data/<plugin>-<marketplace>/heartbeats/<session_id>.json` (T0: la variable
   `CLAUDE_PLUGIN_DATA` **no llega al mod**, así que deriva esa ruta, que es la misma carpeta que
   ven los hooks como `CLAUDE_PLUGIN_DATA`; `$.fs.write` escribe ahí) con la versión, `entrypoint`, si
   `process.run` respondió, si hay diálogo, si el mod de lectura está activo y la fecha. Es un
   fichero **por sesión**: una sesión nunca se guía por el latido de otra. Los de más de 7 días se
   borran al escribir. `doctor` lo lee, y los hooks de lectura lo usan para
   apartarse (decisión 10). Si T0 muestra que `$.fs.write` no puede escribir ahí, el latido va a
   `POST /api/mod-heartbeat` del daemon, y en ese caso el lote de la ola 3 posee `web/metrics.py`.
10. **REQ-023 sin quitar entradas de `hooks.json`.** Los hooks de lectura siguen declarados y **se
    apartan** solo cuando el mod va a hacer **exactamente lo que habría hecho el hook**. Eso se
    cumple con cuatro condiciones a la vez:
    - `CLAUDE_PLUGIN_OPTION_READ_MOD_ENABLED` es verdadero;
    - el latido de **su misma sesión** (`session_id` del payload) dice que el mod de lectura está
      activo y que `process.run` respondió;
    - la capa *bloquea* está en `on`;
    - la vía es clasificable.

    En el modo «solo registrar» (capa *activo* encendida, bloqueo apagado) el mod no actúa y el hook
    actúa siempre, así que no queda hueco en el registro. Si el mod se apaga o falla, el hook vuelve
    a actuar, como pide REQ-016. La nueva letra de REQ-023 está en «Cambios de letra de la spec».
11. **Chat de Desktop solo en Windows.** En macOS y Linux, `install --desktop` se niega con un
    mensaje claro (es/en), sale distinto de 0 y no toca nada. Allí no hay daemon local ni fuente del
    token (la Mac va por stdio contra el backend de la PC). El puente y `token_source` solo leen el
    registro de Windows (`HKCU\Environment`).

## Respuestas a «Preguntas que resuelve el plan»

| Pregunta | Respuesta del plan | Cómo se cierra |
|---|---|---|
| `MIN_CLAUDE_PLUGIN_VERSION` | **2.1.292** si gana la vía B o C; **2.1.295** si gana A (`onFailure`) | La fuente es r1 §4 [DOC]. `install --marketplace` (2.1.292) es la más alta de las funciones que usamos; `onFailure` es 2.1.295. T0 lo confirma instalando esa versión en una config aislada; si algo falla, sube a la primera versión que pase. |
| ¿`claude plugin` respeta `CLAUDE_CONFIG_DIR`? | **Sí en Windows con la 2.1.306** (r1 §3 [PRUEBA]) | T0 lo repite con la versión mínima. El job `plugin` del CI lo comprueba en los tres SO (instala en un `CLAUDE_CONFIG_DIR` vacío y comprueba que `~/.claude/plugins` real no cambia). Si falla en algún SO, el HOME simulado de ese SO cae a settings (REQ-005 ya lo prevé). |
| ¿`$.process.run` en la pestaña Code de Desktop? | Sin medir (r4: «CLI only» [DOC]; debería funcionar [3º]) | En «Medición en vivo de F2»: el latido registra `process_run` y `entrypoint`, y el usuario abre una sesión en la pestaña Code. VS Code no se mide: límite documentado en la wiki. La alternativa de REQ-014 se implementa siempre. Sin `process.run`, el mod de lectura no actúa y los hooks no se apartan (decisión 10). |
| Umbral de lectura acumulada (REQ-020) | Lo fija el primer lote de F4 | Es una salida de «Medir por qué vías se lee» (REQ-018). |

## Reglas de ejecución (obligatorias para cada implementador)

- **Primer paso**: cargar las `local_*` con `ToolSearch` y usarlas (ficheros grandes con `path`;
  salida de tests volcada a fichero y pasada por `local_lint_summary`). En la entrega se listan las
  llamadas; «0» exige motivo.
- **Comandos pesados de uno en uno en toda la máquina**: `bash ~/.claude/scripts/pesado.sh <comando>`
  **desde la tool Bash**. Incluye pytest con `-n 2`, `uv build`, `uv sync`, instalaciones,
  `claude plugin validate|test` y el navegador.
- **Un worktree por agente**: `D:/Projects/ld-wt-<lote>`, con rama propia; nunca sobre el checkout
  principal.
- **Fines de línea**: el repo mezcla LF y CRLF fichero a fichero. No se convierte nada. Antes de
  cada commit, `git ls-files --eol <tocados>` debe dar lo mismo que en `main`.
- **Idioma**: código, identificadores, claves, ficheros, opciones y comandos en inglés. Los textos
  al usuario van por catálogo es/en, con paridad comprobada.
- **Commits firmados**, **sin** coautoría de Claude (la memoria del proyecto anula al harness).
  CodeQL a 0 alertas nuevas: se arreglan, no se descartan. Un PR solo está cerrado con
  `gh pr checks <n>` en verde.
- **`claude -p` solo desde PowerShell**, con `--max-turns 1` y `--plugin-dir`, y dentro de una
  ventana de prueba: `local-delegate test-window start --label "<lote>"` → guardar el id →
  `local-delegate test-window stop <id>`.
- **Secretos**: el token no se escribe en ninguna config, copia, log, evidencia, temporal ni test.
  **No se reintenta `${VAR}` en `claude_desktop_config.json`.**
- **No se tocan** `~/.claude/settings.json`, `~/.claude.json` ni `claude_desktop_config.json`
  reales, el daemon ni el `uv tool` instalado. Todo va en HOME simulado o en un `CLAUDE_CONFIG_DIR`
  del scratchpad. Con `--home` simulado, todo `claude …` hijo recibe `CLAUDE_CONFIG_DIR=<home>/.claude`.
  Instalar en la PC real y reiniciar el daemon lo hace la sesión principal (el usuario hace `/mcp`).
- **CLI de Claude Code para T0 y CI**: versión exacta. Antes se pasa Socket (`depscore`) del paquete
  `@anthropic-ai/claude-code@<versión>`. Primero se intenta `pnpm` con `--ignore-scripts`. Si así no
  queda funcional, se usa el instalador nativo con la versión fijada. T0 deja escrita la vía elegida.
- **Disjunción por programa**: antes de abrir los worktrees de una ola, la sesión principal saca
  con un script las listas «Posee» de los lotes de esa ola y comprueba que no se cruzan (solo se
  admite `CHANGELOG.md`).
- **Cada lote**: (1) tests que fallan primero, y por el assert correcto; (2) cambio; (3) suite
  completa con `pesado.sh`, `ruff check` y `ruff format --check`; (4) línea en `CHANGELOG.md`
  `[Unreleased]` (rebasar); (5) PR y checks; (6) `evidence/<lote>.md` con comandos, resultados y
  llamadas `local_*`; (7) nada huérfano (shells, servidores, ventanas de prueba).

## Olas y lotes

| Ola | Lotes en paralelo | Espera a |
|---|---|---|
| 0 | Medición previa (T0) → PR de documentos del SDD | — |
| 1 (F1) | Plugin empaquetado · Subcomando de hooks, interruptor y variables · Estado, vía y orquestación de la entrega · Puente del chat de Desktop | PR de documentos |
| 2a (F1) | Instalar y desinstalar con plugin · `doctor` con plugin | ola 1 |
| 2b (F1) | `update` con plugin | ola 2a |
| 3 (F2) | Esqueleto del mod y tools fijas · Comandos sin turno · Delegaciones del mod separables y medición | ola 2b |
| 3b | Medición en vivo de F2 → **release 0.40.0** | ola 3 |
| 4 (F3/F4) | Cuota y ahorro en la barra · Medir por qué vías se lee · Retirada de los siete nombres en desuso | 0.40.0 publicada |
| 5 (F4) | Clasificador único de lectura · Mod de lectura con elección | ola 4 |
| 6 (F4) | Coordinación de hooks y mod de lectura → Verificación en vivo de F4 → **release 0.41.0** | ola 5 |
| — | Lectura de la medición de adopción (REQ-024), a los 14 días de instalar la 0.40.0 aquí | 0.40.0 + 14 días |

### Ola 0 — Medición previa (T0) y PR de documentos

Un solo agente, porque la CLI y `claude -p` son un recurso único. No hay código del producto: todo
va al scratchpad y a `evidence/T0.md`.

- **Rescate**: copia `scratchpad/r4/baseline_sessions.py` (sesión `ed2ae533…`, carpeta temporal) a
  `.sdd/changes/claude-plugin-and-mods/evidence/baseline_sessions.py`.
- **CLI**: instala la versión mínima candidata por la vía de las reglas de ejecución. Con un
  `CLAUDE_CONFIG_DIR` del scratchpad prueba `plugin validate --strict --json`,
  `marketplace add <carpeta>`, `plugin install …@… --scope user --config ld_bin=… --json`,
  `plugin list --json`, `plugin update` y `plugin uninstall`. Comprueba que `~/.claude/plugins` real
  no cambia.
- **Hooks que nunca bloquean (B-1)**: en una carpeta del scratchpad, un entorno con
  `local-delegate-mcp==0.39.0` (pesado), sin tocar el `uv tool`.
  - **Control positivo**: un plugin mínimo con `UserPromptSubmit` → `<exe 0.39> hook prompt`
    **bloquea** el prompt en `claude -p` (código 2).
  - **Control negativo**: cada vía tiene sus casos, porque la B no convierte el código 2 sino que
    lo **evita**. Todos los casos se corren dos veces, sobre `UserPromptSubmit` y sobre un
    `PreToolUse` de `Read`, y en todos el resultado esperado es **deja pasar**:

    | Vía | Casos |
    |---|---|
    | A `onFailure` | ejecutable 0.39 (sale con 2) · ejecutable inexistente · ejecutable que sale con 2 a propósito |
    | B `-I -m local_delegate.hook` | entorno 0.39 (sale con 1, ya medido por el revisor) · intérprete inexistente · entorno con el Python base borrado (`pyvenv.cfg` apunta a una ruta que ya no existe; se mide con qué código sale el lanzador de venv de Windows) · envoltorio de prueba con un `sys.exit(2)` dentro y otro con una excepción dentro: los dos deben salir con 0 |
    | C `\|\| exit 0` | los mismos de A |

    Se registra la primera vía que pase todos sus casos y queda fijado `MIN_CLAUDE_PLUGIN_VERSION`.
- **Motor**: `${user_config.*}` en `command` (r1 solo lo probó en `args`); `hooks.json` con `hooks`
  y `modules` a la vez; un `register.js` que lanza al cargar no se lleva por delante los hooks del
  mismo `hooks.json`; `import()` dinámico relativo desde `register.js`; `$.fs.write` en
  `${CLAUDE_PLUGIN_DATA}`; `--config` rellena una `userConfig` de plugin; qué campo distingue una
  sesión con diálogo de `-p` y de un subagente (`entrypoint`, `agent_id`…). Todo desde PowerShell,
  en ventana de prueba y con `--max-turns 1`.
- **Salida**: la vía de B-1 y `MIN_CLAUDE_PLUGIN_VERSION`, la respuesta sobre `CLAUDE_CONFIG_DIR`,
  la forma del mod (`import()` o `build_mod.py`), dónde va el latido y la señal de «hay diálogo».
- **PR de documentos**: con T0 hecho y **antes** de abrir los worktrees de la ola 1, un PR que solo
  añade `.sdd/changes/claude-plugin-and-mods/` (spec, investigación, revisiones, plan, `evidence/`).
  Así los worktrees, que nacen de `main`, ven el brief y el plan.

**Resultado de T0 (2026-10-21, `evidence/T0.md`)**, obligatorio para las olas siguientes:
- Vía **B** para B-1 (`<python de uv tool> -I -m local_delegate.hook <nombre>`); la A (`onFailure`)
  no convierte el código 2. `MIN_CLAUDE_PLUGIN_VERSION = 2.1.292`.
- `claude plugin` respeta `CLAUDE_CONFIG_DIR` en 2.1.292.
- Mod con `build_mod.py` (decisión 7) y latido en ruta derivada (decisión 9).
- Diálogo: `isInteractive` de `session.start` en el mod; `CLAUDE_CODE_ENTRYPOINT` en los hooks
  (`sdk-cli` en `-p`); subagente por `agent_id`, sin medir (se mide en la ola 3b).
- Un `default` de `userConfig` no rellena `${user_config.*}`: `install` pasa siempre
  `--config ld_bin=…`.
- `plugin validate --strict` exige `author` en `plugin.json` y `description` en `marketplace.json`.

### Ola 1 — F1, cuatro lotes en paralelo

Variables de entorno nuevas, en lista cerrada (las declara en `config.ENVIRONMENT_VARIABLES` el
lote «Subcomando de hooks»; los demás las usan sin editar `config.py`): `CLAUDE_CONFIG_DIR`,
`CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, `CLAUDE_PLUGIN_OPTION_READ_MOD_ENABLED` y
`WSL_DISTRO_NAME`. `LD_HOOK_READ_ENABLED`, `LD_HOOK_READ_BLOCK` y `LOCAL_DELEGATE_WEB_TOKEN` ya
existen.

**Contrato de `read_switch`**, fijado aquí porque lo usan dos lotes de esta ola:

- Fichero `LOG_DIR/read-hook.json` = `{"active": true|false, "since": "<ISO 8601>"}`.
- API de `read_switch.py`: `path()`, `active()` y `write(active)`.

Delivery-core **no importa el módulo** (lo posee otro lote de la misma ola): escribe y comprueba
**el fichero** con esa forma exacta. F1-hook-entry tiene un test que lee un fichero con esa forma
(`test_reads_contract_file_shape`). Es la única dependencia entre lotes de la ola 1.

#### Plugin empaquetado y metadatos de versión (F1-package)

- **Posee**: `src/local_delegate/resources/claude-plugin/.claude-plugin/marketplace.json`,
  `<plugin>/.claude-plugin/plugin.json`, `<plugin>/hooks/hooks.json`,
  `.claude-plugin/marketplace.json`, `scripts/bump_version.py`, `tests/test_bump_version.py`,
  `tests/test_release_metadata.py`, `tests/test_plugin_package.py`, `.github/workflows/ci.yml`,
  `scripts/ci_gate.py`, `tests/test_ci_gate.py`, `pyproject.toml`.
- **REQ**: 001, 002 y la mitad declarativa de 003 (la vía de B-1 en las cinco entradas).
- **Tests primero**:
  - `test_plugin_package.py`: `::test_plugin_version_matches_package`,
    `::test_marketplace_points_at_plugin_folder`, `::test_no_bin_at_plugin_root`,
    `::test_hooks_json_matches_settings_delivery_0_39` (eventos y filtros comparados con
    `_HOOK_EVENTS`, `_READ_HOOK`, `_SHELL_HOOK` y `_MCP_READ_HOOK` de `install.py`) y
    `::test_every_hook_entry_is_fail_open` (según la vía de T0: `onFailure` en las cinco, o el
    intérprete con `-I -m`).
  - `test_bump_version.py::test_bump_writes_plugin_and_marketplace_versions`.
  - `test_release_metadata.py::test_plugin_json_version_matches_pyproject`.
  - `test_ci_gate.py`: el job `plugin` está en `EXPECTED_JOBS` (obligatorio, no opcional).
- **CI**: job `plugin` en los tres SO, con estos pasos:
  - `claude plugin validate --strict --json` del marketplace y del plugin.
  - Construir la rueda y comprobar que contiene `.claude-plugin/plugin.json`. Va aquí y no en la
    suite, porque es un comando pesado.
  - Instalar en un `CLAUDE_CONFIG_DIR` vacío y comprobar que `~/.claude/plugins` real no cambia.
  - `claude -p … --output-format stream-json --verbose`: el evento `init` lista el plugin sin
    errores. **Control negativo**: el mismo paso con un `hooks.json` roto debe fallar.
- **Vuelta atrás**: revert del PR. Todavía nadie usa la carpeta.

#### Subcomando de hooks, interruptor y variables (F1-hook-entry)

- **Posee**: `src/local_delegate/__init__.py`, `src/local_delegate/entrypoint.py`,
  `src/local_delegate/hook_entry.py`, `src/local_delegate/hook.py` (solo con la vía B),
  `src/local_delegate/read_switch.py`, `src/local_delegate/config.py`,
  `src/local_delegate/resources/hooks/hook_common.py`,
  `src/local_delegate/resources/hooks/suggest_delegate_read.py`, `tests/test_hook_entry.py`,
  `tests/test_read_switch.py`, `tests/test_hook_common.py`, `tests/test_environment_isolation.py`,
  `scripts/measure_hook_latency.py`.
- **REQ**: 003 y 004.
- **Diseño**:
  - **Despacho**: `hook <nombre>` lee el JSON del hook y corre en proceso la lógica de los scripts de
    `resources/hooks/`, pasando **la ruta del script empaquetado** para que la huella de telemetría
    (`version_de`) sea la misma que en la entrega por settings.
  - **Fallos**: un nombre desconocido sale con 0 y sin texto. Cualquier excepción sale con 0 y deja
    una línea en el log de fallos de hooks.
  - **Codificación**: el envoltorio fuerza UTF-8 en stdout con `reconfigure`. Con `-I`, Python
    ignora `PYTHONUTF8` y `PYTHONIOENCODING`, y en tubería sale `cp1252`: un carácter fuera de esa
    tabla perdería el aviso.
  - **Las dos capas del interruptor**, separadas:
    - *Activo* (registrar y avisar) = fichero `LOG_DIR/read-hook.json`, **o** `LD_HOOK_READ_ENABLED`,
      **o** `--enabled` en la entrega por settings. El fichero sustituye a `--enabled` en la entrega
      por plugin.
    - *Bloquea* = sin cambios: `local-delegate-block-off` > `LD_HOOK_READ_BLOCK` (por defecto
      apagado). Los valores de `block_state` que van a `blocks.jsonl` (`on`/`off_file`/`off_variable`)
      no cambian.
  - **Coste**: con la capa *activo* apagada, el hook de lectura sale sin importar nada más que
    `read_switch`. En la entrega por plugin las entradas van siempre declaradas, así que esto
    importa.
- **Tests primero**:
  - `test_hook_entry.py`:
    - `::test_unknown_hook_exits_zero_silently`
    - `::test_hook_crash_lets_the_call_through`
    - `::test_hook_path_does_not_import_server` (en subproceso: ni `local_delegate.server` ni `mcp`
      en `sys.modules`)
    - `::test_inactive_read_hook_imports_only_switch`
    - `::test_each_hook_name_matches_script_behaviour`: misma salida que el script de la 0.39 para
      el mismo stdin. Cada caso está elegido para producir una salida propia **no vacía**, y una
      guarda falla si alguna sale vacía.
    - `::test_blocks_jsonl_unchanged_format`
    - `::test_plugin_and_settings_fingerprints_match`
    - `::test_hook_output_is_utf8`
    - Con la vía B: `::test_wrapper_exits_zero_on_sys_exit_2` y
      `::test_wrapper_exits_zero_on_exception`.
  - `test_read_switch.py`:
    - `::test_reads_contract_file_shape` (`{"active": …, "since": …}`)
    - `::test_active_layer_state_file_or_enabled_env`
    - `::test_block_layer_precedence_unchanged`
    - `::test_block_state_values_unchanged`
  - `test_environment_isolation.py`: las variables nuevas están en el inventario.
- **Verificación**: `measure_hook_latency.py` mide 20 invocaciones de cada hook con el `.exe` del
  `.venv` del worktree, no con `uv run` ni con el `uv tool`. El p95 ≤ 300 ms queda en `evidence/`.
  Si no llega, se recortan imports; el umbral no se relaja sin el usuario.
- **Vuelta atrás**: revert. Los scripts de settings se comportan igual si el fichero de estado no
  existe.

#### Estado de instalación, vía y orquestación de la entrega (F1-delivery-core)

- **Posee**: `src/local_delegate/install_state.py`, `src/local_delegate/claude_plugin.py`,
  `src/local_delegate/plugin_migration.py`, `<i18n>/plugin.json`, `tests/test_install_state.py`,
  `tests/test_claude_plugin.py`, `tests/test_plugin_migration.py`, `tests/conftest.py`.
- **REQ**: 005 (detección y comandos), 006, 007, 008 (el núcleo de a y b).
- **Diseño**:
  - **`install_state`** guarda `install-state.json` en el directorio que da `install.data_dir_for`,
    con la **misma regla que `language.json`**: con HOME simulado no se escribe salvo que haya
    `LOCAL_DELEGATE_LOG_DIR`. Si el fichero no existe, devuelve «no sé».
  - **`claude_plugin`** define `MIN_CLAUDE_PLUGIN_VERSION` (el valor sale de T0), decide la vía y
    construye los argv de `claude plugin …`. El ejecutor es inyectable. Con HOME simulado, pasa
    `CLAUDE_CONFIG_DIR=<home>/.claude` al hijo.
  - **De dónde sale `ld_bin`**:
    - Solo de una instalación de `uv tool`, detectada con `update.install_kind()`. Según la vía de
      T0, es el ejecutable del entorno de `uv tool` (o su enlace en `~/.local/bin`) o su intérprete.
    - Con `uvx` (caché de uv), con instalación editable o con el `.venv` de un repo o worktree, la
      vía plugin **se rechaza**: va a settings con aviso. Una ruta efímera haría que todos los hooks
      dejaran de actuar en silencio.
  - **`plugin_migration.apply_plugin_delivery(...)`** es **la única orquestación**:
    `install` y `update` solo la llaman. Pasos, en este orden:
    1. Copia de `settings.json` **antes de cualquier `claude plugin …`**
       (`settings.json.local-delegate-plugin.bak`; solo la primera vez).
    2. Lee `install.read_hook_registered()` y escribe `read-hook.json` con ese valor, con la forma
       del contrato y **sin importar `read_switch`**. Si el fichero ya existe, la migración nunca lo
       pone a `false`; apagarlo es cosa de `install --disable-read-hook` o de `uninstall`.
    3. Marketplace e instalación con `--config ld_bin=… --config language=…`.
    4. `list --json`: el plugin está habilitado y con la versión del paquete.
    5. **Solo entonces** retira nuestras entradas de settings con `install._is_ours` y
       `strip_hook_settings` (importadas, no copiadas) y borra `~/.claude/hooks/local-delegate/`.
    6. Escribe el estado.

    La misma función ofrece `revert_to_settings(...)` para REQ-008 b. La CLI reescribe el formato
    de `settings.json`; por eso, después de instalar, los tests comparan JSON y no bytes.
  - **Guarda en `conftest.py`**: borra `CLAUDE_CONFIG_DIR` y `CLAUDE_PLUGIN_*` del entorno de los
    tests, y hace fallar cualquier ejecución del `claude` real que no venga inyectada.
- **Tests primero**:
  - `test_claude_plugin.py`: `::test_min_version_gate`,
    `::test_wsl_and_simulated_home_fall_back_to_settings`,
    `::test_simulated_home_passes_claude_config_dir`, `::test_dry_run_prints_plugin_commands`,
    `::test_install_argv_is_non_interactive`, `::test_real_claude_never_runs_in_tests`,
    `::test_ld_bin_is_uv_tool_env`, `::test_ld_bin_rejected_from_uvx_cache` (y desde una
    instalación editable o un `.venv`: va a settings con aviso).
  - `test_install_state.py`: `::test_roundtrip`, `::test_missing_state_means_unknown_not_empty`,
    `::test_state_follows_language_dir_rule`.
  - `test_plugin_migration.py`:
    - `::test_backup_is_pre_install_bytes`
    - `::test_migration_carries_read_switch_on` y `::test_migration_carries_read_switch_off`, en
      HOME simulado con el bloqueo sembrado encendido y apagado
    - `::test_existing_switch_state_never_turned_off`
    - `::test_migration_removes_every_settings_hook_we_wrote`
    - `::test_migration_keeps_foreign_hooks`
    - `::test_migration_is_idempotent`
    - `::test_plugin_failure_leaves_settings_untouched`
    - `::test_mcp_skill_and_memory_untouched`
    - `::test_revert_to_settings_in_one_step`
- **Mutantes (control positivo)**. Cada uno se comprueba que cambia el camino que corre; se anota
  qué assert dispara y se revierte:
  1. Quitar `record_call` de lo que se retira → falla `…removes_every…` en `ours_left == []`.
  2. Retirar una entrada ajena → falla `…keeps_foreign_hooks` en el assert de esa entrada.
  3. Copia hecha después de instalar → falla `…pre_install_bytes` en la igualdad de bytes.
  4. No escribir el estado del interruptor → falla `…carries_read_switch_on` en el assert sobre el
     **contenido del fichero** (`json.loads(...)["active"] is True`).
  5. Retirar antes de comprobar `list --json` → falla `…plugin_failure_leaves_settings_untouched`
     en la igualdad del fichero.
- **Vuelta atrás**: revert. Los módulos todavía no tienen llamadores.

#### Puente del chat de Claude Desktop, solo Windows (F1-desktop-bridge)

- **Posee**: `src/local_delegate/desktop_bridge.py`, `src/local_delegate/token_source.py`,
  `src/local_delegate/desktop_config.py`, `<i18n>/bridge.json`, `tests/test_desktop_bridge.py`,
  `tests/test_token_source.py`, `tests/test_desktop_config.py`.
- **REQ**: 012, el núcleo. El cableado va en las olas 2a y 2b.
- **Diseño**:
  - **Puente**: MCP stdio que reenvía al `/mcp` del daemon (HTTP *streamable*, con
    `Mcp-Session-Id` y SSE). Lee el token de `HKCU\Environment` con `winreg` y soporta dos
    instancias a la vez.
  - **`desktop_config`**: toca solo la clave `local-delegate`. Hace una copia previa única y rotada
    en la misma carpeta. En Windows la copia hereda la ACL de `%APPDATA%\Claude`; no hay ACL desde
    la librería estándar y no se añaden dependencias. Detecta `${…}` y el token literal sin
    imprimirlo.
  - **Fuera de Windows**: no se ofrece.
- **Tests primero**:
  - `test_desktop_bridge.py`:
    - `::test_bridge_against_real_daemon_app`: la app de `daemon.py` en proceso, con token, sesión
      y SSE.
    - `::test_two_instances_in_parallel`
    - `::test_never_logs_token`
    - `::test_wrong_token_surfaces_401_as_mcp_error`
    - `::test_daemon_down_returns_mcp_error`
  - `test_token_source.py::test_reads_registry_user_env_on_windows`, con registro simulado.
  - `test_desktop_config.py`:
    - `::test_writes_only_our_key`
    - `::test_backup_once_rotated_in_config_folder`
    - `::test_detects_literal_token_without_printing`
    - `::test_detects_unexpanded_var`
    - `::test_foreign_existing_key_needs_explicit_replace`
- **Vuelta atrás**: revert. Todavía nada lo llama.

### Ola 2a — F1, dos lotes en paralelo

Ids de checks nuevos: `claude.delivery`, `claude.version`, `plugin.installed` (instalado,
habilitado, con la versión del paquete y el `language` vigente), `plugin.ld_bin` y
`hooks.duplicates`. Los avisos del chat de Desktop amplían `service.desktop_auth`.
**Contador de `doctor`: de 27 a 32.**

#### Instalar y desinstalar con plugin (F1-install)

- **Posee**: `src/local_delegate/install.py`, `src/local_delegate/cli.py`,
  `src/local_delegate/agents.py`, `<i18n>/cli.json`, `<i18n>/argparse.json`,
  `<i18n>/plugin_install.json`, `tests/test_install_plugin_delivery.py`,
  `tests/test_uninstall_plugin.py`, `tests/test_agents_uninstall.py`,
  `tests/test_install_desktop.py`, `scripts/check_plugin_install.py`, `.github/workflows/ci.yml`,
  `docs/wiki/Claude-plugin.md`, `docs/wiki/Home.md`.
- **REQ**: 005, 006, 008 (b, y la parte de documentación de c), 011, 012 (`install --desktop` y el
  subcomando `desktop-bridge`).
- **Diseño**:
  - **Opciones nuevas**: `--claude-delivery plugin|settings`, cuyo valor por defecto decide
    `claude_plugin`, y `--desktop`. Las dos van en `install.Options`.
  - **`install`** llama a `apply_plugin_delivery`; `--claude-delivery settings` llama a
    `revert_to_settings`.
  - **Capa *activo* del interruptor**:
    - `--enable-read-hook` escribe `{"active": true}`.
    - La opción nueva **`--disable-read-hook`** escribe `{"active": false}`. Es, con `uninstall`, el
      único camino que la apaga.
    - El apagado en caliente sigue siendo `local-delegate-block-off` y solo afecta a la capa
      *bloquea*.
  - **`--desktop`**:
    - En Windows escribe la entrada del puente.
    - En macOS y Linux se niega con un mensaje claro.
    - Si la clave ya existía y no la puso `install`, solo la reemplaza con el flag, avisando.
  - **`uninstall`** lee el estado:
    - Quita plugin, marketplace, entrada de Desktop y lo de `--agents` solo si figuran en el estado.
    - Si `install` había reemplazado una entrada ajena de Desktop, **no la repone**, porque podía
      llevar el token escrito. Quita la nuestra y dice dónde está la copia con la entrada anterior.
    - Borra el fichero del interruptor y el estado.
- **Tests primero**:
  - `test_install_plugin_delivery.py`:
    - `::test_default_is_plugin_when_cli_new_enough`
    - `::test_falls_back_to_settings_with_warning`
    - `::test_install_uses_apply_plugin_delivery` (`install` no reimplementa pasos)
    - `::test_disable_read_hook_turns_active_layer_off`
    - `::test_dry_run_runs_nothing`
    - `::test_enable_read_hook_writes_switch_state`
  - `test_uninstall_plugin.py`: `::test_removes_only_what_state_lists`,
    `::test_preexisting_piece_not_in_state_is_kept`,
    `::test_replaced_foreign_desktop_entry_not_restored_and_backup_reported`.
  - `test_agents_uninstall.py::test_uninstall_undoes_agents_edit`.
  - `test_install_desktop.py`: `::test_desktop_flag_writes_bridge_entry`,
    `::test_replaces_foreign_entry_only_with_flag_and_warns`,
    `::test_desktop_flag_on_macos_refuses_cleanly`.
- **CI**: `check_plugin_install.py` va en el job `plugin`, en los tres SO, con HOME simulado y
  `CLAUDE_CONFIG_DIR`. Recorre esta secuencia:
  1. Siembra una 0.39 por settings, con el bloqueo **encendido**.
  2. `install`: sin duplicados, interruptor encendido, scripts borrados.
  3. Segunda pasada idéntica (idempotencia).
  4. `--claude-delivery settings` vuelve atrás.
  5. `uninstall` deja la config como antes, salvo lo ajeno, que queda intacto.
  6. **La misma orden que declara `hooks.json`** para `prompt`, con la vía de T0
     (`<ld_bin> hook prompt` en la A, `<ld_bin> -I -m local_delegate.hook prompt` en la B), con
     `< muestra.json`: sale con 0 y da la salida esperada. El script lee la orden del propio
     `hooks.json` instalado, sin escribirla a mano.
- **Vuelta atrás**: revert del PR. En una instalación ya migrada, `install --claude-delivery settings`,
  y `update` la respeta: con la marca `claude_delivery_explicit` de `install-state.json` repara los
  hooks de settings en vez de volver a migrar al plugin (F1-settings-choice, #404).

#### `doctor` con plugin (F1-doctor)

- **Posee**: `src/local_delegate/checks.py`, `src/local_delegate/checks_plugin.py`,
  `src/local_delegate/doctor.py`, `<i18n>/doctor.json`, `tests/test_checks.py`, `tests/test_doctor.py`,
  `tests/test_doctor_english.py`, `tests/test_doctor_claude_settings.py`, `tests/test_wiki.py`,
  `tests/test_checks_plugin.py`, `docs/wiki/Integration-install.md`, `docs/wiki/Troubleshooting.md`.
- **REQ**: 009, 008 c (aviso de hooks en settings y plugin a la vez) y 012 (avisos de Desktop).
- **Diseño**:
  - **Sondas nuevas**: leen el estado y `claude plugin list --json`.
  - **Hooks según la vía**: `scaffold.hook_settings`, `hook_files` y `hook_orphans` dependen de la
    vía. Con plugin, que no haya hooks en settings es lo correcto y los scripts sueltos son huérfanos
    (warn). **Este cambio va antes que `update`**, porque las reparaciones existentes repondrían los
    hooks en settings.
  - **WSL**: dentro de WSL no se espera plugin.
  - **Wiki**: dice las versiones mínimas de la pestaña Code (2.1.286) y de VS Code (2.1.299). Lo de
    VS Code queda como límite documentado, sin verificar en vivo.
  - **El número 32**: se actualiza en todos los sitios donde vive:
    - el docstring de `checks.py`;
    - el comentario de `doctor.py:71`;
    - `_NUMBER_WORDS` de `test_checks.py`, ampliado ya hasta 34;
    - los asserts de `test_doctor.py` y `test_doctor_english.py`;
    - `_CHECK_COUNT_WORDS` de `test_wiki.py` y la tabla de la wiki.
- **Tests primero**:
  - `test_checks_plugin.py`:
    - `::test_doctor_flags_hooks_in_settings_and_plugin`
    - `::test_plugin_version_mismatch_warns`
    - `::test_plugin_language_stale_warns`
    - `::test_ld_bin_missing_fails`
    - `::test_ld_bin_not_the_installed_uv_tool_env_warns`: el `ld_bin` debe ser el mismo entorno
      que la versión instalada.
    - `::test_claude_below_min_warns`
    - `::test_wsl_expects_no_plugin`
    - `::test_settings_hooks_absent_is_ok_under_plugin`
    - `::test_desktop_literal_token_not_printed`
  - `test_checks.py::test_check_ids_exact` (32 ids).
  - `test_wiki.py::test_the_doctor_table_lists_every_check`.
- **Mutante**: el detector ignora las entradas del plugin → falla
  `…flags_hooks_in_settings_and_plugin` en `status == "warn"` del id `hooks.duplicates`.
- **Vuelta atrás**: revert.

### Ola 2b — F1, un lote

#### `update` con plugin (F1-update)

- **Posee**: `src/local_delegate/update.py`, `<i18n>/plugin_update.json`,
  `tests/test_update_plugin.py`.
- **REQ**: 008 a, 010 y 012 (reescribir la ruta del puente si cambia el ejecutable).
- **Diseño**:
  - Tras subir el paquete, con plugin: `claude plugin marketplace update` y después
    `claude plugin update local-delegate@local-delegate`.
  - Reparaciones por id: si falla `plugin.installed`, reinstala o vuelve a aplicar
    `--config language=…`; si falla `hooks.duplicates`, **retira** los de settings
    (`plugin_migration`). **Nunca** repone hooks en settings con el plugin puesto.
  - Una instalación por settings que cumple REQ-005 → `apply_plugin_delivery`, que conserva el
    interruptor, y aviso de reiniciar las sesiones abiertas.
  - `plan_pin` y `service.daemon_auth` no cambian.
- **Tests primero**:
  - `test_update_plugin.py`:
    - `::test_marketplace_update_before_plugin_update`
    - `::test_repairs_missing_plugin`
    - `::test_duplicates_are_removed_not_restored`
    - `::test_update_never_restores_settings_hooks_under_plugin`
    - `::test_settings_install_migrates_carries_switch_and_warns_restart`
    - `::test_install_and_update_share_one_orchestration` (va aquí: `update` cambia en esta ola)
    - `::test_language_change_reapplied`
    - `::test_desktop_bridge_path_rewritten`
    - `::test_plan_pin_unchanged`
- **Vuelta atrás**: revert.

### Ola 3 — F2, tres lotes en paralelo

**Interfaz de `<plugin>/mod/common.js`**, fijada aquí:

| Función | Qué hace |
|---|---|
| `token()` | Solo lee `LOCAL_DELEGATE_WEB_TOKEN` y nunca lo registra. |
| `daemonFetch(path, init)` | Solo habla con `http://127.0.0.1:<puerto>`; devuelve `null` si falla. |
| `t(key, vars)` | Textos de `mod/i18n` según `options.language`. |
| `runLd(args, stdin)` | `$.process.run` sobre `options.ld_bin`; devuelve `null` si no está disponible, está vetado o falla. |
| `dataPath(name)` | Ruta dentro de `${CLAUDE_PLUGIN_DATA}`. |
| `hasDialog(e)` | Usa la señal fijada en T0. |
| `heartbeat()` | Escribe el latido. |

Cada pieza exporta `register(on, options, common)`.

#### Esqueleto del mod y tools fijas (F2-mod-core)

- **Posee**: `<plugin>/register.js`, `<plugin>/mod/common.js`, `<plugin>/mod/pinned-tools.js`,
  `<plugin>/mod/pinned-tools.test.ts`, `<plugin>/mod/common.test.ts`,
  `<plugin>/.claude-plugin/plugin.json`, `<plugin>/hooks/hooks.json`, `scripts/build_mod.py`
  (solo si T0 lo exige), `.github/workflows/ci.yml`, `src/local_delegate/checks.py`,
  `src/local_delegate/checks_plugin.py`, `src/local_delegate/doctor.py`, `<i18n>/doctor.json`,
  `tests/test_checks.py`, `tests/test_checks_plugin.py`, `tests/test_doctor.py`,
  `tests/test_doctor_english.py`, `tests/test_wiki.py`, `docs/wiki/Integration-install.md`,
  `tests/test_mod_static.py`.
- **REQ**: 013, 016 y 009 (el check `mod.loaded`; contador de 32 a 33 en todos sus sitios).
- **Diseño**:
  - `tool.describe` saca de ToolSearch la lista `pinned_tools`: por defecto las 4 de la spec, y una
    lista vacía lo apaga. Solo acepta `mcp__local-delegate__*`.
  - `scripts/build_mod.py` genera `register.js` con cada pieza en su propio `try` (decisión 7; el
    `import()` dinámico lo rechaza el motor, T0).
  - `ci.yml`: añade el paso `claude plugin test <plugin>` al job `plugin`.
- **Tests primero**:
  - `test_mod_static.py`:
    - `::test_mod_reads_only_the_token_variable`
    - `::test_mod_talks_only_to_loopback`
    - `::test_mod_never_logs_token`
    - `::test_every_piece_has_a_userconfig_switch`
    - `::test_register_loads_pieces_dynamically_inside_try`
  - `pinned-tools.test.ts`: lista por defecto, vacía y con nombre ajeno.
  - `common.test.ts`: `runLd_null_without_process_run` y `daemonFetch_rejects_non_loopback`.
  - `test_checks_plugin.py`: `::test_mod_loaded_from_heartbeat`, `::test_no_heartbeat_warns`.
- **Vuelta atrás**: piezas a `off` por `userConfig` (no `plugin disable`, que también apaga los
  hooks); revert.

#### Comandos sin turno del modelo (F2-commands)

- **Posee**: `<plugin>/mod/commands.js`, `<plugin>/mod/commands.test.ts`,
  `<plugin>/mod/i18n/es.json`, `<plugin>/mod/i18n/en.json`, `tests/test_mod_i18n_parity.py`.
- **REQ**: 014.
- **Diseño**:
  - `/local-summarize <ruta>` llama a `$.mcp.call(... 'local_summarize', {path})`.
  - `/local-commit`:
    - Corre `git diff --cached` con `runLd` o `process.run` y lo vuelca a un temporal en
      `dataPath`.
    - Llama a `local_commit_msg(path)` y **solo muestra** el mensaje.
    - **Borra el temporal en un `finally`**, porque puede llevar secretos.
  - `/local-lint <fichero|comando>`:
    - Con comando: lo parte según las reglas de Windows o POSIX, con tope de 30 s, vuelca la salida
      a fichero y llama a `local_lint_summary`. El temporal también se borra.
    - Sin `process.run`: acepta solo un fichero y lo dice.
  - Si el daemon o el MCP están caídos, error claro.
- **Tests primero**:
  - `commands.test.ts`:
    - `splits_windows_args` y `splits_posix_args`
    - `lint_without_process_run_accepts_only_file`
    - `commit_only_shows_message`
    - `commit_temp_file_removed`
    - `daemon_down_clear_error`
    - `texts_follow_language`
  - `test_mod_i18n_parity.py::test_mod_catalogs_have_same_keys`.
- **Vuelta atrás**: `commands_enabled=false`; revert.

#### Delegaciones del mod separables y script de medición (F2-attribution)

- **Posee**: `src/local_delegate/web/metrics.py`, `src/local_delegate/attribution.py`,
  `<i18n>/panel.json`, `scripts/measure_plugin_adoption.py`, `tests/test_measure_plugin_adoption.py`,
  `tests/test_dashboard_states.py`.
- **REQ**: 015 y 024 (el script y el criterio).
- **Diseño**:
  - **Panel**: las filas con `tool_use_id` `toolu_plugin_…` se cuentan aparte, con textos en
    `panel.json`.
  - **Script de medición** (desde `evidence/baseline_sessions.py`): % de sesiones interactivas de
    Claude Code con ≥ 1 delegación decidida por el modelo. Excluye `toolu_plugin_` y las ventanas de
    prueba.
  - **Base**: solo desde el 2026-10-08.
  - **Criterio fijado antes**: ≥ +10 puntos con ≥ 30 sesiones, a los 14 días.
- **Tests primero**:
  - `test_measure_plugin_adoption.py`:
    - `::test_plugin_calls_excluded`
    - `::test_test_windows_excluded`
    - `::test_base_starts_2026_10_08`
    - `::test_counts_sessions_not_calls`
    - `::test_subagent_and_print_sessions_excluded`
  - `test_dashboard_states.py::test_mod_calls_shown_apart`.
- **Vuelta atrás**: revert.

### Ola 3b — Medición en vivo de F2 y release 0.40.0

#### Medición en vivo (F2-live)

Un agente; usa `claude -p` y Desktop, que son recursos únicos. Todo en ventana de prueba, con
`claude -p` desde PowerShell y `--max-turns 1`. Evidencia en `evidence/F2-live.md`.

- **REQ-015**: una llamada del mod y una del modelo en la misma sesión se ven separadas.
- **REQ-016**:
  - Todas las piezas a `off` por `userConfig` → `record_call` y el MCP siguen.
  - Un `register.js` que lanza al cargar → lo mismo.
- **REQ-003**:
  - Latencia de los hooks.
  - Con `ld_bin` apuntando a un ejecutable inexistente y a la 0.39, el prompt pasa.
- **Sobrecarga de los hooks siempre declarados**: mediana y p95 de una llamada `Bash` con el plugin
  frente a sin él. Tope fijado antes de medir: **+150 ms de mediana y +300 ms de p95**. Si se
  supera, se estrechan los filtros de las entradas de lectura antes de la release.
- **Chat de Desktop** (va antes que `process.run`, para aprovechar el mismo arranque de Desktop):
  - La sesión principal ejecuta `install --desktop` en la PC real. Reemplaza la entrada
    `mcp-remote` puesta a mano, con aviso.
  - El agente lanza `local-delegate desktop-bridge` como lo haría Desktop: stdio y solo la lista
    fija de variables de r5. Un cliente MCP de script hace `initialize`, `tools/list` y una
    llamada a `local_status` contra el daemon real.
  - Cuando el usuario abra Desktop para el paso siguiente, Desktop arrancará el puente él mismo.
    Se comprueban los arranques del puente en `%LOCALAPPDATA%\Claude\Logs\`, las filas en el log del
    daemon y que `doctor` no avisa. No se le pide al usuario ninguna llamada desde el chat.
- **`process.run`**: en la pestaña Code de Desktop, leído del latido. **El usuario abre una sesión
  en la pestaña Code**; es lo único que se le pide en F2. VS Code no se mide en vivo: la wiki deja
  su versión mínima (2.1.299) como límite documentado, sin verificar.

#### Release 0.40.0 (release-040)

- **Antes de publicar**:
  - `grep -rn "0\.40"` de compromisos fechados.
  - `bump_version.py 0.40.0 --dry-run` y simulación del CHANGELOG. Se repiten con la salida
    redirigida (cp1252).
  - **`bump_version.py 0.40.0 --boundaries`**, escrito explícitamente.
  - `CHANGELOG.md`, que dice «bajar a la 0.39 exige `uninstall` antes» y el coste de no hacerlo con
    la vía B. Cada hook carga el paquete de la 0.39 (alrededor de 1 s, porque carga el servidor) y
    deja un error no bloqueante en cada llamada. No bloquea, pero frena. La wiki lo repite.
  - `README.md` y `docs/wiki/`.
  - Socket del paquete frente a la 0.39.0.
- **Después de publicar**:
  - La sesión principal ejecuta `uv tool install --force "local-delegate-mcp[llamaswap]==0.40.0"`
    y `local-delegate update`, que migra **conservando el interruptor encendido**.
  - Comprueba en `blocks.jsonl` que la serie de P-4 sigue.
  - Reinicia el daemon y el usuario hace `/mcp`.
  - Arranca la ventana de 14 días de REQ-024. La Mac la actualiza el usuario.

### Ola 3c — Arreglo previo a la ola 4: llamadas abandonadas (un lote)

Entra tras la reproducción del 2026-10-22 (12:41–12:53Z, ventanas de prueba `w-20261022T124408Z` y
`w-20261022T125138Z`). La hipótesis de partida, «cerrar Desktop deja el daemon sin escuchar en
9393», **no se reprodujo**: 186 sondas cada 3 s respondieron durante cerrar la ventana (va a la
bandeja), `taskkill` normal y Ctrl+Q (Desktop los ignora), matar todo el árbol de Desktop, matar el
puente con una llamada en curso y cerrarle stdin con una llamada en curso. Sí salió un defecto que
para el cliente es un cuelgue:

- Una llamada cuyo cliente desaparece **sigue ejecutándose hasta el final** (un `local_summarize`
  de 256 KB tardó 302 s) y retiene el turno del backend: un `local_classify` de otro cliente esperó
  192 s con `local_wait: "turn"` en `inflight.json`.
- `notifications/cancelled` **tampoco la para** (el trozo siguió avanzando tras cancelarla), así que
  afecta también al Esc de Claude Code, no solo al puente.
- El puente, al cerrarse stdin, **espera** a sus peticiones en curso antes de salir
  (`desktop_bridge.py`, `Bridge.run`: el grupo de tareas no se cancela): queda un proceso huérfano
  hasta que el daemon acaba.

#### Cancelar las llamadas abandonadas (abandoned-calls)

- **Posee**: `src/local_delegate/desktop_bridge.py`, la parte del daemon/servidor que ejecuta las
  tools y espera el turno del backend (localizarla; probablemente `server.py` y el cliente del
  backend), `tests/test_desktop_bridge.py` y un test nuevo de cancelación del servidor.
- **REQ**: 012 (el puente) y robustez del daemon; no cambia la letra de la spec.
- **Diseño**:
  - **Daemon**: `notifications/cancelled`, el `DELETE` de la sesión y la desconexión del flujo HTTP
    cancelan la llamada: se deja de esperar el turno, no se mandan más trozos al backend y se suelta
    el hueco de concurrencia. El registro de uso apunta la llamada como cancelada (`ok: false` y un
    motivo), no como éxito.
  - **Puente**: al cerrarse stdin manda `notifications/cancelled` por cada petición en curso,
    cancela su grupo de tareas, hace el `DELETE` y sale en ≤ 3 s.
  - Antes de tocar nada, medir dónde se pierde la cancelación (SDK de MCP, hilo del backend o
    espera del turno); la causa no está vista, solo el efecto.
- **Tests primero**:
  - `test_desktop_bridge.py::test_stdin_eof_cancels_inflight_and_exits_fast`
  - `::test_cancelled_notification_releases_backend_turn`, con un backend falso lento: una segunda
    llamada no espera a la cancelada.
  - `::test_session_delete_cancels_inflight`
  - `::test_client_disconnect_cancels_inflight`
- **Verificación en vivo**: repetir el guion de la reproducción (puente propio con un
  `local_summarize` del `CHANGELOG.md`, cortar a los 4 s) y comprobar que `inflight.json` se vacía
  en ≤ 5 s y que un `local_classify` posterior responde en < 5 s. Bajo ventana de prueba.
- **Vuelta atrás**: revert.
- **Sigue abierto**: el incidente del 2026-10-22 08:45 hora local (daemon vivo, sin escuchar, con
  el cerrojo tomado) queda sin causa. Si vuelve a pasar, antes de matar nada: `netstat -ano` del
  pid, volcado de pilas (`py-spy dump`) y los ficheros de estado.

### Ola 4 — F3, primera parte de F4 y retirada de nombres: tres lotes en paralelo

#### Cuota y ahorro en la barra de estado (F3-status)

- **Posee**: `<plugin>/mod/status.js`, `<plugin>/mod/status.test.ts`,
  `src/local_delegate/web/metrics.py`, `src/local_delegate/resources/hooks/record_call.py`,
  `tests/test_metrics_session_filter.py`.
- **REQ**: 017.
- **Diseño**:
  - `/api/stats` gana un parámetro `session`. Hoy solo acepta `from`, `to`, `include_tests` y
    `lang`. `record_call` añade el `session_id` del evento a su nota, porque hoy no lo guarda.
  - `session.measure` → `$.ui.status(...)` muestra el % de cuota de la sesión y el ahorro de **esa**
    sesión.
  - Si el daemon está caído o no hay token, la barra se oculta sin error.
- **Tests primero**:
  - `test_metrics_session_filter.py`: `::test_stats_filters_by_session`,
    `::test_record_call_stores_session_id`.
  - `status.test.ts`: `shows_quota_and_savings`, `hides_when_daemon_down`, `hides_without_token`,
    `off_by_userconfig`.
- **Vuelta atrás**: `status_enabled=false`; revert. El parámetro nuevo es opcional.

#### Medir por qué vías se lee (F4-measure-reads)

- **Posee**: `scripts/measure_read_paths.py`, `tests/test_measure_read_paths.py`,
  `tests/fixtures/read_corpus.jsonl`, `evidence/F4-read-paths.md`.
- **REQ**: 018, y fija el umbral de REQ-020.
- **Diseño**:
  - Recorre los transcripts recientes **excluyendo las ventanas de prueba**. Solo cuenta: ningún
    contenido pasa por el contexto.
  - Vías que mide:
    - `Read` entero y por franjas.
    - Cada forma de shell, incluidas las tuberías.
    - `Grep` con salida grande.
    - Las tools de lectura de otros MCP.

    Para cada lectura anota el tamaño del fichero.
  - **Salidas**:
    - Tabla por vía y volumen.
    - Las vías que cubre F4.
    - **El umbral de REQ-020**, escrito antes de implementar.
    - Un corpus anonimizado.
- **Tests primero**: `test_measure_read_paths.py`: `::test_counts_each_path_kind`,
  `::test_never_emits_file_contents`, `::test_corpus_is_anonymised`, `::test_test_windows_excluded`.
- **Vuelta atrás**: es solo medición.

#### Retirada de los siete nombres en desuso (retire-seven-names)

- **Posee**: `src/local_delegate/deprecations.py`, `tests/test_deprecations.py`, `tests/test_density.py`,
  `tests/test_detect_spanish_names.py`, `tests/test_hook_legacy_names.py`, `tests/test_quota.py`,
  `tests/test_retired_cli_names.py`, `tests/test_structured_summary.py`, `tests/test_transcripts.py`,
  `scripts/build_corpus.py`, `scripts/data/name_exceptions.json`, `docs/recipes/claude-code-hooks.md`,
  `docs/wiki/Configuration.md`, `docs/wiki/Integration-install.md`,
  `src/local_delegate/legacy_names.py`, `src/local_delegate/config.py`,
  `src/local_delegate/checks.py`, `tests/test_wiki.py` (incluye
  `test_the_deprecated_names_row_describes_the_0_38_behaviour`), `tests/test_retired_env_names.py`,
  `tests/test_environment_isolation.py` (incluye `test_hooks_never_name_a_retired_name`).
  - Si el `grep` del momento muestra otro fichero, el lote lo añade a su lista antes de empezar. Se
    comprueba con el script de disjunción; en esta ola nadie más toca esos ficheros.
- **Motivo**: la 0.41.0 no puede salir sin esto. Con el bump a 0.41.0, `_assert_horizon` y
  `overdue("0.41.0")` de `tests/test_deprecations.py` ponen el PR de release en rojo. Tres de los
  siete nombres son del interruptor de lectura (`LD_HOOK_READ_BLOQUEAR`, `LD_HOOK_READ_INTERRUPTOR`
  y `local-delegate-bloqueo-apagado`).
- **REQ**: ninguno de esta spec; es condición previa con nombre de la release 0.41.0 (backlog
  §1.15.5).
- **Tests primero**: `test_deprecations.py` con la versión simulada 0.41.0 en rojo antes del cambio.
  Después del cambio, el test de horizonte pasa **en verde** con 0.41.0.
- **Verificación**: además, que los avisos de esos nombres ya no salen y que el registro queda sin
  ellos.
- **Vuelta atrás**: revert.

### Ola 5 — F4, dos lotes en paralelo

**Contrato de `hook classify`**, fijado aquí:

- stdin: `{"tool_name", "tool_input", "cwd", "session_id"}`.
- stdout: `{"kind": "read"|"write"|"other", "path", "scope": "whole"|"range"|"partial"|"unclassifiable",
  "bytes", "range", "via", "read_switch": "on"|"off_file"|"off_variable"|"inactive"}`.
- `hook classify --list-tools` da los nombres de tool que pueden leer o escribir.
- `hook record-read` (stdin: la salida de `classify` más `decision` y `session_id`) escribe en
  `blocks.jsonl` la misma línea que habría escrito el hook. Así, cuando el mod actúa y el hook se
  aparta, la serie de P-4 no se corta. Lo implementa el clasificador y lo llama el mod.

#### Clasificador único de lectura (F4-classifier)

- **Posee**: `src/local_delegate/resources/hooks/read_classifier.py`,
  `src/local_delegate/resources/hooks/suggest_delegate_shell.py`,
  `src/local_delegate/resources/hooks/suggest_delegate_read.py`,
  `src/local_delegate/resources/hooks/hook_common.py`, `src/local_delegate/hook_entry.py`,
  `tests/test_read_classifier.py`, `tests/test_hook_shell.py`.
- **REQ**: 019 y la telemetría por vía de REQ-004 y REQ-021.
- **Diseño**:
  - Los scripts de hooks usan el clasificador y no llevan regex de lectura propias.
  - **Huella de telemetría**: para `suggest_delegate_read` y `suggest_delegate_shell`,
    `version_de`/`context_of` calculan una huella **combinada** del script más
    `read_classifier.py`. Así un cambio de reglas abre un tramo nuevo de P-4.
    **`HASHED_HOOKS` no se toca**: `tests/test_hook_boundaries.py` exige que sea exactamente la
    lista de scripts que estampan eventos, y el clasificador no estampa ninguno.
- **Tests primero**:
  - `test_read_classifier.py`:
    - `::test_corpus`, parametrizado sobre `read_corpus.jsonl`.
    - `::test_shell_writes_detected`
    - `::test_list_tools_covers_corpus_tools`
    - `::test_settings_hooks_use_the_classifier`
    - `::test_classify_reports_read_switch`
    - `::test_classifier_change_moves_fingerprint`
    - `::test_record_read_writes_same_line_as_hook`
  - `tests/test_hook_boundaries.py` sigue en verde sin tocarlo.
- **Mutantes**:
  1. Borrar la regla de `Get-Content` → falla `test_corpus[Get-Content …]` en `scope == "whole"`.
  2. `grep -c` tratado como lectura entera → falla en `scope == "unclassifiable"`.
- **Vuelta atrás**: revert.

#### Mod de lectura con elección (F4-read-mod)

- **Posee**: `<plugin>/mod/read.js`, `<plugin>/mod/read.test.ts`.
- **REQ**: 020, 021 y 022.
- **Diseño**:
  - **Cuándo actúa**: solo con `read_mod_enabled=true` y `read_switch == "on"` en la respuesta de
    `classify`.
  - **Filtro previo**: un filtro barato descarta por nombre de tool y primer token. Para las
    llamadas que pasan, `classify` por `runLd`. Si no está disponible o falla, deja pasar.
  - **Lectura acumulada**: lleva lo leído por fichero y por vía. Si las franjas suman ≥ el umbral,
    cuenta como lectura entera.
  - **Vías clasificables**:
    - Con diálogo (`hasDialog`): botones «resumir con el modelo local / leer entero».
    - Sin diálogo: deniega con la sugerencia.
  - **Vías no clasificables**: solo aviso y registro.
  - **Telemetría**: cada decisión se registra con `hook record-read` y se escribe el latido de la
    sesión con `read_mod_active`.
  - **Guarda de REQ-022**:
    - Tras un resumen, rechaza `Edit`, `Write`, `NotebookEdit` y las escrituras de shell sobre ese
      fichero hasta que haya una lectura real.
    - La lista se **persiste por `session_id`** en `dataPath` y se recarga al iniciar sesión, así
      que aguanta `--resume`.
- **Tests primero**: `read.test.ts`:
  - `accumulates_ranges_to_whole`
  - `buttons_when_dialog` y `denies_without_dialog`
  - `unclassifiable_only_warns`
  - `blocks_write_after_summary` y `allows_write_after_real_read`
  - `guard_survives_resume`
  - `passes_when_classifier_unavailable`
  - `respects_read_switch_off`
  - `off_by_default`
- **Vuelta atrás**: `read_mod_enabled=false`, que es el valor por defecto; revert.

### Ola 6 — F4, cierre

#### Coordinación de hooks y mod de lectura (F4-hooks-swap)

- **Posee**: `src/local_delegate/resources/hooks/suggest_delegate_read.py`,
  `src/local_delegate/resources/hooks/suggest_delegate_shell.py`, `src/local_delegate/checks.py`,
  `src/local_delegate/checks_plugin.py`, `src/local_delegate/doctor.py`, `<i18n>/doctor.json`,
  `tests/test_checks.py`, `tests/test_checks_plugin.py`, `tests/test_doctor.py`,
  `tests/test_doctor_english.py`, `tests/test_wiki.py`, `tests/test_hook_step_aside.py`,
  `src/local_delegate/resources/hooks/hook_common.py`, `docs/wiki/Integration-install.md`,
  `docs/wiki/Claude-plugin.md`.
- **REQ**: 023 (decisión 10).
- **Diseño**:
  - **El hook se aparta** solo con las cuatro condiciones de la decisión 10, las mismas con las que
    actúa el mod:
    - `CLAUDE_PLUGIN_OPTION_READ_MOD_ENABLED` es verdadero;
    - el latido de **su misma sesión** (`session_id` del payload) tiene `read_mod_active` y
      `process_run: ok`, con menos de 24 h;
    - la capa *bloquea* está en `on`;
    - la vía es clasificable.

    Al apartarse, registra en `blocks.jsonl` que lo hizo y por qué. El motivo se añade en
    `hook_common.record`, que este lote posee. Si falta cualquiera de las cuatro, actúa como en
    la 0.40.
  - **`hooks.json` no cambia.**
  - **`mod.read_overlap`**: el contador pasa de 33 a 34 en todos sus sitios. Avisa si el mod de
    lectura y un hook de lectura actúan sobre la misma vía a la vez, o si ninguno actúa estando el
    interruptor encendido.
- **Tests primero**:
  - `test_hook_step_aside.py`:
    - `::test_read_hook_steps_aside_when_mod_active`
    - `::test_read_hook_acts_when_mod_off_or_stale`
    - `::test_step_aside_logged_in_blocks_jsonl`
    - `::test_read_hook_does_not_step_aside_for_another_session`
    - `::test_no_gap_when_active_but_not_blocking`
  - `test_checks_plugin.py::test_read_mod_and_read_hook_overlap_warns`.
- **Mutantes**:
  1. Ignorar el `session_id` del latido → falla `…does_not_step_aside_for_another_session`.
  2. No comprobar la vigencia del latido → falla `…acts_when_mod_off_or_stale`.
  3. Apartarse sin mirar la capa *bloquea* → falla `…no_gap_when_active_but_not_blocking`.
- **Vuelta atrás**: revert. Los hooks actúan siempre, como en la 0.40.

#### Verificación en vivo de F4 (F4-live)

En `-p`, desde PowerShell, en ventana de prueba y con `--max-turns 1`:

- **REQ-022, control positivo**: sin mod, `Write` pasa.
- **REQ-022, control negativo**: con mod, tras una lectura resumida, `Write` se rechaza y el hash
  del fichero no cambia.

En sesión interactiva en la terminal:

- Aparecen los botones y el resumen llega como resultado.
- `Edit` se rechaza tras el resumen y se acepta tras un `Read` con `offset`/`limit`.
- **`--resume`**: la guarda sigue activa.
- La telemetría por vía queda en `blocks.jsonl`.
- **Sobrecarga** por llamada `Bash` con el mod de lectura: el tope de F2-live, medido de nuevo.

**Posee** (solo para el commit final): `<plugin>/.claude-plugin/plugin.json`. La ola 6 va en serie.

**Si pasa**, un commit pone `read_mod_enabled` a `true` por defecto. **Si no pasa**, F4 sale
apagada y el motivo queda en la wiki y en el backlog.

#### Release 0.41.0 (release-041)

- **Condiciones previas con nombre**: la retirada de los siete nombres en desuso está mezclada y
  F4-live está cerrada.
- **Procedimiento**: el mismo de la 0.40.0, incluido `bump_version.py 0.41.0 --boundaries`. La
  release corta un tramo de P-4, porque la huella ya incluye el clasificador.
- **Después de publicar**: se instala aquí.

### Lectura de la medición de adopción (REQ-024)

- **Cuándo y quién**: la sesión principal, a los 14 días de instalar la 0.40.0 aquí. La fecha
  exacta se escribe en `evidence/` el día de la instalación.
- **Cómo**: corre `measure_plugin_adoption.py` con el criterio fijado (≥ +10 puntos con ≥ 30
  sesiones). Si no llega a 30 sesiones, el resultado es «no concluyente», que no cuenta como éxito.
- **Si no sube**: un commit pone `pinned_tools` vacío por defecto y deja los comandos. Va con su
  línea de CHANGELOG para la siguiente release.

## PRs

- **Un PR por lote** (`feat/plugin-<lote>`). Los mezcla la sesión principal, con squash, cuando
  `gh pr checks` está verde y CodeQL a 0.
- **PR solo de documentos**: tras T0 y antes de la ola 1, el que añade
  `.sdd/changes/claude-plugin-and-mods/`.
- **Releases**: `chore: release v0.40.0` y `chore: release v0.41.0`.
- **Mediciones en vivo**: su evidencia va en el PR siguiente.

## Trazabilidad REQ → lote → prueba

| REQ | Lote | Prueba nombrada |
|---|---|---|
| 001 | Plugin empaquetado | `test_plugin_package.py::test_plugin_version_matches_package`, `test_release_metadata.py::test_plugin_json_version_matches_pyproject`, job `plugin` (`validate --strict`, rueda) |
| 002 | Plugin empaquetado | `test_plugin_package.py::test_hooks_json_matches_settings_delivery_0_39` |
| 003 | T0 · Plugin empaquetado · Subcomando de hooks · F2-live | Control positivo y negativo de B-1 en `evidence/T0.md`, `test_plugin_package.py::test_every_hook_entry_is_fail_open`, `test_hook_entry.py::test_hook_crash_lets_the_call_through`, `::test_hook_path_does_not_import_server`, `measure_hook_latency.py` |
| 004 | Subcomando de hooks · Estado y orquestación | `test_read_switch.py::test_active_layer_state_file_or_enabled_env`, `::test_block_state_values_unchanged`, `test_plugin_migration.py::test_migration_carries_read_switch_on/off` |
| 005 | Estado y orquestación · Instalar | `test_claude_plugin.py::test_min_version_gate`, `::test_simulated_home_passes_claude_config_dir`, `test_install_plugin_delivery.py::test_falls_back_to_settings_with_warning` |
| 006 | Estado y orquestación · Instalar | `test_plugin_migration.py::test_migration_removes_every_settings_hook_we_wrote`, `::test_backup_is_pre_install_bytes`, `::test_migration_is_idempotent` (+ mutantes) |
| 007 | Estado y orquestación | `test_install_state.py::test_missing_state_means_unknown_not_empty`, `::test_state_follows_language_dir_rule` |
| 008 | Estado y orquestación · Instalar · `doctor` · `update` | a: `test_update_plugin.py::test_settings_install_migrates_carries_switch_and_warns_restart`; b: `test_plugin_migration.py::test_revert_to_settings_in_one_step`; c: `test_checks_plugin.py::test_doctor_flags_hooks_in_settings_and_plugin`. Las tres en HOME simulado con `CLAUDE_CONFIG_DIR` |
| 009 | `doctor` · Esqueleto del mod | `test_checks.py::test_check_ids_exact`, `test_checks_plugin.py::test_mod_loaded_from_heartbeat` |
| 010 | `update` | `test_update_plugin.py::test_marketplace_update_before_plugin_update`, `::test_update_never_restores_settings_hooks_under_plugin` |
| 011 | Instalar | `test_uninstall_plugin.py::test_removes_only_what_state_lists`, `test_agents_uninstall.py::test_uninstall_undoes_agents_edit` |
| 012 | Puente · Instalar · `doctor` · `update` · F2-live | `test_desktop_bridge.py::test_bridge_against_real_daemon_app`, `test_install_desktop.py::test_desktop_flag_on_macos_refuses_cleanly`, `test_desktop_config.py::test_detects_literal_token_without_printing`, puente contra el daemon real en `evidence/F2-live.md` |
| 013 | Esqueleto del mod | `pinned-tools.test.ts` (job `plugin`) |
| 014 | Comandos | `commands.test.ts` (`lint_without_process_run_accepts_only_file`, `commit_temp_file_removed`) |
| 015 | Separables · F2-live | `test_dashboard_states.py::test_mod_calls_shown_apart`, `evidence/F2-live.md` |
| 016 | Esqueleto del mod · F2-live | `test_mod_static.py::test_mod_reads_only_the_token_variable`, `::test_register_loads_pieces_dynamically_inside_try`; en vivo, piezas a `off` y `register.js` que lanza |
| 017 | Cuota y ahorro | `test_metrics_session_filter.py::test_stats_filters_by_session`, `status.test.ts` (`hides_when_daemon_down`) |
| 018 | Medir vías | `test_measure_read_paths.py::test_counts_each_path_kind`, `evidence/F4-read-paths.md` |
| 019 | Clasificador | `test_read_classifier.py::test_corpus` (+ mutantes), `::test_classifier_change_moves_fingerprint` |
| 020 | Mod de lectura | `read.test.ts` (`accumulates_ranges_to_whole`) |
| 021 | Mod de lectura | `read.test.ts` (`buttons_when_dialog`, `denies_without_dialog`, `unclassifiable_only_warns`, `respects_read_switch_off`) |
| 022 | Mod de lectura · F4-live | `read.test.ts` (`blocks_write_after_summary`, `guard_survives_resume`); control positivo y negativo en `evidence/F4-live.md` |
| 023 | Coordinación de hooks | `test_hook_step_aside.py::test_read_hook_steps_aside_when_mod_active`, `::test_read_hook_does_not_step_aside_for_another_session`, `::test_no_gap_when_active_but_not_blocking`, `::test_read_hook_acts_when_mod_off_or_stale`, `test_checks_plugin.py::test_read_mod_and_read_hook_overlap_warns` |
| 024 | Separables · Lectura a 14 días | `test_measure_plugin_adoption.py::test_counts_sessions_not_calls`, `::test_plugin_calls_excluded`; la lectura con fecha |

## Estrategia de pruebas

- **Unidad**:
  - Los tests nombrados arriba, con la suite completa por lote (`pesado.sh`, `-n 2`).
  - Los tests del mod con `claude plugin test` en el job `plugin`. No imita bien al motor, así que
    lo que depende del motor se prueba en vivo.
- **Integración**:
  - El job `plugin` del CI en los tres SO: `validate --strict`, rueda, instalación, migración desde
    una 0.39 sembrada con el bloqueo encendido, idempotencia, vuelta a settings y `uninstall` con un
    `CLAUDE_CONFIG_DIR` aislado.
  - El evento `init` con control negativo.
  - `<ld_bin> hook prompt` con una muestra.
- **En vivo** (Windows; la Mac la prueba el usuario): T0, F2-live y F4-live. Siempre desde
  PowerShell, con `--max-turns 1` y en ventana de prueba con `start`/`stop`.
- **Controles positivos**: cada mutante se ejecuta. Se comprueba que muta el camino que corre y qué
  assert dispara, y después se revierte. B-1 tiene su control positivo y negativo en T0.
- **Seguridad**:
  - `ggshield` en pre-push y el job `secrets`.
  - Tests de que el puente, el mod, las copias de `claude_desktop_config.json`, los temporales de
    `/local-commit` y `/local-lint` y el corpus no llevan el token ni datos personales.
  - Socket de la CLI de Claude Code fijada y del paquete tras cada release.

## Migración y compatibilidad

- **Quién migra**: `install` (por defecto) y `update` de la 0.40, en Claude Code con CLI ≥ la
  mínima, HOME real y fuera de WSL.
  - Codex, OpenCode y WSL siguen por settings; en F4 sus hooks usan el clasificador.
  - La entrada MCP de `~/.claude.json`, la skill y el bloque de `CLAUDE.md` no cambian.
- **Una sola orquestación**: `apply_plugin_delivery`, en el orden de su lote. Los puntos de riesgo:
  - La copia se hace antes de cualquier `claude plugin …`.
  - El estado del interruptor se escribe antes de retirar nada.
  - Si el plugin falla, `settings.json` no se toca y se avisa.
  - Si la retirada falla después, quedan duplicados: `doctor` los marca y `update` los retira.
- **Bloqueo de lectura y P-4**:
  - La migración conserva el estado del registro de la 0.39.
  - La capa *bloquea* no cambia.
  - `blocks.jsonl` mantiene su formato y sus valores.
  - La huella del script es la misma en las dos vías.
  - Tras la 0.40.0 se comprueba la serie en esta PC.
- **Copias**:
  - `settings.json.local-delegate-plugin.bak`: una vez, con los bytes previos a todo.
  - `claude_desktop_config.json`: copia única y rotada en su carpeta. Si la entrada previa llevaba
    un token literal, la copia lo hereda; `doctor` y la wiki lo dicen.
- **Idempotencia**: una segunda pasada no cambia nada (probado en CI).
- **Sesiones abiertas**: siguen con los hooks que cargaron; `install` y `update` avisan de
  reiniciarlas.
- **Bajar de versión**: bajar a la 0.39 exige `uninstall` antes. Si alguien no lo hace, la vía de
  B-1 garantiza que el plugin que queda en caché **no bloquea**, y `doctor` de la 0.40, si vuelve,
  marca los duplicados.
- **Vuelta atrás**:
  - `install --claude-delivery settings`, en un solo paso; `update` la respeta (#404).
  - Revert de cualquier PR.
  - Las piezas del mod se apagan por `userConfig`.

## Cambios de letra de la spec

Se anotan en `spec.md` al aprobar este plan, antes de la ola 1. Este plan no edita la spec. La
redacción es la que propone el revisor (`review-plan.md`, segunda pasada):

- **REQ-003** (necesario si en T0 gana la vía B; con la A también vale): «Cada hook invoca el punto
  de entrada `hook` del paquete instalado por ruta absoluta (el ejecutable o el intérprete del
  entorno de `uv tool`), sin depender del `PATH`.» El resto de REQ-003 (p95 ≤ 300 ms, nombre
  desconocido → 0, nunca bloquea) no cambia. La condición es que `ld_bin` sale solo de una
  instalación de `uv tool`.
- **REQ-023**: «En 0.41, con entrega por plugin, el hook de lectura se aparta en las vías que el mod
  cubre en esa sesión; si el mod no actúa, actúa el hook.» Se mantienen la frase de F4 apagada por
  defecto hasta cumplir REQ-022 en vivo y el aviso de `doctor` cuando los dos actúan sobre la misma
  vía.

## Preguntas abiertas

No queda ninguna decisión del usuario más allá de aprobar los dos cambios de letra de arriba.

Única acción manual del usuario en todo el plan: en F2-live, abrir una sesión en la pestaña Code de
Claude Desktop. VS Code no se prueba en vivo; queda como límite documentado en la wiki.

## Revisión del plan

- [x] Cada REQ tiene lote, prueba nombrada y verificación.
- [x] Ficheros disjuntos dentro de cada ola, comprobados por programa; los compartidos tienen un
  dueño por ola (solo `CHANGELOG.md` se comparte).
- [x] Riesgos con copia previa, orden seguro, idempotencia y vuelta atrás: migración, `uninstall`,
  config de Desktop y bajada de versión.
- [x] Sin dependencias Python nuevas; la CLI de Claude Code fijada y auditada.
- [x] Comandos pesados serializados; las mediciones en vivo, con recurso único y ventana de prueba.

## Respuesta a la revisión

| # | Hallazgo | Qué cambió |
|---|---|---|
| B-1 | `ld_bin` sin `hook` bloquea cada prompt | Decisión 3: vías A (`onFailure`, sube la mínima a 2.1.295), B (intérprete con `-I -m`, la 0.39 sale con 1) y C (`|| exit 0`), medidas en T0 con control positivo (la 0.39 real bloquea) y negativo. Gana la primera que pase. Si ninguna pasa, no se abre la ola 1. No se acepta como límite. `test_every_hook_entry_is_fail_open`. |
| B-2 | La migración apaga el bloqueo | `apply_plugin_delivery` lee `read_hook_registered()` y escribe `read-hook.json` antes de retirar; nunca lo pone a `false` si existe. Tests `…carries_read_switch_on/off` en HOME simulado, mutante 4, y CI sembrado con el bloqueo encendido. Tras la 0.40.0 se comprueba la serie de `blocks.jsonl`. |
| I-1 | Dos capas del interruptor | Separadas: *activo* = fichero o `LD_HOOK_READ_ENABLED` o `--enabled`; *bloquea* sin cambios. Tests renombrados, más `test_block_state_values_unchanged`. |
| I-2 | Copia tras `plugin install` | Copia en el paso 1, antes de cualquier `claude plugin`. `test_backup_is_pre_install_bytes`; después de instalar se compara por JSON. |
| I-3 | HOME simulado | `CLAUDE_CONFIG_DIR` al hijo, el estado con la regla de `language.json` y una guarda en `conftest.py` (dueño: delivery-core). Tests `…passes_claude_config_dir`, `…state_follows_language_dir_rule` y `…real_claude_never_runs_in_tests`. |
| I-4 | `config.py` sin dueño | Dueño: el lote de hooks de la ola 1. Lista cerrada de variables y `test_environment_isolation.py` en su lote. |
| I-5 | Ola 2 no independiente | La orquestación pasa a la ola 1 (`apply_plugin_delivery`, `revert_to_settings`). La ola 2 se divide en 2a (install y doctor, con el cambio de `scaffold.hook_*`) y 2b (update). `test_update_never_restores_settings_hooks_under_plugin`. |
| I-6 | Contador en más ficheros | `checks.py` (docstring), `doctor.py`, `test_checks.py` (`_NUMBER_WORDS` hasta 34), `test_doctor.py`, `test_doctor_english.py`, `test_doctor_claude_settings.py`, `test_wiki.py` y la wiki, en los tres lotes que cambian el número. |
| I-7 | `register.js` importa ficheros de otros lotes | `import()` dinámico por pieza dentro de un `try`; la interfaz de `common.js` queda fijada. Si hace falta `build_mod.py`, el generado no se commitea. |
| I-8 | Tests del mod sin CI | El paso `claude plugin test` va en el job `plugin` (mod-core es dueño de `ci.yml` en la ola 3), más `test_mod_i18n_parity.py`. |
| I-9 | `claude -p` del CI no discrimina | Evento `init` en `stream-json` con control negativo (`hooks.json` roto) y `<ld_bin> hook prompt < muestra` con salida esperada. |
| I-10 | REQ-016 con `plugin disable` | T0 mide el módulo que lanza junto a los hooks. F2-live usa piezas a `off` y un `register.js` que lanza. La vuelta atrás es «piezas a `off`». |
| I-11 | F4 deja el control en un mod apagable | Decisión 10: el hook se aparta solo con el mod activo y un latido reciente; `hooks.json` no cambia. `classify` devuelve `read_switch`. `mod.read_overlap` comprueba la coordinación. La letra de REQ-023 se ajusta (pregunta 2). |
| I-12 | `/api/stats` sin sesión | F3-status posee `web/metrics.py` y `record_call.py`: parámetro `session` y `session_id` en la nota. `test_stats_filters_by_session`. |
| I-13 | Puente en macOS sin token | Decisión 11: solo Windows. En macOS y Linux, `--desktop` se niega con mensaje claro. `test_desktop_flag_on_macos_refuses_cleanly`. |
| I-14 | Puente contra un daemon falso | `test_bridge_against_real_daemon_app` (app real en proceso, SSE, sesión, 401), y en F2-live el puente lanzado como Desktop (stdio, variables de r5) contra el daemon real, más sus arranques reales en los logs de Desktop, sin pedirle llamadas al usuario. |
| I-15 | Huellas de telemetría | El hook entry pasa la ruta del script empaquetado (`test_plugin_and_settings_fingerprints_match`). La huella incluye el clasificador (`test_classifier_change_moves_fingerprint`). `--boundaries` va explícito en las dos releases. |
| I-16 | REQ-022 y `--resume` | Lista persistida por `session_id` en `CLAUDE_PLUGIN_DATA`; `guard_survives_resume`, y F4-live lo prueba. |
| I-17 | La 0.41.0 exige retirar los 7 nombres | Lote propio en la ola 4 («Retirada de los siete nombres en desuso»), con el test de horizonte en verde, como condición previa con nombre de release-041. Ya no es pregunta. |
| I-18 | Coste por llamada | El hook inactivo solo importa `read_switch` (test). F2-live y F4-live miden la sobrecarga con un tope fijado antes (+150 ms de mediana, +300 ms de p95). El mod lleva un filtro de descarte barato antes de `classify`. |
| m1 | Dónde va el atajo | En `__init__.main`, con `entrypoint` diferido y `__version__` perezoso. La latencia se mide con el `.exe` del `.venv` del worktree. |
| m2 | T0 incompleto | T0 añade `${user_config.*}` en `command`, el código 2 (B-1) y el módulo que lanza. |
| m3 | `ci_gate.py` obligatorio | En «Posee» del plugin empaquetado, con el test de `EXPECTED_JOBS`. |
| m4 | La rueda dentro de la suite | Movida al job `plugin` del CI. |
| m5 | `.sdd` sin commitear | PR solo de documentos tras T0 y antes de los worktrees de la ola 1. |
| m6 | `panel.json` | Añadido a F2-attribution. |
| m7 | `language` viejo | `update` vuelve a aplicar `--config language=…` (`test_language_change_reapplied`), y `doctor` lo marca (`test_plugin_language_stale_warns`). |
| m8 | REQ-024 sin tarea final | Tarea «Lectura de la medición de adopción» con fecha, dueño y el commit que apaga. El test del prefijo se sustituye por `test_counts_sessions_not_calls`. |
| m9 | «Sesión con diálogo» | La señal se fija en T0; `common.hasDialog(e)` la usa y F4-live la comprueba. |
| m10 | Permisos en Windows | La copia hereda la ACL de `%APPDATA%\Claude` en la misma carpeta (test de ubicación). En POSIX no aplica, porque `--desktop` se niega. |
| m11 | Test que pasa con salida vacía | Cada caso con salida propia no vacía y una guarda. |
| m12 | `uninstall` tras reemplazar una entrada ajena | No la repone (podía llevar el token): quita la nuestra y dice dónde está la copia. Test propio. |
| m13 | Mutantes que faltan | Añadidos el 4 (B-2) y el 5 (retirar antes de comprobar `list --json`). |
| m14 | Ruido y temporales | Vía de instalación de la CLI fijada en las reglas (versión exacta, Socket, `pnpm --ignore-scripts` o instalador nativo). El corpus excluye las ventanas de prueba (`test_test_windows_excluded`). `/local-commit` y `/local-lint` borran sus temporales (`commit_temp_file_removed`). |
| — | Disjunción por programa | Regla de ejecución: script de cruce de las listas «Posee» antes de cada ola. |
| N-1 | Control negativo de la vía B mal definido | T0 lleva una tabla de casos por vía. La B: entorno 0.39, intérprete inexistente, Python base borrado (se mide el código del lanzador de venv) y envoltorio con `sys.exit(2)` o excepción dentro, que debe salir con 0. Todos los casos en `UserPromptSubmit` y en `PreToolUse` de `Read`. Tests del envoltorio en F1-hook-entry. |
| N-2 | De dónde sale `ld_bin` | Solo de una instalación de `uv tool` (`update.install_kind()`). Con `uvx`, editable o un `.venv`, va a settings con aviso. Tests `test_ld_bin_is_uv_tool_env` y `test_ld_bin_rejected_from_uvx_cache`; en `doctor`, `test_ld_bin_not_the_installed_uv_tool_env_warns`. |
| N-3 | Delivery-core depende de `read_switch.py` | Contrato fijado en el preámbulo de la ola 1: `{"active", "since"}`, `path()`, `active()` y `write(active)`. Delivery-core escribe y comprueba el fichero sin importar el módulo, y el mutante 4 mira el contenido del fichero. `test_reads_contract_file_shape` en F1-hook-entry. |
| N-4 | Condiciones de apartarse distintas de las del mod; latido de máquina | Latido por `session_id`. El hook se aparta solo con las cuatro condiciones con las que actúa el mod, incluida la capa *bloquea* en `on`. El mod registra con `hook record-read`. Tests `…does_not_step_aside_for_another_session` y `…no_gap_when_active_but_not_blocking`, con tres mutantes. |
| N-5 | `HASHED_HOOKS` frente al guardián de huellas | Huella combinada (script + clasificador) dentro de `version_de`/`context_of`. `HASHED_HOOKS` no se toca y `test_hook_boundaries.py` sigue en verde. `bump_version.py` sale de «Posee» del clasificador. |
| n1 | Paso 6 del CI con la vía B | El paso usa la misma orden que declara `hooks.json`, leída del fichero instalado. |
| n2 | Codificación con `-I` | El envoltorio fuerza UTF-8 en stdout (`reconfigure`). `test_hook_output_is_utf8`. |
| n3 | Coste de bajar de versión con la vía B | CHANGELOG y wiki de la 0.40.0: alrededor de 1 s y un error no bloqueante por hook si no se hace `uninstall`. |
| n4 | No se puede apagar la capa *activo* | Opción `install --disable-read-hook` (y `uninstall`). El apagado en caliente sigue siendo `block-off`, solo para la capa *bloquea*. `test_disable_read_hook_turns_active_layer_off`. |
| n5 | Lista corta de la retirada de nombres | Añadidos `legacy_names.py`, `config.py`, `checks.py`, `test_wiki.py`, `test_retired_env_names.py` y `test_environment_isolation.py`; nadie más los toca en la ola 4. |
| n6 | Test de orquestación compartida en 2a | Movido a F1-update; en 2a queda `test_install_uses_apply_plugin_delivery`. |
| n7 | Mutantes de la coordinación de F4 | Añadidos tres: `session_id`, vigencia del latido y capa *bloquea*. |
| n8 | Dueños sin escribir en la ola 6 | `hook_common.py` pasa a F4-hooks-swap y `plugin.json` a F4-live (solo para el commit final). |
| — | Letras de REQ-003 y REQ-023 | Sección «Cambios de letra de la spec» con la redacción del revisor. Se anota en `spec.md` al aprobar. |
