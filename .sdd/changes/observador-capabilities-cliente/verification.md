# Verification: observador de capabilities del cliente

## Environment

- Revisión: rama `feat/observador-capabilities-cliente` sobre `main` en `fa08d64`.
- Runtime: Python 3.11 (uv), `mcp` 2.0.0, Windows 11.
- Clientes de la medición: Claude Code 2.1.220, Codex CLI 0.146.0-alpha.3.1.

## Quality checks

- [x] Project-native tests pass — **519 passed, 1 skipped** (503 antes + 16 nuevos).
- [x] `uv run ruff check .` → `All checks passed!`
- [x] `uv run ruff format --check .` → `59 files already formatted`
- [x] `extract_dashboard_js.py` + `node --check` → escrito (39395 chars), `node --check OK`
- [x] Secret scanning — no se añaden credenciales; el registro guarda nombre y versión de un
      programa, protocolo y nombres de capabilities, y hay un test que asevera el **conjunto
      exacto** de campos escritos.
- [x] No unrelated changes.

## Los tests, verificados al revés

Un test que no falla con el defecto puesto no prueba nada. Se introdujo cada defecto uno a uno, se
corrió la suite y se restauró el fichero (comprobado byte a byte al final):

| Defecto introducido | Resultado |
| --- | --- |
| observar **también** en `initialize` | `test_el_middleware_ignora_initialize_aunque_haya_datos` falla |
| dedupe roto (escribe siempre) | **4** tests fallan, entre ellos el de los veinte mensajes |
| `snapshot()` devuelve el estado interno | `test_snapshot_esta_desligado_del_estado_interno` falla |
| quitar la guarda de identidad vacía | `test_sin_capabilities_ni_identidad_no_registra` falla |
| el middleware propaga la excepción | `test_un_observador_que_revienta_no_rompe_la_llamada` falla |
| un campo de más en la línea escrita | `test_la_linea_tiene_exactamente_los_campos_declarados` falla |
| `/api/status` devuelve lista vacía | `test_api_status_expone_los_clientes_observados` falla |

**Y el ejercicio sirvió para algo, que es el motivo de hacerlo:** la primera versión del test de
REQ-002 **no probaba nada**. Conectaba un cliente, hacía solo el handshake y comprobaba que no
quedaba línea; con el defecto puesto —observar también en `initialize`— los catorce tests seguían
pasando, porque durante el handshake no hay ni capabilities ni identidad y **la guarda de REQ-007
descartaba igual**. Medía la otra protección. Se reescribió en dos: uno que ataca la regla directa
(contexto con datos + `method="initialize"` → no registra) y otro que fija la medición del SDK para
que un cambio suyo se note aquí.

## La medición en vivo — el propósito del change

Hecha con **Claude Code y Codex reales**, cada uno lanzando el servidor del repo por stdio con su
propio `LOCAL_DELEGATE_LOG_DIR`. **No se tocó el daemon en producción ni la configuración del
usuario**: Claude Code con `--mcp-config` + `--strict-mcp-config`, Codex con overrides `-c`.

Contenido íntegro de `clients.jsonl` tras las dos conexiones:

```json
{"ts": "2026-07-31T15:53:01+00:00", "client": "claude-code", "version": "2.1.220", "protocol": "2025-11-25", "caps": ["elicitation", "roots"]}
{"ts": "2026-07-31T15:55:54+00:00", "client": "codex-mcp-client", "version": "0.146.0-alpha.3.1", "protocol": "2025-06-18", "caps": ["elicitation"]}
```

### Lo que dice

1. **Los dos clientes declaran `elicitation`.** La decisión que estaba bloqueada queda desbloqueada
   y en sentido afirmativo: `elicitation` tiene recorrido real en este repo.
2. **Cada cliente negocia una revisión distinta**: `2025-11-25` y `2025-06-18`. Con el cliente de
   prueba del SDK salió `2025-11-25`. **Ninguna** es `LATEST_PROTOCOL_VERSION` (`2026-07-28`) ni
   `DEFAULT_NEGOTIATED_VERSION` (`2025-03-26`). Deducir la revisión de las constantes del servidor
   habría dado el número equivocado en los tres casos.
3. **Ninguno declara `sampling`**, que es dato para futuras evaluaciones.
4. Codex conecta como `codex-mcp-client`, no como «codex»: el nombre del binario y el del cliente
   MCP no coinciden.

### Nota de logística, por si hay que repetirla

- **Claude Code y Codex hablan con local-delegate por *stdio*, no con el daemon del 9393.** Cada
  uno lanza su propio proceso. Por eso se puede medir sin parar nada.
- **Codex no lee un `config.toml` del directorio de trabajo**, solo el global: se intentó y
  `codex mcp list` no mostró el servidor. La vía que funciona son los overrides `-c`.
- **`codex.cmd` pasa por `cmd.exe`, que se come las comillas dobles.** Un override con
  `args=["a","b"]` llega como `[a,b]` y falla con *expected a sequence*. Con **comillas simples**
  de TOML (`args=['a','b']`) sobrevive.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | dos clientes reales conectados | pass | `clients.jsonl` de arriba; `test_un_cliente_deja_una_linea_con_lo_negociado` |
| REQ-002 | contexto con datos y `method="initialize"` | pass | `test_el_middleware_ignora_initialize_aunque_haya_datos` (verificado al revés) + `test_en_initialize_el_sdk_todavia_no_entrega_los_datos` |
| REQ-003 | veinte mensajes → una línea | pass | `test_veinte_mensajes_dejan_una_sola_linea`; en vivo Claude Code hizo handshake + `tools/list` + `tools/call` y dejó **una** línea |
| REQ-004 | `GET /api/status` con el registro poblado | pass | `test_api_status_expone_los_clientes_observados` |
| REQ-005 | escritura que lanza, observador que lanza | pass | `test_un_fallo_de_escritura_no_propaga`, `test_un_observador_que_revienta_no_rompe_la_llamada` |
| REQ-006 | capabilities sin `client_info` | pass | `test_capabilities_sin_identidad_si_registra` |
| REQ-007 | mensaje sin caps ni identidad | pass | `test_sin_capabilities_ni_identidad_no_registra` |

## Deviations and residual risk

- **El transporte `streamable_http` no se midió.** Los dos clientes reales usan stdio, así que el
  camino HTTP queda cubierto por los tests y por lectura de código (el middleware vive en
  `ServerRunner`, común a los transportes), **no por medición en vivo**. Si algún día un cliente
  conecta al 9393 por HTTP, confirmar que también queda registrado.
- **El camino del envelope moderno (2026-07-28+)**, donde las capabilities llegan sin identidad,
  está cubierto por test pero **ningún cliente real negocia todavía esa revisión** — que es
  precisamente lo que la medición demuestra.
- **Dos instancias idénticas del mismo cliente cuentan como una** (dedupe por identidad, no por
  conexión). Decisión consciente, escrita en la spec y en el plan; evita atarse a un privado del
  SDK.
