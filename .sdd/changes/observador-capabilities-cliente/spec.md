# Specification: observar qué declara cada cliente MCP

## Summary

Hoy el daemon **no sabe con qué cliente habla**: cero ocurrencias de `capabilities` en `src/`
(research, con control positivo). Este cambio hace que el daemon **registre, por cliente, qué
capabilities declara y qué revisión de protocolo negoció de verdad**, y lo deje en dos sitios: una
línea JSONL persistente y el estado en vivo de `/api/status`.

El dato vale por sí solo —es diagnóstico que hoy no existe— y además **decide dos cosas
pendientes**: si `elicitation` tiene recorrido en este repo, y qué debería comprobar un futuro check
de `doctor` (que es el change siguiente, no este).

## Requirements

- **REQ-001:** El daemon observa, en toda conexión MCP, las `capabilities` declaradas por el
  cliente, su nombre y versión cuando los declara, y la **revisión de protocolo negociada**.
- **REQ-002:** El dato se lee **después del handshake**, no durante `initialize` — donde está
  medido que aún no existe.
- **REQ-003:** Cada identidad de cliente distinta se registra **una sola vez por ejecución del
  daemon** como línea JSONL en `LOG_DIR`, en un fichero propio, separado del log de uso.
- **REQ-004:** `/api/status` expone los clientes observados en esta ejecución, con su protocolo,
  sus capabilities y cuándo se vieron por primera y última vez.
- **REQ-005:** La observación **nunca altera el resultado de una petición**: ni la falla, ni la
  retrasa de forma perceptible, ni modifica su contenido.
- **REQ-006:** El registro funciona igual con `client_info` ausente, que es un caso legítimo del
  protocolo 2026-07-28+ (capabilities sin identidad).
- **REQ-007:** Un mensaje que no trae **ni** capabilities **ni** `client_info` **no** produce
  registro. *(Añadido por la revisión adversarial del plan, `plan-review.md` O-4: es el caso
  simétrico de REQ-006 y sin él se registraría una identidad vacía que además contaminaría el
  experimento de `elicitation`.)*

## Acceptance scenarios

### Scenario: un cliente que se identifica

- **Given** el daemon recién arrancado, sin `clients.jsonl`
- **When** un cliente MCP se conecta, completa el handshake y llama a una tool
- **Then** `clients.jsonl` contiene **una** línea con `ts`, nombre, versión, protocolo negociado y
  la lista de capabilities declaradas
- **And** `GET /api/status` incluye ese cliente en `clients`

### Scenario: el mismo cliente sigue trabajando

- **Given** un cliente ya registrado en esta ejecución
- **When** hace veinte llamadas más (`tools/list`, `tools/call`, ...)
- **Then** `clients.jsonl` **sigue teniendo una sola línea** para él
- **And** `/api/status` refleja el `last_seen` actualizado y el contador de mensajes

### Scenario: dos clientes distintos

- **Given** el daemon sirviendo
- **When** se conectan dos clientes con nombre o versión distintos
- **Then** hay **dos** líneas en `clients.jsonl` y **dos** entradas en `/api/status`

### Scenario: cliente sin `client_info`

- **Given** un cliente que declara capabilities pero no se identifica (protocolo 2026-07-28+)
- **When** envía cualquier petición
- **Then** se registra igual, con el nombre marcado como desconocido y las capabilities presentes
- **And** no se lanza ninguna excepción

### Scenario: mensaje sin capabilities ni identidad

- **Given** el daemon sirviendo
- **When** llega un mensaje en el que ni las capabilities ni el `client_info` están disponibles
- **Then** no se escribe línea alguna y `/api/status` no gana una entrada vacía

### Scenario: el registro falla

- **Given** `LOG_DIR` no escribible (disco lleno, permisos)
- **When** un cliente se conecta y llama a una tool
- **Then** la tool responde con normalidad y el fallo de registro no llega al cliente

## Edge cases and failure behavior

- **`initialize`**: se observa pero no aporta dato (medido). No se registra desde ahí, y **no se
  hace ninguna llamada al cliente** mientras se maneja: el SDK avisa de que eso bloquea la conexión.
- **Excepción en el observador**: se traga y se sigue, igual que `_log_event`
  («nunca rompe una tool», `server.py:384`).
- **Capabilities vacías (`{}`)**: es un dato válido y distinto de «no declaró nada»; se registra
  como lista vacía, no como ausencia.
- **Concurrencia**: varios mensajes simultáneos de la misma conexión no pueden producir dos líneas
  para la misma identidad.

## Non-functional requirements

- **Privacidad**: se registra nombre y versión de un programa, el protocolo y los *nombres* de las
  capabilities. **No** se registran headers, tokens, rutas ni contenido de peticiones.
- **Coste**: la observación es una lectura de atributos ya en memoria; la escritura solo ocurre la
  primera vez que se ve una identidad.
- **Compatibilidad**: no cambia el contrato de ninguna tool ni el formato de `usage.jsonl`. La clave
  `clients` de `/api/status` es aditiva.
- **Sin dependencias nuevas**: stdlib más el SDK ya instalado.

## Non-goals

- **El check de `doctor`.** Va en el change siguiente, a propósito: qué cuenta como fallo (¿un
  cliente sin `elicitation` es un aviso?) solo se puede decidir con los datos que este produce.
- **Implementar `elicitation`.** Este change *decide* si tiene sentido; no la implementa.
- **Autenticación ni `bearer_auth`.** Condicionado a exponer el daemon, con su propia traza.
- **Dashboard visual.** El dato entra por `/api/status`; pintarlo en el panel es otra cosa.
- **Histórico entre reinicios en `/api/status`.** El estado en vivo es de la ejecución actual; el
  histórico es el JSONL.

## Traceability

| Requisito | Trabajo previsto | Evidencia de verificación |
| --- | --- | --- |
| REQ-001 | módulo observador enganchado como `ServerMiddleware` | test + medición en vivo con Claude Code y Codex |
| REQ-002 | el registro se dispara fuera de `initialize` | test que comprueba que `initialize` no registra |
| REQ-003 | dedupe por identidad + escritura JSONL | test de veinte mensajes → una línea |
| REQ-004 | clave `clients` en `/api/status` | test del endpoint + captura real |
| REQ-005 | `try/except` envolvente, sin E/S en el camino caliente | test con `LOG_DIR` no escribible |
| REQ-006 | lectura separada de `client_capabilities` y `client_params` | test con `client_info=None` |
| REQ-007 | guarda que descarta la identidad vacía | test: mensaje sin caps ni info → fichero inexistente |
