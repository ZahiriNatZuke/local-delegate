# Verificación: La landing vive en el repo y se publica en GitHub Pages

> **Verificación fresca del 2026-07-31**, hecha contra el sitio **publicado** y contra el árbol de
> `main`. No reproduce el acta original porque no hubo: la traza se commiteó en plantilla (ver
> `brief.md`). Todo lo de abajo se ejecutó hoy.

## Entorno

- Revisión del trabajo: PR **#65**, `19a84ee`, mergeado el 2026-07-30. Publicado en la **0.15.0**.
- `main` en `b8c43cd`; sitio publicado servido por GitHub Pages.
- Windows 11, Python 3.13 (`uv`), `curl` para las comprobaciones HTTP.

## Evidencia

| Requisito | Comprobación | Resultado |
| --- | --- | --- |
| REQ-001 | Test dedicado de paridad de claves entre los dos idiomas | pasa |
| REQ-002 | `gh run list --workflow=pages.yml` | tres últimas ejecuciones **`success`**; la vigente es la de `chore(release): 0.17.0` (#71) |
| REQ-002 | Disparadores declarados en `pages.yml` | `push` a `main` filtrado por `site/**`, `pyproject.toml`, `scripts/build_site.py` y el propio workflow, más `workflow_dispatch` |
| REQ-003 | `build_site.py --out <tmp>` sobre el árbol | `index.html: __LD_VERSION__ -> 0.17.0`, que es lo que declara `pyproject.toml` |
| REQ-003 | Página **publicada**: `softwareVersion` del JSON-LD | `0.17.0`; cero marcadores supervivientes en el HTML servido |
| REQ-004 | `build_site.py --check` sobre la salida | `OK: sin marcadores pendientes` |
| REQ-005 | Recursos externos en el HTML publicado | **ninguno**: no hay un solo `src`/`href` a un host de terceros |
| REQ-006 | Contenido de `site/` y ausencia de `docs/` en el workflow | se publica `site/`; `docs/` no aparece |
| — | La página responde | `200 text/html; charset=utf-8`, 38 060 B |

## Comprobaciones de calidad

- [x] `uv run pytest tests/test_site.py -q` → **23 pasan**.
- [x] Sin dependencias nuevas: `build_site.py` es solo stdlib.
- [x] Secretos: la página es pública por definición y no lleva credenciales.
- [x] Sin cambios ajenos: el diff del PR toca `site/`, `scripts/build_site.py`, `pages.yml`,
      `.gitignore`, `README.md`, `CHANGELOG.md` y `tests/test_site.py`.

## Desviaciones y riesgo residual

- **La traza se rellenó a posteriori.** Es la desviación de proceso que este cierre documenta y
  no la esconde: el trabajo se verificó, pero la especificación no lo guió.
- **La versión de la página es la del último despliegue, no la última publicada.** `pages.yml`
  solo corre cuando se toca `site/`, `pyproject.toml`, el build o el workflow. Como
  `pyproject.toml` está entre los disparadores, cada release redespliega y el número se pone al
  día solo. Hoy coinciden.
- **Dos defectos aparecieron en la propia revisión del PR y se arreglaron dentro:** un patrón de
  `.gitignore` con comentario al final de línea que no ignoraba nada —y coló la salida del build
  en un commit—, y un `EXE001` de ruff que **en Windows era invisible**, porque ruff solo
  comprueba el bit de ejecución en Unix.
