# Spike de viabilidad de httpx2 (tarea 1b) — cierra el hallazgo F1

Fecha: 2026-07-28. Entorno desechable, fuera del repo: Python 3.11.15 con `fastapi==0.140.7`,
`starlette==1.3.1`, `httpx2==2.9.1`, `pytest`, y **sin `httpx`** (22 paquetes instalados, `httpx` no
está entre ellos).

El F1 decía que quitar `httpx` podía romper los ~22 puntos de `TestClient` en `test_metrics.py` y
`test_daemon.py`, porque Starlette implementa `TestClient` sobre `httpx`. **Ya no es así.**

## (a) `TestClient` sin `httpx` — VERDE

Starlette 1.3.1 invirtió la preferencia. `starlette/testclient.py`:

```python
try:
    import httpx2 as httpx
except ModuleNotFoundError:
    try:
        import httpx
    except ModuleNotFoundError:
        raise RuntimeError("The starlette.testclient module requires the httpx2 package…")
    else:
        warnings.warn("Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.")
```

`httpx2` es el camino principal y `httpx` el fallback deprecado — que es exactamente el aviso que
emite la suite hoy. Verificado **ejecutando**, no leyendo:

| Comprobación | Resultado |
| --- | --- |
| `import httpx` en el entorno | `ModuleNotFoundError` (el spike no valdría nada si estuviera) |
| `starlette.testclient.httpx.__name__` | `"httpx2"`, y `httpx` no queda en `sys.modules` |
| `TestClient` sobre app Starlette (GET texto y JSON) | sirve |
| `TestClient` sobre FastAPI con `Mount` de una sub-app | sirve — es el patrón del daemon (dashboard en la raíz, MCP en `/mcp`) |
| `TestClient` como context manager + POST con JSON | sirve — es el patrón de `test_metrics.py` |
| Excepción de la app propagada al test | `pytest.raises` la ve |

**Conclusión: F1 queda cerrado.** Quitar `httpx` no rompe los tests del dashboard y del daemon.

## (b) `MockTransport` en lugar de `respx` — VERDE, con una consecuencia

Los patrones que hoy usa `respx` en la suite tienen equivalente directo:

| Patrón de `respx` | Equivalente con `httpx2.MockTransport` |
| --- | --- |
| `.mock(return_value=httpx.Response(200, json=…))` | el handler devuelve `httpx2.Response(200, json=…)` |
| `.mock(return_value=httpx.Response(500, text="boom"))` | ídem con `text=` |
| `.mock(side_effect=httpx.ConnectError(…))` | el handler lanza `httpx2.ConnectError` |
| `side_effect=[r1, r2, …]` y `route.calls.call_count` | el handler acumula en una lista y va sirviendo por índice |
| varias rutas en un test (`/v1/models`, `/running`) | el handler enruta por `request.url.path` |
| `raise_for_status()` → `HTTPStatusError.response.status_code` | igual |

F2 de la revisión verificado por ejecución: `httpx2` expone `Response`, `Request`, `ConnectError`,
`HTTPError`, `TimeoutException`, `HTTPStatusError`, `Timeout`, `Limits`, `MockTransport`,
`ASGITransport`, `Client` y `AsyncClient`, con la misma jerarquía (`ConnectError` y `HTTPStatusError`
heredan de `HTTPError`).

**La consecuencia, que el plan no había medido:** `respx` intercepta **globalmente**; `MockTransport`
hay que **inyectarlo** en el `Client`. En `server.py` eso es barato porque hay un cliente
module-level (`_get_client()`), pero el repo instancia `httpx.Client(...)` *localmente* en al menos
seis sitios más: `server.py:1599,1618`, `web/metrics.py:351,381`, `daemon.py:100`, `autostart.py:31`,
más `doctor.py` y `benchmark.py`. Para esos, la migración necesita **monkeypatch de `httpx2.Client`**
(un fixture que envuelva la clase e inyecte el transport) o refactorizarlos para aceptar un cliente.
El spike prueba que el monkeypatch funciona. Es trabajo real que la tarea 6 tiene que asumir.

## (c) Cliente contra el backend local real — PENDIENTE, no bloqueante

`httpx2` **sí completó una conversación HTTP real con llama-swap** en `127.0.0.1:9292`: la petición
salió y volvió un `401 Unauthorized` legítimo del backend, parseado por `httpx2` y elevado como
`HTTPStatusError`. Lo que falta es un `chat/completions` autenticado, y falta solo porque la API key
vive cifrada con DPAPI (`%LOCALAPPDATA%\local-delegate\remote-api-key.clixml`) y su descifrado quedó
fuera de lo que esta sesión puede hacer.

No bloquea: el criterio de parada de la tarea 1b era (a), y el plan ya exige en la **tarea 5** la
delegación real contra el backend en tres tools de familias distintas, con el código ya migrado.

Script listo para ejecutarlo a mano: `scratchpad/spike-httpx2/backend_real.py`.

## Veredicto

**Se sigue adelante con la decisión de una sola librería HTTP.** El único punto que podía obligar a
revisarla —`TestClient` sobre `httpx`— ya no aplica con Starlette 1.3.1.

14/14 tests del spike en verde.
