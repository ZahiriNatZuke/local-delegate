# Specification: Codex: resumen automático de lecturas y guard de escritura (#670)

Nivel: standard (ver `brief.md`). Vía técnica: `research.md`, «Hechos de Codex 0.169.0».

## Summary

Con Codex, un hook `PreToolUse` nuevo (`codex-tool-guard`) da al modelo, en lugar de una lectura
grande de prosa por shell, un resumen local (la lectura no se ejecuta), lleva la cobertura de las
lecturas por rangos con el umbral del 80 % del mod de Claude, avisa de lecturas MCP grandes y
rechaza `apply_patch` o una escritura por shell sobre un fichero leído solo resumido hasta que se
lea literal. Cualquier fallo deja pasar la llamada tal cual.

## Requirements

- **REQ-001** — `codex_hooks.SPECS` añade, sin reordenar las existentes, `codex-tool-guard` en
  `PreToolUse` con el matcher `codex_reads.MATCHER` y `timeout` 180 (`codex_reads.HOOK_TIMEOUT_S`); los
  dos hooks de #669 siguen con su evento, sin matcher y `timeout` 30. El `hooks.json` resultante pasa
  `codex_plugin.check_hooks_file`. El matcher, evaluado como lo hace Codex (regex sin anclar), casa
  con `Bash`, `apply_patch` y las tools MCP cuyo nombre lee según `read_classifier._MCP_READ`
  (`mcp__filesystem__read_text_file`, `mcp__obsidian__read_note`, `mcp__markitdown__convert_to_markdown`),
  y no con ninguna `local_*` de `local-delegate`/`local_delegate`, `mcp__x__list_directory`,
  `Read` ni `shell`: lista enumerada en el test, sin lookaround (el `regex` de Rust no lo admite).
  - Request: "Lectura grande de prosa, código/configuración, lectura por rangos y acumulada, lectura shell y MCP, y escrituras apply_patch se prueban con payloads reales Codex."
  - Verify: test tests/test_codex_reads.py
- **REQ-002** — Lectura entera por shell (`cat`, `Get-Content`, `type`…) de un fichero de prosa por
  encima del umbral (`read_classifier.summarizable`) con el interruptor de lectura en `on`, en el
  hilo principal o en un subagente (sin diálogo en los dos, como `readSteer` sin `readCanAsk`): el
  hook imprime un JSON que cumple el esquema oficial de salida de `PreToolUse` con
  `permissionDecision: "deny"` y un motivo que empieza por la cabecera
  `codex.read.summary.header_budget` y contiene el resumen; la cabecera dice que la lectura no se
  ejecutó, cuántas líneas del fichero se pueden leer literales en la sesión y con qué comando
  (`sed -n 'A,Bp'`, `Get-Content -TotalCount`). El resumen se pide con la ruta absoluta y el fichero
  queda guardado para ese agente. Solo se sustituye un comando que es **solo** la lectura (un único
  segmento, quitando `cd`/`Set-Location` delante, sin `$(`, comillas invertidas, `;`, `&&`, `||` ni
  tubería); un comando compuesto que lee prosa grande pasa literal con la nota
  `codex.read.warn.large`.
  - Request: "Si la plataforma lo permite, portar el clasificador compartido, resumen con path, fallback a lectura real, registro deduplicado y guard por sesión."
  - Verify: test tests/test_codex_reads.py
- **REQ-003** — Fallo en abierto: si el resumen es `None`, vacío, empieza por `[local-delegate error]`,
  es el aviso de llamada movida a segundo plano o lleva un aviso de salida truncada o de presupuesto
  de tiempo (es o en), el hook no imprime nada y no guarda el fichero. Con `LD_HOOK_ENABLED=0`, el
  backend marcado caído, el interruptor de lectura apagado, entrada rota o una excepción: sale 0
  sin salida (salvo el guard, que no depende del backend).
  - Request: "El resumen falla o el backend/modelo no está disponible: la lectura real pasa; nunca dejar al agente sin contenido ni bloquear indefinidamente. Una respuesta vacía, truncada o aviso de llamada aún en curso no cuenta como resumen válido"
  - Verify: test tests/test_codex_reads.py
- **REQ-004** — Pasan literales (sin salida, sin resumen) una lectura de código/configuración
  grande, de prosa pequeña, o un rango de un fichero corto (≤200 líneas y <32 KB); en un
  subagente, la lectura entera de código grande lleva además la nota `codex.read.warn.subagent`
  como `additionalContext`.
  - Request: "Lectura grande de prosa, código/configuración, lectura por rangos y acumulada"
  - Verify: test tests/test_codex_reads.py
- **REQ-005** — Cobertura: un rango (`sed -n a,bp`, `head -n`, `Get-Content -TotalCount`) pasa
  literal y suma su tramo; el rango que llevaría lo leído al 80 % o más de las líneas se resume
  (cabecera `codex.read.summary.header_ranges`); tras una lectura literal entera, los rangos pasan.
  En un subagente los rangos pasan siempre y no suman a la cobertura del principal.
  - Request: "lectura por rangos y acumulada"
  - Verify: test tests/test_codex_reads.py
- **REQ-006** — Guard: tras un resumen, `apply_patch` con `Update/Delete File` o `Move to` sobre ese
  fichero, o una escritura por shell (`sed -i`, redirección, `Set-Content`) sobre él, se deniega con
  `codex.guard.refused`, que nombra la lectura que lo levanta (un tramo con `sed -n`); las rutas
  del parche se resuelven como las de la lectura (relativas al `cwd`, `/d/…` de Git Bash, mayúsculas
  y barras en Windows), y `apply_patch` nunca se analiza como shell. Una lectura literal (un rango) del mismo agente lo levanta y la escritura
  pasa. El estado se separa por agente (principal / cada `agent_id`): el resumen de un subagente no
  guarda el fichero para el principal ni al revés. El estado está en disco y sobrevive a otro
  proceso del hook (reanudar la sesión).
  - Request: "Tras resumen, escritura sobre el fichero se rechaza hasta lectura literal suficiente; conservar seguridad al reanudar y definir alcance entre principal y subagentes sin contaminación cruzada."
  - Verify: test tests/test_codex_reads.py
- **REQ-007** — Una lectura por una tool MCP ajena de un fichero grande pasa con la nota
  `codex.read.warn.large` como `additionalContext`; nunca se deniega.
  - Request: "lectura shell y MCP"
  - Verify: test tests/test_codex_reads.py
- **REQ-008** — El resumen se pide al `/mcp` del daemon por *streamable HTTP* (`initialize`,
  `notifications/initialized`, `tools/call` de `local_summarize` con `path`, `DELETE` de la sesión),
  con `Authorization: Bearer` cuando hay token y respuestas JSON o SSE; un error de red, HTTP o
  `isError` da `None`. El plazo HTTP (150 s, `SUMMARY_TIMEOUT_S`) es menor que el del hook (180 s):
  un daemon que no contesta a tiempo da `None` y la lectura pasa. El cliente se presenta como `local-delegate-codex-read`, que
  `attribution` aparta del coste como `not_claude`.
  - Request: "resumen con path, fallback a lectura real"
  - Verify: test tests/test_codex_reads.py
- **REQ-009** — El estado por sesión guarda solo rutas, rangos y marcas (nunca contenido) en
  `LOG_DIR/codex-read/<session_id>.jsonl`; un `session_id` que no cumple `[A-Za-z0-9_-]{1,128}`
  no escribe estado ni resume (la llamada pasa).
  - Request: "Sin secretos en estado/logs; permisos y confianza Codex intactos."
  - Verify: test tests/test_codex_reads.py
- **REQ-010** — Codex 0.169.0 carga el grupo nuevo sin avisos ni errores (`hooks/list` con un
  `CODEX_HOME` temporal, `scripts/dev/codex_hooks_live.py`) con la clave `…:pre_tool_use:<i>:0`.
  - Request: "permisos y confianza Codex intactos"
  - Verify: cmd python scripts/dev/codex_hooks_live.py
- **REQ-011** — La wiki («Hooks de Codex») y el CHANGELOG dicen qué hace el hook, la vía técnica y
  sus límites (motivo de denegación, sin diálogo, sin caché, lo que solo prueba Codex real), y la
  prueba en vivo con centinela queda escrita para la persona usuaria.
  - Request: "Si no lo permite, documentar el límite [...] Prueba real con un contenido centinela demuestra que el original no entró al contexto"
  - Verify: review docs/wiki/Integration-install.md

## Acceptance scenarios

### Scenario: lectura entera de prosa grande

- **Given** un `.md` de 20 KB y el backend vivo
- **When** Codex pide `cat notes.md`
- **Then** el hook deniega con el resumen como motivo y el fichero queda guardado

### Scenario: editar tras el resumen

- **Given** el fichero guardado
- **When** el modelo manda `apply_patch` sobre él
- **Then** se deniega; tras `sed -n '1,40p' notes.md` el mismo `apply_patch` pasa

### Scenario: el resumen falla

- **Given** el daemon caído o un resumen vacío
- **When** Codex pide `cat notes.md`
- **Then** el hook no imprime nada y Codex ejecuta la lectura

## Edge cases and failure behavior

- Rango más allá del final: pasa. Fichero ilegible para contar líneas: el rango pasa.
- Varias llamadas a la vez (subagentes): el estado es un log de eventos con cerrojo (`append_line`).
- El hook pasa su `timeout`: Codex lo marca `Failed` y la lectura sigue.

## Non-functional requirements

- Sin dependencias nuevas; nombres de código en inglés; textos es/en ASCII en `HOOK_TEXTS`.
- Latencia: el hook corre un proceso de Python en cada `Bash`. Prefiltro antes de importar el
  clasificador: un `Bash` sin extensión de prosa en el comando y sin estado de la sesión sale sin
  más. Se mide y se anota en `verification.md`.
- El token solo va en la cabecera; no se imprime ni se registra.

## Non-goals

- Diálogo con la persona, caché de resúmenes, telemetría P-4 de Codex, `PostToolUse`.
- Sustituir lecturas que no son de un solo fichero (búsquedas, tuberías no clasificables).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
