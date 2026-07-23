"""Tests del autoarranque opcional de llama-swap."""

from __future__ import annotations

from local_delegate import autostart


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
