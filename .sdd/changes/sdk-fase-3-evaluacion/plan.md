# Implementation plan: evaluación de la fase 3 del SDK `mcp` 2.x

## Approach

Un change de decisión, no de código. El entregable es el veredicto de cada capacidad **con su
evidencia** y su escritura en `docs/wiki/Architecture.md`, siguiendo el precedente de OpenTelemetry
(PR #48): el porqué vive donde alguien va a volver a mirar, no solo en la traza SDD.

El método es el que distingue este change de una opinión: **cada veredicto se apoya en algo que se
ejecutó**. Un conteo de invocaciones, un grep con control positivo, la lista de campos de un modelo
del SDK. Y cuando el dato no existe, el veredicto correcto no es «no» — es «bloqueado por esta
medición», nombrándola.

## Ordered tasks

1. **Inventariar lo que el SDK trae de verdad**
   - Files: ninguno (lectura del paquete instalado)
   - Requirements: REQ-001, REQ-002
   - Verification: tabla de módulos en `research.md`, con SEP y revisión de cada uno
   - Nota: **buscar desde Python, no con ripgrep** — `.venv/` está en `.gitignore` y el grep ni
     entra. Este paso ya se hizo mal una vez.

2. **Emitir veredicto por capacidad, con su comprobación**
   - Files: `research.md`
   - Requirements: REQ-001, REQ-002, REQ-005
   - Verification: cada veredicto cita el conteo o el grep que lo sostiene

3. **Separar lo que no es una sola cosa**
   - Files: `research.md` §3
   - Requirements: REQ-005
   - `mcp.server.auth` mezcla un servidor OAuth2 con un `bearer_auth` ligero: dos veredictos.

4. **Declarar lo bloqueado como bloqueado**
   - Files: `research.md` §2
   - Requirements: REQ-004
   - `elicitation` depende de que el cliente la soporte, y eso no está medido. Se nombra el
     experimento que lo desbloquea en vez de decidir a ciegas.

5. **Llevar los descartes a la arquitectura**
   - Files: `docs/wiki/Architecture.md`
   - Requirements: REQ-003
   - Verification: la sección se lee y se entiende sin el contexto de la sesión.

## Test strategy

- **Unit / Integration**: no aplica; no hay código.
- **End-to-end o manual**: la verificación es documental y **por relectura**: cada afirmación de
  `Architecture.md` debe poder rastrearse a una comprobación de `research.md`.
- **Security**: ninguna credencial ni dato personal entra en los artefactos.

## Migration and compatibility

- Solo documentación. No toca código, dependencias ni configuración.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards — no hay: es documentación.
- [x] Dependencies and configuration changes are explicit — ninguna.
- [x] The plan does not include unrelated work — la implementación del observador de capabilities
      salió a **su propio change** (`observador-capabilities-cliente`) en vez de colarse aquí.
