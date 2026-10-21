"""`local-delegate completion <shell>` (SDD cli-completion, REQ-001), for the three shells."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from local_delegate import cli, completion, config, i18n

REGISTRATION = {
    "powershell": "Register-ArgumentCompleter -Native",
    "zsh": "compdef _local_delegate local-delegate local-delegate-mcp",
    "bash": "complete -o default -F _local_delegate local-delegate local-delegate-mcp",
}


def test_the_subcommand_offers_the_three_shells():
    assert completion.SHELLS == ("powershell", "zsh", "bash")


@pytest.mark.parametrize("shell", completion.SHELLS)
def test_completion_writes_utf8_lf_bytes(capsysbinary, shell):
    assert cli.run(["completion", shell]) == 0
    out = capsysbinary.readouterr().out
    assert b"\r" not in out
    text = out.decode("utf-8")
    assert text == completion.render(shell)
    assert completion.header_version(text) is not None
    assert REGISTRATION[shell] in text


def test_completion_uses_the_language_in_force(capsysbinary, monkeypatch):
    """REQ-042: the subcommand renders in the language of the process."""
    monkeypatch.setenv("LOCAL_DELEGATE_LANG", "en")
    i18n.reset()
    assert cli.run(["completion", "powershell"]) == 0
    first = capsysbinary.readouterr().out.decode("utf-8").splitlines()[0]
    assert first.endswith("completion powershell lang=en (generated; do not edit)")


def test_unknown_shell_is_an_argparse_error_from_the_catalog(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.run(["completion", "fish"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    invalid_choice = i18n.t("argparse.invalid_choice").split("%")[0].strip()
    assert invalid_choice
    assert invalid_choice in err
    assert "'fish'" in err


@pytest.mark.parametrize("shell", completion.SHELLS)
def test_completion_writes_nothing_to_disk(tmp_path, monkeypatch, capsysbinary, shell):
    """REQ-001 and REQ-011 (SDD backlog-minor-leftovers): no file appears in the working
    directory, the data directory, HOME or the temporary directory. Each one is a separate
    folder, so a write anywhere among them changes the snapshot. Positive control (checked):
    with the subcommand writing a file to `Path.home()` or to `tempfile.gettempdir()`, the old
    test (working directory only) passed and this one fails on the last assert."""
    places = {name: tmp_path / name for name in ("cwd", "data", "home", "tmp")}
    for path in places.values():
        path.mkdir()
    monkeypatch.chdir(places["cwd"])
    monkeypatch.setattr(config, "LOG_DIR", places["data"])
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(places["data"]))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: places["home"]))
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(places["home"]))
    for name in ("TMP", "TEMP", "TMPDIR"):
        monkeypatch.setenv(name, str(places["tmp"]))
    monkeypatch.setattr(tempfile, "tempdir", str(places["tmp"]))
    assert Path.home() == places["home"] and tempfile.gettempdir() == str(places["tmp"])
    before = sorted(tmp_path.rglob("*"))
    assert cli.run(["completion", shell]) == 0
    assert sorted(tmp_path.rglob("*")) == before
