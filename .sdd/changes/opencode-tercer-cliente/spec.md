# Specification: opencode como tercer cliente de `install`

## Summary

`local-delegate install` pasa a conocer **tres** clientes. opencode se detecta solo, recibe la
entrada MCP (stdio o HTTP), la regla de delegación en su memoria global y la skill en el
directorio donde su cargador la busca; `doctor` lo comprueba con una comprobación propia y
`update` repone lo que falte. Las garantías son las mismas que ya tienen Claude Code y Codex:
idempotente, reversible, sin escribir secretos y sin pisar lo que escribió una persona.

## Requirements

### Selección de cliente

- **REQ-001:** `--clients opencode` y `--target opencode` existen y configuran opencode; `--target
  all` incluye los tres.
- **REQ-002:** La detección automática (`--clients auto`) cuenta opencode como presente si existe
  su **directorio de configuración**, resuelto según REQ-003.
- **REQ-003:** El directorio de configuración de opencode se deriva en **una sola función**:
  `$XDG_CONFIG_HOME/opencode` cuando la variable está puesta y `home` es el HOME real, y
  `home/.config/opencode` en cualquier otro caso. `install`, `checks` y `update` la usan; nadie
  reconstruye la ruta por su cuenta.
- **REQ-004:** Con `--home` simulado la ruta sale de ese `home` (nunca de `$XDG_CONFIG_HOME`), de
  modo que el árbol simulado sigue siendo un sandbox.

### Entrada MCP

- **REQ-005:** El fichero de destino se elige como lo elige el propio cliente: `opencode.json` si
  existe; si no, `opencode.jsonc` si existe; si no hay ninguno, se crea `opencode.jsonc`.
- **REQ-006:** El `probe` que comprueba la entrada mira **los dos** ficheros, porque opencode los
  fusiona.
- **REQ-007:** En modo `stdio` la entrada es
  `{"type": "local", "command": [...], "enabled": true}`, con `command` **array** y el mismo
  paquete/pin que hoy recibe Claude Code.
- **REQ-008:** En modo `http` la entrada es `{"type": "remote", "url": ..., "enabled": true}`,
  contra la misma URL del daemon que ya se calcula para los otros clientes.
- **REQ-009:** Con `--api-key-env`, la clave se referencia como
  `"LOCAL_DELEGATE_API_KEY": "{env:LOCAL_DELEGATE_API_KEY}"` dentro de `environment`. **Nunca se
  escribe el valor.**
- **REQ-010:** Con `--web-token-env` en modo `http`, la cabecera es
  `"Authorization": "Bearer {env:LOCAL_DELEGATE_WEB_TOKEN}"`. **Nunca se escribe el valor.**
- **REQ-011:** No se escribe **ninguna** clave de primer nivel fuera de `mcp` (una clave
  desconocida impide arrancar opencode), ni marcadores de comentario propios.
- **REQ-012:** Reinstalar deja **exactamente una** entrada `mcp["local-delegate"]`, con el
  contenido de esta instalación y sin restos de la anterior.

### Cómo se escribe (y cuándo no se escribe)

- **REQ-013:** Si el binario `opencode` está en el PATH y `--no-client-cli` no se pasó, la entrada
  se registra invocando `opencode mcp add`. Es el camino por defecto porque conserva los
  comentarios y las demás claves del usuario, y porque valida la forma el propio cliente.
- **REQ-014:** Si la CLI no está, o falla, se cae a escribir el fichero nosotros — **solo si eso
  no destruye nada**: el fichero no existe, o existe y **no contiene comentarios**.
- **REQ-015:** Si no hay CLI y el fichero **sí** tiene comentarios, la entrada MCP de opencode
  **no se escribe**. Se avisa con la ruta, se dice qué hacer (instalar la CLI de opencode, o
  añadir la entrada a mano) y **el resto de componentes sí se instala**.
- **REQ-016:** Antes de sobreescribir el fichero se deja una copia `.bak`, como con los demás.
- **REQ-017:** Un fichero de configuración que no se pueda parsear **no se toca**: se avisa y se
  sigue. Nunca se sustituye por uno nuevo.

### Memoria y skill

- **REQ-018:** Con el componente `memory` y opencode entre los objetivos, el bloque gestionado
  (`local-delegate:begin/end`) se inserta o reemplaza en `~/.config/opencode/AGENTS.md`, con el
  mismo texto que reciben `~/.claude/CLAUDE.md` y `~/.codex/AGENTS.md`.
- **REQ-019:** Con el componente `skill` y opencode entre los objetivos, la skill se copia a
  `<config de opencode>/skill/delegacion-local/`.
- **REQ-020:** Instalar solo para opencode **no crea** `~/.claude` ni `~/.codex`.

### Desinstalación

- **REQ-021:** `uninstall` retira la entrada `mcp["local-delegate"]` de los ficheros de opencode
  donde esté, conservando el resto del fichero, y borra el directorio de la skill y el bloque de
  memoria. No existe `opencode mcp remove`, así que lo hace el paquete.
- **REQ-022:** Si al retirar la entrada la clave `mcp` queda vacía, se deja como objeto vacío o se
  quita, pero el fichero resultante sigue siendo válido para opencode.
- **REQ-023:** `uninstall` no borra entradas MCP ajenas ni claves ajenas.

### Diagnóstico y reparación

- **REQ-024:** `client.presence` nombra opencode cuando su directorio existe, y sigue siendo
  `unknown` solo si no hay **ninguno** de los tres.
- **REQ-025:** Existe una comprobación nueva `scaffold.mcp_opencode`, grupo `andamiaje`, con el
  mismo criterio de estados que las dos hermanas: `unknown` si opencode no está instalado o no se
  pudo leer, `missing` si falta la entrada, `ok` con el modo (`local`/`remote`) y la ruta.
- **REQ-026:** `scaffold.memory` cuenta opencode como un cliente más, con la misma regla de «un
  cliente que no está en la máquina no arrastra el estado».
- **REQ-027:** `service.credential` incluye a opencode entre las entradas que mira, tratando
  `local` como el `stdio` de los otros (es decir, ciego a la credencial) y `remote` como `http`.
- **REQ-028:** El `probe` **no escribe nada**, ni crea directorios ni ficheros.
- **REQ-029:** Las **cinco** frases de tamaño de `checks.py` y el mapa `_NUMERO` de
  `tests/test_checks.py` dicen diecisiete.
- **REQ-030:** `update.REPAIRS` repone la entrada MCP de opencode y su bloque de memoria cuando
  estén en `missing`, y **no** repara nada en `warn` que signifique configuración del usuario.
- **REQ-031:** La salida de todo lo anterior no contiene caracteres fuera de cp1252.

### Documentación

- **REQ-032:** `docs/wiki/Integration-install.md` refleja el tercer cliente en la tabla de
  componentes, en «a quién configura», en la tabla de flags y en la lista de comprobaciones del
  doctor (que pasa a diecisiete).
- **REQ-033:** `README.md` y `docs/wiki/Daemon.md` nombran opencode donde hoy nombran a los otros
  dos, con la forma medida de la entrada.
- **REQ-034:** La documentación dice que opencode **no** declara `elicitation`, para no prometer
  que las tools preguntarán en ese cliente.

## Acceptance scenarios

### Scenario: máquina solo con opencode

- **Given** un HOME con `~/.config/opencode/` y **sin** `~/.claude` ni `~/.codex`
- **When** se ejecuta `local-delegate install`
- **Then** se configura opencode (entrada MCP, memoria y skill), **no** se crean `~/.claude` ni
  `~/.codex`, y el reporte final del andamiaje muestra `scaffold.mcp_opencode` en `[ OK ]`

### Scenario: máquina con los tres

- **Given** un HOME con `~/.claude`, `~/.codex` y `~/.config/opencode`
- **When** se ejecuta `local-delegate install`
- **Then** los tres reciben su entrada MCP y su bloque de memoria, y solo Claude Code recibe hooks

### Scenario: reinstalar es idempotente

- **Given** un `opencode.json` que ya tiene la entrada gestionada, un `"theme"` del usuario y un
  comentario
- **When** se reinstala
- **Then** queda **una sola** entrada `local-delegate`, y el `theme` y el comentario siguen ahí

### Scenario: sin CLI y con comentarios — no se pisa

- **Given** un `opencode.jsonc` con comentarios y **sin** el binario `opencode` en el PATH
- **When** se ejecuta `local-delegate install`
- **Then** la entrada MCP de opencode **no se escribe**, se dice por qué y qué hacer, la memoria y
  la skill **sí** se instalan, y el exit code no sube por ello

### Scenario: HTTP con token

- **Given** `--mcp-mode http --web-token-env` y `LOCAL_DELEGATE_WEB_TOKEN` en el entorno
- **When** se ejecuta `install`
- **Then** el fichero contiene `"Authorization": "Bearer {env:LOCAL_DELEGATE_WEB_TOKEN}"` y **no**
  contiene el valor del token

### Scenario: desinstalar deja el fichero utilizable

- **Given** un `opencode.json` con nuestra entrada y otra entrada MCP ajena
- **When** se ejecuta `local-delegate uninstall`
- **Then** desaparece solo la nuestra, la ajena sigue ahí, y el fichero resultante lo acepta
  opencode

### Scenario: config roto

- **Given** un `opencode.json` que no parsea
- **When** se ejecuta `install`
- **Then** el fichero no se toca, la comprobación queda en `unknown` con el motivo, y el resto de
  componentes se instala

### Scenario: `--home` simulado con `XDG_CONFIG_HOME` puesta

- **Given** `XDG_CONFIG_HOME` apuntando al config real del usuario y `--home <árbol simulado>`
- **When** se ejecuta `install --home <árbol>`
- **Then** se escribe **dentro del árbol simulado** y el config real no se toca

## Non-goals

- Hooks/plugins para opencode (ver `brief.md` y `research.md` R10).
- Configuración de proyecto (`./opencode.json`, `.opencode/`).
- Prometer `elicitation` en opencode: medido que no la declara.
- Cambiar `clients.py`: opencode aparecerá en `client.observed` por el observador que ya existe.
