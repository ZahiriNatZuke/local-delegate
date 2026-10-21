"""`local-delegate completion <shell>` (SDD cli-completion, REQ-001).

L2a subset: only `powershell` exists; L2b adds `zsh` and `bash` to the expectations.
"""

from __future__ import annotations

import pytest

from local_delegate import cli, completion, i18n


def test_completion_writes_utf8_lf_bytes(capsysbinary):
    assert cli.run(["completion", "powershell"]) == 0
    out = capsysbinary.readouterr().out
    assert b"\r" not in out
    text = out.decode("utf-8")
    assert text == completion.render("powershell")
    assert text.startswith("# local-delegate ")
    assert "Register-ArgumentCompleter -Native" in text


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


def test_completion_writes_nothing_to_disk(tmp_path, monkeypatch, capsysbinary):
    """REQ-001: no file appears in the data directory or in the working directory."""
    monkeypatch.chdir(tmp_path)
    before = sorted(tmp_path.rglob("*"))
    assert cli.run(["completion", "powershell"]) == 0
    assert sorted(tmp_path.rglob("*")) == before
