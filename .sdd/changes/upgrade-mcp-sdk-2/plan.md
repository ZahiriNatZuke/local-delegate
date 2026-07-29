# Implementation plan: Analisis del upgrade al SDK mcp 2.x: ajuste de lo implementado y mejoras aprovechables

## Approach

**Una rama larga (`feat/mcp-sdk-2`) con PRs pequeños dentro**, no un PR gigante. `main` sigue
publicando 0.12.x sobre `mcp` 1.x mientras tanto, así que un fallo urgente se puede sacar sin
arrastrar la migración a medias.

El orden lo manda una regla: **primero equivalencia, después capacidades**. La fase 1 no añade
nada; su éxito se mide en que *nada cambia* salvo `serverInfo.version`, que hoy está mal. Solo
cuando eso esté verde entran las features. Si se mezclara, una regresión no diría si viene del SDK
nuevo o de una capacidad nueva — y con `httpx2` sustituyendo a `httpx` en el camino del backend,
esa ambigüedad sería cara.

Las features no entran por estar disponibles: **cada una tiene que cerrar una deuda ya apuntada**
en `projects/local-delegate/backlog.md`. Las que no cierran ninguna se quedan fuera y se anotan.

## Ordered tasks

### Fase 0 — Rama y línea base

1. **Rama de trabajo y foto del estado actual**
   - Files or modules: —
   - Requirements covered: base de comparación
   - Verification: `git switch -c feat/mcp-sdk-2` desde `main`; guardar la salida de `pytest -q`
     (233), el handshake actual y el depscore vigente (100/100/99/96/100) como línea base
   - Rollback or recovery: borrar la rama

### Fase 1 — Equivalencia sobre 2.x (sin capacidades nuevas)

1b. **Spike de viabilidad de `httpx2` — antes de tocar nada** *(hallazgo F1 de la revisión)*
   - Files or modules: ninguno del repo; entorno desechable
   - Requirements covered: valida REQ-011 antes de comprometerse
   - Verification: en un entorno con `httpx2` y **sin `httpx`**, comprobar que
     (a) `fastapi.testclient.TestClient` arranca y sirve una app Starlette — hoy se usa en **~22
     puntos** de `test_metrics.py` y `test_daemon.py`, que cubren dashboard y daemon;
     (b) `httpx2.MockTransport` sustituye lo que hace `respx` en un test representativo;
     (c) el cliente del backend funciona contra el backend local real
   - Rollback or recovery: si (a) falla, **parar y volver al usuario**: la decisión de una sola
     librería HTTP habría que revisarla, no forzarla
   - Por qué: Starlette implementa `TestClient` sobre `httpx`. Que la suite avise hoy
     `install httpx2 instead` es un **indicio** de que ya lo soporta, no una prueba.

2. **Dependencias: `mcp>=2,<3` y `httpx2` en lugar de `httpx`**
   - Files or modules: `pyproject.toml`, `uv.lock`
   - Requirements covered: REQ-004, REQ-011
   - Verification: `uv lock` resuelve; **`httpx` no aparece en `uv.lock`** y `uv pip tree` no lo
     muestra bajo ninguna rama
   - Rollback or recovery: revertir las dos líneas
   - Nota: el techo **no se elimina**, se sube. La lección de la 0.12.1 es que un rango sin techo es
     una bomba, no que ese techo concreto sobrara.

3. **`server.py`: `MCPServer` y la versión propia**
   - Files or modules: `src/local_delegate/server.py:32,36`
   - Requirements covered: REQ-001, REQ-002
   - Verification: el handshake devuelve la **versión del paquete**, no la del SDK — lo comprueba
     `scripts/check_install_handshake.py`, que hoy imprime la del SDK
   - Rollback or recovery: revertir el import y el constructor

4. **`daemon.py`: la ruta como argumento**
   - Files or modules: `src/local_delegate/daemon.py:116-117`
   - Requirements covered: REQ-003
   - Verification: el daemon sirve el MCP en `http://127.0.0.1:9393/mcp` y el dashboard sigue
     montado en la raíz
   - Rollback or recovery: revertir
   - Detalle: `settings.streamable_http_path` ya no existe; pasa a
     `streamable_http_app(streamable_http_path=MCP_PATH)`.

5. **Cliente del backend: `httpx` → `httpx2`**
   - Files or modules: `src/local_delegate/server.py` (cliente y manejo de errores), `web/sysinfo.py`
     y `daemon.py` si tocan `httpx`
   - Requirements covered: REQ-011
   - Verification: delegación real contra el backend local (no un mock) en al menos tres tools de
     familias distintas: texto (`local_summarize`), código (`local_explain_code`) y visión
     (`local_describe_image`)
   - Rollback or recovery: revertir; es el punto más delicado de la fase
   - Riesgo: cambian los nombres de las excepciones (`httpx.HTTPError` → equivalente en `httpx2`).
     El manejo de errores del cliente es lo que degrada con gracia cuando el backend no está: si se
     traduce mal, el fallo aparece como una excepción cruda en vez de un aviso.

6. **Suite: `respx` → `httpx2.MockTransport`**
   - Files or modules: `tests/test_core.py` (58), `test_metrics.py` (23), `test_chunking.py` (18),
     `test_vision.py` (14), `test_map_reduce.py` (9); `pyproject.toml` (quitar `respx` de dev)
   - Requirements covered: REQ-005, REQ-012
   - Verification: **233 tests o más**, y ni uno menos. Un test borrado por incómodo es cobertura
     perdida, no un test migrado
   - Rollback or recovery: la fase 1 entera se revierte junta
   - Nota: es la tarea más larga de la migración. Conviene hacerla fichero a fichero, con la suite
     en verde entre uno y otro.

7. **Verificación de equivalencia**
   - Files or modules: —
   - Requirements covered: REQ-005, REQ-006
   - Verification: las **11 tools** ejecutadas contra el backend local real, comparando con la línea
     base de la tarea 1; `install-smoke` en verde con 2.x; los cuatro pasos del CI con `.`
   - Rollback or recovery: —

8. **Dependencias: medir y documentar**
   - Files or modules: `docs/wiki/` o `SECURITY.md`
   - Requirements covered: REQ-013
   - Verification: depscore del paquete con 2.x comparado con la línea base; **`pywin32` documentado
     como dependencia heredada del SDK** (license 70, supplyChain 73) que el proyecto no eligió
   - Rollback or recovery: —
   - Nota: si el `supplyChain` del paquete cae de forma marcada, es motivo para **parar y
     reconsiderar**, no para seguir porque el trabajo ya está hecho.

### Fase 2 — Lo que la migración regala (PR aparte, tras la fase 1 verde)

9. **`annotations` en las 11 tools**
   - Files or modules: `src/local_delegate/server.py`
   - Requirements covered: REQ-007
   - Verification: el cliente recibe las anotaciones; las tools quedan marcadas como de solo
     lectura, que es la verdad — ninguna es destructiva
   - Rollback or recovery: revertir

10. **`structured_output` en `local_extract`**
    - Files or modules: `src/local_delegate/server.py`
    - Requirements covered: REQ-008
    - Verification: el cliente recibe un objeto validado en vez de JSON dentro de una cadena
    - Rollback or recovery: revertir
    - **Deuda que cierra:** hoy `local_extract` devuelve JSON como texto y quien llama lo parsea.

11. **`title`, `description` y `website_url` del server**
    - Files or modules: `src/local_delegate/server.py`
    - Requirements covered: REQ-009
    - Verification: presentación correcta en el cliente
    - Rollback or recovery: revertir

### Fase 3 — Deuda técnica del backlog, una por cambio SDD

Ninguna entra en esta rama sin su propio análisis. Se listan con **la deuda concreta que cierran**:

12. **OpenTelemetry** → *«la contabilidad del chunking sesga las métricas»* y *«la telemetría de
    hooks sigue desconectada del dashboard»*. Es la deuda **más gorda** que 2.x puede atacar: hoy N
    llamadas al backend se registran como **un** evento con `chunks: N`, y el prompt de sistema
    viaja N veces sin aparecer en ningún sitio. Con spans por llamada real, el dashboard podría
    distinguir por fin una delegación eficiente de una que quemó la GPU 16 veces. `opentelemetry-api`
    ya entra como dependencia obligatoria del SDK, así que el coste de adoptarlo es **cero**.
13. **`middleware`** → el backpressure y los guardrails están cosidos a mano dentro de `_run_chat`.
    Sacarlos a un middleware los quita del camino feliz.
14. **Elicitation** → la *política de capacidad dinámica* del proyecto dice consultar VRAM/RAM antes
    de montar un modelo. Hoy eso depende de que el agente se acuerde; con elicitation, la tool puede
    **preguntar** antes de montar un modelo de 14B cuando la VRAM está justa.
15. **`auth` / `TokenVerifier`** → cubre el **MCP HTTP** del daemon, que hoy solo está protegido por
    el bind a loopback. **Ojo: no cubre el dashboard**, que es lo que dice el backlog; el dashboard
    es una app Starlette aparte. Adoptarlo mejora la mitad del problema, y hay que decirlo así.

**Descartadas por ahora, anotadas para no re-descubrirlas:** `cache_hints` (los listados de tools no
son un cuello de botella aquí), `subscriptions` (el dashboard sondea y funciona), `extensions` (11
tools en un módulo no piden agruparse), `request_state_security` (no hay estado entre peticiones que
sellar).

### Fase 4 — Publicación

16. **Release de la versión mayor de la migración**
    - Files or modules: `CHANGELOG.md`, versión
    - Requirements covered: —
    - Verification: `scripts/release.py X.Y.Z --dry-run` y luego real, **con confirmación explícita
      del usuario**
    - Rollback or recovery: PyPI es inmutable; un error obliga a otra versión
    - **Calendario:** no publicar hasta que el SDK tenga al menos un patch (2.0.1+) o unas semanas
      de rodaje. 2.0.0 se publicó el mismo día que rompió la 0.12.1.

## Test strategy

- **Unit:** los 233 existentes, migrados a `MockTransport`. **El número no baja.**
- **Integration:** `install-smoke` con resolución libre y `mcp` 2.x; handshake real.
- **End-to-end o manual:** las 11 tools contra el backend local **de verdad** — con `httpx2` en el
  camino del backend, un mock no prueba que la conversación con llama-swap siga funcionando.
- **Compatibilidad de clientes:** Claude Code y Codex conectados al daemon, no solo un script.
- **Seguridad:** `gitleaks` como siempre; depscore antes y después, con `pywin32` vigilado.

## Migration and compatibility

- **`main` sigue en 1.x** durante toda la migración. Un fix urgente sale de `main` sin tocar la rama.
- **Rebase periódico** de `feat/mcp-sdk-2` sobre `main` para no acumular divergencia.
- **El daemon de Windows** se actualiza como siempre (`uv sync` + reinicio de la tarea). Es donde
  entra `pywin32`, así que es el primero que hay que probar.
- **Ruptura para clientes:** si 2.x negocia otro nivel de protocolo, un cliente viejo podría quedar
  fuera. Verificar con los clientes reales antes de publicar.
- **Versionado: minor, `0.13.0`** *(hallazgo F3)*. Cambia el árbol de dependencias de quien instala
  y sube el mínimo de `pydantic`; un patch mentiría sobre el alcance.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.

Pendiente de una revisión adversarial antes de aprobar el gate `plan`.
