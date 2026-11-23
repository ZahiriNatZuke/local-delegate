# Auditoría: qué falta para cerrar #669, #670 y #671 (Codex nativo)

- Fecha: 2026-11-23, 07:44 hora de Uruguay. Revisión de `main`: `a776da37` (0.53.0), CI de `main` en verde.
- Fuentes: los tres issues (sin comentarios), nota del vault
  `projects/local-delegate/jornada-2026-11-16-diez-issues-y-codex-nativo.md`, memoria
  `cerrar-el-sdd-es-parte-de-terminar.md`, artefactos de los SDD y código de `main`.
- Solo lectura: sin cambios de código, sin cerrar SDD, sin commits. `local-delegate doctor` se corrió
  una vez (solo lectura).

## Hallazgos que cambian el plan

1. **En esta PC los hooks de Codex no están instalados.** `doctor` (0.53.0) dice: «hooks de
   local-delegate en Codex: no instalados en `~\.codex\hooks.json`» y «MCP en Codex: entrada http
   puesta a mano (sin marcadores)» [WARN]. La prueba con Codex real no ha empezado. Codex CLI 0.169.0
   está instalado **en la PC**, así que la prueba se puede hacer aquí; la Mac solo hace falta para
   repetirla allí o para Codex Desktop si solo está en la Mac.
2. **La matriz de capacidades de la wiki está desfasada** (`docs/wiki/Codex-capabilities.md:28-34`):
   la fila «Hooks consultivos» nombra solo `UserPromptSubmit` y `SubagentStart` (ya son cuatro hooks),
   y las filas «Atribución por sesión» y «Lectura automática y guard de escritura» dicen «no disponible
   todavía, se hace en #669/#670», cuando ambas se publicaron en la 0.53.0. El README
   (`README.md:393-407`) y `Integration-install.md:484-543` sí están al día. Esto incumple el criterio
   de #671 «README/recetas/doctor alineados con capacidades reales».
3. Los issues #665, #684 y #687 ya están **cerrados** en GitHub, pero sus SDD siguen abiertos y la
   jornada del 2026-11-16 dejó pendiente su prueba en vivo.

## #669 — Entrega Codex nativa (hooks, instalador, diagnóstico, atribución)

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Adaptador con la forma de hooks real de Codex | hecho | `src/local_delegate/codex_hooks.py:73-80` (`SPECS`: 4 hooks); PR #682 y #686 |
| Cubrir prompts, subagentes, shell, MCP y code mode | hecho (código y fixtures) | `tests/fixtures/codex_hooks/` (bash, apply_patch, mcp, mcp_subagent, code_mode, other_mcp, esquemas oficiales de `rust-v0.169.0`); `tests/test_codex_attribution.py:169,381` |
| install/update/doctor/uninstall, idempotencia, respaldo, coexistencia | hecho | `install.py:2964-2993` (`_uninstall_codex_hooks_action`), `install.py:3528`; `checks.py:1365-1400`; wiki `Integration-install.md:484-543` |
| Controles negativos (matcher equivocado, campos ausentes) | hecho | review deep de `codex-session-attribution` (REQ-002, REQ-005) |
| No generar `trusted_hash` ni saltarse la revisión de confianza | hecho | `checks.py:1396` y `codex_hooks.py:320-335` solo leen `[hooks.state]` |
| Atribución solo con datos observados; desconocido si faltan | hecho en código | `codex-session-attribution/handoff.md` (Decisions); doc en `Savings-and-metrics.md:826` |
| Telemetría global frente a atribución por sesión documentada | hecho | `Integration-install.md` («Telemetría global y atribución por sesión») |
| Falla en abierto con backend caído | hecho (tests) | REQ-003 de #670 y pruebas de `hook_common`; sin prueba real |
| **Codex real: config estricta sin warning, hook que despacha, delegación identificada** | **falta** | REQ-012 «no»; pasos en `codex-session-attribution/handoff.md:41-61`; en la PC ni siquiera están instalados |
| **Capturas del panel claro/oscuro (columna «Codex»)** | **falta** | REQ-008 «partial», hallazgo F4 de `review.md` |
| Checks distinguen configurado, cargado y probado | hecho en `doctor` (aprobados N de 4 + hora de despacho) | `Integration-install.md:526-530` |

Esfuerzo: capturas del panel ~15 min de agente (navegador headless, con cerrojo y máquina tranquila);
prueba real ~30 min de Yohan (aprobar en `/hooks`) más ~15 min de agente para revisar el log de uso;
cierre del SDD ~10 min.

## #670 — Resumen de lecturas y guard de escritura

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Vía técnica investigada y documentada (deny de `PreToolUse`) | hecho | `codex-read-summary-write-guard/handoff.md` (Decisions); wiki `Integration-install.md:545-` |
| Prosa grande, código, rangos y acumulada, shell, MCP, `apply_patch` | hecho con fixtures | `verification.md` REQ-002..REQ-007; `tests/test_codex_reads.py` |
| Resumen inválido o backend caído → la lectura real pasa | hecho (tests) | REQ-003 |
| Guard hasta lectura literal; alcance por agente; sobrevive a otro proceso | hecho (tests) | REQ-005, REQ-006 |
| Sin secretos en estado/logs | hecho (tests) | REQ-009 |
| **Prueba real con centinela** (el original no entra al contexto; `apply_patch` rechazado y levantado; daemon parado; forma del `command` en Windows) | **falta** | `verification.md` «Deviations»; wiki `Integration-install.md:592` |
| **Revisión de resultado deep** (2 jueces + seguridad) | **falta** | `review.md` es la plantilla con TBD |
| Puerta `quality` | falta aprobarla | el CI completo del PR #686 ya está en verde: es la evidencia |

Esfuerzo: revisión deep ~1 h de agentes (2 jueces + revisor de seguridad, en serie por la RAM);
prueba real ~30 min de Yohan; cierre ~15 min.

## #671 — Matriz de capacidades

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| Tabla por superficie con estados implementado/configurado/cargado/probado/no disponible | hecho, **pero desfasada** | `docs/wiki/Codex-capabilities.md:13-34` (ver hallazgo 2) |
| Contraste con la fuente y runtime de Codex CLI | hecho | `verification.md` REQ-004 (`codex debug prompt-input`: 11 tools encendidas, 0 apagadas) |
| Alternativa para tools fijadas (`--codex-direct-tools`) | hecho | `tests/test_codex_direct_tools.py`; README `:484-493` |
| Comandos sin modelo y barra de estado declarados «no disponible» con fuente | hecho | `Codex-capabilities.md:83-113` |
| **Codex Desktop** | **falta** | `Codex-capabilities.md:114-121`, punto 5 |
| **Prueba en vivo de tools directas** | **falta** | mismos pasos 1-4 |
| Tarjeta de seguimiento «subcomando de CLI para `!` en Codex» | falta comprobar/crear en Project 3 | `codex-capability-matrix/handoff.md:225` |

Esfuerzo: actualizar la matriz ~20 min de agente (más `tests/test_wiki.py` con cerrojo); prueba en
vivo CLI ~10 min y Desktop ~10 min de Yohan; cierre ~5 min.

## Los cinco SDD abiertos

`personal-harness sdd check` (solo lectura) sobre cada uno; ninguno salta estados, así que la cadena va
entera. Todos avisan `commands-undeclared` (sin `.sdd/project.json`), que no bloquea.

| SDD | Estado | Check | Paso que falta y comandos |
| --- | --- | --- | --- |
| `codex-session-attribution` (#669) | result-review | ok | capturas + prueba real; luego `sdd approve codex-session-attribution conformance --evidence "<capturas y prueba Codex>"` → `sdd transition codex-session-attribution closing --reason "<...>"` → `sdd approve codex-session-attribution memory --evidence "<nota del vault>"` → `sdd transition codex-session-attribution closed --reason "<...>"` |
| `codex-read-summary-write-guard` (#670) | verifying | ok, 3 warnings de `review.md` | `sdd approve codex-read-summary-write-guard quality --evidence "CI completo del PR #686 en verde (0.53.0)"` → `sdd transition ... result-review` → rellenar `review.md` (deep) → prueba real → `approve ... conformance` → `transition ... closing` → `approve ... memory` → `transition ... closed` |
| `codex-capability-matrix` (#671) | closing | ok | `sdd approve codex-capability-matrix memory --evidence "<nota>"` → `sdd transition codex-capability-matrix closed --reason "<...>"` (antes, arreglar la matriz desfasada, o hacerlo en un cambio aparte) |
| `summarize-test-totals-negation` (#684) | verifying | ok, 3 warnings de `review.md` | prueba en vivo de `local_summarize` sobre salida de pytest; `approve ... quality --evidence "CI del PR #686"` → `transition ... result-review` → `review.md` (lite: standard, 2 jueces) → `approve conformance` → `closing` → `approve memory` → `closed` |
| `extract-diff-files-names` (#665) | result-review | **3 errores**: `review.md` en plantilla (level, security, verdict) | rellenar `review.md` (2 jueces) + prueba en vivo de `local_extract` sobre un `.patch` grande → `approve ... conformance` → `closing` → `approve memory` → `closed` |

Todos los comandos llevan el prefijo `personal-harness`.

## Plan para cerrar hoy

**Sin Codex real (agentes; máximo 2 con código a la vez, pesados con `pesado.sh`):**

1. Agente A (~20 min): poner al día `docs/wiki/Codex-capabilities.md` (cuatro hooks; atribución y
   lectura como «implementado, configurado», «probado» solo tras la prueba real) y correr
   `tests/test_wiki.py`. PR pequeño.
2. Agente B (~1 h): revisión de resultado deep de `codex-read-summary-write-guard` y revisión standard
   de `extract-diff-files-names` y `summarize-test-totals-negation`; rellena los tres `review.md`.
3. Agente C, con la máquina tranquila (~15 min): capturas claro/oscuro del panel con
   `scripts/dev/capture_dashboard.py`.
4. Agente D (~20 min): pruebas en vivo de #684 y #665/#687 contra el daemon, marcadas con
   `test-window`.
5. Sesión principal: `local-delegate install --clients codex` en la PC (deja los hooks y la entrada MCP
   con marcadores; lo puede hacer el agente, no necesita a Yohan) y crear la tarjeta del `!` en
   Project 3.

**Con Codex real (Yohan; en la PC, que ya tiene Codex 0.169.0; la Mac solo para repetir o para
Desktop):** ~45 min en total.

1. `/hooks` en Codex: aprobar los cuatro; `doctor` debe decir «aprobados: 4 de 4».
2. #669: delegación en el hilo principal, desde un subagente y desde code mode; un agente revisa los
   campos del log de uso (`tool_use_id`, `caller_session_key`, `caller_src: codex-hook`,
   `caller_model`, `caller_kind`).
3. #670: centinela en un `.md` grande, `apply_patch` rechazado y luego levantado con un tramo literal,
   daemon parado (la lectura pasa).
4. #671: `install --clients codex --codex-direct-tools`, ver que el modelo llama a `local_summarize`
   sin `tool_search`, y repetirlo en Codex Desktop.

**Cierre:** las cadenas de puertas de la tabla anterior, comentario de evidencia en cada issue, cerrar
#669/#670/#671, tarjetas a «Hecho» y nota del vault (puerta `memory`). Total aproximado: ~3 h de
agentes en serie por recursos + ~45 min de Yohan.

## Nota sobre `local-delegate`

En este encargo las tools `local_*` no estaban disponibles (ToolSearch no encontró ninguna), aunque el
hook de lectura siguió recomendando cargarlas. Llamadas `local_*` hechas: 0. Los artefactos leídos
eran pequeños (menos de 8 KB) y se leyeron por rangos.
