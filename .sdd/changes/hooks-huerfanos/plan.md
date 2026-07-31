# Implementation plan: Detectar y retirar los scripts de hooks huerfanos de instalaciones anteriores

## Approach

Este change entra por el camino que ya está trazado —registro de checks + tabla `REPAIRS` +
acciones de `install`— y no inventa mecanismo. Lo único nuevo de verdad es que **por primera vez el
repo borra ficheros del HOME del usuario**, así que el diseño se ordena alrededor de esa operación.

Tres decisiones la acotan:

1. **La lista de «qué es nuestro» se deriva de `resources/hooks/*.py`**, el directorio empaquetado
   que `install` copia. Es la definición de qué instalamos, y por tanto de qué podemos retirar. Una
   constante paralela se desincronizaría —de hecho `_SCRIPT_NAMES` ya está desincronizada: tiene
   tres nombres y no incluye `hook_common.py`, que es uno de los huérfanos reales.
2. **Se borran ficheros, uno a uno, por nombre exacto, solo en la raíz.** Nada de `rmtree`, nada de
   globs, nada de tocar `local-delegate/`.
3. **El probe no borra.** Mira y pone el `fix_hint`; quien escribe es `install`/`update`. Es el
   contrato del registro, y romperlo aquí —justo en el check destructivo— sería romperlo donde más
   duele.

## Ordered tasks

### 1. La definición de «nuestros scripts»

- **Ficheros:** `src/local_delegate/install.py`
- **Requisitos:** REQ-004
- **Qué:** función `packaged_hook_names()` que devuelve los nombres de los `.py` de
  `resources_dir()/"hooks"`. Ordenada, y tolerante: si el directorio no se puede listar devuelve
  vacío —y con vacío **no se borra nada**, que es la degradación segura.
- **Verificación:** test de que incluye `hook_common.py` y los tres `suggest_*.py`, y de que no
  incluye `__pycache__`.

### 2. El probe

- **Ficheros:** `src/local_delegate/checks.py`
- **Requisitos:** REQ-001..REQ-003, REQ-005, REQ-006
- **Qué:** `_probe_hook_orphans(ctx)`: `unknown` si Claude Code no está o el directorio no se
  lista; `ok` si no hay ninguno; `warn` con el número y la ruta si los hay. Entrada en `CHECKS`
  justo después de `scaffold.hook_files`.
- **Cuidado:** mira `ctx.claude_dir / "hooks"` (la **raíz**), no `ctx.hooks_dir` (que es el
  subdirectorio). Confundirlos haría que el check reportara la instalación buena como huérfana —y
  entonces `install` la borraría. Es el peor fallo posible de este change.
- **Verificación:** tests de los tres estados + el de árbol byte a byte que ya existe.

### 3. La acción de retirado

- **Ficheros:** `src/local_delegate/install.py`
- **Requisitos:** REQ-007..REQ-011
- **Qué:** `_prune_orphans_action(hooks_root)` que devuelve una `Action` (kind `prune`) cuyo `_run`
  borra los ficheros nuestros de esa raíz y devuelve el resumen. Se planifica **solo si hay
  alguno** (REQ-010) y solo con el componente `hooks` y el target `claude`.
- **Cuidados:** `p.is_file()` antes de borrar (REQ del borde del directorio homónimo); `try/except`
  por fichero para saltarse el que no se pueda (REQ-011); el `--dry-run` sale gratis porque
  `install.apply` ya no ejecuta el `_run` en ese modo — **hay que comprobarlo, no suponerlo**.
- **Verificación:** tests de AC-2 y AC-3 con `snapshot()`.
- **Rollback:** los ficheros borrados son copias de recursos empaquetados; reinstalar los repone
  en el sitio correcto. No hay dato del usuario en juego (`telemetry.jsonl` no se toca).

### 4. La entrada en `REPAIRS`

- **Ficheros:** `src/local_delegate/update.py`
- **Requisitos:** REQ-012
- **Qué:** `Repair("scaffold.hook_orphans", (checks.WARN,), frozenset({"hooks"}),
  frozenset({"claude"}), why="scripts de hooks de una instalación anterior")`.
- **Cuidado:** `plan_repairs` **deduplica por `(kind, target)`**, y esto es importante aquí: con
  `hook_files` también en `missing`, se llamaría dos veces a `plan_install(components={"hooks"})`,
  que emite la copia del árbol **y** el prune. La deduplicación existente ya lo cubre, pero hay que
  verificarlo con un test, no darlo por hecho.
- **Verificación:** test de `plan_repairs` con el check en `warn`.

### 5. Los textos del tamaño del registro

- **Ficheros:** `src/local_delegate/checks.py`
- **Requisitos:** REQ-013
- **Qué:** «trece» → «catorce» en los cuatro sitios; el test `_NUMERO` ya contempla `14`.

### 6. Tests

- **Ficheros:** `tests/test_checks.py`, `tests/test_install.py`, `tests/test_update.py`
- **Requisitos:** todos
- **Qué:** los cuatro escenarios, más los bordes: directorio con el nombre de un script, fichero
  no borrable, y —**el más importante**— un test que compruebe que `hooks/local-delegate/` queda
  intacto tras el prune.
- **Verificación al revés:** cambiar el probe para que mire `ctx.hooks_dir` en vez de la raíz debe
  hacer fallar los tests; y quitar el `is_file()` debe hacer fallar el del directorio homónimo.

### 7. CHANGELOG y wiki

- **Ficheros:** `CHANGELOG.md`, `docs/wiki/Integration-install.md`
- **Requisitos:** REQ-014, REQ-015
- **Qué:** entrada nueva; en la wiki, «trece piezas» → «catorce» y la fila de la tabla.
- **Cuidado:** CRLF en el CHANGELOG.

### 8. CI local y ejecución real

- **Requisitos:** todos
- **Qué:** los cuatro pasos del CI; `doctor` real (esta máquina **tiene** los cuatro huérfanos, así
  que debe salir el `[WARN]`); `install --dry-run --home <sim>` sobre un árbol simulado que
  reproduzca el caso; y, **si el usuario lo autoriza**, `install` real en esta máquina para
  limpiarla de verdad.

## Test strategy

- **Unit:** el probe en sus tres estados; `packaged_hook_names()`.
- **Integration:** `plan_install` + `apply` sobre un `tmp_path` que reproduce el caso completo
  —huérfanos + `telemetry.jsonl` + `__pycache__` + hook de terceros + `local-delegate/`— y
  `snapshot()` para comprobar **qué sobrevivió**, que es más fuerte que comprobar qué se borró.
- **End-to-end:** esta máquina, que es el caso real.
- **Verificación al revés:** obligatoria, arriba.
- **Seguridad:** es el punto entero. Sin dependencias, sin red, sin subprocesos.

## Migration and compatibility

- **Compatibilidad:** ninguna instalación correcta se ve afectada — sin huérfanos, el check es
  `ok` y no se planifica nada.
- **Irreversibilidad:** el borrado no tiene `.bak`, a diferencia de las escrituras de `install`.
  Se acepta porque lo borrado son **copias de ficheros que el paquete vuelve a instalar**, no
  configuración editada por el usuario. Anotado como decisión, no como olvido.

## Revisión adversarial del plan

Cinco hallazgos; dos bloqueantes, todos incorporados arriba.

- **R-1 (BLOQUEANTE) — confundir la raíz con el subdirectorio borraría la instalación buena.**
  `ctx.hooks_dir` **ya es** `~/.claude/hooks/local-delegate`, no la raíz. Un probe que mire ahí
  reportaría los cuatro scripts recién instalados como huérfanos, e `install` los borraría acto
  seguido — dejando la máquina sin hooks y en bucle. Es el peor fallo posible aquí, y está a un
  identificador de distancia. Mitigación: la ruta se escribe explícita (`claude_dir / "hooks"`),
  hay un test dedicado a que `local-delegate/` sobreviva, y la verificación al revés incluye
  justo esta permutación.
- **R-2 (BLOQUEANTE) — el `--dry-run` no se puede dar por supuesto.** El resto de las acciones son
  escrituras y `apply` las salta; pero si el prune hiciera el borrado al **planificar** (por
  ejemplo, calculando la lista con un `unlink` de paso), `--dry-run` borraría igual. La regla del
  módulo es que `plan_*` **no toca disco** (`install.py:393`), y aquí hay que respetarla y probarla
  con `snapshot()`, no confiar en ella.
- **R-3 — `_SCRIPT_NAMES` no vale como fuente y hay que decir por qué.** Tiene tres nombres y el
  huérfano `hook_common.py` no está entre ellos: usarla dejaría un fichero atrás en todas las
  máquinas. De ahí `packaged_hook_names()`.
- **R-4 — la deduplicación de `plan_repairs` entra en juego.** Con `hook_orphans` en `warn` y
  `hook_files` en `missing`, `update` llamaría dos veces a `plan_install` y emitiría dos veces la
  copia del árbol y el prune. La deduplicación por `(kind, target)` que se añadió en el change B
  ya lo cubre; se verifica con un test en vez de suponerlo.
- **R-5 — el borrado no deja `.bak`.** Decisión consciente: lo que se borra son copias de recursos
  empaquetados, reponibles con `install`. Queda escrito para que no parezca un olvido.

## Plan review

- [x] Cada requisito mapea a una tarea y a una verificación.
- [x] **La operación destructiva tiene salvaguardas explícitas**: nombre exacto, solo raíz, solo
      ficheros, lista derivada del paquete, degradación segura a «no borrar nada», y un test que
      comprueba qué **sobrevivió**.
- [x] Sin dependencias ni configuración nuevas.
- [x] Sin trabajo ajeno: no se toca `settings.json` (ya está bien), ni `telemetry.jsonl`, ni
      `__pycache__`.
