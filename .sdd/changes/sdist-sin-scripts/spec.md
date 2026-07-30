# Especificación — sacar `scripts/` del sdist y retirar el instalador de hooks de macOS

## Resumen

El paquete que se publica en PyPI deja de distribuir el taller del repositorio. En concreto
desaparece `scripts/install_claude_code_hooks_macos.sh`, un instalador que descargaba código
Python de `raw.githubusercontent.com` sin verificar hash ni firma, lo registraba en
`~/.claude/settings.json` y lo ejecutaba acto seguido. Está obsoleto (clavado en `v0.10.0`),
huérfano (nadie lo referencia), apunta a una ruta que ya no existe en `main` y duplica una función
que el CLI `install` cubre desde recursos empaquetados, sin red.

Quien instala el paquete no pierde nada: el wheel no cambia.

## Requisitos

- **REQ-001:** `scripts/install_claude_code_hooks_macos.sh` no existe en el repositorio.
- **REQ-002:** El sdist construido no contiene ninguna entrada bajo `scripts/`.
- **REQ-003:** El contenido del wheel es idéntico, fichero a fichero, al de antes del cambio.
- **REQ-004:** Los tests que dependen de `scripts/` (`tests/test_vendor.py`,
  `tests/test_bump_version.py`) siguen ejecutándose con normalidad sobre el repositorio, y se
  saltan de forma explícita —no fallan— cuando el script del que dependen no está presente.
- **REQ-005:** El `CHANGELOG.md` recoge el cambio en `Unreleased`.

## Escenarios de aceptación

### Escenario: el sdist ya no lleva el taller

- **Dado** un checkout limpio de la rama del cambio
- **Cuando** se ejecuta `uv build --sdist`
- **Entonces** el tarball resultante no contiene ninguna ruta que empiece por
  `local_delegate_mcp-<versión>/scripts/`

### Escenario: quien instala no nota nada

- **Dado** el wheel construido antes del cambio y el construido después
- **Cuando** se comparan sus listas de ficheros
- **Entonces** ambas coinciden exactamente (29 entradas)

### Escenario: la suite sigue cubriendo lo mismo en el repositorio

- **Dado** el repositorio completo
- **Cuando** se ejecuta `pytest -q`
- **Entonces** los tests de `test_vendor.py` y `test_bump_version.py` se ejecutan y pasan; ninguno
  queda saltado

### Escenario: la suite degrada, no revienta, sin `scripts/`

- **Dado** un árbol donde `scripts/check_vendor.py` y `scripts/bump_version.py` no existen
- **Cuando** se ejecuta `pytest -q`
- **Entonces** los tests que los necesitan quedan marcados como saltados con un motivo legible, y
  la suite termina sin fallos

## Casos límite y comportamiento ante fallo

- El `skip` de REQ-004 debe condicionarse a la ausencia real del fichero en disco, nunca a una
  variable de entorno ni al sistema operativo: un `skip` que se active por error dejaría el
  vendorizado y el bump de versión sin cobertura sin que nadie se entere.
- La exclusión en `[tool.hatch.build.targets.sdist]` debe usar la misma forma que las cuatro
  entradas ya presentes (`/ruta`), para que no dependa del directorio desde el que se construya.

## Requisitos no funcionales

- **Seguridad:** el objetivo primario. El paquete publicado deja de contener un vector de
  ejecución de código remoto sin verificación de integridad.
- **Compatibilidad:** ninguna ruta de instalación soportada (`uv tool install`, `pipx`, `uvx`)
  usa el sdist ni los ficheros retirados.

## No objetivos

- **No se toca el blob vendorizado de Chart.js.** Sus alertas («utiliza eval», «acceso a la red»)
  son ruido de bundle minificado; el UMD de Chart.js solo se publica minificado y la única
  alternativa legible es el ESM, que obligaría a cambiar el arranque del dashboard. El vendorizado
  ya está protegido con manifiesto, hash y auditoría OSV.
- **No se persigue el número del score.** El fin es retirar el riesgo real; que Socket recalcule o
  no es consecuencia, no criterio de aceptación.
- **No se excluye `tests/`, `docs/`, `.github/`, `site/` ni `benchmarks/` del sdist.** Se consideró
  y se descarta: excede el alcance aprobado, y un sdist con tests es útil para quien reconstruya el
  paquete. La incoherencia que dejaba `scripts/` fuera se resuelve con REQ-004, no ampliando la
  poda.
- **No se reescribe ni se sustituye el instalador de macOS.** Su función ya la cumple el CLI
  `install`; recrearlo sería reintroducir el problema.
- **No se tocan las alertas de dependencias de terceros.** Ninguna es accionable; quedan
  documentadas en `research.md`.

## Trazabilidad

| Requisito | Trabajo previsto | Evidencia de verificación |
| --- | --- | --- |
| REQ-001 | Borrado del fichero | `git status` y ausencia en el árbol |
| REQ-002 | `exclude` en `[tool.hatch.build.targets.sdist]` | Listado del tarball construido |
| REQ-003 | Ninguno (efecto colateral a comprobar) | Diff de las listas de ficheros del wheel |
| REQ-004 | `pytest.skip` condicionado a la existencia del fichero | Suite completa + prueba en árbol podado |
| REQ-005 | Entrada en `Unreleased` | `CHANGELOG.md` |
