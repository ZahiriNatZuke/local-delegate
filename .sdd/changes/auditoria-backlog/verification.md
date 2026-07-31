# Verification: Auditoría del backlog: veredicto por punto

## Environment

- Revision de partida: `b04a5e2` (`main`, árbol limpio, 562 tests + 1 skipped, `Unreleased` vacío)
- local-delegate 0.18.1 (CLI de `uv tool` y daemon), Windows 11, Python 3.11/3.12, `mcp` 2.x
- Backend: llama-swap v238 / llama-server b9925 en `127.0.0.1:9292`, **con API key exigida**

## Evidence — veredicto por punto

| # | Punto | Veredicto | Evidencia de ejecución |
| --- | --- | --- | --- |
| 1 | El JS del dashboard no tiene tests de comportamiento | **PARCIAL** | `metrics.py` son **1544** líneas y el JS extraído **593**, no «~1600 de JS». `extract_dashboard_js.py` + `node --check` pasan (exit 0). Un único test ejecuta JS: `test_metrics.py:645` (paridad de `acct()`). La mitad del enunciado que se sostiene es esa; los números, no |
| 2 | El map-reduce procesa cada trozo a ciegas | **PARCIAL** | La mecánica es real (`server.py:913-981`: ni ventana ni glosario). **El síntoma NO se reproduce**: `local_translate` sobre 14.222 chars, `chunks=8`, `ok=true` en el log; los tres términos ambiguos salen **idénticos en las cuatro secciones**. Además el enunciado mezcla `_chat_map_reduce` (resumir) con `_chat_chunked` (traducir), que son funciones distintas |
| 3 | La telemetría de hooks está desconectada | **PARCIAL** | (a) **FALSO**: `LD_HOOK_TELEMETRY_LOG` **sí** está en el `env` de `~/.claude/settings.json`. (b) **FALSO**: `record()` escribe — 1608 eventos (405/772/431 el 29/30/31 de julio), 1493 `PreToolUse` + 115 `UserPromptSubmit`, **283 sugerencias (17,6 %)**. (c) **CIERTO**: `metrics.py` no menciona `telemetry` ni `hook` |
| 4 | El instalador nunca se ha ejecutado en macOS | **no auditable aquí** | Sin Mac, cualquier conclusión sería otra hipótesis. El procedimiento contra HOME simulado **sigue existiendo y es correcto**: `scripts/dev/README.md:54-61` |
| 5 | `docs/recipes/update_agents.py` mal colocado | **OBSOLETO** | El fichero **no existe**; `docs/recipes/` solo tiene `.md`. Lo cerró el PR #82 (`install --agents`) |
| 6 | Re-medir el piloto A/B de hooks | **PARCIAL / desbloqueado** | La premisa «no hay datos porque nadie enciende el log» es **falsa**: hay 3 días. Lo que falta es el brazo B — `LD_HOOK_READ_ENABLED` **no** está definida en ningún ámbito |
| 7 | Que `--dry-run` enseñe el comando literal | **CONFIRMADO (S)** | El dry-run decía «registra 2 hook(s): UserPromptSubmit, PreToolUse/Bash» y «registra el servidor MCP (http)», sin el string. **ARREGLADO** en este change |
| 8 | Los PNG de la marca pueden quedarse viejos | **CONFIRMADO (L)** | Hoy están al día por fecha (PNG 17:04 > SVG 16:03 del 30-jul), pero **nada lo ata**: `test_site.py:297-353` comprueba que existen, que son PNG y que están declarados — ningún check compara con el SVG |
| 9 | Ruido de logs `401` al arrancar | **CONFIRMADO y reencuadrado (crítico)** | No es ruido: es **la delegación rota**. Ver abajo |
| 10 | Sincronizar la wiki nativa sigue siendo manual | **CONFIRMADO (M)** | `scripts/release.py` no menciona «wiki»; ningún workflow la toca (`pages.yml` solo publica `site/`) |
| 11 | El amarillo del botón de idioma | **OBSOLETO** | `site/index.html:213-215`: el activo invierte (`--ink`/`--paper`), sin amarillo. Lo cerró el PR #88, y el propio backlog lo anunciaba arriba sin borrar la entrada |
| 12 | El recibo como feature del dashboard | **no es un pendiente** | Idea sin diseñar; sale del backlog a la lista de ideas |
| 13 | `clients.jsonl` crece sin techo | **PARCIAL** | Creado hoy 16:00:38; **1 línea, 144 bytes**. El mecanismo es real, el ritmo lo hace irrelevante: ~7000 arranques para 1 MB |
| 14 | Tras `update` quedan dos procesos `serve` | **FALSO** | pid **50008 es el padre de 36200**: `.venv\Scripts\pythonw.exe` es el trampolín de `uv` que relanza el intérprete real y espera (de ahí 1 MB). Confirmado por `ParentProcessId` y por el `.ps1` de la tarea. Y el singleton **sí cierra al perdedor** (`daemon.py:176-183`, `return 0`) |
| 15 | El CI post-merge de `main` quedó `cancelled` | **CONFIRMADO (M)** | No fue solo la 0.18.0: **dos** runs `cancelled` hoy (`30654961990`, `30652987094`), los dos con `test (windows-latest) → cancelled` y los otros seis jobs en `success` |
| 16 | Cómo pinta la pregunta de `elicitation` | **no auditable aquí** | Necesita tty |
| 17 | El observador de clientes solo se probó con stdio | **MEDIDO Y CERRADO** | Cliente MCP propio contra `http://127.0.0.1:9393/mcp`: `local-delegate 0.18.1`, protocolo `2025-11-25`, 11 tools; y **queda registrado** — `clients.jsonl` recoge `mcp 0.1.0` |
| 18 | El lunes 3-ago: ¿Dependabot sube `mcp`? | **OBSOLETO** | El experimento ya no es posible: `pyproject.toml:26` dice **`mcp>=2,<3`** desde la 0.13.0, así que la condición («techo `<2` con 2.0.0 publicada») desapareció. Dependabot corre los lunes sin `ignore`, y su último PR es del 2026-07-28 |

## Evidence — hallazgos nuevos, que no estaban en el backlog

| # | Hallazgo | Evidencia |
| --- | --- | --- |
| N1 | **Las tools `local_*` llevaban un día devolviendo `401`** | `local_translate` real → `[local-delegate error] llama31-8b respondió 401`. `local_status` → «Backend: **CAÍDO**». `usage-202607.jsonl`: último `ok:true` el **2026-07-30 09:36**. `9292/v1/models` sin credencial → **401**; el daemon (`/api/backend`) → `available: true`, 5 modelos. La entrada MCP es **`stdio` + `uvx` sin bloque `env`** y `LOCAL_DELEGATE_API_KEY` **no existe** en ningún ámbito. Y `doctor` daba **todo `[ OK ]`** |
| N2 | **El 9393 está publicado en la tailnet, sin autenticación** | `tailscale serve status`: `https://own-pc.tail63ab6b.ts.net:9393 → 127.0.0.1:9393`, además del 9292. El 9292 exige key; el 9393 no, y su `/mcp` sí puede usar el backend |

## Evidence — requisitos

| Requisito | Comprobación | Resultado | Evidencia |
| --- | --- | --- | --- |
| REQ-001 | 18 puntos auditados por ejecución | cumplido | tabla de arriba; 4 obsoletos/falsos, 5 parciales, 6 confirmados, 3 no auditables |
| REQ-002 | `doctor` contra la avería real | cumplido | `[WARN] credencial del backend: el backend exige credencial y Claude Code y Codex hablan por stdio sin ella: sus tools local_* responderán 401` |
| REQ-003 | el arreglo ofrecido no escribe el secreto | cumplido | `CREDENTIAL_HINT` propone `--mcp-mode http`; `--api-key-env` se descarta **en el código** porque reenvía una variable del mismo entorno vacío |
| REQ-004 | `install --dry-run` con el literal | cumplido | imprime `UserPromptSubmit: "python \"…/suggest_delegate_prompt.py\""` y el JSON/TOML de la entrada MCP |
| REQ-005 | backlog reescrito | cumplido | `projects/local-delegate/backlog.md` en el vault |

## Verificar los tests al revés

| Mutante | Qué rompe | Quién lo caza |
| --- | --- | --- |
| 1 | `ciegas` ignora el modo de la entrada | `test_credencial_warn_…` → `assert 'ok' == 'warn'` |
| 2 | preguntar por `backend_models` (el camino del daemon) en vez de `backend_needs_key` | `test_credencial_warn_…` **y** `test_credencial_unknown_…` → `assert 'ok' == 'unknown'`, porque `backend_models` nunca devuelve `None` y se pierde el «no se pudo preguntar» |

El mutante 2 es exactamente el error de diseño que motivó el check, y la suite lo caza por dos vías.

## Quality checks

- [x] Project-native tests pass. **568 passed, 1 skipped** (562 de partida + 6 nuevos)
- [x] Lint, formatting y build. `ruff check .` → *All checks passed*; `ruff format --check .` → 61
      ficheros; `extract_dashboard_js.py` + `node --check` → exit 0
- [x] Secret scanning. gitleaks en pre-commit; y el secreto no se escribe ni se imprime en ningún
      camino nuevo — el aviso nombra la variable, nunca su valor
- [x] No unrelated changes are present.

## Deviations and residual risk

- **El punto 4 y el 16 no se auditaron**: sin Mac y sin tty, cualquier veredicto sería otra
  hipótesis disfrazada. Se marcan como no auditables, no como pendientes vivos.
- **El entorno de `doctor` es un testigo, no una prueba** del entorno del cliente. Alguien que lance
  Claude Code desde una consola con la variable cargada verá un `warn` que no le aplica. Se asume: el
  aviso nombra el síntoma comprobable en vez de afirmar que la máquina está rota, y el falso positivo
  es mucho más barato que el falso negativo que se pagó hoy.
- **El cambio de configuración de esta máquina lo ejecuta el usuario** (el clasificador bloqueó el
  comando), así que la comprobación de que el 401 desaparece queda para después de que lo corra y
  reinicie los clientes.
- **Confirmados y NO arreglados**, con tamaño: PNG de marca atados al SVG (L), sincronizar la wiki
  nativa (M), cubrir el `cancelled` del CI (M), y el bearer del 9393 (L, cubre dos apps). Se dejan
  propuestos enteros antes que empezados a medias.
