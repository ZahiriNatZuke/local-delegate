# Handoff: Check de doctor sobre los clientes MCP observados

## Current state

- SDD status: `closing` (los cinco gates aprobados salvo `memory`, que se cierra al persistir).
- Last completed gate: `conformance`.
- Current revision: rama `feat/check-clientes-observados`, base `023573b`.
- Suite: **553 passed, 1 skipped** (eran 539). Los cuatro pasos del CI en verde.

## What changed

`doctor` gana la comprobación **nº15**, `client.observed`: con qué clientes MCP se ha hablado —
nombre, versión, revisión de protocolo negociada y si declaran `elicitation`—. Cierra el hueco que
dejó el PR #95: el dato se registraba y nadie lo enseñaba por el camino que el usuario usa para
diagnosticar.

Ocho ficheros: `checks.py` (probe + colaborador + frases de tamaño), `clients.py` (solo el rename
de `_ruta_registro` a público), `update.py` (comentario de no reparables), tres de tests, la wiki y
el `CHANGELOG`.

## Decisions

- **La fuente es `clients.jsonl`, no `/api/status`.** Medido: el endpoint expone memoria del
  proceso del daemon, y Claude Code y Codex hablan por *stdio* con su propio proceso — el daemon
  del 9393 **no los ve**. Es la decisión que más condiciona el diseño y no se deriva del código.
- **El check es informativo: nunca `warn` ni `missing`.** Tres razones: un cliente sin
  `elicitation` no es una desviación de la configuración esperada; `warn` subiría el exit code de
  una máquina sana; y no existe `fix_hint` honesto que ofrecer.
- **Agrupar por nombre y quedarse con lo más reciente** no es cosmético: el registro acumula una
  línea **por arranque de proceso** (medido), así que sin agrupar el mismo cliente saldría repetido.
- **`doctor --home` no aísla el registro** y es correcto: `LOG_DIR` no deriva de `HOME`. No
  confundir con el defecto del change C, que sí escribía fuera del árbol simulado.
- **La rotación de `clients.jsonl` queda fuera** a propósito.

## Next action

Abrir el PR y mergearlo. Después, lo pendiente de la sesión: **publicar la 0.18.0** (solo con
confirmación explícita del usuario; el vigilante hará fallar el PR del bump hasta regenerar la
captura del README) y **observar `elicitation` en uso real**.

Contexto que ahorra tiempo a quien siga: el backend está **caído** en esta máquina ahora mismo, que
es justo la condición para provocar la pregunta de `elicitation` llamando a cualquier tool.

## Memory

- Canonical note: `projects/local-delegate/` — pendiente de escribir al cerrar la jornada.
- Indexes updated: pendiente (`MEMORY.md` de Claude Code + backlog del vault).
