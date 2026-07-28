# Verification: Acotar el SDK mcp por debajo del major 2 y cerrar el punto ciego de resolucion libre

## Environment

- Revision: `0d5e4bd` en la rama `fix/mcp-sdk-major-pin`, PR
  [#31](https://github.com/ZahiriNatZuke/local-delegate/pull/31).
- Sistema local: Windows 11, Python 3.11.15 (gestionado por `uv`), `mcp 1.28.1` en el lock.
- Entornos limpios creados en el scratchpad de la sesión, fuera del repositorio.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | Techo en `pyproject.toml` + comentario del motivo | OK | diff de una línea de requirement en `uv.lock` |
| REQ-002 | Import del paquete instalado con resolución libre | OK | el handshake implica que el import ocurrió |
| REQ-003 | Handshake `initialize` sin backend vivo | OK | `OK: handshake respondido por local-delegate (SDK 1.29.0).`, exit 0 |
| REQ-004 | Job `install-smoke` en `ci.yml` | **pass en 13s** | `gh pr checks 31`; reporta su resultado, requisito previo para exigirlo algún día |
| REQ-005 | **Prueba negativa** | **Falla como debe** | ver abajo |
| REQ-006 | `bump_version.py 0.12.2` + `--check` | OK | `OK: todos los archivos declaran 0.12.2` |
| REQ-007 | Entrada de `CHANGELOG.md` | OK | nombra `-32000` y dónde está el traceback real |
| REQ-008 | Ruleset intacto | OK | no se ejecutó `setup_repo_security.sh` |
| REQ-009 | Suite contra la versión del lock | OK | `233 passed` |

### REQ-005 — la prueba negativa, reproducible

No se simuló el fallo: se usó **la 0.12.1 realmente publicada en PyPI**, que es la que lleva el
techo ausente dentro del wheel.

```powershell
uv venv <tmp>\venv-roto
uv pip install --python <tmp>\venv-roto\Scripts\python.exe `
    --refresh --resolution highest "local-delegate-mcp==0.12.1"
<tmp>\venv-roto\Scripts\python.exe .\scripts\check_install_handshake.py
```

Resolución obtenida: `local-delegate-mcp==0.12.1`, **`mcp==2.0.0`**, `mcp-types==2.0.0`.

Salida (exit code **1**):

```
FALLO: el paquete instalado no importa. Una dependencia rompió su API.
Suele ser un major nuevo sin techo en `pyproject.toml`.
--- stderr ---
  File ".../local_delegate/server.py", line 32, in <module>
    from mcp.server.fastmcp import FastMCP
ModuleNotFoundError: No module named 'mcp.server.fastmcp'
```

Es el mismo traceback que reportó el usuario desde la Mac, reproducido en Windows. Confirma dos
cosas: el fallo **no era específico de macOS**, y el check nuevo lo caza.

### Contraprueba con el techo aplicado

Con el wheel construido desde esta rama, la misma instalación de resolución libre trae **`mcp
1.29.0`** —no la 1.28.1 del lock, lo que demuestra que la resolución es realmente libre— y el
handshake responde con exit 0. De paso queda validada la asunción que quedaba abierta en
`research.md`: la suite y el arranque funcionan con 1.29.0.

## Quality checks

- [x] Project-native tests pass. `233 passed` (`uv run pytest -q`).
- [x] Lint, formatting y build. `ruff check .` limpio; `ruff format --check .` → 42 archivos ya
      formateados; `uv lock --check` pasa; `uv build` construye wheel y sdist.
- [x] Validación del JS del dashboard: `extract_dashboard_js.py` + `node --check`, exit 0.
- [x] Secret scanning. `gitleaks` en pre-commit pasó; job `secrets` y GitGuardian en el PR.
- [x] No unrelated changes. El diff toca `pyproject.toml`, `uv.lock`, `server.json`,
      `CHANGELOG.md`, `ci.yml`, el script nuevo y la traza SDD. Nada más.

**Los cuatro pasos del CI se corrieron con `.`, no con rutas parciales**, según la regla de
proceso del proyecto.

## Deviations and residual risk

- **La revisión del plan no fue independiente** (la hizo el mismo agente que lo redactó, por una
  instrucción de sesión que impide lanzar subagentes sin petición). Declarado en `plan-review.md`.
- **El fallo del entorno local, no del cambio:** `pytest` aborta al final en esta máquina con
  `PermissionError [WinError 5]` limpiando el symlink `pytest-current` del temp de Windows. Se
  sorteó con `--basetemp` propio. No afecta al CI ni al paquete, pero conviene saberlo para no
  confundirlo con un fallo de la suite.
- **`install-smoke` depende de PyPI en vivo.** Un índice degradado lo pondría en rojo por causa
  ajena. Aceptado: no es check requerido, así que no bloquea PRs, y el script distingue el fallo
  de import del resto.
- **Riesgo residual conocido:** las otras cinco dependencias directas siguen sin techo. El job
  nuevo las cubre por detección, no por prevención. Y ya hay señal de la próxima: la suite avisa
  `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install
  httpx2 instead`, es decir, `httpx` 2 viene en camino.
- **Defecto separado, anotado:** `serverInfo.version` reporta la versión del **SDK**, no la del
  paquete (`FastMCP("local-delegate")` se instancia sin `version=`). Un handshake no sirve para
  verificar qué versión de local-delegate corre.
- **Pendiente hasta publicar:** la verificación que de verdad cierra el reporte es
  `uvx local-delegate-mcp` **sin pin** en la Mac del usuario, con la 0.12.2 ya en PyPI.
