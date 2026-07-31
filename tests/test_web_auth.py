"""La puerta del puerto del daemon.

Estos tests cubren una superficie de **seguridad**, así que se escriben al revés de lo habitual:
lo que hay que demostrar no es que el token correcto entra —eso es lo fácil— sino que **todo lo
demás se queda fuera**, y que la puerta cubre las dos apps que viven en ese puerto y no solo la
que uno tenía en la cabeza.
"""

from __future__ import annotations

import base64

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from local_delegate.web import auth

TOKEN = "el-token-bueno"


def _basic(usuario: str, contrasena: str) -> str:
    crudo = f"{usuario}:{contrasena}".encode()
    return "Basic " + base64.b64encode(crudo).decode("ascii")


@pytest.fixture
def cliente() -> TestClient:
    """Reproduce la forma real del daemon: una raíz con otra app montada debajo.

    Montar de verdad importa: el fallo que este diseño evita es proteger la app de arriba y
    dejar abierta la de abajo, y eso solo se ve si hay una app de abajo.
    """

    async def raiz(_request):
        return PlainTextResponse("raiz")

    async def montada(_request):
        return PlainTextResponse("montada")

    interna = Starlette(
        routes=[
            Route("/api/status", montada, methods=["GET"]),
            Route("/", montada, methods=["GET"]),
        ]
    )
    externa = Starlette(routes=[Route("/mcp", raiz, methods=["GET"]), Mount("/", app=interna)])
    return TestClient(auth.proteger(externa, TOKEN))


# --- Lo que NO debe entrar ---------------------------------------------------


@pytest.mark.parametrize("ruta", ["/mcp", "/api/status", "/"])
def test_sin_cabecera_no_entra_por_ninguna_ruta(cliente, ruta):
    """El endpoint MCP y el dashboard son dos apps y una sola puerta las cubre.

    La razón de parametrizar por ruta y no probar solo `/mcp`: el agujero real que motivó todo
    esto era que el endpoint MCP estaba cubierto por otra cosa y `/api/*` no, y nadie lo vio
    porque solo se miró por un camino.
    """
    assert cliente.get(ruta).status_code == 401


@pytest.mark.parametrize(
    "cabecera",
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
def test_una_credencial_que_no_es_el_token_no_entra(cliente, cabecera):
    assert cliente.get("/mcp", headers={"Authorization": cabecera}).status_code == 401


def test_el_prefijo_correcto_no_basta(cliente):
    """Un token que empieza bien pero no es el bueno se rechaza igual.

    Escrito aparte porque es la propiedad que rompería una comparación byte a byte con salida
    temprana, que es justo lo que `secrets.compare_digest` existe para evitar.
    """
    assert not auth.peticion_autorizada(f"Bearer {TOKEN[:-1]}", TOKEN)
    assert not auth.peticion_autorizada(f"Bearer {TOKEN}x", TOKEN)


# --- Lo que SÍ debe entrar ---------------------------------------------------


def test_bearer_correcto_entra(cliente):
    respuesta = cliente.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert respuesta.status_code == 200
    assert respuesta.text == "raiz"


def test_la_app_montada_tambien_se_alcanza_con_el_token(cliente):
    respuesta = cliente.get("/api/status", headers={"Authorization": f"Bearer {TOKEN}"})
    assert respuesta.status_code == 200
    assert respuesta.text == "montada"


def test_basic_entra_porque_un_navegador_no_manda_bearer(cliente):
    """El dashboard lo abre un navegador escribiendo una URL, y ahí no hay cabecera Bearer.

    Sin esta vía el token dejaría el panel inalcanzable para su único usuario real, que es la
    clase de arreglo de seguridad que acaba desactivado a la semana.
    """
    respuesta = cliente.get("/", headers={"Authorization": _basic("quien-sea", TOKEN)})
    assert respuesta.status_code == 200


def test_el_usuario_de_basic_da_igual(cliente):
    """Solo se compara la contraseña: no hay cuentas, hay un secreto."""
    for usuario in ("", "admin", "yohan"):
        assert auth.peticion_autorizada(_basic(usuario, TOKEN), TOKEN)


def test_un_token_con_dos_puntos_dentro_sigue_valiendo():
    """El separador de Basic es el PRIMER `:`, así que la contraseña puede llevar los suyos.

    No es teórico: un token generado al azar puede contener cualquier carácter, y partir por el
    último `:` —o por todos— dejaría fuera a esos tokens de una forma dificilísima de diagnosticar
    («a mí me funciona» según qué token te toque).
    """
    raro = "abc:def:ghi"
    assert auth.peticion_autorizada(_basic("usuario", raro), raro)
    assert auth.peticion_autorizada(f"Bearer {raro}", raro)


# --- Cómo se rechaza, que también importa ------------------------------------


def test_el_401_invita_al_navegador_a_preguntar(cliente):
    """Sin `WWW-Authenticate`, el navegador enseñaría un 401 pelado en vez de pedir la clave."""
    respuesta = cliente.get("/")
    assert respuesta.status_code == 401
    assert respuesta.headers["www-authenticate"].startswith("Basic realm=")


def test_el_rechazo_no_filtra_el_token(cliente):
    """Un mensaje de error que se chive del secreto sería peor que no tener puerta."""
    respuesta = cliente.get("/mcp", headers={"Authorization": "Bearer lo-que-sea"})
    assert TOKEN not in respuesta.text
    assert TOKEN not in str(respuesta.headers)


# --- Sin token configurado, nada cambia --------------------------------------


def test_sin_token_la_app_vuelve_intacta():
    """Quien no configura token no paga ni una comparación: `proteger` devuelve el mismo objeto."""

    async def ruta(_request):
        return PlainTextResponse("libre")

    app = Starlette(routes=[Route("/mcp", ruta, methods=["GET"])])
    assert auth.proteger(app, "") is app
    assert TestClient(auth.proteger(app, "")).get("/mcp").status_code == 200


def test_el_lifespan_no_se_filtra():
    """Un scope que no es `http` tiene que pasar de largo.

    Si el middleware respondiera 401 al `lifespan`, el server MCP no arrancaría su ciclo de vida
    y el daemon quedaría inservible **con** el token puesto y perfecto sin él — un fallo que no
    aparece en ninguna prueba de peticiones.
    """
    import asyncio

    vistos = []
    enviados = []

    async def app(scope, _receive, _send):
        vistos.append(scope["type"])

    async def recibir():
        return {"type": "lifespan.startup"}

    async def enviar(mensaje):
        enviados.append(mensaje)

    asyncio.run(auth.proteger(app, TOKEN)({"type": "lifespan"}, recibir, enviar))

    assert vistos == ["lifespan"], "el lifespan no llegó a la app: la puerta se lo tragó"
    assert enviados == [], f"la puerta respondió a un lifespan: {enviados}"
