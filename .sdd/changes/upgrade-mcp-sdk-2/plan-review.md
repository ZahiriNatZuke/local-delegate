# Plan review: Analisis del upgrade al SDK mcp 2.x

Revisión adversarial previa al gate `plan`. Fecha: 2026-07-28.

## Limitación declarada

Revisión **no independiente**: la hizo el mismo agente que redactó el plan, por una instrucción de
sesión que impide lanzar subagentes sin petición explícita. El `personal-sdd-plan-reviewer` no se
ejecutó.

## Findings

### F1 — Bloqueante · `fastapi.testclient.TestClient` va sobre `httpx`

El plan da por hecho que quitar `httpx` de las dependencias es inocuo. **No lo es.**
`fastapi.testclient.TestClient` se usa en **2 ficheros y ~22 puntos** (`tests/test_metrics.py`,
`tests/test_daemon.py`) y Starlette lo implementa sobre `httpx`. Si `httpx` desaparece del entorno,
esos tests pueden dejar de arrancar — y son los que cubren el dashboard y el daemon, no periferia.

Hay indicio a favor —la propia suite emite hoy `StarletteDeprecationWarning: Using httpx with
starlette.testclient is deprecated; install httpx2 instead`, lo que sugiere que Starlette ya prefiere
`httpx2`— pero **es un indicio, no una verificación**. Depende de la versión de Starlette que
resuelva el lock.

**Corrección aplicada al plan:** se añade un **spike de viabilidad** como primera tarea de la fase 1,
antes de tocar `pyproject.toml`. Si `TestClient` no funciona sin `httpx`, la decisión de una sola
librería HTTP hay que revisarla con el usuario, no forzarla.

### F2 — Resuelto durante la revisión · `httpx2` cubre lo que usan los tests

El plan asumía que la API de `httpx2` era análoga a partir de `Client`/`AsyncClient`/`MockTransport`.
Verificado contra el `__init__.py` del wheel 2.9.1: expone también **`Response`, `Request`,
`ConnectError`, `HTTPError`, `TimeoutException`, `HTTPStatusError`, `Timeout` y `Limits`** — que es
exactamente lo que aparece en los tests y en el manejo de errores del cliente.

Sin esto, la tarea 5 (migrar el cliente) y la 6 (migrar la suite) estaban apoyadas en una suposición.

### F3 — Menor · El plan no fija el tipo de versión

«No es un patch» es vago. La migración cambia el árbol de dependencias de quien instala y sube el
mínimo de `pydantic`: es un **minor** (0.13.0), y así debe decirlo el plan.

### F4 — Menor · «ninguna dependencia arrastra `httpx`» no tenía forma de comprobarse

Se concreta: `uv pip tree` sobre el entorno resuelto, más la ausencia de `httpx` en `uv.lock`.

### F5 — Aceptado · Rama larga y divergencia

Una rama de varias fases se separa de `main`. Se acepta porque `main` debe poder publicar fixes de
1.x mientras tanto, y se mitiga con rebase periódico, ya en el plan.

## Verdict

**Un hallazgo bloqueante (F1), corregido en el plan con un spike previo.** F2 quedó verificado
durante la revisión, F3 y F4 concretados, F5 aceptado con mitigación.
