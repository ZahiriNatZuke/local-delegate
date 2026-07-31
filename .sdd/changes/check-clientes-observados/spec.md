# Specification: Check de doctor sobre los clientes MCP observados

## Summary

`local-delegate doctor` gana una comprobación —la nº15— que responde **con qué clientes MCP ha
hablado local-delegate**: nombre, versión, revisión de protocolo negociada y si el cliente puede
responder preguntas (`elicitation`). Es **informativa y de solo lectura**: nunca falla ni cambia el
exit code por lo que encuentre, solo por no poder leerlo — y ni eso, porque no poder leerlo es
`unknown`.

## Requirements

- **REQ-001:** `checks.CHECKS` contiene un check con id `client.observed`, grupo `entorno` y título
  legible, situado junto a `client.presence`.
- **REQ-002:** El check lee las observaciones de **`clients.jsonl` dentro de `config.LOG_DIR`**, y
  **no** de `/api/status` ni de la memoria del proceso.
- **REQ-003:** La lectura se hace mediante un colaborador **inyectable** en `checks.Context`, con
  default que delega en el módulo real, devolviendo `(observaciones, motivo)` — mismo patrón que
  `version_of` y `latest_release`.
- **REQ-004:** El probe **no escribe nada**, ni siquiera crea el directorio o el fichero.
- **REQ-005:** Cuando no hay ninguna observación (fichero ausente, vacío o sin líneas válidas), el
  estado es **`unknown`** y el `detail` explica que todavía no se ha visto ningún cliente.
- **REQ-006:** Cuando el fichero existe pero **no se puede leer** (permisos, error de E/S), el
  estado es **`unknown`** y el `detail` incluye el motivo.
- **REQ-007:** Cuando hay al menos una observación válida, el estado es **`ok`**, con independencia
  de qué capabilities declaren los clientes.
- **REQ-008:** El `detail` lista **un cliente por nombre**, quedándose con su observación **más
  reciente**, e indica para cada uno su versión, la revisión de protocolo y si soporta
  `elicitation`.
- **REQ-009:** Una línea del JSONL que no sea JSON válido, o que no sea un objeto, **se salta** sin
  tumbar el diagnóstico; si quedan otras válidas, el check las usa.
- **REQ-010:** El check **no tiene `fix_hint`**: no hay comando del repo que lo arregle.
- **REQ-011:** La salida del check no contiene caracteres fuera de cp1252.
- **REQ-012:** Las cinco afirmaciones de tamaño de `checks.py` dicen «quince», y el mapa `_NUMERO`
  de `tests/test_checks.py` cubre el 15 — o sea, el test que impide que el módulo mienta sobre su
  tamaño sigue verde por decir la verdad, no por relajarse.
- **REQ-013:** `update.py` documenta `client.observed` entre los checks que **no** se reparan
  escribiendo en el HOME, y `REPAIRS` no lo incluye.
- **REQ-014:** La documentación que enumera las piezas que comprueba `doctor`
  (`docs/wiki/Integration-install.md`) refleja el número y el elemento nuevos.

## Acceptance scenarios

### Scenario: la máquina de hoy — nunca se vio un cliente

- **Given** un `LOG_DIR` sin `clients.jsonl` (el estado real de esta máquina con la 0.17.0)
- **When** el usuario ejecuta `local-delegate doctor`
- **Then** aparece la línea `[ -- ] clientes MCP observados: …` diciendo que aún no se ha visto
  ninguno, **y el exit code no sube por ello**

### Scenario: un cliente que sabe preguntar

- **Given** un `clients.jsonl` con la observación medida de Claude Code
  (`claude-code`, `2.1.220`, `2025-11-25`, caps `elicitation`+`roots`)
- **When** el usuario ejecuta `local-delegate doctor`
- **Then** la línea sale como `[ OK ]` y nombra `claude-code 2.1.220`, el protocolo `2025-11-25` y
  que **sí** puede responder preguntas

### Scenario: dos clientes, uno sin elicitation

- **Given** observaciones de `claude-code` (con `elicitation`) y de un cliente `mudo` sin ella
- **When** el usuario ejecuta `local-delegate doctor`
- **Then** el estado sigue siendo **`ok`**, y el `detail` distingue cuál puede responder preguntas
  y cuál no

### Scenario: el mismo cliente arrancó veinte veces

- **Given** un `clients.jsonl` con veinte líneas idénticas de `claude-code 2.1.220` y una anterior
  de `claude-code 2.1.219`
- **When** el usuario ejecuta `local-delegate doctor`
- **Then** el `detail` menciona `claude-code` **una sola vez**, con la versión de la observación
  **más reciente** (`2.1.220`)

### Scenario: registro a medio escribir

- **Given** un `clients.jsonl` cuya última línea quedó truncada por un proceso muerto, y una
  primera línea válida
- **When** el usuario ejecuta `local-delegate doctor`
- **Then** el diagnóstico **no se cae**, el estado es `ok` y se reporta el cliente de la línea buena

## Edge cases and failure behavior

- **Sin identidad, con capabilities.** Desde la revisión 2026-07-28 el `client_info` es opcional, así
  que `client` puede ser `null`. Esas observaciones se agrupan bajo una etiqueta explícita de
  «sin identificar» y no se descartan.
- **Fichero vacío o solo líneas en blanco** → igual que «sin observaciones»: `unknown`.
- **Un probe que lanza** → `run_all` lo convierte en `unknown` (comportamiento existente), pero el
  probe no debe apoyarse en eso: captura sus propios errores de E/S y los reporta como motivo.
- **`doctor --home <árbol simulado>`** seguirá leyendo el `LOG_DIR` **real** de la máquina, porque
  `LOG_DIR` no deriva de `HOME`. Es el mismo comportamiento que `service.daemon` y
  `service.backend`, y es deliberado: el registro de clientes es un dato de la máquina, no del HOME.

## Non-functional requirements

- **Solo lectura, garantizada por test**: `test_no_probe_writes_anything` debe seguir pasando con el
  check nuevo dentro.
- **Compatibilidad Windows**: nada fuera de cp1252 en la salida.
- **Coste**: una lectura de un fichero local. Sin red, sin subprocesos, sin timeouts. `doctor` no se
  ralentiza de forma apreciable.
- **Privacidad**: solo se muestran nombre de cliente, versión, protocolo y nombres de capabilities
  —lo que ya está en el registro—. No se leen ni se muestran rutas, prompts ni contenidos.
- **Sigue siendo una lista, no un framework**: el check nuevo es una entrada más en la tupla
  estática, sin registro dinámico.

## Non-goals

- **No se toca `clients.py`** en su escritura: ni formato, ni rotación, ni deduplicación en disco.
  El crecimiento del JSONL es real y queda anotado como pendiente, pero es otro cambio.
- **No se añade reparación** en `install` ni en `update`.
- **No se toca `/api/status`**, el dashboard ni su JS.
- **No se mide cómo pinta cada cliente la pregunta** de `elicitation`: eso es uso real, aparte.
- **No se arregla** la discrepancia preexistente entre el docstring de `Check` (`cliente | …`) y el
  grupo real (`entorno`).

## Traceability

| Requisito | Trabajo planificado | Evidencia de verificación |
| --- | --- | --- |
| REQ-001, REQ-011 | entrada en `CHECKS` + probe | test de id/grupo; ejecución real de `doctor` |
| REQ-002, REQ-003 | colaborador `clients_seen` en `Context` | test con colaborador doblado; test de que el default lee el JSONL |
| REQ-004 | probe sin escritura | `test_no_probe_writes_anything` |
| REQ-005, REQ-006 | ramas de «sin datos» y «no se pudo leer» | tests por escenario |
| REQ-007, REQ-008 | agregación por nombre + formato del detail | tests por escenario |
| REQ-009 | salto de líneas inválidas | test de JSONL corrupto |
| REQ-010 | `fix_hint` vacío | test que asevera `fix_hint == ""` |
| REQ-012 | frases de tamaño + `_NUMERO` | `test_el_docstring_dice_cuantos_checks_hay_de_verdad` |
| REQ-013 | comentario y `REPAIRS` de `update.py` | test de que `client.observed` no está en `REPAIRS` |
| REQ-014 | wiki | revisión del diff |
