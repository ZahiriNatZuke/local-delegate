"""`local-delegate recompute-cost`: privacidad, solo lectura, fusión y agregados (T5).

HOME de Claude Code, registro del statusline y log de uso SINTÉTICOS en `tmp_path`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

from test_transcripts import (
    BASE,
    OPUS,
    log_line,
    main_transcript,
    request_entry,
    result_entry,
    subagent,
    synthetic,
    ts,
    write_jsonl,
    write_log,
)

from local_delegate import cli, config, recompute

NOW = BASE + timedelta(days=1)
MONTH = "202610"


def _delegation_with_n(
    path: Path, tid: str, n: int, *, session: str = "sesion-sintetica-0001", s0: float = 0
) -> list:
    """Un hilo con una delegación y `n` peticiones después de su resultado (sin caducidades)."""
    lines = [
        request_entry(
            s0, f"{tid}-0", session=session, tool_use=(tid, "local_summarize", "docs/a.md")
        ),
        result_entry(s0 + 1, tid, session=session),
    ]
    lines += [request_entry(s0 + 2 + i, f"{tid}-{i + 1}", session=session) for i in range(n)]
    return write_jsonl(path, lines)


def _texts(log: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(log.glob("*.json"))}


# --- REQ-072: privacidad --------------------------------------------------------------------


def test_privacy(tmp_path):
    MARKER = "MARCADORA-7f3a"
    SESSION = "sesion-marcadora-9c41"
    TOOL_USE_ID = "toolu_privado01"
    claude, log = tmp_path / "claude", tmp_path / "log"
    project = f"D--{MARKER}-proyecto"
    path = f"{MARKER}/doc.md"
    reset = int((BASE + timedelta(hours=3)).timestamp())
    write_jsonl(
        main_transcript(claude, session=SESSION, project=project),
        [
            {
                "type": "user",
                "timestamp": ts(-5),
                "sessionId": SESSION,
                "message": {"role": "user", "content": f"resume {MARKER} por favor"},
            },
            request_entry(
                0, "m0", session=SESSION, tool_use=(TOOL_USE_ID, "local_summarize", path)
            ),
            result_entry(1, TOOL_USE_ID, f"el resumen de {MARKER}", session=SESSION),
            request_entry(2, "m1", session=SESSION, usage={"input_tokens": 1000}),
            synthetic(
                5,
                "s1",
                session=SESSION,
                quota={"status": "rejected", "rateLimitType": "five_hour", "resetsAt": reset},
            ),
            {
                "type": "cost-state",
                "sessionId": SESSION,
                "startTime": ts(0),
                "modelUsage": {OPUS: {"inputTokens": 1000, "costUSD": 0.004}},
            },
        ],
    )
    write_jsonl(
        claude / "cuota-statusline.jsonl",
        [
            {"ts": ts(0), "session_id": SESSION, "five_hour": 10, "five_reset": "r", "cost_usd": 1},
            {"ts": ts(9), "session_id": SESSION, "five_hour": 40, "five_reset": "r", "cost_usd": 3},
        ],
    )
    write_log(
        log,
        [log_line(1, path=path, tool_use_id=TOOL_USE_ID), log_line(1, path=path)],
    )
    recompute.run(claude, log, now=NOW)

    texts = _texts(log)
    assert recompute.FILE_NAME in texts
    assert f"attribution-{MONTH}.json" in texts  # guarda: el relleno se escribió
    all_json_text = "\n".join(texts.values())
    assert MARKER not in all_json_text
    assert SESSION not in all_json_text
    cost_aggregates_text = texts[recompute.FILE_NAME]
    assert TOOL_USE_ID not in cost_aggregates_text
    aggregates = json.loads(cost_aggregates_text)
    assert aggregates["points"]  # guarda: había algo que escribir


# --- REQ-074: idempotente y de solo lectura -------------------------------------------------


def _tree_snapshot(root: Path) -> list[tuple]:
    return sorted(
        (
            str(p.relative_to(root)),
            p.stat().st_size,
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).hexdigest(),
        )
        for p in root.rglob("*")
        if p.is_file()
    )


def _without_dates(aggregates: dict) -> dict:
    copied = json.loads(json.dumps(aggregates))
    copied.pop("generated", None)
    if isinstance(copied.get("check"), dict):
        copied["check"].pop("date", None)
    return copied


def test_idempotent_and_read_only(tmp_path):
    claude, log = tmp_path / "claude", tmp_path / "log"
    (claude).mkdir()
    (claude / "settings.json").write_text('{"cleanupPeriodDays": 60}', encoding="utf-8")
    _delegation_with_n(subagent(claude, "a1"), "toolu_i1", 4)
    write_jsonl(
        claude / "cuota-statusline.jsonl",
        [
            {"ts": ts(0), "session_id": "s", "five_hour": 10, "five_reset": "r", "cost_usd": 1},
            {"ts": ts(90), "session_id": "s", "five_hour": 30, "five_reset": "r", "cost_usd": 2},
        ],
    )
    write_log(log, [log_line(1, tool_use_id="toolu_i1"), log_line(1)])
    before = _tree_snapshot(claude)

    recompute.run(claude, log, now=NOW)
    first = _texts(log)
    recompute.run(claude, log, now=NOW + timedelta(minutes=1))
    second = _texts(log)

    after = _tree_snapshot(claude)
    assert after == before
    assert set(first) == set(second) == {recompute.FILE_NAME, f"attribution-{MONTH}.json"}
    assert first[f"attribution-{MONTH}.json"] == second[f"attribution-{MONTH}.json"]
    a1, a2 = json.loads(first[recompute.FILE_NAME]), json.loads(second[recompute.FILE_NAME])
    assert a1["generated"] != a2["generated"]
    assert _without_dates(a1) == _without_dates(a2)


# --- REQ-042 (2): agregados de N --------------------------------------------------------------


def test_the_n_aggregates_do_not_count_excluded_ones(tmp_path):
    """Una delegación de Claude Code (N = 40), una del cliente `mcp` (N = 60) y una de un banco
    (N = 70): el agregado solo tiene el 40."""
    claude, log = tmp_path / "claude", tmp_path / "log"
    _delegation_with_n(subagent(claude, "a1"), "toolu_cc", 40)
    _delegation_with_n(subagent(claude, "a2"), "toolu_mcp", 60)
    _delegation_with_n(
        subagent(claude, "a3", project="C--Users-x-AppData-Local-Temp-banco"), "toolu_bk", 70
    )
    write_log(
        log,
        [
            log_line(1, tool_use_id="toolu_cc"),
            log_line(1, tool_use_id="toolu_mcp", client="mcp"),
            log_line(1, tool_use_id="toolu_bk"),
        ],
    )
    recompute.run(claude, log, now=NOW)
    aggregates = recompute.read_aggregates(log)
    assert aggregates["n_by_month"][MONTH]["claude-opus-5-5|subagent"] == [40]


# --- REQ-071: fundir, no sobrescribir ---------------------------------------------------------


def test_a_point_survives_the_deleted_transcript(tmp_path):
    claude, log = tmp_path / "claude", tmp_path / "log"
    reset = int((BASE + timedelta(hours=3)).timestamp())
    transcript = write_jsonl(
        main_transcript(claude),
        [
            request_entry(0, "m0", usage={"input_tokens": 1_000_000}),
            synthetic(
                5,
                "s1",
                quota={"status": "rejected", "rateLimitType": "five_hour", "resetsAt": reset},
            ),
        ],
    )
    recompute.run(claude, log, now=NOW)
    (point,) = recompute.read_aggregates(log)["points"]
    assert point["source"] == "rejection"

    transcript.unlink()  # Claude Code lo borra a los `H` días
    recompute.run(claude, log, now=NOW + timedelta(days=1))
    aggregates = recompute.read_aggregates(log)
    assert point in aggregates["points"]

    # …hasta que caduca (60 días).
    recompute.run(claude, log, now=NOW + timedelta(days=62))
    assert recompute.read_aggregates(log)["points"] == []


def test_an_old_month_is_not_recomputed(tmp_path):
    """Agosto terminó hace más de 30 días: se conserva lo guardado aunque hoy saliera otra cosa."""
    claude, log = tmp_path / "claude", tmp_path / "log"
    claude.mkdir()
    (claude / "settings.json").write_text('{"cleanupPeriodDays": 90}', encoding="utf-8")
    _delegation_with_n(subagent(claude, "a1"), "toolu_ago", 7, s0=-41 * 86400)
    write_log(log, [log_line(-41 * 86400 + 1, tool_use_id="toolu_ago")], month="202608")
    PREVIOUS = {"claude-opus-5|main": [127]}
    log.mkdir(exist_ok=True)
    recompute.write_aggregates(log, {"version": 1, "n_by_month": {"202608": PREVIOUS}})

    recompute.run(claude, log, now=NOW + timedelta(days=5))  # 2026-10-07
    aggregates = recompute.read_aggregates(log)
    assert aggregates["n_by_month"]["202608"] == PREVIOUS

    # Guarda: sin lo previo, ese mes sí sale del relleno (el caso podía dar otra cosa).
    (log / recompute.FILE_NAME).unlink()
    recompute.run(claude, log, now=NOW + timedelta(days=5))
    assert recompute.read_aggregates(log)["n_by_month"]["202608"] == {f"{OPUS}|subagent": [7]}


def test_saves_the_cleanup_period(tmp_path):
    claude, log = tmp_path / "claude", tmp_path / "log"
    claude.mkdir()
    (claude / "settings.json").write_text('{"cleanupPeriodDays": 90}', encoding="utf-8")
    recompute.run(claude, log, now=NOW)
    aggregates = recompute.read_aggregates(log)
    assert aggregates.get("cleanup_days") == 90


def test_without_transcripts_it_does_not_backfill(tmp_path):
    """Otra máquina (la Mac, un CI): sin `projects` no se escribe ningún relleno, y las fuentes
    dicen que no hay datos."""
    claude, log = tmp_path / "claude", tmp_path / "log"
    write_log(log, [log_line(1)])
    summary = recompute.run(claude, log, now=NOW)
    assert list(log.glob("attribution-*.json")) == []
    aggregates = recompute.read_aggregates(log)
    assert aggregates["sources"] == {"transcripts": False, "statusline": False}
    assert aggregates["check"] is None
    assert summary["quota"] == {"five_hour": "uncalibrated", "seven_day": "uncalibrated"}


# --- REQ-070: el subcomando -------------------------------------------------------------------


def test_the_cli_launches_it(tmp_path, monkeypatch, capsys):
    claude, log = tmp_path / "claude", tmp_path / "log"
    _delegation_with_n(subagent(claude, "a1"), "toolu_cli", 3)
    monkeypatch.setattr(config, "LOG_DIR", log)
    try:
        code = cli.run(["recompute-cost", "--claude-dir", str(claude)])
    except SystemExit as e:
        code = e.code
    output = capsys.readouterr().out
    assert code == 0
    assert (log / recompute.FILE_NAME).is_file()
    assert "Plazo de borrado" in output
    assert str(tmp_path) not in output  # el resumen da conteos, no rutas


def test_the_n_aggregates_do_not_count_rows_in_a_window(tmp_path):
    """test-windows-out-of-metrics, REQ-015. La misma delegación cuenta sin ventana y deja de
    contar con ella: el test comprueba algo en los dos sentidos.
    Control: mutante «`test_reason` ignora `test_window`» → el agregado sigue con el 50."""
    from local_delegate import test_windows

    claude, log = tmp_path / "claude", tmp_path / "log"
    _delegation_with_n(subagent(claude, "a1"), "toolu_cc", 40)
    _delegation_with_n(subagent(claude, "a2"), "toolu_win", 50, s0=500)
    write_log(
        log,
        [log_line(1, tool_use_id="toolu_cc"), log_line(501, tool_use_id="toolu_win")],
    )
    recompute.run(claude, log, now=NOW)
    without_window = recompute.read_aggregates(log)["n_by_month"][MONTH]["claude-opus-5-5|subagent"]
    assert sorted(without_window) == [40, 50]
    start = BASE + timedelta(seconds=500)
    test_windows.add(log, start, start + timedelta(seconds=10), "prueba")
    recompute.run(claude, log, now=NOW)
    with_window = recompute.read_aggregates(log)["n_by_month"][MONTH]["claude-opus-5-5|subagent"]
    assert with_window == [40]


def test_the_summary_states_the_quota_status_in_words():
    """`quota.status` da `calibrated|uncalibrated` (valor de máquina); la terminal lo dice en
    español, sin colar el valor en inglés en la prosa."""
    summary = {
        "cleanup_days": 30,
        "transcripts": 0,
        "corrupt_lines": 0,
        "backfilled_lines": 0,
        "matches": {},
        "n_cases": 0,
        "check": None,
        "points": {},
        "discards": {},
        "quota": {"five_hour": "calibrated", "seven_day": "uncalibrated"},
    }
    text = recompute.summary_text(summary)
    assert "Cuota five_hour: calibrada;" in text
    assert "Cuota seven_day: sin calibrar;" in text
    assert "uncalibrated" not in text


def test_the_summary_states_the_matches_with_the_usual_labels():
    """`matches` usa claves de máquina en inglés; la terminal conserva los rótulos de la 0.34.0."""
    summary = {
        "cleanup_days": 30,
        "transcripts": 0,
        "corrupt_lines": 0,
        "backfilled_lines": 4,
        "matches": {"ambiguous": 1, "exact": 2, "no_match": 0, "window": 1},
        "n_cases": 0,
        "check": None,
        "points": {},
        "discards": {},
        "quota": {"five_hour": "calibrated", "seven_day": "calibrated"},
    }
    text = recompute.summary_text(summary)
    assert "(ambiguo: 1, exacto: 2, sin_cruce: 0, ventana: 1)" in text
    assert "no_match" not in text
