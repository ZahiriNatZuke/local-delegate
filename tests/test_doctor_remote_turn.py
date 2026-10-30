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

import argparse
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


def _before_the_pr(ctx: checks.Context) -> checks.Result:
    """The verdict of the check as `main` gave it: the local turn alone, nothing asked."""
    return checks._local_turn(ctx, *ctx.llamaswap_daemon())[0]


def test_client_with_a_turn_is_ok_and_asks_the_tailnet_daemon_with_the_credential(mac):
    probe = Recorder(remote_turn.REACHABLE)
    r = checks._probe_topology(_ctx(mac, probe))
    assert probe.calls == [(TAILNET_TURN, True)]
    assert r.status == checks.OK
    assert i18n.t("doctor.probe.topology.remote_active", url=TAILNET_TURN) in r.detail


#: Reasons a private backend that is not ours also gives (ollama, a bare llama-swap on the LAN).
SOFT = [remote_turn.UNREACHABLE, remote_turn.UNSUPPORTED, remote_turn.NO_CREDENTIAL]
#: Reasons only a daemon of ours, badly set up, gives.
HARD = [remote_turn.UNAUTHORIZED, remote_turn.NEEDS_SECRET, remote_turn.BAD_RESPONSE]


@pytest.mark.parametrize("reason", SOFT)
def test_client_with_auto_and_a_backend_that_may_not_be_ours_only_notes_it(mac, reason):
    ctx = _ctx(mac, Recorder(reason))
    before = _before_the_pr(ctx)
    r = checks._probe_topology(ctx)
    assert r.status == before.status
    assert not checks.is_warning(r.status)
    note = i18n.t("doctor.probe.topology.remote_unusable_auto", url=TAILNET_TURN, reason=reason)
    assert r.detail == f"{before.detail}; {note}"
    assert "LOCAL_DELEGATE_TURN_URL=off" in note


@pytest.mark.parametrize("reason", SOFT)
def test_client_with_an_explicit_turn_url_warns_of_the_same_reasons(mac, monkeypatch, reason):
    monkeypatch.setattr(config, "TURN_URL", TAILNET_TURN)
    r = checks._probe_topology(_ctx(mac, Recorder(reason)))
    assert r.status == checks.WARN
    assert f"({reason})" in r.detail
    assert r.fix_hint == checks.remote_turn_hint(reason)


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("reason", HARD)
def test_client_warns_of_a_daemon_of_ours_badly_set_up_either_way(
    mac, monkeypatch, reason, explicit
):
    if explicit:
        monkeypatch.setattr(config, "TURN_URL", TAILNET_TURN)
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
    ctx = _ctx(mac, probe)
    r = checks._probe_topology(ctx)
    assert probe.calls == []
    assert r == _before_the_pr(ctx)


def test_client_with_a_public_backend_never_asks_it_and_says_exactly_what_main_said(
    mac, monkeypatch
):
    monkeypatch.setattr(config, "BASE_URL", "https://api.example.com/v1")
    probe = Recorder(remote_turn.REACHABLE)
    ctx = _ctx(mac, probe)
    r = checks._probe_topology(ctx)
    assert probe.calls == []
    assert r == _before_the_pr(ctx)


def test_client_with_a_bad_turn_url_warns_without_asking(mac, monkeypatch):
    monkeypatch.setattr(config, "TURN_URL", "http://user:pw@pc.example-tailnet.ts.net:9393/")
    probe = Recorder(remote_turn.REACHABLE)
    r = checks._probe_topology(_ctx(mac, probe))
    assert probe.calls == []
    assert r.status == checks.WARN
    assert r.fix_hint == checks.remote_turn_hint(remote_turn.BAD_URL)


@pytest.mark.parametrize(
    "verdict", [remote_turn.REACHABLE, remote_turn.UNREACHABLE, remote_turn.UNAUTHORIZED]
)
def test_client_in_plaintext_to_a_public_host_warns_whatever_the_answer(mac, monkeypatch, verdict):
    monkeypatch.setattr(config, "TURN_URL", "http://203.0.113.5:9393")
    probe = Recorder(verdict)
    r = checks._probe_topology(_ctx(mac, probe))
    assert probe.calls == [("http://203.0.113.5:9393/", True)]
    assert r.status == checks.WARN
    shown = "http://203.0.113.5:9393/"
    assert i18n.t("doctor.probe.topology.remote_plaintext", url=shown) in r.detail
    assert checks.remote_turn_hint("plaintext") in r.fix_hint
    if verdict != remote_turn.REACHABLE:
        assert checks.remote_turn_hint(verdict) in r.fix_hint


def test_client_in_plaintext_to_a_private_host_does_not_warn(mac, monkeypatch):
    monkeypatch.setattr(config, "TURN_URL", "http://pc.example-tailnet.ts.net:9393")
    r = checks._probe_topology(_ctx(mac, Recorder(remote_turn.REACHABLE)))
    assert r.status == checks.OK


def test_client_pointing_at_its_own_port_asks_nothing(mac, monkeypatch):
    monkeypatch.setattr(config, "TURN_URL", f"http://127.0.0.1:{config.WEB_PORT}")
    probe = Recorder(remote_turn.REACHABLE)
    r = checks._probe_topology(_ctx(mac, probe))
    assert probe.calls == []
    assert r.status == checks.UNKNOWN


# --- `doctor`: the server side (this machine's daemon) ---------------------------------------


def _answering_daemon():
    """A daemon that answers but says nothing of its turn (the shell's config decides)."""
    return llamaswap_api.Status(llamaswap_api.STATE_OK), ""


@pytest.fixture
def the_pc(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "BASE_URL", LOOPBACK_BASE)
    monkeypatch.setattr(config, "TURN_URL", "auto")
    return tmp_path


def _pc_ctx(tmp_path, probe, **kwargs) -> checks.Context:
    kwargs.setdefault("llamaswap_daemon", _answering_daemon)
    return _ctx(tmp_path, probe, **kwargs)


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


def test_server_without_a_secret_only_notes_it(the_pc):
    probe = Recorder(remote_turn.NEEDS_SECRET)
    ctx = _pc_ctx(the_pc, probe, config_path=_config_with(the_pc, "qwen3:30b", "b"))
    before = _before_the_pr(ctx)
    r = checks._probe_topology(ctx)
    # Asked without the credential: the question is whether the daemon has one, not ours.
    assert [with_credential for _url, with_credential in probe.calls] == [False]
    assert before.status == checks.OK
    assert r.status == checks.OK
    assert r.fix_hint == before.fix_hint
    note = i18n.t("doctor.probe.topology.server_no_secret")
    assert r.detail == f"{before.detail}; {note}"
    # Its own words: a second machine, the two secrets, and how to turn the endpoint off.
    for text in (
        "LOCAL_DELEGATE_API_KEY",
        "LOCAL_DELEGATE_WEB_TOKEN",
        "LOCAL_DELEGATE_TURN_SERVER=off",
    ):
        assert text in note
    # Without a secret, the models a remote operation cannot name are not looked at.
    assert "qwen3:30b" not in note


def test_server_with_a_secret_and_clean_names_is_ok(the_pc):
    r = checks._probe_topology(
        _pc_ctx(the_pc, Recorder(remote_turn.UNAUTHORIZED), config_path=_config_with(the_pc, "a"))
    )
    assert r.status == checks.OK
    assert i18n.t("doctor.probe.topology.server_ready") in r.detail


def test_server_warns_of_models_a_remote_operation_cannot_name(the_pc):
    path = _config_with(the_pc, "qwen3:30b", "org/model", "clean-one")
    r = checks._probe_topology(
        _pc_ctx(the_pc, Recorder(remote_turn.UNAUTHORIZED), config_path=path)
    )
    assert r.status == checks.WARN
    note = i18n.t("doctor.probe.topology.server_unnamed_models", models="qwen3:30b, org/model")
    assert note in r.detail
    assert checks._models_without_remote_turn(path) == ["qwen3:30b", "org/model"]
    assert r.fix_hint == checks.remote_turn_hint("unnamed_models")


def test_a_clean_alias_makes_a_model_nameable(the_pc):
    path = _config_with(the_pc, "qwen3:30b", aliases={"qwen3:30b": ["qwen3-30b"]})
    assert checks._models_without_remote_turn(path) == []
    r = checks._probe_topology(
        _pc_ctx(the_pc, Recorder(remote_turn.UNAUTHORIZED), config_path=path)
    )
    assert r.status == checks.OK


@pytest.mark.parametrize(
    "verdict", [remote_turn.UNREACHABLE, remote_turn.UNSUPPORTED, remote_turn.BAD_RESPONSE]
)
def test_server_without_the_endpoint_in_play_keeps_the_old_verdict(the_pc, verdict):
    ctx = _pc_ctx(the_pc, Recorder(verdict), config_path=_config_with(the_pc, "qwen3:30b"))
    assert checks._probe_topology(ctx) == _before_the_pr(ctx)


def test_server_side_is_not_asked_without_a_local_turn(the_pc):
    probe = Recorder(remote_turn.NEEDS_SECRET)
    r = checks._probe_topology(_pc_ctx(the_pc, probe, config_path=None))
    assert probe.calls == []
    assert r.status == checks.UNKNOWN


def test_server_side_is_not_asked_when_the_daemon_is_silent(the_pc):
    probe = Recorder(remote_turn.UNAUTHORIZED)
    ctx = _ctx(the_pc, probe, config_path=_config_with(the_pc, "qwen3:30b"))  # NO_LLAMASWAP_DAEMON
    r = checks._probe_topology(ctx)
    assert probe.calls == []
    assert r == _before_the_pr(ctx)


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
    ctx = checks.Context(home=tmp_path, config_path=path, llamaswap_daemon=_answering_daemon)
    r = checks._probe_topology(ctx)
    assert r.status == checks.WARN
    assert i18n.t("doctor.probe.topology.server_unnamed_models", models="qwen3:30b") in r.detail

    monkeypatch.setattr(config, "API_KEY", "")
    r = checks._probe_topology(ctx)
    assert r.status == checks.OK
    assert i18n.t("doctor.probe.topology.server_no_secret") in r.detail


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


# --- the key case: a PC alone, no secret, no Mac ----------------------------------------------


def test_a_pc_alone_without_a_secret_exits_as_on_main(tmp_path, monkeypatch, capsys):
    """Review of #503: a user with one machine and no secret gets no warning from this check.

    The whole `doctor` of `test_doctor` («everything in place», exit 0), with the daemon answering
    for llama-swap (so the server side IS asked) and its endpoint without a secret.
    """
    import test_doctor
    from conftest import desktop_mcp_remote_entry, make_home, write_claude_desktop

    from local_delegate import claude_plugin, doctor, install, install_state, recompute

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "clients.jsonl").write_text(
        '{"ts": "2026-07-31T17:15:52+00:00", "client": "claude-code", "version": "2.1.220",'
        ' "protocol": "2025-11-25", "caps": ["elicitation", "roots"]}\n',
        encoding="utf-8",
    )
    recompute.write_aggregates(logs, {"version": 1, "check": {"verdict": "pass"}})
    test_doctor._stub_environment(monkeypatch, log_dir=logs)
    home = make_home(tmp_path)
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(logs))
    version = checks._installed_version() or "0.0.0"
    install_state.save(home, install_state.new_state(claude_plugin.SETTINGS, version))
    write_claude_desktop(home, {install.SERVER_NAME: desktop_mcp_remote_entry()})
    today = Path(__file__).parent / "fixtures" / "residency" / "today.yaml"
    monkeypatch.setattr(config, "BASE_URL", LOOPBACK_BASE)
    monkeypatch.setattr(
        llamaswap_api,
        "daemon_status",
        lambda host, port, headers: (
            llamaswap_api.Status(
                llamaswap_api.STATE_OK, config_path=str(today), turn_active=True, turn_detail="x"
            ),
            "",
        ),
    )
    asked: list[tuple[str, bool]] = []

    def no_secret(url: str, *, with_credential: bool = True) -> str:
        asked.append((url, with_credential))
        return remote_turn.NEEDS_SECRET

    monkeypatch.setattr(remote_turn, "probe", no_secret)
    args = argparse.Namespace(config=str(today), online=False, home=str(home))
    exit_code = doctor.run_doctor(args)
    out = capsys.readouterr().out
    # Guard: the server side was really asked, so the verdict below says something.
    assert [with_credential for _url, with_credential in asked] == [False]
    topology = [
        line for line in out.splitlines() if i18n.t("doctor.check.backend.topology") in line
    ]
    assert topology and topology[0].startswith("  [ OK ]"), topology
    assert i18n.t("doctor.probe.topology.server_no_secret") in out
    assert exit_code == 0
