"""La puerta del puerto del daemon.

Estos tests cubren una superficie de **seguridad**, así que se escriben al revés de lo habitual:
lo que hay que demostrar no es que el token correcto entra —eso es lo fácil— sino que **todo lo
demás se queda fuera**, y que la puerta cubre las dos apps que viven en ese puerto y no solo la
que uno tenía en la cabeza.
"""

from __future__ import annotations

import base64
import time

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


def _con_cookie(valor: str) -> dict[str, str]:
    """La sesión se manda como cabecera cruda y no por el cookie-jar del cliente.

    Deliberado: así el test controla exactamente qué llega —incluidas las cookies mal formadas que
    un jar nunca dejaría enviar— y de paso ejercita el parser en vez de darlo por bueno.
    """
    return {"Cookie": f"{auth.COOKIE}={valor}"}


def _app(duracion: int = auth.DURACION_POR_DEFECTO) -> TestClient:
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
    return TestClient(auth.proteger(externa, TOKEN, duracion))


@pytest.fixture
def cliente() -> TestClient:
    return _app()


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


# --- La sesión del navegador -------------------------------------------------
#
# Misma disciplina que arriba: lo que hay que demostrar de una cookie de sesión no es que la buena
# entra, sino que ninguna otra lo consigue. Y como una sesión es un secreto DERIVADO del token,
# cada prueba de rechazo lleva al lado su control positivo — sin él, un fallo tonto en cómo se
# fabrica la cookie del test daría 401 en todas y el fichero entero pasaría sin comprobar nada.


def test_la_cookie_buena_entra_y_las_de_alrededor_no():
    """Control positivo y negativos juntos: la misma fábrica produce las de las dos columnas."""
    cliente = _app()
    buena = auth.crear_sesion(TOKEN, 3600)
    assert cliente.get("/", headers=_con_cookie(buena)).status_code == 200, (
        "la sesión legítima no entró: los rechazos de abajo no probarían nada"
    )

    caducada = auth.crear_sesion(TOKEN, -1)
    de_otro_token = auth.crear_sesion("otro-token", 3600)
    expira, _, firma = buena.partition(".")
    alargada = f"{int(expira) + 10 * 3600}.{firma}"

    for etiqueta, valor in (
        ("caducada", caducada),
        ("firmada con otro token", de_otro_token),
        ("con la expiración alargada a mano", alargada),
        ("firma inventada", f"{int(expira)}.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        ("sin firma", f"{int(expira)}."),
        ("sin separador", str(int(expira))),
        ("con el token dentro tal cual", TOKEN),
        ("vacía", ""),
        ("basura", "no-es-una-sesion"),
        ("expiración no numérica", f"manana.{firma}"),
    ):
        respuesta = cliente.get("/", headers=_con_cookie(valor))
        assert respuesta.status_code == 401, f"entró una sesión {etiqueta}"


def test_alargar_la_sesion_no_es_posible_sin_el_token():
    """La expiración va DENTRO del mensaje firmado, no al lado.

    Si se firmara solo una parte, una cookie legítima recién caducada se convertiría en eterna
    cambiándole el número, que es el único ataque que esta cookie tiene que aguantar.
    """
    caducada = auth.crear_sesion(TOKEN, -1)
    _, _, firma = caducada.partition(".")
    futuro = int(time.time()) + 3600
    assert auth.sesion_valida(f"{futuro}.{firma}", TOKEN) is None
    assert auth.sesion_valida(auth.crear_sesion(TOKEN, 3600), TOKEN) is not None


def test_rotar_el_token_invalida_las_sesiones_vivas():
    """Cambiar el secreto tiene que echar a todo el mundo, y sin lista de sesiones que purgar."""
    vieja = auth.crear_sesion(TOKEN, 3600)
    assert auth.sesion_valida(vieja, TOKEN) is not None
    assert auth.sesion_valida(vieja, TOKEN + "-rotado") is None


def test_basic_entrega_sesion_y_la_segunda_visita_ya_no_pide_nada():
    """El punto de todo esto: entrar una vez con el token y que el navegador siga dentro."""
    cliente = _app()
    primera = cliente.get("/", headers={"Authorization": _basic("quien-sea", TOKEN)})
    assert primera.status_code == 200

    galleta = primera.headers["set-cookie"]
    assert galleta.startswith(f"{auth.COOKIE}=")
    assert "HttpOnly" in galleta, "sin HttpOnly cualquier script de la página lee la sesión"
    assert "SameSite=Lax" in galleta, "SameSite=Lax es lo que hace de token CSRF aquí"
    assert "Path=/" in galleta, "la sesión cubre el puerto entero, no solo la ruta que la emitió"
    assert f"Max-Age={365 * 24 * 3600}" in galleta

    valor = galleta.split(";")[0].split("=", 1)[1]
    # Vaciar el jar del cliente no es limpieza cosmética: sin esto el propio TestClient reenvía la
    # cookie él solo y el control negativo de abajo entra con un 200 que parece del `Authorization`
    # que ya no se manda. La primera versión de este test pasaba por ahí.
    cliente.cookies.clear()
    assert cliente.get("/").status_code == 401, "el jar seguía autorizando: el resto no prueba nada"

    # Sin `Authorization`: es exactamente lo que manda el navegador al volver mañana.
    assert cliente.get("/", headers=_con_cookie(valor)).status_code == 200


def test_la_sesion_tambien_alcanza_la_app_montada():
    """Una puerta, un puerto: la sesión no puede cubrir menos rutas que la cabecera."""
    cliente = _app()
    valor = auth.crear_sesion(TOKEN, 3600)
    for ruta, cuerpo in (("/mcp", "raiz"), ("/api/status", "montada"), ("/", "montada")):
        respuesta = cliente.get(ruta, headers=_con_cookie(valor))
        assert respuesta.status_code == 200, ruta
        assert respuesta.text == cuerpo


def test_bearer_no_recibe_cookie():
    """Un cliente MCP o el CLI no tienen dónde guardarla; darles una es repartir secreto de más."""
    respuesta = _app().get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert respuesta.status_code == 200
    assert "set-cookie" not in respuesta.headers


def test_entrar_con_la_sesion_no_reparte_una_nueva_cada_vez():
    """Renovar en cada respuesta pondría una `Set-Cookie` en cada carga de página sin ganar nada."""
    cliente = _app(duracion=1000)
    fresca = cliente.get("/", headers=_con_cookie(auth.crear_sesion(TOKEN, 900)))
    assert fresca.status_code == 200
    assert "set-cookie" not in fresca.headers


def test_la_sesion_en_uso_se_renueva_antes_de_caducar():
    """Media vida gastada es el punto de renovación: así una sesión usada no caduca nunca."""
    cliente = _app(duracion=1000)
    respuesta = cliente.get("/", headers=_con_cookie(auth.crear_sesion(TOKEN, 400)))
    assert respuesta.status_code == 200
    renovada = respuesta.headers["set-cookie"].split(";")[0].split("=", 1)[1]
    assert auth.sesion_valida(renovada, TOKEN) > time.time() + 900


def test_con_duracion_cero_no_hay_sesion_ninguna():
    """La salida para quien no quiera que el navegador guarde nada: la puerta de siempre."""
    cliente = _app(duracion=0)
    con_basic = cliente.get("/", headers={"Authorization": _basic("quien-sea", TOKEN)})
    assert con_basic.status_code == 200
    assert "set-cookie" not in con_basic.headers
    # Y una cookie perfectamente firmada tampoco abre nada, que es la mitad que se olvida.
    assert cliente.get("/", headers=_con_cookie(auth.crear_sesion(TOKEN, 3600))).status_code == 401


def test_la_sesion_se_encuentra_entre_otras_cookies():
    """El navegador manda todas las cookies del origen juntas, no solo la nuestra."""
    cliente = _app()
    valor = auth.crear_sesion(TOKEN, 3600)
    cabecera = {"Cookie": f"tema=oscuro; {auth.COOKIE}={valor}; otra=cosa"}
    assert cliente.get("/", headers=cabecera).status_code == 200


def test_sin_token_configurado_la_sesion_no_existe():
    """Quien no puso token no gana una cookie: `proteger` sigue devolviendo la misma app."""

    async def ruta(_request):
        return PlainTextResponse("libre")

    app = Starlette(routes=[Route("/mcp", ruta, methods=["GET"])])
    assert auth.proteger(app, "", 3600) is app


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
