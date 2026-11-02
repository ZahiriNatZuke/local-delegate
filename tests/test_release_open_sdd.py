"""Pruebas del aviso de `scripts/release.py` sobre cambios SDD sin cerrar.

Varios SDD se quedaron en `verifying` con su trabajo ya mezclado y publicado, porque al terminar
nadie los cerraba. El release es el momento en que eso se ve: el script avisa (no bloquea) de cada
cambio cuyo `state.json` no está en `closed`, también con `--dry-run`, y no se rompe si el
repositorio no tiene `.sdd`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"

if not SCRIPTS.is_dir():
    pytest.skip(
        "scripts/ no está en el árbol (sdist): estas pruebas necesitan el repositorio",
        allow_module_level=True,
    )


def _load_script():
    spec = importlib.util.spec_from_file_location("release_script", SCRIPTS / "release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load_script()


def _write_state(root: Path, name: str, status: str) -> None:
    folder = root / ".sdd" / "changes" / name
    folder.mkdir(parents=True)
    (folder / "state.json").write_text(
        json.dumps({"slug": name, "status": status}), encoding="utf-8"
    )


def test_lists_only_changes_that_are_not_closed(tmp_path):
    _write_state(tmp_path, "done-change", "closed")
    _write_state(tmp_path, "stuck-change", "verifying")
    _write_state(tmp_path, "early-change", "specifying")

    assert release._open_sdd_changes(tmp_path) == [
        ("early-change", "specifying"),
        ("stuck-change", "verifying"),
    ]


def test_missing_or_broken_state_counts_as_open(tmp_path):
    (tmp_path / ".sdd" / "changes" / "no-state").mkdir(parents=True)
    broken = tmp_path / ".sdd" / "changes" / "broken-state"
    broken.mkdir()
    (broken / "state.json").write_text("{not json", encoding="utf-8")

    assert release._open_sdd_changes(tmp_path) == [
        ("broken-state", "state.json ilegible"),
        ("no-state", "sin state.json"),
    ]


def test_missing_changes_folder_is_not_an_error(tmp_path, capsys):
    assert release._open_sdd_changes(tmp_path) == []
    release._warn_open_sdd_changes(tmp_path)
    assert capsys.readouterr().out == ""


def test_warning_names_each_open_change_with_its_status(tmp_path, capsys):
    _write_state(tmp_path, "done-change", "closed")
    _write_state(tmp_path, "stuck-change", "verifying")

    release._warn_open_sdd_changes(tmp_path)

    out = capsys.readouterr().out
    assert "AVISO: 1 cambios SDD sin cerrar" in out
    assert "SDD sin cerrar: stuck-change (verifying)" in out
    assert "done-change" not in out
    assert "personal-harness sdd transition" in out


def test_dry_run_shows_the_warning_and_still_succeeds(tmp_path, monkeypatch, capsys):
    """El aviso sale antes del plan del --dry-run y no cambia el código de salida."""
    _write_state(tmp_path, "stuck-change", "verifying")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release, "_checks", lambda version: None)
    monkeypatch.setattr(release, "_changelog_notes", lambda version: "- una nota")
    monkeypatch.setattr(sys, "argv", ["release.py", "9.9.9", "--dry-run"])

    assert release.main() == 0

    out = capsys.readouterr().out
    assert "SDD sin cerrar: stuck-change (verifying)" in out
    assert out.index("SDD sin cerrar") < out.index("--dry-run: no se crea nada")
