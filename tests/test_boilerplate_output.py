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

from local_delegate import config, cost, server

URL = "http://test-backend/v1/chat/completions"


def _reply(content: str, *, finish_reason: str = "stop", status: int = 200):
    """Registra la ruta del backend y devuelve el objeto de ruta, para mirarle el call_count."""
    if status != 200:
        return backend_mock.post(URL).mock(return_value=httpx2.Response(status, text="boom"))
    return backend_mock.post(URL).mock(
        return_value=httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 300},
            },
        )
    )


@pytest.fixture(autouse=True)
def _backend_local(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")


# --- El ahorro: el código va al archivo, el recibo al contexto -------------------------
@backend_mock.mock
def test_writes_the_code_and_returns_only_the_receipt(tmp_path):
    code = "def suma(a, b):\n    return a + b\n"
    _reply(code)
    dest = tmp_path / "suma.py"

    output = server.local_boilerplate("una función suma", "python", str(dest))

    assert dest.read_text(encoding="utf-8") == code
    # Lo que de verdad se está probando: el cuerpo del código NO viaja de vuelta.
    assert "return a + b" not in output
    assert output.startswith("[escrito] ")
    assert str(dest) in output
    assert "2 líneas" in output and f"{len(code)} chars" in output


@backend_mock.mock
def test_the_receipt_does_not_grow_with_the_code(tmp_path):
    """Control de magnitud: si el recibo escalara con la salida, no habría ahorro que contar.

    Se compara un recibo contra otro en vez de medir su largo absoluto: el recibo lleva dentro la
    ruta del destino, y en macOS `tmp_path` cuelga de `/private/var/folders/…`, así que un umbral
    fijo mide el sistema de ficheros del runner y no el ahorro.
    """
    short = "def f():\n    return 1\n"
    long_text = "".join(f"def f{i}():\n    return {i}\n" for i in range(400))
    assert len(long_text) > 8000  # el caso que importa: una salida que sí pesa

    dest_a = tmp_path / "a.py"
    dest_b = tmp_path / "b.py"  # mismo largo de ruta que a.py: la diferencia es solo el código
    _reply(short)
    short_receipt = server.local_boilerplate("una función", "python", str(dest_a))
    _reply(long_text)
    long_receipt = server.local_boilerplate("400 funciones", "python", str(dest_b))

    # 400 veces más código y el recibo solo crece por los dígitos de las cifras que reporta.
    assert len(long_text) > len(short) * 400
    assert len(long_receipt) - len(short_receipt) < 20
    assert len(long_receipt) < len(long_text) // 20


@backend_mock.mock
def test_strips_the_fences_before_writing(tmp_path):
    """Si los fences se quitaran en quien llama, al archivo le entrarían las ``` igual."""
    _reply("```python\nprint('hola')\n```")
    dest = tmp_path / "h.py"

    server.local_boilerplate("un hola mundo", "python", str(dest))

    assert dest.read_text(encoding="utf-8") == "print('hola')\n"


@backend_mock.mock
def test_guarantees_the_final_newline(tmp_path):
    """`.strip()` de `_post_chat` deja el código sin newline final; el archivo no debe salir así."""
    _reply("x = 1")
    dest = tmp_path / "s.py"

    server.local_boilerplate("una constante", "python", str(dest))

    assert dest.read_bytes() == b"x = 1\n"


@backend_mock.mock
def test_creates_the_missing_directories(tmp_path):
    _reply("x = 1\n")
    dest = tmp_path / "a" / "b" / "c.py"

    server.local_boilerplate("una constante", "python", str(dest))

    assert dest.read_text(encoding="utf-8") == "x = 1\n"


@backend_mock.mock
def test_the_separator_does_not_depend_on_the_os(tmp_path):
    """Se escribe con LF explícito: en Windows el modo texto convertiría cada \\n en \\r\\n."""
    _reply("a = 1\nb = 2\n")
    dest = tmp_path / "eol.py"

    server.local_boilerplate("dos constantes", "python", str(dest))

    raw = dest.read_bytes()
    assert raw == b"a = 1\nb = 2\n"
    assert b"\r\n" not in raw


# --- Validación del destino: falla ANTES de gastar backend -----------------------------
@backend_mock.mock
def test_relative_path_fails_without_spending_backend(tmp_path):
    path = _reply("no deberia generarse")

    with pytest.raises(ValueError, match="absoluta"):
        server.local_boilerplate("lo que sea", "python", "relativo.py")

    assert path.call_count == 0  # control negativo: no se pagó inferencia


@backend_mock.mock
def test_does_not_overwrite_an_existing_file_nor_spend_backend(tmp_path):
    path = _reply("codigo nuevo")
    dest = tmp_path / "ya.py"
    dest.write_text("NO ME PISES\n", encoding="utf-8")

    with pytest.raises(ValueError, match="overwrite"):
        server.local_boilerplate("otra cosa", "python", str(dest))

    assert dest.read_text(encoding="utf-8") == "NO ME PISES\n"
    assert path.call_count == 0


@backend_mock.mock
def test_overwrite_true_does_overwrite(tmp_path):
    _reply("codigo nuevo\n")
    dest = tmp_path / "ya.py"
    dest.write_text("viejo\n", encoding="utf-8")

    server.local_boilerplate("otra cosa", "python", str(dest), overwrite=True)

    assert dest.read_text(encoding="utf-8") == "codigo nuevo\n"


@backend_mock.mock
def test_a_directory_as_target_is_not_mistaken_for_an_existing_file(tmp_path):
    """Sin la comprobación de `is_dir()` el error hablaría de un archivo que no existe."""
    _reply("x")
    folder = tmp_path / "soy_carpeta"
    folder.mkdir()

    with pytest.raises(ValueError, match="directorio"):
        server.local_boilerplate("algo", "python", str(folder))


@backend_mock.mock
def test_empty_target_fails(tmp_path):
    path = _reply("x")

    with pytest.raises(ValueError, match="obligatorio"):
        server.local_boilerplate("algo", "python", "   ")

    assert path.call_count == 0


@backend_mock.mock
def test_respects_the_allowed_roots(tmp_path, monkeypatch):
    """`LOCAL_DELEGATE_ALLOWED_DIRS` acotaba solo la lectura; ahora también dónde se escribe."""
    path = _reply("x")
    monkeypatch.setattr(config, "ALLOWED_DIRS", [tmp_path / "permitido"])

    with pytest.raises(ValueError, match="raíces permitidas"):
        server.local_boilerplate("algo", "python", str(tmp_path / "fuera" / "x.py"))

    assert path.call_count == 0


# --- Errores del backend: no se escribe basura con nombre de código --------------------
@backend_mock.mock
def test_a_backend_failure_leaves_no_file(tmp_path):
    _reply("", status=500)
    dest = tmp_path / "roto.py"

    output = server.local_boilerplate("algo", "python", str(dest))

    assert not dest.exists()
    assert "[local-delegate error]" in output


@backend_mock.mock
def test_truncated_output_warns_in_the_receipt_and_not_in_the_file(tmp_path):
    """El aviso de `max_tokens` es para quien llama; dentro del archivo sería basura."""
    _reply("def f():\n    pass\n", finish_reason="length")
    dest = tmp_path / "t.py"

    output = server.local_boilerplate("algo", "python", str(dest))

    assert "truncada por max_tokens" in output
    assert "truncada" not in dest.read_text(encoding="utf-8")


# --- Contabilidad: el ahorro de salida se registra y se cuenta -------------------------
@backend_mock.mock
def test_the_event_records_that_the_output_went_to_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    log = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "USAGE_LOG", log)
    _reply("x = 1\n")

    server.local_boilerplate("algo", "python", str(tmp_path / "c.py"))

    event = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert event["tool"] == "local_boilerplate"
    assert event["output_to_file"] is True


@backend_mock.mock
def test_a_failure_does_not_record_output_savings(tmp_path, monkeypatch):
    """No se escribió nada, así que no hay salida que no haya entrado al contexto."""
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    log = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "USAGE_LOG", log)
    _reply("", status=500)

    server.local_boilerplate("algo", "python", str(tmp_path / "c.py"))

    event = json.loads(log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert "output_to_file" not in event


def test_accounting_adds_the_written_output_to_savings():
    """El token de salida es real (lo dio el backend), no una estimación por caracteres."""
    row = {
        "tool": "local_boilerplate",
        "source": "inline",
        "chars_in": 40,
        "chars_out": 4000,
        "tokens_in": 10,
        "tokens_out": 950,
        "output_to_file": True,
    }
    acc = server._accounting(cost.merge_row(row))
    # `source=inline`: la entrada sí viajó por el contexto, así que el ahorro es solo la salida.
    # coste-api-y-cuota: en tokens de Claude (código sin numerar, c = 2,41), no los 950 que
    # reportó el modelo local: 4000 × 100 // 241 = 1659.
    assert acc["saved"] == 1659
    assert acc["tokens_out"] == 950
    assert acc["estimated"] is False


def test_accounting_without_the_mark_does_not_count_output_savings():
    """Control: el mismo evento sin `output_to_file` no debe apuntar ahorro ninguno."""
    row = {
        "tool": "local_boilerplate",
        "source": "inline",
        "chars_in": 40,
        "chars_out": 4000,
        "tokens_in": 10,
        "tokens_out": 950,
    }
    assert server._accounting(row)["saved"] == 0


def test_accounting_adds_both_savings_when_present():
    """Entrada leída server-side y salida escrita a archivo: una llamada puede ahorrar por dos."""
    row = {
        "tool": "local_boilerplate",
        "source": "path",
        "chars_in": 8000,
        "chars_out": 4000,
        "tokens_in": 2100,
        "tokens_out": 950,
        "output_to_file": True,
    }
    # coste-api-y-cuota: entrada por `path` sin extensión (clase `otro`, formato `Read`, respaldo
    # (3), c = 2,41) más la salida en código sin numerar (c = 2,41):
    # 8000 × 100 // 241 + 4000 × 100 // 241 = 3319 + 1659.
    assert server._accounting(cost.merge_row(row))["saved"] == 3319 + 1659
