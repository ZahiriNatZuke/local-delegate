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
        "models": [],
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
    assert roles == {"mechanical", "long", "code", "fast", "vision"}
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
    assert client.get("/api/backend/stats").json() == {"available": False}


@backend_mock.mock
def test_api_status_backend_down(monkeypatch):
    monkeypatch.setattr(config, "BASE_URL", "http://test-backend/v1")
    backend_mock.get("http://test-backend/v1/models").mock(side_effect=httpx2.ConnectError("down"))
    client = TestClient(metrics.app)
    data = client.get("/api/status").json()
    assert data["backend"] == {
        "available": False,
        "models": [],
        "origin": "remote",
        "host": "test-backend",
    }
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
    monkeypatch.setattr(sysinfo, "interesting_processes", list)
    client = TestClient(metrics.app)
    r = client.get("/api/system")
    assert r.status_code == 200
    assert r.json() == {"ram": None, "vram": None, "processes": []}


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
        "estimated": False,
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


def test_paridad_acct_entre_python_y_el_js_del_panel(tmp_path):
    """Las series por día se agrupan en el navegador (dependen de tu zona), así que la regla de
    contabilidad vive por duplicado. Este test ata las dos copias: si divergen, el gráfico
    contradiría al KPI que tiene encima — el mismo defecto que este change vino a cerrar."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")

    acct_js = _extraer_funcion_js(metrics.HTML, "function acct(e){")
    casos = [
        _ev(tokens_in=1100, tokens_out=90),
        _ev(chars_in=84178, chunks=4, tokens_in=26131, tokens_out=786),
        _ev(),  # sin tokens: estimado
        _ev(chars_in=4002, tokens_out=7),  # impar: caza floor contra round
        _ev(
            tool="local_describe_image",
            input_unit="bytes",
            chars_in=504780,
            tokens_in=2758,
            tokens_out=37,
        ),
        _ev(tool="local_describe_image", chars_in=504780, tokens_in=2758, tokens_out=37),
        _ev(tool="local_describe_image", input_unit="bytes", chars_in=504780),
        _ev(source="inline", tokens_in=1100, tokens_out=90),
        _ev(chunks=3, ok=False, tokens_in=900, tokens_out=10),
    ]
    entrada = tmp_path / "casos.json"
    entrada.write_text(json.dumps(casos), encoding="utf-8")
    programa = tmp_path / "paridad.mjs"
    programa.write_text(
        "import {readFileSync} from 'node:fs';\n"
        "const CPT = 4;\n"
        "const tok = c => Math.floor(c/CPT);\n"
        f"{acct_js}\n"
        f"const casos = JSON.parse(readFileSync({json.dumps(str(entrada))}, 'utf-8'));\n"
        "console.log(JSON.stringify(casos.map(acct)));\n",
        encoding="utf-8",
    )
    salida = subprocess.run(
        [node, str(programa)], capture_output=True, text=True, timeout=30, check=True
    )
    desde_js = json.loads(salida.stdout)

    for caso, js in zip(casos, desde_js, strict=True):
        py = metrics._accounting(caso)
        assert js["calls"] == py["backend_calls"], caso
        assert js["tokensIn"] == py["tokens_in"], caso
        assert js["tokensOut"] == py["tokens_out"], caso
        assert js["saved"] == py["saved"], caso
        assert js["estimated"] == py["estimated"], caso


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
    assert f"~{agregado['tokens_context_saved']} tokens" in texto
    assert f"({agregado['backend_calls']} llamadas al backend)" in texto
