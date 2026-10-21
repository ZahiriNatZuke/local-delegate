# Plan de implementación: retirada de los nombres vencidos en la 0.38.0

Desarrolla [spec.md](spec.md) (REQ-001…REQ-025, desviaciones 1–10 y «Cambios tras la revisión»)
sobre [research.md](research.md) (D1–D7). Reglas comunes en [brief.md](brief.md). Revisado en
[review-plan.md](review-plan.md); los cambios están en §8. La release (subir a 0.38.0, sellar
`UNRELEASED`, publicar) queda **fuera**: la hace la PR de release después de L9.

## 1. Resumen y orden de lotes

### Diseño en una página

```
deprecations.DEPRECATED_NAMES  (7 retirados con sucesor, retired_from, warn_until=0.40.0)
   │  effective_kind() · env_vars() · switch_files() · cli_entries()
   ├─► deprecation_notices.warning_text()  ── «X ya no tiene efecto desde la 0.38.0: usa Y» (es/en)
   ├─► cli.run(): chequeo previo a argparse ── SOLO retirados CLI → stderr + código 2
   ├─► completion.py: oculta cli_entries() (alias y retirados)
   ├─► config.DEPRECATED_ENV_VALUES (lee el viejo SOLO para avisar)
   │       ├─► checks._probe_deprecated_names (shell, env de settings.json, ~/.claude, telemetría 7 días
   │       │       filtrada por <LOG_DIR>/retired-names-migration.json; avisa si settings.json es ilegible)
   │       └─► server._describe_deprecated_names (local_status)
   └─► install.plan_retired_name_migration(home)  kind="migrate", SOLO retirados
           ├─► update.run_update: migrar → checks → notas (sin «renombra» para lo migrado)
           └─► install.plan_install: antes de cualquier otra acción sobre settings.json (Claude)
config.py / hook_common.py: solo nombres nuevos.   cooldown.py: solo cooldown.json (lee el viejo).
```

Estrategia: primero se **quitan** las entradas que no sobreviven (`_FAST`, `legacy_write`, L1), así
el **modelo** nuevo (L2) se aplica a un registro sin excepciones. Luego cada superficie deja de dar
efecto al nombre viejo (L3–L5); después se **voltean** las entradas reales a retiradas con sucesor
junto con los guardianes de release (L6). La migración (L7) depende solo del modelo y va en
paralelo. Los tests de superficie comparan contra `warning_text(entry)`, no contra una frase
literal, para que el volteo de L6 no los rompa.

**Estados intermedios aceptados (sin release entre medias)**: entre L3 y L6, `recalcular-coste` da
el error genérico de argparse (el chequeo previo solo mira retirados y las entradas reales aún son
alias); entre L4 y L6, `doctor` muestra el aviso de alias («está obsoleto… se retira en la 0.38.0»)
de nombres que ya no tienen efecto; antes de L6, la migración no encuentra nada real que migrar.

**La suite queda verde tras CADA lote**: cada lote ajusta o borra los tests que su cambio invierte
y añade las excepciones del detector que necesitan sus literales (§2).

### Lotes (cada uno, una PR contra `main`)

| Lote | Contenido | Depende de | REQ |
|---|---|---|---|
| **L1** | Fuera las `_FAST` y la doble escritura de `enfriamiento.json` | — | 005, 006, 007, 011 (filas 8–9) |
| **L2** | Modelo del registro: `retired_from`, regla de clases, lectores por clase efectiva, textos nuevos, pista `rename` para retirados con sucesor | L1 | 002, 003, 004, 012 (sintético) |
| **L3** | CLI: fuera subcomando y opción ocultos; chequeo previo (solo retirados); autocompletado | L2 | 008 (sintético), 011 (filas 6–7), 022 |
| **L4** | Variables del paquete y `local_status` | L3 | 009, 011 (filas 4–5), 013 |
| **L5** | Hooks: solo nombres nuevos; fuera `used_by_hooks`/`hook_names()`; huellas | L4 | 007, 010, 011 (filas 1–3) |
| **L6** | Volteo del registro real, tabla del CHANGELOG, horizonte 0.38.0, `bump_version`, aserciones con el registro real, limpieza del detector | L5, L7 | 001, 008 (real), 012 (real), 015 (real), 019, 020, 021, 023 (tabla) |
| **L7** | Migración en `update` e `install`; filtro de telemetría y `settings.json` ilegible en el check | L2 | 012 (telemetría, ilegible), 014, 015, 016, 017, 018 |
| **L8** | Documentación: CHANGELOG (resto), README, wiki, recetas | L6 | 023 |
| **L9** | Verificación en vivo en HOME simulado y cierre | L8 | 024, 025 |
| **L10** | Tras la verificación: JSON de configuración con BOM e ilegible (no se sobrescribe) | L7 | 026, 027 |
| **L11** | Tras la verificación: la salida redirigida en cp1252 no tumba la CLI | L10 | 028 |

Son **11 lotes** (L10 y L11, tras la verificación). Cada uno deja `main` verde y se revierte con `git revert` de su PR (ninguno migra
datos del repo; L7 migra datos del usuario solo al ejecutarse).

### Qué va en paralelo

- L1 → L2 en serie (`deprecations.py`, `checks.py`, `test_deprecations.py`).
- Tras L2: **L3 ∥ L7** (ficheros disjuntos salvo `name_exceptions.json`, que es «solo añadir»).
- L3 → L4 → L5 en serie (`test_cli_renamed_names.py`, `test_deprecations.py`, `deprecations.py`).
- L6 espera a L5 y a L7 (`test_install.py`, `test_checks.py`, `name_exceptions.json`).
- L8 puede **redactarse** en paralelo con L6/L7, pero se mezcla después de L6.
- Comandos pesados (suite, builds): de uno en uno en la máquina con `pesado.sh`, aunque los lotes
  vayan en paralelo.

### Propiedad de ficheros por lote

`●` = el lote lo edita. `+` = **compartido solo para añadir** (ver §2).

| Fichero | Fin de línea | L1 | L2 | L3 | L4 | L5 | L6 | L7 | L8 |
|---|---|---|---|---|---|---|---|---|---|
| `src/local_delegate/deprecations.py` | LF | ● quita 4 entradas, `legacy_write` de `KINDS` | ● modelo, quita `_looks_env` | | | ● quita `used_by_hooks`, `hook_names` | ● volteo | | |
| `src/local_delegate/deprecation_notices.py` | LF | | ● | | | | | | |
| `src/local_delegate/checks.py` | LF | ● quita `current_roles`, docstring `:1896-1902` | ● pista `rename`, `switch_files` | | | | | ● telemetría migrada, `settings.json` ilegible | |
| `src/local_delegate/config.py` | LF | ● quita `RETIRED_FAST_ROLE_VARIABLES`, comentario `:280-289` | | | ● quita `_env_alias*`, `DEPRECATED_SEEN` | | | | |
| `src/local_delegate/chains.py` | LF | ● comentario `:23` | | | | | | | |
| `src/local_delegate/cooldown.py` | LF | ● | | | | | | | |
| `src/local_delegate/legacy_names.py` | LF | ● quita `old_keys` | | | | ● quita `switch_file` | | | |
| `src/local_delegate/cli.py` | **CRLF** | | | ● | | | | | |
| `src/local_delegate/completion.py` | LF | | | ● `cli_entries()` | | | | | |
| `src/local_delegate/server.py` | **CRLF** | | | | ● | | | | |
| `src/local_delegate/resources/hooks/hook_common.py` | LF, `-text` | | | | | ● | | | |
| `src/local_delegate/resources/hooks/suggest_delegate_read.py` | LF, `-text` | | | | | ● docstring | | | |
| `scripts/data/hook_hashes_after.json` | LF | | | | | ● `--boundaries` | | | |
| `src/local_delegate/install.py` | **CRLF** | | | | | | | ● | |
| `src/local_delegate/update.py` | LF | | | | | | | ● | |
| `resources/i18n/{es,en}/cli.json` | LF | | ● claves nuevas | ● quita `reset_mismatch` | | | | | |
| `resources/i18n/{es,en}/doctor.json` | LF | ● quita `current_roles` | | | | | | ● `settings.json` ilegible | |
| `resources/i18n/{es,en}/mcp.json` | LF | | | | ● `mcp.status.deprecated` | | | | |
| `resources/i18n/{es,en}/install.json` | LF | | | | | | | ● | |
| `scripts/bump_version.py` | LF | | | | | | ● | | |
| `scripts/data/name_exceptions.json` | LF | + | + | + | + | + | ● limpia y cambia motivos | + | |
| `scripts/data/name_exceptions.README.md` | LF | ● enmienda del motivo nuevo | | | | | | | |
| `scripts/_claude_bench.py` | LF | | | | | | ● docstring | | |
| `tests/test_deprecations.py` | LF | ● quita tests `_FAST` (`:62-71`, `:100-102`) | ● reglas, lectores, textos | | ● quita tests `_env_alias` (`:190-207`) | ● quita igualdad (`:170-176`) | ● registro, horizonte, bump, CHANGELOG `[0.38.0]` | | |
| `tests/test_checks.py` | LF | | ● casos sintéticos | | | | ● caso real | ● telemetría, ilegible | |
| `tests/test_fast_role_retired.py` | LF | ● | | | | | | | |
| `tests/test_cooldown.py` | LF | ● | | | | | | | |
| `tests/test_chains.py` | LF | ● `:202-208` | | | | | | | |
| `tests/test_cli_renamed_names.py` | LF | | | ● quita parte CLI | ● quita variables y `local_status` | ● se borra | | | |
| `tests/test_retired_cli_names.py` (nuevo) | LF | | | ● | | | ● registro real, `entrypoint.main` | | |
| `tests/test_retired_env_names.py` (nuevo) | LF | | | | ● | | | | |
| `tests/test_cli_english.py` | LF | | | ● | | | | | |
| `tests/test_completion_model.py`, `tests/test_completion_render.py` | LF | | | ● | | | | | |
| `tests/test_density.py`, `tests/test_structured_summary.py` | LF | | | | ● | | | | |
| `tests/test_hook_legacy_names.py` | LF | | | | | ● | | | |
| `tests/test_environment_isolation.py` | LF | | | | | ● | | | |
| `tests/test_install.py` | LF | | | | | | ● caso real | ● | |
| `tests/test_update.py` | LF | | | | | | | ● | |
| `tests/test_wiki.py` | LF | | | | | | | | ● fila del check |
| `CHANGELOG.md` | LF | | | | | | ● tabla | | ● resto |
| `README.md` | **CRLF** | | | | | | | | ● |
| `docs/wiki/Configuration.md` | LF | | | | | | | | ● |
| `docs/wiki/Troubleshooting.md` | LF* | | | | | | | | ● `:92` |
| `docs/wiki/Integration-install.md` | **CRLF** | | | | | | | | ● |
| `docs/recipes/claude-code-hooks.md`, `docs/wiki/Architecture.md` | LF | | | | | | | | ● |

\* `Troubleshooting.md` no se comprobó en la investigación: L8 lo mira con `git ls-files --eol`
antes de editar.

Si un lote necesita un fichero `●` de otra columna activa, para y lo reporta.

## 2. Reglas de ejecución (todos los lotes)

- **Primer paso**: cargar las `local_*` (`ToolSearch` del brief) y decidir qué pasos van por ellas
  (salida de pytest y ruff volcada a fichero → `local_lint_summary(path=…)`; ficheros grandes como
  `install.py` o `checks.py` → `local_explain_code`/`local_summarize` con `path` antes de leer
  franjas; borrador de commit con `local_commit_msg(path=<diff>)`). La entrega lista las llamadas.
- Rama propia por lote (`retire-legacy/L<n>-<tema>`), commits **firmados**, sin coautoría de Claude,
  PR contra `main`.
- **Suite verde tras cada lote**: el lote ajusta o borra en la misma PR los tests que su cambio
  invierte (las listas por lote de §3 son de partida; si salen más, se arreglan en el lote y se
  anotan en la PR).
- **Detector de nombres en español** (REQ-021):
  - Donde se pueda, los tests **sacan el nombre viejo del registro** en vez de escribirlo literal,
    p. ej. `next(e.old for e in deprecations.DEPRECATED_NAMES if e.new == "LD_HOOK_READ_BLOCK")`;
    así no hace falta excepción.
  - Donde haga falta un literal (para que el test discrimine, o en ficheros que no deben importar el
    registro, como los hooks), el lote **añade** a `scripts/data/name_exceptions.json` las parejas
    (nombre, fichero) de los ficheros que crea o cambia, con el motivo nuevo «nombre retirado con
    sucesor: sin efecto desde la 0.38.0, avisa hasta la 0.40.x». L1 añade ese motivo a
    `name_exceptions.README.md`.
  - El fichero es **compartido solo para añadir**: ningún lote salvo L6 borra ni cambia entradas.
    Si dos PR paralelas (L3 y L7) chocan, la segunda rebasa y junta las dos entradas.
  - Las entradas sobrantes no rompen el test; L6 las limpia y cambia los motivos de
    `enfriamiento.json`.
  - Cada lote corre `uv run pytest tests/test_detect_spanish_names.py -q` antes de abrir la PR.
- **Fin de línea**: `git ls-files --eol <fichero>` antes de editar; no usar `Path.write_text` ni
  `sed -i` sobre ficheros CRLF (`cli.py`, `server.py`, `install.py`, `README.md`,
  `Integration-install.md`). Comprobar al final con `git diff --stat` y `git ls-files --eol` que no
  cambió el terminador.
- Código en inglés; textos al usuario solo por `resources/i18n/{es,en}/*.json`.
- Sin dependencias nuevas.
- **Lint igual que el CI** (`.github/workflows/ci.yml:43-46`), antes de abrir cada PR:
  `uv run ruff check . && uv run ruff format --check .`, más la revisión manual de helpers que se
  quedan sin llamadas tras borrar.
- **Pesado de uno en uno**, desde la tool **Bash**:
  `bash ~/.claude/scripts/pesado.sh uv run pytest -n 2 -q > <scratchpad>/pytest-L<n>.txt 2>&1`, y
  resumir con `local_lint_summary`. Un fichero de tests suelto que tarda segundos puede ir sin
  cerrojo (`uv run pytest tests/test_x.py -q`).
- **CodeQL a 0, también `note`**: no crear ciclos (`deprecations` no importa nada del paquete;
  `config` no importa `deprecation_notices`; la migración vive en `install.py`). Tras el CI:
  `gh pr checks <n>` (incluye los checks que no son workflows) y
  `gh api "repos/ZahiriNatZuke/local-delegate/code-scanning/alerts?ref=refs/pull/<n>/merge&state=open"`
  → `[]`; hilos resueltos.
- **Control positivo** en cada test nuevo de «sin efecto»: gemelo con el nombre nuevo en la misma
  prueba. Y comprobar que el test **falla** con el código anterior (sobre `main` o con el cambio
  revertido en local) antes de darlo por bueno; anotarlo en la PR.
- Valores de `config` en tests: por `reload_config` o subproceso, nunca `setenv` a secas;
  `LD_HOOK_TELEMETRY_LOG` vacío o temporal en todo test del check.
- No tocar el daemon, la tarea programada, `~/.claude*` real, `~/.codex` ni variables del usuario.
  Todo test o prueba que escriba en un HOME lo hace en uno simulado (`tmp_path`) con
  `LOCAL_DELEGATE_LOG_DIR` temporal.
- **Nada huérfano**: sin servidores ni esperas vivas al terminar; toda espera con tope.

## 3. Tareas por lote

### L1 — Fuera las `_FAST` y la doble escritura

- **Ficheros**: `deprecations.py` (quita las 3 `_FAST` y la entrada `legacy_write`; `legacy_write`
  sale de `KINDS`), `config.py` (`RETIRED_FAST_ROLE_VARIABLES`, comentario `:280-289`), `chains.py:23`,
  `checks.py` (`current_roles`, docstring `:1896-1902`), `resources/i18n/{es,en}/doctor.json`,
  `cooldown.py`, `legacy_names.py` (`old_keys`), `name_exceptions.README.md` (enmienda),
  `tests/test_fast_role_retired.py`, `tests/test_cooldown.py`, `tests/test_chains.py`,
  `tests/test_deprecations.py` (`:62-71`, `:100-102`).
- **Qué queda tras L1**: el registro tiene solo los 7 alias. `_looks_env` sigue en `env_vars()`
  (sin entradas que lo usen) hasta L2. La regla de clases actual (`:45-54`) sigue valiendo.
- **Tareas**: REQ-005 y REQ-006 tal cual; quitar `deprecations` del import de `cooldown.py:40`
  (conservar `config` y `legacy_names`), docstring `:14` y comentario `:53`. No tocar
  `cooldown._load`, `_legacy_path`, `LEGACY_STATE_FILE`.
- **Tests**: `test_the_daemon_never_writes_the_old_file` (con gemelo `cooldown.json` y bytes del
  viejo intactos); se borran `test_dual_write_leaves_the_same_state…`,
  `test_the_old_file_carries_the_old_keys…` y `test_without_its_legacy_write_entry…`
  (`test_cooldown.py:369-450`). En `test_fast_role_retired.py`, con `reload_config`,
  `Context(home=tmp_path)` y telemetría vacía: solo `_FAST` → `OK`, gemelo con
  `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` (hoy alias) → `WARN`; se borran o invierten `:143-203`; se
  quedan `:41-133`. `test_chains.py:202-208` sin `_FALLBACK_FAST`. Siguen verdes sin cambios
  `test_an_old_state_from_a_previous_daemon…` y `test_with_both_files_the_new_one_wins`.
- **Verificación**: ficheros sueltos; ruff; suite completa;
  `git grep -nwE "legacy_write_enabled|_write_legacy|RETIRED_FAST_ROLE_VARIABLES|current_roles" -- src scripts tests`
  y `git grep -nE "legacy_names\.old_keys|def old_keys|\"legacy_write\"" -- src scripts tests` → 0.

### L2 — Modelo del registro

- **Ficheros**: `deprecations.py`, `deprecation_notices.py`, `checks.py` (probe),
  `resources/i18n/{es,en}/cli.json`, `tests/test_deprecations.py`, `tests/test_checks.py`.
- **Tareas**:
  1. `DeprecatedName.retired_from: str | None = None`; `effective_kind(entry)`; regla de clases de
     REQ-002 con una función `class_problems(entries)` que use el test; docstring del módulo.
  2. `env_vars()`, `switch_files()` y `cli_entries()` por clase efectiva; **quitar `_looks_env`**
     (tras L1 no hay retirados sin sucesor en el registro real, así que no se pierde nada).
     **Las entradas reales no cambian** (siguen siendo los 7 alias).
  3. `warning_text`: ramas de REQ-004 y claves `cli.deprecations.retired_renamed` y
     `cli.deprecations.retired_renamed_unreleased` en es/en.
  4. `checks._probe_deprecated_names`: pista `rename` cuando `entry.new` no es nulo (alias **o**
     retirado), `remove` solo para retirados sin sucesor; interruptores por `switch_files()`.
- **Tests**: `test_every_entry_follows_its_class_rule` (real + sintético con casos inválidos),
  lectores con registro sintético, `test_warning_text_*` (tres clases, es/en, nunca `UNRELEASED`),
  cuatro casos sintéticos en `test_checks.py` (shell, `env`, interruptor, telemetría) con retirado
  con sucesor → `WARN` + pista `rename`, con telemetría y HOME aislados.
- **Verificación**: `uv run pytest tests/test_deprecations.py tests/test_checks.py -q`; ruff; suite
  completa (incluye los guardianes i18n de paridad y de textos fuera del catálogo).

### L3 — CLI y autocompletado

- **Ficheros**: `cli.py` (CRLF), `completion.py`, `resources/i18n/{es,en}/cli.json`
  (quita `cli.recompute_cost.reset_mismatch`), `tests/test_retired_cli_names.py` (nuevo),
  `tests/test_cli_renamed_names.py` (quita la parte CLI), `tests/test_cli_english.py`,
  `tests/test_completion_model.py`, `tests/test_completion_render.py`, `name_exceptions.json` (+).
- **Tareas**:
  1. Borrar lo listado en REQ-008 (`cli.py:386-406,430-433,1611-1614,1621-1627,1637-1644`).
     Si al quitar `_HIDDEN_COMMANDS` el `metavar` resultante es igual al de argparse, quitar
     también la asignación; si cambia la ayuda, los tests de ayuda lo dirán.
  2. Chequeo previo en `cli.run` (función propia, p. ej. `_reject_retired_names(argv) -> int | None`)
     **solo** con `e for e in deprecations.cli_entries() if e.is_retired`,
     `t("cli.error", detail=warning_text(entry))` en `stderr` y código 2. Comprobar el camino
     `local_delegate:main` → `entrypoint.main` (`pyproject.toml:74-75`, `entrypoint.py:47`): que
     `local-delegate-mcp recalcular-coste` pase por el chequeo.
  3. `completion.py`: ocultar `cli_entries()` en lugar de filtrar por `kind`.
- **Tests**: filas 6–7 de REQ-011 con **registro sintético** (las dos entradas como retiradas),
  espía sobre `recompute.run`, `--claude-dir` temporal y gemelos; forma `=`; alias `cli_command`
  sintético vivo → no da 2; `--label recalcular-coste` no dispara; `noexiste` sigue con el error de
  argparse sin `recalcular-coste` en `choose from`. Completion: contar con `cli_entries()` (≥ 2);
  para cada una, ausente del parser y del modelo/script.
- **Huérfanos en `test_cli_renamed_names.py`**: tras quitar la parte CLI, revisar los imports
  `replace`, `_delegation_with_n`, `subagent`, `recompute` (`:15-23`) y quitar los que queden sin uso.
- **Verificación**: ficheros sueltos; ruff; suite completa (incluye los tests de shells reales del
  autocompletado si el entorno los tiene).

### L4 — Variables del paquete y `local_status`

- **Ficheros**: `config.py`, `server.py` (CRLF), `resources/i18n/{es,en}/mcp.json`,
  `tests/test_retired_env_names.py` (nuevo), `tests/test_cli_renamed_names.py` (quita variables y
  `local_status`: `:125-193`, `:269-276`), `tests/test_deprecations.py` (`:190-207`),
  `tests/test_density.py`, `tests/test_structured_summary.py`, `name_exceptions.json` (+).
- **Tareas**: REQ-009 (lectores normales para las cuatro variables, `DEPRECATED_ENV_VALUES` se
  queda) y REQ-013 (`_describe_deprecated_names` desde `DEPRECATED_ENV_VALUES`, solo entradas con
  `new`; texto nuevo de `mcp.status.deprecated` en es/en).
- **Tests**: filas 4–5 de REQ-011 con `reload_config` o subproceso;
  `test_local_status_lists_a_retired_variable` con valor centinela que no debe aparecer (en L4 las
  entradas aún son alias: el test usa registro sintético con retiradas o filtra por `new`, y L6
  comprueba con el real). Helpers de `test_cli_renamed_names.py:125-150` que citan
  `DEPRECATED_SEEN`: se van.
- **Verificación**: ficheros sueltos; ruff; suite completa;
  `git grep -nw "DEPRECATED_SEEN" -- src tests` → solo `hook_common.py` y
  `tests/test_hook_legacy_names.py` (se van en L5); ni una en `config.py`, `server.py` ni
  `test_cli_renamed_names.py`; `git grep -nwE "_env_alias(_str|_flag)?" -- src tests` → 0.

### L5 — Hooks

- **Ficheros**: `resources/hooks/hook_common.py`, `resources/hooks/suggest_delegate_read.py`
  (docstring), `scripts/data/hook_hashes_after.json`, `legacy_names.py` (`switch_file` fuera de
  `FILE_NAMES`), `deprecations.py` (`used_by_hooks`, `hook_names()`),
  `tests/test_hook_legacy_names.py`, `tests/test_environment_isolation.py`,
  `tests/test_deprecations.py` (`:170-176`), `tests/test_cli_renamed_names.py` (se borra: lo que
  queda, `:231-245`, pasa a `test_hook_legacy_names.py`), `name_exceptions.json` (+: el hook y
  `test_hook_legacy_names.py` necesitan el literal `local-delegate-bloqueo-apagado`, que ya no sale
  de `FILE_NAMES`, si el test no lo saca del registro).
- **Tareas**: REQ-010. Constante propia del interruptor en el hook; `block_state()` y
  `switch_path()` con `os.environ.get` de los nombres nuevos; `record()` sin `deprecated_names`.
  `checks.deprecated_names_in_hook_telemetry` **no** se toca. Tras cambiar
  `suggest_delegate_read.py` (está en `HASHED_HOOKS`, `scripts/bump_version.py:71-75`), correr
  `uv run python scripts/bump_version.py --boundaries`, que solo une huellas y no toca la versión.
- **Tests**: filas 1–3 de REQ-011 con el hook **instalado** en HOME simulado (mismo arnés que los
  tests actuales de `:231-245`); cola de 7 días con evento sintético → `WARN`; test de aislamiento
  reescrito sin `hook_names()`. Comprobar que los tests de temporales (`:76-130`) no cambian.
- **Verificación**: ficheros sueltos más `tests/test_hook_boundaries.py`; ruff; suite completa;
  `git grep -nwE "env_alias|legacy_switch_path|DEPRECATED_SEEN|DEPRECATED_HOOK_NAMES|used_by_hooks" -- src tests`
  y `git grep -nE "deprecations\.hook_names|def hook_names" -- src tests` → 0.

### L6 — Volteo del registro y guardianes de release

- **Ficheros**: `deprecations.py` (las 7 entradas de REQ-001, tupla multilínea), `CHANGELOG.md`
  (`[Unreleased]`: entradilla de incompatible y la tabla «Qué deja de funcionar» con viejo y nuevo
  de cada entrada; el resto de la prosa va en L8), `scripts/bump_version.py`,
  `scripts/data/name_exceptions.json` (limpieza), `scripts/_claude_bench.py`,
  `tests/test_deprecations.py`, `tests/test_checks.py`, `tests/test_retired_cli_names.py`,
  `tests/test_install.py`.
- **Tareas**:
  1. Volteo (REQ-001) con `introduced="UNRELEASED"`, `warn_until="0.40.0"`, `retired_from`.
  2. `stamp_unreleased`/`plan()` robustos (REQ-020).
  3. Detector (REQ-021): correr `uv run python scripts/detect_spanish_names.py` antes y después,
     guardar ambas salidas en `evidence/L6/`, quitar las excepciones de estos nombres que ya no
     casan y cambiar los motivos de `enfriamiento.json` y de los 7 nombres.
- **Tests**: `test_registry_holds_exactly_the_seven_retired_names`,
  `test_registry_has_nothing_overdue_in_0_38_0`, `test_the_0_38_0_bump_keeps_the_registry_valid`
  (carga con `importlib` + `sys.modules`, lectura normalizada a LF, control positivo en 0.41.0),
  `test_the_0_38_0_changelog_still_announces_every_entry`, los cuatro formatos de `bump_version`
  (el de `= ()` debe fallar sobre `main`), caso real de `doctor` (REQ-012), filas 6–7 con el
  registro real y por `entrypoint.main` (REQ-008), un caso real de migración en
  `test_install.py` (REQ-015) y el test del CHANGELOG. **Mutante**: poner `warn_until="0.37.0"` en
  una entrada en local y ver que falla el test de horizonte 0.38.0 por esa entrada (anotarlo en la
  PR; no se sube).
- **Verificación**: ficheros sueltos; ruff; suite completa; simulación en seco del bump sin
  escribir: `uv run python scripts/bump_version.py 0.38.0 --dry-run --no-lock` no falla, y
  `git status` está limpio antes y después.

### L7 — Migración en `update` e `install`

- **Ficheros**: `install.py` (CRLF), `update.py`, `checks.py` (telemetría migrada, `settings.json`
  ilegible), `resources/i18n/{es,en}/install.json`, `resources/i18n/{es,en}/doctor.json`,
  `tests/test_install.py`, `tests/test_update.py`, `tests/test_checks.py`, `name_exceptions.json` (+).
- **Tareas**:
  1. `install.plan_retired_name_migration(home) -> list[Action]` (REQ-015): **solo retirados con
     sucesor**; una acción `kind="migrate"` (no `settings`) cuyo `run` relee `settings.json` al
     aplicarse; lectura con `utf-8-sig` y escritura conservando BOM y fin de línea; copia propia
     `settings.json.retired-names.bak` solo si se escribe `settings.json` (si existe, con fecha UTC
     y sufijo de desempate, apertura exclusiva; permisos con `shutil.copymode`); acciones para el
     interruptor; registro `retired-names-migration.json` al aplicar, con **una fecha por nombre** y
     fusión, en el directorio de datos calculado con la regla de `install.language_dir`
     (`install.py:1592-1603`) / `completion_dir`: con HOME simulado nunca el `LOG_DIR` real; si no
     hay directorio permitido, no se escribe y se dice. El `detail`/`literal` lleva solo nombres
     (REQ-017). JSON inválido, no UTF-8 o `env` no objeto → no escribe y lo dice.
  2. `install.plan_install`: añadir la migración **antes** de cualquier otra acción sobre
     `settings.json` cuando Claude está en el plan. Comprobar que `install.apply` y `describe()`
     aceptan el `kind` nuevo.
  3. `update.run_update`: orden fijo **migrar → checks → notas** (REQ-014). La migración se
     planifica **fuera** de `plan_repairs` (sin su deduplicación por `(kind, target)`) y se aplica
     antes de `checks.run_all`; en `--dry-run`, solo se muestra. Sus fallos suman a `failures`.
     Las notas quitan **solo** el «renombra» que la migración cubre en `settings.json` o en el
     interruptor; la pista de la shell se conserva.
  4. `checks._probe_deprecated_names`: la rama de telemetría ignora los eventos de un nombre con
     `ts` ≤ la fecha de ese nombre en el registro de migración (leído de `ctx.log_dir` o del mismo
     directorio de datos); un `settings.json` ilegible da una advertencia con el motivo (clave nueva
     en `doctor.json`). El BOM en `checks.read_json`/`install._read_json` **no** se toca aquí
     (backlog).
- **Tests** (registro sintético con retiradas, porque las entradas reales aún son alias; L6 añade el
  caso real): (a)–(l) de REQ-015; `--dry-run` sin escrituras (hash de bytes) y sin registro ni
  `.bak`, en `update` y en `install`; HOME simulado sin `LOCAL_DELEGATE_LOG_DIR` → el `LOG_DIR`
  real (monkeypatch) no recibe el registro; idempotencia;
  `settings.json` roto aislando la migración (sin reparación de hooks en el plan);
  `test_migration_and_hook_repair_both_survive` (`env` viejo y hooks viejos a la vez); nombre
  también en la shell → su pista sigue en las notas; migración que falla → `update` sale con 1;
  dos migraciones sucesivas conservan las dos fechas; centinela de
  valores; `OTHER` intacto; viejos en `os.environ` y no en `settings.json` → plan vacío; `install`
  con y sin Claude; notas sin «renombra» para lo migrado, con y sin `--dry-run`; línea en inglés con
  `LOCAL_DELEGATE_OUTPUT_LANGUAGE=en`; telemetría `t0`/`t1`/`t2` y con otro nombre; check con
  `settings.json` no JSON → `WARN` con el motivo.
- **Hallazgos para el backlog** (no se arreglan aquí): la reparación de hooks sobrescribe un
  `settings.json` ilegible (`install.py:261-266`, `:1875-1877`), y `checks.read_json` e
  `install._read_json` no leen un fichero con BOM. Se anotan en la PR y en el backlog.
- **Verificación**: ficheros sueltos; ruff; suite completa; `uv run local-delegate update --help`
  sin cambios de opciones.

### L8 — Documentación

- **Ficheros**: `CHANGELOG.md` (resto de «Lo que rompe y cómo actualizar» según REQ-023 y
  `research-upgrade.md` §3.3–§4, más lo que no mira nadie, la copia con el `env` y `local_status`),
  `README.md:121-123`, `docs/wiki/Configuration.md` (`:38`, `:39`, `:122-125`, `:212`, `:541`,
  `:555-560`, `:566-568`, `:588-609`), `docs/wiki/Troubleshooting.md:92`,
  `docs/wiki/Integration-install.md:453`, `docs/recipes/claude-code-hooks.md:62-63`,
  `docs/wiki/Architecture.md:188` (solo si dice que se sigue escribiendo), `tests/test_wiki.py`
  (assert de la fila del check).
- **Tareas**: redactar con los datos reales de L6/L7 (nombre de la copia propia, salida de
  `update`); la sección `[0.35.0]` no se toca.
- **Verificación**: `uv run pytest tests/test_wiki.py tests/test_deprecations.py -q`;
  `git grep -nE "0\.37\.x|hasta la 0\.37|siguen funcionando con aviso|_FAST" README.md docs/` sin
  resultados (si alguno es historia legítima, se lista en la PR con su fichero y línea); leer el
  diff entero (es prosa).

### L9 — Verificación en vivo y cierre

Sin tocar el daemon ni la configuración real. Todo desde la tool Bash, en **una** shell con el
entorno fijado al principio y usando el ejecutable del `.venv` (`.venv/Scripts/local-delegate`, o
`uv run --no-sync`) para no disparar un `uv sync`:

0. `export LOCAL_DELEGATE_LOG_DIR=<scratchpad>/live-logs` y `export LD_HOOK_TELEMETRY_LOG=` para
   **todos** los pasos; comprobar, solo por nombre (`env | cut -d= -f1`), que la shell no tiene
   ninguno de los 7 nombres viejos.
1. Hash del `~/.claude/settings.json` real (solo el hash, nunca el contenido) al empezar.
2. `H=<scratchpad>/live-home`. Sembrar `$H/.claude/settings.json` con `env` de REQ-025 paso 1
   (valores inventados, sin secretos reales) y `$H/.claude/local-delegate-bloqueo-apagado`.
3. `local-delegate doctor --home "$H"` → `WARN` con los cuatro nombres y pista `rename`.
4. `local-delegate update --home "$H" --no-restart --version 0.37.0 --dry-run` → acciones listadas;
   hashes de `$H/.claude/*` iguales antes y después; ningún valor sembrado en la salida (`grep -c` de
   cada valor = 0).
5. `local-delegate update --home "$H" --no-restart --version 0.37.0` → `env` migrado, clave ajena
   intacta, `settings.json.retired-names.bak` = fichero sembrado (hash), interruptor renombrado,
   `$LOCAL_DELEGATE_LOG_DIR/retired-names-migration.json` con nombres y sin valores.
6. `doctor --home "$H"` sin esos avisos; segunda `update … --dry-run` sin acciones de migración.
7. `local-delegate recalcular-coste --claude-dir "$H/.claude"` y `local-delegate-mcp
   recalcular-coste --claude-dir "$H/.claude"` → código 2 y nombran `recompute-cost`.
8. Hash del `~/.claude/settings.json` real igual al del paso 1. Borrar `$H` y los logs temporales.
9. Los dos `git grep` de REQ-024 → 0; `pyproject.toml` en `0.37.0`.
10. Registrar todo en `verification.md` (comandos, salidas recortadas sin valores, hashes) y
    actualizar `state.json`.

Si `--version 0.37.0` no evita la consulta a PyPI y falla sin red, se anota y no bloquea: la
migración ocurre antes.

### L10 — JSON de configuración: BOM y ficheros ilegibles (tras la verificación)

- **Por qué**: defecto 1 de [verification.md](verification.md): la reparación de hooks de `update`
  reescribía desde cero un `settings.json` con BOM o inválido y borraba el `env` recién migrado.
  REQ-026 y REQ-027.
- **Ficheros**: `src/local_delegate/install.py` (`_decode_config_json`, `_read_json` de solo
  consulta con `utf-8-sig`, `_read_config_json` + `UnreadableConfigError` para los pasos que
  escriben, `_write_json` conserva el BOM), `src/local_delegate/checks.py` (`read_json` acepta el
  BOM), `src/local_delegate/attribution.py` (`cleanupPeriodDays` con `utf-8-sig`), catálogo
  `resources/i18n/{es,en}/install.json`, `tests/test_config_json_safety.py`, `CHANGELOG.md`
  («Corrige»).
- **Usos de `_read_json`**: pasan a `_read_config_json` los cuatro que escriben después (registro
  de hooks en `plan_install`, quitar hooks en `plan_uninstall`, `_register_claude_mcp` y
  `_unregister_claude_mcp` en modo fichero). Siguen tolerantes (solo consultan, o el fichero es
  nuestro y se reescribe entero): `_read_hook_installed`, las dos lecturas de `mcpServers` de
  `~/.claude.json`, `_stored_preference` (`language.json`) y las dos del registro de migración.
- **Tests primero**: en rojo en `main` por la razón que dicen; mutantes `utf-8`, `{}` y sin BOM.
- **Verificación**: suite completa con `pesado.sh` y `-n 2`, `ruff check` y `ruff format --check`,
  CodeQL a 0.

### L11 — La salida redirigida en cp1252 no tumba la CLI (tras la verificación)

- **Por qué**: al repetir en vivo el caso BOM tras L10, `update` con la salida por tubería en
  cp1252 revienta con `UnicodeEncodeError` por la flecha `→` de la descripción de la migración
  (`install._names`) y deja la migración a medias. REQ-028.
- **Ficheros**: `src/local_delegate/entrypoint.py` (guarda `errors="replace"` en stdout/stderr
  no UTF-8, solo en la rama con argumentos; la rama stdio no se toca),
  `src/local_delegate/install.py` (`_names` con `->`), `tests/test_update.py` (las aserciones de la
  flecha), `tests/test_console_encoding.py`, `CHANGELOG.md` («Corrige»).
- **Revisión de otros caracteres**: catálogos `resources/i18n/*/*.json` y textos de
  `install`/`update`/`doctor` de este SDD. Fuera de cp1252 solo quedan textos del panel, del MCP y de
  `scripts/pair_sheet.py` (no van a la consola de la CLI) y la flecha del aviso de afinidad de
  `doctor` (previa a este SDD; la cubre la guarda general).
- **Tests primero**: el subproceso cp1252 en rojo en `main` por el `UnicodeEncodeError`.
- **Verificación**: suite completa con `pesado.sh` y `-n 2`, `ruff check` y `ruff format --check`,
  CodeQL a 0.

## 4. Matriz REQ → lote → prueba

| REQ | Lote | Prueba |
|---|---|---|
| 001 | L6 | `test_deprecations.py::test_registry_holds_exactly_the_seven_retired_names` |
| 002 | L2 | `test_deprecations.py::test_every_entry_follows_its_class_rule` |
| 003 | L2 | `test_deprecations.py` (lectores, registro sintético) |
| 004 | L2 | `test_deprecations.py::test_warning_text_*` |
| 005 | L1 | `test_fast_role_retired.py` (`reload_config`), `test_chains.py` |
| 006 | L1 | `test_cooldown.py::test_the_daemon_never_writes_the_old_file` |
| 007 | L1, L5 | tests de lectura dual existentes, sin cambios |
| 008 | L3, L6 | `test_retired_cli_names.py`, `test_cli_english.py` |
| 009 | L4 | `test_retired_env_names.py` |
| 010 | L5 | `test_hook_legacy_names.py`, `test_environment_isolation.py`, `test_hook_boundaries.py` |
| 011 | L1, L3–L6 | una fila por test, con gemelo |
| 012 | L2, L6, L7 | `test_checks.py`, `test_wiki.py` |
| 013 | L4 | `test_retired_env_names.py::test_local_status_lists_a_retired_variable` |
| 014 | L7 | `test_update.py::test_update_migrates_before_reporting`, `::test_migration_and_hook_repair_both_survive` |
| 015 | L7, L6 | `test_install.py::test_retired_name_migration_*` |
| 016 | L7 | `test_update.py`, `test_install.py` |
| 017 | L7 | centinela de valores, `os.environ` sin efecto en el plan |
| 018 | L7 | guardianes i18n, línea en inglés |
| 019 | L6 | horizonte 0.38.0, bump simulado con `importlib`, CHANGELOG `[0.38.0]` |
| 020 | L6 | cuatro formatos de `bump_version` |
| 021 | L1–L7 (+), L6 | `test_detect_spanish_names.py`, `evidence/L6/` |
| 022 | L3 | `test_completion_model.py`, `test_completion_render.py` |
| 023 | L6, L8 | test del CHANGELOG, `test_wiki.py`, `git grep` |
| 024 | todos, L9 | suite, ruff, CodeQL, `git grep`, `git ls-files --eol` |
| 025 | L9 | `verification.md` |
| 026 | L10 | `test_config_json_safety.py` (BOM: `install`, `update`, `~/.claude.json`, `doctor`) |
| 027 | L10 | `test_config_json_safety.py` (ilegible: hash idéntico, aviso, código ≠ 0, `doctor` sin excepción) |
| 028 | L11 | `test_console_encoding.py` (subproceso cp1252 con y sin BOM, guarda, stdio intacto) |

## 5. Gates

- **Antes de L1**: spec y plan aprobados (revisión de spec y de plan).
- **Por lote**: tests del lote verdes, `ruff check .` y `ruff format --check .`, suite completa
  verde con `pesado.sh`, test del detector verde, CodeQL 0 (incluido `note`), `gh pr checks` todo
  verde, fin de línea intacto, entrega con las llamadas `local_*`.
- **Antes de L9**: L1–L8 mezclados.
- **Cierre**: L9 registrado; revisión del resultado contra la spec; luego la PR de release (fuera).

## 6. Riesgos del plan y puntos de reapertura

- **Estados intermedios** (§1): sin release entre L3 y L6. Si se publicara una 0.37.x en ese hueco,
  el aviso diría «se retira en la 0.38.0» de algo que ya no funciona. Mitigación: no publicar entre
  L3 y L6.
- **`test_cli_renamed_names.py` en tres lotes seguidos**: L3 → L4 → L5 en serie; nunca en paralelo.
- **`name_exceptions.json` compartido**: choque textual entre L3 y L7; se resuelve rebasando y
  juntando (solo añadir).
- **Ciclo de imports** si la migración se saca de `install.py` o si `config` importa
  `deprecation_notices`: CodeQL `py/cyclic-import`. Reabrir la desviación 3 si `install.py` no lo
  admite.
- **`kind="migrate"` nuevo**: si `install.apply`, `describe()` o el resumen de `--dry-run` filtran
  por `kind`, hay que admitirlo ahí; lo cubren los tests de `--dry-run` de L7.
- **Ayuda del CLI** al quitar el `metavar`: puede cambiar el `usage`; si un test de ayuda o de
  autocompletado depende de él, se ajusta en L3.
- **Tests de shells reales del autocompletado** (L3) en CI: si el modelo cambia, los scripts
  generados cambian; se regeneran por la propia suite, no hay ficheros congelados.
- **Huellas de hooks** (L5): si se toca otro hook de `HASHED_HOOKS`, `--boundaries` también.

## 7. Fuera del plan

La PR de release (bump a 0.38.0, sellado de `UNRELEASED`, `[Unreleased]` → `[0.38.0]`, publicar,
instalar en esta PC, Socket), el backlog de `lanzar-tanda-afinidad.ps1`, el hallazgo de la
reparación de hooks sobre un `settings.json` ilegible y cualquier cambio en la lectura dual.

## 8. Cambios tras la revisión del plan

| Hallazgo | Resolución |
|---|---|
| B1 — excepciones del detector sin dueño | Tests sacan el nombre del registro donde se pueda; cada lote **añade** sus parejas (fichero compartido «solo añadir», columna `+`); L6 limpia. |
| B2 — L1 en rojo por `_FAST` y `legacy_write` | Reordenado: L1 quita `_FAST` y `legacy_write`; L2 es el modelo y quita `_looks_env`. |
| I1 — huella del hook | L5 corre `bump_version.py --boundaries`, edita `hook_hashes_after.json` y verifica con `test_hook_boundaries.py`. |
| I2 — chequeo previo y alias | Solo retirados; L3 prueba con registro sintético y alias vivo; L6 con el real. |
| I3 — lint distinto del CI | `uv run ruff check . && uv run ruff format --check .` en cada lote; huérfanos de `test_cli_renamed_names.py` nombrados en L3/L4. |
| M1 — `git grep` de L4 | Corregido: solo `hook_common.py` y `test_hook_legacy_names.py`. |
| M2 — `git grep` de L8 | Mismo patrón que REQ-023, ficheros aceptados listados en la PR. |
| M3 — aislamiento en L9 | `LOCAL_DELEGATE_LOG_DIR` exportado en todos los pasos, `LD_HOOK_TELEMETRY_LOG` vacío, `--claude-dir`, comprobación por nombre. |
| M4 — `uv run` dispara `uv sync` | Ejecutable del `.venv` o `uv run --no-sync`. |
| M5 — simulación del bump | `bump_version.py 0.38.0 --dry-run --no-lock` con `git status` limpio. |
| M6 — `server.main()` | Camino real `entrypoint.main`; probado con `local-delegate-mcp recalcular-coste`. |
| M7 — textos viejos tras L1 | L1 ajusta el docstring de `checks.py:1896-1902` y el comentario de `config.py:280-289`. |
| Ronda 2, R2-M1 / I8 — registro en el `LOG_DIR` real con HOME simulado | L7: directorio con la regla de `language_dir`/`completion_dir`; test sin `LOCAL_DELEGATE_LOG_DIR`. |
| Ronda 2, R2-M2 — `--dry-run` y registro/`.bak` | L7: test de que no existen tras `--dry-run`. |
| Ronda 2, R2-M3 — `--claude-dir` en L9 | Paso 7 con `--claude-dir` en los dos ejecutables. |
| Ronda 2, m14–m17 y nota de `failures` (spec) | L7: fecha por nombre, copia sin pisar ni sin escritura, filtro de notas solo para `settings.json`/interruptor, fallos en `failures`. |
| Ronda 2, m18 — BOM | Solo la migración; los fallos previos van al backlog. |
