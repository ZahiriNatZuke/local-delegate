# Verification: evaluación de la fase 3 del SDK `mcp` 2.x

## Environment

- Revisión: `main` en `fa08d64` (PRs #93 y #94) + este cierre.
- SDK evaluado: `mcp` **2.0.0**, el instalado, no el documentado.
- La evaluación se cierra el **2026-07-31**.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | veredicto de las cinco capacidades | pass | tabla resumen de `research.md` |
| REQ-002 | cada veredicto con comprobación ejecutada | pass | ver abajo |
| REQ-003 | descartes escritos en la arquitectura | pass | `docs/wiki/Architecture.md`, sección «Qué se usa del SDK `mcp` 2.x, y qué no» |
| REQ-004 | `elicitation` declarada bloqueada, no descartada | pass | `research.md` §2 |
| REQ-005 | `auth` evaluado pieza a pieza | pass | `research.md` §3, dos veredictos |

### Las comprobaciones que sostienen cada veredicto

| Capacidad | Lo que se ejecutó | Lo que salió |
| --- | --- | --- |
| `extension` / interceptor | conteo de invocaciones de `_log_event` en `server.py` | **3** (`_chat`, `_chat_chunked`, `_chat_map_reduce`), no once |
| `subscriptions` | grep de `@mcp.resource` y `@mcp.prompt` en `src/` | **0** de cada uno; solo 11 tools |
| `caching` | lectura de `CACHEABLE_METHODS` en el SDK | son métodos de protocolo, no inferencia |
| `auth` | listado del contenido de `mcp.server.auth` | dos familias: `provider`/`handlers`/`routes` y `middleware/bearer_auth` |
| revisión del protocolo | `LATEST_PROTOCOL_VERSION` y `DEFAULT_NEGOTIATED_VERSION` | `2026-07-28` y `2025-03-26` |

## Quality checks

- [x] Project-native tests pass — este change no toca código; la suite se mantuvo en verde en los
      PRs que lo acompañan.
- [x] Lint y formato — solo Markdown; sin cambios de código.
- [x] Secret scanning passes — sin credenciales ni datos personales en los artefactos.
- [x] No unrelated changes — la implementación del observador salió a su propio change.

## El error de método que este change cometió y corrigió

La primera comprobación fue `grep -i middleware` sobre el repo, con **cero** resultados, de lo que
se concluyó que el SDK no tenía nada de eso. **Era falso**: ripgrep respeta `.gitignore`, `.venv/`
está ignorado y la búsqueda **ni entró en el paquete**. Buscando desde Python aparecen 20 ficheros
y el módulo `server/auth/middleware`.

Queda como regla de la casa, y este documento es su evidencia: **un no-resultado no es evidencia si
no se comprueba que la búsqueda podía encontrar algo.**

El segundo error fue de granularidad: la primera redacción descartaba `auth` entero de un plumazo,
metiendo en el mismo saco un servidor OAuth2 y un `bearer_auth` ligero. Lo cazó una pregunta del
usuario. **Un módulo puede traer dos cosas de tamaño muy distinto.**

## Deviations and residual risk

- **`elicitation` quedó fuera del veredicto de este change, a propósito** (REQ-004). Se declaró
  bloqueada por una medición nombrada, y esa medición se hizo en el change
  `observador-capabilities-cliente`: **Claude Code y Codex declaran los dos `elicitation`**, así que
  la capacidad queda desbloqueada en sentido afirmativo y pendiente de su propio change.
- **Los descartes valen para el SDK 2.0.0 y para este repo tal como está hoy.** `subscriptions`
  cambia de veredicto el día que se expongan recursos MCP; `bearer_auth`, el día que el daemon salga
  de loopback. Ambos condicionantes están escritos en `Architecture.md`, no solo aquí.
