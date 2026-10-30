"""Concurrency PC+Mac, lot 5: `doctor` and the remote turn (REQ-027).

Two halves, both inside the existing `backend.topology` check («daemon turn»), so the number of
checks does not change:

- `remote_turn.probe`: a `release` of a lease nobody holds, against the daemon of lot 3 running in
  this process (`daemon.build_app` behind a `TestClient`, as in `test_remote_turn_client.py`). It
  must say who answers and how, and change nothing at the daemon.
- `checks._probe_topology`: the client side (the backend on another machine) and the server side
  (this machine's daemon: does its endpoint have a secret, and which models could a remote
  operation not name), with `turn_probe` doubled and once with the real probe end to end.

Hosts are examples (`pc.example-tailnet.ts.net`, `api.example.com`, `203.0.113.5`): nothing here
leaves the process.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_delegate import (
    checks,
    config,
    daemon,
    i18n,
    llamaswap_api,
    remote_turn,
    server,
    turn_leases,
)
from local_delegate.web import turn_api

_DAEMON_PORT = 19393
_URL = f"http://127.0.0.1:{_DAEMON_PORT}/"
LOOPBACK_BASE = "http://127.0.0.1:9292/v1"
TAILNET_BASE = "https://pc.example-tailnet.ts.net:9292/v1"
TAILNET_TURN = f"https://pc.example-tailnet.ts.net:{config.WEB_PORT}/"
BACKEND_KEY = "the-backend-key-0123456789"
TODAY = Path(__file__).parent / "fixtures" / "topology" / "today.yaml"


# --- the probe against the real endpoint -----------------------------------------------------


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """The PC's daemon in process (topology on loopback, the backend key as its secret)."""
    copy = tmp_path / "llamaswap.yaml"
    copy.write_bytes(TODAY.read_bytes())
    monkeypatch.setenv("LLAMASWAP_CONFIG", str(copy))
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "BASE_URL", LOOPBACK_BASE)
    monkeypatch.setattr(config, "API_KEY", BACKEND_KEY)
    monkeypatch.setattr(config, "WEB_TOKEN", "")
    monkeypatch.setattr(config, "REMOTE_WEB_TOKEN", "")
    monkeypatch.setattr(config, "TURN_SERVER", True)
    monkeypatch.setattr(config, "TURN_URL", "off")
    monkeypatch.setattr(server, "_turn", server._new_turn())
    monkeypatch.setattr(server._turn_version, "value", None)
    server._topology()
    turn_leases.reset()
    remote_turn.reset()
    with TestClient(daemon.build_app("127.0.0.1", _DAEMON_PORT), base_url=_URL) as client:
        remote_turn.set_client_factory(lambda: client)
        yield client
    remote_turn.set_client_factory(remote_turn._new_client)
    remote_turn.reset()
    turn_leases.reset()
    turn_api.disable()


def _acquire(client: TestClient) -> str:
    answer = client.post(
        "/api/turn/acquire",
        json={"op": "1-1", "host": "mac-test", "tool": "local_summarize", "model": "gemma3-4b"},
        headers={"Authorization": f"Bearer {BACKEND_KEY}"},
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["status"] == "granted"
    return answer.json()["lease"]


def test_probe_with_the_backend_key_is_reachable_and_changes_nothing(pc):
    lease = _acquire(pc)
    before = turn_leases.table().get(lease)
    assert before is not None

    assert remote_turn.probe(_URL) == remote_turn.REACHABLE

    # The lease of another operation is still there, untouched, and no other one appeared.
    assert turn_leases.table().get(lease) is before
    assert len(turn_leases.table()._leases) == 1


def test_probe_with_a_wrong_credential_is_unauthorized(pc, monkeypatch):
    monkeypatch.setattr(remote_turn, "credential", lambda: "another-key-0123456789")
    assert remote_turn.probe(_URL) == remote_turn.UNAUTHORIZED


def test_probe_without_credential_tells_whether_the_daemon_has_a_secret(pc, monkeypatch):
    assert remote_turn.probe(_URL, with_credential=False) == remote_turn.UNAUTHORIZED
    monkeypatch.setattr(config, "API_KEY", "")
    assert remote_turn.probe(_URL, with_credential=False) == remote_turn.NEEDS_SECRET


def test_probe_of_a_daemon_with_the_server_off_is_unsupported(pc, monkeypatch):
    monkeypatch.setattr(config, "TURN_SERVER", False)
    assert remote_turn.probe(_URL) == remote_turn.UNSUPPORTED


def test_probe_of_this_machines_own_daemon_is_self(pc):
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    (config.LOG_DIR / "daemon.json").write_text(
        json.dumps({"daemon_id": turn_leases.DAEMON_ID}), encoding="utf-8"
    )
    assert remote_turn.probe(_URL) == remote_turn.SELF


def test_probe_without_a_credential_to_send_asks_nothing(pc, monkeypatch):
    monkeypatch.setattr(remote_turn, "credential", lambda: "")
    sent: list[str] = []
    monkeypatch.setattr(remote_turn._Transport, "get", classmethod(lambda cls: sent.append("x")))
    assert remote_turn.probe(_URL) == remote_turn.NO_CREDENTIAL
    assert sent == []


@pytest.mark.parametrize(
    ("status_code", "body", "verdict"),
    [
        (200, b'{"v": 1, "status": "released"}', remote_turn.REACHABLE),
        (200, b'{"v": 2, "status": "released"}', remote_turn.UNSUPPORTED),
        (200, b'{"status": "released"}', remote_turn.BAD_RESPONSE),
        (200, b'{"v": 1, "status": "granted"}', remote_turn.BAD_RESPONSE),
        (200, b"<html>", remote_turn.BAD_RESPONSE),
        (200, b"[" * 3000 + b"]" * 3000, remote_turn.BAD_RESPONSE),
        (404, b'{"detail": "Not Found"}', remote_turn.UNSUPPORTED),
        (405, b"", remote_turn.UNSUPPORTED),
        (401, b'{"error": "unauthorized"}', remote_turn.UNAUTHORIZED),
        (403, b'{"error": "turn_needs_secret"}', remote_turn.NEEDS_SECRET),
        (403, b'{"error": "origin_not_allowed"}', remote_turn.UNAUTHORIZED),
        (429, b"", remote_turn.BAD_RESPONSE),
        (500, b"", remote_turn.BAD_RESPONSE),
    ],
)
def test_probe_verdicts(tmp_path, monkeypatch, status_code, body, verdict):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    assert remote_turn._probe_verdict(status_code, body) == verdict


def test_probe_of_a_daemon_that_does_not_answer_is_unreachable(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise OSError("connection refused")

    class Refusing:
        stream = staticmethod(refuse)

        def close(self) -> None:
            pass

    monkeypatch.setattr(config, "API_KEY", BACKEND_KEY)
    monkeypatch.setattr(config, "REMOTE_WEB_TOKEN", "")
    remote_turn.set_client_factory(Refusing)
    try:
        assert remote_turn.probe(_URL) == remote_turn.UNREACHABLE
    finally:
        remote_turn.set_client_factory(remote_turn._new_client)
        remote_turn.reset()


# --- `doctor`: the client side (the backend on another machine) ------------------------------


class Recorder:
    """A doubled `turn_probe`: answers `verdict` and keeps what it was asked."""

    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.calls: list[tuple[str, bool]] = []

    def __call__(self, url: str, with_credential: bool) -> str:
        self.calls.append((url, with_credential))
        return self.verdict


@pytest.fixture
def mac(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "BASE_URL", TAILNET_BASE)
    monkeypatch.setattr(config, "API_KEY", BACKEND_KEY)
    monkeypatch.setattr(config, "REMOTE_WEB_TOKEN", "")
    monkeypatch.setattr(config, "TURN_URL", "auto")
    remote_turn.reset()
    yield tmp_path
    remote_turn.reset()


def _ctx(tmp_path, probe, **kwargs) -> checks.Context:
    kwargs.setdefault("llamaswap_daemon", checks.NO_LLAMASWAP_DAEMON)
    return checks.Context(home=tmp_path, turn_probe=probe, **kwargs)


def test_client_with_a_turn_is_ok_and_asks_the_tailnet_daemon_with_the_credential(mac):
    probe = Recorder(remote_turn.REACHABLE)
    r = checks._probe_topology(_ctx(mac, probe))
    assert probe.calls == [(TAILNET_TURN, True)]
    assert r.status == checks.OK
    assert i18n.t("doctor.probe.topology.remote_active", url=TAILNET_TURN) in r.detail


@pytest.mark.parametrize(
    "reason",
    [
        remote_turn.UNREACHABLE,
        remote_turn.UNSUPPORTED,
        remote_turn.UNAUTHORIZED,
        remote_turn.NEEDS_SECRET,
        remote_turn.BAD_RESPONSE,
        remote_turn.NO_CREDENTIAL,
    ],
)
def test_client_without_a_turn_warns_with_the_reason_and_its_fix(mac, reason):
    r = checks._probe_topology(_ctx(mac, Recorder(reason)))
    assert r.status == checks.WARN
    assert f"({reason})" in r.detail
    assert r.fix_hint == checks.remote_turn_hint(reason)
    assert r.fix_hint and not r.fix_hint.startswith("doctor.")


def test_client_never_says_the_credential(mac):
    r = checks._probe_topology(_ctx(mac, Recorder(remote_turn.UNAUTHORIZED)))
    assert BACKEND_KEY not in r.detail + r.fix_hint


def test_client_with_turn_url_off_asks_nothing_and_keeps_the_old_verdict(mac, monkeypatch):
    monkeypatch.setattr(config, "TURN_URL", "off")
    probe = Recorder(remote_turn.REACHABLE)
    r = checks._probe_topology(_ctx(mac, probe))
    assert probe.calls == []
    assert r.status == checks.UNKNOWN
    assert i18n.t("doctor.probe.topology.remote_active", url=TAILNET_TURN) not in r.detail


def test_client_with_a_public_backend_never_asks_it(mac, monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "https://api.example.com/v1")
    probe = Recorder(remote_turn.REACHABLE)
    r = checks._probe_topology(_ctx(mac, probe))
    assert probe.calls == []
    assert r.status == checks.UNKNOWN
    assert i18n.t("doctor.probe.topology.remote_public") in r.detail


def test_client_with_a_bad_turn_url_warns_without_asking(mac, monkeypatch):
    monkeypatch.setattr(config, "TURN_URL", "http://user:pw@pc.example-tailnet.ts.net:9393/")
    probe = Recorder(remote_turn.REACHABLE)
    r = checks._probe_topology(_ctx(mac, probe))
    assert probe.calls == []
    assert r.status == checks.WARN
    assert r.fix_hint == checks.remote_turn_hint(remote_turn.BAD_URL)


def test_client_in_plaintext_to_a_public_host_warns(mac, monkeypatch):
    monkeypatch.setattr(config, "TURN_URL", "http://203.0.113.5:9393")
    probe = Recorder(remote_turn.REACHABLE)
    r = checks._probe_topology(_ctx(mac, probe))
    assert probe.calls == [("http://203.0.113.5:9393/", True)]
    assert r.status == checks.WARN
    assert r.fix_hint == checks.remote_turn_hint("plaintext")


def test_client_pointing_at_its_own_port_asks_nothing(mac, monkeypatch):
    monkeypatch.setattr(config, "TURN_URL", f"http://127.0.0.1:{config.WEB_PORT}")
    probe = Recorder(remote_turn.REACHABLE)
    r = checks._probe_topology(_ctx(mac, probe))
    assert probe.calls == []
    assert r.status == checks.UNKNOWN


# --- `doctor`: the server side (this machine's daemon) ---------------------------------------


@pytest.fixture
def the_pc(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "BASE_URL", LOOPBACK_BASE)
    monkeypatch.setattr(config, "TURN_URL", "auto")
    return tmp_path


def _config_with(tmp_path: Path, *names: str, aliases: dict[str, list[str]] | None = None) -> Path:
    lines = ["models:"]
    for name in names:
        lines += [f'  "{name}":', "    cmd: x --port ${PORT}"]
        for alias in (aliases or {}).get(name, []):
            lines += ["    aliases:", f'      - "{alias}"']
    lines += ["groups:", "  swap:", "    swap: true", "    members:"]
    lines += [f'      - "{name}"' for name in names]
    path = tmp_path / "llamaswap.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_server_without_a_secret_warns(the_pc):
    probe = Recorder(remote_turn.NEEDS_SECRET)
    r = checks._probe_topology(_ctx(the_pc, probe, config_path=_config_with(the_pc, "a", "b")))
    # Asked without the credential: the question is whether the daemon has one, not ours.
    assert [with_credential for _url, with_credential in probe.calls] == [False]
    assert r.status == checks.WARN
    assert i18n.t("doctor.probe.topology.server_needs_secret") in r.detail
    assert r.fix_hint == checks.remote_turn_hint(remote_turn.NEEDS_SECRET)


def test_server_with_a_secret_and_clean_names_is_ok(the_pc):
    r = checks._probe_topology(
        _ctx(the_pc, Recorder(remote_turn.UNAUTHORIZED), config_path=_config_with(the_pc, "a"))
    )
    assert r.status == checks.OK
    assert i18n.t("doctor.probe.topology.server_ready") in r.detail


def test_server_warns_of_models_a_remote_operation_cannot_name(the_pc):
    path = _config_with(the_pc, "qwen3:30b", "org/model", "clean-one")
    r = checks._probe_topology(_ctx(the_pc, Recorder(remote_turn.UNAUTHORIZED), config_path=path))
    assert r.status == checks.WARN
    note = i18n.t("doctor.probe.topology.server_unnamed_models", models="qwen3:30b, org/model")
    assert note in r.detail
    assert checks._models_without_remote_turn(path) == ["qwen3:30b", "org/model"]
    assert r.fix_hint == checks.remote_turn_hint("unnamed_models")


def test_a_clean_alias_makes_a_model_nameable(the_pc):
    path = _config_with(the_pc, "qwen3:30b", aliases={"qwen3:30b": ["qwen3-30b"]})
    assert checks._models_without_remote_turn(path) == []
    r = checks._probe_topology(_ctx(the_pc, Recorder(remote_turn.UNAUTHORIZED), config_path=path))
    assert r.status == checks.OK


@pytest.mark.parametrize(
    "verdict", [remote_turn.UNREACHABLE, remote_turn.UNSUPPORTED, remote_turn.BAD_RESPONSE]
)
def test_server_without_the_endpoint_in_play_keeps_the_old_verdict(the_pc, verdict):
    path = _config_with(the_pc, "qwen3:30b")
    plain = checks._local_turn(_ctx(the_pc, Recorder(verdict), config_path=path))[0]
    r = checks._probe_topology(_ctx(the_pc, Recorder(verdict), config_path=path))
    assert r == plain


def test_server_side_is_not_asked_without_a_local_turn(the_pc):
    probe = Recorder(remote_turn.NEEDS_SECRET)
    r = checks._probe_topology(_ctx(the_pc, probe, config_path=None))
    assert probe.calls == []
    assert r.status == checks.UNKNOWN


def test_server_side_follows_the_daemons_config(the_pc):
    path = _config_with(the_pc, "qwen3:30b")
    status = llamaswap_api.Status(
        llamaswap_api.STATE_OK, config_path=str(path), turn_active=True, turn_detail="x"
    )
    r = checks._probe_topology(
        _ctx(the_pc, Recorder(remote_turn.UNAUTHORIZED), llamaswap_daemon=lambda: (status, ""))
    )
    assert r.status == checks.WARN
    assert i18n.t("doctor.probe.topology.server_unnamed_models", models="qwen3:30b") in r.detail


# --- end to end: the real probe against the daemon in process --------------------------------


def test_doctor_on_the_pc_with_the_real_probe(pc, monkeypatch, tmp_path):
    monkeypatch.setattr(
        checks, "_llamaswap_daemon_destination", lambda: ("127.0.0.1", _DAEMON_PORT, {})
    )
    path = _config_with(tmp_path, "gemma3-4b", "qwen3:30b")
    ctx = checks.Context(
        home=tmp_path, config_path=path, llamaswap_daemon=checks.NO_LLAMASWAP_DAEMON
    )
    r = checks._probe_topology(ctx)
    assert r.status == checks.WARN
    assert i18n.t("doctor.probe.topology.server_unnamed_models", models="qwen3:30b") in r.detail

    monkeypatch.setattr(config, "API_KEY", "")
    r = checks._probe_topology(ctx)
    assert r.status == checks.WARN
    assert i18n.t("doctor.probe.topology.server_needs_secret") in r.detail


def test_doctor_on_the_mac_with_the_real_probe(pc, monkeypatch, tmp_path):
    # The Mac's view of the same daemon: an explicit TURN_URL (the `ssh -L` case) and no local turn.
    monkeypatch.setattr(config, "TURN_URL", _URL)
    ctx = checks.Context(
        home=tmp_path, config_path=None, llamaswap_daemon=checks.NO_LLAMASWAP_DAEMON
    )
    r = checks._probe_topology(ctx)
    assert r.status == checks.OK
    assert i18n.t("doctor.probe.topology.remote_active", url=_URL) in r.detail
    assert turn_leases.table().get(remote_turn.PROBE_LEASE) is None
