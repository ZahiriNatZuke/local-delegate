"""Tests de F4: loader por rango en web/metrics.py (_log_files, _load, /api/inflight,
/api/backend, /api/events) — rotación mensual, cache por archivo, y los endpoints nuevos."""

from __future__ import annotations

import json
import os
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


def test_api_inflight_reflects_server_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    entry_id = server._inflight_start(tool="t", model="m", source="path", chars_in=5)
    try:
        client = TestClient(metrics.app)
        r = client.get("/api/inflight")
        assert r.status_code == 200
        data = r.json()
        assert len(data["inflight"]) == 1
        assert data["inflight"][0]["tool"] == "t"
    finally:
        server._inflight_end(entry_id)


def test_api_inflight_sees_other_process_and_drops_dead_pid(tmp_path, monkeypatch):
    """/api/inflight lee el archivo compartido: ve entradas de OTROS pids vivos y descarta
    las de pids muertos, sin que este proceso haya llamado a _inflight_start para ellas."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    other_pid = os.getppid()  # un pid real y vivo, distinto del nuestro
    path = server._inflight_file()
    data = {
        f"{other_pid}:1": {
            "tool": "local_classify",
            "model": "m",
            "source": "inline",
            "chars_in": 1,
            "started_at": time.time(),
            "pid": other_pid,
        },
        "999999:1": {
            "tool": "local_extract",
            "model": "m",
            "source": "inline",
            "chars_in": 1,
            "started_at": time.time(),
            "pid": 999999,
        },
    }
    server._atomic_write_json(path, data)

    client = TestClient(metrics.app)
    tools = {e["tool"] for e in client.get("/api/inflight").json()["inflight"]}
    assert tools == {"local_classify"}


@respx.mock
def test_api_backend_available(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/running").mock(
        return_value=httpx.Response(200, json={"running": [{"model": "m1", "state": "ready"}]})
    )
    # /api/backend ahora incluye el status #901 fresco (mismo poll de 2s que /running)
    respx.get("http://test-backend/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "m1", "status": {"value": "loaded"}}]})
    )
    client = TestClient(metrics.app)
    data = client.get("/api/backend").json()
    assert data["available"] is True
    assert data["running"][0]["model"] == "m1"
    assert data["models"] == [{"id": "m1", "status": "loaded"}]


@respx.mock
def test_api_backend_unavailable(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/running").mock(side_effect=httpx.ConnectError("down"))
    respx.get("http://test-backend/v1/models").mock(side_effect=httpx.ConnectError("down"))
    client = TestClient(metrics.app)
    assert client.get("/api/backend").json() == {"available": False, "running": [], "models": []}


# --- /api/status: versión, modelos reales del backend, catálogo, tools ----------------
@respx.mock
def test_api_status_reports_version_models_catalog_tools(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "m-b", "status": {"value": "unloaded"}},
                    {"id": "m-a", "status": {"value": "loaded"}},
                ],
                "object": "list",
            },
        )
    )
    client = TestClient(metrics.app)
    data = client.get("/api/status").json()
    assert data["version"] == server._get_version()
    assert data["backend"]["available"] is True
    # #901: modelos ordenados con su status loaded/unloaded (objeto anidado de llama-swap)
    assert data["backend"]["models"] == [
        {"id": "m-a", "status": "loaded"},
        {"id": "m-b", "status": "unloaded"},
    ]
    roles = {c["role"] for c in data["catalog"]}
    assert roles == {"mechanical", "long", "code", "fast", "vision"}
    tool_names = {t["name"] for t in data["tools"]}
    assert "local_summarize" in tool_names and "local_status" in tool_names


@respx.mock
def test_models_with_status_tolerates_missing_and_string(monkeypatch):
    """#901: status como objeto {value}, como string plano, o ausente (None) — todos válidos."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"id": "m1"},  # sin status -> None
                    {"id": "m2", "status": "loaded"},  # string plano
                    {"id": "m3", "status": {"value": "unloaded"}},  # objeto anidado
                ]
            },
        )
    )
    up, models = server._models_with_status()
    assert up is True
    assert models == [
        {"id": "m1", "status": None},
        {"id": "m2", "status": "loaded"},
        {"id": "m3", "status": "unloaded"},
    ]


@respx.mock
def test_api_backend_stats_available(monkeypatch):
    """#898: proxy de /api/metrics/stats de llama-swap."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/api/metrics/stats").mock(
        return_value=httpx.Response(
            200, json={"total_requests": 3, "gen_histogram": {"p50": 40.0, "p95": 55.0}}
        )
    )
    client = TestClient(metrics.app)
    data = client.get("/api/backend/stats").json()
    assert data["available"] is True
    assert data["stats"]["total_requests"] == 3
    assert data["stats"]["gen_histogram"]["p50"] == 40.0


@respx.mock
def test_api_backend_stats_unavailable_on_404(monkeypatch):
    """Backend sin #898 (o no llama-swap): 404 -> degrada a {available: false}."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/api/metrics/stats").mock(return_value=httpx.Response(404))
    client = TestClient(metrics.app)
    assert client.get("/api/backend/stats").json() == {"available": False}


@respx.mock
def test_api_status_backend_down(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    respx.get("http://test-backend/v1/models").mock(side_effect=httpx.ConnectError("down"))
    client = TestClient(metrics.app)
    data = client.get("/api/status").json()
    assert data["backend"] == {"available": False, "models": []}
    assert data["catalog"]  # el catálogo local no depende del backend


# --- /api/system: RAM/VRAM + procesos (estructura, con sysinfo monkeypatcheado) --------
def test_api_system_shape(monkeypatch):
    from local_delegate.web import sysinfo

    monkeypatch.setattr(
        sysinfo,
        "ram_stats",
        lambda: {"used_gb": 10.0, "total_gb": 32.0, "free_gb": 22.0, "pct": 31.3},
    )
    monkeypatch.setattr(
        sysinfo,
        "vram_stats",
        lambda: {"used_mb": 2048, "total_mb": 16384, "pct": 12.5, "gpu_util_pct": 7},
    )
    monkeypatch.setattr(
        sysinfo,
        "interesting_processes",
        lambda: [
            {"pid": 1, "name": "llama-server.exe", "ram_mb": 4096, "vram_mb": 3000, "self": False}
        ],
    )
    client = TestClient(metrics.app)
    data = client.get("/api/system").json()
    assert data["ram"]["total_gb"] == 32.0
    assert data["vram"]["pct"] == 12.5
    assert data["processes"][0]["name"] == "llama-server.exe"


def test_api_system_never_crashes_without_platform_support(monkeypatch):
    from local_delegate.web import sysinfo

    monkeypatch.setattr(sysinfo, "ram_stats", lambda: None)
    monkeypatch.setattr(sysinfo, "vram_stats", lambda: None)
    monkeypatch.setattr(sysinfo, "interesting_processes", lambda: [])
    client = TestClient(metrics.app)
    r = client.get("/api/system")
    assert r.status_code == 200
    assert r.json() == {"ram": None, "vram": None, "processes": []}


def test_sysinfo_smoke():
    """ram/vram/procesos reales: dict con claves esperadas o None/[], nunca excepción."""
    from local_delegate.web import sysinfo

    ram = sysinfo.ram_stats()
    if ram is not None:
        assert set(ram) == {"used_gb", "total_gb", "free_gb", "pct"} and ram["total_gb"] > 0
    vram = sysinfo.vram_stats()
    if vram is not None:
        assert vram["total_mb"] > 0
    procs = sysinfo.interesting_processes()
    assert isinstance(procs, list)
    for p in procs:
        assert {"pid", "name", "ram_mb", "vram_mb", "self"} <= set(p)
