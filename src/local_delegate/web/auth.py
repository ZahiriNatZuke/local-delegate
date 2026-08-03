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
- ``Cookie: ld_sesion=<expiración>.<firma>`` — el navegador, **a partir de la segunda**. Basic solo
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
COOKIE = "ld_sesion"

#: Prefijo firmado junto a la expiración. Va dentro del mensaje del HMAC, no al lado: si un día
#: cambia el formato de la cookie, subir la versión invalida de golpe las emitidas con el viejo en
#: vez de dejar dos interpretaciones posibles del mismo texto.
_VERSION = "ld-sesion|v1"

#: Un año. La sesión se renueva sola en cada visita, así que quien use el panel con alguna
#: regularidad no vuelve a ver la petición de credenciales.
DURACION_POR_DEFECTO = 365 * 24 * 3600


def _token_presentado(cabecera: str) -> str | None:
    """Extrae el token de una cabecera `Authorization`, o ``None`` si no lleva ninguno.

    Devolver ``None`` en vez de una cadena vacía es deliberado: «no trae credencial» y «trae una
    credencial vacía» son cosas distintas, y confundirlas dejaría pasar una petición sin nada si
    alguien configurase el token a vacío. El token vacío ya se descarta antes —sin token no hay
    middleware—, pero un dato que solo es seguro por lo que pasa en otro fichero no es seguro.
    """
    esquema, _, resto = cabecera.partition(" ")
    resto = resto.strip()
    if not resto:
        return None

    esquema = esquema.lower()
    if esquema == "bearer":
        return resto
    if esquema == "basic":
        try:
            descifrado = base64.b64decode(resto, validate=True).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            # Basic mal formado es una credencial inválida, no un error del servidor: el 401 de
            # más abajo es la respuesta correcta y el navegador volverá a preguntar.
            return None
        _usuario, separador, contrasena = descifrado.partition(":")
        return contrasena if separador else None
    return None


def peticion_autorizada(cabecera: str | None, token: str) -> bool:
    """¿La cabecera `Authorization` presenta el token esperado?

    Se compara con :func:`secrets.compare_digest` y no con ``==``: la comparación de cadenas de
    Python corta en el primer byte distinto, y ese tiempo distinto es lo que permite adivinar un
    secreto byte a byte. Es barato ponerlo y caro descubrir que faltaba.
    """
    if not cabecera:
        return False
    presentado = _token_presentado(cabecera)
    if presentado is None:
        return False
    return secrets.compare_digest(presentado, token)


def es_basic(cabecera: str | None) -> bool:
    """¿La credencial vino por Basic, o sea desde un navegador?

    Solo a esas peticiones se les entrega sesión. Un cliente MCP o el CLI mandan Bearer en cada
    llamada y no tienen dónde guardar una cookie: darles una sería una cabecera que nadie lee y,
    peor, repartir un segundo secreto derivado a procesos que no lo necesitan.
    """
    return bool(cabecera) and cabecera.split(" ", 1)[0].lower() == "basic"


# --- Sesión del navegador ----------------------------------------------------


def _firma(token: str, expira: int) -> str:
    firma = hmac.new(
        token.encode("utf-8"), f"{_VERSION}|{expira}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(firma).rstrip(b"=").decode("ascii")


def crear_sesion(token: str, duracion: int, ahora: float | None = None) -> str:
    """Valor de cookie que vale hasta ``ahora + duracion``."""
    expira = int(ahora if ahora is not None else time.time()) + int(duracion)
    return f"{expira}.{_firma(token, expira)}"


def sesion_valida(valor: str | None, token: str, ahora: float | None = None) -> int | None:
    """Instante de expiración de una sesión auténtica y viva, o ``None`` si no lo es.

    Devuelve la expiración en vez de un booleano porque quien llama necesita el dato para decidir
    si toca renovarla, y recalcularla fuera obligaría a parsear la cookie dos veces.

    La firma se comprueba **antes** que la caducidad: la expiración va dentro del mensaje firmado,
    así que hasta que la firma no cuadra ese número es texto que eligió quien mandó la petición.
    """
    if not valor:
        return None
    crudo_expira, separador, firma = valor.partition(".")
    if not separador or not firma:
        return None
    try:
        expira = int(crudo_expira)
    except ValueError:
        return None
    if not secrets.compare_digest(firma, _firma(token, expira)):
        return None
    if expira <= (ahora if ahora is not None else time.time()):
        return None
    return expira


def _cookies(scope) -> dict[str, str]:
    """Las cookies de la petición. Tolera varias cabeceras `cookie` y valores con `=` dentro."""
    crudo: list[str] = []
    for nombre, valor in scope.get("headers") or ():
        if nombre == b"cookie":
            crudo.append(valor.decode("latin-1"))
    cookies: dict[str, str] = {}
    for trozo in ";".join(crudo).split(";"):
        clave, separador, contenido = trozo.partition("=")
        if separador:
            cookies[clave.strip()] = contenido.strip()
    return cookies


def _set_cookie(valor: str, duracion: int) -> bytes:
    """La cabecera `Set-Cookie` de la sesión.

    Sin ``Secure`` a propósito, y no por descuido: el daemon habla HTTP plano incluso cuando el
    navegador está en HTTPS, porque quien pone el TLS es un proxy delante (`tailscale serve`). Con
    ``Secure`` la cookie seguiría funcionando ahí, pero rompería el acceso directo por
    `http://<ip>:9393`, que es un escenario que este proyecto soporta. En ese caso la cookie viaja
    en claro igual que viajaría el token en la cabecera Basic: no se pierde nada que se tuviera.

    ``SameSite=Lax`` es lo que sustituye a un token CSRF: una página ajena no consigue que el
    navegador adjunte esta cookie a un `fetch`, un XHR ni un POST hacia el puerto del daemon.
    """
    return (f"{COOKIE}={valor}; Max-Age={int(duracion)}; Path=/; HttpOnly; SameSite=Lax").encode(
        "latin-1"
    )


class TokenPuerto:
    """Envuelve una app ASGI y exige el token —o una sesión suya— en todas sus rutas."""

    def __init__(self, app, token: str, duracion: int = DURACION_POR_DEFECTO) -> None:
        self.app = app
        self.token = token
        # `duracion <= 0` desactiva la sesión y deja la puerta como estaba: solo cabecera. Es la
        # salida para quien prefiera que el navegador no guarde nada.
        self.duracion = max(0, int(duracion))

    def _entregando_sesion(self, send, valor: str):
        """`send` envuelto para colgar la cookie de la primera respuesta que salga."""

        async def enviar(mensaje):
            if mensaje["type"] == "http.response.start":
                mensaje = dict(mensaje)
                mensaje["headers"] = [
                    *(mensaje.get("headers") or []),
                    (b"set-cookie", _set_cookie(valor, self.duracion)),
                ]
            await send(mensaje)

        return enviar

    async def __call__(self, scope, receive, send) -> None:
        # `lifespan` no es una petición: lo emite el servidor al arrancar y al parar, y filtrarlo
        # dejaría al server MCP sin arrancar su propio ciclo de vida. Cualquier tipo que no sea
        # `http` pasa de largo por la misma razón.
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        cabecera = None
        for nombre, valor in scope.get("headers") or ():
            if nombre == b"authorization":
                cabecera = valor.decode("latin-1")
                break

        ahora = time.time()

        if self.duracion:
            expira = sesion_valida(_cookies(scope).get(COOKIE), self.token, ahora)
            if expira is not None:
                # Renovar solo cuando ya se gastó media vida, en vez de en cada respuesta: así una
                # sesión en uso no caduca nunca sin poner una `Set-Cookie` en cada carga de página.
                if expira - ahora < self.duracion / 2:
                    send = self._entregando_sesion(send, crear_sesion(self.token, self.duracion))
                await self.app(scope, receive, send)
                return

        if peticion_autorizada(cabecera, self.token):
            if self.duracion and es_basic(cabecera):
                send = self._entregando_sesion(send, crear_sesion(self.token, self.duracion))
            await self.app(scope, receive, send)
            return

        cuerpo = b"local-delegate: falta el token del puerto o no es correcto\n"
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(cuerpo)).encode("ascii")),
                    # Lo que hace que el navegador pregunte en vez de enseñar un 401 pelado.
                    (b"www-authenticate", _REALM.encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": cuerpo})


def proteger(app, token: str, duracion: int = DURACION_POR_DEFECTO):
    """Devuelve la app protegida, o la misma app si no hay token que exigir.

    Se decide aquí y no en quien llama para que exista **un solo** sitio donde se responde «¿este
    puerto está protegido?». Sin token, la app vuelve tal cual: quien no configura nada no paga ni
    una comparación por petición.
    """
    return TokenPuerto(app, token, duracion) if token else app
