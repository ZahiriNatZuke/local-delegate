# Revisión del plan: `claude-plugin-and-mods`

> Gate: **plan**. Objeto: `plan.md` (586 líneas) contra `spec.md` v2 (24 REQ), con `research*.md` y
> `review-spec.md` como contexto. Revisado el 2026-10-21, contrastado con el código de `main`
> (`e22e61d`, 0.39.0).

## Veredicto

**Aprobable con cambios, pero no ahora**: el gate no se puede aprobar hasta corregir los **2
bloqueantes**. Los importantes 5 y 7 (olas que no son independientes) también conviene meterlos
antes, porque cambian el reparto. El resto se puede corregir en el mismo pase.

Recuento: **2 bloqueantes · 18 importantes · 14 menores**.

Lo que está bien y no hay que tocar: la tabla de trazabilidad cubre los 24 REQ con lote y prueba
con nombre; tests primero en todos los lotes; el orden seguro de la migración (plugin verificado
con `list --json` **antes** de tocar `settings.json`); `test_hook_path_does_not_import_server`
(un control que sí puede fallar); los catálogos i18n nuevos por lote (el loader une todos los
`*.json`, `i18n.py:70-80`, y `test_i18n_parity.py::check_surfaces` exige que el prefijo coincida
con el fichero, como prevé la decisión 4); T0 como medición previa; F4 apagada por defecto y
condicionada a la prueba en vivo.

## Afirmaciones del plan comprobadas contra el código

| Afirmación | Resultado |
|---|---|
| `__init__` importa `entrypoint` → `server` | **Cierto**: `__init__.py:9` (`from .entrypoint import main`) y `entrypoint.py:22` (`from . import autostart, config, i18n, server`). Además `__init__.py:20` llama a `get_version()` al importar. |
| `i18n` une todos los `resources/i18n/<lang>/*.json` | **Cierto** (`i18n.py:70-80`); el prefijo por fichero lo exige `tests/test_i18n_parity.py`. |
| `scripts/bump_version.py` y `tests/test_release_metadata.py` | Existen los dos. `bump_version.py` también mantiene las huellas de hooks (`HASHED_HOOKS`, `--boundaries`): ver I-15. |
| `doctor` tiene hoy 27 checks | **Cierto** (`tests/test_checks.py:93`). Pero el número aparece en más sitios de los que posee el plan: ver I-6. |
| `install._is_ours`, `strip_hook_settings`, `install.Action`, `_HOOK_EVENTS`, `_READ_HOOK`, `_SHELL_HOOK`, `_MCP_READ_HOOK` | Existen (`install.py:73-91, 210, 1133, 1199`). |
| `web/metrics.py`, `attribution.py`, `test_dashboard_states.py`, `test_hook_common.py`, `test_hook_shell.py` | Existen. |
| El daemon lee el token de «una fuente» reutilizable en macOS | **No existe**: el daemon lo lee solo de su entorno (`config.py:515`) y `autostart.py` no tiene nada de launchd. Ver I-13. |
| `CLAUDE_CONFIG_DIR` y WSL | Ningún módulo de `src/` los trata hoy: son código nuevo (ver I-3). |

## A. Bloqueantes

### B-1. Un `ld_bin` que no conoce `hook` bloquea cada prompt (incumple REQ-003)

- **Dónde**: `plan.md:63` («No se usa `onFailure`… el "deja pasar" lo dan los códigos de salida»),
  decisión 2 (`plan.md:23-26`) y el diseño de F1-hook-entry (`plan.md:168-170`).
- **Por qué importa**: «nombre desconocido → exit 0» solo vale para las versiones **nuevas**. Lo
  comprobé con la 0.39 instalada: `echo {} | local-delegate hook prompt` sale con **exit 2**
  (argparse: «opción no válida: 'hook'»). En Claude Code, exit 2 en `UserPromptSubmit` **bloquea el
  prompt**, y en `PreToolUse` bloquea la tool. El plugin queda en la caché aunque el paquete baje de
  versión, así que basta con bajar a la 0.39 sin `uninstall` (el plan solo lo documenta, `plan.md:561`),
  o con un `ld_bin` que apunte a otro ejecutable viejo, para dejar Claude Code inutilizable en cada
  prompt. REQ-003 dice «nunca bloquea un prompt ni una tool por un fallo propio».
- **Cambio**: (a) T0 mide qué hace Claude Code con exit 2 de un hook de plugin y qué cubre `onFailure`
  (2.1.295); si lo cubre, subir `MIN_CLAUDE_PLUGIN_VERSION` a 2.1.295 y usarlo en las cinco entradas.
  (b) Si no lo cubre, otra salida que no dependa de la versión del ejecutable (p. ej. que el
  `SessionStart`/primer hook compruebe `ld_bin --version` y que `install`/`update`/`uninstall` de la
  0.40 deshabiliten el plugin si el paquete instalado no lo soporta), o, como mínimo, documentarlo
  como límite **aceptado por el usuario**, no por el plan. (c) Prueba con nombre:
  `test_plugin_hooks_never_block_with_old_ld_bin` (o la evidencia de T0 si es conducta del motor).

### B-2. La migración apaga en silencio el bloqueo de lectura

- **Dónde**: F1-delivery-core (`plan.md:200-203`), F1-update (`plan.md:285-288`), release-040
  (`plan.md:383-385`: «`local-delegate update`, que migra al plugin»), y «Interruptor de lectura»
  (`plan.md:563-565`).
- **Por qué importa**: en la 0.39 el interruptor **es** el registro: `install --enable-read-hook`
  registra las entradas de lectura con `--enabled` (`install.py:142, 2257-2258`), y `update` ya tuvo
  este mismo fallo y lo arregla leyendo `install.read_hook_registered()` antes de reescribir
  (`update.py:318`; docstring en `install.py:1149-1156`: «el bloqueo se apaga en silencio justo al
  actualizar»). El plan de migración copia, retira y borra, pero **nadie escribe el fichero de
  estado del interruptor a partir de lo que había**; solo lo escribe `install --enable-read-hook`.
  En esta PC la migración la hace `update` en la release 0.40.0, con la ventana P-4 abierta: el
  bloqueo se apagaría y la serie de `blocks.jsonl` se cortaría, justo lo que REQ-004 quiere evitar.
- **Cambio**: la migración (un solo sitio, ver I-5) lee `read_hook_registered()` **antes** de
  retirar y escribe `read-hook.json` con ese valor; nunca lo pone a `false` si ya existe. Tests:
  `test_plugin_migration.py::test_migration_carries_read_switch_on` y `::…_off`, en `install` y en
  `update`. Mutante: no escribir el estado → falla el assert `read_switch.enabled() is True` de
  `…_on`.

## B. Importantes

### I-1. El interruptor tiene dos capas y el plan las mezcla

- **Dónde**: `plan.md:171-174` y tests `test_read_switch.py::test_env_beats_state_file`,
  `::test_state_file_enables` (`plan.md:179-180`).
- **Por qué**: hoy hay dos decisiones distintas: **actuar** (registrar/avisar), que da `--enabled` o
  `LD_HOOK_READ_ENABLED` (`suggest_delegate_read.py:134-143`), y **bloquear**, que da
  `block_state()` con `local-delegate-block-off` > `LD_HOOK_READ_BLOCK` (por defecto apagado)
  (`hook_common.py:297-305`). El fichero de estado sustituye a `--enabled`, no compite con
  `LD_HOOK_READ_BLOCK`. Con la precedencia escrita («block-off > `LD_HOOK_READ_BLOCK` > fichero»),
  una variable sin definir pasaría a decidir el fichero, y los valores de `block_state` que van a
  `blocks.jsonl` (`on`/`off_file`/`off_variable`) quedarían ambiguos. Además, el plan no menciona
  `LD_HOOK_READ_ENABLED`.
- **Cambio**: escribir en el plan las dos capas: *activo* = fichero de estado **o**
  `LD_HOOK_READ_ENABLED` (o `--enabled` en la vía settings); *bloquea* = sin cambios. Renombrar los
  tests para que digan qué capa prueban y añadir `test_block_state_values_unchanged`.

### I-2. La copia de `settings.json` se hace después de que `claude plugin install` lo modifique

- **Dónde**: `plan.md:257-260` (orden) y `plan.md:555-556`.
- **Por qué**: `claude plugin install … --config` escribe en `settings.json` (`enabledPlugins` y
  `pluginConfigs.<id>.options`: r1 líneas 86-88, [PRUEBA]). Si la copia la hace el plan de
  migración, que corre **después** de instalar, la copia ya no es el estado anterior y la vuelta
  atrás no es fiel. Además, la CLI puede reformatear el fichero, y eso choca con «nada ajeno se toca».
- **Cambio**: la copia, antes de cualquier `claude plugin …`. Test
  `test_backup_is_pre_install_bytes` (igualdad de bytes con el fichero sembrado) y una nota en el plan
  de que el formato lo reescribe la CLI (los tests comparan por JSON, no por bytes, después de
  instalar).

### I-3. HOME simulado: `CLAUDE_CONFIG_DIR`, dónde va el estado y que ningún test lance el `claude` real

- **Dónde**: F1-delivery-core (`plan.md:193-199`), F1-install CI (`plan.md:273-276`).
- **Por qué**: (a) `install --home X` escribe en `X/.claude/settings.json`, pero `claude plugin
  install` escribe donde diga `CLAUDE_CONFIG_DIR` o en el `~/.claude` **real**. Si no se pasa
  `CLAUDE_CONFIG_DIR=X/.claude` al proceso hijo, se instala en la PC real y se migra el HOME falso.
  (b) `install-state.json` va en `LOG_DIR`. `install` ya tiene una regla para no tocar `language.json`
  con HOME simulado (`install.py:1741`); el estado necesita la misma, o los ensayos con `--home`
  ensucian el estado real, y luego un `uninstall` real borraría según datos falsos. (c) Con `claude`
  en el `PATH` (esta PC) y `CLAUDE_CONFIG_DIR` heredado, los tests existentes de `install` (que no
  inyectan ejecutor) podrían tomar la vía plugin.
- **Cambio**: escribir en el plan las tres reglas, con estos tests: `test_simulated_home_passes_claude_config_dir`;
  `test_state_follows_language_dir_rule`; y una guarda en `tests/conftest.py` (con dueño en la ola 1)
  que borre `CLAUDE_CONFIG_DIR`/`CLAUDE_PLUGIN_*` y haga fallar cualquier ejecución del `claude` real
  no inyectada, más un test que lo compruebe.

### I-4. `config.py` y el inventario de variables no tienen dueño

- **Por qué**: `tests/test_environment_isolation.py:113-141` exige que toda variable que lean los hooks
  esté declarada en `config.ENVIRONMENT_VARIABLES`, y que `config` lea el entorno solo por `_read`.
  En la ola 1 van a leer variables nuevas F1-hook-entry (`CLAUDE_PLUGIN_*`, ruta del estado),
  F1-delivery-core (`CLAUDE_CONFIG_DIR`, WSL) y F1-desktop-bridge (token). Ninguno posee `config.py`
  y tres lo necesitarían en la misma ola.
- **Cambio**: un dueño de `config.py` en la ola 1 (p. ej. F1-hook-entry) y la lista de variables
  nuevas cerrada en el plan, para que los otros dos la usen sin editar el fichero.

### I-5. La ola 2 no es independiente

- **Dónde**: `plan.md:242-245` y lotes F1-install / F1-update / F1-doctor.
- **Por qué**: (a) `update` repara a partir de los ids de `checks.run_all` (tabla `REPAIRS`,
  `update.py:147-226, 280-318`). Las reparaciones por `plugin.installed` y `hooks.duplicates` necesitan
  las sondas de F1-doctor. Y, sobre todo, las reparaciones **existentes** de `scaffold.hook_settings`
  / `hook_files` **repondrían los hooks en `settings.json`** con el plugin puesto, hasta que F1-doctor
  cambie su semántica por vía. Si se mezcla primero F1-update, quedan duplicados. (b) `update` construye
  `install.Options` (`update.py:230`), que F1-install amplía (`--claude-delivery`, `--desktop`).
  (c) «Instalar plugin → verificar → copiar → migrar → interruptor → estado» se implementaría dos
  veces, en `install.py` y en `update.py`.
- **Cambio**: pasar a la ola 1 (F1-delivery-core) una sola función de orquestación
  (`plugin_migration.apply_plugin_delivery(...)`, con B-2 e I-2 dentro), y que `install` y `update`
  solo la llamen. Y dividir la ola 2 en **2a** (F1-install + F1-doctor) y **2b** (F1-update), o
  adelantar a la ola 1 las sondas y el cambio de semántica de `scaffold.hook_*`. Test en F1-update:
  `test_update_never_restores_settings_hooks_under_plugin`.

### I-6. El contador de `doctor` vive en más ficheros de los que poseen los lotes

- **Dónde**: F1-doctor (`plan.md:298-301`), F2-mod-core (`plan.md:325-327`), F4-hooks-swap
  (`plan.md:463-465`).
- **Por qué**: además de `test_checks.py:93` y `test_doctor.py`, el número está en
  `tests/test_checks.py:1180-1201` (`_NUMBER_WORDS` termina en 27: con 32 da **KeyError**), en cinco
  frases del docstring de `checks.py` que comprueba `test_the_docstring_states_how_many_checks…`
  (`test_checks.py:1206-1226`), en `tests/test_wiki.py:35` (`_CHECK_COUNT_WORDS`) junto con la tabla
  de la wiki (`test_the_doctor_table_lists_every_check`), en `tests/test_doctor_english.py:89`
  (`== 27`) y en el comentario de `doctor.py:71`. También cambia de conducta
  `tests/test_doctor_claude_settings.py`.
- **Cambio**: añadir esos ficheros a «Posee» de los tres lotes (en olas distintas, así que no hay
  choque) y ampliar los diccionarios hasta 34.

### I-7. La ola 3 comparte el mod: `register.js` importa un fichero de otro lote

- **Dónde**: decisión 6 (`plan.md:41-47`), F2-mod-core (`plan.md:322-327`) y F2-commands
  (`plan.md:342`).
- **Por qué**: la decisión 6 dice que «desde F2 están los cinco ficheros», pero F2-mod-core no posee
  `mod/commands.js`, y `register.js` lo importa. Si es un import estático y el fichero no existe, el
  PR de mod-core no carga. Si mod-core crea un fichero vacío, lo tocan dos lotes. Además,
  `commands.js` usa la API de `common.js` (token, `127.0.0.1`, idioma) sin contrato escrito. Y si T0
  obliga a `build_mod.py`, `register.js` es un generado que cambian **todos** los lotes del mod.
- **Cambio**: que `register.js` cargue cada pieza con un `import()` dinámico dentro de un
  `try` (si falta o falla, esa pieza queda apagada). Eso además cumple REQ-016. Fijar en el plan la
  interfaz de `common.js`. Si hace falta `build_mod.py`, que el generado no se commitee, o que lo
  regenere solo la sesión principal al mezclar.

### I-8. Los tests del mod no corren en ningún CI

- **Dónde**: `plan.md:154-156` (job `plugin`) y `plan.md:532-534`.
- **Por qué**: REQ-013, 014, 017, 020, 021 y 022 se trazan a `*.test.ts`, pero el job `plugin` solo
  valida, instala y lanza `-p`, y la suite es pytest. Según r1:314, `claude plugin test` corre sin
  sesión ni red, así que puede ir en CI. Sin ese paso, ningún PR del mod tiene un control que pueda
  ponerse en rojo. Tampoco hay paridad es/en para `mod/i18n/*.json`.
- **Cambio**: un paso `claude plugin test <plugin>` en el job `plugin` (lo añade F2-mod-core, que en la
  ola 3 sería dueño de `ci.yml`) y un test pytest de paridad para `mod/i18n`.

### I-9. El `claude -p` del CI no distingue nada

- **Dónde**: `plan.md:155-156` y `plan.md:537`.
- **Por qué**: «exit 1 esperado» sale igual si el plugin carga que si no. Y según r1:325, sin cuenta
  solo se disparan los hooks `SessionStart`, y el plugin no declara ninguno: ninguno de nuestros
  hooks corre. Es un control que no puede dar un resultado distinto.
- **Cambio**: comprobar con `--output-format stream-json --verbose` que el evento `init` lista el
  plugin sin errores (r1:328-329), con un control negativo: el mismo paso con un `hooks.json` roto
  debe fallar. Y probar que `ld_bin` resuelve ejecutando `<ld_bin> hook prompt < muestra.json` (exit 0,
  salida esperada).

### I-10. REQ-016 se verifica con `claude plugin disable`, que apaga también los hooks

- **Dónde**: F2-live (`plan.md:375`) y vuelta atrás de F2-mod-core (`plan.md:338`).
- **Por qué**: hooks y mod van en el mismo plugin; deshabilitarlo apaga los dos, así que la prueba
  «los hooks siguen» no puede salir bien por la razón que dice. Tampoco sabemos si un `register.js` que
  lanza al cargar se lleva por delante los `hooks` del mismo `hooks.json`.
- **Cambio**: T0 añade el caso «módulo que lanza al cargar + hooks en el mismo `hooks.json`: ¿se
  disparan los hooks?». F2-live apaga el mod por `userConfig` (todas las piezas a off) **y** con un
  `register.js` que lanza, y comprueba que `record_call` y el MCP siguen. La vuelta atrás del mod pasa
  a ser «piezas a off», no `plugin disable`.

### I-11. La sustitución de hooks de F4 deja el control de lectura en manos de un mod que se puede apagar

- **Dónde**: F4-hooks-swap (`plan.md:467-471`) y F4-live (`plan.md:483`); contrato de `classify`
  (`plan.md:420-423`).
- **Por qué**: `hooks.json` es estático. Si en la 0.41 deja de declarar las entradas de lectura, quien
  ponga `read_mod_enabled=false`, o un mod que falle porque cambió la API, se queda sin bloqueo
  ninguno, en contra de lo que pide REQ-016 (degradable). Además, el mod solo puede leer
  `LOCAL_DELEGATE_WEB_TOKEN` (REQ-016 y `test_mod_reads_only_the_token_variable`), así que no puede
  saber si el interruptor está encendido (fichero de estado, `block-off`, `LD_HOOK_READ_BLOCK`), y
  REQ-021 lo exige.
- **Cambio**: en vez de quitar entradas, que el hook de lectura **se aparte** cuando el mod de lectura
  está activo (`CLAUDE_PLUGIN_OPTION_READ_MOD_ENABLED`, que llega a todos los hooks según r1:89-93,
  más un latido reciente). Así REQ-023 se cumple sin cambiar `hooks.json`, y `mod.read_overlap` pasa a
  comprobar esa coordinación. Añadir `"read_switch": "on"|"off_file"|"off_variable"|"inactive"` a la
  salida de `hook classify`.

### I-12. `/api/stats` no filtra por sesión (REQ-017)

- **Dónde**: F3-status (`plan.md:392-396`).
- **Por qué**: `/api/stats` solo acepta `from`, `to`, `include_tests` y `lang`
  (`web/metrics.py:544-550`). Con un rango de horas no se separa una sesión de otra que corra a la
  vez. F3-status solo posee `mod/status.js`.
- **Cambio**: F3-status posee también `web/metrics.py` (libre en la ola 4) para añadir un parámetro
  `session` (a partir de `session_id`/`tool_use_id` de las notas de `record_call`), con el test
  `test_stats_filters_by_session`. O bien la spec acepta «desde el inicio de la sesión» y el plan lo
  dice.

### I-13. El puente de Desktop en macOS no tiene de dónde sacar el token

- **Dónde**: F1-desktop-bridge (`plan.md:224-227`).
- **Por qué**: el daemon toma el token de su propio entorno (`config.py:515`) y no hay ninguna «fuente»
  que reutilizar. Además, la Mac va por stdio contra el backend de la PC, sin daemon local (memoria
  `topologia-mac-contra-la-pc`), así que un puente al daemon local no tiene nada al otro lado.
- **Cambio**: que el plan decida que en macOS `--desktop` escribe una entrada stdio directa
  (`<ld_bin>` sin argumentos, como la de Claude Code en la Mac) o que no está soportado y lo dice. Test
  `test_desktop_flag_on_macos_*` según la decisión.

### I-14. El puente se prueba contra un daemon falso y no hay prueba en vivo del chat de Desktop

- **Dónde**: `plan.md:232-237` y la ola 3b.
- **Por qué**: el `/mcp` del daemon es *streamable HTTP* (`Mcp-Session-Id`, respuestas SSE, 401 con
  la cabecera mal). Un daemon falso que responde JSON plano no puede mostrar justo los fallos
  probables. Y en ningún sitio del plan alguien abre el chat de Desktop y llama a una tool a través
  del puente.
- **Cambio**: `test_bridge_against_real_daemon_app` (la app de `daemon.py` en proceso, con token,
  sesión y SSE). Y en F2-live, un paso de Desktop: la sesión principal ejecuta `install --desktop` en
  la PC real, el usuario reinicia Desktop y llama a una tool desde el chat, y se comprueba la fila en
  el log del daemon y que `doctor` no avisa.

### I-15. Las huellas de telemetría no verán los cambios del clasificador

- **Por qué**: cada evento lleva `version_de(script)`, el sha256 **del script** (`hook_common.py:63-91`),
  y los tramos de P-4 se cortan por esa huella (`scripts/data/hook_hashes_after.json`,
  `bump_version.py --boundaries`). En F4 la lógica pasa a `read_classifier.py`: un cambio de reglas
  no mueve la huella y la medición mezclaría tramos. Además, `hook_entry` tiene que pasar la ruta del
  script empaquetado para que la huella sea la misma que en la vía settings.
- **Cambio**: que la huella de `suggest_delegate_read/shell` incluya `read_classifier.py` (o añadirlo
  a `HASHED_HOOKS` y al evento). Test `test_classifier_change_moves_fingerprint`. En los dos PR de
  release, `bump_version.py --boundaries` (`docs/wiki/Publishing.md:49`) escrito de forma explícita.

### I-16. La guarda de REQ-022 se pierde con `--resume`

- **Dónde**: F4-read-mod (`plan.md:452-453`) y F4-live (`plan.md:481-482`).
- **Por qué**: la lista de «ficheros leídos como resumen» vive en la memoria del mod. Al reanudar,
  el proceso es nuevo, la lista está vacía y el modelo conserva el resumen en el contexto. Además, `Edit`
  no exige un `Read` previo (r4, 2.1.306). Que la salida sea «límite documentado» en un requisito
  de **pérdida de datos** es poco.
- **Cambio**: persistir la lista por `session_id` en `${CLAUDE_PLUGIN_DATA}` y recargarla al iniciar
  sesión. Test `read.test.ts::guard_survives_resume`, y F4-live lo prueba con `--resume`.

### I-17. La 0.41.0 no puede salir sin la retirada de los 7 nombres: el plan lo trata como una coincidencia

- **Dónde**: `plan.md:488-490` y la pregunta abierta 1 (`plan.md:569-570`).
- **Por qué**: no es solo un compromiso de calendario. `tests/test_deprecations.py:36-38`
  (`_assert_horizon` con la versión de `pyproject.toml`) y `overdue("0.41.0")`, que devuelve los siete
  (`test_deprecations.py:479-480`), ponen en **rojo** el PR de release en cuanto el bump diga 0.41.0.
  Y tres de los siete son del interruptor de lectura (`LD_HOOK_READ_BLOQUEAR`,
  `LD_HOOK_READ_INTERRUPTOR`, `local-delegate-bloqueo-apagado`), la misma zona que tocan
  F1-hook-entry, `doctor` y F4.
- **Opinión**: me parece bien dejarlo **fuera de este SDD**: es otro objetivo, con su propio criterio
  de aceptación, y meterlo aquí alarga una spec ya grande. Pero no puede quedar como «trabajo aparte
  que la release espera», sin dueño ni fecha, porque entonces F4 queda retenida por algo que nadie tiene
  planificado. Propuesta: un SDD ligero propio (`retire-seven-names`), con su sitio fijado en **este**
  plan, en la **ola 4**. Allí los ficheros que toca (`deprecations.py`, `legacy_names.py`, `cli.py`,
  `checks.py`, sus tests y la wiki) están libres: F3-status y F4-measure-reads no los usan. Así está
  mezclado antes de la ola 6, y release-041 lo pone como condición previa con nombre. Si el usuario
  prefiere desacoplar, la otra opción es publicar F4 como 0.40.x sin el bump a 0.41.

### I-18. Coste por llamada de herramienta: los hooks de lectura siempre declarados y `classify` en cada `Bash`

- **Por qué**: en la 0.39, con el interruptor apagado las entradas de lectura **no se registran**
  (`install.py:2257`). En el plugin van siempre (`hooks.json` estático). Así, cada `Read`, `Bash`,
  `PowerShell` y lectura MCP arranca `local-delegate.exe`, unos 300 ms en el peor caso del objetivo
  (r1 midió 1 127 ms con `--version`, que carga el servidor). En F4 se suma `process.run` → `hook
  classify` en cada llamada. Nadie mide el efecto en una sesión real.
- **Cambio**: en F1-hook-entry, que el hook de lectura con el interruptor inactivo salga sin
  importar nada más que `read_switch` (test de `sys.modules`). En F2-live y F4-live, medir la
  sobrecarga por llamada `Bash` con el plugin frente a sin él, y fijar un tope en el plan antes de
  medir. En el mod, un filtro barato en JS (nombre de tool y primer token) antes de llamar a
  `classify`, que sí cabe en «una sola implementación» porque solo descarta.

## C. Menores

1. **Decisión 3, dónde va el atajo** (`plan.md:27-30`): tiene que ir en `__init__.main` con el import
   de `entrypoint` diferido (hoy `__init__.py:9` lo importa al cargar). También hay que hacer perezoso
   `__version__ = get_version()`. `measure_hook_latency.py` mide el `.exe` del `.venv` del worktree,
   no `uv run` (que añade el arranque de uv) ni el `uv tool` real (prohibido tocarlo).
2. **T0 incompleto** (`plan.md:123-131`): r1 solo **probó** `${user_config.*}` en `args`. Que
   funcione en `command` (decisión 2) es [DOC]: añadirlo a T0, junto con exit 2 (B-1) y el módulo
   que lanza (I-10).
3. **`ci_gate.py` no es opcional** (`plan.md:144-145`, «si el gate debe conocer el job»):
   `test_ci_gate.py` ata `EXPECTED_JOBS` a los jobs de `ci.yml`, así que añadir el job `plugin`
   obliga a tocarlo.
4. **`test_wheel_contains_plugin` construye la rueda dentro de la suite** (`plan.md:151-152`): es un
   comando pesado en cada pasada y con xdist. Mejor llevarlo al job `plugin` del CI, o marcarlo y
   correrlo con `pesado.sh`.
5. **`.sdd/changes/claude-plugin-and-mods/` sin commitear** (`plan.md:497-498`): los worktrees nacen
   de `main` y no verán `brief.md`, el plan ni `evidence/T0.md`. Conviene un PR solo de documentos tras
   T0 y antes de abrir los worktrees de la ola 1, en vez de «el primero que llegue».
6. **F2-attribution sin `panel.json`** (`plan.md:357-359`): mostrar aparte las llamadas del mod
   necesita textos del panel (`resources/i18n/{es,en}/panel.json`) y el JS embebido en `metrics.py`.
   Añadir `panel.json` a «Posee».
7. **`userConfig.language` se queda viejo**: si el usuario cambia el idioma después
   (`language.json`), el mod sigue en el anterior. `update` debería volver a aplicar
   `--config language=…`, o el mod debería preguntar el idioma a la CLI.
8. **REQ-024 sin tarea final**: nadie tiene encargada la lectura a 14 días ni la decisión «si no sube,
   se apagan las tools fijas». Falta una tarea con fecha, dueño y el commit que apaga. Y
   `test_counts_by_tool_use_id_not_prefix` (`plan.md:367-368`) prueba un caso que ya no existe: con el
   MCP fuera del plugin, el nombre de las tools no cambia.
9. **REQ-021: falta decir cómo se detecta «sesión con diálogo»** frente a `-p` o un subagente. El
   plan no dice qué señal usa (`entrypoint` del latido, `agent_id` del evento…); hay que fijarla y
   comprobarla en T0 o en F4-live.
10. **«Permisos solo del usuario» en Windows** (`plan.md:230, 235`): sin dependencias nuevas no hay
    ACL desde stdlib. Hay que decir que en Windows la copia hereda la ACL de `%APPDATA%\Claude`
    (y el test comprueba la ubicación), y que en POSIX va con `0600`.
11. **`test_each_hook_name_matches_script_behaviour`** (`plan.md:177-178`): si todos los casos dan
    salida vacía, el test pasa sin haber comprobado nada. Cada caso tiene que producir una salida
    propia, no vacía, y una guarda que lo compruebe.
12. **`uninstall` tras reemplazar una entrada ajena de Desktop**: falta decidir si repone la copia
    previa o deja la clave vacía. Hoy, en esta PC, la entrada previa es `mcp-remote` con el token
    escrito a mano.
13. **Mutantes que faltan**: (a) aplicar la migración antes de comprobar `list --json` → debe fallar
    `test_plugin_failure_leaves_settings_untouched` en la igualdad del fichero; (b) el de B-2.
14. **Ruido en las mediciones y temporales**: T0 y el CI deben decir cómo instalan la CLI (versión
    exacta, `ignore-scripts` o instalador nativo, y Socket del paquete concreto). El corpus de
    REQ-018 debe excluir las ventanas de prueba (memoria: un tercio de lo histórico eran pruebas).
    `/local-commit` debe borrar el temporal del diff, que puede llevar secretos.

## Evidencia que falta antes de aprobar

- La respuesta de T0 a B-1 (conducta con exit 2 y alcance de `onFailure`), o la decisión del usuario
  de aceptarlo como límite.
- El plan corregido con el orden nuevo de olas (I-5) y el sitio de la retirada de los 7 nombres (I-17).

## Evidencia recomendada para el gate cuando se apruebe

- `plan.md` v2 con B-1, B-2 e I-1…I-18 resueltos o con un rechazo razonado, y la tabla de
  trazabilidad al día (pruebas nuevas: `test_migration_carries_read_switch_on/off`,
  `test_backup_is_pre_install_bytes`, `test_simulated_home_passes_claude_config_dir`,
  `test_update_never_restores_settings_hooks_under_plugin`, `test_bridge_against_real_daemon_app`,
  `guard_survives_resume`, `test_stats_filters_by_session`, `test_classifier_change_moves_fingerprint`).
- Una comprobación por programa de que los ficheros son disjuntos dentro de cada ola (no a ojo):
  sacar las listas «Posee» y cruzarlas.

---

## Segunda pasada (plan v2, 978 líneas)

### Veredicto

**Aprobable con cambios.** Los dos bloqueantes de la primera pasada **están resueltos en el
diseño**. Quedan **5 importantes nuevos** y **8 menores** que se pueden corregir en el mismo pase del
plan sin cambiar las olas. Ninguno bloquea el gate si se corrige antes de abrir la ola 1 (los
importantes N-1 y N-2 condicionan T0 y la ola 1; N-4 y N-5, las olas 5 y 6).

Recuento de esta pasada: **0 bloqueantes · 5 importantes · 8 menores**. De los 34 hallazgos
anteriores, 33 quedan resueltos; I-15 queda resuelto a medias (ver N-5).

### Los dos bloqueantes, comprobados

**B-1 (ejecutable viejo o ausente): resuelto en el diseño, con un defecto en los controles (N-1).**
- La premisa de la decisión 2 es cierta: ningún hook nuestro usa el código 2; los bloqueos van con
  `permissionDecision: "deny"` y salida 0 (`hook_common.py:134-155`; ni un `exit(2)` en
  `resources/hooks/`). Así que convertir cualquier salida distinta de 0 en «deja pasar» no pierde
  conducta.
- **La vía B es cierta**, comprobado hoy con el `uv tool` 0.39 de esta PC:
  `"%APPDATA%/uv/tools/local-delegate-mcp/Scripts/python.exe" -I -m local_delegate.hook prompt` →
  «No module named local_delegate.hook», **exit 1**. El 2 de Python solo aparece con un fichero de
  script que no se puede abrir o con opciones mal formadas, que no es el caso con `-m`.
- El control positivo (la 0.39 real bloquea el prompt) discrimina: demuestra que el daño existe y
  que el montaje lo ve. El negativo por vía también discrimina, salvo en lo que dice N-1.
- La regla «si ninguna vía pasa, no se abre la ola 1» está bien: no deja el riesgo como límite.

**B-2 (la migración apaga el bloqueo): resuelto.**
- `apply_plugin_delivery` lee `install.read_hook_registered()` (existe, `install.py:1143`) en el
  paso 2, antes de la instalación (paso 3) y de la retirada (paso 5); nunca escribe `false` sobre un
  estado que ya existe; `install` y `update` solo la llaman (y release-040 migra con `update`).
- El mutante 4 discrimina: `LD_HOOK_READ_ENABLED` está declarada en `config.py:200`, así que la
  suite la aísla y `read_switch.active()` no puede salir `True` por el entorno de la máquina.
- `install.data_dir_for` existe (`install.py:1725`), así que la regla de `language.json` es
  reutilizable de verdad.
- Lo único que falta es el contrato de `read_switch` entre dos lotes de la misma ola (N-3).

### Olas tras partir la 2: disjunción

Crucé a mano las listas «Posee» de cada ola (el plan exige hacerlo además por programa):

| Ola | Resultado |
|---|---|
| 1 | Disjunta. `ci.yml` y `pyproject.toml` → F1-package; `config.py`, `hook_common.py`, `suggest_delegate_read.py` → F1-hook-entry; `conftest.py` → F1-delivery-core. **Pero hay una dependencia de código** entre F1-delivery-core y `read_switch.py` (N-3). |
| 2a | Disjunta (`install.py`, `cli.py`, `ci.yml`, `Home.md` frente a `checks.py`, `doctor.py`, `test_wiki.py`, `Integration-install.md`, `Troubleshooting.md`). |
| 2b | Un solo lote. |
| 3 | Disjunta (`ci.yml`, `plugin.json`, `hooks.json` y `doctor` → mod-core; mod/commands → F2-commands; `metrics.py`, `attribution.py`, `panel.json` → F2-attribution). |
| 4 | Disjunta. `metrics.py` y `record_call.py` → F3-status; la wiki de instalación → retire-seven-names. La lista de retire-seven-names probablemente se queda corta (n-5), pero nadie más en la ola toca esos ficheros. |
| 5 | Disjunta. Pero F4-classifier no posee `tests/test_hook_boundaries.py` ni `scripts/data/hook_hashes_after.json`, y los va a necesitar (N-5). |
| 6 | En serie; no aplica. |

### Las dos decisiones que cambian la letra de la spec

**REQ-003 con la vía B (`ld_bin` = el `python` del entorno de `uv tool`): compatible con la
intención.** Lo que REQ-003 protege es que haya una sola entrada al paquete por ruta absoluta, sin
`python` del sistema ni del `PATH` (el problema de macOS y de la app gráfica), rápida y que nunca
bloquea. `-I -m local_delegate.hook` cumple todo eso, y además `-I` saca el directorio actual de
`sys.path`. La condición es N-2: saber de dónde sale ese intérprete, porque con la vía B una ruta
equivocada o efímera ya no bloquea, sino que **deja de actuar en silencio**. La nueva letra
propuesta: «cada hook invoca el punto de entrada `hook` del paquete instalado por ruta absoluta (el
ejecutable o el intérprete del entorno de `uv tool`), sin depender del `PATH`».

**REQ-023 apartando el hook en vez de quitarlo de `hooks.json`: compatible, y mejor para
REQ-016.** La intención de REQ-023 es que haya un solo control por vía y que `doctor` avise si
coinciden. Apartarse en tiempo de ejecución cumple eso y además devuelve el control al hook si el mod
se apaga o falla, que es lo que pide REQ-016. La condición es N-4: hoy las condiciones para
apartarse no son las mismas que las del mod para actuar, y el latido no es de la sesión. La nueva
letra propuesta: «en 0.41, con entrega por plugin, el hook de lectura se aparta en las vías que el
mod cubre en esa sesión; si el mod no actúa, actúa el hook».

### Hallazgos nuevos o no resueltos

#### Importantes

**N-1. El control negativo de la vía B está mal definido.**
- **Dónde**: T0, `plan.md:172-175` («con la 0.39, con un ejecutable inexistente y con uno que sale
  con 2 deja pasar»).
- **Por qué**: la vía B no convierte el 2; lo **evita**. Un módulo de prueba que sale con 2 bloquea
  también con B, así que ese caso rechazaría B por error, o, si el módulo es el envoltorio que siempre
  sale con 0, no comprueba nada. Además faltan dos casos reales: un entorno roto (la `pyvenv.cfg`
  apunta a un Python base que `uv` borró al actualizar; en Windows el lanzador de venv sale con un
  código propio que hay que medir) y un `PreToolUse` (solo se prueba `UserPromptSubmit`).
- **Cambio**: casos por vía en una tabla. A: 0.39, ejecutable inexistente y uno que sale con 2. B:
  entorno 0.39 (exit 1, ya medido), intérprete inexistente, entorno con el Python base borrado, y el
  envoltorio con un `sys.exit(2)` y una excepción dentro (debe salir 0). Y en las dos vías, el mismo
  juego sobre un `PreToolUse` de `Read`.

**N-2. No se dice de dónde sale `ld_bin`.**
- **Dónde**: F1-delivery-core (`plan.md:282-284, 291`) y la decisión 3.
- **Por qué**: si `install` lo deduce de `sys.executable` o `sys.argv[0]` y se ejecutó con `uvx` (la
  caché de `uv`), desde el `.venv` del repo o desde un worktree, `ld_bin` apunta a algo efímero o que
  no es el paquete instalado. Con la vía B (o la A), cuando desaparezca, **todos los hooks dejan de
  actuar en silencio**: se pierde el bloqueo de lectura y la telemetría de `record_call`, sin aviso
  hasta que alguien corra `doctor`. `update.py` ya distingue cómo está instalado el paquete
  (`install_kind()`, `update.py:586`).
- **Cambio**: una regla escrita: `ld_bin` solo se toma de una instalación de `uv tool` (o del
  ejecutable de `~/.local/bin`, según la vía). Con `uvx`, editable o venv de desarrollo, la vía plugin
  se rechaza y se va a settings con aviso. Tests `test_ld_bin_rejected_from_uvx_cache` y
  `test_ld_bin_is_uv_tool_env`. `plugin.ld_bin` de `doctor` comprueba además que es el mismo entorno
  que la versión instalada.

**N-3. F1-delivery-core depende de `read_switch.py`, que es de otro lote de la misma ola.**
- **Dónde**: `plan.md:289-290` (paso 2) y mutante 4 (`read_switch.active()`, `plan.md:324-325`),
  frente a «Posee» de F1-hook-entry (`plan.md:227`).
- **Por qué**: en su worktree, delivery-core no tiene ese módulo: sus tests no se pueden escribir ni
  correr hasta que se mezcle el otro lote, y el plan no fija la ruta, la forma del JSON ni la API.
- **Cambio**: fijar en el plan el contrato (`LOG_DIR/read-hook.json` =
  `{"active": true|false, "since": "<ISO>"}`; funciones `path()`, `active()`, `write(active)`).
  Delivery-core escribe y comprueba **el fichero**, no importa el módulo, y el mutante 4 asserta
  sobre el contenido del fichero. Un test de F1-hook-entry lee un fichero con esa forma exacta.

**N-4. Las condiciones para apartarse no coinciden con las del mod, y el latido no es de la sesión.**
- **Dónde**: decisión 10 (`plan.md:84-89`), F4-hooks-swap (`plan.md:771-777`) y F4-read-mod
  (`plan.md:733-734`).
- **Por qué**: (a) el mod actúa solo con `read_switch == "on"` (capa *bloquea*), pero el hook se
  aparta sin mirar esa capa. Con el interruptor *activo* y el bloqueo apagado (`off_variable`, el modo
  «solo registrar»), el hook se aparta y el mod no hace nada: se pierde el registro y se corta la
  serie. (b) El latido es un fichero por máquina con 24 h de vigencia. Una sesión cuyo mod no tiene
  `process.run` (otra superficie, un admin que lo veta) se apartaría por el latido de **otra** sesión,
  y se quedaría sin control.
- **Cambio**: (a) que el hook se aparte solo si el mod va a hacer exactamente lo mismo que habría
  hecho el hook con ese estado del interruptor; o que el mod también registre en el modo *activo*
  sin bloqueo. (b) Latido por `session_id` (el hook lo recibe en el payload): el hook se aparta solo
  si el latido de **su** sesión dice que el mod de lectura está activo y que `process.run` respondió.
  Tests `test_read_hook_does_not_step_aside_for_another_session` y
  `test_no_gap_when_active_but_not_blocking`. Mutante: ignorar el `session_id` → falla el primero.

**N-5. «`HASHED_HOOKS` cuenta el clasificador» contradice el guardián de huellas.**
- **Dónde**: F4-classifier, `plan.md:712-714`.
- **Por qué**: `tests/test_hook_boundaries.py:56-63` exige que `HASHED_HOOKS` sea **exactamente**
  la lista de scripts que llaman a `context_of(payload, __file__)`, y la línea 144 ata las claves de
  `hook_hashes_after.json` a esa tupla. `read_classifier.py` no estampa eventos: meterlo en
  `HASHED_HOOKS` pone la suite en rojo, y el lote no posee ni ese test ni el JSON.
- **Cambio**: que la huella de `read` y `shell` se calcule sobre el script **más** el clasificador
  dentro de `version_de`/`context_of`, sin tocar `HASHED_HOOKS`. Si se prefiere cambiar el guardián,
  añadir `tests/test_hook_boundaries.py` y `scripts/data/hook_hashes_after.json` a «Posee» de
  F4-classifier.

#### Menores

1. **El paso 6 del CI no vale con la vía B** (`plan.md:414` y `plan.md:875`):
   `<ld_bin> hook prompt` con `ld_bin` = `python` no ejecuta nada útil. Hay que escribirlo según la
   vía («la misma orden que declara `hooks.json`»).
2. **Codificación de la salida.** Con `-I`, Python ignora `PYTHONUTF8` y `PYTHONIOENCODING`. Medido
   aquí: con la salida en tubería, `sys.stdout.encoding` es `cp1252`. Los hooks imprimen
   `ensure_ascii=False` (`hook_common.py:118-126`). Un carácter fuera de cp1252 lanza una excepción,
   que el envoltorio se traga, y se pierde el aviso. El problema ya existe con los scripts de hoy,
   pero el envoltorio nuevo debería forzar UTF-8 en stdout (`reconfigure`), con el test
   `test_hook_output_is_utf8`.
3. **Coste de una bajada con la vía B**: con la 0.39, cada hook importa `local_delegate/__init__` de
   la 0.39, que carga el servidor (alrededor de 1 s), antes de fallar con 1. Además, cada llamada deja
   un error no bloqueante. No bloquea, pero hay que decirlo en la CHANGELOG y la wiki junto a «bajar
   exige `uninstall`».
4. **No hay forma de apagar la capa *activo* desde `install`**: el estado «nunca se pone a `false`»
   y no existe `--disable-read-hook`. Hay que escribir cuál es el camino para apagarla (opción nueva o
   `uninstall`), y si el apagado en caliente sigue siendo solo `block-off`.
5. **La lista de retire-seven-names se queda corta**: es probable que haga falta `legacy_names.py`,
   `config.py`, `checks.py`, `tests/test_wiki.py`
   (`test_the_deprecated_names_row_describes_the_0_38_behaviour`), `tests/test_retired_env_names.py`
   y `tests/test_environment_isolation.py` (`test_hooks_never_name_a_retired_name`). La regla del
   «grep del momento» lo cubre, pero conviene escribirlos ya, porque son libres en la ola 4.
6. **`test_install_and_update_share_one_orchestration` está en la ola 2a**, pero `update` no cambia
   hasta la 2b. Debería ir en F1-update, o limitarse en 2a a «`install` no reimplementa pasos».
7. **Faltan mutantes de la coordinación de F4**: no comprobar la vigencia del latido → falla
   `test_read_hook_acts_when_mod_off_or_stale`; y el de N-4.
8. **Dueños sin escribir en la ola 6**: el commit de F4-live que pone `read_mod_enabled=true` toca
   `plugin.json`, que no figura en ningún «Posee» de esa ola. Y el motivo «se apartó» en
   `blocks.jsonl` probablemente toca `hook_common.py` (`record`), que F4-hooks-swap no posee. No
   chocan, porque la ola va en serie, pero hay que escribirlos.

### Evidencia recomendada para el gate

- El plan con N-1…N-5 incorporados y las dos nuevas letras de REQ-003 y REQ-023 anotadas en la spec
  antes de la ola 1.
- La comprobación por programa de la disjunción de la ola 1, con el contrato de `read_switch` como
  única dependencia entre lotes.
