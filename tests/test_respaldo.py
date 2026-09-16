"""Tarea 28 de F3: el salto al respaldo, dentro de la plaza de concurrencia.

Los escenarios de la spec (REQ-002 a REQ-019) sobre `backend_mock`, con un backend que responde
**según el modelo pedido**: así cada test ve a qué modelos se llamó y en qué orden, que es lo único
que distingue un salto de un reintento. Los nombres son los defectos del paquete; el residente, sin
`LLAMASWAP_CONFIG`, es el del rol mecánico.

La batería de tools en camino feliz no sirve aquí: da lo mismo con el interruptor roto. Cada test
fija un fallo concreto y mira las llamadas.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import backend_mock
import httpx2

from local_delegate import config, enfriamiento, preguntas, server
from local_delegate.fallos import Clase

URL = "http://test-backend/v1/chat/completions"
MECANICO = "gemma3-4b"
LARGO = "gemma4-26b-a4b"
CODIGO = "qwen36-35b-a3b"
VISION = "gemma4-12b"
CAPACIDAD = '{"error":{"message":"unspecific error: upstream command exited prematurely"}}'


def _ok(contenido: str = "hecho") -> httpx2.Response:
    return httpx2.Response(
        200, json={"choices": [{"message": {"content": contenido}, "finish_reason": "stop"}]}
    )


def _fallo(status: int = 500, texto: str = "boom") -> httpx2.Response:
    return httpx2.Response(status, text=texto)


def _backend(respuestas: dict) -> list[str]:
    """Registra el POST de chat con una respuesta por modelo; devuelve la lista de modelos pedidos.

    El valor puede ser una respuesta, una excepción o una lista que se consume en orden (la
    última se repite).
    """
    # `backend_mock` atiende con la PRIMERA ruta que casa: sin limpiar, un segundo `_backend` en el
    # mismo test no recibiría ninguna llamada.
    backend_mock._rutas.clear()
    pedidos: list[str] = []
    pendientes = {m: list(r) if isinstance(r, list) else [r] for m, r in respuestas.items()}

    def efecto(request: httpx2.Request):
        modelo = json.loads(request.content)["model"]
        pedidos.append(modelo)
        cola = pendientes.get(modelo)
        if cola is None:
            raise AssertionError(f"se llamó a un modelo sin respuesta: {modelo}")
        return cola.pop(0) if len(cola) > 1 else cola[0]

    backend_mock.post(URL).mock(side_effect=efecto)
    return pedidos


def _estado_fichero(tmp_path: Path) -> Path:
    return tmp_path / "enfriamiento.json"


def _enfriar(tmp_path: Path, modelo: str) -> None:
    enfriamiento.Estado(
        _estado_fichero(tmp_path), fallos=1, espera_s=120, espera_max_s=900
    ).registrar_fallo(modelo, Clase.MODELO)


def _entradas(tmp_path: Path) -> dict:
    ruta = _estado_fichero(tmp_path)
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {}


def _ultimo_evento(tmp_path: Path) -> dict:
    lineas = []
    for fichero in sorted(tmp_path.glob("usage*.jsonl")):
        lineas += fichero.read_text(encoding="utf-8").splitlines()
    return json.loads(lineas[-1])


def _texto(caracteres: int) -> str:
    parrafo = ("palabra " * 375).strip() + "\n\n"  # 3 000 chars por párrafo
    return (parrafo * (caracteres // len(parrafo) + 1))[:caracteres]


# --- Escenario: el modelo largo falla y responde el residente ---------------------------------


@backend_mock.mock
def test_el_largo_falla_y_responde_el_residente(recargar_config, tmp_path):
    recargar_config()
    pedidos = _backend({LARGO: _fallo(500), MECANICO: _ok("resumen del residente")})

    salida = server.local_summarize(text=_texto(10_000))

    assert pedidos == [LARGO, MECANICO]
    assert "resumen del residente" in salida
    aviso = salida.split("resumen del residente", 1)[1]
    assert MECANICO in aviso and LARGO in aviso and "http_500" in aviso
    assert _ultimo_evento(tmp_path)["model"] == MECANICO


# --- Escenario: la entrada no cabe en el respaldo ---------------------------------------------


@backend_mock.mock
def test_la_entrada_que_no_cabe_en_el_respaldo_da_el_error_de_hoy(recargar_config, tmp_path):
    texto = _texto(30_000)  # cabe en largo (48 000); ni residente ni código (20 000) la admiten

    recargar_config(LOCAL_DELEGATE_FALLBACK="0", LOCAL_DELEGATE_COOLDOWN="0")
    pedidos_hoy = _backend({LARGO: _fallo(500)})
    error_de_hoy = server.local_summarize(text=texto)

    # Las variables se ENCIENDEN a mano: `recargar_config` solo añade, y sin esto la segunda pasada
    # seguiría con el mecanismo apagado y el test no distinguiría nada.
    recargar_config(LOCAL_DELEGATE_FALLBACK="1", LOCAL_DELEGATE_COOLDOWN="1")
    assert config.FALLBACK and config.COOLDOWN
    pedidos = _backend({LARGO: _fallo(500), MECANICO: _ok(), CODIGO: _ok()})
    salida = server.local_summarize(text=texto)

    assert pedidos_hoy == [LARGO]
    assert pedidos == [LARGO], "no se llama a un candidato que no admite la entrada"
    assert salida == error_de_hoy


# --- Escenario: un 400 no dispara el respaldo -------------------------------------------------


@backend_mock.mock
def test_un_400_no_salta_ni_cuenta_y_conserva_el_reintento_sin_schema(recargar_config, tmp_path):
    recargar_config()
    pedidos = _backend({MECANICO: _fallo(400, "schema no soportado"), LARGO: _ok('{"a": 1}')})

    salida = server.local_extract(fields=["a"], text="texto corto")

    assert pedidos == [MECANICO, MECANICO], "el reintento sin schema sigue; no hay salto"
    assert "_local_delegate" in salida
    assert _entradas(tmp_path) == {}


# --- Escenario: el backend está caído ---------------------------------------------------------


@backend_mock.mock
def test_el_backend_caido_no_salta_ni_enfria(recargar_config, tmp_path, monkeypatch):
    recargar_config()
    monkeypatch.setattr(preguntas, "preguntar", lambda *a, **k: None)
    pedidos = _backend({MECANICO: httpx2.ConnectError("x"), LARGO: _ok()})

    salida = server.local_classify(text="hola", labels=["a", "b"])

    assert pedidos == [MECANICO]
    assert "no se pudo conectar" in salida
    assert _entradas(tmp_path) == {}


# --- Escenario: tres fallos seguidos enfrían el modelo ----------------------------------------


@backend_mock.mock
def test_tres_fallos_desde_dos_procesos_enfrian_y_la_cuarta_va_directa(recargar_config, tmp_path):
    recargar_config()
    pedidos = _backend({CODIGO: _fallo(500), MECANICO: _ok("explicado")})

    server.local_explain_code(code="x = 1")
    server.local_explain_code(code="x = 2")
    # El tercer fallo lo registra «otro proceso»: otra instancia sobre el mismo fichero.
    enfriamiento.desde_config().registrar_fallo(CODIGO, Clase.MODELO)
    assert enfriamiento.desde_config().consultar(CODIGO) is not None

    pedidos.clear()
    salida = server.local_explain_code(code="x = 3")

    assert pedidos == [MECANICO], "el modelo enfriado no recibe la cuarta llamada"
    assert "explicado" in salida and "enfriamiento" in salida


# --- Escenario: en enfriamiento y sin alternativa, falla al momento ---------------------------


@backend_mock.mock
def test_enfriado_sin_alternativa_falla_al_momento(recargar_config, tmp_path):
    recargar_config(LOCAL_DELEGATE_FALLBACK_MECHANICAL="none")
    _enfriar(tmp_path, MECANICO)
    pedidos = _backend({MECANICO: _ok()})

    inicio = time.monotonic()
    salida = server.local_classify(text="hola", labels=["a", "b"])

    assert time.monotonic() - inicio < 1.0
    assert pedidos == []
    assert salida.startswith("[local-delegate error]")
    assert MECANICO in salida and "enfriamiento" in salida and "hasta" in salida


# --- Escenarios: vence el enfriamiento --------------------------------------------------------


def _vencido(tmp_path: Path, modelo: str, espera_s: float = 120.0) -> None:
    datos = {modelo: {"fallos": 0, "espera_s": espera_s, "hasta": time.time() - 1, "reentradas": 1}}
    _estado_fichero(tmp_path).write_text(json.dumps(datos), encoding="utf-8")


@backend_mock.mock
def test_vence_el_enfriamiento_y_la_prueba_sale_bien(recargar_config, tmp_path):
    recargar_config()
    _vencido(tmp_path, MECANICO)
    pedidos = _backend({MECANICO: _ok("a")})

    server.local_classify(text="hola", labels=["a", "b"])

    assert pedidos == [MECANICO]
    assert MECANICO not in _entradas(tmp_path)


@backend_mock.mock
def test_vence_el_enfriamiento_y_la_prueba_falla_dobla_la_espera(recargar_config, tmp_path):
    recargar_config()
    _vencido(tmp_path, MECANICO)
    pedidos = _backend({MECANICO: _fallo(500), LARGO: _ok("a")})

    server.local_classify(text="hola", labels=["a", "b"])

    assert pedidos == [MECANICO, LARGO]
    assert _entradas(tmp_path)[MECANICO]["espera_s"] == 240.0


# --- Escenario: traducción en trozos con respaldo a mitad (REQ-006) ---------------------------


@backend_mock.mock
def test_traduccion_en_cuatro_trozos_cambia_de_modelo_una_sola_vez(recargar_config, tmp_path):
    recargar_config()
    pedidos = _backend({LARGO: [_ok("uno"), _fallo(500), _ok("NO")], MECANICO: _ok("otro")})

    salida = server.local_translate(target_lang="inglés", text=_texto(12_000))

    assert pedidos == [LARGO, LARGO, MECANICO, MECANICO, MECANICO]
    assert "NO" not in salida
    assert "trozo 2" in salida and MECANICO in salida


@backend_mock.mock
def test_commit_en_map_reduce_salta_y_sigue_con_el_respaldo(recargar_config, tmp_path):
    recargar_config()
    pedidos = _backend({CODIGO: _fallo(500), MECANICO: _ok("- a: cambia")})
    diff = "".join(
        f"diff --git a/f{i}.py b/f{i}.py\n" + "+linea de codigo nueva\n" * 200 for i in range(6)
    )
    assert len(diff) > config.max_chars_for_role("code")

    salida = server.local_commit_msg(diff=diff)

    assert pedidos.count(CODIGO) == 1, "tras el salto, los trozos siguientes van al respaldo"
    assert set(pedidos) == {CODIGO, MECANICO}
    assert not salida.startswith("[local-delegate error]")


@backend_mock.mock
def test_en_map_reduce_de_largo_el_respaldo_esta_muerto_por_construccion(recargar_config, tmp_path):
    # Los trozos miden 0,8 x 48 000 = 38 400 chars y ningún candidato de 20 000 los admite
    # (REQ-003): el salto no puede ocurrir con los topes de hoy. Se fija para no descubrirlo en
    # producción.
    recargar_config()
    pedidos = _backend({LARGO: _fallo(500), MECANICO: _ok(), CODIGO: _ok()})

    salida = server.local_summarize(text=_texto(60_000))

    assert pedidos == [LARGO]
    assert salida.startswith("[local-delegate error]")


# --- Escenario: el modelo no cabe en la VRAM (REQ-018) ----------------------------------------


@backend_mock.mock
def test_capacidad_solo_salta_al_residente_y_sin_segundo_salto(recargar_config, tmp_path):
    recargar_config()
    pedidos = _backend({CODIGO: _fallo(500, CAPACIDAD), MECANICO: _fallo(500), LARGO: _ok()})

    salida = server.local_explain_code(code="x = 1")

    assert pedidos == [CODIGO, MECANICO], "tras capacidad, residente y nada más"
    assert salida.startswith("[local-delegate error]")
    assert CODIGO not in _entradas(tmp_path), "capacidad no enfría"


@backend_mock.mock
def test_capacidad_del_residente_no_salta_a_un_modelo_grande(recargar_config, tmp_path):
    recargar_config()
    pedidos = _backend({MECANICO: _fallo(500, CAPACIDAD), LARGO: _ok()})

    server.local_classify(text="hola", labels=["a", "b"])

    assert pedidos == [MECANICO]


# --- Escenario: un modelo de razonamiento agota max_tokens (REQ-019) --------------------------


@backend_mock.mock
def test_razonamiento_agotado_no_salta_ni_enfria(recargar_config, tmp_path):
    recargar_config()
    agotado = httpx2.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": "", "reasoning_content": "pienso"},
                    "finish_reason": "length",
                }
            ]
        },
    )
    pedidos = _backend({MECANICO: agotado, LARGO: _ok()})

    salida = server.local_classify(text="hola", labels=["a", "b"])

    assert pedidos == [MECANICO]
    assert "max_tokens" in salida
    assert _entradas(tmp_path) == {}


@backend_mock.mock
def test_length_sin_razonamiento_es_sin_clasificar_y_no_salta(recargar_config, tmp_path):
    recargar_config()
    nulo = httpx2.Response(
        200, json={"choices": [{"message": {"content": None}, "finish_reason": "length"}]}
    )
    pedidos = _backend({MECANICO: nulo, LARGO: _ok()})

    server.local_classify(text="hola", labels=["a", "b"])

    assert pedidos == [MECANICO]


# --- Escenario: timeout mientras el modelo carga ----------------------------------------------


@backend_mock.mock
def test_timeout_durante_la_carga_no_enfria(recargar_config, tmp_path):
    recargar_config(LOCAL_DELEGATE_FALLBACK="0")
    _backend({MECANICO: httpx2.ReadTimeout("x")})

    server.local_classify(text="hola", labels=["a", "b"])

    assert _entradas(tmp_path) == {}


@backend_mock.mock
def test_timeout_con_el_modelo_cargado_cuenta_y_no_salta(recargar_config, tmp_path, monkeypatch):
    recargar_config()
    monkeypatch.setattr(server._SondaDeCarga, "modelo_cargado", lambda self, **_: True)
    pedidos = _backend({MECANICO: httpx2.ReadTimeout("x"), LARGO: _ok()})

    server.local_classify(text="hola", labels=["a", "b"])

    assert pedidos == [MECANICO], "D-2: un timeout de lectura no dispara el respaldo"
    assert _entradas(tmp_path)[MECANICO]["fallos"] == 1


# --- Escenario: benchmark con el mecanismo apagado --------------------------------------------


@backend_mock.mock
def test_con_el_respaldo_apagado_ningun_fallo_salta(recargar_config, tmp_path):
    recargar_config(LOCAL_DELEGATE_FALLBACK="0")
    pedidos = _backend({CODIGO: _fallo(500), MECANICO: _ok()})

    server.local_explain_code(code="x = 1")

    assert pedidos == [CODIGO]


# --- Escenario: modelo explícito (REQ-005) ----------------------------------------------------


@backend_mock.mock
def test_modelo_explicito_se_envia_aunque_este_enfriado_y_actualiza_su_estado(
    recargar_config, tmp_path
):
    recargar_config()
    _enfriar(tmp_path, LARGO)
    pedidos = _backend({LARGO: _ok("hecho por el largo"), MECANICO: _ok()})

    salida = server.local_delegate(task="t", input="x", output_format="texto", model=LARGO)

    assert pedidos == [LARGO]
    assert "hecho por el largo" in salida
    assert LARGO not in _entradas(tmp_path), "el éxito lo deja limpio"


@backend_mock.mock
def test_modelo_explicito_que_falla_no_salta(recargar_config, tmp_path):
    recargar_config()
    pedidos = _backend({LARGO: _fallo(500), MECANICO: _ok()})

    server.local_delegate(task="t", input="x", output_format="texto", model=LARGO)

    assert pedidos == [LARGO]


@backend_mock.mock
def test_el_modelo_elegido_en_la_pregunta_cuenta_como_explicito(
    recargar_config, tmp_path, monkeypatch
):
    recargar_config()
    _enfriar(tmp_path, LARGO)

    class _Eleccion:
        modelo = LARGO

    monkeypatch.setattr(preguntas, "preguntar", lambda *a, **k: _Eleccion())
    pedidos = _backend({LARGO: _ok(), MECANICO: _ok()})

    server.local_delegate(task="t", input="x", output_format="texto", model="no-existe")

    assert pedidos == [LARGO]


# --- Escenario: mecanismo apagado. El caso que distingue el interruptor -----------------------


@backend_mock.mock
def test_con_las_dos_variables_apagadas_es_el_comportamiento_de_hoy(recargar_config, tmp_path):
    recargar_config(LOCAL_DELEGATE_FALLBACK="0", LOCAL_DELEGATE_COOLDOWN="0")
    _enfriar(tmp_path, CODIGO)
    antes = _estado_fichero(tmp_path).read_bytes()
    pedidos = _backend({CODIGO: _fallo(500), MECANICO: _ok()})

    salida = server.local_explain_code(code="x = 1")

    assert pedidos == [CODIGO], "una sola llamada, al principal, aunque el fichero lo enfríe"
    assert salida == f"[local-delegate error] {CODIGO} respondió 500: boom"
    assert _estado_fichero(tmp_path).read_bytes() == antes


@backend_mock.mock
def test_el_mismo_caso_con_el_mecanismo_encendido_salta(recargar_config, tmp_path):
    recargar_config()
    _enfriar(tmp_path, CODIGO)
    pedidos = _backend({CODIGO: _fallo(500), MECANICO: _ok("explicado")})

    salida = server.local_explain_code(code="x = 1")

    assert pedidos == [MECANICO]
    assert "explicado" in salida


# --- Escenario: estado ilegible ---------------------------------------------------------------


@backend_mock.mock
def test_con_el_estado_corrupto_se_sigue_sin_enfriamiento(recargar_config, tmp_path):
    recargar_config()
    _estado_fichero(tmp_path).write_text("{no es json", encoding="utf-8")
    pedidos = _backend({MECANICO: _ok("a")})

    salida = server.local_classify(text="hola", labels=["a", "b"])

    assert pedidos == [MECANICO]
    assert salida == "a"


# --- REQ-002: tope de saltos y clase que corta la cadena --------------------------------------


@backend_mock.mock
def test_recorre_los_dos_saltos_de_la_cadena(recargar_config, tmp_path):
    """Con el rol `fast` retirado (0.30.0) quedan tres modelos de texto, así que una cadena no
    puede tener más de dos candidatos distintos del principal: este test pasa a comprobar que los
    **recorre los dos** y que ahí se acaba. Que el tope CORTA lo prueba el de abajo, bajándolo a 1.
    """
    recargar_config(LOCAL_DELEGATE_FALLBACK_CODE="residente,long")
    pedidos = _backend({CODIGO: _fallo(500), MECANICO: _fallo(500), LARGO: _fallo(500)})

    server.local_explain_code(code="x = 1")

    assert pedidos == [CODIGO, MECANICO, LARGO]


@backend_mock.mock
def test_el_tope_de_saltos_es_configurable(recargar_config, tmp_path):
    recargar_config(LOCAL_DELEGATE_FALLBACK_MAX_HOPS="1")
    pedidos = _backend({CODIGO: _fallo(500), MECANICO: _fallo(500), LARGO: _ok()})

    server.local_explain_code(code="x = 1")

    assert pedidos == [CODIGO, MECANICO]


@backend_mock.mock
def test_un_fallo_de_otra_clase_en_el_respaldo_corta_la_cadena(recargar_config, tmp_path):
    recargar_config()
    pedidos = _backend({CODIGO: _fallo(500), MECANICO: _fallo(400, "malo"), LARGO: _ok()})

    server.local_explain_code(code="x = 1")

    assert pedidos == [CODIGO, MECANICO]


# --- REQ-008: fallan también los respaldos ----------------------------------------------------


@backend_mock.mock
def test_si_fallan_los_respaldos_vuelve_el_error_original_y_la_lista(recargar_config, tmp_path):
    recargar_config()
    _backend({CODIGO: _fallo(500, "original"), MECANICO: _fallo(502), LARGO: _fallo(503)})

    salida = server.local_explain_code(code="x = 1")

    primera, *resto = salida.splitlines()
    assert primera == f"[local-delegate error] {CODIGO} respondió 500: original"
    detalle = "\n".join(resto)
    assert f"{MECANICO} (http_502)" in detalle and f"{LARGO} (http_503)" in detalle
    entradas = _entradas(tmp_path)
    assert all(entradas[m]["fallos"] == 1 for m in (CODIGO, MECANICO, LARGO))


# --- REQ-007: el aviso nunca se mezcla con el contenido ---------------------------------------


@backend_mock.mock
def test_en_extract_el_aviso_va_en_los_metadatos(recargar_config, tmp_path):
    recargar_config()
    _backend({MECANICO: _fallo(500), LARGO: _ok('{"a": 1}')})

    datos = server.local_extract(fields=["a"], text="texto corto")

    assert datos["a"] == 1
    respaldo = datos["_local_delegate"]["respaldo"]
    assert respaldo["respondio"] == LARGO and respaldo["en_lugar_de"] == MECANICO
    assert respaldo["motivo"] == "http_500"


@backend_mock.mock
def test_en_boilerplate_el_aviso_va_en_el_recibo_y_no_en_el_fichero(recargar_config, tmp_path):
    recargar_config()
    _backend({CODIGO: _fallo(500), MECANICO: _ok("def f():\n    return 1")})
    destino = tmp_path / "gen.py"

    recibo = server.local_boilerplate(spec="f", language="python", target=str(destino))

    # `_escribir_destino` termina el fichero en salto de línea; lo que importa es que no hay aviso.
    assert destino.read_text(encoding="utf-8") == "def f():\n    return 1\n"
    assert MECANICO in recibo and CODIGO in recibo


@backend_mock.mock
def test_en_boilerplate_no_se_escribe_si_fallan_todos(recargar_config, tmp_path):
    recargar_config()
    _backend({CODIGO: _fallo(500), MECANICO: _fallo(500), LARGO: _fallo(500)})
    destino = tmp_path / "gen.py"

    server.local_boilerplate(spec="f", language="python", target=str(destino))

    assert not destino.exists()


# --- Visión: enfriamiento sí, respaldo no -----------------------------------------------------


@backend_mock.mock
def test_vision_enfriada_falla_al_momento_sin_respaldo(recargar_config, tmp_path):
    recargar_config()
    _enfriar(tmp_path, VISION)
    imagen = tmp_path / "x.png"
    imagen.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    pedidos = _backend({VISION: _ok(), MECANICO: _ok()})

    salida = server.local_describe_image(path=str(imagen))

    assert pedidos == []
    assert VISION in salida and "enfriamiento" in salida


@backend_mock.mock
def test_vision_que_falla_no_salta(recargar_config, tmp_path):
    recargar_config()
    imagen = tmp_path / "x.png"
    imagen.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 16)
    pedidos = _backend({VISION: _fallo(500), MECANICO: _ok()})

    server.local_describe_image(path=str(imagen))

    assert pedidos == [VISION]


# --- REQ-017: el salto ocupa la misma plaza ---------------------------------------------------


def test_el_salto_no_suelta_la_plaza_entre_el_principal_y_el_respaldo(
    recargar_config, tmp_path, monkeypatch
):
    recargar_config()
    orden: list[tuple[str, str]] = []
    dentro = 0
    pico = 0
    cerrojo = threading.Lock()
    principal_de_a = threading.Event()

    def post_chat(model, _payload):
        nonlocal dentro, pico
        with cerrojo:
            dentro += 1
            pico = max(pico, dentro)
            orden.append((threading.current_thread().name, model))
        if threading.current_thread().name == "A" and model == CODIGO:
            principal_de_a.set()
        time.sleep(0.1)
        with cerrojo:
            dentro -= 1
        if model == CODIGO:
            return server.ChatResult(text="x", ok=False, error="http_500", clase=Clase.MODELO)
        return server.ChatResult(text="ok", ok=True, finish_reason="stop")

    monkeypatch.setattr(server, "_post_chat", post_chat)
    monkeypatch.setattr(server, "_chat_slots", threading.BoundedSemaphore(1))

    def llamar() -> None:
        server._chat(CODIGO, "s", "u", 8, rol="code")

    a = threading.Thread(target=llamar, name="A")
    b = threading.Thread(target=llamar, name="B")
    a.start()
    assert principal_de_a.wait(timeout=5)
    b.start()  # B ya espera la plaza cuando A falla: si A la soltara, B se colaría
    a.join(timeout=5)
    b.join(timeout=5)

    assert pico == 1
    assert [hilo for hilo, _ in orden] == ["A", "A", "B", "B"], orden


# --- El camino feliz no escribe el estado -----------------------------------------------------


@backend_mock.mock
def test_el_camino_feliz_no_crea_el_fichero_de_estado(recargar_config, tmp_path):
    recargar_config()
    _backend({MECANICO: _ok("a")})

    server.local_classify(text="hola", labels=["a", "b"])

    assert not _estado_fichero(tmp_path).exists()
