"""Aislamiento global de artefactos runtime durante la suite."""

from __future__ import annotations

import pytest

from local_delegate import config


@pytest.fixture(autouse=True)
def isolate_runtime_logs(tmp_path, monkeypatch):
    """Evita que mocks de tests contaminen los logs reales del usuario."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    monkeypatch.delenv("LD_HOOK_TELEMETRY_LOG", raising=False)
