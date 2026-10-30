"""Puerta del puerto del daemon: un token para el endpoint MCP, el dashboard y `/api/*`.

Middleware ASGI puro, no de Starlette, y a propósito. El daemon sirve **una** app raíz —la del
transporte MCP— con el dashboard montado en `/`, así que envolver esa raíz cubre todo lo que
escucha en el puerto de una sola vez. Un `add_middleware` de Starlette dependería de a qué app se
lo añadas y dejaría fuera lo montado por debajo; envolver el ASGI no admite esa duda.

**Tres formas de presentar el mismo secreto**, porque hay tres clases de cliente y ninguna se puede
sacrificar:

- ``Authorization: Bearer <token>`` — clientes MCP y línea de comandos. Es lo que un cliente HTTP
  escribe en su entrada de configuración referenciando una variable de entorno, sin que el secreto
  toque un fichero.
- ``Authorization: Basic <base64(usuario:token)>`` — el navegador, la **primera** vez. Un navegador
  no manda una cabecera Bearer por escribir una URL, y sin esto el dashboard quedaría inalcanzable
  para su único usuario real. Con Basic, el navegador pide las credenciales él solo al recibir el
  401 y no hacen falta pantalla de login ni CSRF. El usuario da igual: solo se compara la clave.
- ``Cookie: ld_session=<expiración>.<firma>`` — el navegador, **a partir de la segunda**. Basic solo
  lo recuerda el navegador mientras la ventana vive y por origen exacto, así que en la práctica el
  panel volvía a pedir el token al reabrir el navegador y otra vez al entrar por `localhost` en vez
  de por `127.0.0.1`. Un dashboard que pide un secreto largo varias veces al día es un dashboard
  que se acaba desprotegiendo, así que la sesión es lo que hace que el token *siga puesto*.

La sesión no guarda estado en ninguna parte: la cookie lleva su propia expiración firmada con
HMAC-SHA256 **usando el token como clave**. Eso da tres propiedades gratis y sin fichero que
mantener: no se puede fabricar sin conocer el token, no se puede alargar sin invalidar la firma, y
**rotar el token invalida todas las sesiones** por el mero hecho de rotarlo.

Sin token configurado el middleware ni se instala, de modo que el coste para quien no lo usa es
exactamente cero.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import time

_REALM = 'Basic realm="local-delegate", charset="UTF-8"'

#: Nombre de la cookie de sesión.
COOKIE = "ld_session"

#: Prefijo firmado junto a la expiración. Va dentro del mensaje del HMAC, no al lado: si un día
#: cambia el formato de la cookie, subir la versión invalida de golpe las emitidas con el viejo en
#: vez de dejar dos interpretaciones posibles del mismo texto.
_VERSION = "ld-session|v1"

#: Un año. La sesión se renueva sola en cada visita, así que quien use el panel con alguna
#: regularidad no vuelve a ver la petición de credenciales.
DEFAULT_DURATION = 365 * 24 * 3600

#: The turn endpoint's three routes (concurrency PC+Mac, REQ-016): `PortToken` lets them through
#: without its token because they check their own secret (`web/turn_api.py`: the port token OR the
#: backend's key, Bearer only). Exact method and path, never a prefix: `/api/turn/x`, `/api/turn/`
#: plus `..`, `//api/turn/acquire` or a `GET` still need the port token.
TURN_ACQUIRE_PATH = "/api/turn/acquire"
TURN_HEARTBEAT_PATH = "/api/turn/heartbeat"
TURN_RELEASE_PATH = "/api/turn/release"
TURN_ROUTES: frozenset[tuple[str, str]] = frozenset(
    ("POST", path) for path in (TURN_ACQUIRE_PATH, TURN_HEARTBEAT_PATH, TURN_RELEASE_PATH)
)


def is_exempt(method: object, path: object) -> bool:
    """Does `PortToken` let this request through without its token? Only the three turn routes."""
    return (method, path) in TURN_ROUTES


def _presented_token(header: str) -> str | None:
    """Extrae el token de una cabecera `Authorization`, o ``None`` si no lleva ninguno.

    Devolver ``None`` en vez de una cadena vacía es deliberado: «no trae credencial» y «trae una
    credencial vacía» son cosas distintas, y confundirlas dejaría pasar una petición sin nada si
    alguien configurase el token a vacío. El token vacío ya se descarta antes —sin token no hay
    middleware—, pero un dato que solo es seguro por lo que pasa en otro fichero no es seguro.
    """
    scheme, _, rest = header.partition(" ")
    rest = rest.strip()
    if not rest:
        return None

    scheme = scheme.lower()
    if scheme == "bearer":
        return rest
    if scheme == "basic":
        try:
            decoded = base64.b64decode(rest, validate=True).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            # Basic mal formado es una credencial inválida, no un error del servidor: el 401 de
            # más abajo es la respuesta correcta y el navegador volverá a preguntar.
            return None
        _user, sep, password = decoded.partition(":")
        return password if sep else None
    return None


def is_request_authorized(header: str | None, token: str) -> bool:
    """¿La cabecera `Authorization` presenta el token esperado?

    Se compara con :func:`secrets.compare_digest` y no con ``==``: la comparación de cadenas de
    Python corta en el primer byte distinto, y ese tiempo distinto es lo que permite adivinar un
    secreto byte a byte. Es barato ponerlo y caro descubrir que faltaba.
    """
    if not header:
        return False
    presented = _presented_token(header)
    if presented is None:
        return False
    return secrets.compare_digest(presented, token)


def is_basic(header: str | None) -> bool:
    """¿La credencial vino por Basic, o sea desde un navegador?

    Solo a esas peticiones se les entrega sesión. Un cliente MCP o el CLI mandan Bearer en cada
    llamada y no tienen dónde guardar una cookie: darles una sería una cabecera que nadie lee y,
    peor, repartir un segundo secreto derivado a procesos que no lo necesitan.
    """
    return bool(header) and header.split(" ", 1)[0].lower() == "basic"


# --- Sesión del navegador ----------------------------------------------------


def _sign(token: str, expires: int) -> str:
    signature = hmac.new(
        token.encode("utf-8"), f"{_VERSION}|{expires}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def create_session(token: str, duration: int, now: float | None = None) -> str:
    """Valor de cookie que vale hasta ``ahora + duracion``."""
    expires = int(now if now is not None else time.time()) + int(duration)
    return f"{expires}.{_sign(token, expires)}"


def valid_session(value: str | None, token: str, now: float | None = None) -> int | None:
    """Instante de expiración de una sesión auténtica y viva, o ``None`` si no lo es.

    Devuelve la expiración en vez de un booleano porque quien llama necesita el dato para decidir
    si toca renovarla, y recalcularla fuera obligaría a parsear la cookie dos veces.

    La firma se comprueba **antes** que la caducidad: la expiración va dentro del mensaje firmado,
    así que hasta que la firma no cuadra ese número es texto que eligió quien mandó la petición.
    """
    if not value:
        return None
    raw_expires, sep, signature = value.partition(".")
    if not sep or not signature:
        return None
    try:
        expires = int(raw_expires)
    except ValueError:
        return None
    if not secrets.compare_digest(signature, _sign(token, expires)):
        return None
    if expires <= (now if now is not None else time.time()):
        return None
    return expires


def _cookies(scope) -> dict[str, str]:
    """Las cookies de la petición. Tolera varias cabeceras `cookie` y valores con `=` dentro."""
    raw: list[str] = []
    for name, value in scope.get("headers") or ():
        if name == b"cookie":
            raw.append(value.decode("latin-1"))
    cookies: dict[str, str] = {}
    for chunk in ";".join(raw).split(";"):
        key, sep, content = chunk.partition("=")
        if sep:
            cookies[key.strip()] = content.strip()
    return cookies


def _set_cookie(value: str, duration: int) -> bytes:
    """La cabecera `Set-Cookie` de la sesión.

    Sin ``Secure`` a propósito, y no por descuido: el daemon habla HTTP plano incluso cuando el
    navegador está en HTTPS, porque quien pone el TLS es un proxy delante (`tailscale serve`). Con
    ``Secure`` la cookie seguiría funcionando ahí, pero rompería el acceso directo por
    `http://<ip>:9393`, que es un escenario que este proyecto soporta. En ese caso la cookie viaja
    en claro igual que viajaría el token en la cabecera Basic: no se pierde nada que se tuviera.

    ``SameSite=Lax`` es lo que sustituye a un token CSRF: una página ajena no consigue que el
    navegador adjunte esta cookie a un `fetch`, un XHR ni un POST hacia el puerto del daemon.
    """
    return (f"{COOKIE}={value}; Max-Age={int(duration)}; Path=/; HttpOnly; SameSite=Lax").encode(
        "latin-1"
    )


class PortToken:
    """Envuelve una app ASGI y exige el token —o una sesión suya— en todas sus rutas."""

    def __init__(self, app, token: str, duration: int = DEFAULT_DURATION) -> None:
        self.app = app
        self.token = token
        # `duracion <= 0` desactiva la sesión y deja la puerta como estaba: solo cabecera. Es la
        # salida para quien prefiera que el navegador no guarde nada.
        self.duration = max(0, int(duration))

    def _delivering_session(self, send, value: str):
        """`send` envuelto para colgar la cookie de la primera respuesta que salga."""

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    *(message.get("headers") or []),
                    (b"set-cookie", _set_cookie(value, self.duration)),
                ]
            await send(message)

        return send_wrapper

    async def __call__(self, scope, receive, send) -> None:
        # `lifespan` no es una petición: lo emite el servidor al arrancar y al parar, y filtrarlo
        # dejaría al server MCP sin arrancar su propio ciclo de vida. Cualquier tipo que no sea
        # `http` pasa de largo por la misma razón.
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        if is_exempt(scope.get("method"), scope.get("path")):
            # Their own dependency checks the secret (and refuses Basic and the cookie).
            await self.app(scope, receive, send)
            return

        header = None
        for name, value in scope.get("headers") or ():
            if name == b"authorization":
                header = value.decode("latin-1")
                break

        now = time.time()

        if self.duration:
            expires = valid_session(_cookies(scope).get(COOKIE), self.token, now)
            if expires is not None:
                # Renovar solo cuando ya se gastó media vida, en vez de en cada respuesta: así una
                # sesión en uso no caduca nunca sin poner una `Set-Cookie` en cada carga de página.
                if expires - now < self.duration / 2:
                    send = self._delivering_session(send, create_session(self.token, self.duration))
                await self.app(scope, receive, send)
                return

        if is_request_authorized(header, self.token):
            if self.duration and is_basic(header):
                send = self._delivering_session(send, create_session(self.token, self.duration))
            await self.app(scope, receive, send)
            return

        body = b"local-delegate: falta el token del puerto o no es correcto\n"
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    # Lo que hace que el navegador pregunte en vez de enseñar un 401 pelado.
                    (b"www-authenticate", _REALM.encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def protect(app, token: str, duration: int = DEFAULT_DURATION):
    """Devuelve la app protegida, o la misma app si no hay token que exigir.

    Se decide aquí y no en quien llama para que exista **un solo** sitio donde se responde «¿este
    puerto está protegido?». Sin token, la app vuelve tal cual: quien no configura nada no paga ni
    una comparación por petición.
    """
    return PortToken(app, token, duration) if token else app
