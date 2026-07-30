# Handoff: install consume checks.CHECKS y anade --clients auto|claude,codex

## Current state

- **SDD status:** `closing` → cerrado con este documento.
- **Last completed gate:** `conformance` (los cinco aprobados salvo `memory`, que cierra aquí).
- **Current revision:** mergeado en `main` como `6b5a856` (PR #73, squash), con los 12 checks del
  PR en verde y el CI completo de `main` verificado después: CI, CodeQL y Vendor audit en éxito.
- **Sin publicar.** El change vive en `Unreleased`.

## What changed

Último change del andamiaje **A → B → C**. `install` deja de planificar a ciegas:

- **`--clients auto|claude|codex`** (repetible, default `auto`) en `install` y `uninstall`. `auto`
  configura solo los clientes presentes. `--target` se conserva con su semántica exacta; los dos
  juntos son error de uso.
- **`install --home` y `uninstall --home` ya no escriben fuera del árbol simulado.**
- **No se pisa una entrada MCP de Codex escrita a mano**: se pregunta; sin terminal se conserva;
  `--force-mcp-codex` la reemplaza.
- **Reporte final** con el estado real del andamiaje, con el formato del `doctor`.

## Decisions

Lo que un futuro lector no puede deducir del código:

1. **`install` NO se convirtió en un segundo `update`.** `checks` decide *a quién* se escribe y
   *qué no se pisa*; nunca decide *si* se escribe. Sobre un andamiaje sano, `install` lo reescribe
   entero — que es lo que arregla una instalación vieja. Si alguien «optimiza» esto para escribir
   solo lo que falta, rompe el verbo.
2. **`present_targets` es una función y no una lectura del check.** `client.presence` devuelve
   `Result(OK, "detectados: Claude Code, Codex")`: **texto de presentación, no datos**. Derivar de
   ahí a quién se le escribe la configuración ataría el instalador a un string de interfaz. Lo
   cazó la revisión adversarial del plan, cuando el diseño ya iba por ese camino.
3. **La confirmación es solo para `install`, no para `uninstall`.** Al instalar, reemplazar una
   entrada puesta a mano cambia la configuración del usuario por la nuestra; al desinstalar, la
   sección `[mcp_servers.local-delegate]` es nuestra por definición y retirarla es lo que se pidió.
   Está escrito en el código para que no se lea como olvido.
4. **El reporte final no altera el exit code**, y sale **también cuando una acción falla**. Lo
   segundo fue un hallazgo de la revisión de resultado: el primer corte devolvía 1 sin imprimir
   nada, o sea que el único caso sin información era aquel en que algo quedó a medias.
5. **El filtro por grupo de `run_all` es aditivo.** Se admitió tocar `checks.py` solo para eso; el
   registro sigue siendo doce elementos en una tupla estática y ningún `probe` cambió.

## Lo que enseñó, y vale más allá de este change

- **Una precaución de test puede esconder el bug.** Las 20 pruebas de `test_install.py` fijaban
  `use_cli=False` («jamás invocar el binario real desde la suite») — correcto, y con la
  consecuencia de que **ese camino no se probaba nunca**, que es exactamente donde vivía el
  defecto. Mismo patrón que `local_extract` con `text=` frente a `path=`.
- **`Path.home()` lee `USERPROFILE` en Windows y `HOME` en POSIX.** Un test que doble la variable
  de entorno pasa en Linux y macOS y falla en el runner de Windows. Hay que doblar `Path.home`.
- **`claude mcp add-json --scope user` ignora cualquier `--home`.** No es un detalle del
  instalador: es la razón por la que `--home` no era un sandbox en ninguno de los dos verbos.

## Next action

Nada pendiente de este change. Para la sesión:

1. **PR #74** (marca del header del dashboard) en vuelo.
2. **Lunes 2026-08-03:** comprobar si Dependabot propone subir `mcp>=2,<3`.
3. Backlog: el JSON cacheado de `update`, `uv tool upgrade`, el `rev` de ruff en pre-commit, el
   `doctor` que no compara contra PyPI, los hooks duplicados del `.sh` retirado.

## Memory

- **Canonical note:** pendiente de escribir en el vault al cerrar la sesión, junto con el PR #74.
- **Indexes updated:** pendiente.
