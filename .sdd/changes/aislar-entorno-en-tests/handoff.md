# Handoff: La suite no puede heredar el entorno de quien la corre

## Current state

- SDD status: `closed` (modo lite).
- Last completed gate: `memory`.
- Current revision: `main` @ `0436aa4` (squash de la PR #135).

## What changed

`config` lleva ahora su propio inventario de variables de entorno (`VARIABLES_DE_ENTORNO`, 34),
alimentado por las lecturas reales del módulo a través de `_leer`, que es su única puerta a
`os.environ`. `tests/conftest.py` usa ese inventario para correr la suite como si ninguna variable
del paquete estuviera definida, recargando el módulo. `tests/test_aislamiento_entorno.py` añade tres
guardianes.

Efecto: `uv run pytest` da `725 passed, 2 skipped` tanto en una máquina con el daemon instalado como
en CI. Antes daba cuatro fallos `401 == 200` en la primera.

## Decisions

- **Recargar `config` en vez de reasignar constantes** en el conftest. Copiar los defaults allí
  crearía una segunda fuente de verdad que envejece en silencio — el defecto recurrente del repo.
  El reload es seguro **porque nadie hace `from local_delegate.config import <constante>`**;
  comprobado por búsqueda. Si algún día alguien lo hiciera, esta decisión deja de ser válida.
- **La lista de variables no se escribe a mano** por el mismo motivo, y se congela al final de
  `config.py` a propósito: declararla antes dejaría fuera lo que se lea más abajo.
- **Lo capturado en tiempo de import queda fuera de alcance** (`server._chat_slots` fija
  `MAX_CONCURRENT_REQUESTS` al importar). Declarado y medido, no olvidado.

## Next action

Nada pendiente. GitHub queda sin alertas de ningún tipo, sin issues y sin PRs abiertos.

## Memory

- Canonical note: `obsidian-vault/projects/local-delegate/jornada-2026-08-03-las-alertas-de-codeql.md`,
  sección de cierre (misma jornada: esto es la deuda que dejó la PR #133).
- Indexes updated: memoria del proyecto en Claude Code — el gancho del gotcha de
  `LOCAL_DELEGATE_WEB_TOKEN` pasa de «deuda abierta» a resuelto, con el patrón que lo cierra.
- Sin secretos ni datos personales en los artefactos.
