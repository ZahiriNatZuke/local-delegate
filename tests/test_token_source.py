"""Fuentes de credenciales que no dependen del entorno del proceso (SDD claude-plugin-and-mods).

Windows (REQ-012): Desktop no pasa su entorno a los MCP ni expande `${VAR}`, así que el puente lee
él mismo la variable de usuario del registro. macOS (issue #409, lote macos-keychain): sin el
entorno de un shell, la clave del backend y el token del daemon salen del Llavero. Registro y
`security` son simulados: la suite no lee ni el registro real ni el Llavero real.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import subprocess
import sys
import time
import types

import pytest

from local_delegate import config, token_source

REG_SZ = 1
REG_EXPAND_SZ = 2


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_winreg(values: dict[str, tuple[str, int]], opened: list):
    """Un `winreg` mínimo: solo `HKCU\\Environment`, con los valores dados."""

    def open_key(root, path):
        opened.append((root, path))
        if (root, path) != ("HKCU", "Environment"):
            raise OSError("no such key")
        return _FakeKey()

    def query_value_ex(_key, name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name]

    return types.SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        REG_SZ=REG_SZ,
        REG_EXPAND_SZ=REG_EXPAND_SZ,
        OpenKey=open_key,
        QueryValueEx=query_value_ex,
        ExpandEnvironmentStrings=lambda value: value.replace("%PART%", "expanded"),
    )


@pytest.fixture
def registry(monkeypatch):
    """Simula Windows con un registro propio; devuelve el dict de valores y las claves abiertas."""
    values: dict[str, tuple[str, int]] = {}
    opened: list = []
    monkeypatch.setattr(token_source.sys, "platform", "win32")
    monkeypatch.setattr(token_source, "_winreg", lambda: _fake_winreg(values, opened))
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    return values, opened


def test_reads_registry_user_env_on_windows(registry):
    values, opened = registry
    values[token_source.TOKEN_VARIABLE] = ("tok-from-registry", REG_SZ)

    assert token_source.web_token() == "tok-from-registry"
    assert ("HKCU", "Environment") in opened


def test_registry_wins_over_a_stale_process_environment(registry, monkeypatch):
    values, _ = registry
    values[token_source.TOKEN_VARIABLE] = ("fresh", REG_SZ)
    monkeypatch.setattr(config, "WEB_TOKEN", "stale")

    assert token_source.web_token() == "fresh"


def test_registry_values_with_variables_are_expanded(registry):
    values, _ = registry
    values[token_source.TOKEN_VARIABLE] = ("pre-%PART%", REG_EXPAND_SZ)

    assert token_source.web_token() == "pre-expanded"


@pytest.mark.parametrize("stored", [None, "", "   "])
def test_missing_or_blank_registry_value_falls_back_to_the_process(registry, monkeypatch, stored):
    values, _ = registry
    if stored is not None:
        values[token_source.TOKEN_VARIABLE] = (stored, REG_SZ)
    monkeypatch.setattr(config, "WEB_TOKEN", "from-process")

    assert token_source.web_token() == "from-process"


def test_no_token_at_all_is_empty(registry):
    assert token_source.web_token() == ""


def test_outside_windows_the_registry_is_not_read(monkeypatch):
    def boom():
        raise AssertionError("winreg must not be loaded outside Windows")

    monkeypatch.setattr(token_source.sys, "platform", "darwin")
    monkeypatch.setattr(token_source, "_winreg", boom)
    monkeypatch.setattr(config, "WEB_TOKEN", "")

    assert token_source.read_user_environment(token_source.TOKEN_VARIABLE) is None
    assert token_source.web_token() == ""


# --- macOS: el Llavero como fuente del sistema (issue #409, lote macos-keychain) ----------------
#
# `security` es siempre simulado: o un `subprocess.run` falso que anota cada llamada, o un
# programa propio de la suite. El Llavero real no se toca nunca (ver `real_keychain_unreachable`
# en `conftest.py`, que además vacía la caché por proceso en cada test).

SECRET = "kc-secret-7f3a-never-printed"


class _FakeSecurity:
    """`subprocess.run` de mentira: responde por servicio y anota argv y plazo de cada llamada."""

    def __init__(self, answers: dict[str, object]):
        self.answers = answers
        self.calls: list[tuple[list[str], object]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs.get("timeout")))
        service = argv[argv.index("-s") + 1]
        answer = self.answers.get(service)
        if isinstance(answer, BaseException):
            raise answer
        if answer is None:
            # Lo que da `security` cuando no encuentra el elemento.
            return subprocess.CompletedProcess(argv, 44, "", "item not found")
        return subprocess.CompletedProcess(argv, 0, f"{answer}\n", "")


@pytest.fixture
def macos(monkeypatch):
    """Simula macOS sin variables: devuelve el `security` falso para darle respuestas."""
    fake = _FakeSecurity({})
    monkeypatch.setattr(token_source.sys, "platform", "darwin")
    monkeypatch.setattr(token_source.subprocess, "run", fake)
    monkeypatch.setattr(token_source.getpass, "getuser", lambda: "ana")
    monkeypatch.setattr(token_source, "SECURITY_COMMAND", ("/usr/bin/security",))
    monkeypatch.setattr(config, "API_KEY", "")
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    return fake


def test_keychain_supplies_the_api_key_when_the_variable_is_missing(macos):
    macos.answers["local-delegate-remote"] = SECRET

    assert token_source.api_key() == SECRET
    assert token_source.resolve(token_source.API_KEY_VARIABLE) == (
        SECRET,
        token_source.SOURCE_KEYCHAIN,
    )
    argv, timeout = macos.calls[0]
    # El mismo comando que documenta la wiki, con la ruta absoluta: el PATH de launchd no manda.
    assert argv == [
        "/usr/bin/security",
        "find-generic-password",
        "-a",
        "ana",
        "-s",
        "local-delegate-remote",
        "-w",
    ]
    assert timeout == token_source.KEYCHAIN_TIMEOUT_SECONDS
    assert timeout <= 5


def test_the_default_program_is_the_absolute_security():
    """El de verdad (sin el doble de `conftest.py`), para que launchd no dependa de su PATH."""
    source = importlib.util.find_spec("local_delegate.token_source").origin
    with open(source, encoding="utf-8") as handle:
        assert 'SECURITY_COMMAND: tuple[str, ...] = ("/usr/bin/security",)' in handle.read()


def test_keychain_supplies_the_web_token_on_macos(macos):
    macos.answers["local-delegate-web-token"] = SECRET

    assert token_source.web_token() == SECRET
    assert macos.calls[0][0][5] == "local-delegate-web-token"


def test_the_variable_wins_over_the_keychain(macos, monkeypatch):
    macos.answers["local-delegate-remote"] = "from-keychain"
    monkeypatch.setattr(config, "API_KEY", "from-env")

    assert token_source.resolve(token_source.API_KEY_VARIABLE) == (
        "from-env",
        token_source.SOURCE_ENVIRONMENT,
    )
    assert macos.calls == []


@pytest.mark.parametrize(
    "literal",
    ["${LOCAL_DELEGATE_API_KEY}", "${LOCAL_DELEGATE_API_KEY:-}", "{env:LOCAL_DELEGATE_API_KEY}"],
)
def test_an_unexpanded_reference_is_not_a_key(macos, monkeypatch, literal):
    """Claude Code pasa `${VAR}` tal cual si no tiene la variable: es el caso del issue #409.

    Tomarlo por la clave taparía el Llavero y el backend daría 401 igual que antes.
    """
    macos.answers["local-delegate-remote"] = SECRET
    monkeypatch.setattr(config, "API_KEY", literal)

    assert token_source.resolve(token_source.API_KEY_VARIABLE) == (
        SECRET,
        token_source.SOURCE_KEYCHAIN,
    )
    assert config.auth_headers() == {"Authorization": f"Bearer {SECRET}"}


@pytest.mark.parametrize(
    "answer",
    [
        None,  # no está: `security` sale con 44
        "",  # salida vacía
        "   ",
        subprocess.TimeoutExpired(["security"], 3.0),  # Llavero bloqueado esperando un diálogo
        FileNotFoundError("/usr/bin/security"),
        PermissionError("denied"),
    ],
    ids=["missing", "empty", "blank", "timeout", "no-program", "not-allowed"],
)
def test_a_failed_or_empty_lookup_is_no_credential(macos, answer):
    macos.answers["local-delegate-remote"] = answer

    assert token_source.resolve(token_source.API_KEY_VARIABLE) == ("", None)
    assert config.auth_headers() == {}
    assert len(macos.calls) == 1


def test_the_lookup_runs_once_per_process_also_when_there_is_nothing(macos):
    macos.answers["local-delegate-web-token"] = SECRET

    for _ in range(3):
        assert token_source.api_key() == ""
        assert token_source.web_token() == SECRET

    services = [argv[5] for argv, _ in macos.calls]
    assert services == ["local-delegate-remote", "local-delegate-web-token"]


def test_a_hanging_security_is_cut_by_the_time_limit(monkeypatch, tmp_path):
    """Un `security` que no termina (diálogo del Llavero bloqueado) no cuelga al que pregunta."""
    hang = tmp_path / "security.py"
    hang.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(token_source.sys, "platform", "darwin")
    monkeypatch.setattr(token_source, "SECURITY_COMMAND", (sys.executable, str(hang)))
    monkeypatch.setattr(token_source, "KEYCHAIN_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(config, "API_KEY", "")

    started = time.monotonic()
    assert token_source.api_key() == ""
    assert time.monotonic() - started < 10


def test_a_real_program_answering_is_read(monkeypatch, tmp_path):
    """El camino de verdad (`subprocess.run` real) con un `security` propio que imprime la clave."""
    answer = tmp_path / "security.py"
    answer.write_text(
        "import sys\n"
        "assert sys.argv[1:] == ['find-generic-password', '-a', 'ana', '-s',"
        " 'local-delegate-remote', '-w'], sys.argv\n"
        f"print({SECRET!r})\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(token_source.sys, "platform", "darwin")
    monkeypatch.setattr(token_source.getpass, "getuser", lambda: "ana")
    monkeypatch.setattr(token_source, "SECURITY_COMMAND", (sys.executable, str(answer)))
    monkeypatch.setattr(config, "API_KEY", "")

    assert token_source.api_key() == SECRET


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_outside_macos_security_is_never_called(monkeypatch, platform):
    def boom(*_args, **_kwargs):
        raise AssertionError("security must not run outside macOS")

    monkeypatch.setattr(token_source.sys, "platform", platform)
    monkeypatch.setattr(token_source.subprocess, "run", boom)
    monkeypatch.setattr(token_source, "_winreg", lambda: _fake_winreg({}, []))
    monkeypatch.setattr(config, "API_KEY", "")
    monkeypatch.setattr(config, "WEB_TOKEN", "")

    assert token_source.api_key() == ""
    assert token_source.web_token() == ""
    assert config.auth_headers() == {}
    assert config.web_auth_headers() == {}


def test_importing_does_not_ask_the_keychain(monkeypatch):
    """Diferido: `token_source` no pregunta al importarse, solo al pedir la credencial."""
    calls: list = []
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "darwin")
        patch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
        importlib.reload(token_source)
        assert calls == []
    importlib.reload(token_source)


def test_config_headers_use_the_keychain_on_macos(macos):
    macos.answers["local-delegate-remote"] = SECRET
    macos.answers["local-delegate-web-token"] = "web-" + SECRET

    assert config.auth_headers() == {"Authorization": f"Bearer {SECRET}"}
    assert config.web_auth_headers() == {"Authorization": f"Bearer web-{SECRET}"}


def test_the_secret_never_reaches_logs_or_output(macos, caplog, capsys):
    macos.answers["local-delegate-remote"] = SECRET
    caplog.set_level(logging.DEBUG)

    token_source.api_key()
    token_source.resolve(token_source.API_KEY_VARIABLE)

    out = capsys.readouterr()
    assert SECRET not in out.out + out.err
    assert SECRET not in caplog.text
