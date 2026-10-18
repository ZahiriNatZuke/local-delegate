"""Coste, cuota e imágenes en `/api/stats` y en el JS del panel (coste-api-y-cuota, T6).

Lo que sirve el backend se prueba con `TestClient`; las funciones puras del panel (`costText`,
`quotaText`, `imagesText`) se **ejecutan con node** sobre esa misma respuesta, como las demás
del panel. El HOME es sintético en todos los tests: el panel no puede leer `~/.claude` (REQ-073) y
un test que lo comprueba necesita un `~/.claude` que pueda leer si estuviera mal.
"""

from __future__ import annotations

import builtins
import contextlib
import inspect
import io
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_dashboard_js import i18n_prelude

from local_delegate import attribution, cost, quota, recompute, server
from local_delegate import config as cfg
from local_delegate.web import metrics

FORBIDDEN_PHRASES = (
    "ahorraste $",
    "ahorro en dólares",
    "dinero ahorrado",
    "tokens de tu cuota",
    "ahorro de cuota",
    "cuota que no gastaste",
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """LOG_DIR y HOME sintéticos, respaldo declarado, caché del lector limpia."""
    logs = tmp_path / "logs"
    logs.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(cfg, "LOG_DIR", logs)
    monkeypatch.setattr(cfg, "USAGE_LOG", logs / "usage.jsonl")
    monkeypatch.setattr(cfg, "COST_FALLBACK", "")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    metrics._FILE_CACHE.clear()
    yield logs, home
    metrics._FILE_CACHE.clear()


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _line(ts: datetime, n: int = 0, **extra) -> dict:
    row = {
        "ts": ts.isoformat(timespec="seconds"),
        "tool": "local_summarize",
        "source": "path",
        "path": f"C:/docs/notas-{n}.md",
        "chars_in": 3_000_000,
        "chars_out": 0,
        "ok": True,
        "tokens_in": 9000,
        "tokens_out": 100,
        "client": "claude-code",
        "tool_use_id": f"toolu_{n:04d}",
    }
    row.update(extra)
    return row


IMAGE = {
    "tool": "local_describe_image",
    "source": "path",
    "chars_in": 250000,
    "chars_out": 800,
    "ok": True,
    "tokens_in": 1200,
    "tokens_out": 200,
    "client": "claude-code",
}


def _write_log(logs: Path, rows: list[dict]) -> None:
    by_month: dict[str, list[dict]] = {}
    for f in rows:
        by_month.setdefault(f["ts"][:7].replace("-", ""), []).append(f)
    for month, month_rows in by_month.items():
        with (logs / f"usage-{month}.jsonl").open("a", encoding="utf-8") as stream:
            for f in month_rows:
                stream.write(json.dumps(f, ensure_ascii=False) + "\n")
    metrics._FILE_CACHE.clear()


def _stats(since: datetime | None = None, until: datetime | None = None, **kw) -> dict:
    client = TestClient(metrics.app, **kw)
    if since is None:
        return client.get("/api/stats").json()
    qs = f"from={since.isoformat()}&to={until.isoformat()}".replace("+", "%2B")
    return client.get("/api/stats?" + qs).json()


def _point(end: datetime, c: float, source: str = "statusline", hours: int = 4) -> dict:
    return {
        "source": source,
        "type": "five_hour",
        "start": (end - timedelta(hours=hours)).isoformat(),
        "end": end.isoformat(),
        "delta_pct": 40 if source == "statusline" else 100,
        "delta_usd": round(c * 0.4, 2),
        "C": c,
        "marks": [quota.MARK_OTHER_SURFACES],
        "unpriced_requests": None,
    }


def _aggregates(logs: Path, points: list[dict]) -> None:
    recompute.write_aggregates(
        logs,
        {
            "version": 1,
            "generated": _now().isoformat(),
            "cleanup_days": 30,
            "check": None,
            "n_by_month": {},
            "points": points,
            "discards": {"five_hour": {}, "seven_day": {}},
            "resets": {"five_hour": None, "seven_day": None},
            "sources": {"transcripts": True, "statusline": True},
        },
    )


# --- node: las funciones puras del panel --------------------------------------------------------


def _extract(header: str) -> str:
    """Recorta una función (o un objeto) del `<script>` balanceando llaves."""
    source = metrics.HTML
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


_FUNCTIONS = (
    "function fmtNum(",
    "function plural(",
    "function dollars(",
    "function costText(",
    "function quotaText(",
    "function imagesText(",
)


def _texts(tmp_path, stats: dict, lang: str = "es") -> dict[str, str]:
    """`costText`, `quotaText` y `imagesText` del panel sobre esa respuesta, en node."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")
    windows = re.search(r"const WINDOWS = \[.*?\];", metrics.HTML).group(0)
    prelude = (
        i18n_prelude(lang) + "\nconst F = {format: n => fmtNum(n, 0)};\n"
        "const F1 = {format: n => fmtNum(n, 1)};\n"
        + _extract("const THREAD_TXT = {")
        + ";\n"
        + windows
        + "\n"
    )
    body = (
        f"const j = {json.dumps(stats)};\n"
        "console.log(JSON.stringify({cost: costText(j).join('\\n'), "
        "quota: quotaText(j).join('\\n'), images: imagesText(j).join('\\n')}));\n"
    )
    program = tmp_path / "texts.mjs"
    program.write_text(
        "\n".join([prelude, *(_extract(f) for f in _FUNCTIONS), body]), encoding="utf-8"
    )
    output = subprocess.run(
        [node, str(program)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return json.loads(output.stdout)


# --- La barra y el relleno (REQ-007) -------------------------------------------------------------


def test_the_race_is_closed_by_the_backfill(env, tmp_path):
    """Escenario de la spec: la línea tiene nota del hook pero no el modelo (`caller_src: hook`).
    Primero cuenta como `pendiente`, valorada con el respaldo; tras el relleno, `por relleno`."""
    logs, _home = env
    ts = _now() - timedelta(hours=1)
    _write_log(logs, [_line(ts, caller_src="hook", caller_kind="subagent")])

    bar = _stats()["cost"]["bar"]
    assert bar["pending"] == 1
    assert bar["backfilled"] == 0

    attribution.write_backfill(
        logs,
        f"{ts:%Y%m}",
        {
            "toolu_0000": {
                "caller_model": "claude-opus-5-5",
                "caller_kind": "subagent",
                "caller_effort": "high",
                "n": 40,
                "expiries": 0,
                "match": "exact",
            }
        },
    )
    c = _stats()["cost"]
    assert c["bar"]["backfilled"] == 1
    assert c["bar"]["pending"] == 0
    assert c["n_origin"]["backfill"] == 1
    # 3 000 000 × 100 // 200 = 1 500 000 tokens: $7,50 y $19,50 con N = 40.
    assert c["figure"] == {"low_bound": 7.5, "estimate": 19.5}


def test_api_stats_carries_cost_quota_and_images(env):
    logs, _home = env
    now = _now()
    image = {**IMAGE, "ts": (now - timedelta(minutes=5)).isoformat(timespec="seconds")}
    _write_log(logs, [_line(now - timedelta(minutes=10)), image])
    j = _stats()
    assert j.get("cost") is not None
    assert j.get("images") == {"n": 1, "bytes": 250000, "chars_returned": 800}
    assert j.get("quota", {}).get("five_hour", {}).get("status") == "uncalibrated"
    assert set(j.get("density_table", {}).get("families", {})) == {"new", "previous"}
    # Las claves de siempre siguen ahí: las nuevas son aditivas.
    assert j["total"]["calls"] == 2


# --- La cuota (REQ-054, REQ-058, REQ-060, REQ-061) -----------------------------------------------


def test_the_quota_does_not_depend_on_the_range(env):
    """Tres puntos del statusline que calibran; delegaciones de hace 3 h; el panel mira el mes
    pasado. El % sale de las últimas 5 h, no del rango."""
    logs, _home = env
    now = _now()
    _aggregates(
        logs,
        [_point(now - timedelta(days=d), c) for d, c in ((20, 150.0), (10, 160.0), (2, 170.0))],
    )
    _write_log(logs, [_line(now - timedelta(hours=3))])

    j = _stats(now - timedelta(days=60), now - timedelta(days=35))
    assert j["cost"]["reason"] == "sin delegaciones en el periodo"  # el rango está vacío
    c = j["quota"]
    assert c["five_hour"]["status"] == "calibrated"
    assert (c["five_hour"].get("a_pct") or 0) > 0, c["five_hour"].get("pct_reason")
    # 1 500 000 tokens × $5/MTok = $7,50 de cota baja; mediana(C) = 160 → 4,7 %.
    assert c["five_hour"]["a_pct"] == 4.7
    assert c["five_hour"]["b_pct"] == round(7.5 * (1 + 40 * 0.2 / 5) / 160 * 100, 1)
    assert c["seven_day"]["status"] == "uncalibrated"


def test_an_old_point_expires_without_regenerating(env, tmp_path):
    """Escenario de la spec: tres puntos que calibran, uno con `end` hace 61 días, y el JSON sin
    regenerar: el panel aplica la vigencia al leer."""
    logs, _home = env
    now = _now()
    _aggregates(
        logs,
        [_point(now - timedelta(days=d), c) for d, c in ((61, 150.0), (10, 160.0), (2, 170.0))],
    )
    j = _stats()
    c = j["quota"]
    assert c["five_hour"]["status"] == "uncalibrated"
    assert "faltan 1 puntos" in c["five_hour"]["reason"]
    text = _texts(tmp_path, j)["quota"]
    assert "faltan 1 puntos" in text
    assert "de una ventana de 5 h" not in text  # ningún % sin calibrar (REQ-059)


def test_warning_against_a_rejection(env, tmp_path):
    """REQ-058: calibrado con mediana(C) = 160 y un rechazo vigente con C = 300."""
    logs, _home = env
    now = _now()
    points = [_point(now - timedelta(days=d), c) for d, c in ((20, 150.0), (10, 160.0), (2, 170.0))]
    points.append(_point(now - timedelta(days=5), 300.0, source="rejection"))
    _aggregates(logs, points)
    _write_log(logs, [_line(now - timedelta(hours=1))])
    j = _stats()
    assert j["quota"]["five_hour"]["status"] == "calibrated"  # guarda: el aviso solo va calibrado
    text = _texts(tmp_path, j)["quota"]
    assert "probable uso en otras superficies" in text
    assert "de una ventana de 5 h" in text


def test_a_malformed_point_is_dropped_without_bringing_the_response_down(env):
    """REQ-061 sobre `cost-aggregates.json` editado a mano: los puntos rotos se saltan y cuentan
    como `linea_corrupta` (en su tipo, o en los dos si el tipo no se lee), y los buenos calibran."""
    logs, _home = env
    now = _now()
    good_ones = [
        _point(now - timedelta(days=d), c) for d, c in ((20, 150.0), (10, 160.0), (2, 170.0))
    ]
    without_c = _point(now - timedelta(days=3), 155.0)
    del without_c["C"]
    c_text = {**_point(now - timedelta(days=4), 155.0), "C": "abc"}
    odd_type = {**_point(now - timedelta(days=5), 155.0), "type": "one_month"}
    _aggregates(logs, [*good_ones, without_c, c_text, odd_type, "no soy un punto"])

    r = TestClient(metrics.app, raise_server_exceptions=False).get("/api/stats")
    assert r.status_code == 200
    q = r.json()["quota"]
    assert q["five_hour"]["status"] == "calibrated"
    assert q["five_hour"]["points"] == 3
    assert q["five_hour"]["discards"]["corrupt_line"] == 4
    assert q["seven_day"]["discards"]["corrupt_line"] == 2


def test_discard_reasons_are_said_in_words(tmp_path):
    """Los motivos de descarte llegan como valores de máquina en inglés y el panel los dice en
    palabras, también los tres que antes no tenían rótulo (`overlapping`, `expired`, `reset`).

    Control: mutante «`DISCARD` con la clave vieja `delta_pequeno`» → sale «small delta 1»."""
    discards = {"small_delta": 1, "overlapping": 2, "expired": 3, "reset": 4, "corrupt_line": 5}
    stats = {
        "quota": {
            "five_hour": {
                "status": "uncalibrated",
                "reason": "faltan 3 puntos",
                "points": 0,
                "rejection_points": 0,
                "discards": discards,
                "drift": False,
                "reset": None,
            },
            "has_aggregates": True,
            "command": "local-delegate recompute-cost",
        }
    }
    text = _texts(tmp_path, stats)["quota"]
    assert (
        "descartes: variación pequeña 1, solapado 2, caducado 3, reinicio 4, línea corrupta 5"
        in text
    )


def test_empty_home(env, tmp_path):
    """Escenario «otra máquina sin datos»: ni `~/.claude` ni `cost-aggregates.json`. El coste usa el
    respaldo y el `N` declarado; la cuota dice que no hay datos y qué comando los genera. Y un
    `cost-aggregates.json` corrupto no tumba `/api/stats`."""
    logs, home = env
    assert not (home / ".claude").exists()
    _write_log(logs, [_line(_now() - timedelta(hours=1))])

    j = _stats()
    b = j["cost"]["bar"]
    assert b["pending"] + b["assumed"] == b["valued"] == 1
    assert j["cost"]["n_origin"]["declared"] == 1
    assert j["cost"]["figure"] is not None
    q = j["quota"]
    assert q["five_hour"]["reason"] == "no hay datos de calibración en esta máquina"
    assert q["has_aggregates"] is False
    text = _texts(tmp_path, j)["quota"]
    assert "no hay datos de calibración en esta máquina" in text
    assert "local-delegate recompute-cost" in text

    (logs / recompute.FILE_NAME).write_text("{ esto no es JSON", encoding="utf-8")
    r = TestClient(metrics.app, raise_server_exceptions=False).get("/api/stats")
    assert r.status_code == 200
    assert r.json()["quota"]["five_hour"]["reason"] == "no hay datos de calibración en esta máquina"


# --- Lo que el panel no hace (REQ-012, REQ-073) --------------------------------------------------


def test_the_dashboard_does_not_read_claude(env, monkeypatch):
    """`/api/stats` y `/api/events` con un `~/.claude` sintético con transcripts y registro: ni una
    apertura de fichero cuelga de él."""
    logs, home = env
    claude = home / ".claude"
    (claude / "projects" / "C--proyecto").mkdir(parents=True)
    (claude / "projects" / "C--proyecto" / "session.jsonl").write_text("{}\n", encoding="utf-8")
    (claude / "cuota-statusline.jsonl").write_text("{}\n", encoding="utf-8")
    (claude / "settings.json").write_text('{"cleanupPeriodDays": 90}', encoding="utf-8")
    _write_log(logs, [_line(_now() - timedelta(hours=1), caller_src="hook")])

    reads: list[str] = []
    root = str(claude.resolve()).lower()

    def _write_note(path) -> None:
        try:
            s = str(Path(os.fspath(path)).resolve()).lower()
        except TypeError:
            return  # un descriptor de fichero
        if s.startswith(root):
            reads.append(s)

    open_, io_open = builtins.open, io.open
    path_open, read_text, read_bytes = Path.open, Path.read_text, Path.read_bytes

    def _open(f, *a, **k):
        _write_note(f)
        return open_(f, *a, **k)

    def _io_open(f, *a, **k):
        _write_note(f)
        return io_open(f, *a, **k)

    def _path_open(self, *a, **k):
        _write_note(self)
        return path_open(self, *a, **k)

    def _read_text(self, *a, **k):
        _write_note(self)
        return read_text(self, *a, **k)

    def _read_bytes(self, *a, **k):
        _write_note(self)
        return read_bytes(self, *a, **k)

    monkeypatch.setattr(builtins, "open", _open)
    monkeypatch.setattr(io, "open", _io_open)
    monkeypatch.setattr(pathlib.Path, "open", _path_open)
    monkeypatch.setattr(pathlib.Path, "read_text", _read_text)
    monkeypatch.setattr(pathlib.Path, "read_bytes", _read_bytes)

    # Control positivo: el espía ve una lectura bajo `~/.claude` cuando la hay (la misma lectura
    # pasa por varias capas: `read_text` → `open` → `io.open`, de ahí el conjunto).
    (claude / "settings.json").read_text(encoding="utf-8")
    assert set(reads) == {str((claude / "settings.json").resolve()).lower()}, (
        "el espía no ve las lecturas: el test no comprobaría nada"
    )
    reads.clear()

    client = TestClient(metrics.app)
    assert client.get("/api/stats").status_code == 200
    assert client.get("/api/events").status_code == 200
    assert reads == []


def test_api_stats_opens_no_sockets(env, monkeypatch):
    logs, _home = env
    _write_log(logs, [_line(_now() - timedelta(hours=1)), {**IMAGE, "ts": _now().isoformat()}])
    attempts: list[str] = []
    # El bucle de asyncio en Windows se conecta a sí mismo por loopback (`socketpair`): eso no es
    # salir a la red, y bloquearlo tumbaría el `TestClient` en vez de probar el panel.
    local = {"127.0.0.1", "::1", "localhost", None}

    def _record(name, original, host_of):
        def _fake(*a, **k):
            if host_of(a) in local:
                return original(*a, **k)
            attempts.append(name)
            raise OSError(f"red prohibida en el test: {name}")

        return _fake

    monkeypatch.setattr(
        socket, "getaddrinfo", _record("getaddrinfo", socket.getaddrinfo, lambda a: a[0])
    )
    monkeypatch.setattr(
        socket,
        "create_connection",
        _record("create_connection", socket.create_connection, lambda a: a[0][0]),
    )
    monkeypatch.setattr(
        socket.socket, "connect", _record("connect", socket.socket.connect, lambda a: a[1][0])
    )

    # Control positivo: los registradores ven un intento de verdad.
    # Esperado: 192.0.2.1 es TEST-NET y no responde. Aquí solo cuenta que el registrador
    # haya visto el intento, que es lo que comprueba el assert siguiente.
    with contextlib.suppress(OSError):
        socket.create_connection(("192.0.2.1", 80), timeout=0.01)
    assert attempts == ["create_connection"]
    attempts.clear()

    r = TestClient(metrics.app).get("/api/stats")
    assert r.status_code == 200
    assert r.json()["cost"]["figure"] is not None  # guarda: la tabla se cargó y se usó
    assert attempts == []


def test_forbidden_phrases(env, tmp_path, monkeypatch):
    """REQ-045 sobre el HTML, la respuesta de `/api/stats`, los textos del panel y los tres
    mensajes a Claude de T4 (coletilla, recibo de salida a fichero y `approx_tokens`)."""
    logs, _home = env
    now = _now()
    _write_log(
        logs,
        [_line(now - timedelta(hours=1)), {**IMAGE, "ts": now.isoformat(timespec="seconds")}],
    )
    monkeypatch.setattr(cfg, "FEEDBACK_ENABLED", True)

    html = TestClient(metrics.app).get("/").text
    stats = _stats()
    texts = _texts(tmp_path, stats)
    tail_note = server._savings_feedback(
        4000,
        "chars",
        event=cost.in_flight_row(tool="local_summarize", source="path", path="a.md"),
    )
    image_tail_note = server._savings_feedback(
        250000,
        "image_bytes",
        event=cost.in_flight_row(
            tool="local_describe_image", source="path", path="a.png", input_unit="bytes"
        ),
    )
    receipt = server._write_target(
        tmp_path / "output.py",
        "x = 1\n",
        event=cost.in_flight_row(tool="local_boilerplate", source="inline"),
    )
    extract_source = inspect.getsource(server.local_extract)
    i = extract_source.index('meta["read_server_side"]')
    approx_tokens = extract_source[i : extract_source.index("}", i) + 1]
    assert "approx_tokens" in approx_tokens  # guarda: el recorte encontró el bloque
    assert "tokens de Claude" in tail_note and "tokens de Claude" in receipt  # guarda

    surfaces = {
        "html": html,
        "metrics.HTML": metrics.HTML,
        "/api/stats": json.dumps(stats, ensure_ascii=False),
        "costText": texts["cost"],
        "quotaText": texts["quota"],
        "imagesText": texts["images"],
        "tail_note": tail_note,
        "image_tail_note": image_tail_note,
        "receipt": receipt,
        "approx_tokens": approx_tokens,
    }
    assert "cuota que no gastaste" not in html
    assert "ahorro de cuota" not in html.lower()
    for name, text in surfaces.items():
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in text.lower(), f"«{phrase}» en {name}"
    # El rótulo y la nota de REQ-045 sí están.
    assert "Equivalente estimado a precio de API: entre $" in texts["cost"]
    assert "no es dinero que hayas ahorrado: tu suscripción es de tarifa plana" in (
        texts["cost"].lower()
    )


def test_cost_text_with_the_bar_and_the_fallback(env, tmp_path):
    """node: el rótulo nombra el respaldo con su número, y los supuestos de REQ-044 están todos."""
    logs, _home = env
    now = _now()
    old = now - timedelta(days=45)  # sin relleno y fuera del plazo: `supuesto`
    _write_log(logs, [_line(old, 0), _line(now - timedelta(hours=1), 1)])
    j = _stats(now - timedelta(days=60), now)
    assert j["cost"]["bar"]["assumed"] == 1  # guarda: la fila vieja cayó donde debía
    text = _texts(tmp_path, j)["cost"]
    assert "2 de 2 con modelo supuesto: Opus 5.5 en subagente" in text
    assert "cota baja con estos supuestos" in text
    assert "neto de la respuesta de la tool" in text.lower()
    assert "si Claude hubiera leído el fichero entero una vez con Read" in text
    assert "No descuenta las relecturas del mismo fichero (medidas entre ~3 % y ~30 %)" in text
    assert "Precios de la tabla del paquete del 20" in text
    assert (
        "Relecturas (N): 0 del relleno, 0 de la mediana de su grupo, 2 con el valor declarado"
        in text
    )


def test_families_are_said_in_words(env, tmp_path):
    """Las familias de tokenizador llegan como `new` y `previous` y el panel las dice en palabras.

    Control: mutante «`FAMILY` con la clave vieja `nueva`» → sale «new 2»."""
    logs, _home = env
    _write_log(logs, [_line(_now() - timedelta(hours=1))])
    j = _stats()
    assert j["cost"]["density"]["families"] == {"new": 1}  # guarda: la fila trae la familia
    j["cost"]["density"]["families"] = {"new": 2, "previous": 1}
    text = _texts(tmp_path, j)["cost"]
    assert "familia de tokenizador (nueva 2, anterior 1)" in text


def test_a_row_without_saving_shows_no_dollars(env, tmp_path):
    """Arreglo tras T10: una fila del desglose con T ≤ 0 (la tool devolvió más de lo que leyó) dice
    «sin ahorro» en vez de «$0,00 $0,00». node, sobre las filas de `/api/stats`."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node no está en el PATH")
    logs, _home = env
    now = _now()
    negative = _line(
        now - timedelta(hours=2),
        1,
        chars_in=100,
        chars_out=500,
        caller_model="claude-sonnet-5-5",
        caller_kind="subagent",
        caller_effort="medium",
    )
    _write_log(logs, [_line(now - timedelta(hours=1), 0), negative])
    breakdown = _stats(now - timedelta(days=1), now)["cost"]["breakdown"]
    by_t = sorted(breakdown, key=lambda g: g["T"])
    assert len(by_t) == 2 and by_t[0]["T"] < 0 < by_t[1]["T"]  # guarda: una de cada
    assert by_t[0]["estimate"] == 0.0  # sin signo: redondea a cero

    program = tmp_path / "cells.mjs"
    program.write_text(
        "\n".join(
            [
                i18n_prelude(),
                *(_extract(f) for f in ("function fmtNum(", "function dollars(")),
                _extract("function costCells("),
                f"const rowsIn = {json.dumps(by_t)};",
                "console.log(JSON.stringify(rowsIn.map(costCells)));",
            ]
        ),
        encoding="utf-8",
    )
    output = subprocess.run(
        [node, str(program)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    without_saving, with_saving = json.loads(output.stdout)
    assert "sin ahorro" in without_saving
    assert "$" not in without_saving
    assert "sin ahorro" not in with_saving
    assert with_saving.count("$") == 2
