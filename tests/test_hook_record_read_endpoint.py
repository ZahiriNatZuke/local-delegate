"""`hook record-read` servido por el daemon (SDD claude-plugin-and-mods, F4-read-fixes).

En la prueba en vivo de la 0.41.0 las decisiones del diálogo del mod de lectura (`summarized`,
`read_whole`, `dismissed`) nunca llegaron a la telemetría: el mod las registraba solo con
`$.process.run`, y esa vía se perdía en silencio tras `$.ui.ask`. Ahora el mod registra primero por
`POST /api/hook/record-read` y el proceso queda de respaldo. Las promesas del endpoint, cada una con
su prueba:

- **la misma línea que el CLI**: los dos caminos pasan por `hook_entry.record_read`, y para la misma
  entrada y el mismo entorno escriben la misma línea (salvo la hora);
- **el entorno es el del cliente**: el destino (`LD_HOOK_TELEMETRY_LOG`), el interruptor del
  experimento y el estado del bloqueo salen de las variables que manda el mod, no del daemon, y el
  entorno del daemon no se toca;
- **solo con token y solo desde loopback**, y un destino que no es un `.jsonl` absoluto se rechaza
  sin escribir nada (el endpoint no escribe donde le digan).
"""

from __future__ import annotations

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

TOKEN = "record-test-token"
RECORD = "/api/hook/record-read"
LOOPBACK = ("127.0.0.1", 50000)
TIMEOUT_S = 60


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(token_source, "daemon_token", lambda: TOKEN)
    return TestClient(metrics.app, client=LOOPBACK, headers={"Authorization": f"Bearer {TOKEN}"})


def _client_env(base: Path, log: Path, **extra: str) -> dict[str, str]:
    """Lo que manda el mod: las variables de `RECORD_ENV`, con destino y apagado propios."""
    data = base / "data"
    data.mkdir(parents=True, exist_ok=True)
    env = {
        "LOCAL_DELEGATE_LOG_DIR": str(data),
        "LD_HOOK_READ_SWITCH_FILE": str(base / "block-off"),
        "LD_HOOK_READ_ENABLED": "1",
        "LD_HOOK_READ_BLOCK": "1",
        "LD_HOOK_TELEMETRY_LOG": str(log),
    }
    env.update(extra)
    return env


def _entry(path: Path, decision: str, via: str = "read_whole", **extra) -> dict:
    """Lo que manda `readRecord`: la salida de `hook classify` más `decision` y `session_id`."""
    return {
        "kind": "read",
        "path": str(path),
        "scope": "whole" if via in {"read_whole", "shell_cat"} else "range",
        "bytes": path.stat().st_size,
        "range": None,
        "via": via,
        "read_switch": "on",
        "summarizable": True,
        "decision": decision,
        "session_id": "sess-1",
        **extra,
    }


def _prose(directory: Path, kb: int = 20) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "report.md"
    target.write_text("palabra ñandú\n" * (kb * 1024 // 15 + 1), encoding="utf-8")
    return target


def _lines(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def _without_ts(line: dict) -> dict:
    """La línea sin lo que cambia en cada escritura: la hora y el `id` aleatorio de un bloqueo (que
    sí debe estar en los dos o en ninguno)."""
    return {
        key: (value if key != "id" else bool(value)) for key, value in line.items() if key != "ts"
    }


def _cli_in_process(monkeypatch, entry: dict, env: dict[str, str]) -> None:
    """`hook_entry.main(["record-read"])` como lo corre `python -m local_delegate.hook`."""
    for name in hook_entry.RECORD_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(entry, ensure_ascii=False)))
    assert hook_entry.main(["record-read"]) == 0


# --- La misma línea que el CLI ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("decision", "via"),
    [
        ("summarized", "read_whole"),
        ("read_whole", "read_whole"),
        ("dismissed", "read_whole"),
        ("summarized", "shell_cat"),
        ("not_prose", "read_range"),
    ],
)
def test_the_endpoint_writes_the_line_the_cli_writes(tmp_path, monkeypatch, client, decision, via):
    prose = _prose(tmp_path / "docs")
    cli_log = tmp_path / "cli" / "telemetry.jsonl"
    http_log = tmp_path / "http" / "telemetry.jsonl"
    entry = _entry(prose, decision, via)

    _cli_in_process(monkeypatch, entry, _client_env(tmp_path, cli_log))
    for name in hook_entry.RECORD_ENV:
        monkeypatch.delenv(name, raising=False)
    response = client.post(RECORD, json={"payload": entry, "env": _client_env(tmp_path, http_log)})

    assert response.status_code == 204, response.text
    cli_lines, http_lines = _lines(cli_log), _lines(http_log)
    # Guarda: los dos caminos escribieron, y la línea es la de una decisión del mod.
    assert len(cli_lines) == len(http_lines) == 1, (cli_lines, http_lines)
    assert http_lines[0]["decision"] == decision
    assert http_lines[0]["source"] == "mod"
    assert http_lines[0]["block"] == "on"
    assert _without_ts(http_lines[0]) == _without_ts(cli_lines[0])


def test_the_endpoint_matches_the_real_cli_process(tmp_path, client):
    """El CLI en proceso de arriba es el de verdad: una fila por el proceso que lanza `runLd`."""
    prose = _prose(tmp_path / "docs")
    cli_log = tmp_path / "cli" / "telemetry.jsonl"
    http_log = tmp_path / "http" / "telemetry.jsonl"
    entry = _entry(prose, "summarized")
    base = {
        name: value
        for name, value in os.environ.items()
        if name not in config.ENVIRONMENT_VARIABLES
        and name not in hook_entry.RECORD_ENV
        and name not in {"PYTHONUTF8", "PYTHONIOENCODING", "PYTHONPATH"}
    }
    for name in ("HOME", "USERPROFILE", "LOCALAPPDATA", "SYSTEMROOT"):
        if name in os.environ:
            base[name] = os.environ[name]
    done = subprocess.run(
        [sys.executable, "-I", "-m", "local_delegate.hook", "record-read"],
        input=json.dumps(entry, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        env={**base, **_client_env(tmp_path, cli_log)},
        timeout=TIMEOUT_S,
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr
    response = client.post(RECORD, json={"payload": entry, "env": _client_env(tmp_path, http_log)})
    assert response.status_code == 204, response.text
    assert [_without_ts(x) for x in _lines(http_log)] == [_without_ts(x) for x in _lines(cli_log)]
    assert len(_lines(http_log)) == 1


# --- El entorno es el de la petición ---------------------------------------------------------------


def test_the_request_environment_wins_over_the_daemon(tmp_path, monkeypatch, client):
    """El daemon tiene otro destino, el experimento apagado y el bloqueo apagado por fichero."""
    daemon_log = tmp_path / "daemon" / "telemetry.jsonl"
    daemon_switch = tmp_path / "daemon-block-off"
    daemon_switch.write_text("", encoding="utf-8")
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(daemon_log))
    monkeypatch.setenv("LD_HOOK_ENABLED", "0")
    monkeypatch.setenv("LD_HOOK_READ_SWITCH_FILE", str(daemon_switch))
    before = dict(os.environ)
    prose = _prose(tmp_path / "docs")
    client_log = tmp_path / "client" / "telemetry.jsonl"

    response = client.post(
        RECORD,
        json={"payload": _entry(prose, "read_whole"), "env": _client_env(tmp_path, client_log)},
    )

    assert response.status_code == 204, response.text
    lines = _lines(client_log)
    assert len(lines) == 1
    assert lines[0]["block"] == "on"  # el del daemon diría `off_file`
    assert not daemon_log.exists()
    assert dict(os.environ) == before

    # Control: con el experimento apagado en la petición no se escribe nada, como en el CLI.
    off = _client_env(tmp_path, client_log, LD_HOOK_ENABLED="0")
    assert (
        client.post(RECORD, json={"payload": _entry(prose, "read_whole"), "env": off}).status_code
        == 204
    )
    assert len(_lines(client_log)) == 1


def test_without_a_destination_nothing_is_written(tmp_path, monkeypatch, client):
    """Sin `LD_HOOK_TELEMETRY_LOG` en la petición el CLI no escribe; el endpoint tampoco, aunque el
    daemon tenga la suya."""
    daemon_log = tmp_path / "daemon" / "telemetry.jsonl"
    monkeypatch.setenv("LD_HOOK_TELEMETRY_LOG", str(daemon_log))
    prose = _prose(tmp_path / "docs")
    env = _client_env(tmp_path, tmp_path / "x.jsonl")
    del env["LD_HOOK_TELEMETRY_LOG"]
    response = client.post(RECORD, json={"payload": _entry(prose, "summarized"), "env": env})
    assert response.status_code == 204
    assert not daemon_log.exists()


@pytest.mark.parametrize(
    "destination", ["relative/telemetry.jsonl", "{base}/telemetry.txt", "{base}/notes.json", ""]
)
def test_a_destination_that_is_not_an_absolute_jsonl_is_refused(tmp_path, client, destination):
    prose = _prose(tmp_path / "docs")
    target = destination.replace("{base}", str(tmp_path))
    env = _client_env(tmp_path, tmp_path / "unused.jsonl", LD_HOOK_TELEMETRY_LOG=target)
    response = client.post(RECORD, json={"payload": _entry(prose, "summarized"), "env": env})
    assert response.status_code == 400
    assert not (tmp_path / "telemetry.txt").exists()
    assert not (tmp_path / "notes.json").exists()
    # Control: el mismo cuerpo con un `.jsonl` absoluto entra.
    good = _client_env(tmp_path, tmp_path / "ok.jsonl")
    assert (
        client.post(RECORD, json={"payload": _entry(prose, "summarized"), "env": good}).status_code
        == 204
    )
    assert len(_lines(tmp_path / "ok.jsonl")) == 1


# --- Puerta ----------------------------------------------------------------------------------------


def test_without_token_401(monkeypatch, tmp_path):
    monkeypatch.setattr(token_source, "daemon_token", lambda: TOKEN)
    prose = _prose(tmp_path / "docs")
    log = tmp_path / "telemetry.jsonl"
    body = {"payload": _entry(prose, "summarized"), "env": _client_env(tmp_path, log)}
    assert TestClient(metrics.app, client=LOOPBACK).post(RECORD, json=body).status_code == 401
    wrong = TestClient(metrics.app, client=LOOPBACK, headers={"Authorization": "Bearer otro"})
    assert wrong.post(RECORD, json=body).status_code == 401
    assert not log.exists()
    good = TestClient(metrics.app, client=LOOPBACK, headers={"Authorization": f"Bearer {TOKEN}"})
    assert good.post(RECORD, json=body).status_code == 204
    assert len(_lines(log)) == 1


def test_only_from_loopback(monkeypatch, tmp_path):
    monkeypatch.setattr(token_source, "daemon_token", lambda: TOKEN)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    prose = _prose(tmp_path / "docs")
    log = tmp_path / "telemetry.jsonl"
    body = {"payload": _entry(prose, "summarized"), "env": _client_env(tmp_path, log)}
    lan = TestClient(metrics.app, client=("192.168.1.20", 50000), headers=headers)
    assert lan.post(RECORD, json=body).status_code == 403
    assert not log.exists()
    other_loopback = TestClient(metrics.app, client=("::1", 50000), headers=headers)
    assert other_loopback.post(RECORD, json=body).status_code == 204


def test_bad_bodies_are_rejected(client):
    for content in (b"no json", b"[1, 2]", b'{"payload": 3, "env": []}'):
        response = client.post(
            RECORD, content=content, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400, (content, response.status_code)
