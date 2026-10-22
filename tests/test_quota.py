"""Puntos de calibración de la cuota y su criterio (REQ-051 a REQ-057, REQ-061; T5).

Registro del statusline y transcripts SINTÉTICOS. Las cifras de `criterio` son las de
`insumos/scripts/criterio.py`, citadas en el escenario de la spec.
"""

from __future__ import annotations

import json
from datetime import timedelta

from test_transcripts import (
    BASE,
    main_transcript,
    request_entry,
    subagent,
    synthetic,
    ts,
    write_jsonl,
)

from local_delegate import i18n, quota, recompute, transcripts

R1 = "2026-10-01T17:00:00+00:00"  # resets de 5 h (valor opaco: solo agrupa)
R7 = "2026-10-05T00:00:00+00:00"


def row(s, session, five, cost, *, reset=R1, seven=1, reset7=R7) -> dict:
    return {
        "ts": ts(s),
        "session_id": session,
        "model": "claude-opus-5-5",
        "five_hour": five,
        "five_reset": reset,
        "seven_day": seven,
        "seven_reset": reset7,
        "cost_usd": cost,
    }


def _lines(rows: list) -> list[str]:
    return [x if isinstance(x, str) else json.dumps(x) for x in rows]


def points_of(rows: list, requests: list | None = None):
    by_type, sessions, d0 = quota.sanitize(_lines(rows))
    points, d1 = quota.statusline_points(by_type, sessions, requests or [])
    return points, d0, d1


def _point(end_days: float, c: float, now, *, kind="five_hour", source="statusline") -> dict:
    end = now - timedelta(days=end_days)
    return {
        "source": source,
        "type": kind,
        "start": (end - timedelta(hours=4)).isoformat(),
        "end": end.isoformat(),
        "delta_pct": 40,
        "delta_usd": c * 0.4,
        "C": c,
        "marks": [],
        "unpriced_requests": None,
    }


# --- REQ-052: el registro del statusline --------------------------------------------------


def test_five_rows_are_one_point():
    rows = [row(100 * i, "A", 10 * (i + 1), float(i + 1)) for i in range(5)]
    points, _, _ = points_of(rows)
    points = [p for p in points if p["type"] == "five_hour"]
    assert len(points) == 1
    p = points[0]
    assert p["delta_pct"] == 40
    assert p["delta_usd"] == 4.0
    assert p["C"] == 10.0
    assert p["start"] == (BASE).isoformat()
    assert quota.MARK_OTHER_SURFACES in p["marks"]


def test_parallel_sessions():
    """B (5 → 45 %) gana a A (10 → 30 %); el Δ$ suma los incrementos de las DOS sesiones."""
    rows = [
        row(0, "B", 5, 1.0),
        row(10, "A", 10, 2.0),
        row(50, "A", 30, 4.0),
        row(100, "B", 45, 5.0),
    ]
    points, _, _ = points_of(rows)
    (p,) = [p for p in points if p["type"] == "five_hour"]
    TOTAL = 4.0 + 2.0
    assert p["delta_usd"] == TOTAL
    assert p["delta_pct"] == 40


def test_discards(tmp_path):
    _, _, d = points_of([row(0, "A", 10, 1.0), row(100, "A", 15, 2.0)])
    assert d["five_hour"].get("small_delta") == 1

    _, _, d = points_of([row(0, "A", 10, 3.0), row(100, "A", 40, 3.0)])
    assert d["five_hour"].get("no_local_use") == 1

    # Una sesión que no está en el registro (`claude -p`) pidió dentro del intervalo.
    claude = tmp_path / "claude"
    write_jsonl(
        main_transcript(claude, session="ajena"), [request_entry(50, "x1", session="ajena")]
    )
    requests = list(transcripts.read(claude / "projects").requests.values())
    points, _, d = points_of([row(0, "A", 10, 1.0), row(100, "A", 40, 2.0)], requests)
    assert d["five_hour"].get("contaminated") == 1
    assert [p for p in points if p["type"] == "five_hour"] == []

    # `/clear`: el coste baja; el incremento es el valor nuevo y el punto lleva la marca.
    points, _, _ = points_of([row(0, "A", 10, 5.0), row(50, "A", 20, 6.0), row(100, "A", 40, 1.0)])
    (p,) = [p for p in points if p["type"] == "five_hour"]
    assert p["delta_usd"] == 2.0
    assert quota.MARK_RESET in p["marks"]

    # Dos ventanas que se solapan: se queda la de mayor Δ%.
    points, _, _ = points_of(
        [
            row(0, "A", 10, 1.0, reset="r5"),
            row(200, "A", 40, 2.0, reset="r5"),
            row(100, "B", 10, 1.0, reset="r6"),
            row(300, "B", 30, 2.0, reset="r6"),
        ]
    )
    points, d = quota.drop_overlapping([p for p in points if p["type"] == "five_hour"])
    assert d["five_hour"].get("overlapping") == 1
    assert [p["delta_pct"] for p in points] == [30]


def test_sanitize_and_corrupt_lines(tmp_path):
    rows = [
        row(0, "A", 120, 1.0),
        row(50, "A", 10, 1.0, seven="abc"),
        "{esto no es json",
        row(100, "A", 40, 2.0),
    ]
    escaped = None
    try:
        _, _, d = quota.sanitize(_lines(rows))
    except Exception as e:  # una línea rota nunca rompe el comando (REQ-061)
        escaped, d = e, {"five_hour": {}, "seven_day": {}}
    assert not escaped
    assert d["five_hour"].get("out_of_range") == 1
    assert d["seven_day"].get("out_of_range") == 1
    assert d["five_hour"].get("corrupt_line") == 1

    # Una línea rota en un transcript: se salta y cuenta, y el comando sigue.
    claude, log = tmp_path / "claude", tmp_path / "log"
    write_jsonl(main_transcript(claude), [request_entry(0, "m0"), '{"type": "assistant", roto'])
    escaped = None
    try:
        recompute.run(claude, log, now=BASE + timedelta(days=1))
        aggregates = recompute.read_aggregates(log) or {}
    except Exception as e:
        escaped, aggregates = e, {}
    assert not escaped
    assert (aggregates.get("discards") or {}).get("five_hour", {}).get("corrupt_line") == 1


def test_a_malformed_previous_point_does_not_break_the_command(tmp_path):
    """REQ-061 en `recompute-cost`: un punto del JSON anterior sin `delta_pct` (editado a mano)
    se salta y cuenta como `linea_corrupta`, en vez de tumbar `quitar_solapados`."""
    claude, log = tmp_path / "claude", tmp_path / "log"
    write_jsonl(main_transcript(claude), [request_entry(0, "m0")])
    broken = {
        "source": "statusline",
        "type": "five_hour",
        "start": (BASE - timedelta(hours=4)).isoformat(),
        "end": BASE.isoformat(),
        "C": 150.0,
    }
    recompute.write_aggregates(log, {"points": [broken]})
    recompute.run(claude, log, now=BASE + timedelta(days=1))
    aggregates = recompute.read_aggregates(log) or {}
    assert aggregates["points"] == []
    assert aggregates["discards"]["five_hour"]["corrupt_line"] == 1
    assert aggregates["discards"]["seven_day"].get("corrupt_line", 0) == 0


# --- REQ-051: rechazos --------------------------------------------------------------------


def test_duplicate_rejections_are_one_point(tmp_path):
    """11 registros del mismo rechazo de 5 h, en el principal y en dos subagentes: un punto.

    Δ$ = las peticiones de [resetsAt − 5 h, primer rechazo]: 1 M de entrada de Opus 5.5 ($4) y
    1 M escritos a 1 h ($8) = $12. Quedan fuera una de antes del intervalo y una posterior.
    """
    claude = tmp_path / "claude"
    reset = int((BASE + timedelta(hours=3)).timestamp())
    rejection = {"status": "rejected", "rateLimitType": "five_hour", "resetsAt": reset}

    def rejections(s0: int, k: int, prefix: str) -> list:
        return [
            synthetic(s0 + i, f"{prefix}{i}", quota=[rejection] if i % 2 else rejection)
            for i in range(k)
        ]

    write_jsonl(
        main_transcript(claude),
        [
            request_entry(-3 * 3600, "antes", usage={"input_tokens": 1_000_000}),
            request_entry(0, "p1", usage={"input_tokens": 1_000_000}),
            request_entry(
                10, "p2", usage={"cache_creation": {"ephemeral_1h_input_tokens": 1_000_000}}
            ),
            request_entry(2000, "despues", usage={"input_tokens": 1_000_000}),
        ]
        + rejections(1000, 5, "r"),
    )
    write_jsonl(subagent(claude, "s1"), rejections(1100, 3, "u"))
    write_jsonl(subagent(claude, "s2"), rejections(1200, 3, "v"))
    index = transcripts.read(claude / "projects")
    rejections_ = quota.rejection_points(index.rejections, index.requests.values())
    assert len(rejections_) == 1
    p = rejections_[0]
    assert p["delta_usd"] == 12.0
    assert p["end"] == (BASE + timedelta(seconds=1000)).isoformat()
    assert p["marks"] == [quota.MARK_LOW_BOUND, quota.MARK_CHECK_ONLY]
    assert p["unpriced_requests"] == 0
    e = quota.status({"points": rejections_}, BASE + timedelta(days=1))
    assert e["five_hour"]["status"] == "uncalibrated"
    assert e["five_hour"]["rejection_points"] == 1


# --- REQ-055 y REQ-056: criterio ----------------------------------------------------------


def test_spec_criterion():
    r = quota.criterion([150, 160, 170, 175])
    assert (r["status"], r["dispersion"]) == ("calibrated", 0.078)
    r = quota.criterion([150, 160, 170, 175, 300])
    assert (r["status"], r["dispersion"]) == ("calibrated", 0.072)
    r = quota.criterion([100, 160, 250])
    assert r["status"] == "uncalibrated"
    assert r["reason"] == "dispersión 51,2 % ≥ 25 %"
    r = quota.criterion([150, 160, 170, 175, 230, 240])
    assert (r["status"], r["drift"]) == ("uncalibrated", True)
    assert r["reason"] == "faltan 1 puntos del statusline"
    r = quota.criterion([150, 160, 170, 175, 230, 100])  # sentidos opuestos: no es deriva
    assert r["status"] == "calibrated"
    assert r["drift"] is False
    r = quota.criterion([150, 160, 170, 175, 230, 240, 235])
    assert (r["status"], r["median_C"]) == ("calibrated", 235)


# --- REQ-054 y REQ-057: vigencia y reinicio ------------------------------------------------


def test_a_61_day_old_point_does_not_count():
    now = BASE
    sources = {"transcripts": True, "statusline": True}
    fresh = [_point(20, 150, now), _point(10, 160, now), _point(5, 170, now)]
    guard = quota.status({"points": fresh, "sources": sources}, now)["five_hour"]
    assert guard["status"] == "calibrated"  # sin el punto viejo, calibra

    with_old = [_point(61, 150, now), _point(10, 160, now), _point(5, 170, now)]
    r = quota.status({"points": with_old, "sources": sources}, now)["five_hour"]
    assert r["status"] == "uncalibrated"
    assert r["reason"] == "faltan 1 puntos del statusline"
    assert r["discards"].get("expired") == 1


def test_manual_reset(tmp_path):
    now = BASE
    points = [_point(5, 150, now)]
    assert quota.current_points(points, now) == points  # guarda
    current = quota.current_points(points, now, (now - timedelta(days=1)).isoformat())
    assert current == []

    # El comando guarda la fecha del reinicio y conserva la del otro tipo.
    log = tmp_path / "log"
    recompute.run(tmp_path / "claude", log, now=now, reset="five_hour")
    recompute.run(tmp_path / "claude", log, now=now + timedelta(hours=1))
    restarts = (recompute.read_aggregates(log) or {}).get("resets")
    assert restarts == {"five_hour": now.isoformat(timespec="seconds"), "seven_day": None}


def test_without_sources_it_says_so():
    """REQ-061: sin registro ni transcripts, «no hay datos de calibración en esta máquina»."""
    now = BASE
    with_nothing = {"points": [], "sources": {"transcripts": False, "statusline": False}}
    assert quota.status(with_nothing, now)["five_hour"]["reason"] == i18n.t(quota.NO_DATA)
    assert quota.status(None, now)["seven_day"]["reason"] == i18n.t(quota.NO_DATA)
    transcripts_only = {"points": [], "sources": {"transcripts": True, "statusline": False}}
    assert quota.status(transcripts_only, now)["five_hour"]["reason"] == i18n.t(quota.NO_STATUSLINE)
