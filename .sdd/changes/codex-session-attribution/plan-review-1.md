# Revisión de spec y plan (una pasada, adversarial, de la propia sesión)

Hecha por el agente que implementa, por orden del encargo («revísalas tú con criterio y deja
constancia»). No es un revisor independiente: la revisión de resultado (puerta `conformance`) lo
compensa con tests de control y mutantes.

## Hallazgos

1. **Bloqueante, aplicado.** `caller_column` ponía `codex` después de `mod`: una fila de Codex con un
   `callId` forjado `toolu_plugin_…` contaría como del mod. Ahora `codex` va primero (REQ-008).
2. **Comprobado.** ¿Es `_meta.sessionId` el mismo valor que el `session_id` del hook? Sí por fuente:
   los dos son `sess.session_id()` (`mcp_tool_call.rs:630-635`, `hook_runtime.rs:206-219`). Se usa en
   hash; la igualdad en vivo queda en la prueba del usuario (REQ-012).
3. **Riesgo aceptado.** El `call_id` de una llamada anidada de code mode coincide entre `_meta` y el
   hook por el despacho normal (research del núcleo); `exec-<uuid>` cabe en el patrón. En vivo, REQ-012.
4. **Riesgo aceptado.** La nota vive en un temporal que cualquier proceso local puede escribir. Una
   nota forjada solo cambia campos de observación (modelo validado por patrón, hilo, sesión en hash)
   de filas que ya están fuera del coste; no se abre ningún fichero señalado por la nota.
5. **Cambio deliberado de tests existentes.** Los tests del núcleo que fijan «exactamente dos hooks»
   (`test_codex_hooks.py`, `test_codex_hooks_install.py`, doctor) cambian a leer `SPECS`: con #670 y
   #671 en paralelo, un recuento fijo se rompería en cada integración. Se conserva lo que comprobaban
   (forma de cada manejador, sin matcher en los dos consultivos).
6. **Compatibilidad, aceptado.** Las filas viejas de Codex pasan de «Sin dato» a «Codex» en el panel
   y en `measure_adoption`; es lo correcto (se sabe que son de Codex) y va en el CHANGELOG.
7. **Alcance.** Desglosar «Codex» por hilo en el panel queda fuera (non-goal): el dato está en la
   fila y añadirlo sería otra columna del dashboard sin petición.

## Resultado

Sin bloqueantes abiertos tras aplicar el 1. Trazabilidad REQ-001..REQ-012 → T1..T7 completa.
