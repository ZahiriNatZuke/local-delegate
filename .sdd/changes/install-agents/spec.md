# Specification: local-delegate install --agents mantiene los subagentes al dia con el catalogo real

## Summary

`local-delegate install --agents` mantiene los subagentes de `~/.claude/agents/` al día con las
tools que expone el MCP: añade al frontmatter `tools:` las que falten y actualiza un bloque de
catálogo delimitado por marcadores. Sustituye a `docs/recipes/update_agents.py`, que no llegaba a
ninguna máquina instalada y cuyo catálogo, escrito a mano, **ya decía «10 tools» habiendo once**.

El catálogo pasa a derivarse de la tabla de `SKILL.md` —recurso empaquetado y única fuente— y un
test nuevo garantiza que esa tabla liste exactamente las tools que registra el servidor.

## Requirements

### El catálogo, con una sola fuente que no puede mentir

- **REQ-001:** Existe una función que devuelve el catálogo de tools —nombre y descripción corta—
  parseando la tabla de `resources/skills/delegacion-local/SKILL.md`.
- **REQ-002:** Un test compara ese catálogo con las tools que registra `server.mcp.list_tools()` y
  **falla si difieren en un solo nombre**. Sin esto se cambiaría una fuente desincronizada por otra
  que puede desincronizarse.
- **REQ-003:** El camino de `install` **no importa `server.py`**: arrastra el SDK MCP y uvicorn.
  (El test sí puede, porque es donde se comparan las dos cosas.)
- **REQ-004:** El bloque generado dice cuántas tools hay, y ese número sale del catálogo, no de una
  constante.

### Qué hace `--agents`

- **REQ-005:** `install --agents` es **opt-in**: sin el flag no se toca ningún subagente.
- **REQ-006:** Solo se procesan los ficheros `~/.claude/agents/*.md` cuyo frontmatter `tools:`
  contenga ya el ancla `mcp__local-delegate__local_delegate`. Los demás **ni se leen para
  escribir**.
- **REQ-007:** En un agente procesado, se añaden a la línea `tools:` las tools del catálogo que
  falten, sin reordenar ni tocar el resto de la línea.
- **REQ-008:** El bloque de catálogo va entre marcadores. Si ya existe, se reemplaza su contenido;
  si no, se inserta tras la sección de delegación reconocible.
- **REQ-009:** Si no se reconoce una sección de delegación, **no se inserta nada**: no se adivina
  dónde va.
- **REQ-010:** Cada fichero modificado deja una copia `.bak`, como el resto de las escrituras de
  `install`.
- **REQ-011:** `--dry-run` no escribe nada y anuncia qué cambiaría.
- **REQ-012:** Idempotente: una segunda pasada no planifica ni escribe nada.
- **REQ-013:** Sin `~/.claude/agents/`, o sin ningún agente que delegue, el comando lo dice y
  termina bien.
- **REQ-014:** El reporte final dice cuántos agentes se revisaron y cuántos cambiaron.

### Retirada y documentación

- **REQ-015:** `docs/recipes/update_agents.py` deja de existir.
- **REQ-016:** `CHANGELOG.md` recoge el cambio bajo `Unreleased` (CRLF) y la wiki documenta el
  flag nuevo.
- **REQ-017:** Los mensajes no usan caracteres fuera de cp1252.

## Acceptance scenarios

### Scenario AC-1: un agente que delega y está desactualizado

- **Given** un agente con el ancla en `tools:` y sin `local_describe_image`, y con una sección
  «Delegación a modelos locales»
- **When** se ejecuta `local-delegate install --agents`
- **Then** su `tools:` incluye la tool que faltaba, aparece el bloque de catálogo con las once, y
  queda un `.bak` al lado

### Scenario AC-2: un agente ajeno no se toca

- **Given** un agente cuyo `tools:` **no** menciona nuestras tools
- **When** se ejecuta `local-delegate install --agents`
- **Then** su fichero queda **byte a byte idéntico** y no se crea ningún `.bak`

### Scenario AC-3: sin el flag no pasa nada

- **Given** agentes desactualizados
- **When** se ejecuta `local-delegate install` sin `--agents`
- **Then** el directorio de agentes queda byte a byte idéntico

### Scenario AC-4: `--dry-run`

- **Given** agentes desactualizados
- **When** se ejecuta `local-delegate install --agents --dry-run`
- **Then** se anuncia el cambio y el árbol queda byte a byte idéntico

### Scenario AC-5: idempotencia

- **Given** agentes ya actualizados
- **When** se ejecuta otra vez `install --agents`
- **Then** no se planifica ninguna acción y el reporte dice que estaban al día

### Scenario AC-6: la skill no puede mentir

- **Given** una tool nueva registrada en el servidor y ausente de la tabla de `SKILL.md`
- **When** corre la suite
- **Then** el test de REQ-002 **falla**, nombrando la que falta

## Edge cases and failure behavior

- **`~/.claude/agents/` no existe:** se dice y se termina bien (exit 0). No es un error.
- **Un agente ilegible o con frontmatter roto:** se salta, se reporta, y el resto continúa.
- **Un agente sin sección de delegación reconocible:** se actualiza su `tools:` si procede, pero
  **no** se inserta bloque (REQ-009).
- **La tabla de `SKILL.md` ilegible:** el catálogo queda vacío y **no se toca ningún agente**; la
  degradación segura de una escritura es no escribir.
- **Marcadores desparejados** (solo el de apertura): no se reemplaza nada y se reporta, en vez de
  arrasar hasta el final del fichero.

## Non-functional requirements

- **Seguridad:** se escribe en ficheros del usuario. Opt-in, solo los que ya declaran el ancla,
  `.bak` siempre, y bloque delimitado — fuera de los marcadores no se toca nada.
- **Sin dependencias nuevas.**
- **Portabilidad:** sin rutas ni comportamientos por sistema operativo.
- **Sin coste en el arranque:** no se importa el servidor MCP.

## Non-goals

- Que `--agents` sea el default.
- Tocar agentes que no declaran ya nuestras tools.
- `uninstall --agents`: retirar el bloque es simétrico, pero qué hacer con las tools ya añadidas
  al `tools:` —que el usuario pudo editar— no tiene respuesta obvia.
- Cambiar el formato de los subagentes o el contenido de la skill.

## Traceability

| Requisito | Trabajo previsto | Evidencia |
|---|---|---|
| REQ-001..REQ-004 | Parseo del catálogo + test de paridad | tests de parseo y de paridad con el servidor |
| REQ-005..REQ-014 | Lógica portada de la receta + acción de `install` | tests de los seis escenarios y de los bordes |
| REQ-015..REQ-017 | Borrado, CHANGELOG y wiki | revisión del diff |
