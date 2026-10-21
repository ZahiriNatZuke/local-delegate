# Revisión adversarial de la spec — `retire-legacy-aliases`

Revisor: agente de revisión de spec (2026-10-21). Base: `main` en `6bbbfc5`. Revisado `spec.md` contra
`research.md` (D1–D7), `research-code.md`, `research-upgrade.md` y el código real.

**Veredicto: `block`** — 1 bloqueante, 7 importantes, 13 menores.

La spec está bien armada: cubre D1–D7, sus referencias `fichero:línea` son casi todas exactas y los
controles positivos por superficie (REQ-011) están bien planteados. Lo que bloquea es una
contradicción sobre **cuándo** se aplica la migración en `update`, que decide si el test de REQ-014
puede pasar y abre una vía para que el registro de hooks se pierda en silencio. El resto son
correcciones de redacción y de pruebas que conviene meter antes del plan.

---

## BLOQUEANTE

### B1. La migración en `update`: «primer paso del plan» o «antes de los checks» (REQ-014 y REQ-016 se contradicen)

- `spec.md:278-279` (REQ-014): «la migración se aplica antes de correr los checks».
- `spec.md:315` (REQ-016): «`update` la planifica siempre […], como primer paso».
- Código: `update.py:862-863` corre `checks.run_all(ctx)` **antes** de planificar nada; las notas
  salen de esos resultados en `plan_repairs` (`update.py:350-357`), y todo se aplica después
  (`update.py:897-899`). Si la migración es solo la primera acción del plan, los checks ya vieron
  el `env` viejo y la nota «renombra LD_HOOK_READ_BLOQUEAR a …» sale igual: el test
  `test_update_migrates_before_reporting` (`spec.md:282-284`) falla. Si en cambio se aplica antes de
  `checks.run_all`, eso es una escritura **antes** del encabezado y del diagnóstico, que en
  `--dry-run` no puede ocurrir: el comportamiento de las dos ramas diverge y la spec no lo fija.
- Riesgo añadido: `plan_repairs` deduplica por `(kind, target)` (`update.py:341-348`). Si quien
  implemente mete la acción de migración en esa lista con `kind="settings"` y destino
  `~/.claude/settings.json`, choca con la acción que registra los hooks (`install.py:1881-1895`,
  también `settings` sobre el mismo fichero) y **una de las dos se descarta**. Si cae el registro
  de hooks, el hook de lectura desaparece y el bloqueo se apaga sin aviso: justo el fallo mudo que
  este SDD quiere evitar.

**Corrección propuesta.** Fijar en REQ-014/REQ-016 una sola semántica, por ejemplo:
1. `run_update` llama a `install.plan_retired_name_migration(opts.home)` **fuera** de
   `plan_repairs` (sin pasar por su deduplicación) y pone sus acciones **al principio** de
   `actions`.
2. La acción usa un `kind` propio (p. ej. `migrate`), no `settings`, y su `run` relee
   `settings.json` en el momento de aplicar (como `_run_settings`, `install.py:1875-1879`), así
   se combina con el registro de hooks que viene después.
3. Las notas de `update` **filtran** las pistas `rename` de los nombres que cubre una acción de
   migración planificada (en las dos ramas, con `--dry-run` o sin él), en vez de exigir que la
   migración «se aplique antes de los checks». Así el test no depende del orden de escritura.
4. Añadir a REQ-016 un test: con `env` viejo **y** hooks desactualizados en el mismo HOME
   simulado, tras `update` existen las dos cosas: la clave renombrada y el registro de hooks
   nuevo.

---

## IMPORTANTES

### I1. El chequeo del CLI previo a argparse rechazaría también un alias futuro (REQ-008 frente a REQ-022)

- `spec.md:181-185` (REQ-008): sale con código 2 si el token es el `old` de una entrada con clase
  efectiva `cli_command`/`cli_option`, tomada de `deprecations.cli_entries()`.
- `spec.md:113-120` (REQ-003): `cli_entries()` devuelve **alias y** retirados con sucesor.
- `spec.md:388-389` (REQ-022): «el mecanismo sigue sirviendo para un alias futuro».

Con un alias futuro registrado, el CLI lo rechazaría con código 2 aunque debería funcionar con
aviso. Hoy no rompe nada (no quedan alias), pero la spec se contradice.
**Corrección:** REQ-008 filtra `entry.is_retired` (o `entry.kind == "retired"`) sobre
`cli_entries()`, y se añade un caso sintético: un alias `cli_command` registrado **no** da 2.

### I2. La puerta de «código muerto» de REQ-024 no puede dar 0

`spec.md:432-435` exige que `git grep` de estos nombres en `src/`, `scripts/` y `tests/` dé 0. Hay
coincidencias que no tienen nada que ver con lo que se retira:
- `old_keys`: `tests/test_affinity.py:623` (`test_frozen_verdict_footprints_with_old_keys…`),
  `tests/test_analyze_benchmark.py:1591,1641-1642,1678-1713` (`old_keys`, `_old_keys`).
- `hook_names`: `install.py:94,1683,1716` (`packaged_hook_names`), `tests/test_install.py:544-585`
  (`test_hook_names_come_from_the_package…`).
- `env_alias` coincide dentro de `_env_alias` (bien) pero también puede coincidir en nombres nuevos.
- `legacy_write`: `scripts/data/name_exceptions.json:170-180` (motivos en prosa que REQ-021 reescribe;
  conviene decirlo).

**Corrección:** usar patrones con límite de palabra y calificados, por ejemplo
`git grep -nwE "_env_alias(_str|_flag)?|DEPRECATED_SEEN|env_alias|legacy_switch_path|_write_legacy|legacy_write_enabled|RETIRED_FAST_ROLE_VARIABLES|_HIDDEN_COMMANDS|reset_mismatch|current_roles|used_by_hooks|DEPRECATED_HOOK_NAMES"`
más `git grep -n "legacy_names.old_keys\|def old_keys\|deprecations.hook_names\|def hook_names"`.

### I3. El test del bump simulado (REQ-019) falla tal como está redactado

`spec.md:350-352`: «ejecuta el texto resultante en un espacio de nombres aislado». `deprecations.py`
usa `from __future__ import annotations` y `@dataclass` (`deprecations.py:22-44`). Comprobado en
esta máquina: `exec` con `{"__name__": "<algo>"}` que no está en `sys.modules` revienta con
`AttributeError: 'NoneType' object has no attribute '__dict__'` (dataclasses busca el módulo de la
clase en `sys.modules` para resolver anotaciones en texto).
**Corrección:** fijar el método: escribir el texto sellado en `tmp_path` y cargarlo con
`importlib.util.spec_from_file_location` + `module_from_spec`, registrándolo en `sys.modules`
(con `monkeypatch.setitem`) antes de `exec_module`, como ya hace `bump_version._hook_common`
(`scripts/bump_version.py:82-89`). Leer el fichero con normalización a LF como `bump_version._read`
(`:117-124`), no con `read_text` a secas.

### I4. Tras migrar, la cola de telemetría de 7 días sigue pidiendo «renombra» (REQ-012, REQ-014, REQ-025)

`checks.py:1938-1943` añade una advertencia por cada nombre que aparezca en la cola de 7 días de
`LD_HOOK_TELEMETRY_LOG` (`config.py:227-228`). En una máquina real en 0.35–0.37 con telemetría
encendida y `LD_HOOK_READ_BLOQUEAR` en `env`, los hooks viejos dejaron eventos con
`deprecated_names`; después de que `update` migre, **durante 7 días** `doctor` y las notas de
`update` seguirán diciendo «renombra LD_HOOK_READ_BLOQUEAR a …» aunque ya no esté en ningún sitio.
Choca con la intención de REQ-014 («no pide renombrarlo a mano») y con el paso 5 de REQ-025, que
solo pasa porque el HOME simulado no tiene telemetría.
**Corrección (elegir una):** (a) en la rama de telemetría, ignorar los eventos con `ts` anterior a
la última escritura de los hooks (`mtime` de `hook_common.py` instalado); o (b) mostrar la rama de
telemetría con su pista propia («visto por hooks antiguos; se apaga solo en ≤ 7 días si ya
corriste `update`») y excluirla de las notas de `update`. Añadir un test: evento de telemetría con
nombre viejo + `env` ya migrado → el resultado no dice «renombra» como acción pendiente (o lo dice
con la pista nueva).

### I5. REQ-017 afirma que `doctor` avisa de sitios que no mira

`spec.md:328-330`: «De lo que vive ahí avisa `doctor` (REQ-012)», refiriéndose a variables del
sistema, perfiles, lanzador del daemon, `settings.local.json`, `~/.claude.json` y `~/.codex`. Pero el
check solo mira la shell donde corre, el `env` de `~/.claude/settings.json`, ficheros en `~/.claude/`
y la telemetría (`checks.py:1922-1943`; `spec.md:253-255`). El lanzador y la entrada MCP stdio solo
los ve `local_status` (REQ-013), y `settings.local.json`, `~/.claude.json` o los `.claude/settings*.json`
de proyecto no los ve nadie (con REQ-010 los hooks dejan de detectar). D4 dice lo mismo
(`research.md:46-47`), pero la spec lo concreta y debe ser exacta.
**Corrección:** reescribir esa frase: «del perfil de la shell avisa `doctor` si la variable está en
la shell donde corre; del lanzador del daemon y del servidor MCP por stdio avisa `local_status`
(REQ-013); `settings.local.json`, `~/.claude.json` y los `settings` de proyecto no se miran: lo dice
el CHANGELOG». Añadir esa línea a la lista de REQ-023.

### I6. El escenario «`settings.json` roto» promete algo que el código no cumple

`spec.md:504-508`: «`settings.json` no se toca». Pero si en la misma corrida `update` repara los
hooks (caso típico de la Mac 0.34), `_run_settings` hace `merge_hook_settings(_read_json(path), …)`
y `_read_json` devuelve `{}` para un JSON inválido (`install.py:261-266`, `:1875-1877`): el
`settings.json` roto **se sobrescribe** con solo los hooks (queda el `.bak`). Es un comportamiento
previo, pero el escenario, tal como está, es falso.
**Corrección:** que el escenario y REQ-016 digan «**la migración** no toca `settings.json`» y que el
test aísle la migración (sin reparación de hooks en el plan). Abrir un punto de backlog para el
problema previo: registrar hooks sobre un `settings.json` ilegible no debería sobrescribirlo.

### I7. El control de REQ-005 y la fila 9 de REQ-011 no fijan el mecanismo, y sin él la prueba no distingue

`spec.md:146-148`: «con solo `LOCAL_DELEGATE_MODEL_FAST` en la shell el check da `OK`».
`config.DEPRECATED_ENV_VALUES` se calcula al importar (`config.py:290-292`): poner la variable con
`monkeypatch.setenv` sin recargar da `OK` **también hoy**, y el gemelo `WARN` fallaría por la misma
razón. Además, el check lee `settings.json` del HOME y la telemetría de `LD_HOOK_TELEMETRY_LOG`: si
no se aíslan, el `OK` puede depender de la máquina.
**Corrección:** exigir el fixture `reload_config` (ya existe, `tests/test_fast_role_retired.py:41`) o
un subproceso para los dos casos, con `Context(home=tmp_path)` y `LD_HOOK_TELEMETRY_LOG` vacío o
temporal. Lo mismo para REQ-013 (`spec.md:271-274`): el valor debe llegar por `reload_config`, no
por `setenv` a secas.

---

## MENORES

1. **Tests existentes que se rompen y la spec no menciona.** `tests/test_deprecations.py:62-71`
   (`test_registry_holds_the_three_fast_role_variables_as_retired`), `:100-102`
   (`test_real_fast_variables_expire_in_0_38_0`, que con el registro nuevo se invierte),
   `:45-54` (ya citado), `tests/test_fast_role_retired.py:143-196` (avisos de las `_FAST`, que deben
   salir o invertirse) y `tests/test_cooldown.py:440-449`
   (`test_without_its_legacy_write_entry…`). Listarlos en REQ-005/REQ-006/REQ-019.
2. **Línea equivocada.** El import de `deprecations` en `cooldown.py` está en la `:40`, no en la
   `:41` (`spec.md:154`), y hay que conservar `config` y `legacy_names` en esa línea. Además,
   el docstring de `cooldown.py:14` y el comentario de `:53` hablan de `legacy_write`.
3. **Fila 6 de REQ-011: «no se escribe nada» no distingue.** `recompute-cost` sobre un
   `--claude-dir` vacío puede no escribir nada tampoco. Usar un espía sobre `recompute.run`
   (llamado con el nombre nuevo, no llamado con el viejo) y pasar siempre `--claude-dir` temporal:
   el defecto es el `~/.claude` real (`cli.py:418`).
4. **Documentación que falta en REQ-023.** `docs/wiki/Configuration.md:39` todavía lista `_FAST`
   con su tope `12000`, y `docs/wiki/Troubleshooting.md:92` cita `…/_FAST/…` como rol vigente.
5. **D7 «tabla de checks atada a su test».** REQ-023 cambia la fila de `Integration-install.md:453`,
   pero `tests/test_wiki.py` solo cuenta checks (`:47`); nada comprueba el texto de la fila. Añadir
   un assert de que la fila ya no nombra las `_FAST` y sí dice «ya no tiene efecto», o quitar «atada a
   su test» de la trazabilidad.
6. **REQ-025: aislar también la telemetría.** El paso 5 («`doctor` ya no avisa») depende de
   `LD_HOOK_TELEMETRY_LOG`, que en esta PC está en el `env` de `settings.json` y podría heredarse en
   la shell. Exigir `LD_HOOK_TELEMETRY_LOG` vacío o temporal y `--version` explícito en `update`
   para no salir a PyPI.
7. **«Nada más cambia en `settings.json`»** (`spec.md:299`) no es cierto en formato: `_write_json`
   reescribe todo con `indent=2` (`install.py:269-274`). Decir «nada más cambia en su contenido
   (igualdad JSON)» y que el test (a) compare con `json.loads`.
8. **La copia `settings.json.retired-names.bak`** guarda el `env` completo (puede tener claves) y no se
   borra nunca; y «solo si no existe ya» hace que una segunda migración en otra versión (alguien
   vuelve a poner un nombre viejo a mano) pierda su original. Documentarlo en el CHANGELOG y decidir
   explícitamente si se acepta.
9. **REQ-017: «no lee `os.environ`» no se puede probar así.** Reformular como prueba que distinga:
   con los nombres viejos en `os.environ` y **no** en `settings.json`, el plan sale vacío.
10. **Referencia ambigua.** «los 25 checks de REQ-011 previo» (`spec.md:252-253`): decir de qué spec
    (¿`cli-completion`?) o citar `tests/test_wiki.py:47`.
11. **`settings.json` ilegible o con BOM** (lo deja así PowerShell 5.1 con `-Encoding UTF8`): la
    migración no lo toca y el check de `doctor` ignora el motivo (`checks.py:1928`, `_reason`) y puede
    decir `OK` con nombres viejos dentro. Que el check diga `WARN`/`UNKNOWN` en ese caso, o al menos
    documentarlo como caso límite.
12. **Chequeo de opciones del CLI.** «Un token anterior a `--` igual al `old`» (`spec.md:182-183`)
    también salta cuando es el **valor** de otra opción (`--label --reiniciar-calibracion`), y una
    abreviatura (`--reiniciar`) ya no dispara el chequeo y cae en el error genérico de argparse.
    Añadirlos a «Casos límite» con el comportamiento elegido.
13. **REQ-015 migra también alias vivos** («alias o retirado con sucesor», `spec.md:290-291`). Hoy no
    hay ninguno, pero para un alias futuro reescribiría el `settings.json` de la persona mientras el
    nombre viejo aún funciona. Decidir si es lo deseado o limitarlo a retirados.

---

## Sobre probar contra la 0.38.0 sin subir la versión

El enfoque es sólido: el guardián de siempre mira `pyproject.toml` (0.37.0) y no prueba nada aquí;
`overdue("0.38.0")` con el registro real más el bump simulado con `stamp_unreleased` cubren lo que
cambiará en la PR de release (las 7 entradas a `introduced="0.38.0"`, texto «desde la 0.38.0»,
horizonte hasta la 0.40.x y control positivo a la 0.41.0). Con dos condiciones: el arreglo de I3
(cargar el texto sellado como módulo de verdad) y que la prueba del CHANGELOG
(`tests/test_deprecations.py:126-143`) también se ejecute sobre un CHANGELOG simulado con
`[Unreleased]` renombrado a `[0.38.0]`, para comprobar que tras la release las 7 entradas siguen
encontrando su sección.

## Cobertura de D1–D7

| Decisión | Requisitos | Estado |
|---|---|---|
| D1 | REQ-005, REQ-006 | cubierta (faltan tests a borrar, menor 1) |
| D2 | REQ-001–004, REQ-012, REQ-013 | cubierta (I4, I5) |
| D3 | REQ-008 | cubierta (I1) |
| D4 | REQ-014–018 | cubierta, con la contradicción B1 |
| D5 | REQ-007 | cubierta |
| D6 | REQ-019, REQ-020 | cubierta (I3) |
| D7 | REQ-021–023 | cubierta (menores 4 y 5) |

Afirmaciones sobre el código comprobadas y correctas: `deprecations.py:51-91`, `checks.py:1892-1953`,
`update.py:345-351`, `config.py:69-101,248-256,293-297,308-311,548-549`, `cooldown.py:61-64,126,136-139,298-307`,
`legacy_names.py:516-517,603-610`, `hook_common.py:101-104,173-174,286-343`, `chains.py:23`,
`bump_version.py:213-227` (con `= ()` en una línea no hay `"\n)\n"` y lanza `BumpError`),
`install.py:227-228` (la `.bak` genérica se pisa en la misma corrida). Fin de línea: `cli.py` e
`install.py` son CRLF; `hook_common.py` lleva `-text`; el resto de los citados, LF.

---

## Ronda 2 (2026-10-21)

**Veredicto: `approve`.** Los 21 hallazgos de la ronda 1 quedan resueltos en el texto y, donde lo
comprobé contra el código, la resolución es correcta. Las correcciones meten **1 hallazgo importante
y 5 menores** nuevos. Ninguno bloquea: son ajustes de redacción que conviene meter en la spec o en
el plan antes de L7, y el importante es obligatorio.

### Comprobación de lo pedido

- **Acción `migrate` fuera de `plan_repairs` y orden migrar → checks → notas** (REQ-014,
  `spec.md:308-322`). Encaja con el código. `run_update` imprime el encabezado y luego llama a
  `checks.run_all` (`update.py:856-863`), así que la migración cabe entre las dos cosas. La
  deduplicación de `plan_repairs` (`update.py:341-348`) ya no la alcanza. El `kind` propio evita el
  choque con la acción `settings` del registro de hooks (`install.py:1881`). Y como `_run_settings`
  relee al aplicar (`install.py:1875-1877`), las dos escrituras se combinan. El test
  `test_migration_and_hook_repair_both_survive` cubre justo el riesgo de la ronda 1.
- **Búsqueda de código muerto** (REQ-024). La corrí sobre el árbol actual: todas las coincidencias
  caen en ficheros que este SDD edita o borra, sin falsos positivos. Puede dar 0 de verdad.
- **Bump simulado con `importlib`** (REQ-019): correcto, y el CHANGELOG simulado con `[0.38.0]`
  cierra lo que faltaba.
- **Registro `retired-names-migration.json` y criterio de telemetría** (REQ-012 y REQ-015).
  Funciona como idea y tiene control positivo (evento posterior y otro nombre). Tiene los fallos
  I8 y m14.
- **Copia de seguridad con fecha** (REQ-015, `spec.md:344-347`): bien orientada, con los huecos m15
  y m16.

### Hallazgos nuevos

**IMPORTANTE**

- **I8. Con un HOME simulado, el registro de migración se escribiría en el `LOG_DIR` real.**
  REQ-015 (`spec.md:348-350`) escribe `<LOG_DIR>/retired-names-migration.json`, y la firma es
  `plan_retired_name_migration(home)`, sin directorio de datos. `config.LOG_DIR` no depende de
  `--home` (`config.py:216`). Por eso existe la regla de `install.language_dir`
  (`install.py:1592-1603`): con un HOME simulado no se toca el `LOG_DIR`, salvo que haya
  `opts.data_dir` o `LOCAL_DELEGATE_LOG_DIR` explícito. Sin esa regla, un
  `update --home <tmp> --no-restart` hecho para probar dejaría en la máquina real un registro que
  **silencia** los avisos de telemetría de esos nombres durante 7 días. REQ-025 solo se libra porque
  exporta `LOCAL_DELEGATE_LOG_DIR`.
  **Corrección:** la función recibe `data_dir` (o el `install.Options`) y aplica la misma regla que
  `language_dir`. Si no hay directorio de datos permitido, migra igual pero no escribe el registro,
  y lo dice. El check lee el registro de `ctx.log_dir` o, si no hay, de `config.LOG_DIR`, como los
  demás probes (`checks.py:1996`). Test: con HOME simulado y sin `LOCAL_DELEGATE_LOG_DIR`, el
  `LOG_DIR` real (con `monkeypatch`) no recibe el fichero.

**MENORES**

- **m14. El registro guarda una sola fecha para todos los nombres.** REQ-015 lo define como `ts` y
  `names`, pero REQ-012 compara con «la última migración que cubrió **ese** nombre». Si una segunda
  migración, de otro nombre, sobrescribe el fichero, los eventos del primer nombre vuelven a
  avisar. **Corrección:** guardar una fecha por nombre (`{"names": {"<viejo>": "<ts>"}}`) y
  fusionar al escribir. Añadir el caso de dos migraciones sucesivas al test.
- **m15. La copia con fecha también se puede pisar.** `settings.json.retired-names.<AAAAMMDDhhmmss>.bak`
  tiene resolución de segundos: dos migraciones en el mismo segundo (el propio test (e) si hace una
  tercera) pisarían la copia con fecha, contra lo de «nunca pisa». Tampoco dice si la hora es local
  o UTC. **Corrección:** crear la copia con apertura exclusiva (`open(..., "xb")`) y un sufijo
  `-1`, `-2`… si ya existe, y fijar UTC.
- **m16. Copia sin escritura.** Falta decir que la copia de `settings.json` solo se hace si esa
  corrida **escribe** en `settings.json`. Si solo se renombra el interruptor, o si el `env` es
  ilegible, no debe aparecer ninguna `.bak`. Añadirlo al test (c).
- **m17. El filtro de notas por nombre esconde la pista de la shell.** REQ-014 paso 3 quita la
  pista `rename` de todo nombre que la migración cubra. Si el mismo nombre está **también** en la
  shell (que no se migra), `update` deja de decir que hay que renombrarlo allí; el check guarda la
  pista, pero las notas de `update` solo imprimen `fix_hint` (`update.py:350-357`). Sin
  `--dry-run` la migración ya se aplicó antes de los checks y no hace falta filtrar nada.
  **Corrección:** filtrar solo en `--dry-run`, y solo las pistas que vengan de `settings.json` o de
  `~/.claude/`.
- **m18. El BOM: la migración lo lee, pero `doctor` y el registro de hooks no.** REQ-015 lee con
  `utf-8-sig` y conserva el BOM. Pero `checks.read_json` falla con BOM (`checks.py:483-498`), así
  que el check avisará siempre de «no se pudo leer», también después de migrar. Y `_read_json` del
  instalador (`install.py:261-266`) devuelve `{}` con BOM: si en la misma corrida se reparan los
  hooks, `_run_settings` reescribe `settings.json` solo con los hooks y pierde la migración y todo
  lo demás. Es el problema previo de la ronda 1, pero ahora lo dispara justo el caso que la spec
  dice soportar. **Corrección:** leer con `utf-8-sig` en `checks.read_text`/`read_json` y en
  `install._read_json`. Es un cambio de una línea en cada sitio y encaja en L7. Si se descarta,
  quitar de REQ-015 y de «Casos límite» la promesa sobre el BOM.

Nota menor sin número: la migración que se aplica antes de los checks tiene que sumar sus fallos a
`failures`, para que `update` salga con 1 si falla (`update.py:897-913`). Que lo diga REQ-014.

### Llamadas `local_*` de esta ronda

0: la spec se revisó por franjas porque había que citar líneas exactas, y las comprobaciones contra
el código fueron lecturas cortas con `sed` y `grep`. En la ronda 1 hubo 2 llamadas
(`local_summarize` sobre `research-code.md` y `research-upgrade.md`).
