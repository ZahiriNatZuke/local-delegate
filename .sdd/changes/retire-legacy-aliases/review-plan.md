# Revisión adversarial del plan — SDD `retire-legacy-aliases`

Revisado: `plan.md` contra `spec.md`, `research.md` (D1–D7) y el código de `main` en `6bbbfc5`.
Revisor: agente de revisión del plan, 2026-10-21. No se modificó nada salvo este fichero.

**Veredicto: `block`** — 2 bloqueantes, 3 importantes, 7 menores.

Lo que está bien y no hace falta tocar:

- **Fin de línea**: los 39 ficheros de la tabla `plan.md:61-103` coinciden con `git ls-files --eol`
  (CRLF: `cli.py`, `server.py`, `install.py`, `README.md`, `Integration-install.md`; `-text` en los
  dos hooks; el resto LF).
- **Versión**: el plan no sube `pyproject.toml` (`plan.md:5`, `:307`, `:371-375`).
- **Comandos pesados**: la suite va por `pesado.sh` con `-n 2` (`plan.md:122-125`).
- **Verificación en vivo**: L9 trabaja en un HOME simulado y no toca el daemon. Lo confirma el
  código: con `--home` simulado `update` no reinicia nada (`update.py:20-21`, `:920-922`), no
  actualiza `uv tool` (solo avisa, `update.py:594`), y el autocompletado y el idioma escriben en el
  `LOCAL_DELEGATE_LOG_DIR` temporal (`shell_profiles.py:461-478`).
- **Cobertura**: los 25 requisitos tienen lote y prueba en la matriz (`plan.md:316-342`).
- **Dependencias**: L2 ∥ L3 ∥ L7 no comparten ningún fichero de la tabla; L3 → L4 → L5 van en
  serie sobre `test_cli_renamed_names.py`.

---

## BLOQUEANTES

### B1. Ningún lote tiene permiso para tocar las excepciones del detector, pero cuatro lotes las necesitan

- **Evidencia**: el detector aparta los nombres por pareja **(nombre, fichero)**
  (`scripts/data/name_exceptions.json:133-190`; el test
  `tests/test_detect_spanish_names.py:187` lo confirma) y
  `test_repo_has_no_spanish_name_outside_the_exception_list`
  (`tests/test_detect_spanish_names.py:237-251`) falla con cualquier hallazgo que no esté en la
  lista. Hoy solo están apartados, por ejemplo, `recalcular-coste` en `cli.py`, `deprecations.py`,
  `test_cli_renamed_names.py` y `test_cli_english.py`, y `local-delegate-bloqueo-apagado` en
  `deprecations.py` y `hook_common.py`.
- **Qué se rompe**: el plan solo deja tocar `name_exceptions.json` a L6 (`plan.md:82`). Pero:
  - **L2** escribe `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` en `tests/test_fast_role_retired.py`, para
    el gemelo de REQ-005 / fila 9 de REQ-011 (`plan.md:174-175`);
  - **L3** crea `tests/test_retired_cli_names.py` con `recalcular-coste` y `--reiniciar-calibracion`;
  - **L4** crea `tests/test_retired_env_names.py` con las dos variables viejas;
  - **L5** necesita `local-delegate-bloqueo-apagado` como literal en `tests/test_hook_legacy_names.py`,
    porque `:27` lo sacaba de `hook_common.FILE_NAMES["switch_file"]` y esa clave desaparece;
  - **L7** pone nombres viejos en `tests/test_install.py` y `tests/test_update.py`, y quizá en los
    comentarios de `install.py`.

  En cada uno de esos lotes la suite queda en **rojo** en `main`. Además, L2, L3 y L7 corren en
  paralelo y tendrían que editar el mismo JSON.
- **Corrección**:
  1. Cada lote añade las parejas (nombre, fichero) de los ficheros que crea o cambia, con el motivo
     nuevo de REQ-021. Añadir `name_exceptions.json` (y `name_exceptions.README.md` para la
     enmienda del motivo, que pasaría a L1 o L2) a la columna de L2, L3, L4, L5 y L7.
  2. Declarar el fichero como **compartido solo para añadir**: si dos PR paralelas chocan, se
     rebasa y se juntan las dos entradas.
  3. L6 se queda con la limpieza: quitar las entradas viejas y cambiar los motivos. Las entradas
     viejas que sobran **no** rompen el test, así que borrar puede esperar a L6.
  4. Alternativa más barata en los tests: sacar el nombre viejo del registro
     (`next(e.old for e in deprecations.DEPRECATED_NAMES if e.new == "...")`) en vez de escribirlo
     literal. Así no hace falta excepción. Un único literal por fichero, si hace falta para que el
     test discrimine, sí la necesita.

### B2. L1, tal como está escrito, deja la suite en rojo: el registro real todavía lleva las `_FAST` y `legacy_write`

- **Evidencia**:
  - Hoy `env_vars()` encuentra las `_FAST` **solo** por la forma del nombre
    (`deprecations.py:163-167`, rama `e.is_retired and _looks_env(e.old)`).
  - `config.DEPRECATED_ENV_VALUES` y `RETIRED_FAST_ROLE_VARIABLES` salen de esa función
    (`config.py:290-297`).
  - `checks._probe_deprecated_names` también la usa (`checks.py:1929`).
- **Qué se rompe**: L1 pide filtrar `env_vars()` «por clase efectiva» y quitar `_looks_env`
  (`plan.md:150-152`) dejando las `_FAST` como retirados sin sucesor (sin `retired_from`). Su clase
  efectiva es entonces `retired`, así que salen de `env_vars()`. Con eso caen en L1 tests que son de
  L2:
  - `tests/test_fast_role_retired.py:186-191` (espera `WARN` con `_MAX_CHARS_FAST` en `env`);
  - `tests/test_fast_role_retired.py:203` (`RETIRED_FAST_ROLE_VARIABLES`);
  - `tests/test_chains.py:208` (`_FALLBACK_FAST` en `ENVIRONMENT_VARIABLES`).

  Pasa lo mismo con la regla de clases: REQ-002 saca `legacy_write` de `KINDS` y deja la clase 1 en
  `{cli_command, cli_option, env_var, switch_file}`. Pero la entrada real `legacy_write`
  (`deprecations.py:90`) sigue en el registro hasta L2. Así,
  `test_every_entry_follows_its_class_rule`, que recorre el registro **real** (`plan.md:157`), falla
  en L1. El plan pasa `KINDS` a L2 (`plan.md:63`), pero no dice cómo trata L1 esa entrada.
- **Corrección** (una de dos):
  - **(a) Recomendada**: invertir L1 y L2. L2 no necesita el modelo nuevo: su gemelo de la fila 9
    (`LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` → `WARN`) ya da `WARN` hoy como alias. Así L1 parte de
    un registro sin `_FAST` ni `legacy_write`, `_looks_env` desaparece de verdad en L1 y la regla
    de clases se aplica sin excepciones. L3 y L7 siguen dependiendo de L1. Queda L2 → L1 → (L3 ∥ L7).
  - **(b)** Si se mantiene el orden, el plan debe decir en L1 de forma explícita que la clase 2
    (retirado sin sucesor) **sigue** entrando en `env_vars()` por `_looks_env` y que la regla de
    clases acepta `legacy_write` hasta L2. En L2 hay que quitar las dos cosas y añadir `_looks_env`
    al `git grep` de `plan.md:177` y a REQ-024.

---

## IMPORTANTES

### I1. L5 cambia un hook con huella y no regenera `hook_hashes_after.json`

- **Evidencia**: `suggest_delegate_read.py` está en `HASHED_HOOKS` (`scripts/bump_version.py:71-75`).
  `tests/test_hook_boundaries.py:66-72` falla si la huella actual de ese hook no está en
  `scripts/data/hook_hashes_after.json`: «corre `uv run python scripts/bump_version.py
  --boundaries`». L5 cambia el docstring de ese hook (`plan.md:216-217`; REQ-010) y solo dice que la
  huella «cambia (esperado, se anota en la PR)» (`plan.md:228-229`).
- **Qué se rompe**: la suite queda en rojo en L5.
- **Corrección**: en L5, añadir `scripts/data/hook_hashes_after.json` a la tabla de ficheros (LF)
  y la tarea `uv run python scripts/bump_version.py --boundaries`. Esa orden **solo une** huellas
  (`bump_version.py:98-114`) y no toca la versión. La verificación de L5 debe incluir
  `tests/test_hook_boundaries.py`. Cambiar `hook_common.py` no afecta a la huella, porque solo se
  hashea el script del hook (`hook_common.py:63-77`).

### I2. El chequeo previo a argparse rechaza también a los alias: el mecanismo no vale para un alias futuro (defecto de la spec que el plan aprovecha)

- **Evidencia**:
  - REQ-008 rechaza todo nombre con clase efectiva `cli_command`/`cli_option` (`spec.md:181-185`),
    y según REQ-002/003 eso incluye a los **alias** de la clase 1.
  - REQ-022 dice que el mecanismo «sigue sirviendo para un alias futuro» (`spec.md:388-389`).
  - El plan cuenta con ese rechazo de alias para que L3 dé código 2 antes de que L6 voltee las
    entradas (`plan.md:30-31`, `:189-190`).
- **Qué se rompe**: un subcomando renombrado en el futuro y registrado como alias, que debería
  funcionar con aviso durante 3 menores, saldría con código 2 sin ejecutarse.
- **Corrección**:
  - `_reject_retired_names` debe filtrar los **retirados con sucesor**
    (`entry.is_retired and effective_kind(entry) in {cli_command, cli_option}`), no todo
    `cli_entries()`.
  - En L3, las filas 6–7 se prueban con un registro **sintético** (monkeypatch de
    `DEPRECATED_NAMES` con las dos entradas como retiradas), y en L6 se añade la aserción con el
    registro real.
  - Entre L3 y L6, `recalcular-coste` da el error genérico de argparse. Sin release de por medio es
    aceptable, igual que el estado intermedio que ya admite `plan.md:30`.
  - Añadir un caso sintético: «alias `cli_command` → el chequeo no lo rechaza».
  - Avisar al revisor de la spec para que corrija REQ-008.

### I3. Las verificaciones de lint no reproducen el CI

- **Evidencia**: el CI corre `uv run ruff check .` y el chequeo de formato de ruff
  (`.github/workflows/ci.yml:43-46`; ruff está en `pyproject.toml:107`). El plan solo pide
  `ruff check --select F401 <ficheros>` y «si ruff está en el proyecto» (`plan.md:126-128`).
- **Qué se rompe**: los recortes parciales de `tests/test_cli_renamed_names.py` en L3 y L4 dejan
  sin uso imports como `replace`, `_delegation_with_n`, `subagent` o `recompute`
  (`tests/test_cli_renamed_names.py:15-23`), y helpers como `:125-150`, que cita `DEPRECATED_SEEN`.
  Si nadie lo mira antes, el lote cae en el CI y en CodeQL `py/unused-import`.
- **Corrección**: en «Reglas de ejecución», antes de abrir cada PR, exigir
  `uv run ruff check . && uv run ruff format --check .`, más la revisión manual de helpers sin
  llamadas. Para L3 y L4, nombrar los imports y helpers de `test_cli_renamed_names.py` que quedan
  huérfanos.

---

## MENORES

- **M1. El `git grep` de L4 espera un resultado equivocado** (`plan.md:211-212`). Dice que solo
  quedarán apariciones en `hook_common.py`, pero `tests/test_hook_legacy_names.py:53-149` también
  usa `hook_common.DEPRECATED_SEEN`, y `tests/test_cli_renamed_names.py:134` cita
  `config.DEPRECATED_SEEN`. Corrección: «solo `hook_common.py` y `tests/test_hook_legacy_names.py`;
  ni una en `config.py`, `server.py` ni `test_cli_renamed_names.py`».
- **M2. El `git grep` de L8 no es el de la spec.** El de `plan.md:286` busca «hasta la 0.37» y
  REQ-023 (`spec.md:420`) busca «0.37.x». Además, «sin resultados sobre estos nombres» no se puede
  comprobar a máquina. Corrección: usar el patrón de la spec más el del plan, y listar los ficheros
  donde se acepta algún resultado (la sección `[0.35.0]` del CHANGELOG no entra, porque el grep es
  sobre `README.md docs/`).
- **M3. En L9 el entorno no está aislado del todo.**
  - Exportar `LOCAL_DELEGATE_LOG_DIR` para **todos** los pasos, incluido el 7 (`recalcular-coste`).
    Si el chequeo fallara, el recálculo escribiría en el `LOG_DIR` real. Pasar también
    `--claude-dir "$H/.claude"`.
  - Vaciar `LD_HOOK_TELEMETRY_LOG` en esa shell (`config.py:227-228`): si está puesta, `doctor` lee
    la telemetría real y el paso 6 («sin esos avisos») dependería de datos ajenos.
  - Comprobar al empezar que la shell no tiene ninguno de los 7 nombres viejos, solo por nombre.
- **M4. `uv run` en L9 puede disparar un `uv sync`**, que es pesado según el brief. Corrección:
  usar `uv run --no-sync` o el ejecutable del `.venv`, o meterlo en `pesado.sh`.
- **M5. Simulación del bump en L6** (`plan.md:250-252`). `scripts/` no tiene `__init__.py`: la
  importación funciona como paquete de espacio de nombres, pero es frágil. Es más claro usar
  `uv run python scripts/bump_version.py 0.38.0 --dry-run --no-lock`, que ya existe
  (`bump_version.py:286-288`), con `git status` limpio antes y después.
- **M6. Nombre equivocado**: «Comprobar que `server.main()` reenvía a `cli.run`»
  (`plan.md:191`). El punto de entrada de los dos ejecutables es `local_delegate:main` →
  `entrypoint.main` (`pyproject.toml:74-75`, `entrypoint.py:47`). Hay que comprobar ese camino con
  `local-delegate-mcp recalcular-coste`.
- **M7. Texto que queda viejo tras L2**: el docstring de `checks.py:1896-1902` sigue hablando de las
  tres variables `fast` y de `LOCAL_DELEGATE_MODEL_FAST`. No rompe nada (ni el detector ni el grep
  de REQ-024 lo ven), pero L2 debería ajustarlo. También el comentario de `config.py:280-289` sobre
  el rol `fast`.

---

## Requisitos sin lote o sin verificación

Ninguno sin lote. La verificación de REQ-021 (`plan.md:338`) queda incompleta mientras no se
resuelva B1: tal como está, el test del detector se rompe antes de L6.

## Estados intermedios en `main`

- Rojos: L1 (B2), L2, L3, L4, L5 y L7 (B1), y L5 (I1).
- Funcional, sin release: entre L3 y L6 el aviso dice «se retira en la 0.38.0» de algo que ya no
  funciona. Ya está aceptado en `plan.md:30-31` y `:355-357`.

## Llamadas `local_*`

0 hechas. Las tools se cargaron (`ToolSearch`), pero no hubo paso donde ahorraran contexto con
fiabilidad. Las citas necesitaban `fichero:línea` literales, así que leí franjas concretas, y el
cruce entre lotes y código exigía criterio. El `plan.md` (25 KB) se leyó por franjas porque había
que citarlo línea a línea; un resumen no habría servido.

---

## Ronda 2 (2026-10-21)

Revisado de nuevo `plan.md` (483 líneas) contra `spec.md` corregida y el código de `main`.

**Veredicto: `approve`** — los 12 hallazgos de la ronda 1 están resueltos; quedan 3 menores nuevos,
que no bloquean.

### Comprobación de los hallazgos de la ronda 1

- **B1 — excepciones del detector: resuelto.**
  - Los tests sacan el nombre viejo del registro donde se puede (`plan.md:139-141`).
  - Columna `+` de «solo añadir» en L1–L5 y L7, y limpieza en L6 (`plan.md:96`, `:147-150`).
  - Test del detector en el gate de cada lote (`plan.md:151`, `:438`).
  - L5 cubre el literal `local-delegate-bloqueo-apagado` (`plan.md:280-282`).
- **B2 — orden de L1 y L2: resuelto.**
  - L1 quita las `_FAST` y `legacy_write`. Tras L1 el registro real son los 7 alias, que cumplen la
    regla de clases actual (`tests/test_deprecations.py:45-54`), así que la suite sigue verde
    (`plan.md:190-191`).
  - L2 quita `_looks_env`. Su único uso es `deprecations.py:166`, y tras L1 ya no hay retirados sin
    sucesor (`plan.md:214-215`).
  - Los tests que dependían de las `_FAST` están en L1: `test_fast_role_retired.py:143-203`,
    `test_chains.py:202-208` y `test_deprecations.py:62-71,100-102`.
- **I1 — huella del hook: resuelto.** En L5 están `hook_hashes_after.json`, la orden
  `--boundaries` y `test_hook_boundaries.py` (`plan.md:88`, `:285-291`).
- **I2 — chequeo previo y alias: resuelto.**
  - El filtro es `cli_entries() if e.is_retired` (`plan.md:238-239`).
  - Hay caso sintético de alias vivo, y L6 prueba con el registro real (`plan.md:244-247`, `:313-314`).
  - El estado intermedio está declarado (`plan.md:35-38`).
- **I3 — lint: resuelto.**
  - `ruff check .` y `ruff format --check .` en cada lote y en el gate (`plan.md:158-160`, `:437`).
  - Los huérfanos de `test_cli_renamed_names.py` están nombrados (`plan.md:249-250`, `:266-267`).
- **M1–M7: resueltos** (`plan.md:269-271`, `:370-371`, `:376-399`, `:318-320`, `:240-242`,
  `:185-186`).
  - `update --version` existe (`cli.py:1778-1782`), así que el paso 4 de L9 es viable.
  - La verificación en vivo no toca el daemon: `--no-restart` más HOME simulado
    (`update.py:916-922`).
  - Con `LOCAL_DELEGATE_LOG_DIR` exportado y `LD_HOOK_TELEMETRY_LOG=` (`config.py:227-228` lo
    convierte en `None`), no lee ni escribe nada real; el `~/.claude/settings.json` real solo se
    mira por su hash.

### Propiedad y paralelo

- Tras L2, L7 corre de hecho en paralelo con L3, L4 y L5.
- Ficheros de L7: `install.py`, `update.py`, `checks.py`, `test_checks.py`, `doctor.json`,
  `install.json`, `test_install.py` y `test_update.py`.
- Ninguno lleva `●` en L3–L5. El único compartido es `name_exceptions.json` (`+`).
- L5 no toca `checks.py` (`plan.md:285`). L6 espera a L5 y a L7. Bien.

### Hallazgos nuevos

- **R2-M1 (MENOR) — dónde escribe `update --home` simulado el registro de la migración.**
  - El registro `<LOG_DIR>/retired-names-migration.json` se escribe en `config.LOG_DIR`
    (`plan.md:332`).
  - Con `--home` simulado y **sin** `LOCAL_DELEGATE_LOG_DIR`, `update --home <tmp>` lo escribiría
    en el `LOG_DIR` real.
  - Va contra la regla que ya sigue el autocompletado (`shell_profiles.py:461-478`, desviación 2 de
    `cli-completion`: con HOME simulado, `<home>/.local/share/local-delegate`).
  - Corrección: derivar el directorio igual que `completion_dir` (o reutilizar esa función), con
    un test de HOME simulado sin la variable.
- **R2-M2 (MENOR) — falta comprobar que `--dry-run` no crea el registro.**
  - Las pruebas de `--dry-run` de L7 comparan los bytes de `settings.json` y del interruptor
    (`plan.md:346`).
  - Corrección: comprobar también que `retired-names-migration.json` y
    `settings.json.retired-names*.bak` **no** existen tras `--dry-run`, en `update` y en `install`.
- **R2-M3 (MENOR) — `local-delegate-mcp recalcular-coste` sin `--claude-dir` en L9.**
  - El paso 7 lo lanza sin la opción (`plan.md:394-395`). Si el chequeo fallara, leería los
    transcripts reales (solo lectura; escribiría en el `LOG_DIR` temporal).
  - Corrección: añadir `--claude-dir "$H/.claude"` también ahí.

### Llamadas `local_*` (ronda 2)

0. El plan corregido había que contrastarlo línea a línea con el código y la spec para citar
`fichero:línea`. Lo leí por franjas, que el bloqueo de lectura permite, y con `grep`/`sed`
puntuales sobre el código. No quedan procesos vivos.
