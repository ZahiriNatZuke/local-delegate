# Implementation plan: observar qué declara cada cliente MCP

## Approach

Un módulo nuevo, `src/local_delegate/clients.py`, con un **`ServerMiddleware`** que se engancha
pasando `middleware=[...]` a `MCPServer` (`server.py:55`). El middleware corre en todo mensaje
inbound, antes de validar params, y lee del contexto tres cosas ya en memoria:
`ctx.session.client_capabilities`, `ctx.session.client_params` y `ctx.protocol_version`.

Tres decisiones de diseño con su motivo, porque ninguna es obvia:

**1. Se salta `initialize`.** Está medido que ahí `client_capabilities` y `client_params` son
`None`: el middleware corre antes del commit del handshake. Registrar desde `initialize` no
registraría nada. El primer mensaje útil es `notifications/initialized`.

**2. El dedupe es por identidad declarada, no por conexión.** El SDK no expone la `Connection` por
API pública desde `ServerRequestContext` (solo `session`, y `ServerSession` no publica ni
`session_id` ni `connection`). Depender de `session._connection` sería atarse a un privado del SDK
—el mismo error que costó la migración a 2.x—. La clave es
`(nombre, versión, protocolo, capabilities ordenadas)`: si un cliente reconecta con lo mismo, es el
mismo dato y no interesa una línea nueva; si cambia de versión o de capabilities, sí lo es.
**Consecuencia aceptada y escrita en la spec:** dos instancias idénticas del mismo cliente cuentan
como una.

**3. Hay lock de verdad, no confianza en el event loop.** El estado en memoria lo lee `/api/status`,
que es un endpoint **síncrono** de FastAPI y por tanto corre en el threadpool de uvicorn, en otro
hilo que el loop del MCP. No es concurrencia de corrutinas: es concurrencia de hilos. Sin lock,
dos mensajes simultáneos podrían escribir dos líneas para la misma identidad.

**Precisado tras la revisión adversarial (`plan-review.md`), porque «hay lock» no bastaba:**

- La sección crítica cubre **comprobar + escribir la línea + añadir al dict**, las tres como una
  sola operación. Si el lock solo envolviera el `dict`, dos corrutinas que comprueban antes de que
  ninguna añada escribirían **dos líneas** para la misma identidad, que es justo lo que REQ-003
  prohíbe. Implica hacer una escritura a disco con el lock tomado: aceptable **porque ocurre una
  vez por identidad, no por mensaje**, y va comentado en el código como decisión.
- `snapshot()` construye una estructura **nueva y desligada dentro del lock**. Devolver el dict
  interno —o una copia superficial— dejaría que el serializador JSON lo recorriera fuera del lock
  mientras el middleware lo muta: `/api/status` fallaría de forma intermitente.

**4. Si no hay capabilities ni `client_info`, no se registra.** El caso simétrico de REQ-006: una
identidad `(None, None, protocolo, ())` no informa de nada y contaminaría el experimento de
`elicitation` con una línea de ruido.

## Ordered tasks

1. **Módulo observador**
   - Files: `src/local_delegate/clients.py` (nuevo)
   - Contenido: `_Identidad` (dataclass congelada), `_VISTOS` con `threading.Lock`,
     `nombres_capabilities(caps)`, `observar_cliente(ctx, call_next)` (el middleware),
     `snapshot()` (lo que consume `/api/status`), `reset()` (para los tests).
   - Ruta del log: `config.LOG_DIR / "clients.jsonl"`, leída **en tiempo de llamada** — no
     capturada en un default de módulo, que no se dobla con monkeypatch.
   - Requirements: REQ-001, REQ-002, REQ-003, REQ-005, REQ-006
   - Verification: `tests/test_clients.py`
   - Rollback: quitar el fichero y el argumento `middleware=`; nada más lo referencia.

2. **Enganche en el servidor**
   - Files: `src/local_delegate/server.py` (solo la llamada a `MCPServer`, +import)
   - Requirements: REQ-001
   - Verification: test end-to-end que monta el `MCPServer` real y conecta un `ClientSession` real
     por streams en memoria (la sonda del research, convertida en test).
   - Rollback: quitar el argumento.

3. **Estado en vivo en `/api/status`**
   - Files: `src/local_delegate/web/metrics.py` (clave `clients`, aditiva)
   - Requirements: REQ-004
   - Verification: test del endpoint con el registro poblado.
   - Rollback: quitar la clave; ningún consumidor la exige.

4. **Tests**
   - Files: `tests/test_clients.py` (nuevo)
   - Requirements: todos
   - Cada test se **verifica al revés**: se comprueba que falla con el defecto puesto antes de
     darlo por bueno.

5. **Documentación**
   - Files: `CHANGELOG.md` (`Unreleased`), `README.md` y wiki **solo si aplica** — decidir leyendo,
     no por reflejo: es un dato de diagnóstico, no una tool nueva.
   - `CHANGELOG.md` es CRLF: se edita con la herramienta de edición, nunca con here-strings.

6. **Medición en vivo** (es el propósito del change, no un extra)
   - Conectar **Claude Code** y **Codex** al daemon con este código y leer `clients.jsonl`.
   - Resultado esperado del experimento: saber si alguno declara `elicitation`.
   - Queda en `verification.md` con la salida real pegada.

## Test strategy

- **Unit**: `nombres_capabilities` con capabilities ausentes, `{}` y con campos declarados;
  `_Identidad` como clave de dict.
- **Integration**: `MCPServer` real + `ClientSession` real por streams en memoria (patrón medido en
  el research, ya ejecutado con éxito). Cubre:
  - `initialize` no registra (REQ-002) — el test asevera sobre el fichero, no sobre un log.
  - veinte mensajes → una línea (REQ-003).
  - dos clientes con versión distinta → dos líneas (REQ-001).
  - `client_info=None` → registra con nombre desconocido y sin excepción (REQ-006).
  - ni capabilities ni `client_info` → **no** registra (REQ-007).
  - **fallo de escritura → la llamada a la tool responde igual (REQ-005).** Se dobla la función de
    escritura para que lance; **no** se juega con permisos del sistema de ficheros, porque en
    Windows `chmod` no los aplica como en POSIX y el test sería inútil justo en el runner donde
    este repo ya se ha equivocado antes. Doblar el destino mide el contrato y mide lo mismo en los
    tres sistemas.
- **End-to-end / manual**: tarea 6, con Claude Code y Codex reales contra el daemon.
- **Security**: `clients.jsonl` no debe contener headers, tokens ni rutas. Test que asevera que la
  línea escrita tiene **exactamente** el conjunto de claves esperado, no «al menos» — así un campo
  añadido por descuido rompe el test.

## Migration and compatibility

- Fichero nuevo en `LOG_DIR`; no toca `usage.jsonl` ni su formato.
- `/api/status` gana una clave; el JS del dashboard no la consume todavía y no se rompe.
- Sin dependencias nuevas, sin variables de entorno nuevas.
- Sin migración de datos: el fichero se crea al primer cliente observado.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback — no hay destructivas; el único
      efecto es un fichero nuevo de solo escritura por anexado.
- [x] Dependencies and configuration changes are explicit — ninguna nueva.
- [x] The plan does not include unrelated work — el check de `doctor` queda fuera por decisión
      explícita del usuario.
