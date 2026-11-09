# Specification: Hooks, mod y caché: lecturas sin MCP, prefiltro multilínea y fallo pasajero

## Summary

Los hooks de lectura y de shell dejan de mandar a tools `local_*` que la sesion no tiene; el prefiltro
del mod deja de saltarse los comandos de varias lineas o con sustitucion; y un fallo pasajero al leer
`test-windows.json` o `backend-params.json` deja de quedarse en cache.

## Requirements

<!-- One block per requirement. Request quotes the literal fragment of the request, or says
"derived: <reason>". Verify starts with one method: test, cmd, manual or review. -->

- **REQ-001** — Con un transcript cuyos `deferred_tools_delta` dejan un conjunto neto sin ninguna tool
  `*local-delegate__local_*`, sin servidor `local-delegate` pendiente y sin ningun `tool_use` de una de
  ellas, el hook de `Read` (prosa grande, codigo en subagente e imagen) y el de shell no emiten aviso
  ni bloqueo y registran `reason="mcp_absent"`.
  - Request: "hooks PreToolUse de Read sugieren local_* sin el MCP cargado"
  - Verify: test tests/test_hooks_mcp_absent.py
- **REQ-002** — Sin transcript, ilegible, mayor que el tope, sin ningun `deferred_tools_delta`, con la
  tool en el conjunto neto, con el servidor pendiente o con un `tool_use` de una `local_*`, el
  comportamiento es el de hoy (aviso o bloqueo). En un subagente se mira su propio transcript
  (`<sesion>/subagents/agent-<agent_id>.jsonl`) si existe; un `agent_id` con forma invalida no
  construye ruta.
  - Request: derived: no regresion; falso negativo antes que falso positivo
  - Verify: test tests/test_hooks_mcp_absent.py
- **REQ-003** — El prefiltro del mod manda al clasificador un comando de shell con salto de linea,
  comilla invertida o `$(` aunque empiece por una palabra inofensiva; los de una linea sin esos
  caracteres siguen descartandose igual.
  - Request: "comando de varias líneas o con \$( pasa sin mirar"
  - Verify: test mod/read.test.ts (plugin test) y tests/test_read_classifier.py
- **REQ-004** — `test_windows.load` y `backend_params.effective` no cachean el resultado de un
  `OSError` distinto de `FileNotFoundError` al leer el fichero: la siguiente llamada, con el fichero
  ya legible y sin cambios, devuelve el contenido real. Un JSON roto (fallo permanente) se sigue
  cacheando.
  - Request: "caché de fallo de lectura pasajero (test_windows y backend_params)"
  - Verify: test tests/test_transient_read_cache.py

## Acceptance scenarios

### Scenario: sesion sin el MCP

- **Given** un transcript con un `deferred_tools_delta` sin tools de local-delegate
- **When** se lee con `Read` un `.md` de 20 KB con el bloqueo encendido
- **Then** no hay `deny` ni aviso y el log de hooks tiene `reason: mcp_absent`

### Scenario: sesion con el MCP

- **Given** un transcript con `mcp__local-delegate__local_describe_image` en `addedNames`
- **When** la misma lectura
- **Then** se bloquea como hoy

### Scenario: prefiltro

- **Given** `cd docs` + salto + `cat ../big.md`, `echo $(cat big.md)` o echo con comillas invertidas
- **When** el mod los ve
- **Then** llama a `hook classify`

### Scenario: cerrojo pasajero

- **Given** `test-windows.json` valido cuya lectura falla una vez con `PermissionError`
- **When** la siguiente lectura ya puede leerlo
- **Then** devuelve sus ventanas

## Edge cases and failure behavior

- Un delta posterior con `removedNames` quita la tool del conjunto; uno con `addedNames` la anade.
- Cualquier excepcion al mirar el transcript: como hoy (no calla).

## Non-functional requirements

- Rendimiento: el hook lee el transcript en binario y solo parsea las lineas con
  `deferred_tools_delta`; tope de 32 MiB.
- Seguridad: `agent_id` validado con `^[A-Za-z0-9_-]{1,128}$` antes de construir la ruta.
- Stdlib unicamente en los hooks.

## Non-goals

- Cambiar el mod para el MCP ausente, el hook de prompt, `SubagentStart` o el panel.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
