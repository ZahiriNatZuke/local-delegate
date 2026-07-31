# Brief: local-delegate install --agents mantiene los subagentes al dia con el catalogo real

## Problem

`docs/recipes/update_agents.py` propaga las tools de local-delegate al frontmatter `tools:` de los
subagentes de `~/.claude/agents/` y mantiene en ellos un bloque de catálogo. Tiene dos problemas,
y el segundo es el de fondo.

**1. Está mal colocado.** El criterio del repositorio, escrito en `Remote-backend.md`, es *lo que
ejecuta el usuario va al CLI; lo que ejecuta el repositorio se queda en `scripts/`*. Una receta en
`docs/` no llega a ninguna máquina instalada: no viaja en el wheel, no sale en `--help`, no la
prueba pytest y no corre en los tres sistemas.

**2. Su catálogo está escrito a mano, y ya se desincronizó.** Medido:

| Fuente | Dice |
|---|---|
| `server.mcp.list_tools()` (y `test_smoke.py`) | **11 tools** |
| `docs/recipes/update_agents.py`, `CATALOG_BODY` | «**10 tools**», sin `local_describe_image` |

Y el caso de uso no es teórico: **27 subagentes** de esta máquina declaran tools
`mcp__local-delegate__*`. Cada tool nueva obliga a acordarse de un fichero que nadie ejecuta desde
el CI.

Es el mismo defecto que esta sesión ya corrigió dos veces —la versión de ruff en `pre-commit`, el
comando de upgrade repartido entre dos módulos—: **dos fuentes para el mismo dato**.

## Lo que el research encontró, y cambia el diseño

**El catálogo canónico ya existe como recurso empaquetado.** `resources/skills/delegacion-local/
SKILL.md`, líneas 36-46, tiene la tabla de las once tools con nombre y descripción corta. Viaja en
el wheel, la instala `install` y es lo que el usuario ya lee.

Así que el bloque de los agentes no hay que escribirlo: hay que **derivarlo de ahí**. Eso evita
además importar `server.py`, que arrastra el SDK MCP y uvicorn — el mismo motivo por el que
`checks.py` difiere sus imports.

**Pero hay un agujero que hay que tapar primero:** `test_smoke.py::test_eleven_tools_registered`
compara las tools del servidor con una lista esperada, y **nadie compara esa lista con la tabla de
`SKILL.md`**. O sea que la fuente «canónica» **puede mentir**, exactamente igual que mintió la
receta. Sin ese test, el cambio sustituiría una fuente desincronizada por otra que puede
desincronizarse.

## Desired outcome

- `local-delegate install --agents` (**opt-in**, nunca por defecto) revisa `~/.claude/agents/*.md`,
  añade al `tools:` las tools que falten y actualiza el bloque de catálogo.
- El catálogo sale de la tabla de `SKILL.md`, y un test garantiza que esa tabla lista **exactamente**
  las tools que registra el servidor.
- `docs/recipes/update_agents.py` desaparece: su trabajo lo hace el CLI.

## In scope

- Parseo de la tabla de tools de `SKILL.md` y el test que la ata a `server.mcp.list_tools()`.
- La lógica de la receta, portada: detección de «agente que delega», actualización de `tools:` e
  inserción/reemplazo del bloque entre marcadores.
- El flag `--agents` en `install`, integrado en `plan_install` para que `--dry-run` funcione.
- Retirar la receta y documentar el cambio.

## Out of scope

- **Que `--agents` sea el comportamiento por defecto.** Los subagentes son del usuario, no
  andamiaje nuestro; tocarlos sin pedirlo sería el mismo error que el viejo `--target all`, que
  creaba `~/.codex/` en máquinas sin Codex.
- **Tocar agentes que no declaran ya nuestras tools.** La receta solo actúa sobre los que tienen
  el ancla `mcp__local-delegate__local_delegate`, y esa regla se conserva: es lo que impide que el
  instalador reescriba subagentes ajenos.
- **`uninstall --agents`.** Retirar el bloque de catálogo es simétrico y tentador, pero abre la
  pregunta de qué hacer con las tools ya añadidas al `tools:` —que el usuario puede haber editado—
  y no hay respuesta obvia. Se deja fuera y se dice.
- Cambiar el formato de los subagentes o el contenido de la skill.

## Constraints and risks

- **Riesgo principal: escribir en ficheros del usuario que no son nuestros.** Los subagentes los
  escribió él. Mitigaciones: opt-in explícito, solo los que ya declaran el ancla, `.bak` como el
  resto de escrituras de `install`, y el bloque delimitado por marcadores —lo de fuera no se
  toca—.
- **La heurística de inserción es delicada.** La receta busca el encabezado «Delegación a modelos
  locales» y mete el bloque antes del siguiente `##`; si no la reconoce, **no inserta nada** (no
  adivina). Esa prudencia se conserva tal cual.
- **No importar `server.py`** desde el camino de `install`: arrastra el SDK MCP y uvicorn.
- **27 agentes reales en esta máquina** son un banco de pruebas excelente, pero también significa
  que un error se multiplica por 27. El `--dry-run` tiene que ser fiable antes de tocar nada.

## Open questions

- ~~¿Al CLI, arreglar la receta, o borrarla?~~ **Resuelto por el usuario:** al CLI, derivando el
  catálogo del MCP.
