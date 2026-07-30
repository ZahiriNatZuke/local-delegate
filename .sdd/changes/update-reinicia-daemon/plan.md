# Plan de implementación — `local-delegate update`

> **APARCADO en `planning` el 2026-07-30, a la espera del change `checks-andamiaje`.**
> Este es el **change B** de una secuencia de tres, decidida con el usuario:
> **A** `checks-andamiaje` (registro único de comprobaciones + `doctor` completo) → **B** este
> (`update` encima de esos checks) → **C** `install` migrado con `--clients auto|claude,codex`.
> El plan de abajo se reescribirá para **consumir** el registro de A en vez de traer su propia
> lógica de verificación: `survey()` pasa a ser «correr los `probe` del registro» y «completar lo
> que falte» pasa a ser «aplicar los `fix`». La spec (17 requisitos) sigue siendo válida; lo que
> cambia es de dónde sale la maquinaria.

## Approach

Un módulo nuevo `src/local_delegate/update.py` con la **misma forma que `install.py`**: funciones
puras que planifican y un `apply` que ejecuta, para que `--dry-run` salga gratis y los tests no
necesiten procesos reales. Tres capas:

1. **Diagnóstico** (`survey()`), sin efectos: qué clientes hay, en qué modo, si hay pin, si el daemon
   responde (`daemon.query_daemon`), qué mecanismo de arranque está registrado y si la instalación es
   editable. Devuelve un `Survey` inmutable — el objeto que los tests construyen a mano.
2. **Plan** (`plan_update(survey, opts)`), sin efectos: lista de `Action` reusando las de
   `install.plan_install` para lo que falte, más las acciones propias de pin y de daemon.
3. **Ejecución**: `install.apply(actions, dry_run=…)`, ya existente.

**Todo lo que ejecuta comandos del sistema pasa por un único `Runner` inyectable** (un callable
`(argv) -> CompletedProcess`). Es la pieza que hace testeable sin lanzar nada: los tests pasan un
doble que registra las invocaciones y devuelve salidas preparadas, incluida la de macOS, que en esta
máquina no se puede ejercitar.

La detección de mecanismo se decide por `sys.platform` **y** por consulta real (`schtasks /Query`,
`launchctl print`, `systemctl --user cat`): estar en Windows no implica que la tarea exista.

## Ordered tasks

1. **`update.py`: diagnóstico**
   - Ficheros: `src/local_delegate/update.py` (nuevo)
   - Requisitos: base de REQ-005..015
   - Contenido: `Survey` (clientes, modo, pin, daemon vivo, mecanismo, editable), `survey()`,
     `latest_version()` portado del bash **conservando el índice simple** y su comentario del porqué.
   - Verificación: tests con HOME simulado; ejecución real en esta PC (debe detectar http + editable)
   - Rollback: fichero nuevo, se borra

2. **`update.py`: pin, con paridad exacta con el bash**
   - Ficheros: `src/local_delegate/update.py`
   - Requisitos: REQ-002
   - Contenido: reemplazo del `==X.Y.Z` reusando `install._write_text` (que ya hace `.bak` y
     conserva el terminador de línea). No se reimplementa nada de eso.
   - Verificación: test con `~/.claude.json` en CRLF y en LF, y comprobación de que ninguna otra
     clave se movió
   - Rollback: `.bak` que el propio código deja

3. **`update.py`: control del daemon**
   - Ficheros: `src/local_delegate/update.py`
   - Requisitos: REQ-005..010, 012, 013
   - Contenido: `detect_mechanism(runner)`, `restart(...)`, `start(...)`, `wait_until_up(...)`.
     Reglas duras: **confirmar contra `/api/daemon` antes de señalar un pid** (REQ-008), **capturar el
     pid previo y exigir que cambie** (REQ-005), y no invocar nada del backend salvo
     `--restart-backend` (REQ-012).
   - Verificación: tests con `Runner` doble para los cuatro caminos (tarea, LaunchAgent, systemd,
     fallback) y para el pid reciclado; ejecución real del camino de Windows en esta PC
   - Rollback: el daemon se puede arrancar a mano con `Start-ScheduledTask`

4. **`cli.py`: subcomando `update`**
   - Ficheros: `src/local_delegate/cli.py`
   - Requisitos: REQ-001, 004
   - Contenido: parser con las cinco flags, siguiendo el estilo de `install` (`cli.py:566`)
   - Verificación: `local-delegate update --help` y `--dry-run` por ejecución
   - Rollback: revertir el bloque del parser

5. **`install` deja el daemon arriba**
   - Ficheros: `src/local_delegate/cli.py` (y `install.py` solo si hace falta un hook de cierre)
   - Requisitos: REQ-011
   - Contenido: al terminar `install`, si la configuración instalada usa daemon, se llama a la misma
     rutina de arranque. Con `stdio` no hace nada.
   - Verificación: test con opciones `stdio` (no arranca) y `http` (arranca) usando el `Runner` doble
   - Rollback: quitar la llamada

6. **Receta de macOS y Linux en la wiki**
   - Ficheros: `docs/wiki/Daemon.md`
   - Requisitos: REQ-016
   - Contenido: sustituye la frase de `Daemon.md:71-73` por dos secciones con el plist completo
     (label `com.local-delegate.daemon`, `KeepAlive`, `RunAtLoad`, rutas de log) y la unidad
     `local-delegate.service`, con los mismos nombres canónicos que detecta el código.
   - Verificación: revisión de contenido; los nombres deben coincidir con las constantes del módulo
   - Rollback: revertir el fichero

7. **El script pasa a envoltorio**
   - Ficheros: `scripts/update_to_latest.sh`
   - Requisitos: REQ-017
   - Contenido: delega en `local-delegate update "$@"` (o `uvx local-delegate-mcp update`), con una
     nota de por qué el fichero sigue existiendo
   - Verificación: ejecutarlo en Git Bash y ver que llega al CLI
   - Rollback: el contenido viejo está en git

8. **Tests**
   - Ficheros: `tests/test_update.py` (nuevo)
   - Requisitos: todos los verificables sin máquina real
   - Contenido: idempotencia (dos pasadas, la segunda sin cambios), `--dry-run` que no escribe,
     los cuatro mecanismos, el pid reciclado, el pin con CRLF/LF, sin red, y que el backend no se
     toca sin la flag
   - Rollback: fichero nuevo

9. **CHANGELOG y backlog**
   - Ficheros: `CHANGELOG.md` (sección `Unreleased`, que **ya existe** con el PR #48), nota del vault
   - Contenido: entrada del subcomando; y anotar los dos scripts que quedan mal colocados como
     changes futuros
   - Verificación: revisión a mano de que la entrada cae en `Unreleased` y no dentro de una versión
     publicada

## Test strategy

- **Unit:** `tests/test_update.py` con `Runner` doble y `tmp_path` como HOME. Cubre selección de
  mecanismo, fallback, pid reciclado, idempotencia, `--dry-run`, pin con los dos terminadores de
  línea y ausencia de red.
- **Integration:** reuso de `install.plan_install` verificado con dos pasadas sobre el mismo HOME
  simulado, comprobando que la segunda no produce acciones.
- **End-to-end manual, en esta PC:** `local-delegate update --dry-run` y luego real, comprobando por
  `/api/daemon` que **el pid cambia** y por el dashboard que **`llama-swap` conserva el suyo**. Es la
  prueba de que REQ-005 y REQ-012 se cumplen a la vez.
- **Sin cubrir por ejecución:** el camino de macOS y el de Linux. Se cubren con el doble y se declara
  como riesgo residual, junto al pendiente ya conocido de que el instalador nunca corrió en macOS.
- **Checks del proyecto:** los cuatro pasos del CI antes de cada push.

## Migration and compatibility

- `scripts/update_to_latest.sh` **no desaparece**: se convierte en envoltorio, así que el hábito de
  la Mac sigue funcionando igual.
- El subcomando es aditivo: ninguna invocación existente cambia de comportamiento salvo `install`,
  que ahora deja el daemon arriba (REQ-011) — y solo cuando la configuración instalada lo usa.
- No hay migración de datos ni de formato de configuración.
- Va a `Unreleased`, sin publicar. Publicar exige confirmación explícita del usuario.

## Plan review

- [ ] Pendiente de revisión adversarial antes de aprobar el gate `plan`.
