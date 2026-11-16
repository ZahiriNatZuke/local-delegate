# Plan review 1: codex-native-hooks

Revisor: agente `personal-sdd-plan-reviewer` independiente, sobre spec.md, plan.md y research.md
de la primera versión, con el código de Codex `rust-v0.169.0` y el del repo. Veredicto:
`approve-with-changes` (cuatro bloqueantes).

## Afirmaciones del research comprobadas por el revisor

Formato de `hooks.json` (`config/src/hook_config.rs:12-19`); clave de confianza por posición
(`hooks/src/lib.rs:125-135`, `discovery.rs:632`, `:811`); hash por evento, matcher y manejador
(`discovery.rs:981-998`, `Modified` en `:1011-1013`); matcher (`matcher.rs:12-23`); código 2
bloquea (`events/pre_tool_use.rs:268-290`); `cmd.exe /C` (`command_runner.rs:455-495`); `callId`,
`sessionId` y `threadId` en `_meta` (`core/src/mcp_tool_call.rs:1446-1457`, `:1557-1575`); ids de
code mode `{PUBLIC_TOOL_NAME}-{uuid}` (`core/src/tools/code_mode/delegate.rs:323`).

## Hallazgos y respuesta

1. Bloqueante. Quitar un grupo nuestro desplaza a los ajenos de detrás y les cambia la clave de
   confianza. Respuesta: un grupo nuestro con grupos detrás pasa a `{"hooks": []}` (Codex lo cuenta
   en el índice y no carga nada, `discovery.rs:632-650`); solo se quita si queda al final. REQ-005,
   REQ-007 y REQ-010 lo prueban.
2. Bloqueante. `[hooks.state]` existe tras aprobar y no provoca aviso de Codex. Respuesta: REQ-008
   solo cuenta grupos de eventos en `[hooks]`; tests con solo `state` y con eventos.
3. Bloqueante. Codex no se salta el BOM y rechaza el fichero entero. Respuesta: BOM = fichero que
   Codex rechaza; `install` no escribe y `doctor` da `warn`; REQ-010 lo mide en Codex real.
4. Bloqueante. Atribución de filas de Codex: relleno a posteriori, panel y resumen por sesión sin
   cubrir. Respuesta: alcance partido; la atribución entera (hook de nota, `callId`, relleno,
   panel) pasa al siguiente PR, descrito en «Non-goals» de la spec.
5. `_meta.sessionId` sin decidir. Respuesta: va con la atribución (siguiente PR).
6. «Otra versión» sin definir y reaprobación sin avisar. Respuesta: definido como comando, matcher o
   timeout distintos de `entries()`; los mensajes dicen que hay que aprobar otra vez; test de que
   `update` no reescribe con todo al día.
7. Nombres de las notas de Codex. Respuesta: va con la atribución (prefijo propio).
8. `commandWindows`. Respuesta: un grupo con `commandWindows` no es nuestro; test.
9. Script de REQ-011 fuera del repo. Respuesta: `scripts/dev/codex_hooks_live.py`.
10. Controles que puedan fallar. Respuesta: excepción y `SystemExit(2)` en un manejador `codex-*`;
    mutante de texto. El del matcher sin `^` deja de aplicar: no hay matcher en este PR.
11. Alcance. Respuesta: partido como se propone.

## Segunda pasada

Veredicto: `approve-with-changes`, sin bloqueantes; cierra los hallazgos 1, 2, 3, 6, 8, 9 y 10.
Hallazgos nuevos y respuesta:

1. Desinstalar e instalar acumulaba huecos y perdía la aprobación. Respuesta: lo que falta ocupa el
   primer `{"hooks": []}` sin matcher del evento antes de ir al final (REQ-005); escenario nuevo y
   test de desinstalar e instalar en T3.
2. Code mode y fixtures aplazados sin declarar. Respuesta: REQ-009 dice que este PR no tiene hook
   sobre herramientas; «Non-goals» lista los fixtures de `PreToolUse` y los controles del matcher.
3. El título prometía la atribución. Respuesta: título de spec y plan con «núcleo; la atribución
   por sesión va aparte».
4. `jsonschema` transitiva. Respuesta: declarada en el grupo `dev` con `==4.26.0` (Socket:
   supplyChain 98, el resto 100); el lock solo gana sus dos líneas y `uv lock --check` pasa.
