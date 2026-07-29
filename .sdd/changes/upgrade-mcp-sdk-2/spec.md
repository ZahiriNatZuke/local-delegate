# Specification: Analisis del upgrade al SDK mcp 2.x: ajuste de lo implementado y mejoras aprovechables

## Summary

El paquete puede correr sobre el SDK `mcp` 2.x sin cambiar su comportamiento observable, con una
migración de **cuatro líneas** en dos archivos. Las mejoras que trae 2.x se adoptan **después** y
por separado, cada una justificada por deuda ya anotada, no por estar disponibles.

## Requirements

### Fase 1 — Migración mínima (sin cambio de comportamiento)

- **REQ-001:** El import y la instanciación pasan a `MCPServer` de `mcp.server.mcpserver`.
- **REQ-002:** El servidor declara su **propia** versión (`version=` del paquete), de modo que un
  handshake `initialize` devuelva la versión de `local-delegate`, no la del SDK. Cierra un defecto
  conocido y hace que `install-smoke` verifique algo real.
- **REQ-003:** El daemon fija la ruta del MCP pasándola a `streamable_http_app(streamable_http_path=…)`,
  porque `Settings` ya no tiene campos de transporte.
- **REQ-004:** El techo pasa de `mcp>=1.2,<2` a `mcp>=2,<3`. El techo **no se elimina**: la lección
  de la 0.12.1 es que un rango sin techo es una bomba de tiempo, no que ese techo concreto sobrara.
- **REQ-005:** Las 11 tools conservan nombre, firma y salida. La suite pasa **sin modificar tests**;
  si algún test hay que tocarlo, es señal de cambio de comportamiento y se documenta.
- **REQ-006:** El handshake y las 11 tools se verifican **ejecutando**, no leyendo firmas: contra el
  backend local real, no solo con un backend falso.

### Fase 2 — Mejoras de bajo riesgo (cambio aparte, tras la fase 1)

- **REQ-007:** Las tools declaran `annotations` (`ToolAnnotations`) que reflejen la verdad: todas
  son de solo lectura salvo por el log de uso; ninguna es destructiva.
- **REQ-008:** `local_extract` usa `structured_output` para devolver un objeto validado en vez de
  JSON dentro de una cadena.
- **REQ-009:** El server declara `title` y `description` para presentarse en los clientes.

### Fase 3 — Las grandes (una por cambio SDD, ninguna aquí)

- **REQ-010:** Cada una de estas se evalúa por separado, **cada una contra la deuda que dice
  resolver**, y solo se adopta si la resuelve de verdad: OpenTelemetry (contabilidad del chunking y
  telemetría de hooks), `middleware` (backpressure y guardrails fuera del camino feliz),
  elicitation (confirmar delegaciones caras cuando la VRAM está justa), `auth` (el MCP HTTP del
  daemon), `cache_hints`, `subscriptions`, `extensions`.

## Acceptance scenarios

### Scenario: el paquete corre sobre 2.x sin que se note

- **Given** el paquete migrado y `mcp` 2.x instalado
- **When** un cliente hace el handshake y llama a cada una de las 11 tools
- **Then** el resultado es equivalente al de 1.29.0, y `serverInfo.version` es la del paquete

### Scenario: el daemon HTTP sigue sirviendo en la misma ruta

- **Given** el daemon migrado
- **When** un cliente se conecta a `http://127.0.0.1:9393/mcp`
- **Then** el handshake responde y el dashboard sigue montado en la raíz

### Scenario: el techo sigue protegiendo

- **Given** el paquete migrado con `mcp>=2,<3`
- **When** se publique algún día `mcp` 3.0.0
- **Then** `install-smoke` lo detecta y una instalación nueva no se rompe

## Edge cases and failure behavior

- **Clientes con protocolo viejo:** si 2.x negocia un nivel de protocolo distinto, un cliente
  antiguo podría quedar fuera. Hay que comprobarlo con los clientes reales (Claude Code, Codex),
  no en abstracto.
- **`mcp-types` como paquete nuevo:** entra como transitiva. Si impusiera un mínimo de Python o de
  `pydantic` superior al del proyecto, es un bloqueante y hay que saberlo antes de migrar.
- **Rollback:** volver a `mcp>=1.2,<2` y revertir las cuatro líneas. Barato mientras la migración
  sea solo eso; deja de serlo en cuanto se adopten mejoras de fase 2 o 3. Por eso van separadas.

## Non-functional requirements

- **Compatibilidad:** la fase 1 no cambia nada observable salvo `serverInfo.version`, que hoy está
  **mal**.
- **Operabilidad:** el daemon de Windows se actualiza como siempre (`uv sync` + reinicio de la
  tarea). Los clientes por `uvx` toman la versión nueva al publicarse.
- **Seguridad:** sin secretos nuevos. `auth` y `request_state_security` quedan para fase 3.

## Non-goals

- **Adoptar mejoras en la misma entrega que la migración.** Mezclarlas haría imposible saber si una
  regresión viene del SDK nuevo o de una capacidad nueva.
- **Quitar el techo de major.** No se repite el error que costó la 0.12.2.
- **Migrar `fetch` u otros MCP del usuario.** Fuera del repo.

## Decisión tomada: una sola librería HTTP, `httpx2`

Decidido por el usuario el 2026-07-28. El entorno queda con **un solo cliente HTTP**: el paquete
migra de `httpx` a `httpx2`, que es lo que usa el SDK 2.x. La alternativa —convivir con las dos—
se descarta: dejaba dos librerías HTTP instaladas para siempre.

Respaldo de la decisión: `httpx2` marca **100 en las cinco dimensiones** de Socket, es de pydantic
y su API es análoga (`Client`, `AsyncClient`, `MockTransport`).

**Consecuencia que hay que asumir:** `respx` no soporta `httpx2` (declara `httpx>=0.25.0`), así que
sale de la suite y se sustituye por `MockTransport`. Son **122 ocurrencias en 5 ficheros**. Esto
mueve la fase 1 de «cuatro líneas» a un cambio serio, y por eso va en su propia rama.

- **REQ-011:** El paquete declara `httpx2` y **no** declara `httpx`. Ninguna dependencia directa
  arrastra `httpx`.
- **REQ-012:** La suite deja de depender de `respx` y mockea con `httpx2.MockTransport`, cubriendo
  los mismos casos. **No se pierde cobertura**: el número de tests no baja de 233.
- **REQ-013:** `pywin32` entra como transitiva obligatoria en Windows (license 70, supplyChain 73).
  Queda **documentado en `SECURITY.md` o en la wiki** como dependencia heredada del SDK que el
  proyecto no eligió, con su motivo.

## Recomendación de calendario

**No migrar todavía; preparar la migración ahora.** Tres motivos, en orden de peso:

1. **El coste está en las dependencias, no en el código.** 2.x mete `httpx2`, `opentelemetry-api`,
   `pyjwt[crypto]`, `jsonschema`, `python-multipart` y `pywin32` (Windows) en un paquete cuyo
   argumento es ser ligero. Antes de decidir hay que **medir el depscore con 2.x**, porque
   `supplyChain` ya está en 96 y esto lo mueve.
2. **2.0.0 se publicó el mismo día que rompió la 0.12.1.** Un major recién salido acumula parches
   las primeras semanas; ser early adopter del mismo SDK que acaba de costarte una release de
   emergencia es imprudente.
3. **No hay ninguna urgencia.** 1.29.0 funciona, el techo protege e `install-smoke` vigila.

Propuesta concreta: dejar la rama lista y verificada, medir el depscore con 2.x, y publicar cuando
el SDK tenga al menos un patch (2.0.1+) o unas semanas de rodaje.

## Traceability

| Requisito | Trabajo planificado | Evidencia de verificación |
| --- | --- | --- |
| REQ-001, REQ-003 | `server.py:32,36`, `daemon.py:116-117` | diff + arranque real |
| REQ-002 | `MCPServer(..., version=…)` | handshake devuelve la versión del paquete |
| REQ-004 | `pyproject.toml` + `uv.lock` | `install-smoke` en verde con 2.x |
| REQ-005 | ningún cambio en `tests/` | `pytest -q` sin tocar tests |
| REQ-006 | prueba manual contra el backend local | salida de cada tool |
| REQ-007..009 | cambio aparte | — |
| REQ-010 | un cambio SDD por mejora | — |
