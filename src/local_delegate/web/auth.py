"""Puerta del puerto del daemon: un token para el endpoint MCP, el dashboard y `/api/*`.

Middleware ASGI puro, no de Starlette, y a propósito. El daemon sirve **una** app raíz —la del
transporte MCP— con el dashboard montado en `/`, así que envolver esa raíz cubre todo lo que
escucha en el puerto de una sola vez. Un `add_middleware` de Starlette dependería de a qué app se
lo añadas y dejaría fuera lo montado por debajo; envolver el ASGI no admite esa duda.

**Dos formas de presentar el mismo token**, porque hay dos clases de cliente y ninguna se puede
sacrificar:

- ``Authorization: Bearer <token>`` — clientes MCP y línea de comandos. Es lo que un cliente HTTP
  escribe en su entrada de configuración referenciando una variable de entorno, sin que el secreto
  toque un fichero.
- ``Authorization: Basic <base64(usuario:token)>`` — el navegador. **Un navegador no manda una
  cabecera Bearer por escribir una URL**, y sin esto el dashboard quedaría inalcanzable para su
  único usuario real. Con Basic, el navegador pide las credenciales él solo al recibir el 401, las
  recuerda, y no hacen falta cookies, ni sesión, ni una pantalla de login, ni CSRF. El usuario da
  igual: solo se compara la contraseña.

Sin token configurado el middleware ni se instala, de modo que el coste para quien no lo usa es
exactamente cero.
"""

from __future__ import annotations

import base64
import binascii
import secrets

_REALM = 'Basic realm="local-delegate", charset="UTF-8"'


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


class TokenPuerto:
    """Envuelve una app ASGI y exige el token en todas sus rutas."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

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

        if peticion_autorizada(cabecera, self.token):
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


def proteger(app, token: str):
    """Devuelve la app protegida, o la misma app si no hay token que exigir.

    Se decide aquí y no en quien llama para que exista **un solo** sitio donde se responde «¿este
    puerto está protegido?». Sin token, la app vuelve tal cual: quien no configura nada no paga ni
    una comparación por petición.
    """
    return TokenPuerto(app, token) if token else app
