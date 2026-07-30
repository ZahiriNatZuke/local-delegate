# Plan de implementación — sacar `scripts/` del sdist y retirar el instalador de hooks de macOS

## Enfoque

Tres cambios pequeños e independientes entre sí, más el registro en el CHANGELOG. El orden importa
solo en un punto: el `skip` de los tests (T3) debe existir **antes** de poder verificar T2 en un
árbol podado, porque si no la comprobación acaba en un error de colección en vez de en un salto
limpio.

Se ataca la causa, no el síntoma: el fichero se borra en vez de excluirse del empaquetado. Excluir
lo dejaría en el repositorio invitando a ejecutarlo, y lo que hace —descargar código de la red y
ejecutarlo sin verificar integridad— no mejora por no publicarse.

El `exclude` del sdist es la parte que responde al alcance aprobado y quita las cuatro entradas de
«Acceso Shell» que aportan `bump_version.py`, `check_install_handshake.py`, `macos_mcp_canary.py`
y `release.py`.

## Tareas ordenadas

1. **T1 — Borrar el instalador de hooks de macOS**
   - Ficheros: `scripts/install_claude_code_hooks_macos.sh` (borrado)
   - Requisitos: REQ-001
   - Verificación: el fichero no está en el árbol; `git status` muestra el borrado y nada más
   - Reversión: `git checkout -- scripts/install_claude_code_hooks_macos.sh`
   - Nota: no requiere sustituto. El CLI `install` ya coloca los mismos cuatro hooks desde
     `resources/hooks/`, sin red. Verificado en la investigación.

2. **T2 — Excluir `scripts/` del sdist**
   - Ficheros: `pyproject.toml`, bloque `[tool.hatch.build.targets.sdist]`
   - Requisitos: REQ-002, REQ-003
   - Cambio: añadir `"/scripts"` a la lista `exclude`, con la misma forma de ruta absoluta que las
     cuatro entradas ya presentes, y un comentario que explique el porqué (es un repositorio donde
     las decisiones de empaquetado se documentan en el propio `pyproject.toml`)
   - Verificación: `uv build --sdist` y listado del tarball; cero entradas bajo `scripts/`. Y
     `uv build --wheel` con comparación de la lista de ficheros contra la del wheel actual
   - Reversión: quitar la línea

3. **T3 — Que los tests dependientes se salten en vez de reventar**
   - Ficheros: `tests/test_vendor.py`, `tests/test_bump_version.py`
   - Requisitos: REQ-004
   - Cambio: en ambos, extraer la ruta del script a una constante de módulo y, justo antes de la
     llamada a `_load_script()`, un `pytest.skip(..., allow_module_level=True)` condicionado a
     `not SCRIPT.exists()`. Tiene que ser a nivel de módulo: hoy los dos ficheros ejecutan
     `_load_script()` en el cuerpo del módulo (`test_vendor.py:39`, `test_bump_version.py:28`), así
     que sin fichero el fallo ocurre al **coleccionar**, y un `skipif` por test no llegaría a
     tiempo
   - Condición: **la ausencia del directorio `scripts/` entero**, no la del fichero suelto. La
     revisión del plan (H2) detectó que condicionarlo al fichero convierte un borrado accidental de
     `check_vendor.py` o `bump_version.py` en un CI verde: el test se saltaría en silencio. Con la
     condición sobre el directorio, «sdist podado» y «alguien borró el script» dejan de ser
     indistinguibles — el segundo sigue fallando, como debe
   - Ni variable de entorno, ni sistema operativo, ni `try/except ImportError`: un salto que se
     dispare por otra causa deja el vendorizado y el bump de versión sin cobertura en silencio
   - Verificación: ver «Estrategia de prueba», que incluye la comprobación al revés
   - Reversión: revertir ambos ficheros

4. **T4 — Registrar el cambio**
   - Ficheros: `CHANGELOG.md`, sección `Unreleased`
   - Requisitos: REQ-005
   - Cuidado: el fichero es **CRLF**. Editarlo con here-strings de PowerShell mete líneas LF y
     backticks de escape. Se edita con la herramienta de edición directa o con Python abriendo con
     `newline=""`

## Estrategia de prueba

- **Unitaria:** suite completa con `uv run pytest -q --basetemp=<temp propio>`. Los 386 tests deben
  seguir pasando y —esto es lo que se comprueba, no que «pase»— **ninguno debe quedar saltado** en
  `test_vendor.py` ni en `test_bump_version.py`. Un skip aquí significaría que la condición se
  disparó cuando no debía.
- **Al revés (obligatorio por convención del repositorio):** copiar el árbol a un directorio
  temporal, borrar `scripts/` de la copia y ejecutar `pytest tests/test_vendor.py
  tests/test_bump_version.py` allí. El resultado esperado es **saltados, no errores de colección**.
  Sin esta prueba, el `skip` no está verificado: un condicional mal escrito se ve idéntico a uno
  bien escrito mientras el fichero exista.
- **Empaquetado:** `uv build` (sdist + wheel) y listado de ambos artefactos. El sdist baja de 124 a
  109 entradas; el wheel se mantiene en 29 idénticas.
- **Integración:** los cuatro pasos del CI antes del push — `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pytest -q --basetemp=<temp propio>`, y
  `extract_dashboard_js.py` + `node --check`.
- **Secretos:** el cambio no introduce ficheros nuevos con contenido; el borrado no puede filtrar
  nada. `secrets` y GitGuardian corren igualmente en el CI.

## Migración y compatibilidad

- **Ninguna ruta de instalación se ve afectada.** `uv tool install`, `pipx` y `uvx` resuelven el
  wheel, que no cambia (REQ-003 lo fija como requisito verificable, no como suposición).
- **Quien tuviera hooks instalados por el `.sh`** no se ve afectado: los ficheros ya están en su
  `~/.claude/hooks/` y su `settings.json` sigue apuntándolos. Si quiere actualizarlos, el camino es
  `local-delegate install`, que es el que debía haber usado desde el principio.
- **El sdist sigue siendo construible e instalable**: `pyproject.toml`, `src/`, `README.md` y
  `LICENSE` no se tocan.

## Revisión del plan

- [x] Cada requisito tiene al menos una tarea y un paso de verificación — REQ-001→T1, REQ-002→T2,
      REQ-003→T2 (comparación de wheels), REQ-004→T3, REQ-005→T4
- [x] Las operaciones destructivas tienen reversión: el único borrado es un fichero versionado en
      git, recuperable con `git checkout`, y sin referencias entrantes (verificado)
- [x] Cambios de configuración explícitos: una línea en `[tool.hatch.build.targets.sdist]`
- [x] El plan no incluye trabajo ajeno: el blob de Chart.js, las alertas de dependencias y la poda
      de `tests/`, `docs/` o `.github/` del sdist quedan fuera por escrito en los no objetivos
