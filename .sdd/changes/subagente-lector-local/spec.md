# Specification v2: que el hilo principal delegue en la tool directa (idea 1 de backlog §4.1, replanteada)

La v1 (`spec-v1-subagente.md`) proponía un subagente enrutador. La tarea 3 demostró que un
subagente **no puede devolver literal** la salida de la tool: el modelo que lo llama le añade
instrucciones de formato y el subagente las obedece por encima de su prompt, llegando a devolver el
doble de texto del que recibió; y Claude Code 2.1.280 ignora los tres mecanismos de hook que lo
habrían forzado (`updatedInput`, `deny` en `SubagentHandback`, `block` en `SubagentStop`). Evidencia
en `verification.md`. El usuario eligió replantear sin subagente (2026-09-22).

## Summary

La salida de una tool `local_*` llamada **desde el hilo principal** llega como `tool_result`:
literal por construcción. El problema a resolver es el que la investigación aisló: **el modelo
principal no decide delegar** (0/14 con solo descripciones; 12/14 cuando el prompt lo pide) y,
además, **nuestras tools son diferidas** —hay que cargar su esquema antes de llamarlas— mientras
los avisos actuales solo las nombran.

El cambio prueba, con un experimento controlado, variantes de los avisos de los hooks que atacan
esas dos causas, publica por defecto la que gane, y la mide en uso real con un criterio escrito
antes de medir. Si ninguna gana, no se publica nada y queda escrito por qué.

## Requirements

- **REQ-101 (variantes de oferta, seleccionables):** cada variante se activa con
  `LD_HOOK_OFERTA` (por defecto `v0`), sin reinstalar:
  - **V0 — actual** (línea base): los textos de hoy, byte a byte.
  - **V1 — receta lista:** el deny y el aviso de `suggest_delegate_read.py` y
    `suggest_delegate_shell.py` dicen **qué tool** conviene para ese tipo de fichero y dan la
    llamada completa: el paso para cargarla (`ToolSearch` con `select:<nombre exacto>`) y los
    argumentos con la ruta absoluta ya puesta. Objetivo: que delegar cueste un paso menos que leer
    por franjas.
  - **V2 — permiso permanente:** V1 más el hook de prompt, **solo cuando el prompt menciona un
    fichero, una ruta o un log**, formulado como permiso del usuario («tienes mi permiso
    permanente para pasar la lectura de ficheros grandes a las tools `local_*`…»), nunca
    «MANDATORY» ni en eventos del sistema.
- **REQ-102 (experimento de adopción):** un script en `scripts/` corre con `claude -p`, en
  sesiones nuevas, al menos 8 tareas realistas que exigen leer un fichero grande (docs, logs, un
  CHANGELOG, un diff, salida de lint, una imagen), sin mencionar delegación, bajo V0, V1 y V2.
  - **Corrida correcta** = la respuesta contiene el hecho verificable de la tarea **y** el
    contenido del fichero no entró al contexto principal: ni `Read` completo, ni `Read` por
    franjas del fichero, ni volcado por Bash.
  - **Una variante supera a V0 en una tarea** si tiene más corridas correctas que V0 en ella.
  - **Se publica por defecto la variante que supera a V0 en más tareas, mínimo 3 de 8**; el plan
    fija el desempate. Si ninguna llega, se retira el código de las variantes y el cambio se cierra
    con el resultado escrito.
- **REQ-103 (telemetría que permite verificar el experimento):** cada evento de los hooks registra
  la variante (`oferta`), la versión del hook y el estado efectivo del bloqueo de lectura.
- **REQ-104 (medición en uso real):** con la variante publicada, un script en `scripts/` mide en
  una ventana de **14 días** desde la release, solo sesiones nuevas y excluyendo las ventanas del
  experimento: lecturas grandes de prosa en el hilo principal, cuántas acabaron en una tool
  `local_*` con `path` (por el cruce `bloqueo_id` que ya existe y por coincidencia de ruta en el
  tiempo), cuántas escaparon por franjas o Bash, y errores de las tools.
- **REQ-105 (criterio, escrito antes de medir):**
  - **Se queda** si la tasa de lecturas grandes que acaban delegadas es al menos el doble de la
    medida en la ventana equivalente anterior con V0 (misma métrica, mismo script) y hay al menos
    10 delegaciones.
  - **Se retira** (vuelve a V0) si hay menos de 5 delegaciones, si la tasa no mejora, o si un
    solo caso muestra la oferta disparándose en un prompt que no mencionaba ningún fichero (V2).
  - Entre medias: no concluyente, se amplía una vez a 30 días.
- **REQ-106 (documentación):** CHANGELOG, README y `docs/wiki/` en la release que lo publique.
- **REQ-107 (sin datos privados):** los scripts no guardan contenido de ficheros ni rutas en claro
  (huella, como la telemetría).

## Acceptance scenarios

### Scenario: V0 no cambia nada
- **Given** `LD_HOOK_OFERTA` sin definir
- **When** se dispara cualquier hook
- **Then** el texto emitido es idéntico al actual y la telemetría añade solo los campos de REQ-103.

### Scenario: V1 da una llamada que funciona
- **Given** V1 y un `Read` bloqueado de un `.md` de 40 KB
- **When** el modelo sigue la receta del deny tal cual
- **Then** la tool se carga, recibe la ruta absoluta y devuelve un resultado sin error.

### Scenario: V2 calla donde debe
- **Given** V2
- **When** el prompt no menciona ningún fichero, o es un evento del sistema
- **Then** el hook de prompt no añade el permiso.

### Scenario: nadie gana
- **Given** ninguna variante supera a V0 en 3 de 8 tareas
- **When** se evalúa REQ-102
- **Then** el código de las variantes se retira, el valor por defecto sigue siendo el actual y el
  resultado queda en `verification.md` y en el vault.

## Edge cases and failure behavior

- Backend caído o modelo enfriado: los hooks ya no bloquean en ese caso; las variantes tampoco
  ofrecen una tool que no va a responder.
- El nombre de la tool en la receta tiene que ser el real del servidor: un test lo compara con el
  registro.
- Formato de transcript cambiado: los scripts fallan con un mensaje, nunca devuelven ceros.

## Non-functional requirements

- Solo Claude Code (los hooks son suyos). Codex, OpenCode y Claude Desktop no cambian.
- El experimento gasta cuota real: el script anuncia corridas y coste estimado y pide confirmación.
- Firma de commits, ruleset de `main` y code scanning como siempre.

## Non-goals

- **Subagente enrutador**: descartado por evidencia (T3). El trabajo queda en
  `archivo-agente-T1-T2.patch`.
- Comandos slash (idea 2 del backlog), plugin, trabajos en segundo plano, relevo.
- El contador anti-franjas al estilo de Serena (backlog).
- Cambiar tools o modelos locales, o el umbral del bloqueo.
- Integrar esto en `personal-dev-harness` (SDD aparte cuando este cierre).

## Traceability

| Requisito | Plan | Verificación |
| --- | --- | --- |
| REQ-101, REQ-103 | por definir | tests por variante + control instalado |
| REQ-102 | por definir | informe del experimento en `verification.md` |
| REQ-104, REQ-105 | por definir | informe a 14 días |
| REQ-106, REQ-107 | por definir | revisión de la release |
