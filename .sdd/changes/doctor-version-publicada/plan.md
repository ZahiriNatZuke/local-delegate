# Implementation plan: doctor compara la version instalada contra la publicada en PyPI

## Approach

El diseño no inventa nada: **repite el patrón que el módulo ya usa tres veces**. Los checks que
hablan por red o lanzan procesos (`service.daemon`, `service.backend`, `backend.*`) no llaman al
módulo real desde el probe, sino a un **colaborador del `Context`** con un default que delega. Eso
es lo que hace los tests deterministas sin `respx` ni sockets, y es literalmente el motivo por el
que `Context` existe («lo que los probes necesitan, **inyectado** y no descubierto»).

Así que el check nuevo aporta un cuarto colaborador, `latest_release`, cuyo default llama a
`update.latest_version()` —con import diferido, porque `update` importa `checks` y a nivel superior
sería un ciclo, exactamente igual que `daemon` y `doctor`—. La verdad sobre «cuál es la última
publicada» sigue viviendo en un solo sitio.

Y el riesgo identificado en el research —atar `install` y `update` a la red— se resuelve con el
mismo mecanismo: el módulo expone un colaborador `SKIP_PYPI` que devuelve `(None, motivo)` sin
tocar nada, y los dos lo inyectan. No hace falta ningún flag ni un grupo nuevo: **quien no quiere
red, dice que no la quiere**, y se ve en la línea que lo inyecta.

Lo que **no** se hace, y es deliberado:

- No se toca `_probe_cli`. «¿Está el comando en el PATH?» y «¿está al día?» son dos preguntas
  distintas y el registro las separa por diseño; además `_installed_version()` sale de
  `importlib.metadata` y funciona aunque el comando no esté en el PATH (caso `uvx`).
- No se reimplementa la consulta ni la ordenación de versiones.
- No se toca el significado de `--online`.

## Ordered tasks

### 1. El colaborador `latest_release` en `Context`

- **Ficheros:** `src/local_delegate/checks.py`
- **Requisitos:** REQ-008, REQ-009
- **Qué:** constante `PYPI_TIMEOUT = 2.0`; función `_default_latest_release()` con import diferido
  de `update` que devuelve `update.latest_version(timeout=PYPI_TIMEOUT)`; función pública
  `SKIP_PYPI()` que devuelve `(None, "no se consulta PyPI en este comando")` sin tocar la red;
  campo nuevo en `Context`, **al final** de los colaboradores para no romper ninguna llamada
  posicional.
- **Verificación:** `Context()` por defecto expone el colaborador; `SKIP_PYPI` no importa `update`
  ni abre sockets.
- **Rollback:** el campo tiene default; quitarlo no rompe llamadas existentes.

### 2. El probe y su entrada en el registro

- **Ficheros:** `src/local_delegate/checks.py`
- **Requisitos:** REQ-001..REQ-006
- **Qué:** `UPGRADE_HINT`; helper de clave numérica de versión (la misma que usa
  `latest_version()` para ordenar: `[int(p) for p in re.findall(r"\d+", v)]`, **rellenando con
  ceros hasta igualar longitudes** — ver hallazgo R-2); `_probe_published(ctx)` con los cinco
  desenlaces de REQ-002; entrada
  `Check("cli.published", "entorno", "version publicada", _probe_published)` justo después de
  `cli.path`.
- **El `fix_hint` depende del tipo de instalación (hallazgo R-3):** si `update.editable_origin()`
  devuelve una ruta, el comando que actualiza **no** es `uv tool upgrade` sino `git pull` +
  `uv sync` sobre ese repo. `editable_origin()` ya existe, está probado y no sale a la red.
- **Cuidados:** todo dentro de `try`/salida a `UNKNOWN` (REQ-004); nada fuera de cp1252 (REQ-006);
  ni una escritura (REQ-005).
- **Verificación:** un test por desenlace, con `latest_release` doblado.
- **Rollback:** quitar la entrada de la tupla deja el módulo como estaba.

### 3. Los cuatro textos del tamaño del registro

- **Ficheros:** `src/local_delegate/checks.py`
- **Requisitos:** REQ-013
- **Qué:** «doce» → «trece» en el docstring del módulo (2 sitios), el comentario de `CHECKS` y el
  docstring de `run_all`. El test `_NUMERO` ya contempla `13: "trece"`.
- **Verificación:** el test del tamaño, que ya existe, pasa sin tocarlo.

### 4. `install` y `update` no salen a la red

- **Ficheros:** `src/local_delegate/cli.py` (línea 157), `src/local_delegate/update.py` (línea 585)
- **Requisitos:** REQ-010, REQ-011
- **Qué:** los dos `Context(...)` pasan `latest_release=checks.SKIP_PYPI`, con un comentario que
  diga el porqué en cada sitio (en `install`, «instalar unos hooks no es motivo para salir a la
  red», que es la frase que ya justifica el filtro por grupos; en `update`, que la consulta ya la
  hace `latest_version()` unas líneas más abajo y duplicarla sería contarla dos veces).
- **Verificación:** tarea 6.
- **Rollback:** quitar el argumento restaura el default.

### 5. Los tests existentes que llegan al probe — **hallazgo bloqueante R-1**

- **Ficheros:** `tests/test_checks.py` (`make_ctx`, línea 20), `tests/test_update.py` (`_ctx`,
  línea 149), `tests/test_doctor.py` (`_stub_environment`, línea 124),
  `tests/test_install_clients.py`
- **Requisitos:** REQ-008
- **Qué:** hay **dos** familias de tests que llegan al probe, y solo una se arregla añadiendo un
  kwarg:
  - **Los que construyen el `Context` ellos mismos** (`test_checks.make_ctx`,
    `test_update._ctx`): basta añadir `latest_release` a los colaboradores doblados.
  - **Los que NO lo construyen** (`tests/test_doctor.py` y `tests/test_install_clients.py`): ahí
    el `Context` lo arma `run_doctor` / el reporte de `cli.py` por dentro, con los defaults. Un
    kwarg no llega. Hay que doblar **el default del módulo**:
    `monkeypatch.setattr(checks, "_default_latest_release", ...)` en `_stub_environment`, igual
    que ese helper ya dobla `checks._port_taken` y `checks.shutil.which`.
- **Por qué es bloqueante y no cosmético:** sin esto la suite empieza a consultar PyPI de verdad
  —lo contrario de lo que promete el docstring de `test_checks.py` («ningún test sale a la
  red»)— y, peor, `test_run_doctor_exit_0_when_everything_is_in_place` (línea 157) **se vuelve
  frágil por dependencia externa**: afirma exit 0, y en cuanto el repo quede por detrás de PyPI
  el check nuevo daría `WARN` y el exit sería 1. O sea que **publicar una versión rompería el CI**
  sin que nadie tocara el código.
- **Verificación:** la suite pasa con la red caída, y los tiempos de `test_doctor.py` no suben.

### 6. Tests nuevos

- **Ficheros:** `tests/test_checks.py`, `tests/test_install.py` (o donde viva el reporte final)
- **Requisitos:** REQ-002..REQ-006, REQ-010, REQ-011
- **Qué:**
  - un test por cada desenlace: menor → `WARN` con `fix_hint`; igual → `OK`; mayor → `OK` con el
    detalle que lo dice; PyPI ilegible → `UNKNOWN`; versión instalada desconocida → `UNKNOWN`;
  - **orden numérico:** instalada `0.9.0` contra publicada `0.11.0` da `WARN` (si alguien compara
    strings, este test falla);
  - **el probe no lanza:** con un `latest_release` que revienta, `run_all` sigue devolviendo los
    trece resultados;
  - **AC-5:** extender `test_filtrar_por_grupo_no_toca_la_red_ni_el_backend` con
    `latest_release=_prohibido` — con el check nuevo en `entorno`, ese test es exactamente la
    prueba de que `install` no sale a internet;
  - **AC-6:** un test de `update` con un `latest_release` prohibido, que falla si el check lo
    llama.
- **Los tests de AC-5 y AC-6 doblan el default del módulo, no un kwarg:** deben ejercitar el
  camino real (`cli.run(["install", ...])` y `update.run_update(...)`), que es donde vive la
  inyección de la tarea 4. Doblar un kwarg probaría el doble, no el código.
- **Verificación al revés (obligatorio):** con la inyección de la tarea 4 revertida, los tests de
  AC-5 y AC-6 deben **fallar**. Un test que no falla con el bug puesto no prueba nada.

### 7. Documentación y CHANGELOG

- **Ficheros:** `docs/wiki/Integration-install.md`, `CHANGELOG.md`
- **Requisitos:** REQ-014, REQ-015
- **Qué:** en la wiki, la línea 108 («las doce piezas» → «las trece piezas») y una fila nueva en la
  tabla de comprobaciones (líneas 127-140), en el grupo Entorno; en el CHANGELOG, entrada bajo
  `Unreleased`.
- **Cuidado:** `CHANGELOG.md` es **CRLF**. Editarlo con la herramienta de edición directa, nunca
  con un here-string de PowerShell.
- **Verificación:** `git diff --stat` no debe mostrar el CHANGELOG entero como modificado.

### 8. Ejecución real y CI local

- **Requisitos:** todos
- **Qué:** los cuatro pasos del CI (`ruff check .`, `ruff format --check .`, `pytest -q` con
  basetemp propio, `extract_dashboard_js.py` + `node --check`) y ejecutar `local-delegate doctor`
  de verdad contra esta máquina, más `doctor --home <tmp>` para ver el caso con HOME simulado.

## Test strategy

- **Unit:** los desenlaces del probe, con el colaborador doblado. Cero red.
- **Integration:** que `install` y `update` no consulten PyPI, con un colaborador que **revienta**
  si lo llaman (no uno que devuelve algo: un doble silencioso no probaría nada).
- **End-to-end o manual:** `doctor` real en esta máquina (donde instalada == publicada == 0.17.0,
  o sea AC-2), y `doctor` con `latest_release` forzado para ver el `[WARN]` de AC-1.
- **Verificación al revés:** revertir la tarea 4 debe romper los tests de AC-5 y AC-6.
- **Seguridad y secretos:** la petición es la misma que ya hace `update` (índice simple de PyPI,
  sin credenciales). No se añade ninguna dependencia: `urllib` es stdlib y ya se usa.

## Migration and compatibility

- **Sin ruptura de API:** el campo nuevo de `Context` va al final y con default; las cuatro
  llamadas existentes (dos en `src`, dos en `tests`) siguen compilando sin tocarse — aunque las de
  tests **sí** se tocan a propósito, para que no salgan a la red.
- **Exit code:** `doctor` puede pasar de 0 a 1 en máquinas con el CLI desactualizado. Es el
  comportamiento pedido (AC-1), y es el mismo precedente que el backend caído en el change A.
- **Sin red:** `doctor` sigue funcionando entero; solo esa línea sale `[ -- ]`.

## Revisión adversarial del plan

Cuatro hallazgos; el primero es bloqueante y ya está incorporado arriba.

- **R-1 (BLOQUEANTE) — la tarea 5 cubría la mitad de los tests afectados.** El plan original solo
  contaba los dos sitios que construyen `Context` explícitamente. Pero `tests/test_doctor.py`
  (seis tests que llaman a `run_doctor`) y `tests/test_install_clients.py` (diez llamadas a
  `cli.run(["install", ...])`) llegan igual al probe **con los defaults**, porque el `Context` lo
  arman por dentro. Consecuencia si no se arregla: la suite sale a la red, y
  `test_run_doctor_exit_0_when_everything_is_in_place` pasa a depender de PyPI — **publicar una
  versión rompería el CI** sin tocar una línea de código. Incorporado a la tarea 5.
- **R-2 (menor) — comparación de versiones de distinta longitud.** `0.17` contra `0.17.0` da
  `[0, 17] < [0, 17, 0]`, o sea un `WARN` falso. Improbable con el versionado del repo, pero
  rellenar con ceros cuesta una línea. Incorporado a la tarea 2.
- **R-3 (menor, real) — el `fix_hint` puede mandar a un comando que no aplica.** En instalación
  editable, `uv tool upgrade local-delegate-mcp` no actualiza nada; lo que actualiza es `git pull`
  + `uv sync`. Y el caso no es teórico: es exactamente el de una segunda máquina con el repo
  clonado que quedó por detrás de un release hecho desde otra. `update.editable_origin()` ya
  resuelve la detección sin salir a la red. Incorporado a la tarea 2.
- **R-4 (decisión consciente, no defecto)** — el reporte final de `install` mostrará siempre
  `[ -- ] version publicada: no se consulta PyPI en este comando`. Es ruido leve. Se **acepta** en
  vez de añadir un parámetro `exclude` a `run_all`: la línea es honesta (dice que la comprobación
  existe y que ahí no se hizo), y un mecanismo de exclusión por check sería la primera grieta
  hacia el framework que la regla 3 del módulo prohíbe explícitamente.

## Plan review

- [x] Cada requisito mapea a al menos una tarea y a un paso de verificación (ver tabla de
      trazabilidad de la spec; REQ-012 se cubre por omisión: `doctor.py` no se toca, y el test de
      `doctor` sin flags lo comprueba).
- [x] Las operaciones con riesgo tienen salvaguarda: la única con riesgo real es sacar a la red a
      quien no lo pidió, y está cubierta por dos tests con colaborador que revienta **más**
      verificación al revés.
- [x] Las dependencias y cambios de configuración son explícitos: ninguna dependencia nueva.
- [x] El plan no incluye trabajo ajeno: los otros pendientes del backlog (caché de PyPI, `uv tool
      upgrade`, hooks duplicados) tienen su propio change y aquí están como *non-goals*.
