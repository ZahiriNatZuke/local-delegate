"""Protected paths: what the tools never read or write, with or without `ALLOWED_DIRS`.

The risk these tests close: the tools read `path` and write `target` outside Claude Code's
permission prompts, and `LOCAL_DELEGATE_ALLOWED_DIRS` is empty by default. A prompt injection in
any file the model reads could ask for `~/.ssh/id_rsa` or drop a script in the Startup folder.

Every test runs on a simulated HOME (`HOME`/`USERPROFILE`/`APPDATA`/`PROGRAMDATA` pointed at
`tmp_path`): nothing here touches the real HOME or `~/.claude.json`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import config, path_guard, server

URL = "http://test-backend/v1/chat/completions"
SECRET = "S3CR3T-VALUE-THAT-MUST-NOT-LEAK"
CASE_INSENSITIVE = sys.platform in ("win32", "darwin")


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """A simulated HOME and data dirs; the guard reads `Path.home()` and these at call time."""
    home = tmp_path / "home"
    home.mkdir()
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    monkeypatch.setattr(config, "ALLOWED_DIRS", [])
    monkeypatch.setattr(config, "DENY_PATHS", [])
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "ld-data")
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    assert Path.home() == home  # the isolation itself, or every test below proves nothing
    return home


def _file(path: Path, content: str = SECRET) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _reply():
    return backend_mock.post(URL).mock(
        return_value=httpx2.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )
    )


def _read_denied(path: Path) -> str:
    with pytest.raises(ValueError, match="Ruta protegida") as caught:
        server._read_input(None, str(path), max_chars=1000)
    message = str(caught.value)
    assert SECRET not in message  # the refusal never carries the content
    return message


def _write_denied(path: Path) -> str:
    with pytest.raises(ValueError, match="Ruta protegida") as caught:
        server._validate_target(str(path), overwrite=True)
    return str(caught.value)


# --- Credentials: denied for reading and writing ---------------------------------------------
HOME_SECRETS = [
    ".ssh/id_rsa",
    ".ssh/config",
    ".aws/credentials",
    ".gnupg/private-keys-v1.d/x.key",
    ".azure/msal_token_cache.json",
    ".kube/config",
    ".docker/config.json",
    ".config/gh/hosts.yml",
    ".config/gcloud/credentials.db",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "_netrc",
    ".git-credentials",
    ".claude.json",
    ".claude/.credentials.json",
    ".codex/auth.json",
    "AppData/Roaming/GitHub CLI/hosts.yml",
    "AppData/Roaming/Claude/claude_desktop_config.json",
]


@pytest.mark.parametrize("rel", HOME_SECRETS)
def test_home_credentials_are_not_read(home, rel):
    message = _read_denied(_file(home / rel))
    assert "credenciales" in message


@pytest.mark.parametrize("rel", HOME_SECRETS)
def test_home_credentials_are_not_written(home, rel):
    assert "credenciales" in _write_denied(home / rel)


ANYWHERE_SECRETS = [
    ".env",
    ".env.local",
    ".env.production",
    ".envrc",
    "id_rsa",
    "id_ed25519",
    "deploy/server.pem",
    "certs/tls.key",
    "certs/store.p12",
    "certs/store.pfx",
    ".npmrc",
    ".git-credentials",
    "claude_desktop_config.json.local-delegate.bak",
    "backup/.claude.json.backup.1",
]


@pytest.mark.parametrize("rel", ANYWHERE_SECRETS)
def test_secret_names_are_protected_in_any_folder(home, tmp_path, rel):
    _read_denied(_file(tmp_path / "project" / rel))


@pytest.mark.parametrize(
    "rel",
    [".env.example", ".env.sample", ".env.template", ".ssh/id_rsa.pub", "keys/id_ed25519.pub"],
)
def test_templates_and_public_keys_outside_home_secrets_are_readable(home, tmp_path, rel):
    """Shareable halves stay readable; `.ssh/` itself is still protected as a whole in HOME."""
    target = _file(tmp_path / "project" / rel, "PUBLIC=1")
    content, _truncated, _raw = server._read_input(None, str(target), max_chars=1000)
    assert content == "PUBLIC=1"


def test_the_ssh_folder_in_home_protects_even_the_public_key(home):
    _read_denied(_file(home / ".ssh" / "id_rsa.pub"))


@pytest.mark.parametrize(
    "rel",
    [
        "src/app.py",
        "logs/app.log",
        "README.md",
        "docs/environment.md",
        ".git/config",  # reading git config is harmless; writing it is not
        ".claude/settings.json",
        "config/keys.py",
        "notes.keynote.txt",
    ],
)
def test_normal_project_files_are_readable(home, tmp_path, rel):
    target = _file(tmp_path / "project" / rel, "fine")
    content, _truncated, _raw = server._read_input(None, str(target), max_chars=1000)
    assert content == "fine"


@pytest.mark.parametrize("rel", [".bashrc", ".zshrc", "Library/LaunchAgents/a.plist"])
def test_write_only_rules_do_not_block_reading(home, rel):
    target = _file(home / rel, "fine")
    content, _truncated, _raw = server._read_input(None, str(target), max_chars=1000)
    assert content == "fine"


# --- Autostart and executable config: denied for writing --------------------------------------
@pytest.mark.parametrize(
    ("rel", "kind"),
    [
        (
            "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/x.cmd",
            "arranque automático",
        ),
        ("Library/LaunchAgents/com.x.plist", "arranque automático"),
        (".config/autostart/x.desktop", "arranque automático"),
        (".config/systemd/user/x.service", "arranque automático"),
        (".bashrc", "ejecuta código"),
        (".bash_profile", "ejecuta código"),
        (".profile", "ejecuta código"),
        (".zshrc", "ejecuta código"),
        (".zprofile", "ejecuta código"),
        (".zshenv", "ejecuta código"),
        ("Documents/PowerShell/Microsoft.PowerShell_profile.ps1", "ejecuta código"),
        ("Documents/WindowsPowerShell/profile.ps1", "ejecuta código"),
        ("OneDrive/Documents/PowerShell/profile.ps1", "ejecuta código"),
        (".claude/settings.json", "ejecuta código"),
        (".claude/settings.local.json", "ejecuta código"),
        (".claude/hooks/pre.py", "ejecuta código"),
        (".codex/config.toml", "ejecuta código"),
    ],
)
def test_autostart_and_executable_config_in_home_are_not_written(home, rel, kind):
    assert kind in _write_denied(home / rel)


def test_programdata_startup_is_not_written(home, tmp_path):
    startup = tmp_path / "ProgramData" / "Microsoft/Windows/Start Menu/Programs/Startup"
    assert "arranque automático" in _write_denied(startup / "x.cmd")


@pytest.mark.parametrize(
    "rel",
    [
        ".git/hooks/pre-commit",
        "sub/.git/hooks/post-checkout",
        ".git/config",
        ".claude/settings.json",
        ".claude/settings.local.json",
    ],
)
def test_repo_hooks_and_project_settings_are_not_written(home, tmp_path, rel):
    assert "ejecuta código" in _write_denied(tmp_path / "project" / rel)


def test_local_delegate_own_config_is_not_written(home, monkeypatch, tmp_path):
    assert "ejecuta código" in _write_denied(config.LOG_DIR / "daemon.json")
    assert "ejecuta código" in _write_denied(config.LOG_DIR / "backend-params.json")
    yaml = tmp_path / "llama-swap" / "config.yaml"
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(yaml))
    assert "ejecuta código" in _write_denied(yaml)


def test_a_normal_target_is_still_writable(home, tmp_path):
    target = tmp_path / "project" / "src" / "new.py"
    assert server._validate_target(str(target), overwrite=False) == target
    # And the usage logs next to the config are not the config.
    assert path_guard.check(config.LOG_DIR / "usage-202611.jsonl", path_guard.WRITE) is None


# --- Case, links and Windows path spellings ---------------------------------------------------
@pytest.mark.skipif(
    not CASE_INSENSITIVE, reason="case-sensitive file system: .SSH is another folder"
)
def test_case_does_not_dodge_the_rules(home, tmp_path):
    _read_denied(_file(home / ".SSH" / "Config"))
    _read_denied(_file(tmp_path / "project" / ".ENV"))
    _read_denied(_file(tmp_path / "project" / "Server.PEM"))
    _write_denied(home / "appdata/roaming/microsoft/windows/start menu/programs/STARTUP/x.cmd")
    _write_denied(tmp_path / "project" / ".GIT" / "Hooks" / "pre-commit")


def _link_dir(link: Path, target: Path) -> None:
    """A directory link: a junction on Windows (no privilege needed), a symlink elsewhere."""
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def test_a_junction_or_symlink_into_a_protected_folder_is_followed(home, tmp_path):
    _file(home / ".ssh" / "config")
    project = tmp_path / "project"
    project.mkdir()
    link = project / "innocent"
    _link_dir(link, home / ".ssh")
    assert (link / "config").read_text(encoding="utf-8") == SECRET  # the link really works
    message = _read_denied(link / "config")
    assert "~/.ssh" in message


def test_a_directory_link_into_startup_is_followed_for_writes(home, tmp_path):
    startup = home / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
    startup.mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    _link_dir(project / "out", startup)
    assert "arranque automático" in _write_denied(project / "out" / "x.cmd")


def test_a_file_symlink_to_a_secret_is_followed(home, tmp_path):
    secret = _file(home / ".npmrc")
    link = tmp_path / "project" / "notes.txt"
    link.parent.mkdir(parents=True)
    try:
        os.symlink(secret, link)
    except OSError as exc:  # Windows without Developer Mode or admin rights
        pytest.skip(f"file symlinks need a privilege here: {exc}")
    _read_denied(link)


def test_dot_dot_segments_are_normalised(home, tmp_path):
    _file(home / ".aws" / "credentials")
    _read_denied(home / "projects" / ".." / ".aws" / "credentials")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows path spellings")
def test_windows_extended_prefix_and_streams_do_not_dodge_the_rules(home, tmp_path):
    secret = _file(home / ".aws" / "credentials")
    assert path_guard.check("\\\\?\\" + str(secret), path_guard.READ) is not None
    env = _file(tmp_path / "project" / ".env")
    assert path_guard.check(str(env) + "::$DATA", path_guard.READ) is not None


# --- LOCAL_DELEGATE_DENY_PATHS and ALLOWED_DIRS ----------------------------------------------
def test_user_deny_paths_block_reading_and_writing(home, monkeypatch, tmp_path):
    private = tmp_path / "private"
    monkeypatch.setattr(config, "DENY_PATHS", [private.resolve()])
    message = _read_denied(_file(private / "notes.md"))
    assert "LOCAL_DELEGATE_DENY_PATHS" in message
    _write_denied(private / "new.py")
    # A sibling folder is not swallowed by a prefix match on the text.
    target = _file(tmp_path / "private-not" / "notes.md", "fine")
    assert server._read_input(None, str(target), max_chars=100)[0] == "fine"


def test_deny_paths_variable_is_parsed_like_allowed_dirs(tmp_path):
    """The variable is read at import: check the parse in a clean interpreter."""
    first, second = tmp_path / "a", tmp_path / "b"
    env = dict(os.environ)
    env["LOCAL_DELEGATE_DENY_PATHS"] = f" {first} ;;{second};"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path(config.__file__).parents[1]), env.get("PYTHONPATH", "")]
    )
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "from local_delegate import config; print(*config.DENY_PATHS, sep='|')",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.strip()
    assert out.split("|") == [str(first.resolve()), str(second.resolve())]


def test_allowed_dirs_do_not_open_a_protected_path(home, monkeypatch):
    """Allowing the whole HOME still leaves its credentials out."""
    monkeypatch.setattr(config, "ALLOWED_DIRS", [home.resolve()])
    _read_denied(_file(home / ".ssh" / "id_ed25519"))


# --- End to end: refused before reading and before the model ----------------------------------
@backend_mock.mock
def test_summarize_refuses_a_secret_without_calling_the_backend(home):
    route = _reply()
    secret = _file(home / ".npmrc")
    with pytest.raises(ValueError, match="Ruta protegida"):
        server.local_summarize(path=str(secret))
    assert route.call_count == 0


@backend_mock.mock
def test_boilerplate_refuses_startup_without_calling_the_backend(home):
    route = _reply()
    target = home / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/x.cmd"
    with pytest.raises(ValueError, match="Ruta protegida"):
        server.local_boilerplate("echo hi", "batch", str(target), overwrite=True)
    assert route.call_count == 0
    assert not target.exists()


def test_the_refusal_is_translated(home, monkeypatch):
    from local_delegate import i18n

    monkeypatch.setattr(i18n, "lang", lambda: "en")
    with pytest.raises(ValueError, match="Protected path \\(credentials, rule ~/.ssh\\)"):
        server._read_input(None, str(_file(home / ".ssh" / "id_rsa")), max_chars=10)
    with pytest.raises(ValueError, match="does not write there"):
        server._validate_target(str(home / ".bashrc"), overwrite=True)
