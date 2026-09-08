"""`local_boilerplate` escribe el código en disco y solo devuelve un recibo.

El objetivo del cambio es que el código generado **no entre al contexto de quien llama**, así que
casi todos los tests de aquí comprueban lo mismo desde ángulos distintos: qué acabó en el archivo
frente a qué acabó en el valor de retorno.

Dos de ellos son controles negativos sobre el backend (`call_count == 0`): la validación del
destino tiene que fallar **antes** de gastar inferencia, porque generar código para tirarlo es el
peor de los dos errores posibles.
"""

from __future__ import annotations

import json

import backend_mock
import httpx2
import pytest

from local_delegate import config, server

URL = "http://test-backend/v1/chat/completions"


def _responde(contenido: str, *, finish_reason: str = "stop", status: int = 200):
    """Registra la ruta del backend y devuelve el objeto de ruta, para mirarle el call_count."""
    if status != 200:
        return backend_mock.post(URL).mock(return_value=httpx2.Response(status, text="boom"))
    return backend_mock.post(URL).mock(
        return_value=httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": contenido}, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 300},
            },
        )
    )


@pytest.fixture(autouse=True)
def _backend_local(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")


# --- El ahorro: el código va al archivo, el recibo al contexto -------------------------
@backend_mock.mock
def test_escribe_el_codigo_y_devuelve_solo_el_recibo(tmp_path):
    codigo = "def suma(a, b):\n    return a + b\n"
    _responde(codigo)
    destino = tmp_path / "suma.py"

    salida = server.local_boilerplate("una función suma", "python", str(destino))

    assert destino.read_text(encoding="utf-8") == codigo
    # Lo que de verdad se está probando: el cuerpo del código NO viaja de vuelta.
    assert "return a + b" not in salida
    assert salida.startswith("[escrito] ")
    assert str(destino) in salida
    assert "2 líneas" in salida and f"{len(codigo)} chars" in salida


@backend_mock.mock
def test_el_recibo_es_mucho_mas_corto_que_el_codigo(tmp_path):
    """Control de magnitud: si el recibo creciera con el código, no habría ahorro que contar."""
    codigo = "".join(f"def f{i}():\n    return {i}\n" for i in range(400))
    _responde(codigo)

    salida = server.local_boilerplate("400 funciones", "python", str(tmp_path / "g.py"))

    assert len(codigo) > 8000  # el caso que importa: una salida que sí pesa
    assert len(salida) < 200


@backend_mock.mock
def test_quita_los_fences_antes_de_escribir(tmp_path):
    """Si los fences se quitaran en quien llama, al archivo le entrarían las ``` igual."""
    _responde("```python\nprint('hola')\n```")
    destino = tmp_path / "h.py"

    server.local_boilerplate("un hola mundo", "python", str(destino))

    assert destino.read_text(encoding="utf-8") == "print('hola')\n"


@backend_mock.mock
def test_garantiza_el_salto_final(tmp_path):
    """`.strip()` de `_post_chat` deja el código sin newline final; el archivo no debe salir así."""
    _responde("x = 1")
    destino = tmp_path / "s.py"

    server.local_boilerplate("una constante", "python", str(destino))

    assert destino.read_bytes() == b"x = 1\n"


@backend_mock.mock
def test_crea_los_directorios_que_falten(tmp_path):
    _responde("x = 1\n")
    destino = tmp_path / "a" / "b" / "c.py"

    server.local_boilerplate("una constante", "python", str(destino))

    assert destino.read_text(encoding="utf-8") == "x = 1\n"


@backend_mock.mock
def test_el_separador_no_depende_del_sistema(tmp_path):
    """Se escribe con LF explícito: en Windows el modo texto convertiría cada \\n en \\r\\n."""
    _responde("a = 1\nb = 2\n")
    destino = tmp_path / "eol.py"

    server.local_boilerplate("dos constantes", "python", str(destino))

    crudo = destino.read_bytes()
    assert crudo == b"a = 1\nb = 2\n"
    assert b"\r\n" not in crudo


# --- Validación del destino: falla ANTES de gastar backend -----------------------------
@backend_mock.mock
def test_ruta_relativa_falla_sin_gastar_backend(tmp_path):
    ruta = _responde("no deberia generarse")

    with pytest.raises(ValueError, match="absoluta"):
        server.local_boilerplate("lo que sea", "python", "relativo.py")

    assert ruta.call_count == 0  # control negativo: no se pagó inferencia


@backend_mock.mock
def test_no_pisa_un_archivo_existente_ni_gasta_backend(tmp_path):
    ruta = _responde("codigo nuevo")
    destino = tmp_path / "ya.py"
    destino.write_text("NO ME PISES\n", encoding="utf-8")

    with pytest.raises(ValueError, match="overwrite"):
        server.local_boilerplate("otra cosa", "python", str(destino))

    assert destino.read_text(encoding="utf-8") == "NO ME PISES\n"
    assert ruta.call_count == 0


@backend_mock.mock
def test_overwrite_true_si_pisa(tmp_path):
    _responde("codigo nuevo\n")
    destino = tmp_path / "ya.py"
    destino.write_text("viejo\n", encoding="utf-8")

    server.local_boilerplate("otra cosa", "python", str(destino), overwrite=True)

    assert destino.read_text(encoding="utf-8") == "codigo nuevo\n"


@backend_mock.mock
def test_un_directorio_como_target_no_se_confunde_con_archivo_existente(tmp_path):
    """Sin la comprobación de `is_dir()` el error hablaría de un archivo que no existe."""
    _responde("x")
    carpeta = tmp_path / "soy_carpeta"
    carpeta.mkdir()

    with pytest.raises(ValueError, match="directorio"):
        server.local_boilerplate("algo", "python", str(carpeta))


@backend_mock.mock
def test_target_vacio_falla(tmp_path):
    ruta = _responde("x")

    with pytest.raises(ValueError, match="obligatorio"):
        server.local_boilerplate("algo", "python", "   ")

    assert ruta.call_count == 0


@backend_mock.mock
def test_respeta_las_raices_permitidas(tmp_path, monkeypatch):
    """`LOCAL_DELEGATE_ALLOWED_DIRS` acotaba solo la lectura; ahora también dónde se escribe."""
    ruta = _responde("x")
    monkeypatch.setattr(config, "ALLOWED_DIRS", [tmp_path / "permitido"])

    with pytest.raises(ValueError, match="raíces permitidas"):
        server.local_boilerplate("algo", "python", str(tmp_path / "fuera" / "x.py"))

    assert ruta.call_count == 0


# --- Errores del backend: no se escribe basura con nombre de código --------------------
@backend_mock.mock
def test_un_fallo_del_backend_no_deja_archivo(tmp_path):
    _responde("", status=500)
    destino = tmp_path / "roto.py"

    salida = server.local_boilerplate("algo", "python", str(destino))

    assert not destino.exists()
    assert "[local-delegate error]" in salida


@backend_mock.mock
def test_la_salida_truncada_avisa_en_el_recibo_y_no_en_el_archivo(tmp_path):
    """El aviso de `max_tokens` es para quien llama; dentro del archivo sería basura."""
    _responde("def f():\n    pass\n", finish_reason="length")
    destino = tmp_path / "t.py"

    salida = server.local_boilerplate("algo", "python", str(destino))

    assert "truncada por max_tokens" in salida
    assert "truncada" not in destino.read_text(encoding="utf-8")


# --- Contabilidad: el ahorro de salida se registra y se cuenta -------------------------
@backend_mock.mock
def test_el_evento_registra_que_la_salida_fue_a_un_archivo(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    log = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "USAGE_LOG", log)
    _responde("x = 1\n")

    server.local_boilerplate("algo", "python", str(tmp_path / "c.py"))

    evento = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert evento["tool"] == "local_boilerplate"
    assert evento["output_to_file"] is True


@backend_mock.mock
def test_un_fallo_no_apunta_ahorro_de_salida(tmp_path, monkeypatch):
    """No se escribió nada, así que no hay salida que no haya entrado al contexto."""
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    log = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "USAGE_LOG", log)
    _responde("", status=500)

    server.local_boilerplate("algo", "python", str(tmp_path / "c.py"))

    evento = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert "output_to_file" not in evento


def test_accounting_suma_la_salida_escrita_al_ahorro():
    """El token de salida es real (lo dio el backend), no una estimación por caracteres."""
    fila = {
        "tool": "local_boilerplate",
        "source": "inline",
        "chars_in": 40,
        "chars_out": 4000,
        "tokens_in": 10,
        "tokens_out": 950,
        "output_to_file": True,
    }
    acc = server._accounting(fila)
    # `source=inline`: la entrada sí viajó por el contexto, así que el ahorro es solo la salida.
    assert acc["saved"] == 950
    assert acc["tokens_out"] == 950
    assert acc["estimated"] is False


def test_accounting_sin_la_marca_no_cuenta_ahorro_de_salida():
    """Control: el mismo evento sin `output_to_file` no debe apuntar ahorro ninguno."""
    fila = {
        "tool": "local_boilerplate",
        "source": "inline",
        "chars_in": 40,
        "chars_out": 4000,
        "tokens_in": 10,
        "tokens_out": 950,
    }
    assert server._accounting(fila)["saved"] == 0


def test_accounting_suma_los_dos_ahorros_cuando_los_hay():
    """Entrada leída server-side y salida escrita a archivo: una llamada puede ahorrar por dos."""
    fila = {
        "tool": "local_boilerplate",
        "source": "path",
        "chars_in": 8000,
        "chars_out": 4000,
        "tokens_in": 2100,
        "tokens_out": 950,
        "output_to_file": True,
    }
    assert server._accounting(fila)["saved"] == 8000 // config.CHARS_PER_TOKEN + 950
