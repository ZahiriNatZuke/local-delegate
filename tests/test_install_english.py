"""Humo en inglés de `install`, `update` y `uninstall` (frente B, ola B5): REQ-021, REQ-034.

Mismo criterio que `test_cli_english.py`: las *palabras distintivas* del catálogo español de las
superficies que imprimen estos comandos (`install`, más `cli`, `doctor` y `common`, que salen en la
cabecera y en el informe del andamiaje) no pueden aparecer en la salida inglesa. Y el control
positivo permanente: las mismas salidas en español sí las tienen.
"""

from __future__ import annotations

import re

from test_cli_english import _ACCENTS, _WORD, _catalog, _run, _set_language, _spanish_in
from test_update import opts_for

from local_delegate import update

SURFACES = ("install", "cli", "doctor", "common")


def _distinctive_spanish_words() -> set[str]:
    english, spanish = set(), set()
    for surface in SURFACES:
        es, en = _catalog("es", surface), _catalog("en", surface)
        for text in en.values():
            english.update(w.lower() for w in _WORD.findall(text))
        for key, text in es.items():
            if text != en[key]:
                spanish.update(w.lower() for w in _WORD.findall(text))
    return spanish - english


def _outputs(tmp_path, capsys, agents_text: str) -> dict[str, tuple[int, str]]:
    home = tmp_path / "home"
    for client in (".claude", ".codex", ".config/opencode"):
        (home / client).mkdir(parents=True, exist_ok=True)
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir()
    (agents_dir / "probe.md").write_text(agents_text, encoding="utf-8")
    common = ["--home", str(home), "--clients", "claude", "--clients", "codex"]
    common += ["--clients", "opencode"]
    outputs = {
        "dry_run": _run(["install", *common, "--agents", "--dry-run"], capsys),
        "install": _run(["install", *common, "--agents"], capsys),
        "install_again": _run(["install", *common, "--agents"], capsys),
    }
    lines: list[str] = []
    code = update.run_update(opts_for(home, version="0.1.0"), out=lines.append)
    outputs["update"] = (code, "\n".join(lines))
    outputs["uninstall"] = _run(["uninstall", *common], capsys)
    return outputs


AGENT = (
    "---\nname: probe\ntools: Read, mcp__local-delegate__local_delegate\n---\n\n"
    "## Delegation to local models\n\nDelegate the mechanical work.\n\n## Other\n\nText.\n"
)


def test_install_update_and_uninstall_in_english(tmp_path, monkeypatch, capsys):
    words = _distinctive_spanish_words()
    assert len(words) >= 100, "sin palabras distintivas el test no discrimina"
    _set_language(monkeypatch, "en")
    outputs = _outputs(tmp_path, capsys, AGENT)
    # Guarda de «esto llegó a comprobar algo»: cada salida pasó por el camino que se quería.
    assert "saves language en (source: variable)" in outputs["dry_run"][1]
    assert "skill local-delegation (en)" in outputs["install"][1]
    assert "catalog inserted" in outputs["install"][1]
    assert "language en, already saved" in outputs["install_again"][1]
    assert "managed block already up to date" in outputs["install_again"][1]
    assert "local-delegate update — HOME:" in outputs["update"][1]
    assert "deletes the language preference" in outputs["uninstall"][1]
    for name, (code, out) in outputs.items():
        assert code == 0, f"{name}: {out}"
        assert not _spanish_in(out, words), f"{name}: {_spanish_in(out, words)}\n{out}"
        assert not _ACCENTS.search(out), f"{name}: {out}"
    claude_md = (tmp_path / "home" / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert not re.search(r"Delegaci[oó]n", claude_md), "el bloque se quitó al desinstalar"


def test_the_same_smoke_in_spanish_does_trip_the_detector(tmp_path, monkeypatch, capsys):
    """Control positivo permanente: en español, cada salida tiene palabras distintivas."""
    words = _distinctive_spanish_words()
    _set_language(monkeypatch, "es")
    outputs = _outputs(tmp_path, capsys, AGENT)
    clean = [name for name, (_code, out) in outputs.items() if not _spanish_in(out, words)]
    assert clean == [], clean
