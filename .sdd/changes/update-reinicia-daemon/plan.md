# Plan de implementación — `local-delegate update`

> **Reescrito el 2026-07-30**, después de que el change **A** (`checks-andamiaje`) se publicara en
> la 0.14.0. El plan anterior traía su propia capa de diagnóstico (`survey()`); esa capa ya existe
> y es `checks.CHECKS`. La spec (17 requisitos) **no cambia**: lo que cambia es de dónde sale la
> maquinaria.

## Approach

**`update` no vuelve a preguntarle nada al sistema por su cuenta.** El diagnóstico es una llamada a
`checks.run_all(ctx)` y lo que `update` aporta encima son dos cosas que A dejó deliberadamente
fuera: **decidir qué arreglar** y **escribir**. Es el contrato literal que dejó A —*`probe` mira,
`fix_hint` dice, y quien escribe es B*—, así que este change no añade ni un `probe` nuevo.

Tres capas, con la misma forma `plan_* / apply` de `install.py` para que `--dry-run` salga gratis:

1. **Diagnóstico** — `checks.run_all(checks.Context(home=..., ...))`. Cero lógica propia.
2. **Selección** — una tabla estática `REPAIRS` que traduce `check.id` → qué acción lo arregla, y
   **bajo qué estados**. Sin efectos.
3. **Ejecución** — `install.apply(actions, dry_run=...)`, que ya existe.

### La tabla `REPAIRS`, que es el corazón del change

| `check.id` | Lo arregla | Repara en |
|---|---|---|
| `scaffold.hook_files` | `plan_install` con `components={"hooks"}`, `targets={"claude"}` | `missing` |
| `scaffold.hook_settings` | igual | `missing`, **`warn`** |
| `scaffold.skill` | `components={"skill"}`, `targets={"claude"}` | `missing`, `warn` |
| `scaffold.memory` | `components={"memory"}`, targets **presentes** | `missing` |
| `scaffold.mcp_claude` | `components={"mcp"}`, `targets={"claude"}` | `missing` |
| `scaffold.mcp_codex` | `components={"mcp"}`, `targets={"codex"}` | `missing` |
| `service.daemon` | la rutina de daemon (tarea 4), no `install` | `missing`, **`warn`** |
| `cli.path`, `client.presence`, `service.backend`, `backend.*` | **nada**: se imprime su `fix_hint` y ya | — |

Dos decisiones que hay que leer con cuidado, porque son las que impiden que `update` rompa cosas:

- **`unknown` nunca repara. Jamás.** Es la regla que A dejó escrita (REQ-003 de aquel change) y la
  razón de que exista: un cliente ausente, un fichero sin permisos o un JSON ilegible se reportan
  `unknown`, y repararlos sería sobrescribir configuración ajena a ciegas.
- **`warn` repara solo en tres casos, y son los tres en que el aviso significa «es nuestro y está
  viejo»**: hooks en formato de instalación anterior, skill sin `SKILL.md`, y daemon sirviendo una
  versión distinta de la instalada. **`scaffold.mcp_codex` en `warn` NO se toca**: ese aviso dice
  «entrada puesta a mano, sin marcadores», o sea configuración del usuario. Pisarla sería
  exactamente el fallo contra el que A puso la regla.

`plan_install` se invoca **una vez por par `(componente, target)`** que haga falta, en vez de una
sola vez con todos los conjuntos: es puro y barato, y así reparar Codex no arrastra a Claude.

**Las acciones se deduplican por `(kind, target)` antes de devolver el plan**, y no es cosmético:
`plan_install` con `components={"hooks"}` emite **dos** acciones —la copia del árbol y el registro en
`settings.json`—, y `_copy_tree_action` (`install.py:347-354`) hace `shutil.rmtree(dst)` antes de
copiar. Sin deduplicar, tener `hook_files` y `hook_settings` los dos en `missing` planificaría **dos
borrados** del mismo directorio.

### Con `--home` simulado no se toca ningún servicio

El daemon y el backend no viven en el HOME: `_probe_daemon` pregunta a `config.WEB_HOST/WEB_PORT` y
el backend a `config.BASE_URL`, y ninguno se deriva de `ctx.home`. Así que `update --home /tmp/prueba`
reiniciaría **el daemon de verdad** de la máquina, que para un flag documentado como «para pruebas»
es un efecto sorpresa y contradice el espíritu de la spec. Regla: **con `--home` distinto del HOME
real se reportan los estados de los servicios y se omite toda acción sobre ellos**, diciendo por qué.

### La idempotencia sale sola, no se programa

REQ-003 pide que una segunda ejecución no produzca cambios. Con este diseño no hay que hacer nada
para conseguirlo: si la primera pasada arregló todo, en la segunda los `probe` responden `ok` y la
tabla no selecciona **ninguna** acción. El plan queda vacío y `apply` no escribe. Es una propiedad
del diseño, y el test la comprueba contando acciones, no comparando ficheros.

**Limitación conocida y aceptada:** `scaffold.memory` es un solo check que agrega Claude y Codex
con `_worst`. Si falta el bloque en uno y está en el otro, se reescriben los dos. El fichero
correcto queda **byte a byte idéntico** —`upsert_block` reemplaza por contenido igual— y lo único
que aparece es su `.bak`, que es lo que hace `install` en cualquier escritura. Se prefiere esto a
partir el check en dos, que cambiaría la salida de `doctor` sin que nadie lo haya pedido. Hay test
de la identidad byte a byte.

### El daemon, y por qué no se lee `daemon.json`

Todo lo que ejecuta comandos del sistema pasa por un **`Runner` inyectable** (un callable
`(argv) -> CompletedProcess`). Es lo que hace testeable el camino de macOS, que en esta máquina no
se puede ejercitar.

REQ-008 dice que nunca se señale un pid sin confirmarlo. La forma más fuerte de cumplirlo no es
«leer `daemon.json` y verificar»: es **no leer nunca `daemon.json`**. El único pid que `update`
usa es el que devuelve `/api/daemon` en esta misma ejecución, vía `ctx.daemon_status` — el mismo
colaborador inyectable que ya usan los probes. Un pid reciclado no puede llegar ahí.

Detección de mecanismo por `sys.platform` **y** por consulta real (`schtasks /Query`,
`launchctl print`, `systemctl --user cat`): estar en Windows no implica que la tarea exista.

### `--restart-backend`, con un límite que el research no había visto

Reiniciar llama-swap no existe hoy: `autostart.ensure_backend()` solo **arranca** si no responde, y
nadie guarda su pid (`autostart.py:72` hace `Popen` y suelta el handle). Así que hay que descubrir
quién escucha en el puerto del backend — `netstat -ano` en Windows, `lsof -ti` en macOS y Linux —,
por el mismo `Runner`.

Y un límite que hay que respetar y no estaba en el research: **`config.backend_origin()` ya
distingue backend local de remoto** (`config.py:97-108`, por el host de `BASE_URL`). Con un backend
remoto —el caso de la Mac apuntando a la PC por Tailscale— `--restart-backend` **no intenta nada**:
lo dice y termina bien. Y su propio docstring avisa de que la heurística falla con un túnel, así que
además de eso se exige que el proceso encontrado se llame `llama-swap` antes de mandarle señal. Dos
confirmaciones, igual que con el daemon.

## Ordered tasks

1. **`checks.py`: dos retoques mínimos**
   - Ficheros: `src/local_delegate/checks.py`
   - Requisitos: base de REQ-005..007
   - Contenido: promover `_daemon_host_port()` a **`daemon_host_port()`** (hoy es privada y solo la
     usa `checks`; B la necesita para saber a dónde preguntar). Y corregir la deriva del docstring:
     dice «los **once** elementos» en **cuatro** sitios (líneas 5, 15, 471 y 490) y desde el PR #61
     el registro tiene **doce** — verificado por ejecución, `len(checks.CHECKS) == 12`. Es
     exactamente la clase de afirmación falsa que ya costó dos sesiones.
   - Verificación: `doctor` sin cambios de salida; test que compara el docstring contra
     `len(CHECKS)` para que no vuelva a derivar
   - Rollback: git

2. **`update.py`: contexto, diagnóstico y tabla de reparaciones**
   - Ficheros: `src/local_delegate/update.py` (nuevo)
   - Requisitos: REQ-003, base de todo lo demás
   - Contenido: `Options` (home, dry_run, versión, flags), construcción del `checks.Context`,
     `REPAIRS` como **tupla estática** —mismo criterio que A: lista, no framework— y
     `plan_repairs(resultados, opts) -> list[Action]` reusando `install.plan_install` por par
     `(componente, target)`. `unknown` no entra nunca.
   - Verificación: tests con HOME simulado; ejecución real en esta PC
   - Rollback: fichero nuevo

3. **`update.py`: el pin, con paridad exacta con el bash**
   - Ficheros: `src/local_delegate/update.py`
   - Requisitos: REQ-002
   - Contenido: `latest_version()` portado conservando el **índice simple** de PyPI y el comentario
     del porqué (`/pypi/<pkg>/json` se sirve con caché; se vio en vivo con la 0.12.0). Reemplazo del
     `==X.Y.Z` con `install._write_text`, que ya hace `.bak` y **conserva el terminador de línea**.
     No se reimplementa nada de eso.
   - Verificación: test con `~/.claude.json` en CRLF y en LF, comprobando que ninguna otra clave se
     movió; test de «sin red» (se avisa y se sigue, exit 0)
   - Rollback: el `.bak` que deja el propio código

4. **`update.py`: control del daemon**
   - Ficheros: `src/local_delegate/update.py`
   - Requisitos: REQ-005..010
   - Contenido: `Runner`, `detect_mechanism(runner)`, `restart()`, `start()`, `wait_until_up()`.
     Reglas duras: el pid **solo** sale de `/api/daemon` (REQ-008), hay que **exigir que el pid
     cambie** tras reiniciar (REQ-005), un puerto ocupado por alguien que no es nuestro daemon no se
     toca, y sin daemon aplicable (`stdio` + `uvx`) se dice con esas palabras y se sale con **0**
     (REQ-009).
   - Verificación: tests con `Runner` doble para los cuatro caminos y para el pid reciclado;
     ejecución real del camino de Windows en esta PC
   - Rollback: `Start-ScheduledTask` a mano

5. **`update.py`: detectar la instalación editable**
   - Ficheros: `src/local_delegate/update.py`
   - Requisitos: **REQ-014**, REQ-015
   - Contenido: detección por **PEP 610** — `importlib.metadata.Distribution.from_name(
     "local-delegate-mcp").read_text("direct_url.json")` y el campo `dir_info.editable`. Si es
     editable, se avisa de que reiniciar **no cambia la versión** y se imprimen los comandos exactos
     (`git pull` + `uv sync`); **no se ejecutan** (non-goal de la spec). REQ-015 sale de aquí por
     construcción: sin pin que cambiar, `update` sigue reparando y reiniciando en vez de terminar
     diciendo «no se toca», que es lo que hace el bash hoy.
   - Verificación: ejecución real en esta PC, que **es** editable; test con el metadato doblado en
     los tres casos (editable, no editable, sin metadato)
   - Rollback: quitar la detección; sin ella solo se pierde el aviso

6. **`update.py`: `--restart-backend`**
   - Ficheros: `src/local_delegate/update.py`
   - Requisitos: REQ-012, REQ-013
   - Contenido: sin la flag, **cero invocaciones** a nada del backend. Con la flag: si
     `config.backend_origin() != "local"`, se informa y no se intenta; si es local, se descubre el
     dueño del puerto de `config.BASE_URL` por el `Runner`, se exige que el nombre del proceso
     contenga `llama-swap`, se termina y se llama a `autostart.ensure_backend(wait=...)`. Y el
     mensaje de REQ-013 cuando se reinicia el daemon **sin** la flag: el backend no se ha tocado y
     los modelos siguen en VRAM.
   - Verificación: test de que sin la flag no hay ni una invocación al 9292; test del camino remoto;
     test del descubrimiento con `Runner` doble en los dos formatos de salida
   - Rollback: quitar la flag

7. **`cli.py`: subcomando `update`**
   - Ficheros: `src/local_delegate/cli.py`
   - Requisitos: REQ-001, REQ-004
   - Contenido: parser con las cinco flags de la spec. **Ya no hay que darlo de alta en ningún otro
     sitio**: el fix del PR #63 dejó el parser como única fuente de subcomandos.
   - Verificación: `local-delegate update --help` y `--dry-run` por ejecución
   - Rollback: revertir el bloque

8. **`install` deja el daemon arriba**
   - Ficheros: `src/local_delegate/cli.py`
   - Requisitos: REQ-011
   - Contenido: al terminar `install` **sin `--dry-run`**, si `mcp_mode == "http"`, se llama a la
     misma rutina de arranque. Con `stdio` no hace nada.
   - Verificación: test con las dos opciones usando el `Runner` doble; y que `--dry-run` no arranca
   - Rollback: quitar la llamada

9. **Receta de macOS y Linux en la wiki**
   - Ficheros: `docs/wiki/Daemon.md`
   - Requisitos: REQ-016
   - Contenido: sustituir la frase de `Daemon.md:72` por dos secciones con el plist completo
     (label `com.local-delegate.daemon`) y la unidad `local-delegate.service`, con los **mismos
     nombres canónicos** que detecta la tarea 4.
   - Verificación: los nombres deben coincidir con las constantes del módulo; test que lo comprueba
   - Rollback: revertir el fichero

10. **El script pasa a envoltorio**
   - Ficheros: `scripts/update_to_latest.sh`
   - Requisitos: REQ-017
   - Contenido: delega en `local-delegate update "$@"`, con una nota de por qué el fichero sigue
     existiendo (el hábito de la Mac) y de que el wheel **no** empaqueta `scripts/`.
   - Verificación: ejecutarlo en Git Bash y ver que llega al CLI
   - Rollback: git

11. **Tests**
    - Ficheros: `tests/test_update.py` (nuevo)
    - Requisitos: todos los verificables sin máquina real
    - Rollback: fichero nuevo

12. **CHANGELOG y backlog**
    - Ficheros: `CHANGELOG.md` (sección `Unreleased`, hoy **vacía** tras la 0.16.0), nota del vault
    - Contenido: entrada del subcomando; y anotar los dos scripts que siguen mal colocados
      (`install_claude_code_hooks_macos.sh`, `docs/recipes/update_agents.py`) como changes propios.

## Test strategy

- **Unit** (`tests/test_update.py`, con `Runner` doble y `tmp_path` como HOME):
  - la tabla `REPAIRS` no selecciona nada ante `unknown`, **para los doce checks**;
  - `warn` de `scaffold.mcp_codex` **no** produce acción; `warn` de `hook_settings` **sí**;
  - idempotencia: segunda pasada → **cero acciones planificadas**;
  - `--dry-run` no escribe ni reinicia (árbol byte a byte, como el test de `doctor`);
  - los cuatro mecanismos de arranque y el fallback;
  - el pid reciclado: no se envía ninguna señal;
  - el pin con CRLF y con LF, y sin red;
  - sin `--restart-backend`: cero invocaciones al backend.
- **Integración:** dos pasadas sobre el mismo HOME simulado; y el caso de `scaffold.memory` con un
  cliente al día y otro sin bloque, comprobando que el fichero correcto queda idéntico.
- **End-to-end manual, en esta PC:** `local-delegate update --dry-run` y luego real, comprobando por
  `/api/daemon` que **el pid cambia** y que **`llama-swap` conserva el suyo**. Es la prueba de que
  REQ-005 y REQ-012 se cumplen a la vez. Ahora mismo hay un caso perfecto servido: el daemon está en
  **0.15.0** con la **0.16.0** instalada, así que `service.daemon` reporta `warn` — la ejecución
  real cubre la rama nueva sin tener que fabricarla.
- **Sin cubrir por ejecución:** macOS y Linux, y el descubrimiento del dueño del puerto en esos
  sistemas. Se cubren con el doble y se declara como riesgo residual, junto al pendiente conocido de
  que el instalador nunca corrió en macOS.
- **Antes de escribir en el HOME real:** ejecutar el comando en **sh, cmd y PowerShell**. Es la
  lección del incidente del 2026-07-30 y aquí aplica igual, porque `update` escribe en el HOME.
- **Checks del proyecto:** los cuatro pasos del CI antes de cada push.

## Migration and compatibility

- `scripts/update_to_latest.sh` no desaparece: se convierte en envoltorio.
- El subcomando es aditivo. La única invocación existente que cambia es `install`, que ahora deja el
  daemon arriba (REQ-011) y solo cuando instaló en modo `http`.
- Sin dependencias nuevas: `httpx2`, `platformdirs`, `subprocess` y `urllib`, todo ya presente.
- Va a `Unreleased`. **Publicar exige confirmación explícita del usuario.**

## Plan review

Revisión adversarial hecha contra la spec, el research y el código real de `checks.py`,
`install.py`, `daemon.py`, `autostart.py` y `config.py`. **Tres hallazgos, ya incorporados arriba:**

- **B-1 (bloqueante) — REQ-014 no tenía ninguna tarea.** El requisito de detectar la instalación
  editable y avisar de que reiniciar no cambia la versión no aparecía ni como tarea ni dentro de
  otra. Es justo el que más le muerde al usuario, porque su máquina de trabajo **es** la editable:
  leería «daemon reiniciado» y esperaría una versión que nadie trajo. → tarea 5 nueva.
- **B-2 — reparar los hooks registrados volvía a copiar los ficheros, y esa copia borra el destino.**
  `plan_install` emite copia + registro juntos, y `_copy_tree_action` hace `rmtree` antes de copiar;
  con los dos checks en `missing` se habrían planificado dos borrados del mismo directorio. →
  deduplicación por `(kind, target)`.
- **B-3 — `--home` simulado reiniciaba el daemon de verdad.** Los servicios no se derivan de
  `ctx.home`. → con `--home` distinto del real no se toca ningún servicio.

No bloqueantes, ya reflejados: `wait_until_up` necesita **reloj inyectable** además del `Runner` o
los tests esperan de verdad; REQ-015 queda cubierto por construcción pero se le da verificación
propia; y el exit distinto de 0 cuando el daemon no vuelve se hace explícito en la tarea 4.

- [x] Cada requisito tiene tarea y verificación.
- [x] Las operaciones destructivas (borrado de directorio, señal a un proceso, reinicio de servicio)
      tienen salvaguarda escrita: deduplicación, doble confirmación antes de señalar, y nada de
      servicios con `--home` simulado.
- [x] Sin dependencias ni configuración nuevas.
- [x] No entra trabajo ajeno: los dos scripts mal colocados quedan anotados como changes propios.
