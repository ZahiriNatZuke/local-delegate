# Especificación: retirada de los nombres vencidos en la 0.38.0

Base: `main` en `6bbbfc5`, `pyproject.toml:3` = `0.37.0`. Insumos: [research.md](research.md)
(decisiones D1–D7, vinculantes), [research-code.md](research-code.md),
[research-upgrade.md](research-upgrade.md). Reglas comunes en [brief.md](brief.md).

## Contexto

El SDD `english-names-bilingual-output` renombró en la 0.35.0 un subcomando, una opción, cuatro
variables y un fichero interruptor, y prometió que los nombres viejos funcionarían con aviso en la
0.35.x, 0.36.x y 0.37.x y **se retirarían en la 0.38.0** (REQ-001, REQ-002, REQ-004, REQ-012 de
aquella spec). La doble escritura de `enfriamiento.json` (excepción de su REQ-005) vence a la vez, y
las tres variables del rol `fast` (`warn_until="0.37.0"`) dejan de avisarse.

Las 11 entradas de `DEPRECATED_NAMES` (`src/local_delegate/deprecations.py:51-91`) vencen en la
0.38.0 (`research-code.md` §1). Borrarlas sin más deja **fallos mudos**: el check de `doctor` y las
notas de `update` se construyen desde ese registro (`checks.py:1892-1953`, `update.py:345-351`); con
`LD_HOOK_READ_BLOQUEAR=1` puesto el bloqueo de lectura se apagaría sin aviso, y con el interruptor
viejo creado se encendería aunque la persona lo apagó (`research-upgrade.md` §1.3). La Mac, en la
0.34, salta directa a la 0.38 sin haber visto nunca un aviso (§1.4).

Este SDD **retira de verdad** lo vencido (ningún nombre viejo tiene efecto), sigue **avisando** de
lo que la persona dejó puesto, **migra** lo que el paquete ya gestiona y deja la release preparada.
La versión del paquete **no** se sube aquí: lo hace la PR de release después.

### Vocabulario

- **Nombre viejo / nombre nuevo**: los pares de la tabla de `research-upgrade.md` §0.
- **Retirado con sucesor**: entrada del registro con `kind="retired"` **y** `new` no nulo. No tiene
  efecto; existe solo para avisar y para migrar (D2).
- **Retirado sin sucesor**: `kind="retired"` y `new=None` (la clase que hoy usan las `_FAST`).
- **Clase efectiva**: `retired_from` si la entrada es un retirado con sucesor; `kind` en otro caso.
  Valores: `cli_command`, `cli_option`, `env_var`, `switch_file`.
- **Control positivo**: el nombre viejo ya no surte efecto **y** su gemelo nuevo sí, en la misma
  prueba y con los mismos datos, para que la prueba distinga.
- **HOME simulado**: `--home` fuera del HOME real (`install.is_simulated_home`).
- **Lectura dual**: los lectores de ficheros de datos y temporales con nombre o claves viejas (REQ-006
  y REQ-008 de la spec anterior). No tiene plazo (D5).

## Alcance

- Borrar del todo las tres `_FAST` y la doble escritura de `enfriamiento.json`, con su código muerto
  (D1).
- Convertir los otros 7 nombres en retirados con sucesor, con `warn_until="0.40.0"`, y cambiar la
  regla de clases de `deprecations.py` (D2).
- Dejar sin efecto cada nombre viejo en su superficie: CLI, `config`, hooks.
- Avisos en `doctor`, `local_status` y `update`, en es/en por el catálogo (D2).
- Error claro del CLI antes de argparse, con código 2 (D3).
- Migración en `update` e `install` del `env` de `~/.claude/settings.json` y del fichero interruptor
  (D4).
- Test de horizonte contra `"0.38.0"` sin subir la versión y `bump_version` robusto (D6).
- Detector de nombres en español, autocompletado y documentación (D7).

## Fuera de alcance

- Subir la versión, mover `[Unreleased]` a `[0.38.0]`, publicar o instalar: es la PR de release.
- Retirar la lectura dual de ficheros de datos y temporales (D5). La nota `waves/A5b-2.md:127` que
  hablaba de retirar la de `coste-agregados.json` queda descartada: manda el plan aprobado.
- Tocar variables de entorno del sistema, perfiles del shell, el lanzador del daemon, la tarea
  programada, `~/.claude/settings.local.json`, `~/.claude.json` o `~/.codex` (D4).
- Un aviso de `doctor` por `enfriamiento.json` huérfano: los hooks viejos ya los detecta
  `scaffold.hook_files` por versión, y el fichero es inocuo (`research-upgrade.md` §1.3).
- `lanzar-tanda-afinidad.ps1:30` (`LOCAL_DELEGATE_COMMIT_IDIOMA`, que nunca existió): backlog.
- Retirar el hook `anotar_llamada.py` y la skill `delegacion-local` de `install.py:113-126`: su
  retirada es permanente y no está en el registro.
- Una comprobación automática de excepciones sobrantes en `name_exceptions.json`: aquí solo se
  limpian las de estos nombres (REQ-021).

## Requisitos

### Registro y regla de clases

- **REQ-001 — Registro tras el cambio.** `DEPRECATED_NAMES` contiene **exactamente** 7 entradas,
  todas retiradas con sucesor, en este orden y con estos datos:

  | `old` | `new` | `retired_from` |
  |---|---|---|
  | `recalcular-coste` | `recompute-cost` | `cli_command` |
  | `--reiniciar-calibracion` | `--reset-calibration` | `cli_option` |
  | `LD_HOOK_READ_BLOQUEAR` | `LD_HOOK_READ_BLOCK` | `env_var` |
  | `LD_HOOK_READ_INTERRUPTOR` | `LD_HOOK_READ_SWITCH_FILE` | `env_var` |
  | `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` | `LOCAL_DELEGATE_STRUCTURED_SUMMARY` | `env_var` |
  | `LOCAL_DELEGATE_COSTE_RESPALDO` | `LOCAL_DELEGATE_COST_FALLBACK` | `env_var` |
  | `local-delegate-bloqueo-apagado` | `local-delegate-block-off` | `switch_file` |

  Todas con `kind="retired"`, `introduced="UNRELEASED"` (la PR de release la sella a `0.38.0`, así
  el aviso dice «desde la 0.38.0») y `warn_until="0.40.0"` (avisa en 0.38.x, 0.39.x y 0.40.x). No
  quedan las `_FAST` ni la entrada `legacy_write`. La tupla se escribe en varias líneas.

  *Verificación*: `tests/test_deprecations.py::test_registry_holds_exactly_the_seven_retired_names`
  compara el registro real con la tabla.

- **REQ-002 — Regla de clases.** `deprecations.py` admite tres clases y el docstring del módulo
  (`deprecations.py:10-19`) las describe:
  1. **Alias con sucesor**: `kind ∈ {cli_command, cli_option, env_var, switch_file}`, `new` no
     nulo, `warn_until=None`, `retired_from=None`. Vence en `introduced + 3 menores` (sin cambios).
  2. **Retirado sin sucesor**: `kind="retired"`, `new=None`, `retired_from=None`, `warn_until`
     obligatorio.
  3. **Retirado con sucesor** (nueva): `kind="retired"`, `new` no nulo, `retired_from` en el
     conjunto de la clase 1, `warn_until` obligatorio. Vence al pasar de la serie de `warn_until`,
     como un retirado.

  El campo nuevo `retired_from: str | None = None` va en `DeprecatedName`; `legacy_write` sale de
  `KINDS`. Una función `effective_kind(entry)` devuelve la clase efectiva. `deprecations` sigue sin
  importar nada del paquete.

  *Verificación*: `tests/test_deprecations.py::test_every_entry_follows_its_class_rule` (sustituye
  a la regla de `:45-54`) recorre el registro real **y** un registro sintético con un caso de cada
  clase y un caso inválido por regla (retirado con sucesor sin `retired_from`, alias con
  `warn_until`, `retired_from="retired"`), que debe rechazar. El test de imports de `:280-294` sigue
  verde.

- **REQ-003 — Lectores por clase efectiva.** `env_vars()`, `switch_files()` y una función nueva
  `cli_entries()` filtran por `effective_kind`, no por la forma del nombre (`_looks_env` desaparece
  si no le queda uso). Así un interruptor retirado sí lo ve el check y un subcomando retirado no se
  confunde con un fichero (`research-code.md` §4 b.2).

  *Verificación*: tests con registro sintético (monkeypatch de `DEPRECATED_NAMES`) en
  `tests/test_deprecations.py`: un alias y un retirado con sucesor de cada clase efectiva salen en su
  lector y en ningún otro.

- **REQ-004 — Texto del aviso.** `deprecation_notices.warning_text(entry)`:
  - retirado con sucesor publicado → clave nueva `cli.deprecations.retired_renamed`:
    es «{old} ya no tiene efecto desde la {version}: usa {new}», en «{old} has had no effect since
    {version}: use {new}»;
  - retirado con sucesor aún `UNRELEASED` → clave nueva `cli.deprecations.retired_renamed_unreleased`
    (es «{old} ya no tiene efecto: usa {new}»), por la misma razón que hoy existe
    `cli.deprecations.removed_later`: no imprimir nunca «UNRELEASED»;
  - retirado sin sucesor y alias: sin cambios (`cli.deprecations.retired`, `.deprecated`).

  *Verificación*: `tests/test_deprecations.py::test_warning_text_*` con entradas sintéticas de las
  tres clases, en es y en en (`i18n.override`); el texto contiene el viejo, el nuevo y la versión, y
  nunca `UNRELEASED`. Los guardianes de paridad de claves es/en y de textos fuera del catálogo siguen
  verdes.

### Retiradas completas (D1)

- **REQ-005 — Rol `fast`: fuera del todo.** Se borran las tres entradas `_FAST`,
  `config.RETIRED_FAST_ROLE_VARIABLES` (`config.py:293-297`), la pista `current_roles` del check
  (`checks.py:1952-1953`) y su clave `doctor.probe.deprecated_names.current_roles` en es/en, y la
  cita de `chains.py:23`. `config` deja de leer las tres variables (salen de
  `DEPRECATED_ENV_VALUES`, del inventario de aislamiento y de `ENVIRONMENT_VARIABLES`).
  - Se quedan las pruebas de que el rol no existe y de que pedir `model="fast"` da error claro
    (`tests/test_fast_role_retired.py:41-133`).

  *Verificación*: control positivo en `tests/test_fast_role_retired.py`, con el valor llegando por
  el fixture `reload_config` (`tests/test_fast_role_retired.py:41`) o por subproceso —nunca por
  `setenv` a secas, porque `DEPRECATED_ENV_VALUES` se calcula al importar (`config.py:290-292`)—,
  con `Context(home=tmp_path)` y `LD_HOOK_TELEMETRY_LOG` vacío: con solo `LOCAL_DELEGATE_MODEL_FAST`
  el check `config.deprecated_names` da `OK`; con `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` en las mismas
  condiciones da `WARN` (el check sigue mirando). Tests que cambian o se borran:
  `tests/test_deprecations.py:62-71` (`test_registry_holds_the_three_fast_role_variables_as_retired`,
  se borra), `:100-102` (`test_real_fast_variables_expire_in_0_38_0`, se borra: lo sustituye
  REQ-019), `tests/test_fast_role_retired.py:143-203` (avisos de las `_FAST`: se borran o se
  invierten a «`OK`»), `tests/test_chains.py:202-208` (deja de esperar
  `LOCAL_DELEGATE_FALLBACK_FAST`). El docstring de `checks.py:1896-1902` y el comentario de
  `config.py:280-289` dejan de hablar del rol `fast`.

- **REQ-006 — Doble escritura de `enfriamiento.json`: fuera del todo.** El daemon solo escribe
  `cooldown.json`. Se borran `cooldown._write_legacy` (`:298-307`), el parámetro `legacy_write`
  (`:126,136-139`), `legacy_write_enabled` (`:61-64`), `deprecations` del import de `cooldown.py:40`
  (se conservan `config` y `legacy_names` en esa línea) y `legacy_names.old_keys`
  (`legacy_names.py:603-610`); el docstring de `cooldown.py:14` y el comentario de `:53` dejan de
  hablar de `legacy_write`. Un `enfriamiento.json` que ya exista **no se borra ni se modifica**.

  *Verificación*: `tests/test_cooldown.py::test_the_daemon_never_writes_the_old_file`: tras
  `enter`, `reenter` y `clear` sobre un `LOG_DIR` temporal existe `cooldown.json` (gemelo) y **no**
  existe `enfriamiento.json`; con un `enfriamiento.json` previo, sus bytes no cambian. Se borran
  `test_dual_write_leaves_the_same_state…`, `test_the_old_file_carries_the_old_keys…` y
  `test_without_its_legacy_write_entry…` (`tests/test_cooldown.py:369-450`), que el test nuevo
  sustituye sin monkeypatch.

- **REQ-007 — La lectura dual se queda (D5).** Siguen intactos: `cooldown._legacy_path` y `_load`
  (`cooldown.py:130,258-264`), `hook_common.cooled_model` (`:592-608`), `legacy_names.FORMATS`,
  `normalize`, `read_key` y sus tablas, `COOLDOWN_EVENTS_FILE_NAMES`, `ATTRIBUTION_FILE_PREFIXES`,
  `COST_AGGREGATES_FILE_NAMES`, `EXCLUDED_WINDOWS_FILE_NAMES`, `QUOTA_STATUSLINE_FILE_NAMES`, los
  ficheros de afinidad y los temporales de hooks (`FILE_NAMES` `block_notes`, `call_notes_dir`,
  `health_prefix`; `legacy_block_notes_path`, `legacy_call_notes_dir`).

  *Verificación*: siguen verdes sin cambios `tests/test_cooldown.py::test_an_old_state_from_a_previous_daemon…`,
  `::test_with_both_files_the_new_one_wins`, `tests/test_hook_legacy_names.py:76-130` y los tests de
  `legacy_names`.

### Superficies que dejan de tener efecto

- **REQ-008 — CLI: error claro antes de argparse (D3).**
  - Se borran el subparser oculto `recalcular-coste`, la opción oculta `--reiniciar-calibracion`,
    `_warn_deprecated`, `cmd_recompute_cost_legacy`, la lectura de `legacy_reset_calibration` en
    `_resolve_reset_calibration` (que pasa a leer solo `args.reset_calibration`),
    `_HIDDEN_COMMANDS` y el filtro de `sub.metavar` que lo usaba, y la clave
    `cli.recompute_cost.reset_mismatch` en es/en.
  - `cli.run(argv)` comprueba `argv` **antes** de construir el parser, **solo contra los retirados
    con sucesor** (`entry.is_retired` y clase efectiva `cli_command`/`cli_option`, sacados de
    `deprecations.cli_entries()`); los alias vigentes **nunca** se rechazan, porque un alias
    funciona con aviso. Si el primer token que no empieza por `-` es el `old` de un retirado
    `cli_command`, o un token anterior a `--` es igual al `old` de un retirado `cli_option` o empieza
    por `old=`, escribe en `stderr` `cli.error` con `deprecation_notices.warning_text(entry)` y
    devuelve **2** sin ejecutar nada.
  - El camino de los dos ejecutables (`local_delegate:main` → `entrypoint.main`,
    `pyproject.toml:74-75`, `entrypoint.py:47`) pasa por el chequeo: `local-delegate-mcp
    recalcular-coste` también da 2.
  - `recompute-cost` y `--reset-calibration` no cambian. Ni `--help` ni el error de argparse para
    otros nombres listan los viejos.

  *Verificación*: `tests/test_retired_cli_names.py` (nuevo, sustituye a la parte CLI de
  `tests/test_cli_renamed_names.py`), con un espía sobre `recompute.run` y `--claude-dir` temporal
  siempre (el defecto es el `~/.claude` real, `cli.py:418`): `cli.run(["recalcular-coste"])` y
  `cli.run(["recompute-cost", "--reiniciar-calibracion", "five_hour"])` (y la forma `=`) devuelven 2,
  el `stderr` nombra el sucesor y el espía **no** se llama; gemelos con `recompute-cost` y
  `--reset-calibration five_hour` devuelven 0 y el espía **sí** se llama. Con registro sintético que
  lleva un **alias** `cli_command` vivo, el chequeo no lo rechaza. Un `cli.run(["noexiste"])` sigue
  dando el error de argparse y 2, y su lista `choose from` no contiene `recalcular-coste`. Hasta que
  L6 voltee las entradas reales, estas filas se prueban con registro sintético (las dos entradas
  como retiradas); L6 añade la aserción con el registro real y por `entrypoint.main`.
  `tests/test_cli_english.py:98-101,223,249` se ajustan.

- **REQ-009 — Variables del paquete.** `config` lee solo los nombres nuevos:
  `HOOK_READ_BLOCK`, `HOOK_READ_SWITCH_FILE`, `STRUCTURED_SUMMARY` y `COST_FALLBACK` pasan a los
  lectores normales (`config.py:248-256,308-311,548-549`). Desaparecen `_env_alias`,
  `_env_alias_str`, `_env_alias_flag` y `DEPRECATED_SEEN` (`config.py:69-101`).
  `DEPRECATED_ENV_VALUES` **sigue** leyendo los cuatro nombres viejos por la puerta `_read`, solo
  para avisar y sin efecto, y por eso siguen en el inventario de aislamiento. `config` no importa
  `deprecation_notices` (ciclo `config → deprecation_notices → i18n → config`).

  *Verificación*: control positivo de REQ-011, filas 4 y 5. Se borran los tests de `_env_alias` de
  `tests/test_deprecations.py:190-207`. `tests/test_density.py:163-164` y
  `tests/test_structured_summary.py:683` se ajustan al inventario resultante.

- **REQ-010 — Hooks: qué ven y qué no.** Los hooks instalados leen **solo** `LD_HOOK_READ_BLOCK`,
  `LD_HOOK_READ_SWITCH_FILE` y `~/.claude/local-delegate-block-off`.
  - **No ven** los nombres viejos: ni los aplican ni los detectan. Se borran de
    `resources/hooks/hook_common.py` `DEPRECATED_HOOK_NAMES`, `DEPRECATED_SEEN`, `env_alias`,
    `legacy_switch_path`, la rama que apaga con el interruptor viejo en `switch_on` y la clave
    `deprecated_names` de `record()` (`:101-104,286-343`). `switch_file` sale de `FILE_NAMES` en las
    dos copias (`hook_common.py:173-174`, `legacy_names.py:516-517`); el hook nombra el interruptor
    con una constante propia.
  - Se borran `DeprecatedName.used_by_hooks`, `deprecations.hook_names()` y el test de igualdad
    `tests/test_deprecations.py:170-176`, que quedan sin objeto.
  - **Siguen viendo** el enfriamiento por la lectura dual (REQ-007) y los temporales viejos.
  - El check de `doctor` sigue leyendo la cola de 7 días de la telemetría
    (`deprecated_names_in_hook_telemetry`): ahí solo llegan eventos de hooks 0.35–0.37 aún sin
    actualizar, y es justo el aviso que conviene en la transición.
  - Docstring de `resources/hooks/suggest_delegate_read.py:37`: sin el nombre viejo.

  *Verificación*: control positivo de REQ-011, filas 1–3, con el hook **instalado** en un HOME
  simulado. `tests/test_hook_legacy_names.py:67-73,132-145,195-212,248-293` se invierten; la cola de
  7 días con un evento sintético `deprecated_names: ["LD_HOOK_READ_BLOQUEAR"]` sigue dando `WARN` en
  el check. `tests/test_environment_isolation.py:192-212` se reescribe sin `hook_names()`.

- **REQ-011 — Control positivo por superficie.** Cada nombre viejo deja de tener efecto **y** su
  gemelo nuevo sí, con los mismos datos:

  | # | Superficie | Nombre viejo → resultado | Gemelo nuevo → resultado | Test |
  |---|---|---|---|---|
  | 1 | hook instalado | `LD_HOOK_READ_BLOQUEAR=1` solo → `block_state()` = `off_variable` | `LD_HOOK_READ_BLOCK=1` → `on` | `tests/test_hook_legacy_names.py` |
  | 2 | hook instalado | `LD_HOOK_READ_BLOCK=1` + `LD_HOOK_READ_INTERRUPTOR=<fichero existente>` → `on` | `LD_HOOK_READ_SWITCH_FILE=<mismo fichero>` → `off_file` | ídem |
  | 3 | hook instalado | `LD_HOOK_READ_BLOCK=1` + `~/.claude/local-delegate-bloqueo-apagado` → `on` | `~/.claude/local-delegate-block-off` → `off_file` | ídem |
  | 4 | `config` en proceso nuevo | `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO=1` → `STRUCTURED_SUMMARY is False` | `LOCAL_DELEGATE_STRUCTURED_SUMMARY=1` → `True` | `tests/test_retired_env_names.py` (nuevo) |
  | 5 | `config` en proceso nuevo | `LOCAL_DELEGATE_COSTE_RESPALDO=x` → `COST_FALLBACK == ""` | `LOCAL_DELEGATE_COST_FALLBACK=x` → `"x"` | ídem |
  | 6 | CLI | `recalcular-coste` → 2, sin escribir | `recompute-cost` → 0 | `tests/test_retired_cli_names.py` |
  | 7 | CLI | `--reiniciar-calibracion five_hour` → 2 | `--reset-calibration five_hour` → aceptada | ídem |
  | 8 | daemon | enfriamiento → no existe `enfriamiento.json` | existe `cooldown.json` | `tests/test_cooldown.py` |
  | 9 | `doctor` | solo `_FAST` → `OK` | variable retirada con sucesor → `WARN` | `tests/test_fast_role_retired.py` |

  «Proceso nuevo» = subprocess o el helper de recarga que ya usan los tests de `config` (`_env*`,
  PR #135). *Verificación*: cada fila es un test con dos aserciones (viejo y gemelo); una fila sin
  gemelo no cuenta. `tests/test_cli_renamed_names.py` desaparece al final (su contenido queda
  repartido en estos ficheros).

### Avisos (D2)

- **REQ-012 — `doctor`.** El check `config.deprecated_names` conserva id, grupo y lugar (los **25
  checks** que cuenta `tests/test_wiki.py:47` no cambian). Mira, como hoy, cuatro sitios: la shell
  donde corre `doctor`, el bloque `env` de `~/.claude/settings.json`, ficheros en `~/.claude/` y la
  cola de 7 días de `LD_HOOK_TELEMETRY_LOG` (`checks.py:1922-1943`).
  - Para un retirado con sucesor encontrado ahí da `WARN` con `warning_text(entry)` y la pista
    `rename` («renombra {old} a {new}»). La pista `remove` queda para los retirados sin sucesor. Sin
    nombres retirados: `OK` como hoy. Avisa hasta la 0.40.x (lo garantiza REQ-019).
  - **Telemetría ya migrada**: la rama de telemetría ignora los eventos de un nombre con `ts`
    anterior o igual a la fecha **de ese nombre** en el registro de migración de REQ-015
    (`retired-names-migration.json`, una fecha por nombre). El check lo lee del mismo directorio de
    datos que lo escribe (`ctx.log_dir` o, si no hay, la regla de REQ-015). Un evento posterior a la
    migración sigue avisando.
  - **`settings.json` ilegible** (no es JSON, no es UTF-8, o lleva BOM, que el lector actual
    `checks.read_json` no admite: fallo previo, ver «Hallazgos para el backlog»): el check ya no lo
    ignora en silencio (`checks.py:1928`, `_reason`): añade una advertencia «no se
    pudo leer el env de settings.json: {reason}» y da `WARN` aunque no haya otros nombres.

  *Verificación*: `tests/test_checks.py` (junto a `:1926-1960`, registro sintético) con cuatro casos:
  variable en shell, clave en `env` de `settings.json`, interruptor en `~/.claude` y evento de
  telemetría; cada uno da `WARN`, el texto nombra viejo y nuevo y la pista es `rename`. Telemetría:
  evento en `t0`, registro de migración en `t1 > t0` con ese nombre → sin advertencia de telemetría;
  evento en `t2 > t1` → advertencia (control); registro de migración con **otro** nombre → el evento
  de `t0` sigue avisando; dos migraciones sucesivas de nombres distintos conservan la fecha de los
  dos. `settings.json` no JSON → `WARN` con el motivo. Un caso con el registro
  **real** y `LD_HOOK_READ_BLOQUEAR` en el `env` de un `settings.json` sembrado (HOME simulado),
  en L6. `tests/test_wiki.py` sigue contando 25.

- **REQ-013 — `local_status`.** `server._describe_deprecated_names` lista los retirados con sucesor
  cuyo nombre viejo tiene valor en el entorno **de este proceso** (`config.DEPRECATED_ENV_VALUES`),
  con `warning_text(entry)`. Es el único sitio que ve el entorno del daemon (su lanzador) y del
  servidor MCP por stdio. La cabecera `mcp.status.deprecated` cambia en es/en a «Nombres retirados
  puestos en el entorno de este proceso (sin efecto):» / «Retired names set in this process's
  environment (no effect):». Nunca imprime el valor de la variable.

  *Verificación*: `tests/test_retired_env_names.py::test_local_status_lists_a_retired_variable`:
  con `LOCAL_DELEGATE_COSTE_RESPALDO=secret-value` llegando por `reload_config` (no por `setenv` a
  secas), la salida de `local_status` nombra el viejo y el nuevo y **no** contiene `secret-value`;
  sin la variable, no hay sección.

- **REQ-014 — `update`: orden fijo migrar → checks → notas.**
  1. `run_update` llama a `install.plan_retired_name_migration(opts.home)` **fuera** de
     `plan_repairs` (sin pasar por su deduplicación por `(kind, target)`, `update.py:341-348`) y la
     aplica **antes** de `checks.run_all` (`update.py:862-863`). En `--dry-run` solo la muestra.
  2. Corre los checks y planifica las reparaciones como hoy.
  3. Las notas pasan la pista del check (`update.py:345-351`) quitando **solo** el «renombra» que
     la migración de esta corrida cubre en el `env` de `settings.json` o en el interruptor de
     `~/.claude/` (aplicada o, en `--dry-run`, planificada). La pista de un nombre que además está en
     la **shell** (que no se migra) se conserva.
  4. Los fallos de la migración se suman a `failures` (`update.py:897-913`): si falla, `update` sale
     con 1.

  *Verificación*: `tests/test_update.py::test_update_migrates_before_reporting`: HOME simulado con
  `LD_HOOK_READ_BLOQUEAR` en `env`; tras `run_update` (y también con `--dry-run`), las notas no
  contienen «renombra LD_HOOK_READ_BLOQUEAR» y la salida contiene la línea de migración; con el
  mismo nombre también en la shell (`reload_config`), la pista de la shell sigue en las notas; con
  una acción de migración que falla, `update` sale con 1.
  `::test_migration_and_hook_repair_both_survive`: mismo HOME con nombres viejos en `env` **y**
  hooks desactualizados en `settings.json`; tras `update`, `env` tiene el nombre nuevo **y** el
  registro de hooks es el de la versión actual (ninguna de las dos escrituras se pierde).

### Migración en `update` e `install` (D4)

- **REQ-015 — Qué migra.** Una función `install.plan_retired_name_migration(home)` devuelve
  `install.Action` con un **`kind` propio** (`migrate`), nunca `settings`, cuyo `run` **relee**
  `settings.json` en el momento de aplicar (como `_run_settings`, `install.py:1875-1879`), para
  combinarse con cualquier otra escritura de la corrida. Migra **solo retirados con sucesor**: un
  alias vigente no se toca, porque aún funciona.
  - Bloque `env` de `<home>/.claude/settings.json`, por cada retirado con sucesor de clase efectiva
    `env_var`:
    - viejo presente y nuevo ausente → la clave pasa a llamarse como el nuevo, con el **mismo
      valor** y en la **misma posición**;
    - viejo y nuevo presentes → se quita el viejo (ya ganaba el nuevo).
  - Fichero `<home>/.claude/<old>` de cada retirado con sucesor de clase efectiva `switch_file`:
    - viejo existe y nuevo no → se renombra al nuevo;
    - existen los dos → se borra el viejo;
    - si es un directorio o un enlace, no se toca.
  - El **contenido** del resto de `settings.json` no cambia (igualdad JSON: hooks, permisos, el
    resto de `env`); el formato sí puede cambiar, porque `_write_json` reescribe con `indent=2`
    (`install.py:269-274`). Se conserva el fin de línea; un fichero con BOM se lee (`utf-8-sig`) y se
    escribe conservando el BOM (lo deja así PowerShell 5.1 con `-Encoding UTF8`). Esto lo garantiza
    **la migración**; que `doctor` (`checks.read_json`) e `install._read_json` no lean el BOM, y que
    por eso la reparación de hooks reescriba `settings.json`, es un fallo previo fuera de alcance
    («Hallazgos para el backlog»).
  - **Copia propia**: solo si esta corrida **escribe** `settings.json` (no cuando solo se renombra
    el interruptor ni cuando el `env` es ilegible), antes de escribir copia `settings.json` a
    `settings.json.retired-names.bak`; si ya existe, a
    `settings.json.retired-names.<AAAAMMDDhhmmss>.bak` en **UTC**, y si también existe, con sufijo de
    desempate `-1`, `-2`…; la copia se crea con apertura exclusiva (`open(…, "xb")`). Nunca pisa una
    copia previa, ni dentro del mismo segundo.
    La copia conserva los permisos del original (`shutil.copymode` tras la apertura exclusiva) y contiene el `env` completo (puede
    llevar claves): la salida de la migración lo dice y el CHANGELOG también.
  - **Registro de migración**: al aplicar (nunca en `--dry-run`), escribe
    `retired-names-migration.json` en el **directorio de datos de la migración**, calculado con la misma regla que `install.language_dir` (`install.py:1592-1603`) y `completion_dir`: con un HOME simulado nunca es el `LOG_DIR` real salvo `data_dir` o `LOCAL_DELEGATE_LOG_DIR` explícitos. Guarda **una fecha UTC por nombre**
    (`{"names": {"<viejo>": "<ts>"}}`, sin valores) y **fusiona** con lo que ya hubiera. Si no hay
    directorio de datos permitido, migra igual, no escribe el registro y lo dice. Lo usa el check
    (REQ-012). La función recibe el directorio de datos (o el `install.Options`), no lo saca de
    `config.LOG_DIR`.
  - Todas las claves viejas se migran en **una sola** acción sobre `settings.json`. La función vive
    en `install.py` para no abrir un ciclo `install ↔ <módulo nuevo>` (`py/cyclic-import`).

  *Verificación*: `tests/test_install.py::test_retired_name_migration_*` sobre HOME simulado y
  registro sintético con retirados (y con el real en L6): (a) solo viejo → renombrado con su valor y
  `json.loads` igual salvo esa clave, orden de claves de `env` intacto; (b) los dos → queda el nuevo
  con su valor; (c) interruptor solo viejo → existe el nuevo y no el viejo; (d) los dos interruptores
  → queda solo el nuevo; (e) existe `settings.json.retired-names.bak` con los bytes originales, y una
  segunda migración (nombre viejo puesto de nuevo a mano) crea una copia con fecha sin pisar la
  primera; (f) un `settings.json` en CRLF sigue en CRLF; (g) con BOM, se migra y conserva el BOM;
  (h) un alias vigente en el registro sintético no se migra; (i) registro de migración con una
  fecha por nombre, sin valores, y fusión en una segunda migración; (j) con HOME simulado y **sin**
  `LOCAL_DELEGATE_LOG_DIR`, el `LOG_DIR` real (con `monkeypatch`) no recibe el registro; (k) si solo
  se renombra el interruptor o el `env` es ilegible, no aparece ninguna `.bak`; (l) tres migraciones
  en el mismo segundo dejan tres copias distintas.

- **REQ-016 — Cuándo corre.**
  - `update` la aplica **siempre**, como primer paso (REQ-014).
  - `install` la planifica cuando el cliente Claude Code está en el plan, **antes** de cualquier otra
    acción sobre `settings.json`.
  - `--dry-run` la muestra y no escribe nada.
  - Es idempotente: una segunda corrida no planifica nada.
  - Si `settings.json` no es JSON válido, no es UTF-8 o su `env` no es un objeto, **la migración no
    escribe nada en él** y lo dice (clave propia en `install.json`, con el motivo); el interruptor se
    migra igual y la corrida no falla por esto. Lo que hagan en la misma corrida otras acciones
    previas (la reparación de hooks sobrescribe hoy un `settings.json` ilegible) queda fuera de
    alcance: hallazgo para el backlog.

  *Verificación*: `tests/test_update.py::test_retired_name_migration_dry_run_writes_nothing`
  (bytes de `settings.json` y del interruptor idénticos tras `--dry-run`; **no** existen
  `retired-names-migration.json` ni `settings.json.retired-names*.bak`, en `update` y en `install`;
  la acción aparece en la salida), `::test_retired_name_migration_is_idempotent`, `::test_unreadable_settings_is_left_alone`
  (aislando la migración: sin reparación de hooks en el plan; bytes idénticos y el mensaje con el
  motivo); `tests/test_install.py::test_install_plans_the_migration_for_claude` y su caso sin
  Claude.

- **REQ-017 — Límites y datos sensibles.**
  - Nunca toca variables de entorno del sistema, perfiles del shell, el lanzador del daemon,
    `settings.local.json`, `~/.claude.json`, los `.claude/settings*.json` de proyecto ni `~/.codex`.
  - Qué se ve de lo que no migra: una variable en la shell donde corre `doctor` la avisa `doctor`
    (REQ-012); el entorno del daemon (su lanzador) y del servidor MCP por stdio, `local_status`
    (REQ-013). `settings.local.json`, `~/.claude.json` y los `settings` de proyecto **no los mira
    nadie**: lo dice el CHANGELOG (REQ-023). No se amplía el alcance para mirarlos.
  - La descripción y el `literal` de la acción (lo que imprime `--dry-run`) muestran **solo
    nombres** («LD_HOOK_READ_BLOQUEAR → LD_HOOK_READ_BLOCK»), nunca valores: el `env` puede
    contener claves.

  *Verificación*: test con `env` = `{"LOCAL_DELEGATE_COSTE_RESPALDO": "s3cr3t-value", "OTHER": "x"}`:
  la salida de `update --dry-run` y de `install --dry-run` no contiene `s3cr3t-value`; tras
  `update`, `OTHER` sigue igual. Test que distingue: con los nombres viejos en `os.environ` y **no**
  en `settings.json` ni en `~/.claude/`, el plan de migración sale vacío.

- **REQ-018 — Textos.** Los textos de la migración (descripción de acción, resumen de `update`,
  `settings.json` ilegible, aviso de la copia con el `env`) van en
  `resources/i18n/{es,en}/install.json`; la advertencia de `settings.json` ilegible del check, en
  `doctor.json`. En las dos lenguas.

  *Verificación*: guardianes de paridad de claves y de textos fuera del catálogo verdes; un test en
  `tests/test_update.py` con `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en` comprueba la línea en inglés.

### Release y guardianes (D6)

- **REQ-019 — Horizonte contra la 0.38.0 sin subir la versión.**
  - `test_registry_has_nothing_overdue_in_0_38_0`: `overdue("0.38.0") == []` con el registro real.
  - `test_the_0_38_0_bump_keeps_the_registry_valid`: lee `deprecations.py` normalizando a LF (como
    `bump_version._read`, `scripts/bump_version.py:117-124`), aplica
    `bump_version.stamp_unreleased(texto, "0.38.0")`, escribe el resultado en `tmp_path` y lo
    **carga como módulo de verdad** con `importlib.util.spec_from_file_location` +
    `module_from_spec`, registrándolo en `sys.modules` (`monkeypatch.setitem`) antes de
    `exec_module`, como `bump_version._hook_common` (`scripts/bump_version.py:82-89`). Un `exec` en un
    diccionario suelto revienta con `@dataclass` y `from __future__ import annotations`. Comprueba:
    las 7 entradas quedan con `introduced="0.38.0"`; `overdue("0.38.0")`, `overdue("0.39.5")` y
    `overdue("0.40.9")` dan `[]`; **control positivo**: `overdue("0.41.0")` devuelve los 7 nombres;
    y `warning_text` de una entrada sellada contiene «0.38.0».
  - `test_the_0_38_0_changelog_still_announces_every_entry`: sobre una copia en memoria del
    `CHANGELOG.md` real con `## [Unreleased]` renombrado a `## [0.38.0]`, `changelog_problems`
    (`tests/test_deprecations.py:126-143`) con las entradas selladas da `[]`.
  - El guardián existente `test_horizon_no_deprecated_name_is_overdue_in_the_current_version` no
    se toca.

  *Verificación*: los tres tests en `tests/test_deprecations.py`. Un mutante que ponga
  `warn_until="0.37.0"` en una entrada debe hacer fallar el primero (se prueba en el lote y se
  anota en la PR).

- **REQ-020 — `bump_version` robusto.** `scripts/bump_version.py::stamp_unreleased`
  (`:213-227`) y `plan()` funcionan con el registro escrito como `= ()` en una línea, `= (\n)`, una
  tupla multilínea sin ninguna entrada `UNRELEASED` y una con varias: en los tres primeros casos
  devuelve el texto sin cambios, en el último sella todas y ninguna otra cadena fuera de la tupla.

  *Verificación*: casos nuevos en `tests/test_deprecations.py` (junto a `:257-278`, fixture
  sintética) para los cuatro formatos; el de `= ()` falla hoy con `BumpError` (control de que el
  test discrimina).

- **REQ-021 — Detector de nombres en español.** La suite queda verde en cada lote: los tests sacan
  el nombre viejo del registro (`deprecations.find`/recorrido por `new`) en vez de escribirlo
  literal donde se pueda; donde haga falta un literal, el lote que lo escribe **añade** su pareja
  (nombre, fichero) a `scripts/data/name_exceptions.json` con el motivo nuevo (fichero compartido
  solo para añadir). Al cerrar, en L6:
  - se quitan las entradas de estos nombres que ya no casan con ningún hallazgo;
  - las de `enfriamiento.json` que siguen haciendo falta por la lectura dual (`hook_common.py`,
    `test_cooldown.py`, `test_fallback.py`, `test_f1_conformance.py`) cambian su motivo a «lectura
    de formato viejo (REQ-006 de english-names-bilingual-output)»; la de `scripts/build_corpus.py`
    (dato congelado) se queda;
  - los 7 nombres que siguen apareciendo (registro, migración, tests de retirada) llevan el motivo
    nuevo «nombre retirado con sucesor: sin efecto desde la 0.38.0, avisa hasta la 0.40.x», que se
    añade como enmienda a la lista de motivos de `scripts/data/name_exceptions.README.md`.
  - `scripts/_claude_bench.py:11`: docstring sin el nombre viejo.

  *Verificación*: `tests/test_detect_spanish_names.py::test_repo_has_no_spanish_name_outside_the_exception_list`
  verde; la PR adjunta la lista de excepciones de estos nombres que ya no casaban y se quitaron
  (salida de `scripts/detect_spanish_names.py` antes y después).

- **REQ-022 — Autocompletado.** Ni el modelo ni los tres scripts ofrecen `recalcular-coste` ni
  `--reiniciar-calibracion`. `completion.py` oculta los nombres de `deprecations.cli_entries()`
  (clase efectiva CLI, alias y retirados), de modo que el mecanismo sigue sirviendo para un alias
  futuro (que se oculta en el autocompletado pero funciona, REQ-008).

  *Verificación*: `tests/test_completion_model.py:148-159` y
  `tests/test_completion_render.py:256-262` cuentan con `cli_entries()` (siguen siendo ≥ 2 con el
  registro real) y, para los retirados, comprueban que el nombre **no** está en el parser **ni** en
  el modelo/script; para los alias, el test sintético de `test_completion_model.py:186-200` sigue
  comprobando que se ocultan.

### Documentación (D7)

- **REQ-023 — CHANGELOG, README y wiki.**
  - `CHANGELOG.md` `[Unreleased]`: entradilla con marca de **incompatible** y la sección «Lo que
    rompe y cómo actualizar», con el formato en español de la 0.35.0/0.36.0 y el estilo de la
    retirada de `fast` (0.30.0, `CHANGELOG.md:986-1006`): tabla «Qué deja de funcionar» con las
    ocho filas de `research-upgrade.md` §0 (viejo → nuevo → qué pasa si sigue puesto), un «Qué
    notas si aún usas un nombre viejo» por grupo, las líneas de §3.3 (correr `doctor` antes;
    quien salta desde la 0.34 revisa `env`, perfil y lanzador; interruptor nuevo con su comando;
    `enfriamiento.json` deja de escribirse y `update` cambia los hooks viejos; las `_FAST` dejan de
    avisarse; la lectura de datos viejos no cambia) y una línea de lo que migra `update`/`install`
    y lo que no. La sección `[0.35.0]` no se toca.
  - `README.md:121-123`: el aviso pasa a pasado y dice que `doctor` nombra lo que sigue puesto y
    `update` migra lo que puede.
  - `docs/wiki/Configuration.md`: `:38`, `:122-125`, `:212`, `:541`, `:555-560`, `:566-568` y la
    sección `:588-609`, que pasa a «Nombres retirados en la 0.38.0» con la tabla como referencia
    y la migración de `update`.
  - `docs/wiki/Configuration.md:39` (lista `_FAST` con su tope `12000`) y
    `docs/wiki/Troubleshooting.md:92` (cita `…/_FAST/…` como rol vigente): sin las `_FAST`.
  - `docs/wiki/Integration-install.md:453`: fila del check sin las `_FAST` y con el comportamiento
    0.38.
  - `docs/recipes/claude-code-hooks.md:62-63` y, si hace falta, `docs/wiki/Architecture.md:188`.
  - En el CHANGELOG, además: lo que **no** mira nadie (`settings.local.json`, `~/.claude.json`,
    `settings` de proyecto, REQ-017), que la copia `settings.json.retired-names*.bak` contiene el
    `env` completo y se puede borrar, y que `local_status` es quien avisa del entorno del daemon.

  *Verificación*: `tests/test_deprecations.py::test_each_entry_matches_the_changelog_section_that_announces_it`
  (con `introduced="UNRELEASED"` exige viejo y nuevo de cada entrada en `[Unreleased]`),
  `tests/test_wiki.py` verde con un assert nuevo: la fila del check en `Integration-install.md` no
  nombra ninguna `_FAST` y dice «ya no tiene efecto»;
  `git grep -nE "0\.37\.x|hasta la 0\.37|siguen funcionando con aviso|_FAST" README.md docs/` sin
  resultados.

### Calidad

- **REQ-024 — Calidad y límites del cambio.**
  - Código, identificadores y claves en inglés; textos al usuario por el catálogo es/en.
  - Sin dependencias nuevas.
  - `pyproject.toml` sigue en `0.37.0` al terminar el SDD.
  - Fin de línea de cada fichero conservado (`git ls-files --eol`).
  - Suite completa verde y CodeQL a **0** alertas abiertas en cada PR, incluidas las `note`
    (`py/unused-import`, `py/cyclic-import`), con los hilos resueltos.
  - Sin código muerto de lo retirado, con límite de palabra y símbolos calificados para que pueda
    dar 0 de verdad (hay `old_keys` y `packaged_hook_names` legítimos en otros sitios):
    `git grep -nwE "_env_alias(_str|_flag)?|DEPRECATED_SEEN|env_alias|legacy_switch_path|_write_legacy|legacy_write_enabled|RETIRED_FAST_ROLE_VARIABLES|_HIDDEN_COMMANDS|reset_mismatch|current_roles|used_by_hooks|DEPRECATED_HOOK_NAMES|_looks_env" -- src scripts tests`
    y `git grep -nE "legacy_names\.old_keys|def old_keys|deprecations\.hook_names|def hook_names|\"legacy_write\"" -- src scripts tests`
    dan 0. Los motivos en prosa de `name_exceptions.json` que nombran `legacy_write` los reescribe
    REQ-021 (por eso el patrón no mira `scripts/data/`).

  *Verificación*: `bash ~/.claude/scripts/pesado.sh uv run pytest -n 2` verde;
  `gh pr checks <n>` y `gh api "repos/ZahiriNatZuke/local-delegate/code-scanning/alerts?ref=refs/pull/<n>/merge&state=open"`
  vacío; el `git grep` anterior en el lote de cierre.

- **REQ-025 — Verificación en vivo sin tocar nada real.** Con el código del último lote, sobre un
  HOME simulado, con `LOCAL_DELEGATE_LOG_DIR` temporal **exportado en todos los pasos**,
  `LD_HOOK_TELEMETRY_LOG` vacío, sin ninguno de los 7 nombres viejos en la shell (comprobado solo por
  nombre), `--claude-dir "$H/.claude"` donde la orden lo admita y la versión explícita en `update`
  para no salir a PyPI:
  1. se siembra `<home>/.claude/settings.json` con `env` que lleva `LD_HOOK_READ_BLOQUEAR=1`,
     `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO=1`, `LOCAL_DELEGATE_COST_FALLBACK=a` **y**
     `LOCAL_DELEGATE_COSTE_RESPALDO=b`, más una clave ajena; y `<home>/.claude/local-delegate-bloqueo-apagado`;
  2. `doctor --home` da `WARN` en `config.deprecated_names` con los cuatro nombres y pista `rename`;
  3. `update --home … --no-restart --dry-run` lista las acciones, no escribe nada (hash de los
     ficheros igual antes y después) y no imprime ningún valor;
  4. `update --home … --no-restart` migra: `env` con `LD_HOOK_READ_BLOCK=1`,
     `LOCAL_DELEGATE_STRUCTURED_SUMMARY=1`, `LOCAL_DELEGATE_COST_FALLBACK=a`, sin viejos, clave ajena
     intacta, `settings.json.retired-names.bak` igual al fichero sembrado, interruptor renombrado;
  5. `doctor --home` ya no avisa de esos nombres; una segunda `update` no planifica migración;
  6. `local-delegate recalcular-coste` sale con 2 y nombra `recompute-cost`.

  No se toca el daemon, la tarea programada, `~/.claude*` real ni variables del usuario.

  *Verificación*: registro en `verification.md` con los comandos, las salidas relevantes (sin
  valores) y los hashes; comprobación final de que el `~/.claude/settings.json` real no cambió (hash
  antes y después).

## Escenarios de aceptación

### Escenario: el bloqueo no se apaga en silencio (Mac que salta de 0.34 a 0.38)

- **Given** un `settings.json` con `env.LD_HOOK_READ_BLOQUEAR = "1"` y hooks 0.34 instalados
- **When** la persona corre `local-delegate update` con la 0.38
- **Then** `env` pasa a `LD_HOOK_READ_BLOCK = "1"`, queda `settings.json.retired-names.bak`, los hooks pasan a la
  0.38 y el bloqueo sigue encendido; `update` informa de la migración (REQ-014, REQ-015).

### Escenario: el interruptor apagado sigue apagado

- **Given** existe `~/.claude/local-delegate-bloqueo-apagado` y no el nuevo, con `LD_HOOK_READ_BLOCK=1`
- **When** corre `update`
- **Then** existe `~/.claude/local-delegate-block-off`, el viejo no, y el hook da `off_file`.

### Escenario: variable vieja en el lanzador del daemon

- **Given** el lanzador exporta `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO=1`
- **When** el daemon 0.38 arranca y la persona pide `local_status`
- **Then** el resumen estructurado está apagado, `local_status` dice «LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO
  ya no tiene efecto desde la 0.38.0: usa LOCAL_DELEGATE_STRUCTURED_SUMMARY» y el lanzador no se
  toca (REQ-009, REQ-013, REQ-017).

### Escenario: subcomando viejo en una tarea programada

- **Given** una tarea que corre `local-delegate recalcular-coste`
- **When** se ejecuta con la 0.38
- **Then** sale con 2, `stderr` dice «error: recalcular-coste ya no tiene efecto desde la 0.38.0: usa
  recompute-cost» y no se recalcula nada (REQ-008).

### Escenario: las dos claves en `env`

- **Given** `env` con `LOCAL_DELEGATE_COST_FALLBACK=a` y `LOCAL_DELEGATE_COSTE_RESPALDO=b`
- **When** corre `update`
- **Then** queda solo `LOCAL_DELEGATE_COST_FALLBACK=a` (REQ-015 b).

### Escenario: `--dry-run`

- **Given** el `settings.json` del primer escenario
- **When** corre `update --dry-run`
- **Then** la salida lista «LD_HOOK_READ_BLOQUEAR → LD_HOOK_READ_BLOCK», ningún fichero cambia y no
  aparece ningún valor de `env` (REQ-016, REQ-017).

### Escenario: `settings.json` roto

- **Given** un `settings.json` que no es JSON válido y el interruptor viejo
- **When** corre `update`
- **Then** **la migración** no escribe en `settings.json` y dice por qué, el interruptor se migra y
  `update` no falla por esto (REQ-016). (Si en la misma corrida se reparan hooks, esa otra acción
  sobrescribe hoy un JSON ilegible: hallazgo previo, fuera de alcance, para el backlog.)

### Escenario: `_FAST` olvidada

- **Given** `LOCAL_DELEGATE_MODEL_FAST` en la shell, ningún otro nombre viejo y sin telemetría
- **When** corre `doctor`
- **Then** `config.deprecated_names` da `OK` (REQ-005).

### Escenario: release

- **Given** este SDD mezclado con `pyproject.toml` en `0.37.0`
- **When** la PR de release corre `bump_version 0.38.0`
- **Then** las 7 entradas quedan con `introduced="0.38.0"`, el guardián de horizonte pasa y el aviso
  dice «desde la 0.38.0» (REQ-019, REQ-020).

## Casos límite y fallos

- `env` con el nombre viejo con valor vacío: se migra igual (el valor se conserva tal cual).
- Interruptor viejo que es un directorio o un enlace: no se toca; `doctor` sigue avisando.
- Fallo al escribir `settings.json` (permisos): la acción falla como las demás de `install.apply`,
  cuenta en `failures` y no deja el fichero a medias (`_write_json` escribe de una vez).
- Token `recalcular-coste` como valor de otra opción (`--label recalcular-coste`): no dispara el
  chequeo de REQ-008, que solo mira el primer token posicional para subcomandos.
- `--reiniciar-calibracion` como **valor** de otra opción (`--label --reiniciar-calibracion`): sí
  dispara el chequeo (sale con 2). Se acepta: es improbable y el mensaje es claro.
- Abreviatura de la opción vieja (`--reiniciar`): no dispara el chequeo; cae en el error genérico de
  argparse con código 2. Se acepta.
- Eventos de telemetría de hooks viejos tras migrar: no piden «renombra» para los nombres
  migrados (REQ-012); uno posterior a la migración sí avisa.
- `settings.json` con BOM: la migración lo lee y lo conserva (REQ-015); el check no lo puede leer
  (fallo previo) y lo dice (REQ-012); la reparación de hooks de la misma corrida puede reescribirlo
  (fallo previo, backlog).
- `update --home <simulado>` sin `LOCAL_DELEGATE_LOG_DIR`: el registro de migración no va al
  `LOG_DIR` real (REQ-015).
- `local-delegate-mcp` con argumentos reenvía a `cli.run`: el chequeo de REQ-008 aplica igual.

## Requisitos no funcionales

- **Seguridad y privacidad**: ningún valor de `env` ni de variables sale en salidas, logs,
  telemetría ni evidencias (REQ-013, REQ-017).
- **Compatibilidad**: Python ≥ 3.11 (`pyproject.toml:6`), sin `deprecated=` de argparse (3.13).
- **Operabilidad**: toda escritura sobre ficheros del usuario deja copia y es visible en
  `--dry-run`.

## Hallazgos para el backlog (fuera de alcance)

1. **La reparación de hooks sobrescribe un `settings.json` ilegible**: `_run_settings` hace
   `merge_hook_settings(_read_json(path), …)` y `_read_json` devuelve `{}` con un JSON inválido
   (`install.py:261-266`, `:1875-1877`); queda solo la `.bak` genérica.
2. **BOM en `settings.json`**: `checks.read_json` (`checks.py:483-498`) e `install._read_json`
   (`install.py:261-266`) no leen un fichero con BOM; `doctor` dice que no puede leerlo y la
   reparación de hooks de la misma corrida lo reescribe solo con los hooks (perdería también la
   migración). La migración sí lo soporta (REQ-015).

## Desviaciones y decisiones de redacción

1. **Los hooks no detectan los nombres viejos** (REQ-010). `research-upgrade.md` §1.5.1 proponía que
   el hook siguiera detectándolos (sin aplicarlos) para alimentar la cola de telemetría. No se
   adopta: `doctor` ya mira la shell, el `env` de `settings.json` (de donde heredan los hooks) y
   `~/.claude/`, y la migración resuelve los dos últimos; mantener detección en el hook obliga a
   conservar la copia `DEPRECATED_HOOK_NAMES` y su test de igualdad solo para un caso marginal
   (variable puesta en el entorno del proceso de Claude Code y no en la shell de `doctor`). Ver
   «Dudas».
2. **Clave de aviso aparte para `UNRELEASED`** (REQ-004): entre la mezcla y la release, `main`
   mostraría «desde la UNRELEASED»; se sigue el precedente de `cli.deprecations.removed_later`.
3. **La migración vive en `install.py`** (REQ-015), aunque sea un fichero CRLF grande, para no
   crear un ciclo `install ↔ módulo nuevo`.
4. **Orden fijo en `update`: migrar → checks → notas** (REQ-014), con la migración fuera de
   `plan_repairs` y tipo de acción propio (`migrate`) que relee `settings.json` al aplicarse, para
   no chocar con la deduplicación por `(kind, target)` ni perder el registro de hooks.
5. **`used_by_hooks` y `hook_names()` se borran** (REQ-010): sin nombres viejos en los hooks no
   tienen productor. Si una ola futura vuelve a renombrar algo que lean los hooks, se repone.
6. **`tests/test_cli_renamed_names.py` se reparte** en `test_retired_cli_names.py`,
   `test_retired_env_names.py` y los tests de hooks existentes, uno por superficie.
7. **Copia propia en vez de la `.bak` genérica** (REQ-015): D4 decía «con copia de seguridad como
   el resto de `update`»; la genérica se pisa en la misma corrida y perdería el original. Si la
   copia propia ya existe, se crea otra con fecha: nunca se pisa.
8. **Registro de migración en `LOG_DIR`** (REQ-012, REQ-015): fichero nuevo
   `retired-names-migration.json` (nombres y fecha, sin valores) para que la cola de telemetría no
   pida «renombra» por eventos anteriores a la migración. Es un criterio verificable y no depende
   del `mtime` de los hooks.
9. **El check avisa de un `settings.json` ilegible** (REQ-012): hoy ignora el motivo en silencio y
   puede decir `OK` con nombres viejos dentro (menor 11 de la revisión, aceptado).
10. **La migración y el chequeo previo del CLI solo actúan sobre retirados con sucesor**
    (REQ-008, REQ-015): un alias vigente funciona con aviso y no se rechaza ni se reescribe.

## Decisiones de la sesión principal sobre las dudas (2026-10-21)

1. **Detección en los hooks: NO.** Se queda la desviación 1 tal cual: los hooks no tienen canal para
   avisar al usuario y `doctor` ya cubre `settings.json` y el fichero interruptor.
2. **Copia propia `settings.json.retired-names.bak`: SÍ**, por el motivo dado (la `.bak` genérica
   la pisaría la siguiente escritura de la misma corrida). Tras la revisión (menor 8), si ya existe
   se crea otra con fecha.

## Trazabilidad

Lotes del plan: L1 fuera `_FAST` y doble escritura; L2 modelo del registro; L3 CLI y
autocompletado; L4 variables y `local_status`; L5 hooks; L6 volteo del registro y guardianes de
release; L7 migración; L8 documentación; L9 verificación en vivo.

| REQ | Lote | Verificación |
|---|---|---|
| REQ-001 | L6 | `test_deprecations.py::test_registry_holds_exactly_the_seven_retired_names` |
| REQ-002 | L2 | `test_deprecations.py::test_every_entry_follows_its_class_rule` |
| REQ-003 | L2 | `test_deprecations.py` (lectores con registro sintético) |
| REQ-004 | L2 | `test_deprecations.py::test_warning_text_*` |
| REQ-005 | L1 | `test_fast_role_retired.py` (`reload_config`, telemetría aislada), `test_chains.py` |
| REQ-006 | L1 | `test_cooldown.py::test_the_daemon_never_writes_the_old_file` |
| REQ-007 | L1, L5 | tests existentes de lectura dual (sin cambios) |
| REQ-008 | L3 (sintético), L6 (real y `entrypoint.main`) | `test_retired_cli_names.py`, `test_cli_english.py` |
| REQ-009 | L4 | `test_retired_env_names.py` |
| REQ-010 | L5 | `test_hook_legacy_names.py`, `test_environment_isolation.py`, `test_hook_boundaries.py` |
| REQ-011 | L1, L3, L4, L5, L6 | tabla de REQ-011 |
| REQ-012 | L2, L7 (telemetría migrada, `settings.json` ilegible), L6 (real) | `test_checks.py`, `test_wiki.py` |
| REQ-013 | L4 | `test_retired_env_names.py::test_local_status_lists_a_retired_variable` |
| REQ-014 | L7 | `test_update.py::test_update_migrates_before_reporting`, `::test_migration_and_hook_repair_both_survive` |
| REQ-015 | L7, L6 (real) | `test_install.py::test_retired_name_migration_*` |
| REQ-016 | L7 | `test_update.py`, `test_install.py` |
| REQ-017 | L7 | tests de valores sensibles y de `os.environ` sin efecto en el plan |
| REQ-018 | L7 | guardianes i18n, test en inglés |
| REQ-019 | L6 | `test_deprecations.py` (horizonte 0.38.0, bump simulado con `importlib`, CHANGELOG `[0.38.0]`) |
| REQ-020 | L6 | `test_deprecations.py` (cuatro formatos) |
| REQ-021 | L1–L7 (añadir), L6 (limpiar) | `test_detect_spanish_names.py` |
| REQ-022 | L3 | `test_completion_model.py`, `test_completion_render.py` |
| REQ-023 | L6 (tabla del CHANGELOG), L8 | `test_deprecations.py` (CHANGELOG), `test_wiki.py` (fila del check) |
| REQ-024 | todos, L9 | suite, `ruff`, CodeQL, `git grep` con límite de palabra |
| REQ-025 | L9 | `verification.md` |

## Cambios tras la revisión

Revisiones: [review-spec.md](review-spec.md) (block: 1 bloqueante, 7 importantes, 13 menores) y
[review-plan.md](review-plan.md) (block: 2 bloqueantes, 3 importantes, 7 menores). Decisiones de la
sesión principal del 2026-10-21.

### Revisión de la spec

| Hallazgo | Resolución |
|---|---|
| B1 — orden de la migración en `update` | Aceptado. REQ-014: migración fuera de `plan_repairs`, `kind="migrate"`, relee `settings.json` al aplicar; orden migrar → checks → notas; notas sin `rename` para lo migrado (también en `--dry-run`); test con `env` viejo y hooks viejos a la vez. |
| I1 — el chequeo del CLI rechazaría un alias futuro | Aceptado. REQ-008 solo mira retirados con sucesor; caso sintético con alias vivo que no da 2. |
| I2 — el `git grep` de código muerto no podía dar 0 | Aceptado. REQ-024 con `-w` y símbolos calificados. |
| I3 — el bump simulado con `exec` revienta | Aceptado. REQ-019 carga con `importlib` y `sys.modules` y lee con normalización a LF; añade el CHANGELOG simulado con `[0.38.0]`. |
| I4 — la telemetría sigue pidiendo «renombra» tras migrar | Aceptado con el criterio del registro de migración (`retired-names-migration.json`, por nombre y fecha) en REQ-012/REQ-015, con test y control. |
| I5 — REQ-017 afirmaba que `doctor` mira sitios que no mira | Aceptado. REQ-017 dice qué mira cada uno y qué no mira nadie; sin ampliar alcance; va al CHANGELOG. |
| I6 — escenario de `settings.json` roto falso | Aceptado. La migración no escribe y lo dice; test aislado; la sobrescritura previa por la reparación de hooks va al backlog, fuera de alcance. |
| I7 — control de `_FAST` sin mecanismo | Aceptado. `reload_config` o subproceso, `Context(home=tmp_path)` y telemetría vacía; igual en REQ-013. |
| Menor 1 — tests rotos sin listar | Aceptado. Listados en REQ-005/REQ-006 (REQ-019 sustituye a `:100-102`). |
| Menor 2 — línea de `cooldown.py` | Aceptado. `:40`, docstring `:14`, comentario `:53`. |
| Menor 3 — «no se escribe nada» no distingue | Aceptado. Espía sobre `recompute.run` y `--claude-dir` temporal. |
| Menor 4 — `_FAST` en `Configuration.md:39` y `Troubleshooting.md:92` | Aceptado, en REQ-023. |
| Menor 5 — fila de la tabla de checks sin test | Aceptado. Assert nuevo en `test_wiki.py`. |
| Menor 6 — aislar la telemetría en vivo | Aceptado. REQ-025: `LD_HOOK_TELEMETRY_LOG` vacío, `LOG_DIR` exportado, versión explícita. |
| Menor 7 — «nada más cambia» no es cierto en formato | Aceptado. Igualdad JSON; el formato puede cambiar. |
| Menor 8 — la copia guarda claves y «solo si no existe» pierde originales | Aceptado. Copia con fecha si ya existe, permisos del original, aviso en la salida y en el CHANGELOG. |
| Menor 9 — «no lee `os.environ`» no se puede probar | Aceptado. Test que distingue: viejos en `os.environ` y no en `settings.json` → plan vacío. |
| Menor 10 — referencia ambigua a los 25 checks | Aceptado. Cita `tests/test_wiki.py:47`. |
| Menor 11 — `settings.json` con BOM o ilegible | Aceptado. La migración lee y conserva el BOM; el check avisa si no puede leer (desviación 9). |
| Menor 12 — valor de otra opción y abreviatura | Aceptado como caso límite con el comportamiento elegido (sale con 2; error de argparse). |
| Menor 13 — la migración tocaría alias vivos | Aceptado. Solo retirados con sucesor (desviación 10). |

### Revisión del plan (lo que afecta a la spec)

| Hallazgo | Resolución |
|---|---|
| B1 — nadie podía tocar las excepciones del detector | Aceptado. REQ-021: cada lote añade sus parejas (solo añadir) y los tests sacan el nombre del registro donde se pueda; L6 limpia. Detalle en el plan. |
| B2 — L1 dejaba la suite en rojo | Aceptado: el lote de las `_FAST` y la doble escritura pasa a ser L1 y el modelo pasa a L2. |
| I1 — huella del hook | Aceptado. L5 corre `bump_version.py --boundaries`; REQ-010 lo verifica con `test_hook_boundaries.py`. |
| I2 — chequeo previo y alias | Igual que I1 de la spec. |
| I3 — lint distinto del CI | Aceptado en el plan (`ruff check .` y `ruff format --check .`). |
| M1–M7 | Aceptados en el plan; M6 cambia REQ-008 (camino `entrypoint.main`). |

### Ronda 2 (las dos revisiones aprueban)

| Hallazgo | Resolución |
|---|---|
| I8 (spec) / R2-M1 (plan) — con HOME simulado el registro iría al `LOG_DIR` real | Aceptado. REQ-015: el directorio se calcula con la regla de `install.language_dir`/`completion_dir`; sin directorio permitido, no se escribe y se dice; test (j). |
| R2-M2 (plan) — `--dry-run` podría crear el registro o la `.bak` | Aceptado. REQ-016: test de que no existen tras `--dry-run`, en `update` y en `install`. |
| R2-M3 (plan) — `recalcular-coste` sin `--claude-dir` en la verificación en vivo | Aceptado en el plan (L9 paso 7). |
| m14 — una sola fecha para todos los nombres | Aceptado. Una fecha por nombre, con fusión; test de dos migraciones sucesivas. |
| m15 — la copia con fecha se puede pisar en el mismo segundo | Aceptado. UTC, apertura exclusiva y sufijo de desempate; test (l). |
| m16 — copia sin escritura | Aceptado. Solo hay copia si se escribe `settings.json`; test (k). |
| m17 — el filtro de notas escondía la pista de la shell | Aceptado. Solo se quita el «renombra» de lo que la migración cubre en `settings.json`/interruptor; test con el nombre también en la shell. |
| m18 — BOM en `doctor` e `install._read_json` | La migración soporta el BOM; los fallos de `doctor`, `install._read_json` y la reparación de hooks son previos y van a «Hallazgos para el backlog», fuera de alcance. |
| Nota sin número — fallos de la migración en `failures` | Aceptado. REQ-014 paso 4 y su test. |

## Cambios tras la verificación

La verificación en vivo ([verification.md](verification.md), defecto 1, y `evidence/live/`)
encontró que `install._read_json` (`src/local_delegate/install.py:263-268`) leía con `utf-8`
estricto y ante cualquier error devolvía `{}`; los pasos que escriben después reescribían
`settings.json` o `~/.claude.json` desde cero, y con BOM o JSON inválido se perdían el `env`
(también el recién migrado por L7), las claves ajenas y el bloqueo de lectura. Era previo a este SDD
(el hallazgo m18 lo había dejado fuera), pero la 0.38.0 manda a todo el mundo a correr `update`, así
que la sesión principal lo mete en el plan como lote L10 (2026-10-21).

- **REQ-026 — El BOM se lee y se conserva.** Los ficheros JSON de configuración que `install`,
  `update` y `uninstall` reescriben (`~/.claude/settings.json`, `~/.claude.json`) se leen con
  `utf-8-sig`, y al reescribir un fichero que tenía BOM UTF-8 se escribe con BOM (y con su fin de
  línea), como ya hace la migración de L7. Las lecturas de solo consulta y los checks de `doctor`
  que leen `settings.json`/`~/.claude.json` también aceptan el BOM.
  *Verificación*: `tests/test_config_json_safety.py`: `update` sobre HOME simulado con
  `settings.json` = BOM + `env` viejo + clave ajena + hooks viejos → código 0, BOM conservado, `env`
  migrado con la clave ajena, clave de primer nivel ajena intacta y hooks registrados; lo mismo con
  `install`; `~/.claude.json` con BOM al registrar el MCP; `doctor` (`_probe_hook_settings`) no da
  `unknown` con BOM. Mutantes: leer con `utf-8` y escribir sin BOM ponen en rojo esos tests.
- **REQ-027 — Un fichero ilegible no se sobrescribe.** Se distingue «no existe» (se trata como
  `{}`, como antes) de «existe pero no se puede leer, no es UTF-8, no es JSON o no es un objeto»: en
  ese caso la acción que escribiría el fichero no escribe, falla con un aviso del catálogo i18n
  (es/en, `install.config_unreadable` y `install.config_unreadable.fix`) que nombra el fichero, el
  motivo y cómo arreglarlo, e `install`/`update`/`uninstall` terminan con código distinto de 0 (la
  acción cuenta en `failures`). Las lecturas que solo consultan siguen tratando ilegible como vacío.
  `doctor` no revienta: da `unknown` con el motivo.
  *Verificación*: `tests/test_config_json_safety.py`: JSON inválido, lista y BOM + inválido → hash
  del fichero idéntico, aviso con la ruta y el texto de arreglo, `failures ≥ 1` en `install`, código
  ≠ 0 en `update`, fallo en `uninstall`; `~/.claude.json` inválido al registrar y al quitar el MCP
  → excepción y fichero idéntico; `doctor` con inválido → `unknown` con la ruta y `run_all` sin
  excepción. Mutante: devolver `{}` en vez de fallar pone en rojo esos tests.

Al repetir en vivo el caso BOM sobre `main` (tras L10), la sesión principal encontró un segundo
defecto (2026-10-21): con la salida redirigida a fichero o tubería en Windows (codificación
cp1252), `update --home <H> --no-restart --version 0.37.0` sobre un `settings.json` con
`LD_HOOK_READ_BLOQUEAR` revienta con `UnicodeEncodeError` en `install.apply` →
`out(action.describe())`, por la flecha `→` de la descripción de la acción `migrate`
(`install._names`). La migración se aborta a medias, no se registran los hooks y sale con 1. Es
justo el camino de la 0.38.0: `update` lanzado por Claude Code, un script o la tarea programada.
Va como lote L11.

- **REQ-028 — Ningún comando de la CLI revienta por la codificación de la salida.** Al arrancar un
  subcomando de la CLI (`entrypoint.main` con argumentos), si `sys.stdout`/`sys.stderr` son de
  texto, su codificación no es UTF-8 y su política de errores es la estricta, se reconfiguran con
  `errors="replace"`: un carácter que la consola no puede representar sale como `?` en vez de
  tumbar el comando. El modo servidor MCP por stdio (sin argumentos) **no** se toca: ahí stdout es
  el canal del protocolo. Además, la descripción de la migración usa `->` en vez de `→`, para que la
  salida sea legible también en cp1252.
  *Verificación*: `tests/test_console_encoding.py`: subproceso con `PYTHONIOENCODING=cp1252`, sin
  `PYTHONUTF8`, salida por tubería, `update --home <H simulado> --no-restart --version 0.37.0` con
  `settings.json` (con y sin BOM) que lleva `LD_HOOK_READ_BLOQUEAR` → código 0, `env` migrado,
  hooks registrados, BOM conservado y sin `UnicodeEncodeError` (en rojo en `main` por esa
  excepción); la guarda convierte un `→` en `?` sin excepción; con el modo stdio la política de
  errores de stdout sigue siendo la estricta.

| REQ | Lote | Prueba |
|---|---|---|
| REQ-026 | L10 | `tests/test_config_json_safety.py` (BOM) |
| REQ-027 | L10 | `tests/test_config_json_safety.py` (ilegible) |
| REQ-028 | L11 | `tests/test_console_encoding.py` |
