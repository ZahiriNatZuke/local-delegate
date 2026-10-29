"""Concurrency PC+Mac, lot 1 (REQ-005): a `read_timeout` names the loaded model that blocked it.

Measured on 2026-10-29 (step 1): the PC's call failed with «gemma no respondió en 180 s. Puede que
el backend aún lo esté cargando» while llama-swap was busy with the Mac's qwen. The text now comes
from the `/running` photo of the load probe (the same sample that decides `error_class`), then the
cached `/running`, then the operation's own sample; `error` and `error_class` do not change.
"""

from __future__ import annotations

import contextvars
import json
import time
from pathlib import Path

import backend_mock
import httpx2
import pytest

from local_delegate import concurrency, config, failures, i18n, server

CHAT = "http://test-backend/v1/chat/completions"
RUNNING = "http://test-backend/running"
ASKED = "gemma4-26b-a4b"
OTHER = "qwen36-35b-a3b"


@pytest.fixture(autouse=True)
def probe_at_once(reload_config, monkeypatch):
    reload_config()
    concurrency.reset_cache()
    monkeypatch.setattr(server, "_probe_delay", lambda: 0.0)
    # The PC: the topology resolves the requested name (here, to itself). The Mac's case, without
    # topology, has its own tests below.
    monkeypatch.setattr(server, "_resolved_model_name", lambda model: model)
    yield
    concurrency.reset_cache()


def _running(*pairs: tuple[str, str]) -> httpx2.Response:
    return httpx2.Response(200, json={"running": [{"model": m, "state": s} for m, s in pairs]})


def _timeout_after(seconds: float):
    def effect(_request):
        time.sleep(seconds)
        raise httpx2.ReadTimeout("timed out")

    return effect


def _seconds() -> object:
    return server._machine(config.HTTP_TIMEOUT)


@backend_mock.mock
def test_another_model_loaded_is_named_as_the_cause():
    backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready")))
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.3))

    result = server._post_chat(ASKED, {"model": ASKED})

    assert result.ok is False
    assert result.error == "read_timeout"
    assert result.read_timeout_cause == "model_swap"
    expected = i18n.t(
        "mcp.error.read_timeout_swap", model=ASKED, seconds=_seconds(), loaded=OTHER, hosts=""
    )
    assert result.text == server.ERROR_PREFIX + expected
    # The class is decided as before: not loaded, so a load (capacity), not the model's fault.
    assert result.error_class == failures.FailureClass.CAPACITY


@backend_mock.mock
def test_the_requested_model_loaded_says_busy():
    backend_mock.get(RUNNING).mock(return_value=_running((ASKED, "ready"), (OTHER, "ready")))
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.3))

    result = server._post_chat(ASKED, {"model": ASKED})

    assert result.read_timeout_cause == "busy"
    assert result.text == server.ERROR_PREFIX + i18n.t(
        "mcp.error.read_timeout_busy", model=ASKED, seconds=_seconds()
    )
    assert result.error_class == failures.FailureClass.READ_TIMEOUT


@backend_mock.mock
def test_without_a_sample_the_text_is_todays():
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(404, text="no"))
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.3))

    result = server._post_chat(ASKED, {"model": ASKED})

    assert result.read_timeout_cause is None
    assert result.text == server.ERROR_PREFIX + i18n.t(
        "mcp.error.read_timeout", model=ASKED, seconds=_seconds()
    )


@backend_mock.mock
def test_the_probes_photo_is_the_first_source():
    """The probe saw qwen loaded; by the time the timeout lands, gemma is ready. The text keeps
    the probe's view, so it agrees with `error_class` (capacity)."""
    answers = iter([_running((OTHER, "ready"))])
    running = backend_mock.get(RUNNING).mock(
        side_effect=lambda _r: next(answers, _running((ASKED, "ready")))
    )
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.3))

    result = server._post_chat(ASKED, {"model": ASKED})

    assert running.call_count == 1  # guard: the probe sampled, nobody asked again
    assert result.read_timeout_cause == "model_swap"
    assert result.error_class == failures.FailureClass.CAPACITY


@backend_mock.mock
def test_without_the_probes_photo_the_cached_running_is_used(monkeypatch):
    monkeypatch.setattr(server, "_probe_delay", lambda: 60.0)  # the probe never fires
    backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "starting")))
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.05))

    result = server._post_chat(ASKED, {"model": ASKED})

    assert result.read_timeout_cause == "model_swap"
    assert OTHER in result.text


@backend_mock.mock
def test_the_host_seen_in_llama_swaps_inflight_is_named():
    backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready")))
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.3))

    def in_an_operation() -> server.ChatResult:
        trace = concurrency.start(ASKED)
        trace.note_inflight([{"model": OTHER, "host": "mac"}, {"model": "else", "host": "pc"}])
        return server._post_chat(ASKED, {"model": ASKED})

    result = contextvars.copy_context().run(in_an_operation)

    hosts = i18n.t("mcp.error.read_timeout_from", host="mac")
    assert result.text == server.ERROR_PREFIX + i18n.t(
        "mcp.error.read_timeout_swap", model=ASKED, seconds=_seconds(), loaded=OTHER, hosts=hosts
    )


def _events(tmp_path: Path) -> list[dict]:
    lines: list[str] = []
    for file in sorted(tmp_path.glob("usage*.jsonl")):
        lines += file.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@backend_mock.mock
def test_the_cause_reaches_the_usage_event(tmp_path, monkeypatch):
    monkeypatch.setattr(concurrency, "BACKEND_SAMPLE_DELAY_S", 60.0)
    backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready")))
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.1))

    out = server.local_summarize(text="texto " * 200)

    assert "llama-swap" in out
    failed = [e for e in _events(tmp_path) if e.get("error") == "read_timeout"]
    assert failed, "no read_timeout event was written"
    assert failed[-1]["read_timeout_cause"] == "model_swap"
    assert failed[-1]["error_class"] == failures.FailureClass.CAPACITY.value


# --- Without topology (a remote backend: the Mac) -------------------------------------------


@backend_mock.mock
def test_without_topology_an_alias_is_not_blamed_on_a_swap(monkeypatch):
    """The Mac asks for an alias; llama-swap shows the real id `ready`. That is the same model,
    busy, not another one: no `model_swap`, the prudent text."""
    monkeypatch.setattr(server, "_resolved_model_name", lambda model: None)
    running = backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready")))
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.3))

    result = server._post_chat("long-alias", {"model": "long-alias"})

    assert running.call_count >= 1  # guard: there was a photo to read
    assert result.read_timeout_cause is None
    assert result.text == server.ERROR_PREFIX + i18n.t(
        "mcp.error.read_timeout", model="long-alias", seconds=_seconds()
    )


@backend_mock.mock
def test_without_topology_a_requested_model_seen_starting_is_still_a_swap(monkeypatch):
    """Decidable without topology: the requested name itself is in `/running`, not ready."""
    monkeypatch.setattr(server, "_resolved_model_name", lambda model: None)
    backend_mock.get(RUNNING).mock(return_value=_running((OTHER, "ready"), (ASKED, "starting")))
    backend_mock.post(CHAT).mock(side_effect=_timeout_after(0.3))

    result = server._post_chat(ASKED, {"model": ASKED})

    assert result.read_timeout_cause == "model_swap"
    assert OTHER in result.text
