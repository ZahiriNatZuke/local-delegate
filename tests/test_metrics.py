"""Tests de F4: loader por rango en web/metrics.py (_log_files, _load, /api/inflight,
/api/backend, /api/events) — rotación mensual, cache por archivo, y los endpoints nuevos."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import backend_mock
import httpx2
import pytest
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
        "causa": "transporte",
        "etiqueta": "fallo de red",
        "detalle": "fallo de red con test-backend (ConnectError)",
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
        "causa": "http_error",
        "etiqueta": "responde con error",
        "detalle": "test-backend responde HTTP 404",
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
        "causa": "transporte",
        "etiqueta": "fallo de red",
        "detalle": "fallo de red con test-backend (ConnectError)",
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
def test_api_backend_dice_la_causa_de_un_401(monkeypatch):
    """REQ-012/REQ-014: un 401 es un backend vivo que rechaza la credencial, no uno caído."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(401))
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(401))

    j = TestClient(metrics.app).get("/api/backend").json()

    assert j.get("causa") == "credencial"
    assert j["available"] is False
    assert "401" in (j.get("detalle") or "")


@backend_mock.mock
def test_api_backend_conserva_la_lista_y_la_marca_vieja(monkeypatch):
    """REQ-021: tras un sondeo bueno, uno con `ConnectError` devuelve la misma lista, sin estado."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    ruta = backend_mock.get(MODELS).mock(
        return_value=httpx2.Response(200, json={"data": [{"id": "m1", "status": "loaded"}]})
    )
    backend_mock.get(RUNNING).mock(return_value=httpx2.Response(200, json={"running": []}))
    client = TestClient(metrics.app)
    bueno = client.get("/api/backend").json()
    ruta.mock(side_effect=httpx2.ConnectError("down"))

    j = client.get("/api/backend").json()

    assert j.get("models_stale") is True
    assert bueno.get("models_stale") is False
    assert [m["id"] for m in j["models"]] == ["m1"]
    assert j["models"][0]["status"] is None
    assert j.get("causa") == "transporte"


@backend_mock.mock
def test_api_backend_no_pide_running_si_models_falla(monkeypatch):
    """REQ-013: con el backend inalcanzable se gasta un plazo de conexión, no dos."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(MODELS).mock(side_effect=httpx2.ConnectError("down"))
    ruta_running = backend_mock.get(RUNNING).mock(
        return_value=httpx2.Response(200, json={"running": []})
    )

    j = TestClient(metrics.app).get("/api/backend").json()

    assert ruta_running.call_count == 0
    assert j["running"] == []


@backend_mock.mock
def test_api_backend_dice_si_running_respondio(monkeypatch):
    """REQ-022: `running_ok` falso con un backend que no es llama-swap (`/running` → 404)."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(MODELS).mock(
        return_value=httpx2.Response(200, json={"data": [{"id": "m1", "status": "loaded"}]})
    )
    ruta_running = backend_mock.get(RUNNING).mock(return_value=httpx2.Response(404))
    client = TestClient(metrics.app)

    j = client.get("/api/backend").json()

    assert j.get("running_ok") is False
    assert j["available"] is True
    ruta_running.mock(
        return_value=httpx2.Response(200, json={"running": [{"model": "m1", "state": "ready"}]})
    )
    assert client.get("/api/backend").json().get("running_ok") is True


@backend_mock.mock
def test_api_status_dice_la_causa_en_el_bloque_backend(monkeypatch):
    """REQ-012: `/api/status` usa el mismo sondeo que `/api/backend`."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(MODELS).mock(return_value=httpx2.Response(401))

    data = TestClient(metrics.app).get("/api/status").json()

    assert data["backend"].get("causa") == "credencial"
    assert data["backend"].get("models_stale") is True
    assert "401" in (data["backend"].get("detalle") or "")


@backend_mock.mock
def test_api_backend_stats_dice_el_codigo_con_un_404(monkeypatch):
    """REQ-020: el panel solo culpa a la versión de llama-swap con un 404, así que lo necesita."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get(STATS).mock(return_value=httpx2.Response(404))

    j = TestClient(metrics.app).get("/api/backend/stats").json()

    assert j.get("status_http") == 404
    assert j.get("causa") == "http_error"
    assert j["available"] is False


def test_api_backend_stats_dice_la_causa_con_un_nombre_que_no_resuelve(monkeypatch):
    """Red real: un nombre `.invalid` no resuelve nunca (RFC 6761). Sin código HTTP."""
    monkeypatch.setattr(config, "BASE_URL", "http://no-existe.invalid:9292/v1")

    j = TestClient(metrics.app).get("/api/backend/stats").json()

    assert j.get("causa") == "dns"
    assert j.get("status_http") is None
    assert "no-existe.invalid" in (j.get("detalle") or "")


def _plazo_de_conexion(t):
    """Lee el plazo de conexión sin reventar si llega un número (control (a) del plan)."""
    return t.connect if isinstance(t, httpx2.Timeout) else t


def test_api_backend_stats_usa_el_plazo_de_sondeo(monkeypatch):
    """REQ-013: `/api/metrics/stats` es un sondeo de estado y lleva su plazo, no 1 s."""
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    plazos: list = []
    real = httpx2.Client

    def registrador(*args, **kwargs):
        plazos.append(kwargs.get("timeout"))
        transporte = httpx2.MockTransport(lambda req: httpx2.Response(404))
        return real(transport=transporte)

    monkeypatch.setattr(httpx2, "Client", registrador)

    TestClient(metrics.app).get("/api/backend/stats")

    assert plazos, "el endpoint no llegó a crear el cliente"
    plazo_conexion = _plazo_de_conexion(plazos[0])
    assert plazo_conexion == config.TIMEOUT_SONDA_CONEXION
    assert plazos[0].read == config.TIMEOUT_SONDA_LECTURA


def test_api_system_dice_plataforma_origen_y_host(monkeypatch):
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


def test_api_inflight_deja_pasar_la_espera_local(tmp_path, monkeypatch):
    """REQ-022: la fila «en cola local» depende de que `espera_local` llegue al panel."""
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
                "espera_local": "plaza",
            }
        },
    )

    entradas = TestClient(metrics.app).get("/api/inflight").json()["inflight"]

    assert len(entradas) == 1
    e = entradas[0]
    assert e.get("espera_local") == "plaza"


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
    assert by_backend["local"]["tokens_saved"] == 1000
    assert by_backend["remote"]["tokens_saved"] == 2000
    assert by_backend["remote"]["hosts"] == ["pc.ts.net:9292"]
    # los eventos previos al campo no se cuentan como locales: quedan como "unknown"
    assert by_backend["unknown"]["calls"] == 1


def test_dashboard_computes_ranges_in_local_time():
    """El selector 'Hoy' usa la medianoche LOCAL, no la UTC (que corre el día)."""
    html = TestClient(metrics.app).get("/").text
    assert "localMidnight" in html and "localDayKey" in html
    assert "Date.UTC(" not in html  # ya no queda ningún rango calculado en UTC


def test_estados_vacios_usan_la_tipografia_del_panel():
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
    manifiesto = json.loads(
        (Path(metrics.__file__).parents[1] / "resources" / "vendor" / "vendor.json").read_text(
            encoding="utf-8"
        )
    )
    version = next(f["version"] for f in manifiesto["files"] if f["file"] == "chart.umd.min.js")
    assert f"Chart.js v{version}" in r.text


def test_web_fonts_can_be_disabled_for_zero_third_party_requests(monkeypatch):
    # La hoja completa con esquema y ruta, no el host suelto: buscar solo "fonts.googleapis.com"
    # daría por bueno un href a "https://fonts.googleapis.com.otrositio.tld/…", que es un tercero
    # distinto. Los asserts de ausencia de más abajo sí van por subcadena, y ahí es lo correcto:
    # cualquier aparición de "googleapis" con WEB_FONTS=False es un fallo.
    hoja = 'href="https://fonts.googleapis.com/css2?'
    html = TestClient(metrics.app).get("/").text
    assert hoja in html  # por defecto sí, es solo tipografía

    monkeypatch.setattr(config, "WEB_FONTS", False)
    html = metrics.render_index()
    assert hoja not in html
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


def test_accounting_una_llamada_sin_trocear():
    a = metrics._accounting(_ev(tokens_in=1100, tokens_out=90))
    assert a == {
        "backend_calls": 1,
        "tokens_in": 1100,
        "tokens_out": 90,
        "saved": 1000,  # chars_in ÷ 4: el contenido que no entró al contexto
        "returned": 100,  # chars_out ÷ 4: lo que la tool devolvió al contexto
        "net": 900,
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


def test_accounting_troceado_separa_ahorro_de_coste():
    """El caso que da nombre al change, con los números del evento REAL del log."""
    a = metrics._accounting(_ev(chars_in=84178, chunks=4, tokens_in=26131, tokens_out=786))
    assert a["backend_calls"] == 4  # cuatro llamadas al backend, no una
    assert a["tokens_in"] == 26131  # coste real, con el prompt de sistema repetido 4 veces
    assert a["saved"] == 21044  # ahorro: el documento UNA vez, no cuatro
    assert a["tokens_in"] > a["saved"]  # el troceo lo paga la GPU, no el contexto


def test_accounting_sin_tokens_estima_y_lo_declara():
    a = metrics._accounting(_ev())
    assert a["tokens_in"] == 1000 and a["tokens_out"] == 100
    assert a["estimated"] is True


def test_accounting_imagen_usa_el_token_real_y_no_los_bytes():
    """chars_in son BYTES del PNG: dividirlos entre 4 inventaba un ahorro ×48."""
    a = metrics._accounting(
        _ev(
            tool="local_describe_image",
            input_unit="bytes",
            chars_in=504780,
            tokens_in=2758,
            tokens_out=37,
        )
    )
    assert a["saved"] == 2758
    assert a["tokens_in"] == 2758


def test_accounting_imagen_historica_sin_marca_se_reconoce_por_la_tool():
    """Los eventos anteriores al campo `input_unit` no se pueden reescribir: hay 4 en el log."""
    a = metrics._accounting(
        _ev(tool="local_describe_image", chars_in=504780, tokens_in=2758, tokens_out=37)
    )
    assert a["saved"] == 2758


def test_accounting_imagen_sin_token_real_no_inventa_numero():
    a = metrics._accounting(_ev(tool="local_describe_image", input_unit="bytes", chars_in=504780))
    assert a["saved"] == 0  # ni estimable ni real: 0 antes que un número falso
    assert a["tokens_in"] == 0
    assert a["estimated"] is True


def test_accounting_inline_no_cuenta_como_ahorro():
    a = metrics._accounting(_ev(source="inline", tokens_in=1100, tokens_out=90))
    assert a["saved"] == 0
    assert a["tokens_in"] == 1100  # pero el coste sí se cuenta: la GPU lo gastó igual


def test_accounting_fallo_a_mitad_cuenta_las_llamadas_gastadas():
    a = metrics._accounting(_ev(chunks=3, ok=False, tokens_in=900, tokens_out=10))
    assert a["backend_calls"] == 3


# --- Panel honesto (REQ-001 a REQ-008): fallos fuera, neto dentro, desglose en caracteres --------
#
# Los campos nuevos se leen con `.get(...)`: contra el código de antes el test tiene que fallar por
# el assert que nombra el plan, no por un `KeyError`.

# El evento del escenario «el neto resta lo que volvió al contexto».
_NETO_RESTA = {
    "source": "path",
    "chars_in": 4000,
    "chars_out": 400,
    "ok": True,
    "tokens_in": 1100,
    "tokens_out": 90,
}
# El del escenario «la salida a fichero no descuenta el recibo».
_SALIDA_A_FICHERO = {
    "source": "inline",
    "output_to_file": True,
    "chars_out": 4000,
    "tokens_out": 950,
    "ok": True,
    "tokens_in": 10,
}
# El del escenario «una imagen por `path`».
_IMAGEN_POR_PATH = {
    "tool": "local_describe_image",
    "source": "path",
    "chars_in": 250000,
    "chars_out": 800,
    "ok": True,
    "tokens_in": 1200,
    "tokens_out": 200,
}
# El del escenario «un fallo no infla las cuentas»: sin tokens, con el texto del error de vuelta.
_FALLO_SIN_TOKENS = {"source": "path", "chars_in": 4000, "chars_out": 144, "ok": False}


def test_accounting_un_fallo_no_ahorra_ni_genera():
    a = metrics._accounting(dict(_FALLO_SIN_TOKENS))
    assert a["saved"] == 0
    assert (a.get("returned"), a.get("net")) == (0, 0)
    assert (a.get("chars_saved_text"), a.get("chars_returned")) == (0, 0)
    assert (a["tokens_in"], a["tokens_out"]) == (0, 0), "el texto del error no es generación"
    assert a["estimated"] is False
    assert a.get("failed") is True
    assert a["backend_calls"] == 1


def test_accounting_un_fallo_no_es_una_estimacion():
    a = metrics._accounting(_ev(ok=False))
    assert a["estimated"] is False
    assert a.get("failed") is True


def test_accounting_fallo_troceado_conserva_el_coste_real():
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


def test_accounting_neto_resta_lo_devuelto():
    a = metrics._accounting(dict(_NETO_RESTA))
    assert a.get("returned") == 100
    assert a["saved"] == 1000
    assert a.get("net") == 900


def test_accounting_salida_a_fichero_no_descuenta_el_recibo():
    a = metrics._accounting(dict(_SALIDA_A_FICHERO))
    assert a.get("net") == 950
    assert a["saved"] == 950
    assert a.get("returned") == 0, "el recibo de dos líneas no se registra: se toma 0"


def test_accounting_el_neto_puede_ser_negativo():
    a = metrics._accounting(_ev(chars_in=400, chars_out=800, tokens_in=120, tokens_out=200))
    assert a.get("net") == -100
    assert (a["saved"], a.get("returned")) == (100, 200)


def test_accounting_desglosa_en_caracteres():
    """Los cuatro campos del contrato con `coste-api-y-cuota`, más los del evento que copia."""
    a = metrics._accounting(dict(_NETO_RESTA))
    assert a.get("chars_saved_text") == 4000
    assert a.get("chars_returned") == 400
    assert (a.get("bytes_saved_image"), a.get("chars_saved_output")) == (0, 0)
    assert (a.get("unit"), a.get("source"), a.get("failed")) == ("chars", "path", False)

    s = metrics._accounting(dict(_SALIDA_A_FICHERO))
    assert s.get("chars_saved_output") == 4000
    assert (s.get("chars_returned"), s.get("chars_saved_text")) == (0, 0)

    i = metrics._accounting(dict(_IMAGEN_POR_PATH))
    assert i.get("bytes_saved_image") == 250000, "la imagen va en BYTES, en su propio campo"
    assert i.get("chars_saved_text") == 0
    assert i.get("chars_returned") == 800
    assert (i["saved"], i.get("returned"), i.get("net")) == (1200, 200, 1000)
    assert (i.get("unit"), i.get("tool")) == ("bytes", "local_describe_image")

    f = metrics._accounting(dict(_FALLO_SIN_TOKENS, tool="local_summarize", model="m"))
    campos = ("chars_saved_text", "bytes_saved_image", "chars_saved_output", "chars_returned")
    assert [f.get(c) for c in campos] == [0, 0, 0, 0]
    assert (f.get("tool"), f.get("model"), f.get("failed")) == ("local_summarize", "m", True)


def test_tokens_claude_es_la_unica_conversion(monkeypatch):
    """REQ-008: lo ahorrado y lo devuelto pasan SOLO por `tokens_claude`; el coste local, no."""
    monkeypatch.setattr(server, "tokens_claude", lambda cantidad, *, tipo, evento: 7)
    a = metrics._accounting(dict(_NETO_RESTA))
    assert a["saved"] == 7
    assert a.get("returned") == 7
    assert a.get("net") == 0
    assert a["tokens_in"] == 1100, "el coste del modelo local no pasa por la conversión"


def test_stats_distingue_delegaciones_de_llamadas_al_backend(tmp_path, monkeypatch):
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
    assert j["tokens_context_saved"] == 22044
    assert j["estimated_events"] == 0
    tool = j["by_tool"][0]
    assert tool["backend_calls"] == 5 and tool["tokens_in"] == 27231


def test_stats_marca_los_eventos_que_hubo_que_estimar(tmp_path, monkeypatch):
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


def _stats_de(tmp_path, monkeypatch, filas: list[dict]) -> dict:
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "USAGE_LOG", tmp_path / "usage.jsonl")
    _write_jsonl(tmp_path / "usage-202607.jsonl", filas)
    metrics._FILE_CACHE.clear()
    return (
        TestClient(metrics.app)
        .get("/api/stats?from=2026-07-01T00:00:00%2B00:00&to=2026-08-01T00:00:00%2B00:00")
        .json()
    )


def test_stats_el_log_sintetico_de_la_mac_no_infla_nada(tmp_path, monkeypatch):
    """Escenario de la Mac, sintético: 4 delegaciones buenas con `usage` y 4 `connect_error`."""
    buenas = [_ev(tokens_in=1100, tokens_out=90) for _ in range(4)]
    fallos = [
        _ev(ok=False, error="connect_error", error_class="backend_ausente", chars_out=144)
        for _ in range(4)
    ]
    j = _stats_de(tmp_path, monkeypatch, buenas + fallos)
    assert j["estimated_events"] == 0
    assert j["tokens_context_saved"] == 4 * 1000, "solo suman las 4 buenas"
    assert j["tokens_generated_local"] == 4 * 90
    assert j.get("tokens_returned") == 4 * 100
    assert j.get("tokens_context_net") == j["tokens_context_saved"] - j.get("tokens_returned", 0)


def test_stats_ok_null_no_cuenta_como_error():
    """REQ-006: el predicado de fallo es `ok` exactamente `false`, igual que en la contabilidad."""
    j = metrics._aggregate([_ev(ok=None), _ev()])
    assert j["total"]["errors"] == 0
    assert j["by_tool"][0]["errors"] == 0


def test_stats_expone_el_desglose_en_caracteres(tmp_path, monkeypatch):
    j = _stats_de(
        tmp_path,
        monkeypatch,
        [
            _ev(**_NETO_RESTA),
            _ev(**_SALIDA_A_FICHERO),
            _ev(**_IMAGEN_POR_PATH),
            _ev(**_FALLO_SIN_TOKENS),
        ],
    )
    assert j.get("chars_saved_text") == 4000
    assert j.get("bytes_saved_image") == 250000
    assert j.get("chars_saved_output") == 4000
    assert j.get("chars_returned") == 400 + 800
    assert j.get("tokens_returned") == 100 + 200
    assert j["tokens_context_saved"] == 1000 + 950 + 1200
    assert j.get("tokens_context_net") == 900 + 950 + 1000
    assert j["total"]["errors"] == 1


def test_stats_quien_delego_trae_el_neto():
    j = metrics._aggregate(
        [
            _ev(client="claude-code", **_NETO_RESTA),
            _ev(client="claude-code", **_FALLO_SIN_TOKENS),
        ]
    )
    fila = j["by_client"][0]
    assert fila.get("tokens_net") == 900, "el fallo no suma y el devuelto se resta"
    assert j["by_tool"][0].get("tokens_net") == 900
    assert j["by_backend"][0].get("tokens_net") == 900


def test_el_js_usa_un_solo_predicado_de_fallo():
    """REQ-006: `!e.ok` cuenta `ok: null` como fallo; la regla dice `ok` exactamente `false`."""
    html = metrics.HTML
    assert "!e.ok" not in html
    assert "e.ok?'ok':'err'" not in html
    assert "e.ok===false" in html


def test_dashboard_pide_los_kpis_al_servidor():
    """Una sola implementación de las cuentas: el panel no las recalcula en el cliente."""
    html = TestClient(metrics.app).get("/").text
    assert "fetch('/api/stats?'" in html


def _extraer_funcion_js(fuente: str, cabecera: str) -> str:
    """Recorta una función del <script> inline balanceando llaves (no hay strings con '{' dentro)."""
    i = fuente.index(cabecera)
    depth, j = 0, i
    while True:
        if fuente[j] == "{":
            depth += 1
        elif fuente[j] == "}":
            depth -= 1
            if depth == 0:
                return fuente[i : j + 1]
        j += 1


def _sin_ok(evento: dict) -> dict:
    """`_ev` pone `ok: True` por defecto: el caso «sin clave `ok`» se construye quitándola."""
    return {k: v for k, v in evento.items() if k != "ok"}


# Pares (campo en Python, campo en JS) del contrato con `coste-api-y-cuota`, más los de siempre.
# Empieza por `returned`: es el primero que no existía, así que el control lo nombra.
_CAMPOS_PARIDAD = (
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


def test_paridad_acct_entre_python_y_el_js_del_panel(tmp_path):
    """Las series por día se agrupan en el navegador (dependen de tu zona), así que la regla de
    contabilidad vive por duplicado. Este test ata las dos copias: si divergen, el gráfico
    contradiría al KPI que tiene encima — el mismo defecto que este change vino a cerrar."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")

    tokens_claude_js = _extraer_funcion_js(metrics.HTML, "function tokensClaude(")
    acct_js = _extraer_funcion_js(metrics.HTML, "function acct(e){")
    casos = [
        # --- Los 12 casos de REQ-001, en este orden ---------------------------------------
        _ev(tokens_in=1100, tokens_out=90),  # neto positivo
        _ev(ok=False, error="connect_error", chars_out=144),  # fallo sin tokens
        _ev(chunks=3, ok=False, tokens_in=900, tokens_out=10),  # fallo troceado con tokens
        _ev(ok=None),  # `ok: null`: bueno
        _sin_ok(_ev(source="path", chars_in=4000)),  # sin clave `ok`: bueno
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
        # Los dos campos a la vez: una operación por trozos que saltó y luego falló. Sin este caso
        # un mutante que invertía el orden de la causa en el JS sobrevivía a la paridad.
        _ev(
            ok=False,
            model_requested="gemma4-26b-a4b",
            fallback_reason="http_500",
            fallback_class="modelo",
            error="http_503",
            error_class="sin_clasificar",
            chunks=3,
        ),
    ]
    entrada = tmp_path / "casos.json"
    entrada.write_text(json.dumps(casos), encoding="utf-8")
    programa = tmp_path / "paridad.mjs"
    programa.write_text(
        "import {readFileSync} from 'node:fs';\n"
        "const CPT = 4;\n"
        "const tok = c => Math.floor(c/CPT);\n"
        f"{tokens_claude_js}\n"
        f"{acct_js}\n"
        f"const casos = JSON.parse(readFileSync({json.dumps(str(entrada))}, 'utf-8'));\n"
        "console.log(JSON.stringify(casos.map(acct)));\n",
        encoding="utf-8",
    )
    salida = subprocess.run(
        [node, str(programa)], capture_output=True, text=True, timeout=30, check=True
    )
    desde_js = json.loads(salida.stdout)

    desde_py = [metrics._accounting(c) for c in casos]
    for caso, py, js in zip(casos, desde_py, desde_js, strict=True):
        for campo_py, campo_js in _CAMPOS_PARIDAD:
            # `.get`: un campo que falta en el JS falla por el assert, no por `KeyError`.
            assert js.get(campo_js) == py[campo_py], (campo_py, caso)
    # Guarda de «esto llegó a comprobar algo» (REQ-001): sin un caso de cada, la paridad de las
    # ramas nuevas saldría verde con las dos copias rotas.
    assert any(py["net"] < 0 for py in desde_py)
    assert any(py["failed"] and py["tokens_in"] > 0 for py in desde_py)
    assert any("ok" not in c for c in casos)
    assert any(py["bytes_saved_image"] > 0 for py in desde_py)
    assert any(py["chars_saved_output"] > 0 for py in desde_py)
    assert any(py["fallback"] for py in desde_py)
    assert any(py["cause"] == "configuracion" for py in desde_py)


def test_local_status_y_el_dashboard_cuentan_igual(tmp_path, monkeypatch):
    """Tercera superficie: `local_status` tenía su propia copia de la cuenta (chars_in ÷ 4 a
    mano, imágenes incluidas), así que habría seguido dando un número distinto al del panel
    sobre el MISMO log."""
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    log = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "USAGE_LOG", log)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    filas = [
        _ev(chars_in=84178, chunks=4, tokens_in=26131, tokens_out=786),
        _ev(
            tool="local_describe_image",
            input_unit="bytes",
            chars_in=504780,
            tokens_in=2758,
            tokens_out=37,
        ),
    ]
    _write_jsonl(log, filas)
    metrics._FILE_CACHE.clear()

    agregado = metrics._aggregate(filas)
    texto = server.local_status()
    assert f"(bruto ~{agregado['tokens_context_saved']})" in texto
    assert f"({agregado['backend_calls']} llamadas al backend)" in texto


def test_local_status_cuenta_el_neto_como_el_panel(tmp_path, monkeypatch):
    """REQ-005: `local_status` dice el neto y el bruto con la misma función que el panel."""
    monkeypatch.setattr(config, "LOG_ROTATION_ENABLED", False)
    log = tmp_path / "usage.jsonl"
    monkeypatch.setattr(config, "USAGE_LOG", log)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    filas = [
        _ev(**_NETO_RESTA),
        _ev(**_FALLO_SIN_TOKENS),
        _ev(chars_in=400, chars_out=800, tokens_in=120, tokens_out=200),
    ]
    _write_jsonl(log, filas)
    metrics._FILE_CACHE.clear()

    agregado = metrics._aggregate(filas)
    # Si la clave falta (código de antes), el texto esperado tampoco está: falla el assert y no un
    # `TypeError` al formatear un `None`.
    n = agregado.get("tokens_context_net", "(falta tokens_context_net)")
    esperado = f"~{n} tokens netos"
    texto = server.local_status()
    assert esperado in texto
    assert f"(bruto ~{agregado['tokens_context_saved']})" in texto


# --- F3, tarea 29: el salto y su causa, en la cuenta y en el panel -----------------------------


def test_accounting_marca_el_salto_y_su_causa():
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
    assert a["cause"] == "modelo"
    assert a["backend_calls"] == 2, "la llamada del respaldo también gastó backend"


def test_accounting_causa_de_configuracion_en_un_fallo():
    a = metrics._accounting(_ev(ok=False, error="config_max_tokens", error_class="configuracion"))
    assert a["fallback"] is False
    assert a["cause"] == "configuracion"


def test_accounting_en_un_fallo_tras_saltar_la_causa_es_la_del_fallo():
    a = metrics._accounting(
        _ev(
            ok=False,
            model_requested="gemma4-26b-a4b",
            fallback_class="modelo",
            error_class="sin_clasificar",
        )
    )
    assert a["cause"] == "sin_clasificar", "manda cómo acabó la operación, no por qué saltó"
    assert a["fallback"] is True


def test_accounting_el_historico_sin_campos_nuevos_se_lee_igual():
    a = metrics._accounting(_ev(chars_in=84178, chunks=4, tokens_in=26131, tokens_out=786))
    assert a["fallback"] is False and a["cause"] is None
    assert (a["backend_calls"], a["tokens_in"], a["saved"]) == (4, 26131, 21044)


def test_stats_cuenta_los_saltos_y_las_causas_y_atribuye_al_que_respondio(tmp_path, monkeypatch):
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
                error_class="configuracion",
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
    assert j["causes"] == {"modelo": 1, "configuracion": 1}
    por_modelo = {m["model"]: m for m in j["by_model"]}
    assert por_modelo["gemma3-4b"]["tokens_in"] == 600, "los tokens del salto van al que respondió"
    assert por_modelo["gemma3-4b"]["backend_calls"] == 3
    assert por_modelo["gemma3-4b"]["fallback_calls"] == 1


def test_el_panel_marca_las_operaciones_con_salto():
    html = metrics.HTML
    assert "e.model_requested" in html and "fbchip" in html
    assert "e.error_class" in html


# --- Quién delegó: el desglose por cliente -----------------------------------------------------
#
# Nace de la medición de adopción: el KPI de ahorro es acumulativo y no distingue un mes de smoke
# tests de un mes de trabajo real. En la medición del 3-ago las 20 líneas de una prueba sólo se
# separaron cruzando a mano contra los transcripts, que es algo que el panel no puede hacer.


def _fila_de_uso(**extra) -> dict:
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


def test_stats_separa_las_delegaciones_por_cliente():
    agregado = metrics._aggregate(
        [
            _fila_de_uso(client="claude-code"),
            _fila_de_uso(client="claude-code"),
            _fila_de_uso(client="codex-mcp-client"),
        ]
    )

    por_cliente = {c["client"]: c["calls"] for c in agregado["by_client"]}
    assert por_cliente == {"claude-code": 2, "codex-mcp-client": 1}


def test_stats_no_reparte_ni_descarta_las_lineas_sin_cliente():
    """Las de antes de que el campo existiera, y las que no vienen de una sesión MCP.

    Repartirlas entre los clientes conocidos inventaría de quién eran, y descartarlas haría que
    los totales de la tarjeta no cuadraran con el KPI de arriba. Casilla propia.
    """
    agregado = metrics._aggregate([_fila_de_uso(client="claude-code"), _fila_de_uso()])

    por_cliente = {c["client"]: c["calls"] for c in agregado["by_client"]}
    assert por_cliente == {"claude-code": 1, "desconocido": 1}
    assert sum(c["calls"] for c in agregado["by_client"]) == agregado["total"]["calls"]
