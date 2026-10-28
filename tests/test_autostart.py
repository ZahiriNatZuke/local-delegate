"""Tests del autoarranque opcional de llama-swap."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from local_delegate import autostart, probes


def _capture_spawn(monkeypatch, watch: str | None) -> list[str]:
    calls = []
    monkeypatch.setattr(autostart, "_backend_up", lambda: False)
    monkeypatch.setattr(autostart, "_find_exe", lambda: "llama-swap")
    monkeypatch.setenv("LLAMASWAP_CONFIG", "C:\\models\\config.yaml")
    if watch is None:
        monkeypatch.delenv("LLAMASWAP_WATCH_CONFIG", raising=False)
    else:
        monkeypatch.setenv("LLAMASWAP_WATCH_CONFIG", watch)
    monkeypatch.setattr(
        autostart.subprocess,
        "Popen",
        lambda args, **_kwargs: calls.append(args),
    )

    assert autostart.ensure_backend(wait=0) is False
    return calls[0]


def test_autostart_watch_config_is_opt_in(monkeypatch):
    args = _capture_spawn(monkeypatch, None)

    assert "--config" in args
    assert "-watch-config" not in args


def test_autostart_can_watch_config(monkeypatch):
    args = _capture_spawn(monkeypatch, "1")

    assert args[args.index("--config") + 1] == "C:\\models\\config.yaml"
    assert "-watch-config" in args


# --- Never run a llama-swap resolved by bare name (CWD lookup on Windows) ---------------------

_EXE_NAME = "llama-swap.exe" if sys.platform == "win32" else "llama-swap"


def _fake_exe(folder: Path, name: str = _EXE_NAME) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / name
    exe.write_bytes(b"not a real binary")
    exe.chmod(0o755)
    return exe


def _capture_launches(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(autostart, "_backend_up", lambda: False)
    monkeypatch.delenv("LLAMASWAP_CONFIG", raising=False)
    monkeypatch.setattr(
        autostart.subprocess, "Popen", lambda args, **_kwargs: calls.append(list(args))
    )
    return calls


def test_exe_in_cwd_but_not_in_path_is_not_run(tmp_path, monkeypatch):
    calls = _capture_launches(monkeypatch)
    repo = tmp_path / "foreign-repo"
    _fake_exe(repo)
    _fake_exe(repo, "llama-swap")  # both spellings: Popen/CreateProcess would find either
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.chdir(repo)
    monkeypatch.delenv("LLAMASWAP_EXE", raising=False)
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    # A relative entry (".") must not count as "the cwd is in PATH" either.
    monkeypatch.setenv("PATH", os.pathsep.join([str(empty), ".", ""]))

    assert autostart._find_exe() is None
    assert autostart.ensure_backend(wait=0) is False
    assert calls == []


def test_missing_llamaswap_exe_warns_and_does_not_start(tmp_path, monkeypatch, capsys):
    calls = _capture_launches(monkeypatch)
    # A llama-swap reachable through PATH must NOT be used as a silent fallback.
    bin_dir = tmp_path / "bin"
    _fake_exe(bin_dir)
    monkeypatch.setenv("PATH", str(bin_dir))
    missing = tmp_path / "nope" / _EXE_NAME
    monkeypatch.setenv("LLAMASWAP_EXE", str(missing))

    assert autostart.ensure_backend(wait=0) is False
    assert calls == []
    err = capsys.readouterr().err
    assert f"LLAMASWAP_EXE={missing}" in err


def test_relative_llamaswap_exe_is_refused_even_if_it_exists(tmp_path, monkeypatch, capsys):
    calls = _capture_launches(monkeypatch)
    _fake_exe(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLAMASWAP_EXE", _EXE_NAME)

    assert autostart.ensure_backend(wait=0) is False
    assert calls == []
    assert f"LLAMASWAP_EXE={_EXE_NAME}" in capsys.readouterr().err


def test_exe_in_path_is_launched_by_absolute_path(tmp_path, monkeypatch, capsys):
    calls = _capture_launches(monkeypatch)
    bin_dir = tmp_path / "bin"
    exe = _fake_exe(bin_dir)
    cwd = tmp_path / "cwd"
    _fake_exe(cwd)  # a decoy in the cwd must lose against PATH
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("LLAMASWAP_EXE", raising=False)
    monkeypatch.setenv("PATH", str(bin_dir))

    assert autostart.ensure_backend(wait=0) is False
    assert len(calls) == 1
    assert Path(calls[0][0]).is_absolute()
    assert Path(calls[0][0]) == exe
    assert capsys.readouterr().err == ""


def test_valid_absolute_llamaswap_exe_is_launched(tmp_path, monkeypatch):
    calls = _capture_launches(monkeypatch)
    exe = _fake_exe(tmp_path / "opt")
    monkeypatch.setenv("LLAMASWAP_EXE", str(exe))

    assert autostart.ensure_backend(wait=0) is False
    assert [Path(c[0]) for c in calls] == [exe]


def test_cwd_listed_in_path_as_absolute_is_allowed(tmp_path, monkeypatch):
    calls = _capture_launches(monkeypatch)
    exe = _fake_exe(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLAMASWAP_EXE", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))

    autostart.ensure_backend(wait=0)
    assert [Path(c[0]) for c in calls] == [exe]


def test_doctor_version_probe_does_not_run_bare_name_from_cwd(tmp_path, monkeypatch):
    ran: list[list[str]] = []

    def fake_run(args, **_kwargs):
        ran.append(list(args))
        return probes.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(probes.subprocess, "run", fake_run)
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    _fake_exe(tmp_path, name)
    monkeypatch.chdir(tmp_path)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    assert probes._run_version("llama-server") is None
    assert probes._run_version(os.path.join("sub", name)) is None
    assert ran == []
