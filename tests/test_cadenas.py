"""Tarea 27 de F3 y T12 de `daemon-reparte-el-backend`: las cadenas de respaldo por rol.

Lo que se fija arriba es la RESOLUCIÓN de la cadena con la configuración vigente (REQ-003, REQ-004 y
REQ-014 de F3); el salto en sí se prueba en `test_respaldo.py` y en el bloque de T12 de abajo. Una
cadena es una lista ordenada de pasos, ya sin repetidos, sin el propio modelo principal y solo con
modelos del catálogo de texto o el paso `loaded`.

Defectos (REQ-020, que enmienda REQ-004 de F3), con `loaded` = los alternativos con celda aprobada
que ya están cargados, resueltos al saltar (REQ-019). Sin bloque B no tiene miembros:
- código   -> loaded -> largo
- largo    -> loaded -> código
- mecánico -> loaded -> largo
- visión   -> ninguna
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import cadenas, checks, config, server, topologia

MECANICO = "gemma3-4b"
LARGO = "gemma4-26b-a4b"
CODIGO = "qwen36-35b-a3b"
#: El modelo del rol `fast`, retirado en la 0.30.0. Se conserva como caso de «esto ya NO está en el
#: catálogo», que es exactamente lo que pasó a ser.
RETIRADO = "qwen35-2b"

FIXTURES_TOPOLOGIA = Path(__file__).parent / "fixtures" / "topologia"


def _config_llamaswap(tmp_path: Path, texto: str) -> Path:
    ruta = tmp_path / "config.yaml"
    ruta.write_text(texto, encoding="utf-8")
    return ruta


#: Dos modelos con TTL efectivo 0 (uno por `ttl: 0`, otro por `globalTTL` 0) y uno con TTL 120.
DOS_RESIDENTES = """\
globalTTL: 0
models:
  gemma3-4b: {}
  gemma4-26b-a4b:
    ttl: 120
  qwen35-2b: {}
groups:
  swap:
    swap: true
    members: [gemma4-26b-a4b]
  fijos:
    persistent: true
    exclusive: false
    swap: false
    members: [gemma3-4b, qwen35-2b]
"""


# --- Defectos ---------------------------------------------------------------------------------


def test_las_cadenas_por_defecto_son_las_de_la_spec(recargar_config):
    """REQ-020: `loaded` primero y ninguna lleva al mecánico desde código o largo."""
    recargar_config()
    assert cadenas.resolver("code").pasos == (cadenas.LOADED, LARGO)
    assert cadenas.resolver("long").pasos == (cadenas.LOADED, CODIGO)
    assert cadenas.resolver("mechanical").pasos == (cadenas.LOADED, LARGO)
    # Sin bloque B, las efectivas (REQ-020): `code -> long`, `long -> code`, `mechanical -> long`.
    assert cadenas.resolver("code").modelos == (LARGO,)
    assert cadenas.resolver("long").modelos == (CODIGO,)
    assert cadenas.resolver("mechanical").modelos == (LARGO,)


def test_vision_no_tiene_cadena(recargar_config):
    """Visión queda fuera de `ALLOWED_MODELS` a propósito: su cadena se resuelve vacía ANTES."""
    recargar_config()
    assert cadenas.resolver("vision").modelos == ()


# --- El residente (REQ-023): solo si la config tiene un modelo con TTL efectivo 0 -----------------


def test_sin_config_de_llamaswap_no_hay_residente_ni_cae_al_mecanico(recargar_config, monkeypatch):
    """Sustituye a «sin config, el residente es el mecánico»: el residente fantasma desaparece."""
    recargar_config()
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    assert cadenas.residentes() is None
    lineas = "\n".join(cadenas.describir())
    assert "sin residente" in lineas
    assert MECANICO not in lineas.split("code:")[0], "ni el mecánico como residente"


def test_un_grupo_persistent_con_ttl_no_es_residente(recargar_config, monkeypatch, tmp_path):
    """Sustituye a «el residente sale del grupo persistent»: con la config del 2026-09-15 (4B en un
    grupo `persistent` con TTL 600) llama-swap lo descarga, así que no es residente."""
    recargar_config()
    ruta = tmp_path / "config.yaml"
    ruta.write_bytes((FIXTURES_TOPOLOGIA / "pre-sin-residente-20261006.yaml").read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(ruta))
    assert cadenas.residentes() == ()
    assert cadenas.texto_residentes() == "sin residente"
    # Y la cadena no cambia por haber un grupo persistent: `loaded` no es «el del grupo».
    assert cadenas.resolver("code").pasos == (cadenas.LOADED, LARGO)


def test_con_varios_residentes_se_dicen_todos(recargar_config, monkeypatch, tmp_path):
    """Sustituye a «con varios miembros gana el primero»: ya no se elige uno, se dicen los que hay,
    también los que no están en el catálogo (el del rol retirado): es lo que llama-swap retiene."""
    recargar_config()
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(_config_llamaswap(tmp_path, DOS_RESIDENTES)))
    assert cadenas.residentes() == (MECANICO, RETIRADO)
    assert cadenas.texto_residentes() == f"residente: {MECANICO}, {RETIRADO}"


def test_sin_pyyaml_no_se_sabe_y_no_cae_al_mecanico(recargar_config, monkeypatch, tmp_path):
    """Sustituye a «sin pyyaml cae al mecánico y lo dice»: sin PyYAML no se sabe, y se dice."""
    recargar_config()
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(_config_llamaswap(tmp_path, DOS_RESIDENTES)))
    monkeypatch.setattr(topologia, "yaml", None)
    assert cadenas.residentes() is None
    assert cadenas.texto_residentes().startswith("sin residente")


def test_local_status_dice_las_cadenas_con_loaded(recargar_config, monkeypatch):
    """Sustituye a «local_status dice el residente y su origen»: dice las cadenas con su paso."""
    recargar_config()
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    lineas = cadenas.describir()
    assert f"  code: loaded -> {LARGO}" in lineas
    assert f"  long: loaded -> {CODIGO}" in lineas
    assert f"  mechanical: loaded -> {LARGO}" in lineas
    assert not any("defecto: el modelo del rol" in linea for linea in lineas)


# --- Sobrescribir -----------------------------------------------------------------------------


def test_una_cadena_se_sobrescribe_con_roles_y_modelos(recargar_config):
    recargar_config(LOCAL_DELEGATE_FALLBACK_CODE=f"long, {MECANICO}")
    assert cadenas.resolver("code").modelos == (LARGO, MECANICO)


def test_una_cadena_vacia_desactiva_el_respaldo_de_ese_rol(recargar_config):
    recargar_config(LOCAL_DELEGATE_FALLBACK_LONG="")
    assert cadenas.resolver("long").pasos == ()
    assert cadenas.resolver("code").pasos == (cadenas.LOADED, LARGO), "los demás no cambian"


def test_none_tambien_desactiva_porque_windows_no_guarda_variables_vacias(recargar_config):
    """En Windows fijar una variable a "" la BORRA: en el daemon real la cadena vacía no existe.

    `monkeypatch.setenv` sí guarda "" en el diccionario de Python, así que el test de arriba pasa
    igual y no lo habría destapado. `none` es la forma que funciona en las tres plataformas.
    """
    recargar_config(LOCAL_DELEGATE_FALLBACK_LONG="none")
    assert cadenas.resolver("long").modelos == ()
    assert cadenas.resolver("long").ignorados == ()


def test_un_modelo_desconocido_se_ignora_y_se_informa(recargar_config):
    recargar_config(LOCAL_DELEGATE_FALLBACK_CODE="long,modelo-que-no-existe")
    cadena = cadenas.resolver("code")
    assert cadena.modelos == (LARGO,)
    assert cadena.ignorados == ("modelo-que-no-existe",)


def test_los_repetidos_y_el_propio_modelo_se_quitan(recargar_config):
    """Largo y código consolidados en uno: ese modelo no se reintenta contra sí mismo."""
    recargar_config(LOCAL_DELEGATE_MODEL_CODE=LARGO)
    assert cadenas.resolver("long").pasos == (cadenas.LOADED,)
    assert cadenas.resolver("code").pasos == (cadenas.LOADED,)
    # Y los repetidos dentro de una misma cadena se quitan: «long,code,long» con los dos roles
    # consolidados en un modelo es tres veces el mismo candidato.
    recargar_config(
        LOCAL_DELEGATE_MODEL_CODE=LARGO, LOCAL_DELEGATE_FALLBACK_MECHANICAL="long,code,long"
    )
    assert cadenas.resolver("mechanical").modelos == (LARGO,)


# --- Variables (REQ-014) ----------------------------------------------------------------------


def test_el_respaldo_viene_encendido_con_dos_saltos(recargar_config):
    recargar_config()
    assert config.FALLBACK is True
    assert config.FALLBACK_MAX_HOPS == 2


def test_las_variables_nuevas_estan_en_el_inventario(recargar_config):
    recargar_config()
    for nombre in (
        "LOCAL_DELEGATE_FALLBACK",
        "LOCAL_DELEGATE_FALLBACK_MAX_HOPS",
        "LOCAL_DELEGATE_FALLBACK_MECHANICAL",
        "LOCAL_DELEGATE_FALLBACK_LONG",
        "LOCAL_DELEGATE_FALLBACK_CODE",
        "LOCAL_DELEGATE_FALLBACK_FAST",
        "LLAMASWAP_CONFIG",
        "LLAMASWAP_EXE",
        "LLAMASWAP_LISTEN",
        "LLAMASWAP_WATCH_CONFIG",
    ):
        assert nombre in config.VARIABLES_DE_ENTORNO, nombre


def test_nadie_fuera_de_config_lee_llamaswap_del_entorno():
    """Tres sitios leían `LLAMASWAP_CONFIG` con `os.environ` directo: dos fuentes para un dato.

    El guardián de `test_aislamiento_entorno.py` solo mira `config.py`, así que por ahí la suite
    volvía a heredar el entorno de la máquina.
    """
    paquete = Path(config.__file__).parent
    lectura_directa = re.compile(r"os\.environ[^\n]*LLAMASWAP_")
    culpables = [
        f"{ruta.name}:{numero}"
        for ruta in paquete.rglob("*.py")
        if ruta.name != "config.py"
        for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1)
        if lectura_directa.search(linea)
    ]
    assert culpables == []


# --- doctor -----------------------------------------------------------------------------------


def test_doctor_avisa_de_un_modelo_desconocido_en_una_cadena(recargar_config, tmp_path):
    recargar_config(LOCAL_DELEGATE_FALLBACK_CODE="long,modelo-que-no-existe")
    resultado = checks._probe_fallback(checks.Context(home=tmp_path))
    assert resultado.status == checks.WARN
    assert "modelo-que-no-existe" in resultado.detail
    assert "LOCAL_DELEGATE_FALLBACK_CODE" in resultado.detail


def test_doctor_no_avisa_con_las_cadenas_por_defecto(recargar_config, tmp_path):
    recargar_config()
    resultado = checks._probe_fallback(checks.Context(home=tmp_path))
    assert resultado.status == checks.OK


# El bloque «`fast` es inalcanzable desde las tools» se retiró con el rol (0.30.0): comprobaba que
# ninguna tool enrutaba a él, que era el argumento para quitarlo. Lo que queda por proteger —que su
# modelo ya no se pueda pedir a mano— vive en `test_rol_fast_retirado.py`.


# --- T12 de `daemon-reparte-el-backend`: cadenas sin residente (REQ-019 a REQ-023) -------------
#
# El paso `loaded` sustituye a `residente`: el conjunto de alternativos con celda aprobada que ya
# están cargados, resuelto en el momento del salto. Sin bloque B (sin proveedor registrado) no tiene
# miembros: se salta sin gastar salto y sin tocar la red. Los escenarios van sobre `backend_mock`,
# que responde según el modelo pedido, y miran los `Intento` reales que devuelve `_con_respaldo`.

URL = "http://test-backend/v1/chat/completions"
CAPACIDAD = '{"error":{"message":"unspecific error: upstream command exited prematurely"}}'
HOY = Path(__file__).parent / "fixtures" / "topologia" / "hoy.yaml"
DIFF = "diff --git a/x b/x\n+hola\n"


def _ok(contenido: str = "hecho") -> httpx2.Response:
    return httpx2.Response(
        200, json={"choices": [{"message": {"content": contenido}, "finish_reason": "stop"}]}
    )


def _fallo(status: int = 500, texto: str = "boom") -> httpx2.Response:
    return httpx2.Response(status, text=texto)


def _backend(respuestas: dict) -> list[str]:
    """El POST de chat con una respuesta por modelo; devuelve los modelos pedidos, en orden.

    Un modelo sin respuesta hace fallar el test.
    """
    backend_mock._rutas.clear()
    pedidos: list[str] = []

    def efecto(request: httpx2.Request):
        modelo = json.loads(request.content)["model"]
        pedidos.append(modelo)
        if modelo not in respuestas:
            raise AssertionError(f"se llamó a un modelo sin respuesta: {modelo}")
        return respuestas[modelo]

    backend_mock.post(URL).mock(side_effect=efecto)
    return pedidos


@pytest.fixture
def intentos(monkeypatch) -> list:
    """Los `Intento` de cada `_con_respaldo`, en orden: las llamadas reales al backend."""
    vistos: list = []
    original = server._con_respaldo

    def espia(*args, **kwargs):
        resultado = original(*args, **kwargs)
        vistos.extend(resultado[2])
        return resultado

    monkeypatch.setattr(server, "_con_respaldo", espia)
    return vistos


def _texto(caracteres: int) -> str:
    parrafo = ("palabra " * 375).strip() + "\n\n"
    return (parrafo * (caracteres // len(parrafo) + 1))[:caracteres]


@backend_mock.mock
def test_codigo_nunca_cae_al_mecanico(recargar_config, intentos):
    """Escenario «código nunca cae al mecánico»: el 4B no es candidato, no hay celdas aprobadas."""
    recargar_config()
    _backend({CODIGO: _fallo(500), LARGO: _ok("mensaje"), MECANICO: _ok("del 4B")})

    server.local_commit_msg(diff=DIFF)

    assert intentos[0].modelo == CODIGO
    assert intentos[1].modelo == "gemma4-26b-a4b"
    assert MECANICO not in [i.modelo for i in intentos]


@backend_mock.mock
def test_largo_salta_a_codigo_y_mecanico_a_largo(recargar_config, intentos):
    recargar_config()
    _backend({LARGO: _fallo(500), CODIGO: _ok("resumen"), MECANICO: _ok("del 4B")})
    server.local_summarize(text=_texto(10_000))
    assert "gemma3-4b" not in [i.modelo for i in intentos]
    assert [i.modelo for i in intentos] == [LARGO, CODIGO]

    intentos.clear()
    _backend({MECANICO: _fallo(500), LARGO: _ok("a")})
    server.local_classify(text="hola", labels=["a", "b"])
    assert [i.modelo for i in intentos] == [MECANICO, LARGO]


@backend_mock.mock
def test_fallo_de_capacidad_sin_nada_cargado(recargar_config, intentos):
    """Escenario: sin `loaded` un fallo de capacidad no salta y vuelve el error de siempre."""
    recargar_config()
    _backend({CODIGO: _fallo(500, CAPACIDAD), MECANICO: _ok(), LARGO: _ok()})

    salida = server.local_explain_code(code="x = 1")

    assert [i.modelo for i in intentos] == ["qwen36-35b-a3b"]
    assert salida.startswith("[local-delegate error]")


@backend_mock.mock
def test_loaded_vacio_no_gasta_salto(recargar_config, intentos):
    """Con un solo salto, `code → loaded → long` llega a `long`: el paso vacío no lo gasta."""
    recargar_config(LOCAL_DELEGATE_FALLBACK_MAX_HOPS="1")
    assert config.FALLBACK_MAX_HOPS == 1
    assert cadenas.resolver("code").pasos == (cadenas.LOADED, LARGO)
    _backend({CODIGO: _fallo(500), LARGO: _ok("mensaje")})

    server.local_commit_msg(diff=DIFF)

    assert intentos[-1].modelo == "gemma4-26b-a4b"
    assert [i.modelo for i in intentos] == [CODIGO, LARGO]


def test_miembros_loaded_sin_proveedor_no_consulta_la_red(recargar_config, monkeypatch):
    """Sin bloque B no hay proveedor: `loaded` se resuelve vacío y sin tocar la red (REQ-019)."""
    recargar_config()
    rutas_pedidas: list[str] = []
    original = backend_mock._handler

    def espia(request):
        rutas_pedidas.append(f"{request.method} {request.url}")
        return original(request)

    monkeypatch.setattr(backend_mock, "_handler", espia)
    with backend_mock.mock:
        miembros = cadenas.miembros_loaded(
            "local_commit_msg", CODIGO, propios=frozenset(), nadie_mas=True
        )

    assert miembros == ()
    assert rutas_pedidas == []


@backend_mock.mock
def test_con_proveedor_el_salto_va_al_miembro_de_loaded(recargar_config, intentos):
    """El camino con miembros ya existe (el proveedor lo registra T15): recibe tool y fallido."""
    recargar_config()
    vistos: list[tuple] = []

    def proveedor(tool, fallido, propios, nadie_mas):
        vistos.append((tool, fallido))
        return (MECANICO,)

    cadenas.registrar_proveedor_loaded(proveedor)
    try:
        _backend({CODIGO: _fallo(500), MECANICO: _ok("del 4B"), LARGO: _ok()})
        server.local_commit_msg(diff=DIFF)
    finally:
        cadenas.registrar_proveedor_loaded(None)

    assert vistos == [("local_commit_msg", CODIGO)]
    assert [i.modelo for i in intentos] == [CODIGO, MECANICO]


@pytest.fixture
def status_sin_red(monkeypatch):
    """`local_status` sin backend, GPU ni llama-swap: solo interesa lo que dice de las cadenas."""
    monkeypatch.setattr(
        server,
        "sondear_backend",
        lambda: server.EstadoBackend(False, [], True, "rechazada", "sin red en los tests", None),
    )
    for nombre in ("_vram_info", "_ram_info", "_llamaswap_groups"):
        monkeypatch.setattr(server, nombre, lambda: None)
    monkeypatch.setattr(server, "_port_listening", lambda *_: False)


def test_el_estado_ya_no_habla_de_un_residente_fantasma(
    recargar_config, monkeypatch, tmp_path, status_sin_red
):
    """Escenario: con la config de hoy (un solo grupo `swap`, TTL 120) no hay residente."""
    recargar_config()
    copia = tmp_path / "llamaswap.yaml"
    copia.write_bytes(HOY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copia))
    doctor = checks._probe_fallback(checks.Context(home=tmp_path))
    texto = server.local_status() + "\n" + doctor.detail

    assert "residente gemma3-4b" not in texto
    assert "defecto: el modelo del rol" not in texto
    assert "sin residente" in texto
    assert "sin residente" in doctor.detail
    assert doctor.detail == "cadenas válidas; sin residente"


def test_con_ttl_0_en_un_grupo_persistent_describir_dice_el_residente(
    recargar_config, monkeypatch, tmp_path
):
    recargar_config()
    ruta = tmp_path / "llamaswap.yaml"
    ruta.write_text(
        "globalTTL: 120\n"
        "models:\n"
        "  gemma3-4b:\n    ttl: 0\n"
        "  gemma4-26b-a4b: {}\n"
        "  qwen36-35b-a3b: {}\n"
        "groups:\n"
        "  swap:\n    swap: true\n    members: [gemma4-26b-a4b, qwen36-35b-a3b]\n"
        "  resident:\n    persistent: true\n    exclusive: false\n    members: [gemma3-4b]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(ruta))

    lineas = "\n".join(cadenas.describir())

    assert "residente: gemma3-4b" in lineas
    assert "sin residente" not in lineas


# --- Corrección tras la revisión de la ola 6 ---------------------------------------------------


@backend_mock.mock
def test_un_miembro_de_loaded_que_repite_un_paso_posterior_no_se_llama_dos_veces(recargar_config):
    """`code -> loaded -> long` con `loaded` = el 26B: si el 26B falla, el paso `long` no lo repite."""
    recargar_config()
    cadenas.registrar_proveedor_loaded(lambda *_: (LARGO,))
    try:
        pedidos = _backend({CODIGO: _fallo(500, "original"), LARGO: _fallo(500, "otro")})
        salida = server.local_commit_msg(diff=DIFF)
    finally:
        cadenas.registrar_proveedor_loaded(None)

    assert pedidos == [CODIGO, LARGO]
    # REQ-008: la línea de «también fallaron» no repite modelo.
    linea = next(linea for linea in salida.splitlines() if "también fallaron" in linea)
    assert linea.count(LARGO) == 1, linea


def test_sin_topologia_el_residente_dice_el_motivo(recargar_config, monkeypatch, tmp_path):
    """Con una config legible pero `matrix`, «no se sabe: matrix», como «Turno: no (matrix)»."""
    recargar_config()
    matrix = (
        "models:\n  gemma4-26b-a4b: {}\n  qwen36-35b-a3b: {}\n"
        "routing:\n  router:\n    use: matrix\n    settings:\n      matrix: {}\n"
    )
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(_config_llamaswap(tmp_path, matrix)))
    foto = topologia.foto()
    assert isinstance(foto, topologia.SinTopologia) and foto.motivo == topologia.MATRIX

    assert cadenas.texto_residentes() == "sin residente (no se sabe: matrix)"
    assert "  sin residente (no se sabe: matrix)" in cadenas.describir()
    monkeypatch.delenv("LLAMASWAP_CONFIG")
    assert cadenas.texto_residentes() == "sin residente (no se sabe: sin LLAMASWAP_CONFIG)"
