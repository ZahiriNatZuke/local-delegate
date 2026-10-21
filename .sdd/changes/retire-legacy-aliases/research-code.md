# Investigación del código — retirada de los nombres vencidos en la 0.38.0

Mapa de impacto del **código** (no de la documentación) para el SDD `retire-legacy-aliases`.
Base: `main` en `6bbbfc5`, `pyproject.toml:3` = `0.37.0`. Todo `fichero:línea` es de ese commit.

## 1. Registro `DEPRECATED_NAMES` (`src/local_delegate/deprecations.py:51-91`)

Regla de vencimiento (`deprecations.py:106-134`): un alias vence en `introduced + 3 menores`
(`removal_version`); un retirado vence cuando la versión pasa de la serie de `warn_until`.

| # | kind | viejo | nuevo | introduced | warn_until | used_by_hooks | ¿vence en 0.38.0? | línea |
|---|---|---|---|---|---|---|---|---|
| 1 | retired | `LOCAL_DELEGATE_MODEL_FAST` | — | 0.30.0 | 0.37.0 | no | **sí** (0.38 > serie 0.37) | 54 |
| 2 | retired | `LOCAL_DELEGATE_MAX_CHARS_FAST` | — | 0.30.0 | 0.37.0 | no | **sí** | 55 |
| 3 | retired | `LOCAL_DELEGATE_FALLBACK_FAST` | — | 0.30.0 | 0.37.0 | no | **sí** | 56 |
| 4 | cli_command | `recalcular-coste` | `recompute-cost` | 0.35.0 | — | no | **sí** (`removal_version`=0.38.0) | 58 |
| 5 | cli_option | `--reiniciar-calibracion` | `--reset-calibration` | 0.35.0 | — | no | **sí** | 59 |
| 6 | env_var | `LD_HOOK_READ_BLOQUEAR` | `LD_HOOK_READ_BLOCK` | 0.35.0 | — | **sí** | **sí** | 60-62 |
| 7 | env_var | `LD_HOOK_READ_INTERRUPTOR` | `LD_HOOK_READ_SWITCH_FILE` | 0.35.0 | — | **sí** | **sí** | 63-69 |
| 8 | env_var | `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` | `LOCAL_DELEGATE_STRUCTURED_SUMMARY` | 0.35.0 | — | no | **sí** | 70-75 |
| 9 | env_var | `LOCAL_DELEGATE_COSTE_RESPALDO` | `LOCAL_DELEGATE_COST_FALLBACK` | 0.35.0 | — | no | **sí** | 76-78 |
| 10 | switch_file | `local-delegate-bloqueo-apagado` | `local-delegate-block-off` | 0.35.0 | — | **sí** | **sí** | 80-86 |
| 11 | legacy_write | `enfriamiento.json` | `cooldown.json` | 0.35.0 | — | no | **sí** | 90 |

**Las 11 entradas vencen en la 0.38.0**: el registro, tal como está, queda vacío. Comprobado con
la propia regla: `overdue("0.38.0")` las devuelve todas (el test
`tests/test_deprecations.py:100-102` ya fija que las `_FAST` vencen en 0.38.0).

El guardián `tests/test_deprecations.py:74-76` lee la versión de `pyproject.toml`; **este SDD se
mezcla con 0.37.0**, así que el guardián está verde antes y después. Hace falta un test que mida el
registro real contra `"0.38.0"` (ver §5), o el cambio no se comprueba hasta el PR de release.

## 2. Caminos del código que reconocen cada nombre vencido

### 2.1 CLI — subcomando `recalcular-coste` y opción `--reiniciar-calibracion` (entradas 4 y 5)

- `src/local_delegate/cli.py:386-392` `_warn_deprecated(old)`: imprime en `stderr`
  `cli.warning` + `deprecation_notices.warning_text(entry)`. Solo lo usan los dos alias.
- `cli.py:395-406` `_resolve_reset_calibration`: lee `args.legacy_reset_calibration`, avisa y
  rechaza valores distintos con `cli.recompute_cost.reset_mismatch`.
- `cli.py:430-433` `cmd_recompute_cost_legacy`: handler del subcomando viejo.
- `cli.py:1611-1614`: `sub.add_parser("recalcular-coste")` sin `help` (oculto) +
  `_add_recompute_cost_args`.
- `cli.py:1621-1622` `sub.metavar` filtra `_HIDDEN_COMMANDS`; `cli.py:1626-1627`
  `_HIDDEN_COMMANDS = frozenset({"recalcular-coste"})`. Sin alias ocultos, el `metavar` y la
  constante sobran (argparse ya pinta todo `choices`).
- `cli.py:1637-1644`: `--reiniciar-calibracion` con `dest="legacy_reset_calibration"`,
  `help=argparse.SUPPRESS`.
- i18n: `resources/i18n/{es,en}/cli.json:288` `cli.recompute_cost.reset_mismatch` queda sin uso.
  `cli.json:63-66` (`cli.deprecations.*`) siguen en uso si sobrevive algún aviso (checks/local_status).
- `src/local_delegate/completion.py:16-17,63,129-130,190,203`: oculta los `old` de kind
  `cli_command`/`cli_option`. Con el registro sin entradas CLI no oculta nada, pero el
  mecanismo sigue siendo correcto y genérico (lo prueba un test con registro sintético,
  `tests/test_completion_model.py:186-200`). **No hay que tocar `completion.py`**.

Hoy, con un nombre que no existe, argparse da su error genérico y sale con 2 (probado con
`build_parser().parse_args(...)`): `invalid choice: 'x' (choose from …)` y
`unrecognized arguments: --x five_hour`. Ojo: hoy la lista de `choose from` **incluye**
`recalcular-coste`, porque argparse la saca de `choices`, no del `metavar`. No hay subclase de
`ArgumentParser` ni `error()` propio; la entrada es `cli.run(argv)` (`cli.py:1830-1833`).

### 2.2 Variables de entorno en el paquete (`config.py`) (entradas 6–9 y 1–3)

- `config.py:69-71` `DEPRECATED_SEEN`; `config.py:74-87` `_env_alias`; `:90-93`
  `_env_alias_str`; `:96-101` `_env_alias_flag`. Solo los usan las cuatro variables renombradas.
- `config.py:248-249` `HOOK_READ_BLOCK = _env_alias_flag("LD_HOOK_READ_BLOCK", "LD_HOOK_READ_BLOQUEAR", False)`.
- `config.py:253-256` `HOOK_READ_SWITCH_FILE = _env_alias_str(..., "LD_HOOK_READ_INTERRUPTOR", "")`.
- `config.py:308-311` `STRUCTURED_SUMMARY = _env_alias_flag(..., "LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO", False)`.
- `config.py:548-549` `COST_FALLBACK = _env_alias_str(..., "LOCAL_DELEGATE_COSTE_RESPALDO", "")`.
- `config.py:279-297` rol `fast`: `DEPRECATED_ENV_VALUES` (lee **todas** las `env_vars()` del
  registro, alias y retiradas, por la puerta `_read`) y `RETIRED_FAST_ROLE_VARIABLES`. El
  comentario `chains.py:23` cita `RETIRED_FAST_ROLE_VARIABLES`.
- `server.py:5958-5971` `_describe_deprecated_names` (`local_status`): solo mira
  `config.DEPRECATED_SEEN`, es decir, **solo alias leídos con `_env_alias`**; nunca listó las
  retiradas `_FAST` puestas en el entorno del daemon. i18n `mcp.json:113` `mcp.status.deprecated`.

### 2.3 Hooks (`resources/hooks/hook_common.py`, atributo `-text`, LF)

- `hook_common.py:286-291` `DEPRECATED_HOOK_NAMES` (copia de `deprecations.hook_names()`, test
  de igualdad `tests/test_deprecations.py:170-176`).
- `hook_common.py:294-295` `DEPRECATED_SEEN`; `:297-307` `env_alias`.
- `hook_common.py:310-315` `switch_path()` (usa `env_alias(... "LD_HOOK_READ_INTERRUPTOR")` y
  `FILE_NAMES["switch_file"][1]`); `:318-320` `legacy_switch_path()`; `:323-332` `switch_on()`
  (apaga con el interruptor viejo y lo anota); `:335-343` `block_state()` (lee
  `LD_HOOK_READ_BLOQUEAR` por `env_alias`).
- `hook_common.py:101-104` `record()` añade `deprecated_names` a la telemetría si
  `DEPRECATED_SEEN` no está vacío.
- `hook_common.py:173-174` `FILE_NAMES["switch_file"]` = `(viejo, nuevo)`; copia de
  `legacy_names.py:516-517`, atadas por `tests/test_hook_legacy_names.py:61-65`.

### 2.4 Fichero interruptor (entrada 10)

- Hook: §2.3 (`legacy_switch_path`, `switch_on`).
- `doctor`: `checks.py:1933-1935` recorre `deprecations.switch_files()` (solo kind
  `switch_file`) y avisa si existe `~/.claude/<old>`.
- Tabla `legacy_names.py:517` (`FILE_NAMES["switch_file"]`): al retirar, `switch_file` sale de las
  dos tablas (o queda solo el nombre nuevo como constante en el hook).

### 2.5 Doble escritura de `enfriamiento.json` (entrada 11)

- `cooldown.py:12-17` docstring; `:53-54` `LEGACY_STATE_FILE, STATE_FILE`; `:61-64`
  `legacy_write_enabled()` (único uso de `deprecations` en el módulo, import en `:41`);
  `:126,136-139` parámetro `legacy_write` del constructor; `:288-289` llamada; `:298-307`
  `_write_legacy`.
- Por diseño, **borrar la entrada 11 ya apaga la doble escritura** (`legacy_write_enabled()` pasa a
  `False`, lo prueba `tests/test_cooldown.py:440-450`), pero deja código muerto: `_write_legacy`,
  el parámetro `legacy_write`, `legacy_write_enabled` y `legacy_names.old_keys`
  (`legacy_names.py:603-610`; su único uso es `cooldown.py:301`).
- **Se queda** (lectura dual, §3): `cooldown.py:130` `_legacy_path` y `:258-264` `_load` (lee el
  viejo traducido si no hay nuevo), y `hook_common.py:592-608` `cooled_model` (lee
  `enfriamiento.json` si no hay `cooldown.json`). Para eso `LEGACY_STATE_FILE` sigue haciendo
  falta.

### 2.6 Check `config.deprecated_names` (`checks.py:1892-1954`, registro `:2241-2244`)

Recorre: `config.DEPRECATED_ENV_VALUES` (shell, `:1922-1924`), `env` de `settings.json`
(`:1926-1931`, vía `deprecations.env_vars()`), interruptores viejos (`:1933-1935`), y la cola de
7 días de la telemetría de hooks (`:1937-1942`, función `deprecated_names_in_hook_telemetry`
`:1843-1889`). Pista `remove` para retirados y `rename` para alias (`:1946-1951`); pista extra
`current_roles` si alguno acaba en `_FAST` (`:1952-1953`). i18n `doctor.json:20,117-124`.
REQ-011 de la spec previa fija **25 checks** y el test de la wiki los cuenta: borrar el check
cambia ese número.

### 2.7 `deprecation_notices.py:15-24`

`warning_text`: retirado → `cli.deprecations.retired` con `version=entry.introduced` (no nombra
sucesor); alias → `cli.deprecations.deprecated` con `removed_in`/`removed_later`.

### 2.8 Detector de nombres en español

- `scripts/data/name_exceptions.json`, sección «Alias de compatibilidad»: **31 de 39** entradas son
  de estos nombres (`LD_HOOK_READ_BLOQUEAR` ×6, `LD_HOOK_READ_INTERRUPTOR` ×5,
  `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO` ×4, `LOCAL_DELEGATE_COSTE_RESPALDO` ×4,
  `recalcular-coste` ×4, `reiniciar-calibracion` ×1, `local-delegate-bloqueo-apagado` ×2,
  `enfriamiento.json` ×5) con motivo «alias de compatibilidad (REQ-001, REQ-002)… introduced».
  Las de `enfriamiento.json` en `hook_common.py`, `test_cooldown.py`, `test_fallback.py` y
  `test_f1_conformance.py` **siguen haciendo falta** (lectura dual), pero su motivo debe pasar a
  «lectura de formato viejo (REQ-006)». La de `scripts/build_corpus.py` (dato congelado) se queda.
- El guardián real es `tests/test_detect_spanish_names.py:237-247`
  (`outside_exceptions == 0`). **No hay comprobación de excepciones sobrantes**: una entrada que ya
  no casa no rompe nada; quitarla es higiene. Motivos válidos en
  `scripts/data/name_exceptions.README.md:16-18` («alias de compatibilidad… con su versión de
  retirada»): un nombre retirado que siga en `deprecations.py` (opción b/c) necesita un motivo que
  encaje (p. ej. el de los alias permanentes `delegacion-local`).
- Los tests del detector con `recalcular-coste` (`test_detect_spanish_names.py:44-46,185-205`)
  usan datos sintéticos: no dependen del registro.

### 2.9 Restos menores

- `scripts/_claude_bench.py:11`: docstring que aún dice `LD_HOOK_READ_INTERRUPTOR` (el código,
  `:79-80`, ya usa los nombres nuevos). Corregir.
- `scripts/build_corpus.py:453` y `benchmarks/catalogo-2026-09/cases.json:297`: término esperado
  de un caso congelado. **No se toca.**
- `install.py` no escribe ni migra estas variables (no aparecen en `install.py`).

## 3. Lo que NO tiene plazo y por tanto NO se retira

Evidencia: spec de `english-names-bilingual-output` y `CHANGELOG.md:396-432` (sección `[0.35.0]`,
tabla y «Plazos»).

- **REQ-006** (`spec.md:151-163`): «**Todo** lector de un formato de REQ-005 … acepta … los viejos
  y los nuevos … **sin fecha de caducidad**». Estado vigente: «si existen los dos, gana el nuevo».
  Por tanto **se quedan**: `cooldown._load` (`cooldown.py:258-264`), `hook_common.cooled_model`
  (`:592-608`), `legacy_names.FORMATS`/`normalize`/`read_key` y todas las tablas de valores
  (`legacy_names.py:26-71,73-…`), `COOLDOWN_EVENTS_FILE_NAMES` (`:528-531`, lo lee
  `scripts/measure_cooldown.py`), `ATTRIBUTION_FILE_PREFIXES`, `COST_AGGREGATES_FILE_NAMES`,
  `EXCLUDED_WINDOWS_FILE_NAMES`, ficheros de afinidad (`:537-566`). CHANGELOG `:419-420`: «se lee
  el viejo mientras no haya nuevo».
- **Temporales de hooks** (`FILE_NAMES` `block_notes`, `call_notes_dir`, `health_prefix`,
  `legacy_names.py:518-520` y `hook_common.py:175-177`, `legacy_block_notes_path` `:643-645`,
  `legacy_call_notes_dir` `:695-697`): CHANGELOG `:422` «el daemon lee los dos», sin plazo.
- **REQ-008** (`spec.md:200-202`): `cuota-statusline.jsonl` lo escribe el statusline del usuario;
  `QUOTA_STATUSLINE_FILE_NAMES` (`legacy_names.py:545`). CHANGELOG `:421` «el viejo vale sin plazo».
- **REQ-012/013** hook `anotar_llamada.py` y skill `delegacion-local`: `install.py:113-126`
  (`_RETIRED_SCRIPTS`, `_RETIRED_SKILLS`) son retirada por `install`, «alias permanente» en
  `name_exceptions.json:7-16`. No están en `DEPRECATED_NAMES`. **No se tocan.**
- **REQ-011** ids de checks (`config.coste`, grupos): CHANGELOG `:414` «sin alias». Nada que retirar.
- Cookie `ld_sesion` (`:415`): sin alias.
- Sí tienen plazo (CHANGELOG `:426-430`, REQ-004 `spec.md:111-119`, REQ-005 excepción
  `spec.md:143-147`, REQ-012 `spec.md:251-252`): subcomando, opción, cuatro variables, interruptor
  y la doble escritura de `enfriamiento.json`. Más las tres `_FAST` por su `warn_until`.

## 4. Opciones de diseño para «retirar»

Hecho clave: **varios de estos nombres los pone la persona en sitios que el paquete no toca**
(lanzador del daemon, `env` de `settings.json`, `~/.claude/`). Si dejan de leerse sin aviso, el
efecto es mudo, justo el fallo que el repo persigue (`checks.py:1900-1903`). Casos concretos:

- `LD_HOOK_READ_BLOQUEAR=1` puesto → en 0.38 el bloqueo de lectura **se apaga en silencio**.
- `~/.claude/local-delegate-bloqueo-apagado` → el bloqueo **se enciende** aunque la persona lo
  apagó.
- `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO`/`COSTE_RESPALDO` viven en el entorno **del daemon**, que
  `doctor` no ve; solo `local_status` podría avisar, y hoy solo lo hace por `DEPRECATED_SEEN`.
- Una máquina que salte de 0.34 a 0.38 (la Mac sigue en 0.34 según la memoria del proyecto) nunca
  vio el aviso de la 0.35–0.37.

### (a) Borrar las entradas y todo el código que las lee

- Pros: lo más simple; registro vacío; menos código; cumple al pie de la letra «se retiran».
- Contras: todos los fallos mudos de arriba; `doctor` deja de poder decir nada. El registro vacío
  en una línea **rompe la release**: `scripts/bump_version.py:213-227` `stamp_unreleased` busca
  `"\n)\n"` tras `DEPRECATED_NAMES:` y con `= ()` lanza `BumpError` («no se encontró el cierre»)
  —probado en memoria con el texto real—; con la tupla en varias líneas (`(\n    # …\n)`) pasa.
  Además rompe tests que usan el registro real como control (§5).

### (b) Convertir cada alias en `kind="retired"` con `warn_until` (como el rol `fast`)

- Pros: reutiliza la maquinaria existente (check, `warning_text`, horizonte); `doctor` avisa unas
  versiones de que el nombre sigue puesto y ya no hace nada; el registro no queda vacío.
- Contras con el modelo actual:
  1. Un retirado **no tiene `new`** (`tests/test_deprecations.py:49`, docstring
     `deprecations.py:17-19`): el aviso diría «X ya no tiene efecto» sin decir qué poner.
  2. `switch_files()` (`deprecations.py:144-146`) solo devuelve kind `switch_file`: un interruptor
     retirado **no lo vería el check**. `env_vars()` sí incluye retirados que parecen variable
     (`_looks_env`), pero no se puede distinguir un fichero de un subcomando por la forma
     (`recalcular-coste` y `local-delegate-bloqueo-apagado` son ambos kebab-case).
  3. Un CLI retirado no lo puede detectar `doctor`; solo el propio CLI al recibirlo.
  4. No tiene sentido para `enfriamiento.json` (nadie lo «pone») ni para las `_FAST`, que ya
     cumplieron su `warn_until`.

### (c) Recomendada: mixta — retirado **con sucesor** para lo que pone la persona, borrado para el resto

1. **Borrar del todo** (opción a) las tres `_FAST` (su `warn_until` venció: es lo acordado) y la
   entrada `legacy_write` de `enfriamiento.json`, con su código muerto (`_write_legacy`, parámetro
   `legacy_write`, `legacy_write_enabled`, `legacy_names.old_keys`, `RETIRED_FAST_ROLE_VARIABLES`,
   pista `current_roles` y su clave i18n, comentario `chains.py:23`). Si se quiere, quitar
   `legacy_write` de `KINDS`.
2. **Las 7 restantes** (subcomando, opción, 4 variables, interruptor) pasan a retiradas:
   `kind="retired"`, **`new` conservado**, `introduced="UNRELEASED"` (el bump la sella a 0.38.0,
   así el aviso dice «desde la 0.38.0»), `warn_until` a decidir en la spec (propuesta: `"0.40.0"`,
   tres menores como un alias), `used_by_hooks=False`, y un campo nuevo explícito, p. ej.
   `retired_from: str | None` con el kind que tenía (`env_var`, `switch_file`, `cli_command`,
   `cli_option`), para que cada lector filtre sin adivinar por la forma.
3. Ajustes:
   - `deprecations.py`: permitir `new` en retirados; `switch_files()` incluye retirados con
     `retired_from="switch_file"`; `env_vars()` por `retired_from`/kind en vez de `_looks_env`;
     `hook_names()` queda vacío (los hooks ya no leen nombres viejos).
   - `deprecation_notices.warning_text`: si el retirado tiene `new`, clave nueva (p. ej.
     `cli.deprecations.retired_renamed`: «{old} ya no tiene efecto desde la {version}: usa {new}»,
     es/en).
   - `checks.py:1946-1951`: pista `rename` también para retirados con `new`.
   - `server._describe_deprecated_names`: mirar las retiradas con valor en
     `config.DEPRECATED_ENV_VALUES` (hoy solo `DEPRECATED_SEEN`), para cubrir el entorno del
     daemon (`STRUCTURED_SUMMARY`, `COST_FALLBACK`).
   - `config.py`: las cuatro variables pasan a `_env_flag`/`_env`; desaparecen `_env_alias*` y
     `DEPRECATED_SEEN`; `DEPRECATED_ENV_VALUES` sigue leyendo los nombres viejos **solo para
     avisar** (sin efecto), por la puerta `_read`, así siguen en el inventario de aislamiento.
   - Hooks: `block_state`/`switch_path` leen solo los nombres nuevos (`os.environ.get`), fuera
     `env_alias`, `legacy_switch_path`, `DEPRECATED_SEEN`, `DEPRECATED_HOOK_NAMES` (o `= ()`), y
     la clave `deprecated_names` de `record()`. Con eso `deprecated_names_in_hook_telemetry` y la
     sección `read_by_hooks` del check quedan sin productor (solo eventos de hooks 0.35–0.37 de los
     últimos 7 días): decidir en la spec si se quitan o se dejan una versión.
   - CLI: quitar subparser/opción ocultos, `_warn_deprecated`, `cmd_recompute_cost_legacy`,
     `_resolve_reset_calibration` (pasa a leer `args.reset_calibration`), `_HIDDEN_COMMANDS` y el
     `metavar`, y la clave `reset_mismatch`. Para no dejar solo el error genérico de argparse, un
     **chequeo previo en `cli.run`** (`cli.py:1830`): si `argv` contiene un `old` retirado con
     `retired_from` CLI, imprimir «`recalcular-coste` ya no existe desde la 0.38.0: usa
     `recompute-cost`» por `cli.error` y salir con 2. Barato, sin tocar argparse, y no choca con
     `completion.py` (que rechaza alias de subparser, `completion.py:183-186`). Alternativa más
     simple: aceptar el error genérico (ya sale con 2 y lista `recompute-cost` en `choose from`).
     Nota: el `deprecated=` de argparse es de Python 3.13 y el paquete pide `>=3.11`
     (`pyproject.toml:6`); además sirve para avisar, no para retirar.

Por qué (c): cumple «se retiran en la 0.38.0» (ningún nombre viejo tiene efecto), mantiene el
principio de no fallar en silencio y reutiliza el check (los 25 checks de REQ-011 no cambian). El
registro nunca queda vacío, lo que esquiva el `BumpError`. Coste: un campo y una clave i18n más.
**Esto amplía lo que dijo la spec previa** («se retiran»): conviene que la spec nueva lo decida de
forma explícita.

## 5. Tests afectados y tests nuevos

### Hay que cambiarlos o borrarlos

- `tests/test_deprecations.py`
  - `:62-71` `test_registry_holds_the_three_fast_role_variables_as_retired` → borrar.
  - `:100-102` `test_real_fast_variables_expire_in_0_38_0` → sustituir por el control nuevo (abajo).
  - `:45-54` regla de clases → aceptar `new` en retirados y exigir `retired_from` (opción c).
  - `:111-116` texto del aviso → añadir caso de retirado con sucesor.
  - `:141-143` CHANGELOG: con `introduced="UNRELEASED"` la sección `[Unreleased]` tiene que nombrar
    el viejo **y** el nuevo de cada retirada (el test recorre `(e.old, e.new)`, `:133-136`).
  - `:170-176` igualdad hook ↔ registro: sigue valiendo con `()` en ambos lados.
  - `:190-207` tests de `config._env_alias` → borrar si se borra `_env_alias`.
  - `:257-278` tests de `bump_version`: siguen con su fixture sintética; añadir el caso de registro
    sin entradas `UNRELEASED`.
  - `:27` imports (`legacy_names`, `hook_common`) pueden quedar sin uso → CodeQL.
- `tests/test_cli_renamed_names.py` (entero sobre los alias: `:59` subcomando con aviso, `:70`
  versión 0.38.0, `:92` y `:110` opción, `:119` ayuda, `:152-193` variables en el paquete, `:231`
  y `:245` hook instalado, `:269-276` `local_status`) → reescribir como «nombres retirados»: el
  viejo no tiene efecto, el nuevo sí, el aviso nombra el sucesor.
- `tests/test_hook_legacy_names.py`: `:27` `OLD_SWITCH` sale de `FILE_NAMES` (si se quita
  `switch_file` de la tabla); `:67-73`, `:132-145`, `:195-212`, `:248-293` (interruptor viejo,
  eventos con `deprecated_names`, cola de 7 días, avisos de `doctor`) → invertir: el interruptor
  viejo ya **no** apaga y `doctor` lo avisa como retirado. `:76-130` (temporales) no cambian.
- `tests/test_cooldown.py:369-450`: `test_dual_write_leaves_the_same_state…` y
  `test_the_old_file_carries_the_old_keys…` → borrar; `:440-450`
  `test_without_its_legacy_write_entry…` → convertir en «no se escribe `enfriamiento.json`» sin
  monkeypatch; `test_an_old_state_from_a_previous_daemon…` y `test_with_both_files_the_new_one_wins`
  se quedan (REQ-006).
- `tests/test_fast_role_retired.py:143-203` (avisos de las `_FAST` y «salen del registro único»)
  → borrar o reorientar a una variable retirada nueva; `:41-133` (el rol no existe, error claro al
  pedir el modelo) se quedan.
- `tests/test_chains.py:202` espera `LOCAL_DELEGATE_FALLBACK_FAST` en `ENVIRONMENT_VARIABLES` →
  quitarla (deja de leerse).
- `tests/test_checks.py:1926-1960`: usan registro sintético; se mantienen. Añadir caso de retirado
  con sucesor (pista `rename`) e interruptor retirado.
- `tests/test_environment_isolation.py:192-212`: el control positivo exige
  `LD_HOOK_READ_BLOQUEAR` en `hook_names()` → borrar o reescribir (sin alias en hooks no hay
  nada que medir); la rama `with_alias` del escáner (`:107-108`) queda sin caso.
- `tests/test_completion_model.py:148-159` (`checked >= 2` con el registro real) y
  `tests/test_completion_render.py:256-262` (`len(retired) >= 2`) → fallan sin entradas CLI;
  pasar a registro sintético o comprobar directamente que `recalcular-coste` y
  `--reiniciar-calibracion` no están en el parser. `test_completion_model.py:47-49` sigue bien.
- `tests/test_cli_english.py:98-101` (docstring), `:223` caso `legacy_alias` y `:249` su assert
  → quitar o cambiar al mensaje del chequeo previo.
- `tests/test_density.py:163-164` y `tests/test_structured_summary.py:683` → quitar el nombre
  viejo del inventario esperado (o mantenerlo si `DEPRECATED_ENV_VALUES` lo sigue leyendo, opción c).
- `tests/test_quota.py:165`: solo docstring.

### Nuevos

1. **Control del horizonte con la versión de destino**: `overdue("0.38.0") == []` con el registro
   real (hoy daría las 11). Sin esto el SDD no se comprueba hasta el PR de release.
2. **Control positivo «ya no tiene efecto»**, uno por superficie: `LD_HOOK_READ_BLOQUEAR=1` solo
   → hook instalado con `block == "off_variable"`; interruptor viejo en `~/.claude` y bloqueo
   encendido → `block == "on"`; `LD_HOOK_READ_INTERRUPTOR` apuntando a un fichero existente → no
   apaga; `LOCAL_DELEGATE_RESUMEN_ESTRUCTURADO=1` en un proceso limpio →
   `STRUCTURED_SUMMARY is False`; `LOCAL_DELEGATE_COSTE_RESPALDO=x` → `COST_FALLBACK == ""`;
   `recalcular-coste` → salida 2 (con el mensaje del sucesor si se adopta el chequeo previo);
   `--reiniciar-calibracion` → salida 2. Cada uno con su gemelo con el nombre nuevo que sí surte
   efecto (que distinga).
3. `cooldown`: tras `enter/reenter/clear` no existe `enfriamiento.json`; y un `enfriamiento.json`
   viejo sin `cooldown.json` se sigue leyendo (ya existe: control de que no se rompió REQ-006).
4. `doctor` (opción c): retirado con sucesor en shell, en `env` de `settings.json` y como
   interruptor → `WARN` con «ya no tiene efecto desde la 0.38.0: usa …» y pista `rename`.
5. `local_status` (opción c): variable retirada en el entorno del proceso → aparece.
6. `bump_version`: `plan()` con un registro sin `UNRELEASED` y con tupla vacía multilínea no falla.

## 6. `scripts/bump_version.py` y otras comprobaciones atadas a versiones

- `bump_version.py:203-209` → `stamp_unreleased` (`:213-227`) cambia `"UNRELEASED"` solo dentro
  de la tupla `DEPRECATED_NAMES`. Con opción c, las 7 retiradas nuevas nacen `UNRELEASED` y el PR
  de release las sella a `0.38.0`. Con opción a y `= ()` en una línea, **`BumpError`** (§4).
- `grep 0\.38|warn_until`: solo aparecen en `deprecations.py`, en tests
  (`test_checks.py:1955` sintético; `test_cli_renamed_names.py:71,80`;
  `test_deprecations.py:84-113`; `test_detect_spanish_names.py:194` sintético) y en docs
  (`README.md:122`, `docs/wiki/Configuration.md:125,591`, CHANGELOG). `tests/test_pace.py:203`
  `0.38` es un número, no una versión. No hay otra comprobación atada a 0.38.0; nada de CI lee
  `warn_until`.

## 7. Riesgos

- **CodeQL `note`** (bloquea `main`): imports que quedan sin uso — `cooldown.py:41`
  (`deprecations` si se borra `legacy_write_enabled`), `cli.py:388` (`deprecation_notices`,
  `deprecations` si se borra `_warn_deprecated` y no hay chequeo previo), imports de tests
  (`test_deprecations.py:27`, `test_cooldown.py:442`, `test_hook_legacy_names.py`). Ciclo: el
  módulo `deprecations` no puede importar nada del paquete (`test_deprecations.py:280-294`,
  `py/cyclic-import` del PR #311); el texto nuevo va en `deprecation_notices`. No importar
  `deprecation_notices` desde `config` (sería `config → deprecation_notices → i18n → config`).
- **Código muerto** si se borra a medias: `_write_legacy`, `old_keys`, `_env_alias*`,
  `env_alias`, `DEPRECATED_SEEN` (dos copias), `_HIDDEN_COMMANDS`, `reset_mismatch`,
  `current_roles`, `deprecated_names_in_hook_telemetry`.
- **Fallo mudo** para quien tiene puesto un nombre viejo (§4), sobre todo la Mac (0.34 → 0.38).
- **`enfriamiento.json` rancio**: queda en `LOG_DIR` sin actualizarse. El daemon y los hooks ≥ 0.35
  leen antes `cooldown.json`, así que no les afecta; un hook ≤ 0.34 vería un estado viejo, acotado
  por `Tmax`. REQ-006 dice que el viejo queda intacto: no borrarlo.
- **Hash de los hooks**: cambiar `hook_common.py` cambia la huella que registra
  `bump_version --boundaries`; es normal en una release.
- **Fin de línea** (`git ls-files --eol`): **CRLF** → `src/local_delegate/cli.py`,
  `src/local_delegate/server.py`, `README.md`. **LF** → `deprecations.py`,
  `deprecation_notices.py`, `legacy_names.py`, `cooldown.py`, `config.py`, `checks.py`,
  `completion.py`, `chains.py`, `resources/hooks/hook_common.py` (además `attr/-text`), los seis
  `resources/i18n/{es,en}/{cli,doctor,mcp}.json`, `scripts/data/name_exceptions.json`,
  `scripts/bump_version.py`, `scripts/_claude_bench.py`, `CHANGELOG.md`,
  `docs/wiki/Configuration.md` y todos los tests citados (`test_deprecations`,
  `test_cli_renamed_names`, `test_checks`, `test_hook_legacy_names`, `test_cooldown`,
  `test_fast_role_retired`, `test_completion_model`, `test_completion_render`,
  `test_environment_isolation`, `test_cli_english`, `test_structured_summary`, `test_density`,
  `test_chains`, `test_quota`).

## Anexo — método

Lecturas con `grep`/`sed` en la tool Bash; simulación sin escribir nada en el repo de
`build_parser().parse_args` con nombres inexistentes y de `stamp_unreleased` con el registro vacío
(en memoria). Llamadas `local_*`: 1 (`local_summarize` de `tests/test_cli_renamed_names.py`). El
resto se leyó literal porque hacían falta líneas exactas para citar.
