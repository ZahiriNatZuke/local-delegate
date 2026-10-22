"""claude_plugin: when the plugin delivery applies, and the `claude plugin …` commands it runs.

REQ-005 (SDD claude-plugin-and-mods, F1-delivery-core). The runner is always injected: the guard in
`conftest.py` makes any run of the real `claude` fail.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from conftest import FakeClaude

from local_delegate import claude_plugin, install_origin, update

LD_BIN = "C:/uv/tools/local-delegate-mcp/Scripts/python.exe"


def _decide(home, fake, **kwargs):
    kwargs.setdefault("ld_bin", claude_plugin.LdBin(LD_BIN, None))
    kwargs.setdefault("environ", {})
    kwargs.setdefault("platform", "win32")
    return claude_plugin.decide(home, runner=fake, which=fake.which, **kwargs)


def _real_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(claude_plugin, "is_simulated_home", lambda _home: False)
    return home


def test_min_version_gate(tmp_path, monkeypatch):
    home = _real_home(monkeypatch, tmp_path)

    exact = _decide(home, FakeClaude(version=claude_plugin.MIN_CLAUDE_PLUGIN_VERSION))
    assert exact.delivery == claude_plugin.PLUGIN and exact.reason is None
    newer = _decide(home, FakeClaude(version="2.1.307"))
    assert newer.delivery == claude_plugin.PLUGIN

    older = _decide(home, FakeClaude(version="2.1.291"))
    assert older.delivery == claude_plugin.SETTINGS
    assert older.reason == "old_version"
    assert "2.1.291" in older.warning and claude_plugin.MIN_CLAUDE_PLUGIN_VERSION in older.warning

    missing = _decide(home, FakeClaude(present=False))
    assert (missing.delivery, missing.reason) == (claude_plugin.SETTINGS, "no_cli")

    garbled = _decide(home, FakeClaude(version_output="Claude Code, who knows"))
    assert (garbled.delivery, garbled.reason) == (claude_plugin.SETTINGS, "version_unknown")

    # The user's explicit choice wins and needs no warning.
    chosen = _decide(home, FakeClaude(), requested=claude_plugin.SETTINGS)
    assert (chosen.delivery, chosen.reason, chosen.warning) == (claude_plugin.SETTINGS, None, None)

    # Version comparison is numeric, not textual.
    assert claude_plugin.version_at_least("2.1.1000", "2.1.292")
    assert not claude_plugin.version_at_least("2.0.999", "2.1.292")
    assert claude_plugin.parse_version("2.1.307 (Claude Code)") == (2, 1, 307)


def test_wsl_and_simulated_home_fall_back_to_settings(tmp_path, monkeypatch):
    home = _real_home(monkeypatch, tmp_path)
    wsl = _decide(home, FakeClaude(), environ={"WSL_DISTRO_NAME": "Ubuntu"})
    assert (wsl.delivery, wsl.reason) == (claude_plugin.SETTINGS, "wsl")
    assert wsl.warning

    monkeypatch.setattr(claude_plugin, "is_simulated_home", lambda _home: True)
    # A simulated HOME on a platform where CLAUDE_CONFIG_DIR was not verified: settings.
    other_os = _decide(home, FakeClaude(), platform="freebsd14")
    assert (other_os.delivery, other_os.reason) == (claude_plugin.SETTINGS, "simulated_home")
    assert other_os.warning


def test_simulated_home_passes_claude_config_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(claude_plugin, "is_simulated_home", lambda _home: True)
    fake = FakeClaude()

    decision = _decide(home, fake, platform="win32")

    assert decision.delivery == claude_plugin.PLUGIN
    expected = {"CLAUDE_CONFIG_DIR": str(home / ".claude")}
    assert decision.env == expected
    # Even the version probe ran against the simulated config, never the real one.
    assert fake.calls and all(env == expected for _argv, env in fake.calls)

    # With the real HOME, no override: the child inherits the user's environment.
    monkeypatch.setattr(claude_plugin, "is_simulated_home", lambda _home: False)
    assert claude_plugin.child_env(home) is None


def test_dry_run_prints_plugin_commands(tmp_path, monkeypatch):
    home = _real_home(monkeypatch, tmp_path)
    fake = FakeClaude()
    decision = _decide(home, fake)
    calls_before = len(fake.calls)

    lines = claude_plugin.dry_run_lines(decision, language="es")

    assert fake.calls[calls_before:] == []  # printing runs nothing
    text = "\n".join(lines)
    assert "plugin marketplace add" in text
    assert str(claude_plugin.marketplace_dir()) in text
    assert f"plugin install {claude_plugin.PLUGIN_ID}" in text
    assert f"ld_bin={LD_BIN}" in text and "language=es" in text
    assert "plugin list --json" in text

    settings = _decide(home, FakeClaude(present=False))
    assert claude_plugin.dry_run_lines(settings, language="es") == []


def test_install_argv_is_non_interactive(monkeypatch):
    argv = claude_plugin.install_argv("claude", LD_BIN, "en")

    assert argv[:4] == ["claude", "plugin", "install", claude_plugin.PLUGIN_ID]
    assert argv[argv.index("--scope") + 1] == "user"
    configs = [argv[i + 1] for i, a in enumerate(argv) if a == "--config"]
    assert configs == [f"ld_bin={LD_BIN}", "language=en"]
    assert "--json" in argv
    assert claude_plugin.PLUGIN_ID == "local-delegate@local-delegate"
    # The default runner never waits on a prompt: stdin is closed.
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(claude_plugin.subprocess, "run", fake_run)
    claude_plugin.run_subprocess(argv, None)
    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["timeout"] > 0


def test_real_claude_never_runs_in_tests(tmp_path):
    # The conftest guard: an attempt to launch the real `claude` fails loudly…
    with pytest.raises(RuntimeError, match="real `claude`"):
        subprocess.run(["claude", "--version"], capture_output=True)
    with pytest.raises(RuntimeError, match="real `claude`"):
        subprocess.Popen(["C:/Program Files/nodejs/claude.cmd", "plugin", "list"])
    with pytest.raises(RuntimeError, match="real `claude`"):
        claude_plugin.run_subprocess(["claude", "plugin", "list", "--json"], None)
    # …while any other program still runs.
    done = subprocess.run([sys.executable, "-c", "print(7)"], capture_output=True, text=True)
    assert done.stdout.strip() == "7"


def test_ld_bin_is_uv_tool_env(tmp_path, monkeypatch):
    prefix = tmp_path / "uv" / "tools" / "local-delegate-mcp"
    python = prefix / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    monkeypatch.setattr(install_origin, "install_kind", lambda: update.UV_TOOL)

    found = claude_plugin.resolve_ld_bin(prefix=prefix)

    assert found == claude_plugin.LdBin(str(python), None)
    # An absolute path: hooks must never depend on the PATH.
    assert claude_plugin.Path(found.path).is_absolute()

    # The uv tool env without its interpreter: rejected, not guessed.
    python.unlink()
    assert claude_plugin.resolve_ld_bin(prefix=prefix).reason == "no_python"


@pytest.mark.parametrize(
    ("kind", "cache", "reason"),
    [
        (update.UV_TOOL, True, "uvx_cache"),
        (update.OTHER, True, "uvx_cache"),
        (update.EDITABLE, False, "editable"),
        (update.OTHER, False, "not_uv_tool"),
    ],
)
def test_ld_bin_rejected_from_uvx_cache(tmp_path, monkeypatch, kind, cache, reason):
    if cache:
        prefix = tmp_path / "AppData" / "Local" / "uv" / "cache" / "abc123"
    else:
        prefix = tmp_path / "repo" / ".venv"
    python = prefix / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    (prefix / "uv-receipt.toml").write_text('requires = ["local-delegate-mcp"]\n', "utf-8")
    monkeypatch.setattr(install_origin, "install_kind", lambda: kind)

    found = claude_plugin.resolve_ld_bin(prefix=prefix)

    assert found.path is None and found.reason == reason

    # And the decision goes to settings, with a warning that names the cause.
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setattr(claude_plugin, "is_simulated_home", lambda _home: False)
    decision = _decide(home, FakeClaude(), ld_bin=found)
    assert decision.delivery == claude_plugin.SETTINGS
    assert decision.reason == f"ld_bin_{reason}"
    assert decision.warning
