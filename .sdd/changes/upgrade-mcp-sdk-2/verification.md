# Verification: Analisis del upgrade al SDK mcp 2.x — Fase 1 (equivalencia)

## Environment

- Revision: rama `feat/mcp-sdk-2`, commit `a8f522b` (2026-07-28).
- Relevant runtime and tool versions: Windows 11, Python 3.11.15, `mcp` 2.0.0, `mcp-types` 2.0.0,
  `httpx2` 2.9.1, `httpcore2` 2.9.1, `starlette` 1.3.1, `fastapi` 0.140.7, `pywin32` 312.
  `httpx` y `respx` **desinstalados**.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | Import y clase del server | ✅ | `type(server.mcp).__module__` → `mcp.server.mcpserver.server`, clase `MCPServer` |
| REQ-002 | Versión propia en el handshake | ✅ | `check_install_handshake.py` → «respondido por local-delegate (versión 0.12.2)»; antes imprimía la del SDK. Test `test_handshake_declara_la_version_del_paquete` |
| REQ-003 | Ruta del MCP como argumento | ✅ | `build_app()` expone `/api/daemon`, `/mcp` y el dashboard en la raíz; `settings.streamable_http_path` ya no se toca |
| REQ-004 | Techo `mcp>=2,<3` | ✅ | `pyproject.toml`; `uv lock` resuelve `mcp==2.0.0` |
| REQ-005 | Las 11 tools conservan nombre, firma y salida | ⚠️ parcial | 11 tools registradas; la suite pasa sin perder casos. **Falta ejecutarlas contra el backend real.** Además apareció un cambio observable no previsto (el 421 por `Host`), corregido — ver abajo |
| REQ-006 | Verificar ejecutando, contra el backend real | ❌ pendiente | bloqueado por la API key (ver *Deviations*) |
| REQ-011 | Declara `httpx2`, nada arrastra `httpx` | ✅ | `httpx` tiene **0 menciones** en `uv.lock`; el único `name = "httpx…"` es `httpx2`. `uv pip list` sin `httpx` |
| REQ-012 | Sin `respx`, sin perder cobertura, ≥233 tests | ✅ | **236 tests** (233 + 3 nuevos). `tests/backend_mock.py` sobre `httpx2.MockTransport` |
| REQ-013 | `pywin32` documentada como heredada | ✅ | sección «Dependencias» de `SECURITY.md`, con sus puntuaciones y por qué no es evitable |

### Depscore de lo que entra (Socket, 2026-07-28)

| Paquete | license | maint | quality | supplyChain | vuln |
| --- | --- | --- | --- | --- | --- |
| `httpx2` 2.9.1 | 100 | 100 | 100 | 100 | 100 |
| `httpcore2` 2.9.1 | 100 | 100 | 100 | 99 | 100 |
| `mcp` 2.0.0 | 100 | 100 | 100 | 98 | 100 |
| `mcp-types` 2.0.0 | 100 | 100 | 100 | 100 | 100 |
| `truststore` 0.10.4 | 100 | 100 | 100 | 100 | 100 |
| **`pywin32` 312** | **70** | 100 | 100 | **73** | 100 |

`httpx2` marca 100 en las cinco dimensiones: quedarse con una sola librería HTTP no compra deuda de
supply chain. `pywin32` es el único punto flojo y no es evitable sin renunciar al SDK 2.x.

## Quality checks

- [x] Project-native tests pass. — `pytest -q` → **236 passed**.
- [x] Lint, formatting, type checking, and build checks pass where applicable. — `ruff check .`
  (All checks passed), `ruff format --check .` (44 files already formatted),
  `extract_dashboard_js.py` + `node --check` OK.
- [x] Secret scanning passes. — gitleaks del pre-commit, en verde al commitear.
- [x] No unrelated changes are present. — el diff toca solo la migración, su documentación y la
  traza SDD.

## Hallazgos de la ejecución que el análisis no había visto

Los dos salieron de **ejecutar**, que es exactamente lo que REQ-006 exigía y lo que leer firmas no
daba.

### 1. El SDK 2.x valida el header `Host` y responde 421

Con un host de loopback, `streamable_http_app` **activa sola** la protección contra DNS rebinding
(`mcp/server/lowlevel/server.py`) y solo admite `127.0.0.1:*`, `localhost:*` y `[::1]:*`. El daemon
no le pasaba el host, así que quedaba activada **siempre**, incluso con
`LOCAL_DELEGATE_WEB_HOST=0.0.0.0` — un escenario que el proyecto documenta y permite. Publicar el
daemon en la red local habría dejado de funcionar **en silencio**: 421 a todo cliente que llegara
por la IP de la LAN.

Corregido pasando el host configurado, que hace lo correcto en ambos casos: con loopback la
protección queda puesta gratis, y con `0.0.0.0` no se activa. Dos tests nuevos lo fijan.

Contradecía REQ-005 («no cambia nada observable»), y por eso se corrige en vez de aceptarse.

### 2. `respx` interceptaba global; `MockTransport` hay que inyectarlo

El plan trataba la migración de la suite como una sustitución uno a uno. No lo es: el paquete crea
clientes HTTP en varios sitios (`server.py` cacheado, más `web/metrics.py`, `daemon.py`,
`autostart.py`, `doctor.py`, `benchmark.py`), y `respx` los interceptaba todos sin que el código lo
supiera. `tests/backend_mock.py` lo resuelve sustituyendo la clase `httpx2.Client` mientras dura el
test e invalidando el cliente cacheado de `server`, que si se creó antes del mock traería su
transport real.

## Deviations and residual risk

- **REQ-006 sin cumplir: las 11 tools no se han ejecutado contra el backend local real.** La API
  key vive cifrada con DPAPI (`%LOCALAPPDATA%\local-delegate\remote-api-key.clixml`) y descifrarla
  quedó fuera de lo que la sesión podía hacer. Mitigación parcial: `httpx2` **sí** completó una
  conversación HTTP real con llama-swap en `:9292` —volvió un 401 legítimo, parseado y elevado como
  `HTTPStatusError`—, así que el transporte y el manejo de errores funcionan contra el backend de
  verdad; lo que falta es el tramo autenticado y la comparación de salidas tool a tool.
  **La evidencia todavía NO es suficiente para cerrar la fase 1.**
- **El CI no ha corrido.** El workflow solo se dispara en `push` a `main` o en `pull_request`, así
  que `install-smoke` —el check que resuelve libremente y habría cazado el incidente de la 0.12.1—
  no se ha ejecutado con `mcp` 2.x. Requiere abrir un PR.
- **Clientes reales sin probar.** Claude Code y Codex contra el daemon migrado, por si 2.x negocia
  otro nivel de protocolo. El daemon en ejecución sigue siendo el de 0.12.2 sobre `mcp` 1.x.
- **Riesgo de calendario, ya aceptado en el spec:** `mcp` 2.0.0 se publicó el mismo día que rompió
  la 0.12.1. La recomendación de no publicar hasta 2.0.1+ o unas semanas de rodaje sigue en pie, y
  esta rama no la toca.
