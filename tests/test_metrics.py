"""Tests de F4: loader por rango en web/metrics.py (_log_files, _load, /api/inflight,
/api/backend, /api/events) — rotación mensual, cache por archivo, y los endpoints nuevos."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx
import respx
from fastapi.testclient import TestClient

from local_delegate import config, server
from local_delegate.web import metrics


def _write_jsonl(path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_log_files_lists_rotated_and_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    for ym in ("202601", "202602", "202603"):
        _write_jsonl(
            tmp_path / f"usage-{ym}.jsonl", [{"ts": f"{ym[:4]}-{ym[4:]}-01T00:00:00+00:00"}]
        )
    _write_jsonl(tmp_path / "usage.jsonl", [{"ts": "2020-01-01T00:00:00+00:00"}])
    metrics._FILE_CACHE.clear()

    files = metrics._log_files()
    yms = sorted(ym for _p, ym in files if ym is not None)
    assert yms == ["202601", "202602", "202603"]
    assert any(ym is None for _p, ym in files)  # el legado siempre es candidato


def test_load_range_opens_only_intersecting_months(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")  # no existe: no cuenta
    for ym, day in (("202601", "15"), ("202602", "15"), ("202603", "15")):
        _write_jsonl(
            tmp_path / f"usage-{ym}.jsonl",
            [
                {
                    "ts": f"{ym[:4]}-{ym[4:]}-{day}T00:00:00+00:00",
                    "tool": "x",
                    "model": "m",
                    "source": "inline",
                    "chars_in": 1,
                    "chars_out": 1,
                    "ok": True,
                }
            ],
        )
    metrics._FILE_CACHE.clear()

    range_from = datetime(2026, 2, 1, tzinfo=timezone.utc)
    range_to = datetime(2026, 2, 28, tzinfo=timezone.utc)
    rows, files_read = metrics._load(range_from, range_to)
    assert len(rows) == 1
    assert len(files_read) == 1
    assert "202602" in files_read[0]


def test_load_uses_cache_until_file_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    p = tmp_path / "usage-202603.jsonl"
    _write_jsonl(p, [{"ts": "2026-03-01T00:00:00+00:00"}])
    metrics._FILE_CACHE.clear()

    first = metrics._read_file_cached(p)
    assert len(first) == 1
    # sin tocar el archivo, debe devolver la misma lista cacheada (identidad de objeto)
    assert metrics._read_file_cached(p) is first

    time.sleep(0.05)
    _write_jsonl(p, [{"ts": "2026-03-01T00:00:00+00:00"}, {"ts": "2026-03-02T00:00:00+00:00"}])
    second = metrics._read_file_cached(p)
    assert len(second) == 2


def test_api_events_default_range_last_30_days(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    now = datetime.now(timezone.utc)
    ym = now.strftime("%Y%m")
    _write_jsonl(
        tmp_path / f"usage-{ym}.jsonl",
        [
            {
                "ts": now.isoformat(timespec="seconds"),
                "tool": "t",
                "model": "m",
                "source": "inline",
                "chars_in": 1,
                "chars_out": 1,
                "ok": True,
            }
        ],
    )
    metrics._FILE_CACHE.clear()
    client = TestClient(metrics.app)
    r = client.get("/api/events")
    data = r.json()
    assert data["meta"]["count"] == 1
    assert len(data["meta"]["files_read"]) == 1


def test_api_inflight_reflects_server_state(monkeypatch):
    monkeypatch.setattr(
        server,
        "_inflight",
        {
            1: {
                "tool": "t",
                "model": "m",
                "source": "path",
                "chars_in": 5,
                "started_at": time.time(),
            }
        },
    )
    client = TestClient(metrics.app)
    r = client.get("/api/inflight")
    assert r.status_code == 200
    data = r.json()
    assert len(data["inflight"]) == 1
    assert data["inflight"][0]["tool"] == "t"


@respx.mock
def test_api_backend_available(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/running").mock(
        return_value=httpx.Response(200, json={"running": [{"model": "m1", "state": "ready"}]})
    )
    client = TestClient(metrics.app)
    r = client.get("/api/backend")
    data = r.json()
    assert data["available"] is True
    assert data["running"][0]["model"] == "m1"


@respx.mock
def test_api_backend_unavailable(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/running").mock(side_effect=httpx.ConnectError("down"))
    client = TestClient(metrics.app)
    r = client.get("/api/backend")
    assert r.json() == {"available": False}
