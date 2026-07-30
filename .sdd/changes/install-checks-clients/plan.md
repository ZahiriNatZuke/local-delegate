# Implementation plan: install consume checks.CHECKS y anade --clients auto|claude,codex

## Approach

El cambio se apoya en piezas que **ya existen** y evita crear superficie nueva:

1. **El consumo de `checks` vive en `cli.py`**, no en `install.py`. `cli` ya importa los dos sin
   ciclo (`cli.py:116`); `install.py` no gana ninguna dependencia y sigue siendo el módulo que
   escribe. Esto neutraliza el riesgo de ciclo que documenta `checks.py:80-83`.
2. **El bug del HOME no necesita código nuevo: necesita un flag bien calculado.** `install`
   **ya** tiene `Options.use_cli` (`install.py:336`), que es exactamente el interruptor del
   camino peligroso. El arreglo es calcularlo también a partir de `--home`, igual que hace
   `update.py:236`. Una línea en `cli.py:55`.
3. **La regla «HOME simulado» pasa a tener una sola definición.** Hoy vive solo en
   `update.Options.simulated_home` (`update.py:109-116`) y ahora la necesitan dos módulos. Se
   extrae a `install.is_simulated_home(home)` —el módulo más bajo de los tres, ya importado por
   `checks` y por `update`— y `update` la consume. Este repo ya pagó caro tener la misma verdad
   en tres sitios (la cuenta de tokens del PR #48) y dos derivaciones del host del daemon.
4. **La confirmación de Codex se decide antes de planificar**, y `plan_install` se mantiene
   puro: `install.Options` gana un booleano `skip_codex_mcp` que suprime esa acción. Filtrar la
   lista de acciones por `kind == "toml"` desde fuera sería frágil y mudo.
5. **El reporte final reutiliza el renderizado del doctor** (`doctor._GROUP_HEADINGS` y
   `doctor._print_group`, `doctor.py:289-310`) en vez de escribir un formato paralelo. Usar un
   privado de otro módulo es práctica establecida aquí: `checks` usa `install._is_ours` y
   `doctor._compare_line`.

### Ajuste a la especificación, decidido en esta fase

La spec dice «`checks.py` no se modifica». Para cumplir REQ-013 (no salir a la red ni lanzar
binarios del backend) hay que correr **solo** los grupos `entorno` y `andamiaje`, y `run_all`
corre los doce. Las dos salidas eran duplicar su `try/except` fuera del módulo o añadirle un
filtro. Se elige el filtro:

> `checks.run_all(ctx, *, groups: tuple[str, ...] | None = None)` — aditivo, con el
> comportamiento actual intacto cuando no se pasa. **El registro `CHECKS` y los doce `probe`
> siguen sin tocarse**, que es lo que el non-goal protege de verdad.

`spec.md` queda corregido en consecuencia.

## Ordered tasks

1. **Las dos reglas del HOME, con una sola definición cada una**
   - Ficheros: `src/local_delegate/install.py` (nuevas `is_simulated_home(home)` y
     `present_targets(home) -> set[str]`), `src/local_delegate/update.py`
     (`Options.simulated_home` y `_present_targets` delegan en ellas).
   - Requisitos: REQ-002 (base), REQ-006 (base).
   - **Por qué `present_targets` va aquí y no se saca del check** (hallazgo B-1 de la revisión):
     `client.presence` devuelve texto de presentación —`Result(OK, "detectados: Claude Code,
     Codex")`, `checks.py:199-207`—, no datos. Derivar la selección de clientes parseando ese
     `detail` acoplaría el comportamiento del instalador a un string de UI. La función correcta
     ya existe en `update.py:167-174`, en el módulo equivocado para que la use `install`.
   - Verificación: `tests/test_update.py:449` sigue verde sin cambios (no hay regresión de
     comportamiento); tests nuevos de las dos funciones — HOME igual, distinto e irresoluble; y
     presencia con ninguno, uno y los dos clientes.
   - Rollback: funciones aisladas, sin estado; revertir es quitarlas y restaurar lo anterior.

2. **`use_cli` deja de ignorar `--home`**
   - Ficheros: `src/local_delegate/cli.py` (`_install_options`).
   - Requisitos: REQ-006, REQ-007.
   - Verificación: test que dobla `install.shutil.which` y `install.subprocess.run` con un espía
     y afirma **cero invocaciones** con `--home` simulado — **en los dos verbos**, y el caso de
     `uninstall` es el que más importa porque su camino por CLI *desregistra* el MCP real
     (`install.py:568`), o sea destruye configuración en vez de duplicarla. Más comparación byte
     a byte del árbol «real».
   - El doble del HOME real es `monkeypatch.setattr(Path, "home", ...)`, **no** una variable de
     entorno (hallazgo N-1): `Path.home()` lee `USERPROFILE` en Windows y `HOME` en POSIX, así
     que un `setenv("HOME", ...)` pasaría en Linux y macOS y fallaría en el runner de Windows.
   - **Verificado al revés**: con la línea antigua restaurada, el test tiene que fallar.
   - Rollback: una línea.

3. **`--clients` y la resolución por presencia**
   - Ficheros: `src/local_delegate/cli.py` (`_add_common_install_args`, `_install_options`,
     `_run_install`).
   - Requisitos: REQ-001..005.
   - Verificación: tests de las combinaciones — `auto` con un cliente, `auto` con ninguno
     (nada escrito, exit 0, **con el reporte impreso igual**), `--clients codex` explícito en
     máquina sin Codex, `--target all` conservando el comportamiento previo, y `--clients` +
     `--target` juntos → exit 2 sin escribir. **Y `uninstall --clients auto`** (hallazgo B-3):
     limpia solo los clientes presentes y deja intacto lo demás.
   - Rollback: el flag es aditivo; quitarlo devuelve el default `all`.

4. **Confirmación acotada al Codex puesto a mano**
   - Ficheros: `src/local_delegate/install.py` (`Options.skip_codex_mcp`, respetado en
     `plan_install`), `src/local_delegate/cli.py` (la pregunta y el flag
     `--force-mcp-codex`).
   - Requisitos: REQ-008..011.
   - Verificación: cuatro caminos con stdin doblado — sí, no, sin tty, `--force-mcp-codex`— y el
     caso `--dry-run` (no pregunta, lo anuncia). Test de que con `--no-mcp` no se pregunta nunca.
     El molde del doblaje de `stdin` ya existe y se reutiliza: `tests/test_smoke.py:139-174`,
     que además cubre el **stdin raro** —un objeto sin `isatty` usable—, caso que ya mordió aquí.
   - `uninstall` **no** hereda la pregunta, y hay que dejarlo escrito en el código (hallazgo
     N-2): ahí la sección `[mcp_servers.local-delegate]` es nuestra por definición y retirarla es
     la orden explícita del usuario. Sin ese comentario, la asimetría se leerá como olvido.
   - Rollback: `skip_codex_mcp=False` restaura el comportamiento actual exacto.

5. **Filtro por grupo en `run_all` y reporte final**
   - Ficheros: `src/local_delegate/checks.py` (parámetro `groups`, aditivo),
     `src/local_delegate/cli.py` (impresión del reporte).
   - Requisitos: REQ-012..015.
   - Verificación: test de que `run_all(ctx, groups=("entorno","andamiaje"))` devuelve 8
     resultados y **no invoca** los colaboradores de red ni de versiones (dobles que fallan el
     test si se llaman); test de que la salida de `install` contiene las etiquetas de estado; y
     que en `--dry-run` el rótulo dice «estado actual».
   - El registro se recorre **dos veces** por ejecución —una antes de planificar, para resolver
     y detectar el caso «a mano», y otra al final para reportar— y eso va comentado en el código
     (hallazgo N-4): reutilizar la primera pasada para el reporte daría el estado **previo** a
     escribir, que es justo lo contrario de lo que el reporte afirma.
   - Rollback: parámetro con default; sin pasarlo, `run_all` se comporta igual que hoy.

6. **Documentación y CHANGELOG**
   - Ficheros: `README.md`, `docs/wiki/Integration-install.md`,
     `docs/recipes/claude-code-integration.md`, `CHANGELOG.md`.
   - Requisitos: REQ-017, y el «once piezas» de REQ-018.
   - Verificación: revisión del diff; `tests/test_site.py` y `test_release_metadata.py` verdes.
   - Rollback: solo texto.

7. **El docstring que miente**
   - Ficheros: `tests/test_install.py:270-273`.
   - Requisitos: REQ-018.
   - Verificación: el texto nuevo coincide con lo que ya dicen `install.py:173-177` y
     `checks.py:296-299`; el test sigue verde (su aserción no cambia, solo el porqué).
   - Rollback: solo texto.

## Test strategy

- **Unit** (`tests/test_install.py`): `is_simulated_home` en sus tres casos; `skip_codex_mcp`
  suprimiendo exactamente una acción y ninguna más; el espía de `subprocess.run`.
- **Unit** (`tests/test_checks.py`): el filtro por grupo, con dobles que revientan si se llama a
  la red o al backend.
- **Integración** (`tests/test_smoke.py`): el CLI de punta a punta con `--clients`, incluidos el
  exit 2 del conflicto de flags y el exit 0 sin clientes.
- **Al revés, obligatorio en dos puntos**: la prueba del HOME (tarea 2) y la de la entrada de
  Codex (tarea 4) deben **fallar** con el arreglo revertido. Un test que no falla con el bug
  puesto no prueba nada, y aquí la suite actual es el ejemplo: sus 20 pruebas pasan con el bug
  del HOME dentro porque todas fijan `use_cli=False`.
- **Manual end-to-end en Windows, antes de cualquier push**: `install --home <tmp>` y
  `uninstall --home <tmp>` en `sh`, `cmd` y PowerShell, con hash del `~/.claude.json` real antes
  y después. Es la lección del incidente que bloqueó Claude Code (PRs #55 y #57).
- **Los cuatro pasos del CI con `.`**: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run pytest -q --basetemp=<temp propio>`, y `extract_dashboard_js.py` + `node --check`.
- **Seguridad**: ninguna acción nueva escribe fuera del HOME de destino; no se imprimen
  secretos; skill `personal-security-check` antes de commitear.

## Migration and compatibility

- **Cambio de comportamiento observable y deliberado:** sin flags, `install` deja de crear
  `~/.codex/` en máquinas sin Codex. Va al `CHANGELOG` bajo `Unreleased` como cambio de
  comportamiento, no como fix mudo.
- **`--target` no se rompe.** Sigue aceptado con su semántica exacta, incluido `all`, que es la
  vía de escape para quien quiera el comportamiento anterior. Está en tres documentos
  publicados.
- **Nada que migrar en disco.** El change no cambia formatos ni ubicaciones: los mismos ficheros,
  los mismos marcadores, los mismos `.bak`.
- **Sin dependencias nuevas.** Solo stdlib y módulos internos.
- **No se publica.** El change entra en `Unreleased`; la release es decisión aparte del usuario.

## Plan review

Revisión adversarial en [`plan-review.md`](./plan-review.md): 3 hallazgos bloqueantes y 4 no
bloqueantes, **todos remediados** en este plan y en `spec.md`.

- B-1 → tarea 1: `present_targets` extraída; prohibido parsear `Result.detail` (REQ-002).
- B-2 → REQ-005: el reporte se imprime también cuando no hay clientes, tras el aviso.
- B-3 → tareas 2 y 3: `uninstall` cubierto en el HOME simulado y en `--clients auto`.
- N-1 → tarea 2: el doble es `Path.home`, no la variable de entorno.
- N-2 → tarea 4 y casos límite: la asimetría `install`/`uninstall`, escrita.
- N-3 → tarea 4: se reutiliza el molde de tty de `tests/test_smoke.py:139-174`.
- N-4 → tarea 5: las dos pasadas del registro van comentadas.

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
