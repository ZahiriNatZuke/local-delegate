"""El clasificador del mod de lectura servido por el daemon (SDD claude-plugin-and-mods,
F4-classify-daemon).

El mod le pregunta al daemon por HTTP en vez de arrancar `python -I -m local_delegate.hook classify`
en cada llamada. Tres promesas, y cada una tiene aquí su prueba:

- **una sola fuente de verdad**: para la misma entrada y el mismo entorno, el endpoint da el mismo
  JSON, byte a byte, que el CLI (`hook classify` y `hook classify --config`), sobre todo el corpus de
  `tests/fixtures/read_corpus.jsonl`;
- **el entorno es el del cliente**: el daemon no tiene el entorno de Claude Code, así que el mod
  manda las variables que lee el clasificador (`hook_entry.CLASSIFY_ENV`) y el endpoint usa esas, no
  las de su propio proceso; `cwd` y las rutas relativas, igual;
- **solo con token y solo desde loopback**, como el resto de rutas que el CLI pide al daemon.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_delegate import config, hook_entry, token_source
from local_delegate.web import metrics

ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "read_corpus.jsonl"
TOKEN = "classify-test-token"
CLASSIFY = "/api/hook/classify"
CONFIG = "/api/hook/classify-config"
LOOPBACK = ("127.0.0.1", 50000)
TIMEOUT_S = 60


def _load_corpus_helpers():
    """`_tool_call` de `test_read_classifier.py`: cómo se convierte una fila en una llamada."""
    spec = importlib.util.spec_from_file_location(
        "_endpoint_read_classifier_tests", ROOT / "tests" / "test_read_classifier.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


corpus_helpers = _load_corpus_helpers()


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(token_source, "daemon_token", lambda: TOKEN)
    return TestClient(metrics.app, client=LOOPBACK, headers={"Authorization": f"Bearer {TOKEN}"})


def _client_env(base: Path, **extra: str) -> dict[str, str]:
    """Lo que el mod manda: las variables de `CLASSIFY_ENV`, con datos y apagado propios."""
    data = base / "data"
    data.mkdir(parents=True, exist_ok=True)
    env = {
        "LOCAL_DELEGATE_LOG_DIR": str(data),
        "LD_HOOK_READ_SWITCH_FILE": str(base / "block-off"),
        "LD_HOOK_READ_ENABLED": "1",
        "LD_HOOK_READ_BLOCK": "1",
    }
    env.update(extra)
    return env


def _cli_in_process(monkeypatch, capsys, args: list[str], stdin: str, env: dict[str, str]) -> str:
    """`hook_entry.main` como lo corre `python -m local_delegate.hook`, con `env` como entorno."""
    for name in hook_entry.CLASSIFY_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    capsys.readouterr()
    assert hook_entry.main(args) == 0
    out = capsys.readouterr().out
    assert out.endswith("\n"), out
    return out[: -len("\n")]


def _cli_process(args: list[str], stdin: str, env: dict[str, str], cwd: Path) -> bytes:
    """El CLI de verdad, como lo lanza el mod (`runLd`): el intérprete aislado, por módulo."""
    base = {
        name: value
        for name, value in os.environ.items()
        if name not in config.ENVIRONMENT_VARIABLES
        and name not in hook_entry.CLASSIFY_ENV
        and name not in {"PYTHONUTF8", "PYTHONIOENCODING", "PYTHONPATH"}
    }
    # `HOME`/`USERPROFILE`/`LOCALAPPDATA` sí son del proceso: el CLI los hereda tal cual.
    for name in ("HOME", "USERPROFILE", "LOCALAPPDATA", "SYSTEMROOT"):
        if name in os.environ and name not in env:
            base[name] = os.environ[name]
    done = subprocess.run(
        [sys.executable, "-I", "-m", "local_delegate.hook", *args],
        input=stdin.encode("utf-8"),
        capture_output=True,
        env={**base, **env},
        timeout=TIMEOUT_S,
        cwd=cwd,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.rstrip(b"\r\n")


def _corpus_cases(cwd: Path) -> list[dict]:
    rows = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line]
    cases = []
    for index, row in enumerate(rows):
        tool_name, tool_input = corpus_helpers._tool_call(row)
        cases.append(
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "cwd": str(cwd),
                "session_id": f"s{index}",
            }
        )
    return cases


def _prose(directory: Path, name: str = "report.md", kb: int = 20) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    target.write_text("palabra ñandú\n" * (kb * 1024 // 15 + 1), encoding="utf-8")
    return target


# --- Igual que el CLI ------------------------------------------------------------------------------


def test_classify_matches_the_cli_on_the_whole_corpus(tmp_path, monkeypatch, capsys, client):
    env = _client_env(tmp_path)
    cases = _corpus_cases(tmp_path)
    assert len(cases) > 700  # guarda: el corpus llegó entero
    # Unas filas que sí tocan ficheros de verdad, con rutas relativas al `cwd` de la llamada.
    _prose(tmp_path / "docs")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "big.py").write_text("x = 1\n" * 4000, encoding="utf-8")
    for tool_input in (
        {"file_path": "docs/report.md"},
        {"command": "sed -n 5,40p docs/report.md"},
        {"command": "cat src/big.py"},
        {"command": "cd docs && head -n 20 report.md"},
    ):
        tool_name = "Read" if "file_path" in tool_input else "Bash"
        cases.append(
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "cwd": str(tmp_path),
                "session_id": "s",
            }
        )
    kinds = set()
    for payload in cases:
        stdin = json.dumps(payload, ensure_ascii=False)
        expected = _cli_in_process(monkeypatch, capsys, ["classify"], stdin, env)
        response = client.post(CLASSIFY, json={"payload": payload, "env": env})
        assert response.status_code == 200, response.text
        assert response.content == expected.encode("utf-8"), payload
        answer = json.loads(response.content)
        kinds.add((answer["kind"], answer["summarizable"], answer["read_switch"]))
    # Guarda: la comparación vio lecturas, escrituras y otras, y prosa resumible de verdad.
    assert {k for k, _, _ in kinds} == {"read", "write", "other"}, kinds
    assert ("read", True, "on") in kinds, kinds


def test_classify_matches_the_real_cli_process(tmp_path, client):
    """El CLI en proceso de arriba es el mismo que el de verdad: unas filas por el proceso."""
    env = _client_env(tmp_path)
    prose = _prose(tmp_path / "docs")
    cases = [
        {"tool_name": "Read", "tool_input": {"file_path": "docs/report.md"}, "cwd": str(tmp_path)},
        {
            "tool_name": "Bash",
            "tool_input": {"command": "sed -n 5,40p docs/report.md"},
            "cwd": str(tmp_path),
        },
        {"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": str(tmp_path)},
        {"tool_name": "Write", "tool_input": {"file_path": str(prose)}, "cwd": str(tmp_path)},
    ]
    for payload in cases:
        stdin = json.dumps(payload, ensure_ascii=False)
        expected = _cli_process(["classify"], stdin, env, tmp_path)
        response = client.post(CLASSIFY, json={"payload": payload, "env": env})
        assert response.status_code == 200, response.text
        assert response.content == expected, payload
    expected = _cli_process(["classify", "--config"], "", env, tmp_path)
    assert client.post(CONFIG, json={"env": env}).content == expected


def test_config_matches_the_cli(tmp_path, monkeypatch, capsys, client):
    for extra in ({}, {"LD_HOOK_READ_SUGGEST_KB": "3"}, {"LD_HOOK_READ_SUGGEST_KB": "mal"}):
        env = _client_env(tmp_path, **extra)
        expected = _cli_in_process(monkeypatch, capsys, ["classify", "--config"], "", env)
        response = client.post(CONFIG, json={"env": env})
        assert response.status_code == 200, response.text
        assert response.content == expected.encode("utf-8"), extra


# --- El entorno es el de la petición ---------------------------------------------------------------


def test_the_request_environment_wins_over_the_daemon(tmp_path, monkeypatch, client):
    """El daemon tiene otro entorno: apagado por fichero, umbral alto y sin la capa «activo»."""
    daemon_switch = tmp_path / "daemon-block-off"
    daemon_switch.write_text("", encoding="utf-8")
    monkeypatch.setenv("LD_HOOK_READ_SWITCH_FILE", str(daemon_switch))
    monkeypatch.setenv("LD_HOOK_READ_SUGGEST_KB", "1000")
    monkeypatch.delenv("LD_HOOK_READ_ENABLED", raising=False)
    monkeypatch.delenv("LD_HOOK_READ_BLOCK", raising=False)
    monkeypatch.chdir(tmp_path.parent)  # el `cwd` del daemon no es el de la llamada
    prose = _prose(tmp_path / "docs", kb=20)
    env = _client_env(tmp_path, LD_HOOK_READ_SUGGEST_KB="4")  # sin fichero de apagado
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": "docs/report.md"},
        "cwd": str(tmp_path),
    }

    answer = client.post(CLASSIFY, json={"payload": payload, "env": env}).json()
    assert answer["read_switch"] == "on"  # el del daemon diría `inactive`
    assert answer["summarizable"] is True  # con 1000 KB del daemon, 20 KB no lo serían
    assert answer["path"] == str(prose)  # relativa al `cwd` de la llamada, no al del daemon
    assert answer["bytes"] == prose.stat().st_size
    config_answer = client.post(CONFIG, json={"env": env}).json()
    assert config_answer["min_bytes"] == 4 * 1024

    # Control: con el entorno del daemon en la petición, sale lo del daemon.
    daemon_env = _client_env(tmp_path, LD_HOOK_READ_SUGGEST_KB="1000")
    daemon_env["LD_HOOK_READ_SWITCH_FILE"] = str(daemon_switch)
    other = client.post(CLASSIFY, json={"payload": payload, "env": daemon_env}).json()
    assert other["read_switch"] == "off_file"
    assert other["summarizable"] is False


def test_a_variable_missing_from_the_request_is_not_taken_from_the_daemon(
    tmp_path, monkeypatch, client
):
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1")
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": "docs/report.md"},
        "cwd": str(tmp_path),
    }
    env = {"LOCAL_DELEGATE_LOG_DIR": str(tmp_path / "data")}
    answer = client.post(CLASSIFY, json={"payload": payload, "env": env}).json()
    assert answer["read_switch"] == "inactive"


def test_unknown_or_non_text_variables_are_ignored(tmp_path, client):
    payload = {"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": str(tmp_path)}
    env = {"PATH": "x", "LD_HOOK_READ_ENABLED": 1, "LOCAL_DELEGATE_LOG_DIR": str(tmp_path / "data")}
    answer = client.post(CLASSIFY, json={"payload": payload, "env": env}).json()
    assert answer["read_switch"] == "inactive"
    assert answer["kind"] == "other"


def test_the_endpoint_leaves_the_daemon_environment_alone(tmp_path, monkeypatch, client):
    monkeypatch.delenv("LD_HOOK_READ_ENABLED", raising=False)
    before = dict(os.environ)
    payload = {"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": str(tmp_path)}
    client.post(CLASSIFY, json={"payload": payload, "env": _client_env(tmp_path)})
    client.post(CONFIG, json={"env": _client_env(tmp_path)})
    assert dict(os.environ) == before


# --- Puerta ----------------------------------------------------------------------------------------


def test_without_token_401(monkeypatch, tmp_path):
    monkeypatch.setattr(token_source, "daemon_token", lambda: TOKEN)
    bare = TestClient(metrics.app, client=LOOPBACK)
    body = {"payload": {"tool_name": "Bash", "tool_input": {"command": "ls"}}, "env": {}}
    assert bare.post(CLASSIFY, json=body).status_code == 401
    assert bare.post(CONFIG, json={"env": {}}).status_code == 401
    wrong = TestClient(metrics.app, client=LOOPBACK, headers={"Authorization": "Bearer otro"})
    assert wrong.post(CLASSIFY, json=body).status_code == 401
    # Control: con el token entra.
    good = TestClient(metrics.app, client=LOOPBACK, headers={"Authorization": f"Bearer {TOKEN}"})
    assert good.post(CLASSIFY, json=body).status_code == 200


def test_only_from_loopback(monkeypatch):
    monkeypatch.setattr(token_source, "daemon_token", lambda: TOKEN)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    lan = TestClient(metrics.app, client=("192.168.1.20", 50000), headers=headers)
    body = {"payload": {"tool_name": "Bash", "tool_input": {"command": "ls"}}, "env": {}}
    assert lan.post(CLASSIFY, json=body).status_code == 403
    assert lan.post(CONFIG, json={"env": {}}).status_code == 403
    other_loopback = TestClient(metrics.app, client=("::1", 50000), headers=headers)
    assert other_loopback.post(CLASSIFY, json=body).status_code == 200


def test_bad_bodies_are_rejected_without_a_trace(client):
    for content in (b"no json", b"[1, 2]", b'{"payload": 3, "env": []}'):
        response = client.post(
            CLASSIFY, content=content, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400, (content, response.status_code)
