# Especificación — `local-delegate update`

## Summary

Actualizar deja de ser un script de bash que solo cambia un número: pasa a ser un subcomando del
CLI que **revisa el estado real de la máquina, actualiza lo que haya que actualizar, completa lo que
falte de configuración y termina siempre dejando el daemon arriba** — reiniciándolo si corría,
levantándolo si no. El backend de inferencia no se toca salvo que se pida.

Reparto de responsabilidades, explícito:

- **`install`** configura desde cero: hooks, skill, memoria y entrada MCP.
- **`update`** revisa lo instalado, actualiza la versión, **completa lo que falte** y deja el daemon
  arriba.
- **Los dos** terminan con el daemon en marcha cuando la configuración lo usa.

## Requirements

### El subcomando

- **REQ-001:** `local-delegate update` existe, aparece en `local-delegate --help` y acepta
  `--dry-run`, `--home DIR`, `--version X.Y.Z`, `--restart-backend` y `--no-restart`.
- **REQ-002:** **Paridad con el script**: actualiza el pin `local-delegate-mcp==X.Y.Z` en
  `~/.claude.json` y `~/.codex/config.toml` donde exista, con copia `.bak`, conservando el
  terminador de línea del fichero y sin tocar ninguna otra clave de la entrada. La última versión se
  consulta por el **índice simple** de PyPI, no por `/pypi/<pkg>/json`.
- **REQ-003:** Completa la configuración ausente reusando `install.plan_install`, y es
  **idempotente**: correrlo dos veces seguidas no produce cambios la segunda vez ni duplica hooks,
  bloques ni entradas MCP.
- **REQ-004:** `--dry-run` describe todo lo que haría —ediciones, reinicio y arranque incluidos— y
  **no escribe ni reinicia nada**.

### El daemon, al final de todo

- **REQ-005:** Si el daemon está arriba, `update` lo reinicia y **verifica que reinició de verdad**:
  `/api/daemon` vuelve a responder y el `pid` es **distinto** del que había antes.
- **REQ-006:** Si no está arriba pero la configuración de algún cliente lo usa (entrada de tipo
  HTTP), `update` lo **levanta** y verifica que `/api/daemon` responde.
- **REQ-007:** Usa el mecanismo registrado en la máquina, en este orden: tarea programada
  `LocalDelegateDaemon` (Windows), LaunchAgent `com.local-delegate.daemon` (macOS), unidad
  `local-delegate.service` de `systemd --user` (Linux). Si no hay ninguno registrado, cae al
  **fallback**: terminar el proceso y relanzar `serve` desacoplado.
- **REQ-008:** **Nunca termina un proceso por el pid del fichero de estado sin confirmarlo antes
  contra `/api/daemon`.** Un pid reciclado por otro proceso no debe recibir la señal.
- **REQ-009:** Si no hay daemon aplicable —el caso `stdio` + `uvx` de la Mac—, lo dice con esas
  palabras, recuerda que ahí lo que aplica es reiniciar el cliente, y **termina con éxito**: no es
  un error.
- **REQ-010:** `--no-restart` salta toda esta parte y solo informa.
- **REQ-011:** `install` también termina dejando el daemon arriba, con las mismas reglas, **cuando la
  configuración que acaba de instalar lo usa**. Si instaló `stdio`, no levanta nada.

### El backend de inferencia

- **REQ-012:** El backend (`llama-swap` / `llama-server`, puerto 9292) **no se toca por defecto**,
  ni siquiera cuando el daemon se reinicia. Solo con `--restart-backend` explícito.
- **REQ-013:** La salida deja claro, cuando reinicia el daemon, que el backend **no** se ha tocado y
  que los modelos siguen en VRAM.

### Casos de máquina

- **REQ-014:** Con una instalación **editable** (el daemon corre de un venv del repo, como esta PC),
  `update` lo detecta y avisa de que reiniciar **no cambia la versión** sin `git pull` + `uv sync`
  antes, con los comandos exactos. No los ejecuta.
- **REQ-015:** Si no hay pin que cambiar pero sí daemon vivo, `update` **igual** hace su trabajo
  (completar y reiniciar) en vez de terminar diciendo «no se toca» como hoy.

### Documentación y compatibilidad

- **REQ-016:** `docs/wiki/Daemon.md` gana la receta completa de **macOS (LaunchAgent)** y de
  **Linux (`systemd --user`)**, al mismo nivel de detalle que la de Windows, con los nombres
  canónicos que detecta REQ-007.
- **REQ-017:** `scripts/update_to_latest.sh` queda como envoltorio fino que delega en el CLI y
  acepta los mismos argumentos, para no romper el hábito en la Mac.

## Acceptance scenarios

### Escenario: esta PC — daemon por HTTP, sin pin, instalación editable

- **Dado** el daemon vivo en el 9393 (`pid` P, versión V) y ninguna entrada con pin
- **Cuando** se ejecuta `local-delegate update`
- **Entonces** no cambia ningún pin, avisa de que la instalación es editable, reinicia el daemon, y
  `/api/daemon` responde con un `pid` distinto de P — y `llama-swap` sigue con el mismo pid

### Escenario: la Mac — `stdio` con pin y sin daemon

- **Dado** `~/.claude.json` con `local-delegate-mcp==0.13.0` y ningún daemon escuchando
- **Cuando** se ejecuta `local-delegate update`
- **Entonces** el pin queda en la última publicada con su `.bak`, y la salida dice que no hay daemon
  que reiniciar y que hay que reiniciar el cliente. Código de salida 0

### Escenario: el daemon está caído

- **Dado** una entrada MCP de tipo HTTP y nadie escuchando en el puerto
- **Cuando** se ejecuta `local-delegate update`
- **Entonces** lo levanta por el mecanismo registrado y `/api/daemon` acaba respondiendo

### Escenario: falta configuración

- **Dado** un HOME donde la skill o los hooks no están instalados
- **Cuando** se ejecuta `local-delegate update`
- **Entonces** los instala sin duplicar lo que ya existía, y una segunda ejecución no produce cambios

### Escenario: el pid del estado ya no es el daemon

- **Dado** un `daemon.json` con un pid que ahora pertenece a otro proceso y nada escuchando
- **Cuando** `update` intenta reiniciar
- **Entonces** **no** envía ninguna señal a ese pid: trata el daemon como caído y lo levanta

## Edge cases and failure behavior

- **Sin red o PyPI caído:** no se puede resolver la última versión. Se avisa y se sigue con el resto
  (completar y reiniciar), sin tocar los pines. Código de salida 0.
- **El mecanismo registrado falla** (`schtasks` devuelve error, `launchctl` no encuentra el label):
  se informa del fallo concreto y se cae al fallback antes de darse por vencido.
- **El daemon no vuelve** dentro del margen de espera: se informa con el último error y se sale con
  código distinto de 0. Es el único caso que debe fallar ruidosamente.
- **Dos daemons / puerto ocupado por otro:** `query_daemon` ya distingue «es nuestro daemon» de
  «alguien escucha ahí»; un puerto ocupado por otro servicio no se toca ni se mata.
- **`--home` apuntando a un HOME simulado:** nada fuera de ese árbol se escribe, igual que en
  `install`.

## Non-functional requirements

- **Sin dependencias nuevas.** Todo con lo ya presente: `httpx2`, `platformdirs`, `subprocess`,
  `urllib`.
- **Multiplataforma de verdad:** el camino principal no puede exigir bash. Debe correr en Windows sin
  Git Bash.
- **Seguridad:** no se lee ni se escribe ninguna API key; `update` no toca variables de entorno ni el
  secreto DPAPI. Solo se envía señal a un proceso confirmado como daemon propio (REQ-008).
- **Cobertura:** tests de pytest para la selección de mecanismo, el fallback, la idempotencia, el
  `--dry-run` y la protección del pid, con el ejecutor de comandos inyectado — sin lanzar procesos
  reales en el CI.

## Non-goals

- **No** registra el LaunchAgent ni la tarea programada: eso es trabajo de `install`, y queda para su
  propio change. `update` **usa** el que haya y documenta cómo crearlo.
- **No** ejecuta `git pull` ni `uv sync` (REQ-014 solo avisa).
- **No** toca `autostart.ensure_backend()` ni el arranque del backend.
- **No** promueve los otros dos scripts mal colocados (`install_claude_code_hooks_macos.sh`,
  `docs/recipes/update_agents.py`): se anotan en el backlog como changes propios.

## Traceability

| Req | Trabajo previsto | Verificación |
|---|---|---|
| REQ-001, 004 | `cli.py`: parser `update` | `--help` y `--dry-run` por ejecución |
| REQ-002 | `update.py`: puerto del pin desde bash | tests con HOME simulado + `.bak` y newline |
| REQ-003, 011 | reuso de `plan_install`/`apply` | test de idempotencia (dos pasadas) |
| REQ-005..010 | `update.py`: detección y reinicio | tests con ejecutor inyectado + ejecución real en esta PC |
| REQ-012, 013 | flag y mensajes | test de que no se invoca al backend sin la flag; pid de llama-swap intacto |
| REQ-014, 015 | detección de editable / sin pin | ejecución real en esta PC |
| REQ-016 | `docs/wiki/Daemon.md` | revisión de contenido |
| REQ-017 | `scripts/update_to_latest.sh` | ejecución del envoltorio |
