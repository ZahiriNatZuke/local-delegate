"""`local-delegate test-window {start,stop,add,list}` (T3, REQ-006 a REQ-010).

`config.LOG_DIR` apunta a `tmp_path`: el fichero real de la máquina no se toca.
"""

from __future__ import annotations

import json

import pytest

from local_delegate import cli, config
from local_delegate import test_windows as tw


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    return tmp_path


def _ventanas(log_dir) -> list[dict]:
    return json.loads((log_dir / tw.FILE_NAME).read_text(encoding="utf-8"))["windows"]


def test_start_imprime_un_id_que_esta_en_el_fichero(log_dir, capsys):
    assert cli.run(["test-window", "start", "--label", "ola 11"]) == 0
    wid = capsys.readouterr().out.strip()
    (entrada,) = _ventanas(log_dir)
    assert entrada["id"] == wid
    assert entrada["end"] is None and entrada["label"] == "ola 11"


@pytest.mark.parametrize(("abiertas", "codigo"), [(0, 2), (1, 0), (2, 2)])
def test_stop_sin_id(log_dir, capsys, abiertas, codigo):
    """Control: mutante «`stop` sin id cierra la primera aunque haya dos» → falla el caso de 2."""
    ids = []
    for _ in range(abiertas):
        cli.run(["test-window", "start"])
        ids.append(capsys.readouterr().out.strip())
    assert cli.run(["test-window", "stop"]) == codigo
    salida = capsys.readouterr()
    if abiertas == 2:
        assert all(i in salida.err for i in ids)
        assert all(v["end"] is None for v in _ventanas(log_dir))
    if abiertas == 1:
        assert _ventanas(log_dir)[0]["end"] is not None


def test_stop_de_un_id_que_no_existe_da_2(log_dir, capsys):
    assert cli.run(["test-window", "stop", "w-nada"]) == 2
    assert "no existe" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("inicio", "fin"),
    [
        ("2026-10-08T01:20:05.255Z", "2026-10-08T01:22:31.544Z"),
        ("2026-10-08T01:20:05.255+00:00", "2026-10-08T01:22:31.544+00:00"),
        ("2026-10-08T01:20:05.255", "2026-10-08T01:22:31.544"),
        ("2026-10-08T03:20:05.255+02:00", "2026-10-08T03:22:31.544+02:00"),
    ],
)
def test_add_normaliza_a_utc_con_z(log_dir, inicio, fin):
    assert cli.run(["test-window", "add", inicio, fin]) == 0
    (entrada,) = _ventanas(log_dir)
    assert (entrada["start"], entrada["end"]) == (
        "2026-10-08T01:20:05.255Z",
        "2026-10-08T01:22:31.544Z",
    )


def test_add_sin_milisegundos_los_pone(log_dir):
    assert cli.run(["test-window", "add", "2026-09-15T19:31:14Z", "2026-09-15T19:35:14Z"]) == 0
    assert _ventanas(log_dir)[0]["start"] == "2026-09-15T19:31:14.000Z"


@pytest.mark.parametrize(
    ("inicio", "fin"),
    [("2026-10-08T02:00:00Z", "2026-10-08T01:00:00Z"), ("rota", "2026-10-08T01:00:00Z")],
)
def test_add_con_fechas_malas_da_2(log_dir, capsys, inicio, fin):
    assert cli.run(["test-window", "add", inicio, fin]) == 2
    assert capsys.readouterr().err.startswith("test-window:")


def test_add_repetido_da_0_y_dice_que_ya_existia(log_dir, capsys):
    args = ["test-window", "add", "2026-09-15T19:31:14Z", "2026-09-15T19:35:14Z", "--label", "P-4"]
    assert cli.run(args) == 0
    capsys.readouterr()
    assert cli.run(args) == 0
    assert "ya existía" in capsys.readouterr().out
    assert len(_ventanas(log_dir)) == 1


def _log(log_dir, horas: list[str]) -> None:
    (log_dir / "usage-202610.jsonl").write_text(
        "".join(
            json.dumps({"ts": f"2026-10-08T{h}+00:00", "tool": "local_summarize"}) + "\n"
            for h in horas
        ),
        encoding="utf-8",
    )


def test_list_cuenta_las_filas_de_cada_ventana(log_dir, capsys):
    _log(log_dir, ["01:20:04", "01:20:05", "01:21:00", "01:22:31", "01:22:32"])
    cli.run(["test-window", "add", "2026-10-08T01:20:05.255Z", "2026-10-08T01:22:31.544Z"])
    capsys.readouterr()
    assert cli.run(["test-window", "list"]) == 0
    linea = capsys.readouterr().out.strip()
    assert "3 filas" in linea and "w-20261008T012005Z" in linea


def test_list_json_con_claves_en_ingles(log_dir, capsys):
    _log(log_dir, ["01:21:00"])
    cli.run(["test-window", "add", "2026-10-08T01:20:05.255Z", "2026-10-08T01:22:31.544Z"])
    cli.run(["test-window", "start"])
    capsys.readouterr()
    assert cli.run(["test-window", "list", "--json"]) == 0
    datos = json.loads(capsys.readouterr().out)
    assert set(datos) == {"file", "error", "ignored", "windows"}
    assert set(datos["windows"][0]) == {"id", "start", "end", "label", "created_at", "rows"}
    assert [w["rows"] for w in datos["windows"]] == [1, 0]
    assert datos["windows"][1]["end"] is None


def test_un_fichero_ilegible_no_se_pisa(log_dir, capsys):
    (log_dir / tw.FILE_NAME).write_text("{roto", encoding="utf-8")
    assert cli.run(["test-window", "start"]) == 2
    assert "ilegible" in capsys.readouterr().err
    assert (log_dir / tw.FILE_NAME).read_text(encoding="utf-8") == "{roto"
