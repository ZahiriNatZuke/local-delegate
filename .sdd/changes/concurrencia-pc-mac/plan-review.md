# Revisión del gate plan — concurrencia-pc-mac

Revisor: subagente `personal-sdd-plan-reviewer`, independiente, sin herramientas `local_*` (MCP
caído el 2026-10-29). Dos rondas.

## Ronda 1 — rechazado (6 bloqueantes)

| # | Hallazgo | Resolución en `plan.md` |
|---|---|---|
| B1 | El test de dos máquinas con `python -I` ignora `PYTHONPATH` y probaría el código de `main` (el `.venv` importa `main`); el hijo podía heredar token, Llavero o `LOG_DIR` real. | Lote 4: `sys.executable` sin `-I`, lanzador con `sys.path.insert(0, <worktree>/src)` y comprobación de `__file__` (sale con código 3), entorno construido desde cero, `GuardedPopen` de `tests/conftest.py:406`. |
| B2 | El lote 3 no tenía forma de enterarse de cambios del turno (`Turn._cond` privado); `release_slot`/`abandon` no reevalúan; cambio de comportamiento sin inventario de tests. | Lote 2: `wait_change(timeout)` con contador de versión, `release_slot`/`abandon` llaman a `_apply`, **paso 0 de inventario** de tests que dependan de eso o de la forma de `Active`. |
| B3 | La cesión remota no tenía lote; `expired`/429 seguían como degradación. | Lote 3: `yield` por arrendamiento y tope para quien lo ignore; lote 4: `expired` = volver a pedir, 429 = esperar. |
| B4 | Exención de `PortToken` por prefijo; `is_request_authorized` acepta `Basic`; faltaban `Origin`/JSON y el test de variantes. | Lote 3: igualdad exacta de método y ruta (`TURN_ROUTES`), solo `Bearer`, sin `Origin`, JSON; tests de `Basic`, cookie y variantes de ruta (`..`, `%2e%2e`, `//`, `/x`, `GET`). |
| B5 | Muestreo por operación frente a la spec nueva por envío; carrera del temporizador que podía escribir `backend_wait` tras la limpieza. | Lote 1: `send_watch` por envío con `Event` de parada y número de generación; tests (f), (g), (h) con su control positivo. |
| B6 | Con túnel y `BACKEND_ORIGIN=remote`, el descubrimiento podía apuntar al daemon propio. | Lote 4: guarda «nunca a sí mismo» por loopback + `WEB_PORT` propio y por `daemon_id`; test con control positivo. |

No bloqueantes atendidos: REQ-005 con `_LoadProbe` primero; cesión en las dos salidas tempranas de
`ensure` (afinidad y mismo modelo) y `affinity = None` al volver; `in_backend: false` al conceder y
`_inflight_live` para entradas remotas; `_note_queue_progress` en eventos remotos; interruptor
`LOCAL_DELEGATE_TURN_SERVER=off` para el rollback en la PC sin publicar; cifras del paso 1 en los
criterios en vivo y definición comprobable de «evento duplicado»; tabla REQ → test → control
positivo.

## Ronda 2 — aprobado con cambios (incorporados)

Los seis bloqueantes y los no bloqueantes de la ronda 1, cubiertos. Dos correcciones pequeñas,
ya aplicadas en `plan.md` y `spec.md`:

1. **`daemon_id` no existía** (`daemon._daemon_payload`, `daemon.py:58-67`, solo guarda servicio,
   pid, host, puerto y URL): el lote 3 lo genera una vez por arranque (`secrets.token_urlsafe(16)`),
   lo escribe en `daemon.json` y `/api/daemon` y lo devuelve en cada respuesta del endpoint, con
   test de estabilidad; el lote 4 compara el de `acquire` con el del `daemon.json` local.
2. **Entorno de los hijos del test de dos máquinas:** `USERPROFILE`, `HOME`, `APPDATA` y
   `LOCALAPPDATA` a `tmp_path`, y comprobación por hash de que `~/.claude.json` y el
   `inflight.json`/log reales no cambian.

Aviso atendido: test de carga en el lote 3 (16 esperas largas abiertas y `/api/inflight` < 1 s;
threadpool de anyio de 40 hilos).

Con esto el gate queda **aprobado**. Evidencia exigida en la implementación: inventario del paso 0
del lote 2 con su resultado; tabla de control positivo por lote en `verification.md` con el
`assert` que cae; salida del lanzador de cada hijo (`__file__` bajo el worktree y el código 3 del
control positivo); ningún PID vivo ni fichero real cambiado tras el test de dos máquinas; lista de
rutas con exención y 401 de cada variante; paso 0 del lote 3 hecho (clave confirmada por hash en las
dos máquinas, sin mostrar valores).
