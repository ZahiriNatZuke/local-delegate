"""El cruce entre un bloqueo del hook y la delegacion que viene despues.

El formato de la nota vive en dos sitios —lo escribe `hook_common`, que es stdlib pura y no puede
importar el paquete, y lo lee `server`— asi que estos tests van de **ida y vuelta**: escriben con
el hook de verdad y leen con el servidor de verdad. Es la misma cautela que el test de paridad del
espejo JavaScript del panel, y por la misma razon: dos fuentes del mismo dato se desincronizan
solas.
"""

from __future__ import annotations

import json
import time

import pytest

from local_delegate import server
from local_delegate.resources.hooks import hook_common


@pytest.fixture
def notes(tmp_path, monkeypatch):
    file = tmp_path / "blocks.jsonl"
    monkeypatch.setattr(hook_common, "block_notes_path", lambda: file)
    # El nombre viejo también se lee (REQ-012): que no lea el temporal real del usuario.
    monkeypatch.setattr(hook_common, "legacy_block_notes_path", lambda: tmp_path / "old.jsonl")
    return file


def test_the_block_id_reaches_the_server(notes, tmp_path):
    """Ida y vuelta: lo escribe el hook, lo encuentra el servidor, y nadie pasa nada por el agente."""
    document = tmp_path / "report.md"
    document.write_text("hola", encoding="utf-8")

    hook_common.record_block("abc123def456", str(document))

    assert server._recent_block_id(str(document)) == "abc123def456"


def test_another_path_does_not_take_someone_elses_block(notes, tmp_path):
    """Control positivo: si cualquier lectura heredara el id, la adopcion medida seria falsa."""
    hook_common.record_block("abc123def456", str(tmp_path / "report.md"))

    assert server._recent_block_id(str(tmp_path / "other.md")) is None


def test_the_same_path_written_differently_still_matches(notes, tmp_path):
    """El hook recibe la ruta del cliente y el servidor la recibe del agente: no coinciden letra a
    letra. En Windows ademas cambian las mayusculas y las barras."""
    document = tmp_path / "sub" / "report.md"
    document.parent.mkdir()
    document.write_text("hola", encoding="utf-8")

    hook_common.record_block("long-id-1234", str(document))
    other_form = str(tmp_path / "sub" / ".." / "sub" / "report.md")

    assert server._recent_block_id(other_form) == "long-id-1234"


def test_an_old_block_no_longer_counts(notes, tmp_path, monkeypatch):
    """Pasada la ventana, el agente hizo otra cosa por el camino: atribuirselo infla la adopcion."""
    document = tmp_path / "report.md"
    hook_common.record_block("caducado1234", str(document))

    old = json.loads(notes.read_text(encoding="utf-8").strip())
    old["ts"] = time.time() - server.BLOCK_WINDOW_S - 1
    notes.write_text(json.dumps(old) + "\n", encoding="utf-8")

    assert server._recent_block_id(str(document)) is None


def test_the_most_recent_block_for_that_path_wins(notes, tmp_path):
    document = tmp_path / "report.md"
    hook_common.record_block("primero12345", str(document))
    hook_common.record_block("segundo12345", str(document))

    assert server._recent_block_id(str(document)) == "segundo12345"


def test_notes_do_not_grow_unbounded(notes, tmp_path):
    for i in range(hook_common.MAX_NOTES + 50):
        hook_common.record_block(f"id{i:010d}", str(tmp_path / f"{i}.md"))

    assert len(notes.read_text(encoding="utf-8").splitlines()) <= hook_common.MAX_NOTES


def test_the_note_does_not_store_the_path(notes, tmp_path):
    """Hereda la regla de la telemetria de hooks: ni rutas ni contenido, solo una huella."""
    document = tmp_path / "client-secret.md"
    hook_common.record_block("abc123def456", str(document))

    raw = notes.read_text(encoding="utf-8")
    assert "client-secret" not in raw
    assert str(tmp_path) not in raw


@pytest.mark.parametrize(
    "content",
    ["", "no es json\n", '{"sin": "campos"}\n', '{"id": 1, "sha": null, "ts": "ayer"}\n'],
    ids=["vacio", "basura", "sin campos", "tipos raros"],
)
def test_a_broken_notes_file_does_not_break_the_tool(notes, tmp_path, content):
    notes.write_text(content, encoding="utf-8")

    assert server._recent_block_id(str(tmp_path / "report.md")) is None


def test_without_notes_file_nothing_happens_either(notes, tmp_path):
    assert not notes.exists()
    assert server._recent_block_id(str(tmp_path / "report.md")) is None


# --- Y lo que de verdad importa: que acabe en el evento del log -------------------------------


def _events(directory):
    files = sorted(directory.glob("usage-*.jsonl"))
    assert files, f"ningún log escrito en {directory}"
    return [json.loads(x) for x in files[-1].read_text(encoding="utf-8").splitlines()]


def test_the_tool_event_keeps_the_block(notes, tmp_path, monkeypatch):
    """Probar la función no es probar el uso: el dato tiene que llegar al log, que es lo que lee
    el panel."""
    from local_delegate import config

    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)
    document = tmp_path / "report.md"
    document.write_text("hola", encoding="utf-8")
    hook_common.record_block("abc123def456", str(document))

    server._log_event(
        tool="local_summarize",
        model="m",
        source="path",
        chars_in=10,
        chars_out=5,
        latency_ms=1,
        ok=True,
        path=str(document),
    )

    assert _events(tmp_path / "logs")[-1]["block_id"] == "abc123def456"


def test_a_spontaneous_delegation_carries_no_block(notes, tmp_path, monkeypatch):
    """Control positivo: si todo evento llevara id, «aceptado» contaría también lo que nadie
    provocó, y la adopción medida saldría inflada."""
    from local_delegate import config

    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", True)

    server._log_event(
        tool="local_summarize",
        model="m",
        source="path",
        chars_in=10,
        chars_out=5,
        latency_ms=1,
        ok=True,
        path=str(tmp_path / "nobody-blocked-me.md"),
    )

    assert "block_id" not in _events(tmp_path / "logs")[-1]
