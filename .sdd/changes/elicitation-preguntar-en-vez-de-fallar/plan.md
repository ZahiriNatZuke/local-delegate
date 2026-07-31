# Implementation plan: que una tool pregunte en vez de fallar seco

## Approach

Un módulo nuevo, `src/local_delegate/preguntas.py`, con una función `preguntar(...)` que devuelve la
respuesta del usuario **o `None`** cuando no se pudo preguntar, no contestaron, dijeron que no o
falló algo. Toda la complejidad —capability, canal, plazo, excepciones— queda ahí; los puntos de
uso solo ven «me dieron una respuesta o no».

Cuatro decisiones, las cuatro apoyadas en medición (`research.md`):

**1. El contexto viaja por `ContextVar`, no por firmas.** `_post_chat` está tres capas por debajo de
la tool y las 11 tools son síncronas. Pasar el `ctx` por parámetro obligaría a tocar 15 firmas.
Medido que un `ContextVar` puesto por un `ServerMiddleware` **sí se ve** desde la tool síncrona
(anyio copia el contexto al hilo del threadpool). Consecuencia: **REQ-009 se cumple por
construcción**, porque no se cambia ninguna firma.

**2. Una tool síncrona sí puede preguntar.** Medido: `anyio.from_thread.run(ctx.elicit, ...)`
funciona desde el hilo del threadpool. No hay que convertir nada a async.

**3. El plazo es obligatorio, no una precaución, y va DENTRO de la corrutina.** Medido que un
cliente que declara `elicitation` y no contesta **cuelga la tool para siempre**: el SDK no impone
timeout. Y medido también —tras la revisión adversarial— que la forma ingenua de ponerlo **no
existe**: un `anyio.move_on_after` alrededor de `from_thread.run` lanza `NoEventLoopError` al
instante, porque desde el hilo del threadpool no hay event loop que consultar. El plazo tiene que ir
**dentro del wrapper async** que cruza al loop:

```python
async def _con_plazo():
    with anyio.move_on_after(config.ASK_TIMEOUT):
        return await ctx.elicit(mensaje, Modelo)
    return None

respuesta = anyio.from_thread.run(_con_plazo)   # vuelve sola al agotarse
```

**4. Middleware propio, separado del observador, y el orden se fija a propósito.** `clients.py`
observa; `preguntas.py` habilita preguntar. Son dos responsabilidades. El SDK los lista
**outermost-first**: va primero el observador y después el de preguntas —«observar primero,
habilitar después»—. Hoy son independientes; el orden se fija para que nadie lo cambie creyendo que
da igual.

## Ordered tasks

1. **Config**
   - Files: `src/local_delegate/config.py`
   - `LOCAL_DELEGATE_ASK` (default **activado**: preguntar es más seguro que fallar, y el usuario
     siempre puede decir que no) y `LOCAL_DELEGATE_ASK_TIMEOUT` (default **30 s**).
   - Requirements: REQ-008

2. **Módulo `preguntas.py`**
   - `CTX_ACTUAL: ContextVar`, el middleware que lo puebla, `puede_preguntar(ctx)` (capability **y**
     canal, por separado), `preguntar(mensaje, Modelo)` con plazo y `try/except` envolvente.
   - Requirements: REQ-005, REQ-006, REQ-007, REQ-009
   - Rollback: quitar el middleware; los puntos de uso degradan solos porque ya tratan `None`.

3. **Enganche en el servidor**
   - Files: `src/local_delegate/server.py` (lista de `middleware=`)
   - Requirements: REQ-001

4. **Caso 1 — backend caído**
   - Files: `server.py`, dentro del `except httpx2.ConnectError` de `_post_chat` (línea ~524)
   - Tras agotar el camino de `AUTOSTART`, preguntar; si dicen que sí, `autostart.ensure_backend` y
     reintentar **una** vez. Si no, el `ChatResult` de error de hoy, **sin cambiar su texto**.
   - Requirements: REQ-001, REQ-002

5. **Caso 2 — modelo inválido**
   - Files: `server.py`, la validación de `model` (~1324)
   - Ofrecer los modelos válidos; con respuesta, continuar con ella; sin respuesta, el error de
     texto de hoy, **sin tocar backend**.
   - Requirements: REQ-003
   - **Acotado tras la revisión adversarial (B-3): fuera `chunk` y `style`.** Los tres eran
     «parámetro inválido con lista finita», pero solo `model` justifica preguntar: su lista **sale
     de la configuración de cada instalación** y es imposible de adivinar. `chunk` (`auto`/`on`/`off`)
     y `style` (`conventional`/`plain`) tienen dos o tres valores fijos y documentados; preguntarlos
     es superficie sin valor.

6. **Caso 3 — `output_format` en blanco**
   - Files: `server.py`, `local_delegate` (~1328)
   - Requirements: REQ-004

7. **Tests** — `tests/test_preguntas.py`
   - Cada uno **verificado al revés**.

8. **Documentación** — `CHANGELOG.md` (CRLF, con la herramienta de edición), `README.md` (las dos
   variables nuevas), `docs/wiki/Architecture.md` (`elicitation` deja de estar «pendiente de una
   medición» y pasa a «se usa»).

## Test strategy

- **Unit**: `puede_preguntar` con capability ausente / canal ausente / ambas; `preguntar` con el
  mecanismo apagado, con `elicit` que lanza y con plazo agotado.
- **Integration**, con `MCPServer` y `ClientSession` reales por streams en memoria — el patrón que
  ya funciona en `test_clients.py`:
  - backend caído + cliente que acepta → se intenta arrancar y se reintenta.
  - backend caído + cliente que declina → **exactamente** el error de hoy.
  - cliente que no responde → la tool termina dentro del plazo, no cuelga.
  - modelo inválido + cliente que elige → continúa con el elegido.
  - `output_format=" "` + cliente que responde → usa lo respondido.
  - schema de las 11 tools **idéntico** al de antes del change.
- **Security**: las preguntas no llevan rutas, contenido ni credenciales; test que lo asevera sobre
  el texto del mensaje.

## Migration and compatibility

- Dos variables de entorno nuevas, ambas con default; nada más cambia sin configurar.
- Ninguna tool cambia de schema (REQ-009), así que un cliente viejo ve lo mismo.
- Un cliente sin `elicitation` se comporta **exactamente** como hoy.
- Sin dependencias nuevas.

## Plan review

Ver `plan-review.md`.
