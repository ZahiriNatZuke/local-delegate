# Brief: Codex: resumen automático de lecturas y guard de escritura (#670)

Nivel: standard. Disparador: un hook nuevo de Codex que puede **denegar** llamadas de herramienta
(lecturas por shell y `apply_patch`) en la máquina del usuario y escribe estado por sesión; un fallo
dejaría al agente sin contenido o sin poder editar.

## Problem

El mod de Claude Code (`mod/read.js`) sustituye una lectura grande de prosa por un resumen local,
cuenta la cobertura por rangos (80 %) y protege el fichero de escrituras hasta una lectura literal.
La entrega de Codex (#669, `codex_hooks.py`) solo tiene dos hooks consultivos: ninguno actúa sobre
lecturas de shell, MCP ni `apply_patch`.

## Desired outcome

Con la vía técnica demostrada en el código de Codex 0.169.0: un hook `PreToolUse` que, para una
lectura grande de prosa por shell, deniega la llamada con el resumen como motivo (el original no se
ejecuta ni entra al contexto), lleva la cobertura por rangos, y deniega `apply_patch` (o una
escritura por shell) sobre un fichero resumido hasta una lectura literal. Lo que no se pueda
demostrar sin Codex real queda como prueba en vivo para la persona usuaria.

## In scope

- Hook `codex-tool-guard` (`PreToolUse`, Bash, `apply_patch` y lecturas MCP ajenas) en `codex_hooks.SPECS`.
- Clasificador compartido (`read_classifier`), resumen por el `/mcp` del daemon, fallo en abierto.
- Estado por sesión y por agente (principal/subagente) en el directorio de datos.
- Textos es/en, CHANGELOG, wiki con la conclusión y sus límites, tests con fixtures oficiales.

## Out of scope

- Atribución por sesión de las llamadas MCP (#669, otro agente) y comandos sin modelo / barra de estado (#671).
- Diálogo «resumir o leer entero» (Codex no da diálogo a un hook) y caché de resúmenes.
- Telemetría de hooks P-4 para Codex (decisión de #669: la serie es de Claude Code).

## Constraints and risks

- Un hook de Codex con código 2 bloquea: el nuestro siempre sale con 0 (`local_delegate.hook`).
- Codex solo ejecuta hooks aprobados en `/hooks`: el hook nuevo pide aprobación.
- Sin tocar `~/.codex`, el daemon ni `~/.claude*`; sin leer secretos en los tests.

## Open questions

- Ninguna que cambie la especificación: lo que solo se ve con Codex real va a «prueba en vivo».

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-16 Original request, verbatim:

  > Tarea: resolver el issue #670 (`gh issue view 670 -R ZahiriNatZuke/local-delegate`): en Codex, resumen automático de lecturas y guard de escritura con equivalencia comprobable (lecturas por shell, `apply_patch`). [...] Implementa lo que se pueda verificar con fixtures; lo que no se pueda comprobar sin Codex real, déjalo descrito como prueba en vivo para el usuario y no lo des por hecho. Si una parte resulta inviable (Codex no expone el evento, no deja reescribir la salida, etc.), documenta la conclusión con su evidencia en `docs/wiki/` [...]
