# Specification: el panel puede decir que no hay adopción

## Summary

El log de uso anota **quién** pidió cada delegación, el panel separa las delegaciones por cliente,
y la tarjeta de hooks muestra **por qué** el hook descartó lo que descartó. Con eso, una racha sin
uso real deja de parecerse a una racha de trabajo.

## Requirements

- **REQ-001:** Cada línea del log de uso lleva `client` con el nombre del cliente MCP que pidió la
  llamada. Si no se pudo saber, el campo **se omite** en vez de escribirse vacío o inventado.
- **REQ-002:** El campo es sólo el **nombre** del cliente (p. ej. `claude-code`). No se registra
  versión, capabilities, cabeceras ni nada que identifique la sesión.
- **REQ-003:** `/api/stats` incluye el desglose de delegaciones por cliente, y el panel lo muestra.
  Las líneas sin `client` (las de antes de este cambio) se agrupan como desconocidas, no se
  descartan ni se reparten.
- **REQ-004:** `/api/hooks` incluye el desglose de los eventos de lectura por `motivo` de descarte
  y por `ext`, y el panel lo muestra.
- **REQ-005:** Los eventos anteriores al PR #146, que no tienen `ext` ni `motivo`, cuentan como
  desconocidos. No se les asigna un motivo por defecto.
- **REQ-006:** El panel **no cruza** sugerencias con delegaciones, ni presenta ninguna tasa de
  conversión. Lo que muestra es la selectividad del hook: de lo que vio, en qué avisó.
- **REQ-007:** Observar no puede romper una tool: si la identidad no está disponible o su lectura
  falla, la delegación se registra igual y sin `client`.

## Acceptance scenarios

### Scenario: la delegación queda firmada por quien la pidió

- **Given** el daemon levantado y un cliente MCP que se identifica como `probe-cliente`
- **When** ese cliente llama a una tool que registra uso
- **Then** la línea nueva del `usage` lleva `"client": "probe-cliente"` y ninguna otra clave nueva

### Scenario: sin identidad, la delegación se registra igual

- **Given** un cliente que no manda `clientInfo`
- **When** llama a una tool
- **Then** la línea se escribe sin la clave `client`, y la tool devuelve su resultado normal

### Scenario: el panel distingue una racha sin uso real

- **Given** un log con delegaciones de `claude-code` y de un script sin identidad
- **When** se pide `/api/stats`
- **Then** el desglose por cliente separa ambas, y las de antes del cambio salen como desconocidas

### Scenario: la tarjeta de hooks explica los descartes

- **Given** telemetría con eventos `codigo`, `acotada`, `pequeno` y avisos
- **When** se pide `/api/hooks`
- **Then** el desglose por motivo devuelve los cuatro grupos con sus conteos, y el de extensiones
  las ordena por frecuencia

### Scenario: la telemetría vieja no inventa motivos

- **Given** eventos sin `ext` ni `motivo`
- **When** se agregan
- **Then** cuentan como desconocidos y no engordan ningún motivo concreto

## Out of scope

- Cualquier tasa de conversión sugerencia → delegación. Son dos registros sin identificador común.
- Marcar una delegación como «prueba» por heurística. La firma es el cliente, y ya está.
- Tocar `clients.jsonl`, que responde otra pregunta (qué clientes se han visto).

## Verification

- Suite del proyecto, con tests de los agregados (funciones puras) y del registro.
- **Verificación end-to-end**: daemon levantado, tool llamada por un cliente MCP real que se
  identifica, y la línea del `usage` inspeccionada en disco. Sin esto sólo se habría probado la
  pieza — el `ContextVar` cruza el threadpool en un script suelto, que no es lo mismo que cruzarlo
  con el SDK por medio.
- Un control que falle si los tests pasan en vacío: una llamada con identidad debe producir
  `client`, de modo que un cambio que nunca la propague no pase la suite.
