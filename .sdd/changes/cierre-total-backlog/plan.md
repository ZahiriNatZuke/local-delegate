# Plan de implementación — cierre total del backlog

## Enfoque

Ocho tareas independientes entre sí, cada una con su prueba, agrupadas en **PRs pequeños por tema**
para que el CI diga qué rompió qué. Ninguna toca el ruleset: el paso de macOS y el del navegador
entran en jobs **que ya existen**, porque este repo ya pagó una vez el precio de un check exigido
que nadie reporta.

Dos decisiones de diseño que merecen justificarse antes de escribirlas:

**El handler de `SIGBREAK`.** La causa medida es que uvicorn restaura el handler *original* y
vuelve a lanzar la señal. Por tanto el arreglo no es capturar más excepciones: es **hacer que el
handler original sea uno que produzca `KeyboardInterrupt`**, que es lo que el `except` ya existente
sabe cazar. Instalar `signal.default_int_handler` en `SIGBREAK` antes de servir convierte el camino
de `CTRL_BREAK` en el de `Ctrl+C`, ya probado. Un solo punto y sin lógica nueva de apagado.

**El hook de Read.** Hay dos puertas y la bandera abre una. Se podría escribir la variable de
entorno en el `settings.json` del usuario, pero eso es global a la sesión y no reversible con
`uninstall`. La forma correcta es que **el registro mismo sea el interruptor**: el instalador
registra el script con un argumento explícito, y el script acepta ese argumento *o* la variable.
Así `install`/`uninstall` siguen siendo la única fuente, y la variable sigue sirviendo para quien
instale a mano siguiendo la recipe.

## Tareas ordenadas

1. **Salida limpia ante `CTRL_BREAK` en los dos caminos** — REQ-001
   - Ficheros: `src/local_delegate/daemon.py`, `src/local_delegate/server.py`, `tests/test_ctrl_c.py`
   - Verificación: test que lanza procesos reales con `CREATE_NEW_PROCESS_GROUP`, manda
     `CTRL_BREAK_EVENT` y asevera `rc == 0`; se salta fuera de Windows con motivo.
   - Retroceso: quitar la instalación del handler; nada más depende de ella.

2. **El mensaje del lock dice dónde está el daemon vivo** — REQ-002
   - Ficheros: `src/local_delegate/daemon.py`, `tests/test_daemon.py`
   - Verificación: test con el lock tomado y un `daemon.json` de otro puerto; el mensaje nombra ese
     puerto y el pid.
   - Retroceso: volver al mensaje anterior.

3. **`local-delegate --version`** — REQ-003
   - Ficheros: `src/local_delegate/cli.py`, `tests/test_core.py`
   - Verificación: `--version` sale con 0 e imprime lo mismo que `local_delegate.__version__`.
   - Retroceso: quitar el argumento.

4. **`--enable-read-hook` enciende de verdad** — REQ-004
   - Ficheros: `src/local_delegate/install.py`, `resources/hooks/suggest_delegate_read.py`,
     `tests/test_install.py`, `tests/test_hook_recipes.py`, `docs/recipes/claude-code-hooks.md`
   - Verificación: test **de la combinación** — instala en un HOME temporal, lee el comando que
     quedó en `settings.json`, lo ejecuta con el entorno limpio y asevera que emite. Con control
     negativo: instalado sin la bandera, no emite.
   - Retroceso: la variable sigue funcionando; el argumento es aditivo.

5. **Techo para `clients.jsonl` sin cegar el check** — REQ-005
   - Ficheros: `src/local_delegate/clients.py`, `src/local_delegate/checks.py`, `tests/test_clients.py`
   - Verificación: test que pasa el techo y asevera que el check sigue viendo al cliente antiguo.
   - Retroceso: subir el techo a infinito restaura el comportamiento actual.

6. **Panel interactuado en navegador real** — REQ-006, REQ-007
   - Ficheros: `tests/test_dashboard_ui.py` (nuevo), `pyproject.toml`, `.github/workflows/ci.yml`
   - Verificación: paginación y filtro sobre el DOM servido; el test lleva **control positivo**
     (afirma que había más de una página antes de paginar) para que no pueda pasar sin comprobar.
   - Retroceso: el test se salta solo; quitar el paso del CI no afecta a nada más.

7. **El instalador ejercido en macOS** — REQ-008
   - Ficheros: `.github/workflows/ci.yml`
   - Verificación: el run del CI. Paso dentro de `test (macos-latest)`, contra `--home` temporal.
   - Retroceso: quitar el paso.

8. **Cierre documental y release** — REQ-009, REQ-010
   - Ficheros: `CHANGELOG.md`, backlog del vault, `scripts/release.py` (solo ejecutarlo)
   - Verificación: `doctor` y **una tool `local_*` real** contra el paquete publicado.

## Estrategia de pruebas

- **Unitarias**: mensaje del lock, `--version`, rotación de `clients.jsonl`.
- **Integración**: la combinación instalador↔hook (tarea 4) y el check tras la rotación (tarea 5).
- **End-to-end**: códigos de salida con procesos reales (tarea 1); panel en navegador (tarea 6);
  instalador en macOS en el CI (tarea 7).
- **Secretos**: `gitleaks` ya corre en el job `secrets`; ninguna tarea añade credenciales.

## Migración y compatibilidad

- Sin cambios de contrato en tools ni en `usage.jsonl`.
- El hook de Read sigue apagado por defecto: cambia lo que hace `--enable-read-hook`, no el
  comportamiento de quien no la usa.
- La rotación es un cambio de formato en disco solo en el sentido de que aparece un `.1`; el lector
  se adapta en el mismo PR.

## Revisión adversaria del plan

- [x] **Cada requisito tiene tarea y verificación.** REQ-001→1, 002→2, 003→3, 004→4, 005→5,
      006/007→6, 008→7, 009/010→8.
- [x] **Las operaciones peligrosas tienen salvaguarda.** La única con riesgo real es la 8 (publicar).
      Va después de que el CI esté verde y usa `scripts/release.py`, que es el camino probado.
- [x] **Dependencias y configuración explícitas.** Playwright entra como grupo opt-in, fuera del
      wheel; no hay dependencia de runtime nueva.
- [x] **Sin trabajo no relacionado.** El comprobador de tipos queda fuera y anotado.

Objeciones que se levantaron contra este plan y cómo quedaron:

- *«Instalar un handler global de señal desde una librería es invasivo.»* Cierto en general. Aquí se
  hace en los **puntos de entrada** (`serve` y el arranque stdio), que son procesos nuestros, no en
  el import de un módulo. Un consumidor que importe `local_delegate` no ve el cambio.
- *«El test de navegador se saltará siempre en local y nadie lo verá fallar.»* Por eso el CI lo
  corre en un job que ya existe y por eso lleva control positivo. Un test que se salta en todas
  partes es exactamente el fallo que este repo ya cometió cuatro veces en una sesión.
- *«Rotar `clients.jsonl` puede cegar el check.»* Es el riesgo principal de la tarea 5, está
  escrito como requisito (REQ-005) y tiene su propio escenario de aceptación.
- *«Ocho tareas en una tanda es mucho.»* Van en PRs por tema, no en uno solo. El CI aísla la culpa.
