"""La puerta del puerto del daemon.

Estos tests cubren una superficie de **seguridad**, así que se escriben al revés de lo habitual:
lo que hay que demostrar no es que el token correcto entra —eso es lo fácil— sino que **todo lo
demás se queda fuera**, y que la puerta cubre las dos apps que viven en ese puerto y no solo la
que uno tenía en la cabeza.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from local_delegate.web import auth

TOKEN = "el-token-bueno"


def _basic(user: str, password: str) -> str:
    raw = f"{user}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _with_cookie(value: str) -> dict[str, str]:
    """La sesión se manda como cabecera cruda y no por el cookie-jar del cliente.

    Deliberado: así el test controla exactamente qué llega —incluidas las cookies mal formadas que
    un jar nunca dejaría enviar— y de paso ejercita el parser en vez de darlo por bueno.
    """
    return {"Cookie": f"{auth.COOKIE}={value}"}


def _app(duration: int = auth.DEFAULT_DURATION) -> TestClient:
    """Reproduce la forma real del daemon: una raíz con otra app montada debajo.

    Montar de verdad importa: el fallo que este diseño evita es proteger la app de arriba y
    dejar abierta la de abajo, y eso solo se ve si hay una app de abajo.
    """

    async def root(_request):
        return PlainTextResponse("raiz")

    async def mounted(_request):
        return PlainTextResponse("montada")

    inner = Starlette(
        routes=[
            Route("/api/status", mounted, methods=["GET"]),
            Route("/", mounted, methods=["GET"]),
        ]
    )
    outer = Starlette(routes=[Route("/mcp", root, methods=["GET"]), Mount("/", app=inner)])
    return TestClient(auth.protect(outer, TOKEN, duration))


@pytest.fixture
def client() -> TestClient:
    return _app()


# --- Lo que NO debe entrar ---------------------------------------------------


@pytest.mark.parametrize("path", ["/mcp", "/api/status", "/"])
def test_without_header_nothing_gets_in_on_any_route(client, path):
    """El endpoint MCP y el dashboard son dos apps y una sola puerta las cubre.

    La razón de parametrizar por ruta y no probar solo `/mcp`: el agujero real que motivó todo
    esto era que el endpoint MCP estaba cubierto por otra cosa y `/api/*` no, y nadie lo vio
    porque solo se miró por un camino.
    """
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        "",
        "Bearer",
        "Bearer ",
        "Bearer el-token-malo",
        "Bearer el-token-bueno-y-un-poco-mas",
        "Bearer el-token-buen",
        "el-token-bueno",  # sin esquema
        "Basic no-es-base64-valido",
        "Basic " + base64.b64encode(b"sin-dos-puntos").decode(),
        "Basic " + base64.b64encode(b"usuario:el-token-malo").decode(),
        "Negotiate el-token-bueno",
    ],
)
def test_a_credential_that_is_not_the_token_does_not_get_in(client, header):
    assert client.get("/mcp", headers={"Authorization": header}).status_code == 401


def test_the_correct_prefix_is_not_enough(client):
    """Un token que empieza bien pero no es el bueno se rechaza igual.

    Escrito aparte porque es la propiedad que rompería una comparación byte a byte con salida
    temprana, que es justo lo que `secrets.compare_digest` existe para evitar.
    """
    assert not auth.is_request_authorized(f"Bearer {TOKEN[:-1]}", TOKEN)
    assert not auth.is_request_authorized(f"Bearer {TOKEN}x", TOKEN)


# --- Lo que SÍ debe entrar ---------------------------------------------------


def test_correct_bearer_gets_in(client):
    response = client.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.text == "raiz"


def test_the_mounted_app_is_also_reached_with_the_token(client):
    response = client.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert response.text == "montada"


def test_basic_gets_in_because_a_browser_does_not_send_bearer(client):
    """El dashboard lo abre un navegador escribiendo una URL, y ahí no hay cabecera Bearer.

    Sin esta vía el token dejaría el panel inalcanzable para su único usuario real, que es la
    clase de arreglo de seguridad que acaba desactivado a la semana.
    """
    response = client.get("/", headers={"Authorization": _basic("quien-sea", TOKEN)})
    assert response.status_code == 200


def test_the_basic_user_does_not_matter(client):
    """Solo se compara la contraseña: no hay cuentas, hay un secreto."""
    for user in ("", "admin", "yohan"):
        assert auth.is_request_authorized(_basic(user, TOKEN), TOKEN)


def test_a_token_with_a_colon_inside_is_still_valid():
    """El separador de Basic es el PRIMER `:`, así que la contraseña puede llevar los suyos.

    No es teórico: un token generado al azar puede contener cualquier carácter, y partir por el
    último `:` —o por todos— dejaría fuera a esos tokens de una forma dificilísima de diagnosticar
    («a mí me funciona» según qué token te toque).
    """
    odd = "abc:def:ghi"
    assert auth.is_request_authorized(_basic("usuario", odd), odd)
    assert auth.is_request_authorized(f"Bearer {odd}", odd)


# --- Cómo se rechaza, que también importa ------------------------------------


def test_the_401_invites_the_browser_to_ask(client):
    """Sin `WWW-Authenticate`, el navegador enseñaría un 401 pelado en vez de pedir la clave."""
    response = client.get("/")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic realm=")


def test_the_rejection_does_not_leak_the_token(client):
    """Un mensaje de error que se chive del secreto sería peor que no tener puerta."""
    response = client.get("/mcp", headers={"Authorization": "Bearer lo-que-sea"})
    assert TOKEN not in response.text
    assert TOKEN not in str(response.headers)


# --- Sin token configurado, nada cambia --------------------------------------


def test_without_a_token_the_app_comes_back_intact():
    """Quien no configura token no paga ni una comparación: `protect` devuelve el mismo objeto."""

    async def path(_request):
        return PlainTextResponse("libre")

    app = Starlette(routes=[Route("/mcp", path, methods=["GET"])])
    assert auth.protect(app, "") is app
    assert TestClient(auth.protect(app, "")).get("/mcp").status_code == 200


# --- La sesión del navegador -------------------------------------------------
#
# Misma disciplina que arriba: lo que hay que demostrar de una cookie de sesión no es que la buena
# entra, sino que ninguna otra lo consigue. Y como una sesión es un secreto DERIVADO del token,
# cada prueba de rechazo lleva al lado su control positivo — sin él, un fallo tonto en cómo se
# fabrica la cookie del test daría 401 en todas y el fichero entero pasaría sin comprobar nada.


def test_the_good_cookie_gets_in_and_the_ones_around_it_do_not():
    """Control positivo y negativos juntos: la misma fábrica produce las de las dos columnas."""
    client = _app()
    good = auth.create_session(TOKEN, 3600)
    assert client.get("/", headers=_with_cookie(good)).status_code == 200, (
        "la sesión legítima no entró: los rechazos de abajo no probarían nada"
    )

    expired = auth.create_session(TOKEN, -1)
    from_another_token = auth.create_session("otro-token", 3600)
    expires, _, signature = good.partition(".")
    extended = f"{int(expires) + 10 * 3600}.{signature}"

    for label, value in (
        ("caducada", expired),
        ("firmada con otro token", from_another_token),
        ("con la expiración alargada a mano", extended),
        ("firma inventada", f"{int(expires)}.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        ("sin firma", f"{int(expires)}."),
        ("sin separador", str(int(expires))),
        ("con el token dentro tal cual", TOKEN),
        ("vacía", ""),
        ("basura", "no-es-una-sesion"),
        ("expiración no numérica", f"manana.{signature}"),
    ):
        response = client.get("/", headers=_with_cookie(value))
        assert response.status_code == 401, f"entró una sesión {label}"


def test_extending_the_session_is_not_possible_without_the_token():
    """La expiración va DENTRO del mensaje firmado, no al lado.

    Si se firmara solo una parte, una cookie legítima recién caducada se convertiría en eterna
    cambiándole el número, que es el único ataque que esta cookie tiene que aguantar.
    """
    expired = auth.create_session(TOKEN, -1)
    _, _, signature = expired.partition(".")
    future = int(time.time()) + 3600
    assert auth.valid_session(f"{future}.{signature}", TOKEN) is None
    assert auth.valid_session(auth.create_session(TOKEN, 3600), TOKEN) is not None


def test_rotating_the_token_invalidates_live_sessions():
    """Cambiar el secreto tiene que echar a todo el mundo, y sin lista de sesiones que purgar."""
    old = auth.create_session(TOKEN, 3600)
    assert auth.valid_session(old, TOKEN) is not None
    assert auth.valid_session(old, TOKEN + "-rotado") is None


def test_basic_hands_out_a_session_and_the_second_visit_asks_for_nothing():
    """El punto de todo esto: entrar una vez con el token y que el navegador siga dentro."""
    client = _app()
    first = client.get("/", headers={"Authorization": _basic("quien-sea", TOKEN)})
    assert first.status_code == 200

    cookie = first.headers["set-cookie"]
    assert cookie.startswith(f"{auth.COOKIE}=")
    assert "HttpOnly" in cookie, "sin HttpOnly cualquier script de la página lee la sesión"
    assert "SameSite=Lax" in cookie, "SameSite=Lax es lo que hace de token CSRF aquí"
    assert "Path=/" in cookie, "la sesión cubre el puerto entero, no solo la ruta que la emitió"
    assert f"Max-Age={365 * 24 * 3600}" in cookie

    value = cookie.split(";")[0].split("=", 1)[1]
    # Vaciar el jar del cliente no es limpieza cosmética: sin esto el propio TestClient reenvía la
    # cookie él solo y el control negativo de abajo entra con un 200 que parece del `Authorization`
    # que ya no se manda. La primera versión de este test pasaba por ahí.
    client.cookies.clear()
    assert client.get("/").status_code == 401, "el jar seguía autorizando: el resto no prueba nada"

    # Sin `Authorization`: es exactamente lo que manda el navegador al volver mañana.
    assert client.get("/", headers=_with_cookie(value)).status_code == 200


def test_the_session_also_reaches_the_mounted_app():
    """Una puerta, un puerto: la sesión no puede cubrir menos rutas que la cabecera."""
    client = _app()
    value = auth.create_session(TOKEN, 3600)
    for path, body in (("/mcp", "raiz"), ("/api/status", "montada"), ("/", "montada")):
        response = client.get(path, headers=_with_cookie(value))
        assert response.status_code == 200, path
        assert response.text == body


def test_bearer_gets_no_cookie():
    """Un cliente MCP o el CLI no tienen dónde guardarla; darles una es repartir secreto de más."""
    response = _app().get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    assert "set-cookie" not in response.headers


def test_entering_with_the_session_does_not_hand_out_a_new_one_each_time():
    """Renovar en cada respuesta pondría una `Set-Cookie` en cada carga de página sin ganar nada."""
    client = _app(duration=1000)
    fresh = client.get("/", headers=_with_cookie(auth.create_session(TOKEN, 900)))
    assert fresh.status_code == 200
    assert "set-cookie" not in fresh.headers


def test_the_session_in_use_is_renewed_before_expiring():
    """Media vida gastada es el punto de renovación: así una sesión usada no caduca nunca."""
    client = _app(duration=1000)
    response = client.get("/", headers=_with_cookie(auth.create_session(TOKEN, 400)))
    assert response.status_code == 200
    renewed = response.headers["set-cookie"].split(";")[0].split("=", 1)[1]
    assert auth.valid_session(renewed, TOKEN) > time.time() + 900


def test_with_zero_duration_there_is_no_session_at_all():
    """La salida para quien no quiera que el navegador guarde nada: la puerta de siempre."""
    client = _app(duration=0)
    with_basic = client.get("/", headers={"Authorization": _basic("quien-sea", TOKEN)})
    assert with_basic.status_code == 200
    assert "set-cookie" not in with_basic.headers
    # Y una cookie perfectamente firmada tampoco abre nada, que es la mitad que se olvida.
    assert (
        client.get("/", headers=_with_cookie(auth.create_session(TOKEN, 3600))).status_code == 401
    )


def test_the_session_is_found_among_other_cookies():
    """El navegador manda todas las cookies del origen juntas, no solo la nuestra."""
    client = _app()
    value = auth.create_session(TOKEN, 3600)
    header = {"Cookie": f"tema=oscuro; {auth.COOKIE}={value}; otra=cosa"}
    assert client.get("/", headers=header).status_code == 200


def test_without_a_configured_token_the_session_does_not_exist():
    """Quien no puso token no gana una cookie: `protect` sigue devolviendo la misma app."""

    async def path(_request):
        return PlainTextResponse("libre")

    app = Starlette(routes=[Route("/mcp", path, methods=["GET"])])
    assert auth.protect(app, "", 3600) is app


def test_the_lifespan_is_not_filtered():
    """Un scope que no es `http` tiene que pasar de largo.

    Si el middleware respondiera 401 al `lifespan`, el server MCP no arrancaría su ciclo de vida
    y el daemon quedaría inservible **con** el token puesto y perfecto sin él — un fallo que no
    aparece en ninguna prueba de peticiones.
    """
    import asyncio

    seen = []
    sent = []

    async def app(scope, _receive, _send):
        seen.append(scope["type"])

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        sent.append(message)

    asyncio.run(auth.protect(app, TOKEN)({"type": "lifespan"}, receive, send))

    assert seen == ["lifespan"], "el lifespan no llegó a la app: la puerta se lo tragó"
    assert sent == [], f"la puerta respondió a un lifespan: {sent}"


# --- A6: la cookie cambia de nombre y de prefijo firmado (REQ-012) ----------------------------
def _session_from_0_34(token: str, expires: int) -> str:
    """Una sesión emitida por la 0.34.0: prefijo `ld-sesion|v1` dentro del HMAC."""
    signature = hmac.new(
        token.encode(), f"ld-sesion|v1|{expires}".encode(), hashlib.sha256
    ).digest()
    return f"{expires}." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")


def test_a_0_34_session_cookie_asks_to_authenticate_without_error():
    """La cookie vieja no entra, ni con su nombre ni con el nuevo: 401 que pide Basic, sin 500.

    Y autenticarse una vez basta: se recibe la sesión nueva aunque el navegador siga mandando la
    vieja.
    """
    client = _app()
    old = _session_from_0_34(TOKEN, int(time.time()) + 3600)

    for name in ("ld_sesion", auth.COOKIE):
        response = client.get("/", headers={"Cookie": f"{name}={old}"})
        assert response.status_code == 401, name
        assert response.headers["www-authenticate"].startswith("Basic realm=")

    accepted = client.get(
        "/", headers={"Authorization": _basic("x", TOKEN), "Cookie": f"ld_sesion={old}"}
    )
    assert accepted.status_code == 200
    assert accepted.headers["set-cookie"].startswith("ld_session=")
