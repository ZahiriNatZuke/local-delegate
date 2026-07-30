# Specification: install consume checks.CHECKS y anade --clients auto|claude,codex

## Summary

`local-delegate install` deja de decidir a ciegas. Resuelve **a qué clientes** escribe con el
mismo registro de comprobaciones que ya usan `doctor` y `update`, no pisa una entrada MCP que
escribió el usuario sin preguntarle, respeta de verdad `--home`, y termina diciendo el estado
real del andamiaje en vez de un «Listo» que solo cuenta acciones.

Lo que **no** cambia: `install` sigue siendo declarativo. Sobre un andamiaje sano lo reescribe
entero, que es lo que arregla una instalación vieja. `checks` decide *a quién* se escribe y
*qué no se pisa*; nunca decide *si* se escribe.

## Requirements

### Selección de clientes

- **REQ-001:** `install` y `uninstall` aceptan `--clients` con valores `auto`, `claude` y
  `codex`, repetible, con default `auto`.
- **REQ-002:** `--clients auto` resuelve a los clientes **presentes en el HOME de destino**:
  existe el directorio `~/.claude` para Claude Code y `~/.codex` para Codex. El criterio sale de
  **una única función compartida** con el check `client.presence` y con `update`. Queda
  explícitamente prohibido derivarlo parseando el `detail` de un `Result`: ese texto es de
  presentación («detectados: Claude Code, Codex»), no un dato.
- **REQ-003:** La resolución se imprime siempre, antes de cualquier escritura, diciendo qué
  clientes se configuran y por qué (`auto` → detectados, o selección explícita).
- **REQ-004:** `--target` sigue aceptado con su semántica actual (`claude`, `codex`, `all`;
  `all` fuerza los dos aunque no estén presentes). Pasar `--clients` y `--target` en la misma
  invocación es error de uso con exit **2** y no escribe nada.
- **REQ-005:** Con `--clients auto` y ningún cliente presente: se imprime un aviso que dice qué
  se buscó y dónde, y cómo forzarlo (`--clients claude`), **no se escribe nada** y el exit code
  es **0**. El reporte final de REQ-012 **sí se imprime** también en este camino —los `[ -- ]`
  son justamente la explicación de por qué no se hizo nada— pero precedido del aviso, nunca de
  un «Listo».

### HOME simulado

- **REQ-006:** Cuando `--home` apunta fuera del HOME real del usuario, ni `install` ni
  `uninstall` invocan el binario `claude`: la entrada MCP se escribe (o se quita) editando
  `<home>/.claude.json` dentro de ese árbol.
- **REQ-007:** Con `--home` simulado, el `~/.claude.json`, el `~/.claude/` y el `~/.codex/` del
  usuario real quedan **byte a byte idénticos** antes y después de ejecutar `install` y
  `uninstall`.

### Configuración ajena de Codex

- **REQ-008:** Si el check `scaffold.mcp_codex` reporta `warn` («entrada puesta a mano, sin
  marcadores») y la acción de Codex está en el plan, `install` **pregunta por consola** antes de
  reemplazarla, mostrando la ruta afectada. Responder que no salta esa acción y continúa con el
  resto del plan.
- **REQ-009:** Sin terminal interactiva (stdin no es un tty), la pregunta no se hace: se **omite
  la acción**, se avisa de que se conservó la entrada del usuario y se dice qué flag la
  reemplaza sin preguntar.
- **REQ-010:** `--force-mcp-codex` responde la pregunta afirmativamente de antemano: reemplaza
  la entrada sin preguntar, en cualquier entorno. El `.bak` que ya deja `_write_text` se
  conserva y se menciona en la salida.
- **REQ-011:** Con `--dry-run` no se pregunta nada: la acción se describe indicando que en una
  ejecución real pediría confirmación.

### Reporte final

- **REQ-012:** Al terminar, `install` imprime **siempre** el estado de los checks de los grupos
  `entorno` y `andamiaje` del registro, en el mismo formato que `doctor` (`[ OK ]`, `[WARN]`,
  `[FALT]`, `[ -- ]`, con la línea `arréglalo con:` cuando corresponde).
- **REQ-013:** El reporte **no** ejecuta los checks de los grupos `servicio` ni `backend`:
  instalar el andamiaje no debe salir a la red ni lanzar los binarios del backend. Para lograrlo
  se admite un filtro **opcional y aditivo** por grupo en `checks.run_all`; el registro `CHECKS`
  y los doce `probe` no se tocan (ajuste decidido en `plan.md`, sección *Approach*).
- **REQ-014:** El reporte es informativo: **no** altera el exit code. `install` devuelve 0 si
  todas las acciones se aplicaron, 1 si alguna falló, 2 en error de uso.
- **REQ-015:** Con `--dry-run` el reporte se imprime rotulado como estado **actual** (nada se
  escribió), no como resultado.

### Compatibilidad y documentación

- **REQ-016:** Las garantías vigentes se conservan, verificadas por las pruebas que ya existen:
  idempotencia, no tocar hooks ni bloques ajenos, `.bak` antes de sobrescribir, preservación del
  terminador de línea y `uninstall` que revierte solo lo suyo.
- **REQ-017:** `README.md`, `docs/wiki/Integration-install.md`,
  `docs/recipes/claude-code-integration.md` y `CHANGELOG.md` (`Unreleased`) documentan el flag
  nuevo y el cambio de default como cambio de comportamiento.
- **REQ-018:** Se corrige el docstring de `tests/test_install.py:270-273`, que repite como
  verdad que el formato `args` de los hooks «Claude Code no lo ejecuta» — refutado y ya
  corregido en `install.py:173-177` y `checks.py:296-299`. Y el «once piezas» de
  `docs/wiki/Integration-install.md:79`, que contradice su propia tabla de doce.

## Acceptance scenarios

### Scenario: máquina con un solo cliente (el caso por defecto)

- **Given** un HOME con `~/.claude` y sin `~/.codex`
- **When** se ejecuta `local-delegate install --home <ese HOME>`
- **Then** se imprime que se configura solo Claude Code por detección, se escriben hooks, skill,
  memoria y entrada MCP bajo `~/.claude`, **no se crea `~/.codex`**, y el reporte final lista
  los checks de entorno y andamiaje con Codex en `[ -- ]`.

### Scenario: `--home` simulado no toca el HOME real

- **Given** una máquina con `claude` en el PATH y un `~/.claude.json` real con contenido
- **When** se ejecuta `install --home <tmp>` y después `uninstall --home <tmp>`
- **Then** el binario `claude` no se invoca ni una vez, el `~/.claude.json` real queda idéntico
  byte a byte, y la entrada MCP aparece y desaparece en `<tmp>/.claude.json`.

### Scenario: entrada de Codex escrita a mano, con terminal

- **Given** un `~/.codex/config.toml` con `[mcp_servers.local-delegate]` sin marcadores
- **When** se ejecuta `install` en una terminal interactiva y se responde que **no**
- **Then** esa sección queda intacta, la salida dice que se conservó, el resto del plan se
  aplica y el exit code es 0.

### Scenario: la misma entrada, sin terminal (CI, salida a fichero)

- **Given** el mismo `config.toml` y stdin que no es un tty
- **When** se ejecuta `install`
- **Then** no se pregunta, la sección queda intacta, se avisa de que se conservó y se nombra
  `--force-mcp-codex`, y el exit code es 0.

### Scenario: `--target` sigue funcionando

- **Given** un HOME sin `~/.codex`
- **When** se ejecuta `install --target all --home <ese HOME>`
- **Then** se configuran los dos clientes —incluido Codex, creando su directorio—, igual que
  antes de este change.

### Scenario: HOME sin ningún cliente

- **Given** un directorio vacío
- **When** se ejecuta `install --home <ese directorio>`
- **Then** no se escribe absolutamente nada, se avisa de qué se buscó y cómo forzarlo, y el exit
  code es 0.

## Edge cases and failure behavior

| Caso | Comportamiento |
|---|---|
| `--clients auto --clients claude` | la selección explícita gana; `auto` se ignora sin error |
| `--clients` y `--target` juntos | exit 2, no escribe nada (REQ-004) |
| `--home` igual al HOME real | no es simulado: el camino por CLI sigue disponible |
| `--home` con una ruta irresoluble (`OSError`) | se trata como simulado — el lado seguro es no invocar la CLI global |
| `--no-mcp` con entrada de Codex a mano | no se pregunta: esa acción no está en el plan |
| `--clients codex` en máquina sin Codex | selección explícita: se configura igual y se crea el directorio |
| Un `probe` del reporte final lanza excepción | `run_all` ya lo reporta `unknown`; el reporte no puede tumbar un install que ya escribió |
| `stdin` cerrado o `EOFError` en la pregunta | igual que sin tty: se omite la acción y se avisa |
| `uninstall` con la entrada de Codex puesta a mano | **se quita igual, sin preguntar.** La sección se llama `[mcp_servers.local-delegate]`: es nuestra por definición, y `uninstall` es la orden explícita de retirarla, no de sustituirla por otra configuración. La asimetría con `install` queda anotada en el código |

## Non-functional requirements

- **Seguridad:** ninguna acción nueva escribe fuera del HOME de destino. No se registran ni
  imprimen secretos; `--api-key-env` sigue reenviando la variable sin escribir su valor.
- **Compatibilidad:** el CLI se mantiene retrocompatible salvo el default de clientes, que es el
  objetivo declarado del change y va al `CHANGELOG` como cambio de comportamiento.
- **Operabilidad:** la salida nueva no usa ni un carácter fuera de cp1252 — una flecha `→` mata
  la consola de Windows, y ya pasó (`doctor.py:308-309`).
- **Rendimiento:** el reporte final no sale a la red ni lanza binarios del backend (REQ-013).
- **Diseño:** el registro `CHECKS` sigue siendo una tupla estática de doce elementos y ningún
  `probe` cambia de semántica. Lo único que se admite en `checks.py` es el filtro opcional por
  grupo de REQ-013. No hay registro dinámico, ni entry points, ni herencia.

## Non-goals

- Publicar a PyPI: el change entra en `Unreleased`.
- Modificar `doctor` o `update`.
- Añadir, quitar o cambiar la semántica de ningún `probe`.
- Reparar selectivamente como hace `update`: `install` sigue reescribiendo lo que le toca.
- El resto del backlog (`doctor` vs PyPI, JSON cacheado de `update`, `uv tool upgrade`, hooks
  duplicados, `rev` de ruff, captura del README, amarillo de la landing) y la fase 3 del SDK.

## Traceability

| Requisito | Trabajo planificado | Evidencia de verificación |
|---|---|---|
| REQ-001..005 | `cli.py`: flag, resolución y avisos | tests de CLI + ejecución manual |
| REQ-006..007 | `install.py`: lanzador inyectable y HOME simulado | test con doble del runner + comparación byte a byte |
| REQ-008..011 | `install.py`/`cli.py`: confirmación acotada al caso `warn` | tests de los cuatro caminos (sí, no, sin tty, `--force`) |
| REQ-012..015 | reporte final desde el registro | tests de salida + ejecución manual |
| REQ-016 | sin cambios de comportamiento | la suite existente de `test_install.py` |
| REQ-017..018 | docs y `CHANGELOG` | revisión de diff |
