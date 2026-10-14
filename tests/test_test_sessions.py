"""Tests de `scripts/test_sessions.py` (SDD subagente-lector-local, tarea 0)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location(
    "test_sessions", ROOT / "scripts" / "test_sessions.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _transcript(dir_: Path, name: str, events: list[dict]) -> None:
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / f"{name}.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


def test_only_counts_sdk_sessions_of_the_requested_day(tmp_path):
    p = tmp_path / "projects" / "D--x"
    _transcript(
        p,
        "a",
        [
            {"entrypoint": "sdk-cli", "sessionId": "a", "timestamp": "2026-09-22T10:00:00Z"},
            {"entrypoint": "sdk-cli", "sessionId": "a", "timestamp": "2026-09-22T10:05:00Z"},
        ],
    )
    # Control: interactiva el mismo día y sdk de otro día. Si el filtro no discriminara, entrarían.
    _transcript(p, "b", [{"entrypoint": "cli", "sessionId": "b", "timestamp": "2026-09-22T11:00Z"}])
    _transcript(
        p, "c", [{"entrypoint": "sdk-cli", "sessionId": "c", "timestamp": "2026-09-21T09:00Z"}]
    )

    sessions = mod.sdk_sessions(tmp_path / "projects", "2026-09-22")

    assert [s["session_id"] for s in sessions] == ["a"]
    assert sessions[0]["start"] == "2026-09-22T10:00:00Z"
    assert sessions[0]["end"] == "2026-09-22T10:05:00Z"


def test_merge_does_not_duplicate_and_keeps_what_was_there(tmp_path):
    # Lo que había está en el formato viejo (claves en español): se lee igual y sale en el nuevo.
    old = {"sesiones": [{"session_id": "a"}], "ventanas": [{"inicio": "x", "fin": "y"}]}
    output = tmp_path / "v.json"
    output.write_text(json.dumps(old), encoding="utf-8")
    data = mod.merge(output, [{"session_id": "a"}, {"session_id": "z"}], "prueba")
    assert [s["session_id"] for s in data["sessions"]] == ["a", "z"]
    assert data["windows"] == [{"start": "x", "end": "y"}]
    assert "sesiones" not in data and "ventanas" not in data
    # Sin el fichero nuevo, se parte del de antes que tenga al lado (`ventanas-excluidas.json`).
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / mod.LEGACY_OUTPUT_NAME).write_text(json.dumps(old), encoding="utf-8")
    data = mod.merge(legacy_dir / "excluded-windows.json", [{"session_id": "z"}], "prueba")
    assert [s["session_id"] for s in data["sessions"]] == ["a", "z"]


def test_the_output_stores_no_paths(tmp_path):
    p = tmp_path / "projects" / "D--x"
    _transcript(
        p,
        "a",
        [
            {
                "entrypoint": "sdk-cli",
                "sessionId": "a",
                "timestamp": "2026-09-22T10:00:00Z",
                "cwd": "C:\\secreto\\ruta",
            }
        ],
    )
    output = tmp_path / "v.json"
    mod.main(
        ["--day", "2026-09-22", "--projects", str(tmp_path / "projects"), "--output", str(output)]
    )
    assert "secreto" not in output.read_text(encoding="utf-8")
