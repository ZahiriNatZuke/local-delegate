# Revisión de spec y plan, pasada 1

Revisor independiente: `personal-sdd-plan-reviewer` (solo lectura). Veredicto: approve-with-changes.

| # | Severidad | Hallazgo | Resolución |
| --- | --- | --- | --- |
| 1 | bloqueante | Lectura entera de prosa en subagente sin definir | REQ-002: se resume en principal y subagente, cada uno en su alcance; test por alcance |
| 2 | bloqueante | Sin valor de timeout del hook ni HTTP | REQ-001: 180 s; REQ-008: HTTP 150 s; test con servidor lento → `None` |
| 3 | bloqueante | El agente no sabe cómo leer literal | REQ-002: la cabecera da el presupuesto y el comando; REQ-006: el rechazo nombra la lectura que lo levanta; tests |
| 4 | menor | Comandos compuestos | REQ-002: solo un comando que es solo la lectura; compuesto → pasa con nota; tests de los dos |
| 5 | menor | Guard saltable por ruta / `apply_patch` como shell | REQ-006: rutas resueltas como la lectura; `apply_patch` nunca como shell; control con ruta relativa y otra caja |
| 6 | menor | Matcher no verificable | REQ-001: atado a `_MCP_READ`/`OWN_MCP_SERVERS`, lista enumerada en el test |
| 7 | menor | Sin payload real de Windows | Prueba en vivo: captura del payload con un hook temporal de volcado (handoff) |
| 8 | menor | Controles negativos y latencia | `verification.md` con una fila por REQ y sus controles (79/80 %, cruce principal/subagente, fuera del final, truncado); NFR de latencia con prefiltro |
