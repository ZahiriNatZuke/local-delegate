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
| REQ-004 | Techo `mcp>=2,<3` | ✅ | `pyproject.toml`; `uv lock` resuelve `mcp==2.0.0`; **`install-smoke` en verde** resolviendo libremente con `--resolution highest`, que es el escenario de `uvx` que rompió la 0.12.1 |
| REQ-005 | Las 11 tools conservan nombre, firma y salida | ✅ | **11/11 ejecutadas contra llama-swap real** con salidas correctas (ver abajo). Apareció un cambio observable no previsto —el 421 por `Host`—, corregido |
| REQ-006 | Verificar ejecutando, contra el backend real | ✅ | `httpx2` 2.9.1 en el camino, `API_KEY` presente, 12 peticiones HTTP reales a `127.0.0.1:9292`, todas 200 |
| REQ-011 | Declara `httpx2`, nada arrastra `httpx` | ✅ | `httpx` tiene **0 menciones** en `uv.lock` y **0 en `uv pip tree`** sobre el entorno resuelto (las dos comprobaciones que pedía el hallazgo F4); el único `name = "httpx…"` es `httpx2` |
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
- [x] Secret scanning passes. — gitleaks del pre-commit, en verde al commitear; en el PR, `secrets`,
  GitGuardian y CodeQL también.
- [x] No unrelated changes are present. — el diff toca solo la migración, su documentación y la
  traza SDD.

## Las 11 tools contra el backend real (REQ-006)

Ejecutadas el 2026-07-28 contra llama-swap en `127.0.0.1:9292`, con el código ya migrado y
`httpx2` 2.9.1 como cliente. **12 peticiones HTTP reales, todas 200.** No basta con que respondan:
se comprobó que la salida es correcta, no solo presente.

| Tool | s | Salida |
| --- | --- | --- |
| `local_status` | 0.2 | catálogo de los 5 modelos, VRAM, RAM, groups de llama-swap |
| `local_summarize` | 5.8 | resumen fiel del texto de entrada |
| `local_classify` | 0.1 | `red` — la etiqueta correcta de `[red, cocina, arte]` |
| `local_extract` | 0.3 | `{"host": "127.0.0.1", "puerto": "9393"}`, JSON válido |
| `local_boilerplate` | 18.0 | la función pedida, sin explicación alrededor |
| `local_delegate` | 0.1 | `OK` |
| `local_lint_summary` | 0.4 | agrupa F401 y E501 con su conteo |
| `local_commit_msg` | 0.5 | `chore(x.py): agregar tipos a la función suma` |
| `local_translate` | 0.1 | `The backend is down.` |
| `local_explain_code` | 2.4 | explicación correcta de la función |
| `local_describe_image` | 16.5 | describe el dashboard de verdad, con el sufijo del ahorro server-side |

### Comparación contra la línea base (tarea 7)

La línea base de la tarea 1 **no se capturó a tiempo** (se empezó por el spike con la rama ya
creada), así que se reconstruyó después: `local-delegate-mcp==0.12.2` instalado desde PyPI en un
entorno limpio, que resuelve **`mcp` 1.29.0 + `httpx` 0.28.1** — el mundo previo exacto. Las mismas
11 tools, con las mismas entradas, contra el mismo backend.

| | Resultado |
| --- | --- |
| **Idénticas carácter a carácter** | **9 / 11** |
| `ok` en 1.x / en 2.x | 11/11 / 11/11 |
| Degradadas | ninguna, en ninguno de los dos |

Las dos que difieren, verificadas una a una:

- **`local_status`** — tres líneas: el contador de eventos del log (79 → 90) y la VRAM
  (1785 → 1811 MiB), **volátiles por definición**; y la línea de groups de llama-swap, que falta en
  la línea base porque el entorno se instaló **sin el extra opcional `[llamaswap]`** (pyyaml) y esa
  línea lo requiere — degradación documentada en el docstring de `_llamaswap_groups`, no regresión.
  Artefacto del montaje de la comparación, no del SDK.
- **`local_explain_code`** — mismo contenido y estructura, redacción distinta. El modelo corre con
  temperatura: la igualdad carácter a carácter no es exigible aquí.

**Ninguna diferencia es atribuible al SDK ni a `httpx2`.** Esto es lo que convierte REQ-005 de «las
salidas se ven bien» en «el comportamiento no cambió».

Cubre las tres familias que el plan exigía por separado: **texto** (`local_summarize`), **código**
(`local_explain_code`, `local_boilerplate`, con `qwen25-coder-14b`) y **visión**
(`local_describe_image`, con `qwen3-vl-8b`). Que los modelos de 14B y de visión se monten y
respondan prueba que el ciclo completo con llama-swap —incluido el swap de modelos, que es el que
más tarda— sigue funcionando tras cambiar de librería HTTP.

## El daemon migrado y los clientes reales

El daemon de Windows se actualizó a esta rama (`uv sync` + `Stop-Process` + `Start-ScheduledTask`) y
quedó corriendo sobre `mcp` 2.0.0. Verificado contra `http://127.0.0.1:9393/mcp`:

| Comprobación | Resultado |
| --- | --- |
| `initialize` | 200, `serverInfo` = `{"name": "local-delegate", "version": "0.12.2"}` |
| **`protocolVersion` negociado** | **`2024-11-05`** — el mismo que pidió el cliente |
| `tools/list` | las 11 tools, con sus nombres intactos |
| `Host` ajeno | **421**, que confirma que el proceso corre el SDK 2.x |
| Dashboard en la raíz | 200, HTML completo |
| `/api/daemon` | 200 |
| **Claude Code** (cliente real, por el daemon) | `local_status` y `local_translate` respondieron; delegación real de extremo a extremo |

**La duda del nivel de protocolo queda despejada:** era el riesgo declarado en el spec («si 2.x
negocia un nivel de protocolo distinto, un cliente antiguo podría quedar fuera»). No lo negocia:
respeta el que pide el cliente. No hay ruptura para clientes viejos.

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

## Fase 2 — implementada en rama aparte y verificada contra el backend real

Rama **`feat/mcp-sdk-2-fase2`**, sobre la de la fase 1. **239 tests**, los cuatro pasos del CI en
verde en local, handshake OK.

Verificado el 2026-07-29 con `scratchpad/verifica_fase2.py`, que comprueba las tres cosas **tal como
las ve un cliente por el protocolo** (`list_tools` y `call_tool`), no leyendo el código:

| Req | Qué exige | Estado | Evidencia |
| --- | --- | --- | --- |
| REQ-007 | `annotations` que reflejen la verdad | ✅ | `list_tools` devuelve **11/11** con `title`, `read_only_hint=True`, `open_world_hint=False`, y **sin** `destructive_hint`/`idempotent_hint` |
| REQ-008 | `local_extract` con salida estructurada | ✅ | `output_schema` = `{"type": "object", "additionalProperties": true}` (antes `{"result": {"type": "string"}}`). **Contra llama-swap real:** `{"host": "127.0.0.1", "puerto": "9393"}`, dos peticiones 200, claves exactas en la raíz y sin `_local_delegate` cuando no hubo truncamiento. `structured_content` llega igual, y `content` conserva el JSON como texto para clientes que no leen salida estructurada |
| REQ-009 | `title` y `description` del server | ✅ | `title="Local Delegate"`, `description` y `website_url`, con `version` 0.12.2 |

**La degradación por error también quedó probada contra el backend real**, y no por un mock: el
ensayo previo del script corrió sin la API key, el backend respondió **401**, y `local_extract`
devolvió `{"_local_delegate": {"error": "respuesta no parseable como JSON", "crudo": "…401…"}}` con
`is_error: False`. Quien llama ve qué pasó en vez de comerse una excepción de protocolo, que es
justo lo que ese `try/except json.JSONDecodeError` promete.

**Decisiones que conviene no re-discutir:**

- `destructive_hint` e `idempotent_hint` **se omiten**: el protocolo solo les da sentido cuando
  `read_only_hint` es falso, así que declararlos junto a `read_only_hint=True` sería ruido que
  además se contradice. REQ-007 pedía «ninguna es destructiva» y eso ya lo dice `read_only_hint`.
- `read_only_hint=True` **pese al log de uso**, porque ese log es contabilidad interna del servidor
  —lo que alimenta el dashboard—, no un efecto sobre los datos de quien llama.
- La forma de `local_extract` la eligió el usuario entre tres opciones: **claves pedidas en la raíz**
  y lo que no son datos bajo la clave reservada `_local_delegate`. El aviso de truncamiento antes
  iba como texto **delante** del JSON, de modo que la salida ni siquiera era parseable.

**Dos tests existentes cambiaron**, y REQ-005 mandaba señalarlo: comparaban contra la cadena que
`local_extract` ya no devuelve. Ninguno se borró; se añadieron tres.

**Susto descartado:** el SDK 2.x genera `output_schema`/`structured_content` también para tools que
devuelven `str` (`{"result": …}`), lo que parecía un cambio observable no detectado de la fase 1.
**Verificado contra `mcp` 1.29.0: ya pasaba igual.** La única diferencia es interna de Python.

**PR #35, en draft, con base en `feat/mcp-sdk-2` y no en `main`**, para que el diff que se revise
sea solo el de las capacidades nuevas y no arrastre la fase 1. **9 checks en verde**: `lint`,
`secrets`, `install-smoke`, `test` en los tres sistemas, GitGuardian y los dos de Socket Security.

**Son 9 y no los 11 del PR #34, y es por diseño, no por una regresión:** `codeql.yml` solo se
dispara en `push`/`pull_request` contra `main`, así que CodeQL no corre en un PR entre ramas de
trabajo. Correrá cuando la fase 2 llegue a `main`. Conviene saberlo para no leer «9 verdes» como
cobertura perdida.

## Deviations and residual risk

- ~~REQ-006 sin cumplir.~~ **Resuelto:** las 11 tools se ejecutaron contra llama-swap real, 11/11
  con salida correcta. La API key la cargó el usuario en su propia sesión (vive cifrada con DPAPI en
  `%LOCALAPPDATA%\local-delegate\remote-api-key.clixml`) y se borró del entorno al terminar; su
  valor no aparece en ningún artefacto.
- ~~El CI no ha corrido.~~ **Resuelto:** PR #34 (draft) con los **11 checks en verde**, incluidos
  `install-smoke`, `test` en los tres sistemas (ubuntu, macOS, Windows), `lint`, `secrets`, CodeQL,
  GitGuardian y los dos de Socket Security — que **no** levantaron alerta por `pywin32` ni por el
  árbol de dependencias nuevo.
- ~~Clientes reales sin probar.~~ **Resuelto para Claude Code:** el daemon corre la rama y Claude
  Code delega contra él sin cambios. El protocolo negociado sigue siendo `2024-11-05`. **Codex no se
  ha probado**, aunque comparte transporte y el riesgo que quedaba era el nivel de protocolo, que ya
  está descartado.
- **Depscore del paquete publicado (tarea 8): `100/100/99/96/100` en la 0.12.2, idéntico a la
  0.12.1.** Es la línea base contra la que comparar cuando se publique la 0.13.0; el paquete migrado
  todavía no está en PyPI, así que su propio depscore no se puede medir hasta entonces. El árbol
  nuevo sí está medido pieza a pieza y sale limpio salvo `pywin32`.
- **Fallo de proceso, anotado para no repetirlo:** la línea base de la tarea 1 no se capturó antes de
  empezar; se reconstruyó a posteriori instalando la versión publicada. Salió bien porque el paquete
  estaba en PyPI y el backend seguía disponible — si cualquiera de las dos cosas hubiera cambiado, la
  comparación se habría perdido sin remedio.
- **Riesgo de calendario, ya aceptado en el spec:** `mcp` 2.0.0 se publicó el mismo día que rompió
  la 0.12.1. La recomendación de no publicar hasta 2.0.1+ o unas semanas de rodaje sigue en pie, y
  esta rama no la toca.
