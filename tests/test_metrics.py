"""Tests de F4: loader por rango en web/metrics.py (_log_files, _load, /api/inflight,
/api/backend, /api/events) — rotación mensual, cache por archivo, y los endpoints nuevos."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import backend_mock
import httpx2
import pytest
from fastapi.testclient import TestClient

from local_delegate import config, cost, failures, i18n, legacy_names, llamaswap_api, server
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

    range_from = datetime(2026, 2, 1, tzinfo=UTC)
    range_to = datetime(2026, 2, 28, tzinfo=UTC)
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
    now = datetime.now(UTC)
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


@backend_mock.mock
def test_api_backend_available(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/running").mock(
        return_value=httpx2.Response(200, json={"running": [{"model": "m1", "state": "ready"}]})
    )
    # /api/backend ahora incluye el status #901 fresco (mismo poll de 2s que /running)
    backend_mock.get("http://test-backend/v1/models").mock(
        return_value=httpx2.Response(
            200, json={"data": [{"id": "m1", "status": {"value": "loaded"}}]}
        )
    )
    client = TestClient(metrics.app)
    data = client.get("/api/backend").json()
    assert data["available"] is True
    assert data["running"][0]["model"] == "m1"
    assert data["models"] == [{"id": "m1", "status": "loaded"}]


@backend_mock.mock
def test_api_backend_unavailable(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/running").mock(side_effect=httpx2.ConnectError("down"))
    backend_mock.get("http://test-backend/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    client = TestClient(metrics.app)
    assert client.get("/api/backend").json() == {
        "available": False,
        "running": [],
        "running_ok": False,  # /running ni se pide con /models caído (REQ-013)
        "models": [],
        "models_stale": True,
        "cause": "transport",
        "label": "fallo de red",
        "detail": "fallo de red con test-backend (ConnectError)",
        "origin": "remote",  # host no-loopback => la inferencia correría fuera de esta máquina
        "host": "test-backend",
    }


# --- /api/status: versión, modelos reales del backend, catálogo, tools ----------------
@backend_mock.mock
def test_api_status_reports_version_models_catalog_tools(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(
        return_value=httpx2.Response(
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
    assert roles == {"mechanical", "long", "code", "vision"}
    tool_names = {t["name"] for t in data["tools"]}
    assert "local_summarize" in tool_names and "local_status" in tool_names


@backend_mock.mock
def test_models_with_status_tolerates_missing_and_string(monkeypatch):
    """#901: status como objeto {value}, como string plano, o ausente (None) — todos válidos."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(
        return_value=httpx2.Response(
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


@backend_mock.mock
def test_api_backend_stats_available(monkeypatch):
    """#898: proxy de /api/metrics/stats de llama-swap."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/api/metrics/stats").mock(
        return_value=httpx2.Response(
            200, json={"total_requests": 3, "gen_histogram": {"p50": 40.0, "p95": 55.0}}
        )
    )
    client = TestClient(metrics.app)
    data = client.get("/api/backend/stats").json()
    assert data["available"] is True
    assert data["stats"]["total_requests"] == 3
    assert data["stats"]["gen_histogram"]["p50"] == 40.0


@backend_mock.mock
def test_api_backend_stats_unavailable_on_404(monkeypatch):
    """Backend sin #898 (o no llama-swap): 404 -> degrada a {available: false}."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/api/metrics/stats").mock(
        return_value=httpx2.Response(404)
    )
    client = TestClient(metrics.app)
    assert client.get("/api/backend/stats").json() == {
        "available": False,
        "cause": "http_error",
        "label": "responde con error",
        "detail": "test-backend responde HTTP 404",
        "status_http": 404,
    }


@backend_mock.mock
def test_api_status_backend_down(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    client = TestClient(metrics.app)
    data = client.get("/api/status").json()
    assert data["backend"] == {
        "available": False,
        "models": [],
        "models_stale": True,
        "cause": "transport",
        "label": "fallo de red",
        "detail": "fallo de red con test-backend (ConnectError)",
        "origin": "remote",
        "host": "test-backend",
    }
    assert data["catalog"]  # el catálogo local no depende del backend


# --- T4 de `panel-cuentas-y-estados-honestos`: causa, lista guardada, `/running` y plazos --------
# Los campos nuevos se leen con `.get(...)`: el control (a) de cada test tiene que fallar en el
# assert, no por un `KeyError` contra el código de antes.
MODELS = "http://test-backend/v1/models"
RUNNING = "http://test-backend/running"
STATS = "http://test-backend/api/metrics/stats"


@backend_mock.mock
def test_api_backend_states_the_cause_of_a_401(monkeypatch):
    """REQ-012/REQ-014: un 401 es un backend vivo que rechaza la credencial, no uno caído."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(401))
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(401))

    j = TestClient(metrics.app).get("/api/backend").json()

    assert j.get("cause") == "credential"
    assert j["available"] is False
    assert "401" in (j.get("detail") or "")


@backend_mock.mock
def test_api_backend_keeps_the_list_and_marks_it_stale(monkeypatch):
    """REQ-021: tras un sondeo bueno, uno con `ConnectError` devuelve la misma lista, sin estado."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    path = backend_mock.get(MODELS).mock(
        return_value=httpx2.Response(200, json={"data": [{"id": "m1", "status": "loaded"}]})
    )
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(200, json={"running": []}))
    client = TestClient(metrics.app)
    good = client.get("/api/backend").json()
    path.mock(side_effect=httpx2.ConnectError("down"))

    j = client.get("/api/backend").json()

    assert j.get("models_stale") is True
    assert good.get("models_stale") is False
    assert [m["id"] for m in j["models"]] == ["m1"]
    assert j["models"][0]["status"] is None
    assert j.get("cause") == "transport"


@backend_mock.mock
def test_api_backend_does_not_request_running_if_models_fails(monkeypatch):
    """REQ-013: con el backend inalcanzable se gasta un plazo de conexión, no dos."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(MODELS).mock(side_effect=httpx2.ConnectError("down"))
    running_route = backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(200, json={"running": []})
    )

    j = TestClient(metrics.app).get("/api/backend").json()

    assert running_route.call_count == 0
    assert j["running"] == []


@backend_mock.mock
def test_api_backend_says_whether_running_answered(monkeypatch):
    """REQ-022: `running_ok` falso con un backend que no es llama-swap (`/running` → 404)."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(MODELS).mock(
        return_value=httpx2.Response(200, json={"data": [{"id": "m1", "status": "loaded"}]})
    )
    running_route = backend_mock.get(RUNNING).mock(return_value=httpx2.Response(404))
    client = TestClient(metrics.app)

    j = client.get("/api/backend").json()

    assert j.get("running_ok") is False
    assert j["available"] is True
    running_route.mock(
        return_value=httpx2.Response(200, json={"running": [{"model": "m1", "state": "ready"}]})
    )
    assert client.get("/api/backend").json().get("running_ok") is True


@backend_mock.mock
def test_api_status_states_the_cause_in_the_backend_block(monkeypatch):
    """REQ-012: `/api/status` usa el mismo sondeo que `/api/backend`."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(401))

    data = TestClient(metrics.app).get("/api/status").json()

    assert data["backend"].get("cause") == "credential"
    assert data["backend"].get("models_stale") is True
    assert "401" in (data["backend"].get("detail") or "")


@backend_mock.mock
def test_api_backend_stats_states_the_code_on_a_404(monkeypatch):
    """REQ-020: el panel solo culpa a la versión de llama-swap con un 404, así que lo necesita."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(STATS).mock(return_value=httpx2.Response(404))

    j = TestClient(metrics.app).get("/api/backend/stats").json()

    assert j.get("status_http") == 404
    assert j.get("cause") == "http_error"
    assert j["available"] is False


def test_api_backend_stats_states_the_cause_on_a_name_that_does_not_resolve(monkeypatch):
    """Red real: un nombre `.invalid` no resuelve nunca (RFC 6761). Sin código HTTP."""
    monkeypatch.setattr(config, "BASE_URL", "http://missing.invalid:9292/v1")

    j = TestClient(metrics.app).get("/api/backend/stats").json()

    assert j.get("cause") == "dns"
    assert j.get("status_http") is None
    assert "missing.invalid" in (j.get("detail") or "")


def _connect_timeout_of(t):
    """Lee el plazo de conexión sin reventar si llega un número (control (a) del plan)."""
    return t.connect if isinstance(t, httpx2.Timeout) else t


def test_api_backend_stats_uses_the_probe_timeout(monkeypatch):
    """REQ-013: `/api/metrics/stats` es un sondeo de estado y lleva su plazo, no 1 s."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    timeouts: list = []
    real = httpx2.Client

    def recorder(*args, **kwargs):
        timeouts.append(kwargs.get("timeout"))
        transport = httpx2.MockTransport(lambda req: httpx2.Response(404))
        return real(transport=transport)

    monkeypatch.setattr(httpx2, "Client", recorder)

    TestClient(metrics.app).get("/api/backend/stats")

    assert timeouts, "el endpoint no llegó a crear el cliente"
    connect_timeout = _connect_timeout_of(timeouts[0])
    assert connect_timeout == config.PROBE_CONNECT_TIMEOUT
    assert timeouts[0].read == config.PROBE_READ_TIMEOUT


def test_api_system_states_platform_origin_and_host(monkeypatch):
    """REQ-025: el panel necesita saber dónde corre el cómputo y en qué plataforma está."""
    import sys

    from local_delegate.web import sysinfo

    monkeypatch.setattr(sysinfo, "ram_stats", lambda: None)
    monkeypatch.setattr(sysinfo, "vram_stats", lambda: None)
    monkeypatch.setattr(sysinfo, "interesting_processes", list)
    monkeypatch.setattr(config, "BASE_URL", "http://100.64.0.2:9292/v1")

    j = TestClient(metrics.app).get("/api/system").json()

    assert j.get("platform") == sys.platform
    assert j.get("origin") == "remote"
    assert j.get("host") == "100.64.0.2:9292"
    assert j.get("panel_url") == f"http://100.64.0.2:{config.WEB_PORT}/"


def test_api_inflight_lets_the_local_wait_through(tmp_path, monkeypatch):
    """REQ-022: la fila «en cola local» depende de que `local_wait` llegue al panel."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    pid = os.getpid()
    server._atomic_write_json(
        server._inflight_file(),
        {
            f"{pid}:1": {
                "tool": "local_summarize",
                "model": "m",
                "source": "path",
                "chars_in": 1,
                "started_at": time.time(),
                "pid": pid,
                "local_wait": "slot",
            }
        },
    )

    entries = TestClient(metrics.app).get("/api/inflight").json()["inflight"]

    assert len(entries) == 1
    e = entries[0]
    assert e.get("local_wait") == "slot"


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
    monkeypatch.setattr(sysinfo, "interesting_processes", list)
    client = TestClient(metrics.app)
    r = client.get("/api/system")
    assert r.status_code == 200
    assert {k: r.json()[k] for k in ("ram", "vram", "processes")} == {
        "ram": None,
        "vram": None,
        "processes": [],
    }


def test_dashboard_identifies_shared_mcp_daemon():
    client = TestClient(metrics.app)
    html = client.get("/").text
    assert "DAEMON MCP" in html


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


# --- Actividad y origen del cómputo (local vs remoto) ---------------------------------
def test_last_event_ts_ignores_the_selected_range(tmp_path, monkeypatch):
    """El indicador de actividad mira TODO el histórico, no el rango del selector."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    _write_jsonl(
        tmp_path / "usage-202605.jsonl",
        [{"ts": "2026-05-01T10:00:00+00:00"}, {"ts": "2026-05-02T10:00:00+00:00"}],
    )
    _write_jsonl(tmp_path / "usage-202607.jsonl", [{"ts": "2026-07-20T18:30:00+00:00"}])
    metrics._FILE_CACHE.clear()
    assert metrics._last_event_ts() == "2026-07-20T18:30:00+00:00"


def test_last_event_ts_without_logs_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    metrics._FILE_CACHE.clear()
    assert metrics._last_event_ts() is None


def test_api_inflight_exposes_activity_signals(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    _write_jsonl(tmp_path / "usage-202607.jsonl", [{"ts": "2026-07-20T18:30:00+00:00"}])
    metrics._FILE_CACHE.clear()
    data = TestClient(metrics.app).get("/api/inflight").json()
    assert data["inflight"] == [] and data["count"] == 0
    assert data["last_event_ts"] == "2026-07-20T18:30:00+00:00"
    assert data["now"]  # hora del servidor: el cliente corrige el desfase de su propio reloj


def test_stats_separates_local_and_remote_compute(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    base = {"tool": "local_summarize", "model": "m", "chars_out": 10, "ok": True}
    _write_jsonl(
        tmp_path / "usage-202607.jsonl",
        [
            {
                **base,
                "ts": "2026-07-20T10:00:00+00:00",
                "source": "path",
                "chars_in": 4000,
                "backend": "local",
                "backend_host": "127.0.0.1:9292",
            },
            {
                **base,
                "ts": "2026-07-20T11:00:00+00:00",
                "source": "path",
                "chars_in": 8000,
                "backend": "remote",
                "backend_host": "pc.ts.net:9292",
            },
            {**base, "ts": "2026-07-20T12:00:00+00:00", "source": "inline", "chars_in": 100},
        ],
    )
    metrics._FILE_CACHE.clear()
    data = (
        TestClient(metrics.app)
        .get("/api/stats?from=2026-07-01T00:00:00Z&to=2026-07-31T00:00:00Z")
        .json()
    )
    by_backend = {b["backend"]: b for b in data["by_backend"]}
    assert by_backend["local"]["tokens_saved"] == 1659  # 4000 × 100 // 241
    assert by_backend["remote"]["tokens_saved"] == 3319  # 8000 × 100 // 241
    assert by_backend["remote"]["hosts"] == ["pc.ts.net:9292"]
    # los eventos previos al campo no se cuentan como locales: quedan como "unknown"
    assert by_backend["unknown"]["calls"] == 1


def test_dashboard_computes_ranges_in_local_time():
    """El selector 'Hoy' usa la medianoche LOCAL, no la UTC (que corre el día)."""
    html = TestClient(metrics.app).get("/").text
    assert "localMidnight" in html and "localDayKey" in html
    assert "Date.UTC(" not in html  # ya no queda ningún rango calculado en UTC


def test_empty_states_use_the_dashboard_typography():
    """`.empty` vive entre texto monoespaciado; sin font-family propia heredaba la sans.

    Se notaba sobre todo en «sin datos (requiere llama-swap ≥ v236)», rodeado de nombres de
    modelo, badges y chips en mono — y el propio panel llegaba a enseñar dos estados vacíos con
    tipografías distintas, porque el de tools usa `.tchip`, que sí la declara.
    """
    html = TestClient(metrics.app).get("/").text
    empty_rule = re.search(r"\.empty\{[^}]*\}", html)
    assert empty_rule, "no se encontró la regla .empty"
    assert "font-family:var(--mono)" in empty_rule.group(0)


# --- El panel no depende de la red -----------------------------------------------------
def test_chart_js_is_served_from_the_package_not_a_cdn():
    """El dashboard de una herramienta local-first tiene que funcionar sin salida a internet."""
    client = TestClient(metrics.app)
    html = client.get("/").text
    assert "cdn.jsdelivr.net" not in html
    assert '<script src="/vendor/chart.umd.min.js">' in html

    r = client.get("/vendor/chart.umd.min.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/javascript")
    assert len(r.text) > 100_000  # la distribución real, no un stub

    # La versión se lee del manifiesto, NO se escribe aquí: `vendor.json` es su fuente de verdad
    # y clavarla en un test la convierte en una segunda que hay que acordarse de actualizar.
    # Este assert existía con «Chart.js v4.4.1» a mano y fue una de las dos cosas que hubo que
    # tocar al subir a 4.5.1.
    manifest = json.loads(
        (Path(metrics.__file__).parents[1] / "resources" / "vendor" / "vendor.json").read_text(
            encoding="utf-8"
        )
    )
    version = next(f["version"] for f in manifest["files"] if f["file"] == "chart.umd.min.js")
    assert f"Chart.js v{version}" in r.text


def test_web_fonts_can_be_disabled_for_zero_third_party_requests(monkeypatch):
    # La hoja completa con esquema y ruta, no el host suelto: buscar solo "fonts.googleapis.com"
    # daría por bueno un href a "https://fonts.googleapis.com.otrositio.tld/…", que es un tercero
    # distinto. Los asserts de ausencia de más abajo sí van por subcadena, y ahí es lo correcto:
    # cualquier aparición de "googleapis" con WEB_FONTS=False es un fallo.
    stylesheet = 'href="https://fonts.googleapis.com/css2?'
    html = TestClient(metrics.app).get("/").text
    assert stylesheet in html  # por defecto sí, es solo tipografía

    monkeypatch.setattr(config, "WEB_FONTS", False)
    html = metrics.render_index()
    assert stylesheet not in html
    assert "googleapis" not in html and "gstatic" not in html
    assert "/vendor/chart.umd.min.js" in html  # los gráficos siguen, son locales


def test_dashboard_survives_without_chart_js():
    """Si Chart.js no cargara, el resto del panel (KPIs, tabla, actividad) sigue vivo."""
    html = TestClient(metrics.app).get("/").text
    assert "const HAS_CHART = typeof Chart !== 'undefined'" in html
    assert "if(HAS_CHART) Chart.register" in html


# --- Contabilidad del troceado: ahorro frente a coste -------------------------
# El defecto que cierran estos tests: N llamadas al backend se registraban como UN evento y el
# dashboard sumaba solo `chars_in ÷ 4`, así que una delegación eficiente y otra que quemó la GPU
# 16 veces daban exactamente el mismo número. El dato real (`chunks`, `tokens_in`) ya estaba en el
# log; nadie lo leía.


def _ev(**kw) -> dict:
    base = {
        "ts": "2026-07-15T10:00:00+00:00",
        "tool": "local_summarize",
        "model": "m",
        "source": "path",
        "chars_in": 4000,
        "chars_out": 400,
        "latency_ms": 100,
        "ok": True,
    }
    base.update(kw)
    return base


def _resolved(row: dict) -> dict:
    """La fila como la entrega `_load` en producción: fundida y con su densidad resuelta
    (coste-api-y-cuota, REQ-006). Sin relleno ni `caller_model`, toma el respaldo declarado (Opus
    5.5, familia nueva). `_ev` no trae `path`: clase `other`, que en `read_format` cae en el
    respaldo (3), la mayor `c` sin numerar de la familia, 2,41; lo devuelto es prosa sin numerar,
    2,23; la salida, prosa sin numerar, 2,23."""
    return cost.merge_row(row)


def test_accounting_one_call_without_chunking():
    a = metrics._accounting(_resolved(_ev(tokens_in=1100, tokens_out=90)))
    assert a == {
        "backend_calls": 1,
        "tokens_in": 1100,
        "tokens_out": 90,
        "saved": 1659,  # 4000 chars × 100 // 241: el contenido que no entró al contexto
        "returned": 179,  # 400 chars × 100 // 223: lo que la tool devolvió al contexto
        "net": 1480,
        "estimated": False,
        "fallback": False,
        "cause": None,
        # Contrato con `coste-api-y-cuota`: desglose en caracteres y campos del evento.
        "chars_saved_text": 4000,
        "bytes_saved_image": 0,
        "chars_saved_output": 0,
        "chars_returned": 400,
        "failed": False,
        "tool": "local_summarize",
        "model": "m",
        "source": "path",
        "unit": "chars",
    }


def test_accounting_chunked_separates_saving_from_cost():
    """El caso que da nombre al change, con los números del evento REAL del log."""
    a = metrics._accounting(
        _resolved(_ev(chars_in=84178, chunks=4, tokens_in=26131, tokens_out=786))
    )
    assert a["backend_calls"] == 4  # cuatro llamadas al backend, no una
    assert a["tokens_in"] == 26131  # coste real, con el prompt de sistema repetido 4 veces
    assert a["saved"] == 34928  # ahorro: el documento UNA vez (84178 × 100 // 241), no cuatro
    # El troceo lo paga la GPU, no el contexto: el coste local supera una pasada del documento en
    # tokens LOCALES (84178 ÷ 4 = 21044). Antes se comparaba con `saved`, que ya no está en la
    # misma unidad (tokens de Claude).
    assert a["tokens_in"] > 21044


def test_accounting_without_tokens_estimates_and_says_so():
    a = metrics._accounting(_ev())
    assert a["tokens_in"] == 1000 and a["tokens_out"] == 100
    assert a["estimated"] is True


def test_accounting_image_uses_the_real_token_not_the_bytes():
    """chars_in son BYTES del PNG: dividirlos entre 4 inventaba un ahorro ×48."""
    a = metrics._accounting(
        _resolved(
            _ev(
                tool="local_describe_image",
                input_unit="bytes",
                chars_in=504780,
                tokens_in=2758,
                tokens_out=37,
            )
        )
    )
    # coste-api-y-cuota, REQ-038: la imagen sale entera del neto (0 tokens de Claude); el token
    # real del backend se queda en el coste local, y los bytes en su campo del contrato.
    assert a["saved"] == 0
    assert a["tokens_in"] == 2758
    assert a["bytes_saved_image"] == 504780


def test_accounting_historical_image_without_mark_is_recognized_by_the_tool():
    """Los eventos anteriores al campo `input_unit` no se pueden reescribir: hay 4 en el log."""
    a = metrics._accounting(
        _resolved(_ev(tool="local_describe_image", chars_in=504780, tokens_in=2758, tokens_out=37))
    )
    assert a["saved"] == 0  # REQ-038: la imagen no suma tokens de Claude
    assert (a["unit"], a["bytes_saved_image"]) == ("bytes", 504780)  # se reconoció por la tool


def test_accounting_image_without_real_token_does_not_make_up_a_number():
    a = metrics._accounting(_ev(tool="local_describe_image", input_unit="bytes", chars_in=504780))
    assert a["saved"] == 0  # ni estimable ni real: 0 antes que un número falso
    assert a["tokens_in"] == 0
    assert a["estimated"] is True


def test_accounting_inline_does_not_count_as_saving():
    a = metrics._accounting(_ev(source="inline", tokens_in=1100, tokens_out=90))
    assert a["saved"] == 0
    assert a["tokens_in"] == 1100  # pero el coste sí se cuenta: la GPU lo gastó igual


def test_accounting_failure_halfway_counts_the_spent_calls():
    a = metrics._accounting(_ev(chunks=3, ok=False, tokens_in=900, tokens_out=10))
    assert a["backend_calls"] == 3


# --- Panel honesto (REQ-001 a REQ-008): fallos fuera, neto dentro, desglose en caracteres --------
#
# Los campos nuevos se leen con `.get(...)`: contra el código de antes el test tiene que fallar por
# el assert que nombra el plan, no por un `KeyError`.

# El evento del escenario «el neto resta lo que volvió al contexto».
_NET_SUBTRACTS = {
    "source": "path",
    "chars_in": 4000,
    "chars_out": 400,
    "ok": True,
    "tokens_in": 1100,
    "tokens_out": 90,
}
# El del escenario «la salida a fichero no descuenta el recibo».
_OUTPUT_TO_FILE = {
    "source": "inline",
    "output_to_file": True,
    "chars_out": 4000,
    "tokens_out": 950,
    "ok": True,
    "tokens_in": 10,
}
# El del escenario «una imagen por `path`».
_IMAGE_BY_PATH = {
    "tool": "local_describe_image",
    "source": "path",
    "chars_in": 250000,
    "chars_out": 800,
    "ok": True,
    "tokens_in": 1200,
    "tokens_out": 200,
}
# El del escenario «un fallo no infla las cuentas»: sin tokens, con el texto del error de vuelta.
_FAILURE_WITHOUT_TOKENS = {"source": "path", "chars_in": 4000, "chars_out": 144, "ok": False}


def test_accounting_a_failure_neither_saves_nor_generates():
    a = metrics._accounting(dict(_FAILURE_WITHOUT_TOKENS))
    assert a["saved"] == 0
    assert (a.get("returned"), a.get("net")) == (0, 0)
    assert (a.get("chars_saved_text"), a.get("chars_returned")) == (0, 0)
    assert (a["tokens_in"], a["tokens_out"]) == (0, 0), "el texto del error no es generación"
    assert a["estimated"] is False
    assert a.get("failed") is True
    assert a["backend_calls"] == 1


def test_accounting_a_failure_is_not_an_estimate():
    a = metrics._accounting(_ev(ok=False))
    assert a["estimated"] is False
    assert a.get("failed") is True


def test_accounting_chunked_failure_keeps_the_real_cost():
    a = metrics._accounting(
        {
            "chunks": 3,
            "ok": False,
            "tokens_in": 900,
            "tokens_out": 10,
            "source": "path",
            "chars_in": 4000,
        }
    )
    assert a["saved"] == 0
    assert a["tokens_in"] == 900, "la GPU gastó esos tokens aunque la operación fallara"
    assert a["tokens_out"] == 10
    assert a["backend_calls"] == 3
    assert a.get("net") == 0


def test_accounting_net_subtracts_what_was_returned():
    a = metrics._accounting(_resolved(dict(_NET_SUBTRACTS)))
    assert a.get("returned") == 179  # 400 × 100 // 223
    assert a["saved"] == 1659  # 4000 × 100 // 241
    assert a.get("net") == 1480


def test_accounting_output_to_file_does_not_deduct_the_receipt():
    a = metrics._accounting(_resolved(dict(_OUTPUT_TO_FILE)))
    assert a.get("net") == 1793  # 4000 chars de salida × 100 // 223 (prosa sin numerar)
    assert a["saved"] == 1793
    assert a.get("returned") == 0, "el recibo de dos líneas no se registra: se toma 0"


def test_accounting_net_can_be_negative():
    a = metrics._accounting(
        _resolved(_ev(chars_in=400, chars_out=800, tokens_in=120, tokens_out=200))
    )
    assert a.get("net") == -193
    assert (a["saved"], a.get("returned")) == (165, 358)  # 400 × 100 // 241 y 800 × 100 // 223


def test_accounting_breaks_down_into_characters():
    """Los cuatro campos del contrato con `coste-api-y-cuota`, más los del evento que copia."""
    a = metrics._accounting(dict(_NET_SUBTRACTS))
    assert a.get("chars_saved_text") == 4000
    assert a.get("chars_returned") == 400
    assert (a.get("bytes_saved_image"), a.get("chars_saved_output")) == (0, 0)
    assert (a.get("unit"), a.get("source"), a.get("failed")) == ("chars", "path", False)

    s = metrics._accounting(dict(_OUTPUT_TO_FILE))
    assert s.get("chars_saved_output") == 4000
    assert (s.get("chars_returned"), s.get("chars_saved_text")) == (0, 0)

    i = metrics._accounting(_resolved(dict(_IMAGE_BY_PATH)))
    assert i.get("bytes_saved_image") == 250000, "la imagen va en BYTES, en su propio campo"
    assert i.get("chars_saved_text") == 0
    assert i.get("chars_returned") == 800
    # coste-api-y-cuota, REQ-038: los campos del contrato no cambian, pero la imagen sale entera
    # del neto (ni lo leído ni lo devuelto).
    assert (i["saved"], i.get("returned"), i.get("net")) == (0, 0, 0)
    assert (i.get("unit"), i.get("tool")) == ("bytes", "local_describe_image")

    f = metrics._accounting(dict(_FAILURE_WITHOUT_TOKENS, tool="local_summarize", model="m"))
    fields = ("chars_saved_text", "bytes_saved_image", "chars_saved_output", "chars_returned")
    assert [f.get(c) for c in fields] == [0, 0, 0, 0]
    assert (f.get("tool"), f.get("model"), f.get("failed")) == ("local_summarize", "m", True)


def test_claude_tokens_is_the_only_conversion(monkeypatch):
    """REQ-008: lo ahorrado y lo devuelto pasan SOLO por `claude_tokens`; el coste local, no."""
    monkeypatch.setattr(server, "claude_tokens", lambda amount, *, kind, event: 7)
    a = metrics._accounting(dict(_NET_SUBTRACTS))
    assert a["saved"] == 7
    assert a.get("returned") == 7
    assert a.get("net") == 0
    assert a["tokens_in"] == 1100, "el coste del modelo local no pasa por la conversión"


def test_stats_tells_delegations_from_backend_calls(tmp_path, monkeypatch):
    """Escenario de aceptación: dos eventos, uno troceado -> 2 delegaciones, 5 llamadas."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    _write_jsonl(
        tmp_path / "usage-202607.jsonl",
        [
            _ev(tokens_in=1100, tokens_out=90),
            _ev(chars_in=84178, chunks=4, tokens_in=26131, tokens_out=786),
        ],
    )
    metrics._FILE_CACHE.clear()

    r = TestClient(metrics.app).get(
        "/api/stats?from=2026-07-01T00:00:00%2B00:00&to=2026-08-01T00:00:00%2B00:00"
    )
    j = r.json()
    assert j["total"]["calls"] == 2
    assert j["backend_calls"] == 5
    assert j["tokens_local_input"] == 27231
    assert j["tokens_context_saved"] == 36587  # 4000 × 100 // 241 + 84178 × 100 // 241
    assert j["estimated_events"] == 0
    tool = j["by_tool"][0]
    assert tool["backend_calls"] == 5 and tool["tokens_in"] == 27231


def test_stats_marks_the_events_that_had_to_be_estimated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    _write_jsonl(tmp_path / "usage-202607.jsonl", [_ev(), _ev(tokens_in=10, tokens_out=1)])
    metrics._FILE_CACHE.clear()

    j = (
        TestClient(metrics.app)
        .get("/api/stats?from=2026-07-01T00:00:00%2B00:00&to=2026-08-01T00:00:00%2B00:00")
        .json()
    )
    assert j["estimated_events"] == 1


def _stats_of(tmp_path, monkeypatch, rows: list[dict]) -> dict:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    _write_jsonl(tmp_path / "usage-202607.jsonl", rows)
    metrics._FILE_CACHE.clear()
    return (
        TestClient(metrics.app)
        .get("/api/stats?from=2026-07-01T00:00:00%2B00:00&to=2026-08-01T00:00:00%2B00:00")
        .json()
    )


def test_stats_the_synthetic_mac_log_inflates_nothing(tmp_path, monkeypatch):
    """Escenario de la Mac, sintético: 4 delegaciones buenas con `usage` y 4 `connect_error`."""
    good_ones = [_ev(tokens_in=1100, tokens_out=90) for _ in range(4)]
    failures = [
        _ev(ok=False, error="connect_error", error_class="backend_ausente", chars_out=144)
        for _ in range(4)
    ]
    j = _stats_of(tmp_path, monkeypatch, good_ones + failures)
    assert j["estimated_events"] == 0
    assert j["tokens_context_saved"] == 4 * 1659, "solo suman las 4 buenas"  # 4000 × 100 // 241
    assert j["tokens_generated_local"] == 4 * 90
    assert j.get("tokens_returned") == 4 * 179  # 400 × 100 // 223
    assert j.get("tokens_context_net") == j["tokens_context_saved"] - j.get("tokens_returned", 0)


def test_stats_ok_null_does_not_count_as_error():
    """REQ-006: el predicado de fallo es `ok` exactamente `false`, igual que en la contabilidad."""
    j = metrics._aggregate([_resolved(_ev(ok=None)), _resolved(_ev())])
    assert j["total"]["errors"] == 0
    assert j["by_tool"][0]["errors"] == 0


def test_stats_exposes_the_breakdown_in_characters(tmp_path, monkeypatch):
    j = _stats_of(
        tmp_path,
        monkeypatch,
        [
            _ev(**_NET_SUBTRACTS),
            _ev(**_OUTPUT_TO_FILE),
            _ev(**_IMAGE_BY_PATH),
            _ev(**_FAILURE_WITHOUT_TOKENS),
        ],
    )
    assert j.get("chars_saved_text") == 4000
    assert j.get("bytes_saved_image") == 250000
    assert j.get("chars_saved_output") == 4000
    assert j.get("chars_returned") == 400 + 800
    # Neto de texto 1659 − 179, salida a fichero 4000 × 100 // 223 = 1793, imagen 0 (REQ-038).
    assert j.get("tokens_returned") == 179 + 0
    assert j["tokens_context_saved"] == 1659 + 1793 + 0
    assert j.get("tokens_context_net") == 1480 + 1793 + 0
    assert j["total"]["errors"] == 1


def test_stats_who_delegated_carries_the_net():
    j = metrics._aggregate(
        [
            _resolved(_ev(client="claude-code", **_NET_SUBTRACTS)),
            _resolved(_ev(client="claude-code", **_FAILURE_WITHOUT_TOKENS)),
        ]
    )
    row = j["by_client"][0]
    assert row.get("tokens_net") == 1480, "el fallo no suma y el devuelto se resta"  # 1659 − 179
    assert j["by_tool"][0].get("tokens_net") == 1480
    assert j["by_backend"][0].get("tokens_net") == 1480


def test_the_js_uses_a_single_failure_predicate():
    """REQ-006: `!e.ok` cuenta `ok: null` como fallo; la regla dice `ok` exactamente `false`."""
    html = metrics.HTML
    assert "!e.ok" not in html
    assert "e.ok?'ok':'err'" not in html
    assert "e.ok===false" in html


def test_dashboard_requests_the_kpis_from_the_server():
    """Una sola implementación de las cuentas: el panel no las recalcula en el cliente."""
    html = TestClient(metrics.app).get("/").text
    assert "fetch('/api/stats?'" in html


def _extract_js_function(source: str, header: str) -> str:
    """Recorta una función del <script> inline balanceando llaves (no hay strings con '{' dentro)."""
    i = source.index(header)
    depth, j = 0, i
    while True:
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[i : j + 1]
        j += 1


def _without_ok(event: dict) -> dict:
    """`_ev` pone `ok: True` por defecto: el caso «sin clave `ok`» se construye quitándola."""
    return {k: v for k, v in event.items() if k != "ok"}


# Pares (campo en Python, campo en JS) del contrato con `coste-api-y-cuota`, más los de siempre.
# Empieza por `returned`: es el primero que no existía, así que el control lo nombra.
_PARITY_FIELDS = (
    ("returned", "returned"),
    ("net", "net"),
    ("saved", "saved"),
    ("chars_saved_text", "charsSavedText"),
    ("bytes_saved_image", "bytesSavedImage"),
    ("chars_saved_output", "charsSavedOutput"),
    ("chars_returned", "charsReturned"),
    ("failed", "failed"),
    ("tool", "tool"),
    ("model", "model"),
    ("source", "source"),
    ("unit", "unit"),
    ("backend_calls", "calls"),
    ("tokens_in", "tokensIn"),
    ("tokens_out", "tokensOut"),
    ("estimated", "estimated"),
    ("fallback", "fallback"),
    ("cause", "cause"),
)


def test_acct_parity_between_python_and_the_dashboard_js(tmp_path):
    """Las series por día se agrupan en el navegador (dependen de tu zona), así que la regla de
    contabilidad vive por duplicado. Este test ata las dos copias: si divergen, el gráfico
    contradiría al KPI que tiene encima — el mismo defecto que este change vino a cerrar."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")

    raw_rows = [
        # --- Los 12 casos de REQ-001, en este orden ---------------------------------------
        _ev(tokens_in=1100, tokens_out=90),  # neto positivo
        _ev(ok=False, error="connect_error", chars_out=144),  # fallo sin tokens
        _ev(chunks=3, ok=False, tokens_in=900, tokens_out=10),  # fallo troceado con tokens
        _ev(ok=None),  # `ok: null`: bueno
        _without_ok(_ev(source="path", chars_in=4000)),  # sin clave `ok`: bueno
        _ev(ok=0),  # `ok: 0`: bueno
        _ev(chars_in=400, chars_out=800, tokens_in=120, tokens_out=200),  # neto negativo
        _ev(chars_in=8000, tokens_in=2100, tokens_out=950, output_to_file=True),  # a fichero, path
        _ev(
            tool="local_boilerplate",
            source="inline",
            chars_in=40,
            chars_out=4000,
            tokens_in=10,
            tokens_out=950,
            output_to_file=True,
        ),  # a fichero, inline
        _ev(
            tool="local_describe_image",
            input_unit="bytes",
            chars_in=250000,
            chars_out=800,
            tokens_in=1200,
            tokens_out=200,
        ),  # imagen por `path` con tokens
        _ev(tool="local_describe_image", input_unit="bytes", chars_in=504780),  # imagen sin tokens
        _ev(chars_in=3),  # texto por `path` con `chars_in: 3`: bruto 0, neto negativo
        # --- Los de antes, que siguen cubriendo otras ramas -------------------------------
        _ev(chars_in=84178, chunks=4, tokens_in=26131, tokens_out=786),
        _ev(),  # sin tokens: estimado
        _ev(chars_in=4002, tokens_out=7),  # impar: caza floor contra round
        _ev(tool="local_describe_image", chars_in=504780, tokens_in=2758, tokens_out=37),
        _ev(source="inline", tokens_in=1100, tokens_out=90),
        # F3, tarea 29: un evento con salto y uno con causa de configuración (REQ-013, REQ-019).
        # Sin ellos la paridad pasaría sin ejercitar las ramas nuevas en ninguna de las dos copias.
        _ev(
            model="gemma3-4b",
            model_requested="gemma4-26b-a4b",
            fallback_reason="http_500",
            fallback_class="modelo",
            chunks=2,
            tokens_in=1200,
            tokens_out=90,
        ),
        _ev(ok=False, error="config_max_tokens", error_class="configuracion", tokens_in=50),
        # T15 (REQ-016): la afinidad lleva `model_requested` y NO es un respaldo en ninguna copia.
        _ev(
            model="gemma4-26b-a4b",
            model_requested="gemma3-4b",
            routing="affinity",
            affinity_foreign_flight=0,
            tokens_in=300,
            tokens_out=40,
        ),
        # Los dos campos a la vez: una operación por trozos que saltó y luego falló. Sin este caso
        # un mutante que invertía el orden de la causa en el JS sobrevivía a la paridad.
        _ev(
            ok=False,
            model_requested="gemma4-26b-a4b",
            fallback_reason="http_500",
            fallback_class="modelo",
            error="http_503",
            error_class="unclassified",
            chunks=3,
        ),
        # --- coste-api-y-cuota, REQ-037: casos que cambian entre `÷ 4` y la densidad, en orden --
        # Prosa por `path` de Opus 5.5: familia nueva, columna `read_format`, origen `measured`.
        _ev(path="C:/docs/guia.md", caller_model="claude-opus-5-5", tokens_in=1100, tokens_out=90),
        # La misma prosa inline, escrita a fichero: columna `unnumbered` (la de lo que la tool
        # escribe). Inline no reclama ahorro de entrada, así que es la salida la que cambia.
        _ev(
            source="inline",
            caller_model="claude-opus-5-5",
            chars_out=4000,
            tokens_in=10,
            tokens_out=950,
            output_to_file=True,
        ),
        # `.md` por `path` de Haiku 4.5: familia anterior, su `read_format` sin medir → respaldo (2).
        _ev(
            path="C:/docs/notas.md", caller_model="claude-haiku-4-5", tokens_in=1100, tokens_out=90
        ),
        # `.bin` por `path`: clase `other`, sin celda → respaldo (3), `conservative`.
        _ev(path="C:/datos/volcado.bin", caller_model="claude-opus-5-5", tokens_in=900),
        # Imagen con `chars_returned > 0`: todo 0 (REQ-038).
        _ev(
            tool="local_describe_image",
            input_unit="bytes",
            path="C:/img/captura.png",
            caller_model="claude-haiku-4-5",
            chars_in=250000,
            chars_out=800,
            tokens_in=1200,
            tokens_out=200,
        ),
        # Modelo fuera de la tabla: familia nueva supuesta.
        _ev(path="C:/src/app.py", caller_model="claude-unknown-9", tokens_in=1100),
    ]
    # Como en producción: las filas pasan antes por la fusión de Python (REQ-006, REQ-037). Sin
    # relleno en `tmp_path`, las que no traen `caller_model` toman el respaldo declarado.
    cases = cost.merge(raw_rows, log_dir=tmp_path)
    from_js = _acct_in_js(node, tmp_path, cases)

    from_py = [metrics._accounting(c) for c in cases]
    for case, py, js in zip(cases, from_py, from_js, strict=True):
        for py_field, js_field in _PARITY_FIELDS:
            # `.get`: un campo que falta en el JS falla por el assert, no por `KeyError`.
            assert js.get(js_field) == py[py_field], (py_field, case)
    # Guarda de «esto llegó a comprobar algo» (REQ-001): sin un caso de cada, la paridad de las
    # ramas nuevas saldría verde con las dos copias rotas.
    assert any(py["net"] < 0 for py in from_py)
    assert any(py["failed"] and py["tokens_in"] > 0 for py in from_py)
    assert any("ok" not in c for c in cases)
    assert any(py["bytes_saved_image"] > 0 for py in from_py)
    assert any(py["chars_saved_output"] > 0 for py in from_py)
    assert any(py["fallback"] for py in from_py)
    assert any(
        c.get("routing") == "affinity" and not py["fallback"]
        for c, py in zip(cases, from_py, strict=True)
    ), "falta el caso de afinidad"
    # Filas viejas y nuevas (REQ-006): las dos copias traducen la clase con la misma tabla.
    assert any(c.get("error_class") == "configuracion" for c in cases), "falta la fila vieja"
    assert any(c.get("error_class") == "unclassified" for c in cases), "falta la fila nueva"
    assert any(py["cause"] == "configuration" for py in from_py)
    # Guarda de REQ-037: un evento de cada origen de celda, de cada familia, y una imagen con
    # devuelto que da 0 en las dos copias.
    origins = {c["density"]["text"][1] for c in cases if c["density"]["text"]}
    assert origins >= {"measured", "unnumbered", "conservative"}
    assert {c["family"] for c in cases} >= {"new", "previous"}
    assert any(
        c["density"]["text"] is None and py["chars_returned"] > 0 and py["returned"] == 0
        for c, py in zip(cases, from_py, strict=True)
    )
    assert any("assumed_family" in c["marks"] for c in cases)


def _acct_in_js(node: str, tmp_path: Path, cases: list[dict]) -> list[dict]:
    """`acct` del panel, con su `claudeTokens` de verdad, corrido con node sobre `cases`."""
    tokens_claude_js = _extract_js_function(metrics.HTML, "function claudeTokens(")
    acct_js = _extract_js_function(metrics.HTML, "function acct(e){")
    input_file = tmp_path / "cases.json"
    input_file.write_text(json.dumps(cases), encoding="utf-8")
    program = tmp_path / "parity.mjs"
    program.write_text(
        "import {readFileSync} from 'node:fs';\n"
        "const CPT = 4;\n"
        "const tok = c => Math.floor(c/CPT);\n"
        f"const LEGACY_VALUES = {json.dumps(legacy_names.PANEL_VALUE_ALIASES)};\n"
        f"{_extract_js_function(metrics.HTML, 'function legacyValue(')}\n"
        f"{tokens_claude_js}\n"
        f"{acct_js}\n"
        f"const testCases = JSON.parse(readFileSync({json.dumps(str(input_file))}, 'utf-8'));\n"
        "console.log(JSON.stringify(testCases.map(acct)));\n",
        encoding="utf-8",
    )
    output = subprocess.run(
        [node, str(program)], capture_output=True, text=True, timeout=30, check=True
    )
    return json.loads(output.stdout)


def test_the_js_follows_python(tmp_path):
    """Escenario de la spec «el JS sigue a Python» (REQ-037): con el `c100` de una fila resuelta
    cambiado a mano, las dos copias siguen el valor nuevo. Si el JS resolviera la densidad por su
    cuenta, seguiría dividiendo por 200."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")
    (row,) = cost.merge(
        [_ev(path="C:/docs/guia.md", caller_model="claude-opus-5-5", chars_out=0)],
        log_dir=tmp_path,
    )
    assert row["density"]["text"] == [200, "measured"]  # guarda: el punto de partida
    row["density"]["text"] = [250, "measured"]
    chars = row["chars_in"]
    (js,) = _acct_in_js(node, tmp_path, [row])
    py = metrics._accounting(row)
    assert py["saved"] == chars * 100 // 250  # 4000 × 100 // 250 = 1600
    assert js["saved"] == chars * 100 // 250


def test_local_status_and_the_dashboard_count_the_same(tmp_path, monkeypatch):
    """Tercera superficie: `local_status` tenía su propia copia de la cuenta (chars_in ÷ 4 a
    mano, imágenes incluidas), así que habría seguido dando un número distinto al del panel
    sobre el MISMO log."""
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    log = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "USAGE_LOG", log)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    rows = [
        _ev(chars_in=84178, chunks=4, tokens_in=26131, tokens_out=786),
        _ev(
            tool="local_describe_image",
            input_unit="bytes",
            chars_in=504780,
            tokens_in=2758,
            tokens_out=37,
        ),
    ]
    _write_jsonl(log, rows)
    metrics._FILE_CACHE.clear()

    # El panel agrega las filas que le da `_load`, ya fundidas (coste-api-y-cuota, REQ-006).
    aggregate = metrics._aggregate(cost.merge(rows, log_dir=tmp_path))
    assert aggregate["tokens_context_saved"] == 34928  # guarda: 84178 × 100 // 241 + imagen 0
    text = server.local_status()
    assert f"(bruto ~{aggregate['tokens_context_saved']})" in text
    assert f"({aggregate['backend_calls']} llamadas al backend)" in text


def test_local_status_counts_the_net_like_the_dashboard(tmp_path, monkeypatch):
    """REQ-005: `local_status` dice el neto y el bruto con la misma función que el panel."""
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    log = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "USAGE_LOG", log)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    rows = [
        _ev(**_NET_SUBTRACTS),
        _ev(**_FAILURE_WITHOUT_TOKENS),
        _ev(chars_in=400, chars_out=800, tokens_in=120, tokens_out=200),
    ]
    _write_jsonl(log, rows)
    metrics._FILE_CACHE.clear()

    aggregate = metrics._aggregate(cost.merge(rows, log_dir=tmp_path))
    assert aggregate.get("tokens_context_net") == 1480 - 193  # guarda: ninguna cifra a 0
    # Si la clave falta (código de antes), el texto esperado tampoco está: falla el assert y no un
    # `TypeError` al formatear un `None`.
    n = aggregate.get("tokens_context_net", "(falta tokens_context_net)")
    expected = f"~{n} tokens netos"
    text = server.local_status()
    assert expected in text
    assert f"(bruto ~{aggregate['tokens_context_saved']})" in text


def test_local_status_merges_like_the_dashboard(tmp_path, monkeypatch):
    """coste-api-y-cuota, REQ-006: `local_status` funde el relleno como el panel. Una línea sin
    `caller_model` cuyo relleno dice Haiku: sin fusión no trae `density` y da 0."""
    from local_delegate import attribution

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "COST_FALLBACK", "")
    monkeypatch.setattr(server, "_utcnow", lambda: datetime(2026, 10, 6, 12, 0, tzinfo=UTC))
    row = _ev(ts="2026-10-06T10:00:00+00:00", path="C:/docs/notas.md", tool_use_id="toolu_h")
    _write_jsonl(tmp_path / "usage-202610.jsonl", [row])
    attribution.write_backfill(
        tmp_path, "202610", {"toolu_h": {"caller_model": "claude-haiku-4-5", "match": "exact"}}
    )
    metrics._FILE_CACHE.clear()

    j = (
        TestClient(metrics.app)
        .get("/api/stats?from=2026-10-01T00:00:00%2B00:00&to=2026-11-01T00:00:00%2B00:00")
        .json()
    )
    # Haiku, `.md` por `path`: prosa sin numerar de la familia anterior (respaldo (2)), 3,01;
    # devuelto en prosa sin numerar, 3,01. 4000 × 100 // 301 − 400 × 100 // 301 = 1328 − 132.
    assert j["tokens_context_net"] == 1196
    text = server.local_status()
    m = re.search(r"~(-?\d+) tokens netos", text)
    status_net = int(m.group(1)) if m else None
    assert status_net == j["tokens_context_net"]


def test_api_events_rows_come_resolved(tmp_path, monkeypatch):
    """REQ-006: `/api/events` entrega las filas fundidas y resueltas; el JS no resuelve nada."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    _write_jsonl(
        tmp_path / "usage-202607.jsonl",
        [_ev(), _ev(tool="local_describe_image", input_unit="bytes", chars_in=900)],
    )
    metrics._FILE_CACHE.clear()
    events = (
        TestClient(metrics.app)
        .get("/api/events?from=2026-07-01T00:00:00%2B00:00&to=2026-08-01T00:00:00%2B00:00")
        .json()["events"]
    )
    assert len(events) == 2  # guarda: hay filas que mirar
    assert all("density" in e for e in events)
    assert all(e.get("caller_model") and e.get("family") for e in events)


# --- F3, tarea 29: el salto y su causa, en la cuenta y en el panel -----------------------------


def test_accounting_marks_the_fallback_and_its_cause():
    a = metrics._accounting(
        _ev(
            model="gemma3-4b",
            model_requested="gemma4-26b-a4b",
            fallback_reason="http_500",
            fallback_class="modelo",
            chunks=2,
            tokens_in=1200,
            tokens_out=90,
        )
    )
    assert a["fallback"] is True
    assert a["cause"] == "model"
    assert a["backend_calls"] == 2, "la llamada del respaldo también gastó backend"


def test_accounting_affinity_is_not_fallback():
    """T15 (REQ-016): la afinidad lleva `model_requested`, pero el panel no la cuenta como salto."""
    a = metrics._accounting(
        _ev(model="gemma4-26b-a4b", model_requested="gemma3-4b", routing="affinity")
    )
    assert a["fallback"] is False


def test_accounting_configuration_cause_on_a_failure():
    # Fila del formato viejo (0.34.0): la causa sale ya en el formato nuevo (REQ-006).
    a = metrics._accounting(_ev(ok=False, error="config_max_tokens", error_class="configuracion"))
    assert a["fallback"] is False
    assert a["cause"] == "configuration"


def test_accounting_on_a_failure_after_falling_back_the_cause_is_the_failures():
    a = metrics._accounting(
        _ev(
            ok=False,
            model_requested="gemma4-26b-a4b",
            fallback_class="modelo",
            error_class="unclassified",
        )
    )
    assert a["cause"] == "unclassified", "manda cómo acabó la operación, no por qué saltó"
    assert a["fallback"] is True


def test_accounting_history_without_new_fields_reads_the_same():
    a = metrics._accounting(
        _resolved(_ev(chars_in=84178, chunks=4, tokens_in=26131, tokens_out=786))
    )
    assert a["fallback"] is False and a["cause"] is None
    # 84178 × 100 // 241 = 34928
    assert (a["backend_calls"], a["tokens_in"], a["saved"]) == (4, 26131, 34928)


def test_stats_counts_fallbacks_and_causes_and_credits_the_one_that_answered(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    _write_jsonl(
        tmp_path / "usage-202607.jsonl",
        [
            _ev(model="gemma3-4b", tokens_in=100, tokens_out=10),
            _ev(
                model="gemma3-4b",
                model_requested="gemma4-26b-a4b",
                fallback_reason="http_500",
                fallback_class="modelo",
                chunks=2,
                tokens_in=500,
                tokens_out=20,
            ),
            _ev(
                model="gemma4-26b-a4b",
                ok=False,
                error="config_max_tokens",
                error_class="configuration",
                tokens_in=50,
                tokens_out=0,
            ),
        ],
    )
    metrics._FILE_CACHE.clear()

    j = (
        TestClient(metrics.app)
        .get("/api/stats?from=2026-07-01T00:00:00%2B00:00&to=2026-08-01T00:00:00%2B00:00")
        .json()
    )
    assert j["fallback_events"] == 1
    # El salto es una fila vieja (`modelo`) y el fallo una nueva: cuentan juntos (REQ-006).
    assert j["causes"] == {"model": 1, "configuration": 1}
    by_model = {m["model"]: m for m in j["by_model"]}
    assert by_model["gemma3-4b"]["tokens_in"] == 600, "los tokens del salto van al que respondió"
    assert by_model["gemma3-4b"]["backend_calls"] == 3
    assert by_model["gemma3-4b"]["fallback_calls"] == 1


def test_a_log_with_old_and_new_rows_reads_as_if_all_were_new(tmp_path, monkeypatch):
    """Escenario de la spec (REQ-005/006, ola A3): en un mismo `usage-*.jsonl` conviven filas de la
    0.34.0 (`bloqueo_id`, `fallo_conexion: rechazada`, `error_class: timeout_lectura`) y filas
    nuevas. `/api/events` las entrega todas con las claves y valores nuevos, y `/api/stats` suma
    las causas viejas y nuevas en el mismo cubo, con la misma etiqueta."""
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    old_ones = [
        _ev(ts="2026-07-15T10:00:00+00:00", bloqueo_id="b-viejo", secciones=4),
        _ev(
            ts="2026-07-15T10:01:00+00:00",
            ok=False,
            error="connect_error",
            error_class="endpoint",
            fallo_conexion="rechazada",
        ),
        _ev(
            ts="2026-07-15T10:02:00+00:00", ok=False, error="timeout", error_class="timeout_lectura"
        ),
    ]
    new_ones = [
        _ev(ts="2026-07-15T11:00:00+00:00", block_id="b-new", sections=4),
        _ev(
            ts="2026-07-15T11:01:00+00:00",
            ok=False,
            error="connect_error",
            error_class="endpoint",
            connection_failure="refused",
        ),
        _ev(ts="2026-07-15T11:02:00+00:00", ok=False, error="timeout", error_class="read_timeout"),
    ]
    _write_jsonl(tmp_path / "usage-202607.jsonl", old_ones + new_ones)
    metrics._FILE_CACHE.clear()
    client = TestClient(metrics.app)
    range_qs = "from=2026-07-01T00:00:00%2B00:00&to=2026-08-01T00:00:00%2B00:00"

    events = client.get(f"/api/events?{range_qs}").json()["events"]
    assert len(events) == 6
    assert sorted(e["block_id"] for e in events if "block_id" in e) == ["b-new", "b-viejo"]
    assert [e["connection_failure"] for e in events if "connection_failure" in e] == [
        "refused",
        "refused",
    ]
    assert [e.get("sections") for e in events if e.get("sections")] == [4, 4]
    old_in_output = {"bloqueo_id", "secciones", "fallo_conexion"} & {k for e in events for k in e}
    assert not old_in_output, old_in_output

    j = client.get(f"/api/stats?{range_qs}").json()
    assert j["causes"] == {"endpoint": 2, "read_timeout": 2}
    labels = {failures.label(e["connection_failure"]) for e in events if "connection_failure" in e}
    assert labels == {"nadie escucha"}


def test_the_dashboard_marks_the_operations_with_fallback():
    html = metrics.HTML
    assert "e.model_requested" in html and "fbchip" in html
    assert "e.error_class" in html
    # REQ-019 (backend-extra-params): the row also marks reasoning and per-role params, and opens
    # the detail dialog.
    assert "e.reasoning_chars" in html and "reasonchip" in html
    assert "e.backend_params" in html and "paramschip" in html
    assert "e.backend_params_rejected" in html
    assert 'id="eventDlg"' in html and "eventRows(" in html


# --- Quién delegó: el desglose por cliente -----------------------------------------------------
#
# Nace de la medición de adopción: el KPI de ahorro es acumulativo y no distingue un mes de smoke
# tests de un mes de trabajo real. En la medición del 3-ago las 20 líneas de una prueba sólo se
# separaron cruzando a mano contra los transcripts, que es algo que el panel no puede hacer.


def _usage_row(**extra) -> dict:
    base = {
        "ts": "2026-08-18T10:00:00+00:00",
        "tool": "local_summarize",
        "model": "gemma3-4b",
        "source": "path",
        "chars_in": 1000,
        "chars_out": 50,
        "latency_ms": 10,
        "ok": True,
        "tokens_in": 300,
        "tokens_out": 12,
        "raw_len": 1000,
    }
    base.update(extra)
    return base


def test_stats_splits_the_delegations_by_client():
    aggregate = metrics._aggregate(
        [
            _usage_row(client="claude-code"),
            _usage_row(client="claude-code"),
            _usage_row(client="codex-mcp-client"),
        ]
    )

    by_client = {c["client"]: c["calls"] for c in aggregate["by_client"]}
    assert by_client == {"claude-code": 2, "codex-mcp-client": 1}


def test_stats_neither_splits_nor_drops_the_lines_without_client():
    """Las de antes de que el campo existiera, y las que no vienen de una sesión MCP.

    Repartirlas entre los clientes conocidos inventaría de quién eran, y descartarlas haría que
    los totales de la tarjeta no cuadraran con el KPI de arriba. Casilla propia.
    """
    aggregate = metrics._aggregate([_usage_row(client="claude-code"), _usage_row()])

    by_client = {c["client"]: c["calls"] for c in aggregate["by_client"]}
    assert by_client == {"claude-code": 1, "unknown": 1}
    assert sum(c["calls"] for c in aggregate["by_client"]) == aggregate["total"]["calls"]


# --- T13 de daemon-reparte-el-backend: llama-swap para el CLI de residencia (REQ-039) ----------
LS_RUNNING = "http://test-backend/running"
LS_EVENTS = "http://test-backend/api/events"


def _sse(*messages: tuple[str, object]) -> bytes:
    return "".join(
        f"event: message\ndata: {json.dumps({'type': t, 'data': json.dumps(d)})}\n\n"
        for t, d in messages
    ).encode()


def _llamaswap_with_secrets() -> None:
    """`/running` con el `cmd` (y su `--api-key`) y una foto `inflight` con cabeceras."""
    backend_mock.get(LS_RUNNING).mock(
        return_value=httpx2.Response(
            200,
            json={
                "running": [
                    {
                        "model": "m",
                        "state": "ready",
                        "ttl": 120,
                        "cmd": "llama-server -m MODELOS/m.gguf --api-key fake-key-1",
                        "proxy": "http://localhost:5800",
                    }
                ]
            },
        )
    )
    backend_mock.get(LS_EVENTS).mock(
        return_value=httpx2.Response(
            200,
            content=_sse(
                ("logData", {"source": "proxy", "data": "[INFO] arranque\n"}),
                (
                    "inflight",
                    {
                        "operation": "snapshot",
                        "requests": [
                            {
                                "model": "m",
                                "req_headers": {"Authorization": "Bearer fake-key-2"},
                            }
                        ],
                    },
                ),
            ),
        )
    )


@backend_mock.mock
def test_llamaswap_status_never_returns_cmd_headers_or_keys(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    monkeypatch.setenv("LLAMASWAP_CONFIG", "D:/configs/llama-swap.yaml")
    _llamaswap_with_secrets()

    r = TestClient(metrics.app).get("/api/llamaswap/status")

    assert r.status_code == 200
    assert "fake-key-1" not in r.text
    assert "fake-key-2" not in r.text
    data = r.json()
    assert data["llamaswap"] == "ok"
    assert data["models"] == [{"id": "m", "state": "ready", "ttl": 120}]
    assert data["in_flight"] == {"m": 1}
    assert data["own_delegations"] == 0
    assert data["config_path"] == "D:/configs/llama-swap.yaml"
    # Lo que el daemon dice de su turno (para `doctor`): `test-backend` no es loopback, no hay.
    assert data["turn_active"] is False
    assert data["turn_reason"] == "backend remoto"


@backend_mock.mock
def test_llamaswap_status_counts_own_delegations(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    _llamaswap_with_secrets()
    entry = server._inflight_start(tool="t", model="m", source="path", chars_in=5)
    try:
        data = TestClient(metrics.app).get("/api/llamaswap/status").json()
    finally:
        server._inflight_end(entry)
    assert data["own_delegations"] == 1


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/llamaswap/status"),
        ("POST", "/api/llamaswap/watch"),
        ("GET", "/api/llamaswap/watch/abc"),
    ],
)
def test_llamaswap_endpoints_require_the_web_token(monkeypatch, method, path):
    """La app sola, sin la puerta del daemon (`auth.protect`): la dependencia de cada ruta basta.

    `BASE_URL` va a un puerto sin nadie: si la dependencia faltara, el endpoint no saldría a la red
    de verdad (ni al llama-swap real del 9292).
    """
    monkeypatch.setattr(config, "WEB_TOKEN", "fake-key-3")
    monkeypatch.setattr(config, "BASE_URL", "http://127.0.0.1:9/v1")
    client = TestClient(metrics.app)

    r = client.request(method, path)

    assert r.status_code == 401
    with_token = client.request(method, path, headers={"Authorization": "Bearer fake-key-3"})
    assert with_token.status_code != 401


@backend_mock.mock
def test_llamaswap_watch_with_llamaswap_down_says_down(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(LS_EVENTS).mock(side_effect=httpx2.ConnectError("rechazada"))
    client = TestClient(metrics.app)

    opened = client.post("/api/llamaswap/watch")
    assert opened.status_code == 200
    result = client.get(f"/api/llamaswap/watch/{opened.json()['id']}").json()

    assert result["outcome"] == "down"
    assert client.get("/api/llamaswap/watch/no-existe").status_code == 404


@backend_mock.mock
def test_llamaswap_watch_that_cannot_open_is_502(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(LS_EVENTS).mock(return_value=httpx2.Response(401))

    r = TestClient(metrics.app).post("/api/llamaswap/watch")

    assert r.status_code == 502
    assert r.json() == {"error": i18n.t(metrics.WATCH_REJECTED)}


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (llamaswap_api.QueryError, metrics.WATCH_REJECTED),
        (llamaswap_api.TooManyWatches, metrics.WATCH_LIMIT),
        (httpx2.ConnectError, metrics.WATCH_UNREACHABLE),
    ],
    ids=["query_error", "too_many_watches", "http_error"],
)
def test_llamaswap_watch_502_does_not_expose_the_exception(monkeypatch, caplog, failure, message):
    """CodeQL py/stack-trace-exposure: el texto de la excepción va al log del daemon, no al
    navegador. El texto lleva un marcador único para que la comprobación no dependa de qué dice
    cada excepción de verdad."""
    marker = "internal-detail-7f3a9c"

    def fails(_backend):
        raise failure(marker)

    monkeypatch.setattr(llamaswap_api.watches, "open", fails)

    with caplog.at_level("WARNING", logger=metrics.logger.name):
        r = TestClient(metrics.app).post("/api/llamaswap/watch")

    assert r.status_code == 502
    assert marker not in r.text
    assert r.json() == {"error": i18n.t(message)}
    assert marker in caplog.text, "guarda: el detalle sí llegó al log"


# --- Las pruebas fuera de las métricas (test-windows-out-of-metrics, T4) -------------------------


class _Mix:
    """Un log con 10 filas reales y 3 de prueba (ventana, cliente `mcp` y banco), y opcionalmente
    filas de Codex fuera de toda ventana. La de ventana es de `local_describe_image`, para que
    `imagenes` cambie con el interruptor.
    """

    def __init__(self, tmp_path, monkeypatch, *, codex: int = 0) -> None:
        from datetime import timedelta

        from test_dashboard_cost import IMAGE, _aggregates, _line, _point

        from local_delegate import attribution, test_windows

        self.logs = tmp_path / "logs"
        self.logs.mkdir()
        monkeypatch.setattr(config, "LOG_DIR", self.logs)
        monkeypatch.setattr(config, "USAGE_LOG", self.logs / "usage.jsonl")
        monkeypatch.setattr(config, "COST_FALLBACK", "")
        monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
        self.now = datetime.now(UTC).replace(microsecond=0)
        monkeypatch.setattr(metrics, "_now", lambda: self.now)
        a = self.now
        rows = [_line(a - timedelta(minutes=10 + i), n=i) for i in range(10)]
        in_window = a - timedelta(minutes=5)
        rows.append(
            {**IMAGE, "ts": in_window.isoformat(timespec="seconds"), "tool_use_id": "toolu_win"}
        )
        rows.append(_line(a - timedelta(minutes=6), n=90, client="mcp"))
        rows.append(_line(a - timedelta(minutes=7), n=91))  # banco por el relleno
        rows += [
            _line(a - timedelta(minutes=30 + i), n=80 + i, client="codex-mcp-client")
            for i in range(codex)
        ]
        rows.sort(key=lambda f: f["ts"])
        self.log = self.logs / f"usage-{a:%Y%m}.jsonl"
        _write_jsonl(self.log, rows)
        attribution.write_backfill(self.logs, f"{a:%Y%m}", {"toolu_0091": {"bench": True}})
        test_windows.add(self.logs, in_window - timedelta(seconds=2), in_window, "prueba")
        # Cuota calibrada, para que `_bloque_cuota` llegue a llamar a `_load` (REQ-014).
        _aggregates(
            self.logs,
            [_point(a - timedelta(days=d), c) for d, c in ((20, 150.0), (10, 160.0), (2, 170.0))],
        )
        metrics._FILE_CACHE.clear()
        since = (a - timedelta(days=1)).isoformat().replace("+", "%2B")
        until = (a + timedelta(minutes=1)).isoformat().replace("+", "%2B")
        self.qs = f"from={since}&to={until}"
        self.client = TestClient(metrics.app)

    def get(self, path: str, include: bool = False) -> dict:
        extra = "&include_tests=1" if include else ""
        return self.client.get(f"{path}?{self.qs}{extra}").json()


def test_a_marked_test_does_not_count_in_the_dashboard(tmp_path, monkeypatch):
    import hashlib

    m = _Mix(tmp_path, monkeypatch)
    before = hashlib.sha256(m.log.read_bytes()).hexdigest()
    s, e = m.get("/api/stats"), m.get("/api/events")
    assert s["total"]["calls"] == 10
    assert e["meta"]["count"] == 10
    assert s["excluded_tests"] == e["meta"]["excluded_tests"] == 3
    assert s["images"]["n"] == 0
    assert hashlib.sha256(m.log.read_bytes()).hexdigest() == before


def test_the_switch_shows_them_and_the_cost_does_not_change(tmp_path, monkeypatch):
    """Control: mutantes «`cost_block` con las filas filtradas» y «`_quota_block` filtra» →
    fallan las igualdades de `cost` y de `quota`."""
    m = _Mix(tmp_path, monkeypatch)
    excluded, included = m.get("/api/stats"), m.get("/api/stats", include=True)
    e = m.get("/api/events", include=True)
    assert included["total"]["calls"] == 13
    assert e["meta"]["count"] == 13
    assert included["excluded_tests"] == e["meta"]["excluded_tests"] == 0
    assert included["tests_in_range"] == 3
    assert included["quota"]["five_hour"]["status"] == "calibrated", (
        "guarda: la cuota llega a _load"
    )
    assert included["cost"] == excluded["cost"]
    assert included["quota"] == excluded["quota"]
    # La de ventana es una imagen, que va fuera de la base del coste: quedan la `mcp` y la de banco.
    assert included["cost"]["bar"]["excluded_by_reason"] == {"tests": 2}
    assert (excluded["images"]["n"], included["images"]["n"]) == (0, 1)


def test_codex_still_counts_in_the_usage(tmp_path, monkeypatch):
    m = _Mix(tmp_path, monkeypatch, codex=2)
    s = m.get("/api/stats")
    assert s["total"]["calls"] == 12
    by_client = {c["client"]: c["calls"] for c in s["by_client"]}
    assert by_client.get("codex-mcp-client") == 2
    assert s["cost"]["bar"]["excluded_by_reason"]["not_claude"] == 2


@pytest.mark.parametrize("include", [False, True])
def test_events_and_stats_count_the_same_set(tmp_path, monkeypatch, include):
    """Paridad de conjunto (REQ-011). Control: mutante «solo `stats` filtra» → falla `meta.count`;
    mutante «`test_reason` ignora el `banco` de la fila» → bajan los `excluded_tests`."""
    m = _Mix(tmp_path, monkeypatch, codex=2)
    s, e = m.get("/api/stats", include), m.get("/api/events", include)
    assert m.get("/api/stats")["excluded_tests"] == 3, "guarda: el log tiene pruebas que quitar"
    assert e["meta"]["count"] == s["total"]["calls"]
    assert e["meta"]["excluded_tests"] == s["excluded_tests"]
    assert e["meta"]["tests_in_range"] == s["tests_in_range"] == 3


def test_open_test_windows_names_the_open_ones(tmp_path, monkeypatch):
    from local_delegate import test_windows

    m = _Mix(tmp_path, monkeypatch)
    assert m.get("/api/stats")["open_test_windows"] == []
    w = test_windows.start(m.logs, "en vivo")
    open_ones = m.get("/api/stats")["open_test_windows"]
    assert open_ones == [{"id": w.id, "start": test_windows.format_instant(w.start)}]


def test_api_hooks_sets_the_windows_aside(tmp_path, monkeypatch):
    from local_delegate import test_windows

    hooks_log = tmp_path / "telemetry.jsonl"
    _write_jsonl(
        hooks_log,
        [
            {"ts": "2026-10-08T01:00:00Z", "event": "PreToolUse", "category": "read"},
            {"ts": "2026-10-08T01:21:00Z", "event": "PreToolUse", "category": "read"},
            {"ts": "2026-10-08T01:21:30Z", "event": "PreToolUse", "category": "read"},
        ],
    )
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", hooks_log)
    test_windows.add(tmp_path, "2026-10-08T01:20:05.255Z", "2026-10-08T01:22:31.544Z")
    metrics._FILE_CACHE.clear()
    qs = "from=2026-10-08T00:00:00%2B00:00&to=2026-10-09T00:00:00%2B00:00"
    client = TestClient(metrics.app)
    excluded = client.get(f"/api/hooks?{qs}").json()
    included = client.get(f"/api/hooks?{qs}&include_tests=1").json()
    assert (excluded["total"], excluded["excluded_tests"]) == (1, 2)
    assert (included["total"], included["excluded_tests"]) == (3, 0)


def test_live_data_is_not_filtered(tmp_path, monkeypatch):
    """REQ-017: la última fila, aunque esté en una ventana, es la que enseña el indicador."""
    from local_delegate import test_windows

    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    _write_jsonl(
        tmp_path / "usage-202610.jsonl",
        [
            {"ts": "2026-10-08T01:00:00+00:00", "tool": "local_extract"},
            {"ts": "2026-10-08T01:21:00+00:00", "tool": "local_summarize"},
        ],
    )
    test_windows.add(tmp_path, "2026-10-08T01:20:05.255Z", "2026-10-08T01:22:31.544Z")
    metrics._FILE_CACHE.clear()
    assert metrics._last_event()["tool"] == "local_summarize"
    last = TestClient(metrics.app).get("/api/inflight").json()["last_event"]
    assert last["tool"] == "local_summarize"


@pytest.mark.parametrize("value", ["0", "yes", "", "TRUE ", "1", "true"])
def test_include_tests_only_turns_on_with_1_or_true(value):
    assert metrics._include_tests(value) is (value.strip().lower() in {"1", "true"})


# --- `?lang=` en los `/api/*` y el catálogo del panel (B4, plan D6) -----------------------------
#
# La suite corre con el proceso en español (`LOCAL_DELEGATE_LANG=es`, REQ-043): lo que llega en
# inglés solo puede venir del `?lang=` del visitante.


def _empty_logs(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    metrics._FILE_CACHE.clear()
    return TestClient(metrics.app)


def test_api_stats_writes_its_reasons_in_the_visitor_language(tmp_path, monkeypatch):
    from local_delegate import quota, valuation

    client = _empty_logs(tmp_path, monkeypatch)
    by_lang = {
        lang: client.get("/api/stats", params={"lang": lang}).json() for lang in ("es", "en")
    }
    for lang, data in by_lang.items():
        assert data["cost"]["reason"] == i18n.t_lang(lang, valuation.NO_DELEGATIONS)
        assert data["quota"]["five_hour"]["reason"] == i18n.t_lang(lang, quota.NO_DATA)
    assert by_lang["es"]["cost"]["reason"] != by_lang["en"]["cost"]["reason"]  # guarda


@pytest.mark.parametrize("lang", [None, "fr", "EN"])
def test_without_a_valid_lang_the_server_uses_its_own_language(tmp_path, monkeypatch, lang):
    """D6: sin `lang`, o con uno que no vale, el del proceso (aquí `es`): un JS viejo sigue igual."""
    from local_delegate import valuation

    client = _empty_logs(tmp_path, monkeypatch)
    params = {} if lang is None else {"lang": lang}
    data = client.get("/api/stats", params=params).json()
    assert data["cost"]["reason"] == i18n.t_lang("es", valuation.NO_DELEGATIONS)


def test_api_hooks_says_why_it_is_off_in_the_visitor_language(monkeypatch):
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
    client = TestClient(metrics.app)
    es = client.get("/api/hooks").json()["reason"]
    en = client.get("/api/hooks", params={"lang": "en"}).json()["reason"]
    assert es == i18n.t_lang("es", "panel.hooks.disabled")
    assert en == i18n.t_lang("en", "panel.hooks.disabled") != es


def test_api_status_roles_and_tool_summaries_come_from_the_catalog():
    """REQ-027: el resumen de cada tool sale del catálogo en el idioma del panel, no del docstring
    (que sigue en inglés y no cambia con el idioma)."""
    client = TestClient(metrics.app)
    es = client.get("/api/status").json()
    en = client.get("/api/status", params={"lang": "en"}).json()
    assert [c["label"] for c in es["catalog"]] == ["mecánico", "largo", "código", "visión"]
    assert [c["label"] for c in en["catalog"]] == ["mechanical", "long", "code", "vision"]
    names = [t.name for t in server.mcp._tool_manager.list_tools()]
    assert len(names) == 11 and [t["name"] for t in en["tools"]] == names
    for lang, data in (("es", es), ("en", en)):
        for tool in data["tools"]:
            assert tool["summary"] == i18n.t_lang(lang, "panel.tool." + tool["name"]), tool
    assert es["tools"][0]["summary"] != en["tools"][0]["summary"]


def test_every_tool_has_its_summary_in_both_catalogs():
    names = [t.name for t in server.mcp._tool_manager.list_tools()]
    for lang in ("es", "en"):
        missing = [n for n in names if "panel.tool." + n not in i18n.catalog(lang)]
        assert missing == [], (lang, missing)


@backend_mock.mock
def test_api_backend_writes_the_cause_in_the_visitor_language(monkeypatch):
    """D6: el daemon en español sirve la causa en inglés a quien la pide en inglés, también el
    `detail` que `server.probe_backend` ya redactó en el idioma del proceso. Mutante: devolver
    `probe.detail` tal cual en `_probe_detail` → el detalle sale en español y falla."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    client = TestClient(metrics.app)
    es = client.get("/api/backend").json()
    en = client.get("/api/backend", params={"lang": "en"}).json()
    assert (es["label"], es["detail"]) == (
        "fallo de red",
        "fallo de red con test-backend (ConnectError)",
    )
    assert en["label"] == failures.label("transport", language="en") == "network failure"
    assert en["detail"] == "network failure with test-backend (ConnectError)"
    status_en = client.get("/api/status", params={"lang": "en"}).json()["backend"]
    assert (status_en["label"], status_en["detail"]) == (en["label"], en["detail"])


@backend_mock.mock
def test_api_backend_rewords_an_http_status_cause(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(return_value=httpx2.Response(500))
    en = TestClient(metrics.app).get("/api/backend", params={"lang": "en"}).json()
    assert en["detail"] == failures.detail(
        en["cause"], host="test-backend", status=500, language="en"
    )
    assert "500" in en["detail"]


@backend_mock.mock
def test_api_backend_stats_writes_the_cause_in_the_visitor_language(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/api/metrics/stats").mock(
        return_value=httpx2.Response(404)
    )
    client = TestClient(metrics.app)
    es = client.get("/api/backend/stats").json()
    en = client.get("/api/backend/stats", params={"lang": "en"}).json()
    assert es["status_http"] == en["status_http"] == 404
    assert en["label"] == failures.label(en["cause"], language="en") != es["label"]


def test_the_page_carries_both_catalogs_without_closing_its_script():
    """REQ-020: el panel lleva los dos idiomas (cambia sin recargar). Un `</b>` de un texto sin
    escapar cerraría el `<script>` a mitad del catálogo."""
    html = TestClient(metrics.app).get("/").text
    assert html.count("</script>") == 2  # Chart.js y el del panel
    raw = re.search(r"const I18N = (.*?);\r?\nconst LANGS", html, re.DOTALL).group(1)
    assert "</" not in raw
    catalogs = json.loads(raw.replace("<\\/", "</"))
    assert catalogs == metrics.panel_catalogs()
    assert set(catalogs) == {"es", "en"} and len(catalogs["en"]) >= 300  # guarda de no vacío
    assert "__I18N__" not in html


# --- «Procesos del backend» sin los llama-swap de los tests (decisión del usuario, 2026-10-18) ----


@pytest.mark.parametrize(
    ("command_line", "port"),
    [
        (r"D:\llms\llama-swap.exe --config c.yaml -watch-config --listen 127.0.0.1:9292", 9292),
        ("llama-swap -config c.yaml -listen 127.0.0.1:53111 -watch-config", 53111),
        ("llama-swap --listen=:5800", 5800),
        ("llama-swap -config c.yaml", 8080),  # sin -listen: el de por defecto
        ("llama-swap -listen 127.0.0.1", None),
    ],
)
def test_listen_port_reads_the_llamaswap_command_line(command_line, port):
    from local_delegate.web import sysinfo

    assert sysinfo.listen_port(command_line) == port


def test_the_backend_processes_leave_out_the_test_llamaswaps(monkeypatch):
    """El de la suite (`fake_llamaswap.py`) es el mismo `llama-swap.exe` en un puerto libre: no se
    cuenta. El del backend, el `llama-server` y el propio daemon, sí. Mutante: que
    `is_backend_llamaswap` devuelva siempre `True` → el 202 aparece y falla el primer assert."""
    from local_delegate.web import sysinfo

    me = os.getpid()
    processes = [
        {"pid": 201, "name": "llama-swap.exe", "ram_mb": 40},
        {"pid": 202, "name": "llama-swap.exe", "ram_mb": 30},
        {"pid": 203, "name": "llama-server.exe", "ram_mb": 7000},
        {"pid": 204, "name": "llama-swap.exe", "ram_mb": 20},
        {"pid": 205, "name": "llama-swap.exe", "ram_mb": 10},
        {"pid": me, "name": "python.exe", "ram_mb": 90},
    ]
    lines = {
        201: r"D:\llms\llama-swap.exe --config c.yaml --listen 127.0.0.1:9292",
        202: r"D:\llms\llama-swap.exe -config t\config.yaml -listen 127.0.0.1:53111",
        204: sysinfo.PENDING,  # recién lanzado: su línea todavía no se ha leído
        205: None,  # no se puede leer (permisos): se cuenta, como antes de esta regla
    }
    monkeypatch.setattr(config, "BASE_URL", "http://127.0.0.1:9292/v1")
    monkeypatch.setattr(sysinfo, "_all_processes", lambda: processes)
    monkeypatch.setattr(sysinfo, "_command_line", lambda pid: lines.get(pid))
    monkeypatch.setattr(sysinfo, "proc_vram_map", dict)

    pids = [p["pid"] for p in sysinfo.interesting_processes()]

    assert 202 not in pids
    assert 204 not in pids
    assert pids == [me, 203, 201, 205]  # el daemon primero y luego por RAM


@pytest.mark.llamaswap_real
@pytest.mark.skipif(sys.platform != "win32", reason="la línea de órdenes se lee con PowerShell")
def test_a_real_test_llamaswap_is_not_listed(tmp_path):
    """Probar el uso, no la pieza: un llama-swap de prueba DE VERDAD (`fake_llamaswap.py`, el mismo
    ejecutable que el backend) no sale en «Procesos del backend» una vez leída su línea de órdenes."""
    from fake_llamaswap import FakeModel, binary_available, fake_llamaswap

    from local_delegate.web import sysinfo

    if not binary_available():
        pytest.skip("falta llama-swap-v255 de prueba")
    with fake_llamaswap(tmp_path, [FakeModel("m-proc")]) as ls:
        pid = ls._proc.pid
        listed: dict[int, str] = {}
        sampled = False
        for _ in range(150):  # la primera muestra de PowerShell tarda ~1 s
            listed = {p["pid"]: p["name"] for p in sysinfo.interesting_processes()}
            with sysinfo._cmd_lock:
                sampled = pid in sysinfo._cmd_cache["lines"]
            if sampled:
                listed = {p["pid"]: p["name"] for p in sysinfo.interesting_processes()}
                break
            time.sleep(0.1)
        assert sampled, "guarda: la línea de órdenes del llama-swap de prueba llegó a leerse"
        assert f":{ls.port}" in sysinfo._cmd_cache["lines"][pid]
        assert pid not in listed
