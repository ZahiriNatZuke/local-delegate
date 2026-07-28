# Implementation plan: Acotar el SDK mcp por debajo del major 2 y cerrar el punto ciego de resolucion libre

## Approach

Dos piezas independientes en un mismo PR, porque sin la segunda la primera se repite dentro de seis
meses con otra dependencia:

1. **El techo** (`mcp>=1.2,<2`). Una línea. Devuelve a `uvx` la resolución correcta y no toca una
   sola línea de código: la superficie del SDK en el repo (`server.py:32,36` y `daemon.py:116-117`)
   queda igual.
2. **El check que lo vigila.** Un job que construye el wheel, lo instala en un entorno limpio **sin
   `uv.lock`** —resolviendo como lo haría `uvx`— e intenta un handshake `initialize` real. Es la
   única forma de reproducir en CI lo que sufre un usuario: el lock, que es lo que hoy nos protege,
   es exactamente lo que nos ciega.

Se descarta migrar a la API 2.x en este cambio: dejaría a los usuarios rotos durante toda la
migración, y la superficie incluye `settings.streamable_http_path`/`streamable_http_app()`, cuyo
equivalente en 2.x no está verificado. El techo es reversible en una línea el día que se migre.

El script del handshake vive en `scripts/` (no en `scripts/dev/`) porque lo consume el CI, igual
que `scripts/extract_dashboard_js.py`.

## Ordered tasks

1. **Rama de trabajo**
   - Files or modules: —
   - Requirements covered: convenciones del repositorio
   - Verification: `git switch -c fix/mcp-sdk-major-pin` desde `main` al día
   - Rollback or recovery: borrar la rama

2. **Techo de major para `mcp`**
   - Files or modules: `pyproject.toml`
   - Requirements covered: REQ-001
   - Verification: `uv lock` regenera sin error; el diff es de una línea más comentario
   - Rollback or recovery: revertir la línea

3. **Regenerar el lock**
   - Files or modules: `uv.lock`
   - Requirements covered: REQ-001, REQ-009
   - Verification: `uv lock --check` pasa; `uv run pytest -q` verde contra la versión que quede
     fijada (anotar cuál: puede subir de 1.28.1 a 1.29.0)
   - Rollback or recovery: `git checkout uv.lock`. **Si la suite falla contra 1.29.0** (hallazgo F2
     de la revisión), se estrecha el techo a la última versión buena y la regresión de 1.x se
     investiga aparte — no se mezcla con este fix.

4. **Script de comprobación de instalación**
   - Files or modules: `scripts/check_install_handshake.py` (nuevo)
   - Requirements covered: REQ-002, REQ-003
   - Verification: ejecutado en local contra un venv limpio; sale 0 con el techo
   - Rollback or recovery: borrar el archivo
   - Detalle: arranca el server con `LOCAL_DELEGATE_WEB=0` y `LOCAL_DELEGATE_AUTOSTART=0` contra un
     `BASE_URL` muerto a propósito, manda `initialize` por stdio y exige `serverInfo` en la
     respuesta. Distingue en el mensaje un fallo de import (regresión de dependencia) de un fallo
     de red o de arranque, para no confundir un PyPI caído con una regresión.

5. **Job `install-smoke` en el CI**
   - Files or modules: `.github/workflows/ci.yml`
   - Requirements covered: REQ-004
   - Verification: el run del PR muestra el job en verde
   - Rollback or recovery: quitar el job
   - Detalle: solo `ubuntu-latest` (la resolución de dependencias no depende del sistema y el fallo
     es un import puro). Pasos: `uv build` → `uv venv` aislado → `uv pip install dist/*.whl` **sin**
     `uv sync` y sin el lock → `python scripts/check_install_handshake.py`. Comentario en el YAML
     explicando **por qué** no usa el lock, que es justo lo contrario de lo que hacen los otros jobs.
   - **Corrección del hallazgo F1 (bloqueante):** la instalación fuerza `--refresh` y
     `--resolution highest`. Un entorno limpio **no** implica caché limpia: con `mcp` 1.x cacheado,
     `uv` podría satisfacer `mcp>=1.2` sin consultar el índice y el job pasaría aunque el techo no
     estuviera puesto. Sería un check incapaz de fallar — el mismo defecto que este cambio combate.

6. **Prueba negativa deliberada**
   - Files or modules: — (no se commitea)
   - Requirements covered: REQ-005
   - Verification: repetir el paso 4 forzando `mcp>=2` en el entorno limpio; debe **fallar** con el
     `ModuleNotFoundError`. Se pega la salida en `verification.md`.
   - Rollback or recovery: el entorno es temporal, en el scratchpad

7. **CHANGELOG**
   - Files or modules: `CHANGELOG.md`
   - Requirements covered: REQ-007
   - Verification: entrada bajo `[Unreleased] / Fixed` que nombra el síntoma `-32000` y dónde está
     el traceback real
   - Rollback or recovery: revertir

8. **Bump a 0.12.2**
   - Files or modules: `pyproject.toml`, `server.json` (dos sitios), `uv.lock`
   - Requirements covered: REQ-006
   - Verification: `uv run python scripts/bump_version.py 0.12.2` y luego `--check`; mover la
     sección `[Unreleased]` a `[0.12.2]`
   - Rollback or recovery: `bump_version.py 0.12.1`
   - Nota: arrastra a la release los PR #29 y #30, que estaban represados en `main` por tocar solo
     `scripts/`. Se mencionan en la entrada del CHANGELOG.

9. **Los cuatro pasos del CI en local, con `.`**
   - Files or modules: —
   - Requirements covered: REQ-009 y la regla de proceso del proyecto
   - Verification: `ruff check .`, `ruff format --check .`, `pytest -q`, `extract_dashboard_js.py` +
     `node --check`. **Con `.`, no con rutas parciales.**
   - Rollback or recovery: —

10. **PR y CI**
    - Files or modules: —
    - Requirements covered: REQ-004, REQ-008
    - Verification: los 6 checks requeridos en verde **más** `install-smoke`; comprobar
      `gh run list` **después** del merge, no solo los checks del PR
    - Rollback or recovery: revertir el merge
    - Nota: **no se toca el ruleset.** `install-smoke` queda como check informativo hasta
      comprobar que reporta en un PR real (REQ-008).

11. **Publicación — solo con confirmación explícita del usuario**
    - Files or modules: tag `v0.12.2`
    - Requirements covered: REQ-006
    - Verification: `publish.yml` encadena `check-version → pypi → mcp-registry`; después,
      GitHub Release a mano, depscore del paquete y verificación del registro
    - Rollback or recovery: PyPI es **inmutable**; un error obliga a 0.12.3. De ahí que el
      `check-version` y el `--check` del bump vayan antes del tag.
    - Verificación final real: `uvx local-delegate-mcp` **sin pin** en la Mac del usuario. Es la
      única prueba de que el problema reportado quedó cerrado donde apareció.

## Test strategy

- **Unit:** la suite existente (`uv run pytest -q`) contra la versión de `mcp` que quede en el lock.
  No se añaden tests unitarios: el cambio es de metadatos de empaquetado, no de comportamiento.
- **Integration:** `scripts/check_install_handshake.py` sobre el wheel construido en un entorno
  limpio con resolución libre. Es la prueba que faltaba.
- **End-to-end o manual:** `uvx local-delegate-mcp` sin pines en la Mac tras publicar.
- **Prueba negativa:** forzar `mcp>=2` y comprobar que el check falla (REQ-005). Sin esto, el job
  nuevo es decorativo.
- **Security y secret scanning:** `gitleaks` en pre-commit y en el job `secrets`. El cambio no
  introduce credenciales; el job nuevo no necesita ninguna.

## Migration and compatibility

- **Sin cambio de comportamiento.** Solo se estrecha el rango admisible de una dependencia.
- **Quien ya aplicó el workaround** `--with "mcp<2"` no se rompe: el techo es compatible con él.
  Puede retirarlo tras actualizar, pero no es obligatorio.
- **El daemon de Windows** no está afectado (venv editable con lock). Tras el merge se reinicia
  como siempre: `Stop-Process` del pid + `Start-ScheduledTask LocalDelegateDaemon`.
- **Compatibilidad hacia adelante:** el techo bloquea 2.x a propósito. La migración es un cambio
  SDD aparte y es la vía para levantarlo.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
