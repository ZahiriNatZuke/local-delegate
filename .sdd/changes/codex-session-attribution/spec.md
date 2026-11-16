# Specification: Atribución de cada delegación de Codex a su sesión (#669, segunda parte)

Nivel: standard. Disparador: cambia el estado persistido (campos nuevos en las filas del log de uso
de Codex), el contrato de `/api/stats` (`codex_calls`) y la configuración de un cliente externo
(un tercer hook en `~/.codex/hooks.json`, que Codex pide aprobar).

## Summary

Cada delegación que pide Codex queda en el log con su id de llamada, la clave de un solo sentido de
su sesión y, si el hook `PreToolUse` aprobado dejó nota, el hilo (principal o subagente), el tipo de
agente y el modelo de Codex que la pidió. Esas filas no entran en el relleno a posteriori (que cruza
con transcripts de Claude) ni en el coste, y el panel y el resumen por sesión las cuentan en una
columna propia «Codex», sin mezclarlas con las de Claude.

**Decisión sobre `_meta.sessionId`.** Se lee, solo de `codex-mcp-client`, y se guarda solo como
`hook_common.session_key(sessionId)`. Motivo: en Codex 0.169.0 `_meta.sessionId` y el `session_id`
del hook salen de la misma función `sess.session_id()` (research, «Hechos»); así la fila tiene sesión
aunque el hook no esté aprobado, y `/api/stats?session=<id de Codex>` la encuentra. `threadId` no se
lee (en un subagente es el hilo del subagente, que ya da `agent_id` en la nota y no hace falta).

## Requirements

- **REQ-001** — `codex_hooks.SPECS` termina con una tercera entrada `codex-mcp-call` en
  `PreToolUse` con matcher `^mcp__local[-_]delegate__`; las dos anteriores no cambian ni de orden ni
  de forma. `entries()` da su grupo con ese matcher y un único manejador `command` (timeout 30), el
  fichero pasa `codex_plugin.check_hooks_file` sin hallazgos y `hook_key` sabe la etiqueta
  `pre_tool_use`.
  - Request: "hook `PreToolUse` sobre `^mcp__local[-_]delegate__` con nota de Codex"
  - Verify: test tests/test_codex_attribution.py
- **REQ-002** — `codex_hooks.matcher_matches(matcher, names)` reproduce `HookMatcher` de
  `hooks/src/engine/matcher.rs` (todo, exacto con `|`, regex sin anclar). Con él, nuestro matcher
  casa `mcp__local_delegate__local_summarize` y `mcp__local-delegate__local_extract`, y no casa
  `Bash`, `apply_patch` (ni sus alias `Write`/`Edit`), `mcp__memory__create_entities`,
  `mcp__local_delegatex__t` ni `xmcp__local_delegate__t`. Controles negativos: el mismo patrón sin
  `^` casa `xmcp__local_delegate__t`, y el literal `mcp__local_delegate__` (modo exacto) no casa
  ninguna herramienta nuestra.
  - Request: "controles del matcher"
  - Verify: test tests/test_codex_attribution.py
- **REQ-003** — Fixtures de `PreToolUse` (Bash, `apply_patch`, MCP nuestro en el hilo principal, MCP
  nuestro en un subagente, MCP nuestro desde code mode con `tool_use_id` `exec-<uuid v4>`, y MCP
  ajeno) que cumplen el esquema de entrada oficial de `rust-v0.169.0` (copiado a
  `tests/fixtures/codex_hooks`). Lanzado como lo lanza Codex, `codex-mcp-call` sale con 0 y sin
  salida en todos; solo para las llamadas a nuestro servidor deja en el directorio de notas el
  fichero `codex-<tool_use_id>.json` con exactamente `tool_use_id`, `ts`, `client` (`codex`),
  `model`, `agent_id`, `agent_type` y `session_key` (clave de un solo sentido); nunca `cwd`,
  `transcript_path`, `tool_input` ni el `session_id` en claro. Sin `tool_use_id`, con uno que no
  cumple `^[A-Za-z0-9_-]{1,128}$` (`../x`, 129 caracteres) o con stdin roto, no deja nota y sale
  con 0.
  - Request: "fixtures de `PreToolUse` (Bash, `apply_patch`, MCP, code mode con ids `exec-<uuid>`)"
  - Verify: test tests/test_codex_attribution.py
- **REQ-004** — El middleware lee `_meta.callId` (validado con el patrón de REQ-003) y
  `_meta.sessionId` (en hash) solo cuando el cliente es `codex-mcp-client`. Controles: Claude Code
  con `callId` y `sessionId` en `_meta` sigue dando solo su `claudecode/toolUseId` y ninguna clave
  de Codex; Codex con `claudecode/toolUseId` no da ese id.
  - Request: "leer `_meta.callId` solo de `codex-mcp-client`; decidir qué hacer con `_meta.sessionId`"
  - Verify: test tests/test_codex_attribution.py
- **REQ-005** — La fila del log de una delegación de Codex (con `LOCAL_DELEGATE_LOG` temporal)
  lleva `tool_use_id` = `callId` y `caller_session_key` = clave de `sessionId`; con una nota vigente
  de `codex-mcp-call` además `caller_kind` (`main` o `subagent` según `agent_id`),
  `caller_agent_type` (solo en subagente), `caller_model` (el slug de Codex tal cual, validado) y
  `caller_src` `codex-hook`; nunca `caller_effort` ni proyecto. Una nota caducada, de otro id o una
  nota de Claude con el mismo id no cuentan. La entrada en curso (`/api/inflight`) lleva la misma
  clave de sesión. Las filas de Claude Code no cambian (sus tests siguen en verde).
  - Request: "Hook `PreToolUse` … con nota de Codex (prefijo propio en el nombre del fichero)"
  - Verify: test tests/test_codex_attribution.py
- **REQ-006** — Las filas de Codex quedan fuera del relleno a posteriori: `transcripts.match_lines`
  no les da entrada aunque un `tool_use` de Claude de la misma tool caiga en su ventana (control: la
  misma fila con cliente `claude-code` sí se cruza `window`), y `cost.merge_row` no les funde una
  entrada vieja de `attribution-AAAAMM.json`. El recibo en curso (`cost.in_flight_row`) de una
  llamada de Codex es el mismo que antes del cambio (no toma el modelo de Codex).
  - Request: "apartar las filas de Codex del relleno a posteriori"
  - Verify: test tests/test_codex_attribution.py
- **REQ-007** — Una fila de Codex con atribución completa sigue en el tramo `excluded` del coste con
  motivo `not_claude` (`cost.segment`, `valuation.cost_block` `excluded_by_reason`) y no entra en la
  base valorada.
  - Request: "y del coste (`excluded`)"
  - Verify: test tests/test_codex_attribution.py
- **REQ-008** — `attribution.caller_column` da `codex` para toda fila de `codex-mcp-client`, antes
  que `mod` (una fila de Codex nunca es del mod, aunque su `callId` empiece por `toolu_plugin_`); `/api/stats` trae `codex_calls` en el total y en cada fila de `by_client`, y las cinco
  columnas suman `calls`. La tarjeta «Quién delegó» enseña la columna «Codex» solo cuando alguna
  fila la tiene distinta de cero, con su texto en es y en. Verificado con capturas en claro y oscuro.
  - Request: "darles columna propia en el panel"
  - Verify: test tests/test_codex_attribution.py
- **REQ-009** — `/api/stats?session=<id de sesión de Codex>` da solo las filas de esa sesión, con
  `codex_calls` igual a `calls`; con otro id da cero. `/api/inflight?session=<id>` marca como suya la
  delegación en curso de esa sesión de Codex.
  - Request: "y en el resumen por sesión"
  - Verify: test tests/test_codex_attribution.py
- **REQ-010** — `scripts/measure_adoption.py` cuenta `codex` en `delegations_by_caller` (las
  columnas siguen sumando el total) y su línea «por hilo» lo dice en es y en.
  - Request: "derived: `caller_column` con un valor nuevo dejaría fuera de la suma las filas de Codex en el medidor que ya lo usa"
  - Verify: test tests/test_codex_attribution.py
- **REQ-011** — CHANGELOG («Unreleased»), `docs/wiki/Savings-and-metrics.md` (campos de la fila de
  Codex, columna «Codex», decisión de `sessionId`) y `docs/wiki/Integration-install.md` (tercer hook,
  qué cubre y qué no, aprobación en `/hooks`) al día; `doctor` cuenta tres hooks.
  - Request: "derived: #669 pide documentar la diferencia entre telemetría global y atribución por sesión"
  - Verify: test tests/test_wiki.py
- **REQ-012** — La prueba con Codex real (aprobar `codex-mcp-call`, delegar desde el hilo principal,
  un subagente y code mode, y ver los campos en el log, la columna en el panel y `?session=`) queda
  descrita paso a paso en `handoff.md`; no se simula.
  - Request: "Si algo de eso no se puede verificar sin Codex real, dilo y deja la prueba en vivo descrita en el handoff"
  - Verify: manual handoff.md «Next action»

## Acceptance scenarios

### Scenario: delegación de Codex con el hook aprobado

- **Given** `codex-mcp-call` aprobado y una llamada `mcp__local_delegate__local_summarize` con
  `call_id` `call_abc` en un subagente
- **When** Codex lanza el hook y luego manda `tools/call` con `_meta.callId` `call_abc` y `sessionId`
- **Then** la fila lleva `tool_use_id: call_abc`, `caller_kind: subagent`, `caller_agent_type`,
  `caller_model` de Codex, `caller_src: codex-hook` y `caller_session_key`; el panel la cuenta en
  «Codex» y el coste la deja en `excluded` (`not_claude`).

### Scenario: hook sin aprobar

- **Given** `codex-mcp-call` sin aprobar (no corre)
- **When** Codex manda `tools/call` con `_meta.callId` y `sessionId`
- **Then** la fila lleva `tool_use_id` y `caller_session_key` y nada más de `caller_*`; cuenta en
  «Codex» y en `?session=`.

## Edge cases and failure behavior

- `_meta` ausente, no dict, o valores no string o con forma inválida: se omite el campo.
- Nota ilegible, a medias, de más de diez minutos o con `tool_use_id` distinto: sin nota.
- `model` que no cumple `^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$`: se omite `caller_model`.
- El hook falla en abierto: cualquier excepción sale con 0 y deja una línea en `hook-failures.jsonl`
  con el tipo (red de `local_delegate.hook`).

## Non-functional requirements

- Privacidad: ningún id de sesión en claro, ni `cwd`, `transcript_path` o `tool_input` en la nota o
  en la fila. Los ids de llamada son aleatorios de Codex y ya se guardan los de Claude.
- Compatibilidad: filas viejas sin campos nuevos cuentan como hasta ahora (Codex → «Codex» en vez de
  «Sin dato»); Claude Code sin cambios.
- Operabilidad: observar nunca rompe una tool; el hook no depende del backend.

## Non-goals

- Hooks de lecturas, shell o `apply_patch` (#670); comandos sin modelo, barra de estado, matriz de
  capacidades (#671). Los fixtures de Bash y `apply_patch` aquí solo prueban que nuestro hook no los
  atrapa.
- Valorar el coste de Codex o leer sus transcripts. Medir el esfuerzo (no viene en el payload).
- Desglosar en el panel Codex por hilo (el dato queda en la fila: `caller_kind`).

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
