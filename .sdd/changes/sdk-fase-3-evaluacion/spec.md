# Specification: evaluación de la fase 3 del SDK `mcp` 2.x

## Summary

Este change **no entrega código**: entrega una **decisión escrita y verificable** sobre qué
capacidades del SDK `mcp` 2.x se adoptan y cuáles no, con el motivo de cada descarte anotado donde
alguien vaya a volver a mirar. Es el mismo precedente que OpenTelemetry (PR #48): lo caro no es
evaluar una vez, es re-evaluar cada seis meses porque nadie escribió por qué se dijo que no.

## Requirements

- **REQ-001:** Cada una de las cinco capacidades de la fase 3 —`extension`/`intercept_tool_call`,
  `elicitation`, `auth`, `caching`, `subscriptions`— tiene un veredicto explícito.
- **REQ-002:** Cada veredicto se apoya en una **comprobación por ejecución** contra el SDK
  instalado o contra el código del repo, no en documentación ni en suposición.
- **REQ-003:** Los descartes quedan escritos en `docs/wiki/Architecture.md`, no solo en la traza
  SDD, para que estén donde se consulta la arquitectura.
- **REQ-004:** Una capacidad cuyo veredicto dependa de un dato que no se tiene **no se descarta ni
  se adopta**: se declara bloqueada y se nombra la medición que la desbloquea.
- **REQ-005:** Un módulo que contenga piezas de tamaño o propósito distinto se evalúa **pieza a
  pieza**, no en bloque.

## Acceptance scenarios

### Scenario: alguien vuelve a proponer el interceptor dentro de seis meses

- **Given** `docs/wiki/Architecture.md` en `main`
- **When** lo lee buscando si `intercept_tool_call` aporta
- **Then** encuentra el veredicto, el motivo y **el dato que lo sostiene** (tres puntos de
  telemetría, no once) sin tener que volver a medir

### Scenario: una capacidad depende de algo no medido

- **Given** `elicitation`, cuyo valor depende de que el cliente la soporte
- **When** se cierra la evaluación
- **Then** no aparece como «descartada» ni como «adoptada», sino como bloqueada por una medición
  concreta y nombrada

### Scenario: un módulo con dos piezas distintas

- **Given** `mcp.server.auth`, que contiene un servidor OAuth2 y un `bearer_auth` ligero
- **When** se emite el veredicto
- **Then** hay **dos** veredictos distintos, no uno

## Edge cases and failure behavior

- **Un no-resultado no cuenta como evidencia** si no se comprueba que la búsqueda podía encontrar
  algo. Aplicado literalmente: la primera comprobación de este change fue un `grep` de `middleware`
  con cero resultados del que se concluyó que el SDK no lo tenía — y era falso, porque ripgrep
  respeta `.gitignore` y `.venv/` está ignorado.
- **Un comentario del repo no es evidencia**: se verifica por ejecución.
- Una capacidad publicada hace días, con el SDK negociando por defecto una revisión anterior, se
  evalúa contando también **si algún cliente la negocia**.

## Non-functional requirements

- Sin cambios de código en este change: solo documentación y traza.
- Los descartes deben poder releerse sin el contexto de la sesión que los produjo.

## Non-goals

- Implementar ninguna de las capacidades evaluadas.
- Decidir sobre capacidades fuera de la fase 3.

## Traceability

| Requisito | Trabajo | Evidencia |
| --- | --- | --- |
| REQ-001 | veredicto de las cinco | `research.md`, tabla resumen |
| REQ-002 | comprobaciones ejecutadas | conteos y greps citados en `research.md` |
| REQ-003 | sección nueva en `Architecture.md` | `docs/wiki/Architecture.md`, «Qué se usa del SDK `mcp` 2.x, y qué no» |
| REQ-004 | `elicitation` declarada bloqueada | `research.md` §2; desbloqueada después por el change `observador-capabilities-cliente` |
| REQ-005 | `auth` partido en dos | `research.md` §3 y `Architecture.md` |
