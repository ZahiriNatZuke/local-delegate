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


def _windows(log_dir) -> list[dict]:
    return json.loads((log_dir / tw.FILE_NAME).read_text(encoding="utf-8"))["windows"]


def test_start_prints_an_id_that_is_in_the_file(log_dir, capsys):
    assert cli.run(["test-window", "start", "--label", "ola 11"]) == 0
    wid = capsys.readouterr().out.strip()
    (entry,) = _windows(log_dir)
    assert entry["id"] == wid
    assert entry["end"] is None and entry["label"] == "ola 11"


@pytest.mark.parametrize(("open_ones", "code"), [(0, 2), (1, 0), (2, 2)])
def test_stop_without_id(log_dir, capsys, open_ones, code):
    """Control: mutante «`stop` sin id cierra la primera aunque haya dos» → falla el caso de 2."""
    ids = []
    for _ in range(open_ones):
        cli.run(["test-window", "start"])
        ids.append(capsys.readouterr().out.strip())
    assert cli.run(["test-window", "stop"]) == code
    output = capsys.readouterr()
    if open_ones == 2:
        assert all(i in output.err for i in ids)
        assert all(v["end"] is None for v in _windows(log_dir))
    if open_ones == 1:
        assert _windows(log_dir)[0]["end"] is not None


def test_stop_of_a_nonexistent_id_gives_2(log_dir, capsys):
    assert cli.run(["test-window", "stop", "w-none"]) == 2
    assert "no existe" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-10-08T01:20:05.255Z", "2026-10-08T01:22:31.544Z"),
        ("2026-10-08T01:20:05.255+00:00", "2026-10-08T01:22:31.544+00:00"),
        ("2026-10-08T01:20:05.255", "2026-10-08T01:22:31.544"),
        ("2026-10-08T03:20:05.255+02:00", "2026-10-08T03:22:31.544+02:00"),
    ],
)
def test_add_normalizes_to_utc_with_z(log_dir, start, end):
    assert cli.run(["test-window", "add", start, end]) == 0
    (entry,) = _windows(log_dir)
    assert (entry["start"], entry["end"]) == (
        "2026-10-08T01:20:05.255Z",
        "2026-10-08T01:22:31.544Z",
    )


def test_add_without_milliseconds_adds_them(log_dir):
    assert cli.run(["test-window", "add", "2026-09-15T19:31:14Z", "2026-09-15T19:35:14Z"]) == 0
    assert _windows(log_dir)[0]["start"] == "2026-09-15T19:31:14.000Z"


@pytest.mark.parametrize(
    ("start", "end"),
    [("2026-10-08T02:00:00Z", "2026-10-08T01:00:00Z"), ("rota", "2026-10-08T01:00:00Z")],
)
def test_add_with_bad_dates_gives_2(log_dir, capsys, start, end):
    assert cli.run(["test-window", "add", start, end]) == 2
    assert capsys.readouterr().err.startswith("test-window:")


def test_repeated_add_gives_0_and_says_it_already_existed(log_dir, capsys):
    args = ["test-window", "add", "2026-09-15T19:31:14Z", "2026-09-15T19:35:14Z", "--label", "P-4"]
    assert cli.run(args) == 0
    capsys.readouterr()
    assert cli.run(args) == 0
    assert "ya existía" in capsys.readouterr().out
    assert len(_windows(log_dir)) == 1


def _log(log_dir, hours: list[str]) -> None:
    (log_dir / "usage-202610.jsonl").write_text(
        "".join(
            json.dumps({"ts": f"2026-10-08T{h}+00:00", "tool": "local_summarize"}) + "\n"
            for h in hours
        ),
        encoding="utf-8",
    )


def test_list_counts_the_rows_of_each_window(log_dir, capsys):
    _log(log_dir, ["01:20:04", "01:20:05", "01:21:00", "01:22:31", "01:22:32"])
    cli.run(["test-window", "add", "2026-10-08T01:20:05.255Z", "2026-10-08T01:22:31.544Z"])
    capsys.readouterr()
    assert cli.run(["test-window", "list"]) == 0
    line = capsys.readouterr().out.strip()
    assert "3 filas" in line and "w-20261008T012005Z" in line


def test_list_json_with_english_keys(log_dir, capsys):
    _log(log_dir, ["01:21:00"])
    cli.run(["test-window", "add", "2026-10-08T01:20:05.255Z", "2026-10-08T01:22:31.544Z"])
    cli.run(["test-window", "start"])
    capsys.readouterr()
    assert cli.run(["test-window", "list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"file", "error", "ignored", "windows"}
    assert set(data["windows"][0]) == {"id", "start", "end", "label", "created_at", "rows"}
    assert [w["rows"] for w in data["windows"]] == [1, 0]
    assert data["windows"][1]["end"] is None


def test_an_unreadable_file_is_not_overwritten(log_dir, capsys):
    (log_dir / tw.FILE_NAME).write_text("{roto", encoding="utf-8")
    assert cli.run(["test-window", "start"]) == 2
    assert "ilegible" in capsys.readouterr().err
    assert (log_dir / tw.FILE_NAME).read_text(encoding="utf-8") == "{roto"


def test_list_also_counts_the_fixed_name_log(log_dir, capsys, monkeypatch):
    """Los mismos ficheros que el panel: también `config.USAGE_LOG` si no es uno rotado."""
    fixed = log_dir / "usage.jsonl"
    fixed.write_text(
        json.dumps({"ts": "2026-10-08T01:21:00+00:00", "tool": "local_extract"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "USAGE_LOG", fixed)
    _log(log_dir, ["01:21:10"])
    cli.run(["test-window", "add", "2026-10-08T01:20:05.255Z", "2026-10-08T01:22:31.544Z"])
    capsys.readouterr()
    cli.run(["test-window", "list"])
    assert "2 filas" in capsys.readouterr().out
