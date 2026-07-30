# Verificación — `probar-codex-daemon`

## Entorno

- `main` en `0489246`. Daemon **0.13.1** (SDK `mcp` 2.0.0) en `127.0.0.1:9393`, pid 27032.
- Codex CLI bundled del Desktop (`C:\Users\Yohan\.local\bin\codex.cmd` → build `69066b736e1e17a4`),
  modelo `gpt-5.6-terra`, esfuerzo bajado a `low` para no gastar cuota de más.
- Backend llama-swap local en `127.0.0.1:9292`.

## Resultado: **funciona**

| Req | Comprobación | Resultado |
|---|---|---|
| REQ-001 | `codex mcp get local-delegate` | `transport: streamable_http`, `url: http://127.0.0.1:9393/mcp`, `enabled: true` |
| REQ-002 | `codex exec` con una tarea que necesita `local_classify` | `mcp: local-delegate/local_classify started` → `(completed)` |
| REQ-003 | Log del daemon | evento `local_classify`, `gemma3-4b`, `ok: true`, `tokens_in: 67`, `tokens_out: 3`, `latency_ms: 7516`, `v: 0.13.1` |
| REQ-004 | Dos fallos acotados | ninguno es de local-delegate — abajo |

**De regalo, dos confirmaciones que no se buscaban:**

1. **Codex lee la salida estructurada de la fase 2.** El JS que ejecutó fue
   `r.structuredContent?.result ?? r.content?.map(...)`: va **primero** al `structuredContent` que
   añadió el `output_schema` de la fase 2 de la migración. No es solo que el transporte funcione —
   la anotación de tools también le sirve a Codex.
2. **La contabilidad del PR #48 procesa bien una llamada que no vino de Claude Code:**
   `{backend_calls: 1, tokens_in: 67, tokens_out: 3, saved: 0, estimated: False}`. El `saved: 0` es
   correcto: el texto viajó `inline`, así que no hubo ahorro de contexto que apuntar.

## El `error` que no era un error

La salida de consola de `codex exec` terminaba en `error`, con pinta de fallo. **No lo era: era la
respuesta de la tool.** Clasificó *«el disco duro está lleno»* entre `error / aviso / info` y devolvió
`error`, que es la etiqueta correcta. Se confirmó leyendo el rollout de la sesión
(`~/.codex/sessions/2026/07/30/rollout-…-019fb306-….jsonl`), donde el
`custom_tool_call_output` trae `"output": "error"` con `Script completed`.

Conviene anotarlo: **con `local_classify` la salida de un cliente puede ser indistinguible de un
fallo**, porque la etiqueta *es* la palabra «error».

## Dos hallazgos ajenos a local-delegate

Ninguno se ha tocado: son configuración del usuario, no del repo.

### 1. Estando dentro de `D:\Projects\local-delegate`, Codex no carga NINGÚN MCP

```
Error: failed to load configuration
Caused by: url is not supported for stdio
    in `mcp_servers.github`
```

**Causa raíz, acotada por bisección** (rangos de línea sobre una copia del config en un `CODEX_HOME`
aislado, sin tocar el real): el MCP `github` está definido **dos veces con transportes
incompatibles**:

- `~/.codex/config.toml` → `url = "https://api.githubcopilot.com/mcp/"` (HTTP)
- `D:\Projects\local-delegate\.codex\config.toml` → `command = "npx"` (stdio)

Codex **fusiona** la config del proyecto con la global, la entrada acaba con `command` **y** `url`, y
aborta la carga **entera** — no solo esa entrada. Comprobado por ejecución: el mismo comando falla
desde el repo y funciona desde `C:\`.

No es una regresión de la migración: el `.bak` del 2026-07-29 muestra que lo único que cambió ese día
en el config del repo fue la entrada `git` (el workaround `--with mcp<2`). El choque de `github` ya
existía.

El `.codex/` del repo está en `.gitignore:32`, así que es local de esta máquina y no viaja al
repositorio.

### 2. `rtk` no existe en el shell que usa Codex

Codex intentó `pwsh -Command "rtk read …SKILL.md"` y recibió *«The term 'rtk' is not recognized»*.
Su `AGENTS.md` le indica usar RTK, pero el shim no está en el PATH que hereda. Coste real: un turno y
tokens perdidos por sesión, cada vez que lo intenta.

## Comprobaciones de calidad

- [x] Sin cambios de código del proyecto: solo artefactos SDD.
- [x] La configuración de Codex del usuario **no se modificó**; las pruebas de bisección se hicieron
      sobre una copia en `CODEX_HOME` temporal.
- [x] Sin secretos en los artefactos: no se copió `auth.json` ni se volcaron tokens.

## Riesgo residual

- Se probó **una** tool (`local_classify`, `inline`). No se probó `path` server-side desde Codex, que
  es el modo que da sentido al proyecto; el transporte es el mismo y ya está verificado con Claude
  Code, pero desde Codex no se ha visto.
- No se probó **Codex Desktop** (la app), solo su CLI bundled. Comparten `config.toml`, así que el
  hallazgo 1 probablemente también le afecte al abrir este repo — no comprobado.
