# Specification: `doctor` ve cuando la entrada MCP no puede autenticarse contra el daemon

## Summary

Un check nuevo pregunta si el puerto del daemon exige token y, si lo exige, comprueba que las
entradas MCP en modo HTTP de los tres clientes lleven con qué autenticarse. La combinación que
hoy da «todo a punto» con las tools en 401 pasa a avisar.

## Requirements

- **REQ-001:** Existe un check en el grupo `servicio` que decide con `ctx.daemon_needs_token`. El
  grupo `andamiaje` no cambia: sigue sin salir a la red.
- **REQ-002:** Si el daemon **no** exige token, o no se pudo averiguar, el check es `ok` o
  `unknown` respectivamente. Nunca `missing`: esto es informativo sobre una configuración, no
  sobre algo que falte instalar.
- **REQ-003:** Si el daemon exige token, una entrada en modo HTTP **sin** con qué autenticarse es
  `warn`, y el aviso nombra al cliente y el síntoma comprobable (401 en las tools).
- **REQ-004:** El check reconoce las tres formas en que `install` escribe la autenticación:
  `headers.Authorization` en Claude Code y opencode, y `bearer_token_env_var` en Codex. Un cliente
  bien configurado en cualquiera de las tres no produce aviso.
- **REQ-005:** Las entradas en modo `stdio` no entran en este check: no hablan con el puerto del
  daemon, y de su problema ya avisa `service.credential`.
- **REQ-006:** Si la entrada referencia una variable de entorno que **este proceso no ve**, el
  check avisa por separado, redactado como sospecha y no como veredicto — el entorno de `doctor`
  es un testigo del que verá el cliente, no una prueba.
- **REQ-007:** El check nunca tumba el diagnóstico: cualquier fallo suyo es `unknown`.

## Acceptance scenarios

### Scenario: la avería de hoy queda vista

- **Given** un daemon que exige token y la entrada de Claude Code en `{"type": "http", "url": ...}`
  sin cabecera
- **When** corre `doctor`
- **Then** el check es `warn` y nombra a Claude Code y el 401

### Scenario: la instalación correcta no molesta

- **Given** el mismo daemon y la entrada con `headers.Authorization` referenciando la variable,
  que está presente en el entorno
- **When** corre `doctor`
- **Then** el check es `ok`

### Scenario: Codex se autentica de otra forma y también vale

- **Given** un daemon que exige token y el bloque de Codex con `bearer_token_env_var`
- **When** corre `doctor`
- **Then** ese cliente no aparece en ningún aviso

### Scenario: un daemon abierto no genera ruido

- **Given** un daemon que no exige token y entradas HTTP sin cabecera
- **When** corre `doctor`
- **Then** el check es `ok`

### Scenario: no se puede preguntar al puerto

- **Given** `daemon_needs_token` devuelve `None`
- **When** corre `doctor`
- **Then** el check es `unknown`, nunca `warn` ni `missing`

### Scenario: la cabecera está pero la variable no

- **Given** un daemon que exige token, la entrada con `Bearer ${LOCAL_DELEGATE_WEB_TOKEN}` y esa
  variable vacía en el entorno de `doctor`
- **When** corre `doctor`
- **Then** el check es `warn` y el texto dice que la variable no está **en este entorno**, sin
  afirmar que el cliente esté roto

### Scenario: stdio no entra por esta puerta

- **Given** un daemon que exige token y una entrada en `stdio`
- **When** corre `doctor`
- **Then** este check no la cuenta como ciega

## Out of scope

- Que `install` avise de que va a borrar una cabecera existente, o que conserve la que había.
  Es un arreglo distinto, en otro fichero, y con su propia decisión de diseño.
- Claude Desktop, que sigue fuera del registro de clientes (punto de backlog aparte).
- Cambiar `_probe_mcp_claude`: seguirá diciendo si la entrada existe, que es su pregunta.

## Verification

- Suite del proyecto, con tests por escenario contra el probe (función pura salvo el colaborador
  inyectado, que se dobla).
- Un control que falle si los tests pasan en vacío: el escenario de la instalación correcta debe
  dar `ok`, de modo que un check que avisara siempre no pase la suite.
- **Verificación contra la máquina real**: `doctor` con la entrada correcta debe dar `ok`, y con
  la cabecera quitada a mano debe dar `warn` — reproduciendo la avería de hoy y volviendo atrás.
