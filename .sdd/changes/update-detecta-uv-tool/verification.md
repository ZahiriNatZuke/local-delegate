# Verification: update detecta el CLI instalado como uv tool y dice como actualizarlo

## Environment

- **Revisión:** rama `feat/update-detecta-uv-tool`, sobre `main` en `5afe69b`.
- **Máquina:** Windows 11, Python 3.11 (uv). Conviven **las dos instalaciones** que este change
  distingue: la de `uv tool` (`~/.local/bin/local-delegate`, entorno en
  `%APPDATA%\uv\tools\local-delegate-mcp`, 0.17.0) y la editable del repo (`.venv`).
- **Suite:** 451 tests, 1 skipped (438 al empezar el change; **+13**).

## Evidence

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | Una sola función con tres respuestas | OK | `update.install_kind()` → `EDITABLE` / `UV_TOOL` / `OTHER` |
| REQ-002 | Detección por `uv-receipt.toml`, sin rutas ni `uv` | OK | lee `Path(sys.prefix)/"uv-receipt.toml"`; ni un `subprocess`, ni `UV_TOOL_DIR`, ni una ruta de plataforma en la función |
| REQ-003 | No lanza | OK | `test_un_prefix_ilegible_no_revienta_la_deteccion` con un `sys.prefix` con bytes nulos → `OTHER` |
| REQ-004 | Responde por el proceso que corre | OK | **ejecución real en los dos contextos** (abajo) |
| REQ-005 | El `fix_hint` consume la misma función | OK | `checks._upgrade_hint` → `update.upgrade_command()`; `test_la_pista_depende_de_como_este_instalado` cubre los tres modos; `checks.UPGRADE_HINT` se retiró para no dejar el comando escrito dos veces |
| REQ-006 | Mensaje con versión y comando | OK | ejecución real: nombra `0.17.0` y `uv tool upgrade local-delegate-mcp` |
| REQ-007 | Explica por qué no lo hace él | OK | «reinstalaría el entorno desde el que se está ejecutando»; el test lo exige literalmente |
| REQ-008 | Silencio cuando no aporta | OK | `test_sin_nada_que_avisar_el_bloque_no_aparece`, parametrizado con al día / por delante / sin red |
| REQ-009 | No cambia plan ni exit code | OK | `test_el_aviso_de_uv_tool_no_cambia_el_plan_ni_el_exit_code`, comparando el contenido línea a línea |
| REQ-010 | Sale por `out` | OK | `run_update` usa `out(line)` |
| REQ-011 | cp1252 | OK | `test_el_aviso_de_uv_tool_cabe_en_la_consola_de_windows`, incluido `GENERIC_UPGRADE` |
| REQ-012 | CHANGELOG, CRLF | OK | `CRLF=904, LF sueltos=0` |
| REQ-013 | Wiki | OK | `docs/wiki/Remote-backend.md`: bloque nuevo «Lo que `update` NO hace», con el comando y el porqué |

### Ejecución real en los dos contextos — el punto que el plan marcó como riesgo (R-2)

Desde `uv run` (como se prueba todo aquí) `sys.prefix` apunta al `.venv` del repo, así que el
camino de `uv tool` **no se recorre**. Para verificarlo de verdad se ejecutó el **Python del
entorno de `uv tool`** con el código del repo en `PYTHONPATH` — `sys.prefix` real con receipt,
código nuevo:

```
sys.prefix:        C:\Users\Yohan\AppData\Roaming\uv\tools\local-delegate-mcp
codigo desde:      D:\Projects\local-delegate\src\local_delegate\update.py
install_kind():    uv-tool
upgrade_command(): uv tool upgrade local-delegate-mcp
version instalada: 0.17.0

--- aviso con una 0.18.0 publicada ---
El CLI está instalado como `uv tool` en la versión 0.17.0.
  `update` no puede actualizarlo: reinstalaría el entorno desde el que se está
  ejecutando, y eso deja la instalación rota. Hazlo tú, en otra terminal:
    uv tool upgrade local-delegate-mcp
--- al dia (0.17.0): ---
(nada, correcto)
```

Y desde el repo editable, `local-delegate update --dry-run` sigue enseñando el bloque
`Instalación EDITABLE: el código se sirve de D:\Projects\local-delegate` y **no** el de `uv tool`
(AC-3), con `install_kind() == editable` y el comando `git -C … pull && uv sync --project …`.

**Sin tocar la instalación real del usuario:** no se instaló ni desinstaló nada; `local-delegate`
sigue en 0.17.0 vía `uv tool`.

### Verificación al revés (obligatoria)

Sustituida la detección por `return OTHER`, fallan los tres tests que la protegen y ninguno más:

```
FAILED tests/test_update.py::test_reconoce_una_instalacion_de_uv_tool
FAILED tests/test_update.py::test_el_aviso_de_uv_tool_da_la_version_y_el_comando
FAILED tests/test_update.py::test_el_aviso_de_uv_tool_no_cambia_el_plan_ni_el_exit_code
3 failed, 105 passed
```

### El experimento que decidió el diseño

Antes de especificar se probó si `update` podía ejecutar el upgrade. Con `cowsay` —paquete
inocuo, para no tocar la instalación real—, lanzando `uv tool install cowsay@latest --force` desde
el Python de ese mismo entorno:

```
returncode: 2
error: failed to remove directory `…\uv\tools\cowsay\Scripts`: Acceso denegado. (os error 5)
import cowsay tras el upgrade: FALLO -> ModuleNotFoundError

$ uv tool list      → Failed find package `cowsay` in tool environment
$ cowsay -t hola    → ModuleNotFoundError: No module named 'cowsay'
```

**No es que falle: rompe la instalación.** Alcanza a borrar el paquete antes de estrellarse contra
el `Scripts/` bloqueado. Experimento limpiado (`uv tool uninstall cowsay`) y comprobado que
`local-delegate-mcp` seguía intacto.

## Quality checks

- [x] **Tests:** `uv run pytest -q` → **451 passed, 1 skipped**.
- [x] **Lint:** `uv run ruff check .` → *All checks passed!*
- [x] **Formato:** `uv run ruff format --check .` → *53 files already formatted*
- [x] **JS del dashboard:** `extract_dashboard_js.py` + `node --check` → OK.
- [x] **Secretos:** sin credenciales. El cambio **no ejecuta** ningún upgrade —que es su tesis—,
      no añade subprocesos, no sale a la red y no añade dependencias.
- [x] **Sin cambios ajenos:** `update.py`, `checks.py`, dos ficheros de test, `CHANGELOG.md`,
      `docs/wiki/Remote-backend.md` y la traza SDD.

## Deviations and residual risk

- **Hallazgo durante la implementación:** la primera versión de `uv_tool_lines` devolvía una línea
  vacía inicial como separador, y eso **rompió su propio test** de REQ-009: el filtro
  `line not in extra` borraba **todas** las líneas vacías de la salida y desalineaba la
  comparación. Se corrigió en el código, no en el test — la función devuelve **el aviso**, no su
  maquetación, y la separación la pone quien imprime. El test además ignora ahora las líneas
  vacías, que son presentación.
- **`PACKAGE in text` casa por subcadena** (hallazgo R-3 del plan). Con `local-delegate-mcp` es
  distintivo de sobra; queda anotado en el código por si algún día el nombre fuera corto.
- **`pipx`, `pip --user` y conda no se reconocen**, por diseño: caen en `OTHER` y reciben un texto
  genérico. Es mejor que el comportamiento anterior, que les sugería `uv tool upgrade` — un
  consejo que en esas instalaciones simplemente no hace nada.
- **No verificado en macOS ni Linux** más allá del CI del PR. La detección no usa nada específico
  de plataforma, que es justo por lo que se eligió el receipt en vez de `uv tool dir`.
