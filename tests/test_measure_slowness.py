"""El control de lentitud de REQ-025 (`scripts/measure_slowness.py`), con datos sinteticos.

El script va a decidir si el umbral de lentitud se queda en 0,5 y si la referencia de velocidad va
por tramos. Un script que cuenta mal parece una medida, asi que cada pieza de la regla tiene un
guion cuyo resultado cambia si la pieza se quita. Cada guion esta pensado para que su mutante
**mute**: la mediana es robusta, y un guion con pocos eventos «viejos» no cambia la mediana de toda
la historia aunque la ventana no exista.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "measure_slowness", ROOT / "scripts" / "measure_slowness.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_slowness"] = module
    spec.loader.exec_module(module)
    return module


ml = _load()

MODEL = "modelo-a"


def _ev(i: int, tok_s: float, *, tokens_out: int = 100, tokens_in: int = 500, **extra) -> dict:
    return {
        "id": i,
        "ts": float(i),
        "modelo": MODEL,
        "tok_s": tok_s,
        "tokens_out": tokens_out,
        "tokens_in": tokens_in,
        **extra,
    }


# ---------------------------------------------------------------------------
# La regla: una pieza por test
# ---------------------------------------------------------------------------


def test_window_of_50_median_uses_last_50() -> None:
    # 31 eventos viejos a 100 tok/s y 28 nuevos a 40. La ventana de los 50 ultimos del 60.º evento
    # tiene 22 viejos y 28 nuevos (mediana 40); la historia entera tiene 31 viejos de 59 (mediana
    # 100). Con solo 10 viejos la mediana de toda la historia tambien daria 40 y el mutante no
    # mutaria.
    events = [_ev(i, 100.0) for i in range(31)] + [_ev(i, 40.0) for i in range(31, 59)]
    events.append(_ev(59, 40.0))
    result = ml.compute_slowness(events)
    assert len(result) == 60
    ref = result[59]["ref"]
    assert ref == 40.0
    assert result[59]["pace_rel"] == 1.0
    assert result[59]["slow"] is False


def test_minimum_10_event_10_has_no_reference_and_11_does() -> None:
    events = ml.compute_slowness([_ev(i, 40.0) for i in range(11)])
    assert events[9].get("pace_rel") is None
    assert "ref" not in events[9] and "slow" not in events[9]
    assert events[10]["pace_rel"] == 1.0
    assert events[10]["slow"] is False


def test_tokens_out_below_8_not_in_window() -> None:
    # 12 eventos buenos a 40 tok/s y 15 de 3 tokens a 5 tok/s: sin el filtro, los cortos son mayoria
    # de la ventana y arrastran la mediana a 5.
    events = [_ev(i, 40.0) for i in range(12)]
    events += [_ev(i, 5.0, tokens_out=3) for i in range(12, 27)]
    events.append(_ev(27, 40.0))
    result = ml.compute_slowness(events)
    ref = result[27]["ref"]
    assert ref == 40.0
    assert all("pace_rel" not in e for e in result[12:27])  # los cortos no se evaluan


def test_event_with_exactly_8_tokens_is_included() -> None:
    events = [_ev(i, 40.0, tokens_out=8) for i in range(10)] + [_ev(10, 40.0)]
    assert ml.compute_slowness(events)[10]["ref"] == 40.0


def test_reference_does_not_look_ahead() -> None:
    # Ids en orden temporal; la lista llega desordenada. El 12.º va a 10 tok/s tras 12 a 40.
    sorted_ones = [_ev(i, 40.0) for i in range(12)] + [_ev(12, 10.0)]
    unordered = [sorted_ones[i] for i in (7, 12, 0, 3, 11, 5, 1, 9, 2, 10, 4, 8, 6)]
    result = ml.compute_slowness(unordered)
    marked = [e["id"] for e in result if e.get("slow")]
    assert marked == [12]
    assert [e["id"] for e in result] == list(range(13))


def test_failed_event_not_in_normal_speed() -> None:
    events = [_ev(i, 40.0) for i in range(10)]
    events += [_ev(i, 5.0, ok=False) for i in range(10, 25)]
    events.append(_ev(25, 40.0))
    result = ml.compute_slowness(events)
    assert result[25]["ref"] == 40.0
    assert "pace_rel" not in result[12]  # el fallido tampoco se evalua


def test_each_model_has_its_window() -> None:
    slow_ones = [{**_ev(i, 100.0), "modelo": "rapido"} for i in range(12)]
    slow_ones += [_ev(100 + i, 10.0) for i in range(12)]
    result = ml.compute_slowness(slow_ones)
    assert not any(e.get("slow") for e in result)  # 10 tok/s es normal para modelo-a


def test_threshold_is_strict() -> None:
    base = [_ev(i, 40.0) for i in range(10)]
    exact = ml.compute_slowness([*base, _ev(10, 20.0)])[10]  # ritmo 0,50 exacto
    below = ml.compute_slowness([*base, _ev(10, 19.6)])[10]  # ritmo 0,49
    assert exact["pace_rel"] == 0.5 and exact["slow"] is False
    assert below["pace_rel"] == 0.49 and below["slow"] is True


def test_by_spans_12k_event_at_18_tok_s_not_slow() -> None:
    # Cortos (< 2k) a 40 tok/s y largos (> 10k) a 26. Con una sola referencia, la mediana la ponen
    # los cortos (mayoria) y el evento largo a 18 sale a 0,45 (lento con el umbral por defecto,
    # 0,5); por tramos se compara con los largos (mediana 26) y sale a 0,69: no es lento.
    events = [_ev(i, 40.0, tokens_in=500) for i in range(20)]
    events += [_ev(20 + i, 26.0, tokens_in=12_000) for i in range(12)]
    events.append(_ev(32, 18.0, tokens_in=12_000))
    slow = ml.compute_slowness(events, by_spans=True)[-1]["slow"]
    assert not slow
    one_item = ml.compute_slowness(events, by_spans=False)[-1]
    assert one_item["slow"] is True


def test_by_spans_each_span_needs_its_own_minimum() -> None:
    events = [_ev(i, 40.0, tokens_in=500) for i in range(20)]
    events += [_ev(20 + i, 26.0, tokens_in=12_000) for i in range(9)]
    events.append(_ev(29, 5.0, tokens_in=12_000))  # solo 9 largos antes: sin referencia
    result = ml.compute_slowness(events, by_spans=True)
    assert "pace_rel" not in result[-1]


@pytest.mark.parametrize(
    ("tokens", "span"),
    [
        (0, "<2k"),
        (1_999, "<2k"),
        (2_000, "2k-10k"),
        (10_000, "2k-10k"),
        (10_001, ">10k"),
        (None, None),
    ],
)
def test_span_limits(tokens: int | None, span: str | None) -> None:
    assert ml.span_of(tokens) == span


@pytest.mark.parametrize(
    ("short", "long_one", "expected"),
    [
        (40.0, 30.0, "una referencia"),  # 0,75 exacto: no es menor
        (40.0, 29.9, "por tramos"),
        (40.0, None, "una referencia"),
        (None, 20.0, "una referencia"),
    ],
)
def test_reference_decision(short, long_one, expected) -> None:
    assert ml.decide_reference({"<2k": short, ">10k": long_one}) == expected


# ---------------------------------------------------------------------------
# Datos: cruce con el log y agrupacion por evento
# ---------------------------------------------------------------------------

T0 = datetime(2026, 10, 1, tzinfo=UTC).timestamp()


def _row(
    id_: int,
    end: float,
    *,
    model: str = MODEL,
    output: int = 100,
    tps: float = 40.0,
    entry: int = 500,
    dur: float = 8.0,
) -> dict:
    return {
        "id": id_,
        "fin": end,
        "modelo": model,
        "entrada": entry,
        "salida": output,
        "tps": tps,
        "dur": dur,
    }


def _call(end: float, *, latency: float = 10.0, model: str = MODEL, ok: bool = True) -> dict:
    return {
        "fin": end,
        "ini": end - latency,
        "modelo": model,
        "ok": ok,
        "tool": "local_summarize",
    }


def test_rows_of_same_event_grouped_with_sigma_output_over_sigma_ms() -> None:
    calls = [_call(T0 + 100)]
    rows = [
        _row(1, T0 + 96, output=100, tps=50.0, dur=4.0, entry=300),  # 2 s de generacion
        _row(2, T0 + 99, output=100, tps=25.0, dur=3.0, entry=900),  # 4 s de generacion
    ]
    events = ml.group_by_event(rows, calls)
    assert len(events) == 1
    e = events[0]
    assert e["origen"] == "PC" and e["filas"] == [1, 2]
    assert e["tokens_out"] == 200
    assert e["tok_s"] == pytest.approx(200 / 6)
    assert e["tokens_in"] == 900  # la mayor entrada de una llamada, no la suma


def test_row_without_log_call_is_non_pc_event() -> None:
    events = ml.group_by_event([_row(7, T0 + 500)], [_call(T0 + 100)])
    assert [(e["origen"], e["filas"]) for e in events] == [("no-PC", [7])]


def test_call_from_other_model_does_not_claim_row() -> None:
    events = ml.group_by_event([_row(1, T0 + 99)], [_call(T0 + 100, model="otro")])
    assert events[0]["origen"] == "no-PC"


def test_with_two_simultaneous_calls_tightest_wins() -> None:
    long_one = _call(T0 + 100, latency=60.0)
    adjusted = _call(T0 + 101, latency=9.0)
    events = ml.group_by_event([_row(1, T0 + 100, dur=8.0)], [long_one, adjusted])
    assert len(events) == 1 and events[0]["ok"] is True
    assert events[0]["ts"] == T0 + 100


def test_call_with_ok_false_leaves_event_out_of_window() -> None:
    events = ml.group_by_event([_row(1, T0 + 99)], [_call(T0 + 100, ok=False)])
    assert events[0]["ok"] is False


# ---------------------------------------------------------------------------
# Copia de solo lectura y controles sobre una base sintetica
# ---------------------------------------------------------------------------

SCHEMA = """
create table activity (
    id integer primary key autoincrement,
    ts_created integer not null,
    model_id text not null,
    resp_status_code integer not null default 0,
    cache_tokens integer not null default 0,
    input_tokens integer not null default 0,
    output_tokens integer not null default 0,
    tokens_per_second real not null default 0,
    duration_ms integer not null default 0
)
"""


def _create_db(path: Path, rows: list[tuple]) -> None:
    with_ = sqlite3.connect(path)
    with_.execute(SCHEMA)
    with_.executemany(
        "insert into activity (id, ts_created, model_id, resp_status_code, cache_tokens,"
        " input_tokens, output_tokens, tokens_per_second, duration_ms) values (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    with_.commit()
    with_.close()


def _log(folder: Path, calls: list[dict]) -> None:
    lines = [
        json.dumps(
            {
                "ts": datetime.fromtimestamp(c["fin"], UTC).isoformat(),
                "tool": "local_summarize",
                "model": c["modelo"],
                "latency_ms": int((c["fin"] - c["ini"]) * 1000),
                "ok": c["ok"],
                "backend": "local",
            }
        )
        for c in calls
    ]
    (folder / "usage-202610.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _scenario(tmp_path: Path, *, slow_pc: bool, slow_mac: bool) -> tuple[Path, Path]:
    """Qwen3.6 de la PC (12 normales y, si se pide, 12 lentos) y 3 filas de la Mac 570, 571, 573."""
    model = ml.CONTROL_MODEL
    rows, calls = [], []
    id_ = 100
    for i in range(12):
        end = T0 + 100 * i
        rows.append((id_ + i, int(end), model, 200, 0, 500, 100, 40.0, 8000))
        calls.append({"fin": end + 1, "ini": end - 9, "modelo": model, "ok": True})
    if slow_pc:
        for i in range(12, 24):
            end = T0 + 100 * i
            rows.append((id_ + i, int(end), model, 200, 0, 500, 100, 10.0, 8000))
            calls.append({"fin": end + 1, "ini": end - 9, "modelo": model, "ok": True})
    for k, row in enumerate(ml.EXPECTED_ROWS):
        tps = 8.0 if slow_mac else 40.0
        rows.append((row, int(T0 + 5000 + 100 * k), model, 200, 0, 500, 100, tps, 8000))
    folder = tmp_path / "copia"
    folder.mkdir()
    _create_db(folder / "metrics.db", rows)
    logs = tmp_path / "logs"
    logs.mkdir()
    _log(logs, calls)
    return folder, logs


def test_copy_metrics_copies_three_files_without_touching_original(tmp_path: Path) -> None:
    origin = tmp_path / "real"
    origin.mkdir()
    _create_db(origin / "metrics.db", [(1, int(T0), MODEL, 200, 0, 1, 10, 40.0, 1000)])
    (origin / "metrics.db-wal").write_bytes(b"wal")
    (origin / "metrics.db-shm").write_bytes(b"shm")
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in origin.iterdir()}
    copied = ml.copy_metrics(origin, tmp_path / "copia")
    assert sorted(p.name for p in copied) == ["metrics.db", "metrics.db-shm", "metrics.db-wal"]
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in origin.iterdir()}
    assert before == after
    assert (tmp_path / "copia" / "metrics.db-wal").read_bytes() == b"wal"


def test_read_rows_opens_read_only_and_drops_non_generation(tmp_path: Path) -> None:
    path = tmp_path / "metrics.db"
    _create_db(
        path,
        [
            (1, int(T0), MODEL, 200, 5, 100, 10, 40.0, 2000),
            (2, int(T0), MODEL, 500, 0, 100, 10, 40.0, 2000),  # error
            (3, int(T0), MODEL, 200, 0, 100, 0, 0.0, 2000),  # sin generacion
        ],
    )
    rows = ml.read_rows(path)
    assert [f["id"] for f in rows] == [1]
    assert rows[0]["entrada"] == 105  # entrada + cache
    with_ = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        with_.execute("delete from activity")
    with_.close()


def test_control_b_marks_three_mac_rows(tmp_path: Path) -> None:
    folder, logs = _scenario(tmp_path, slow_pc=False, slow_mac=True)
    r = ml.measure(ml.read_rows(folder / "metrics.db"), ml.read_calls(logs), since="2026-10-01")
    assert r["b"]["cumple"] is True
    assert r["b"]["marcadas_de_las_esperadas"] == [570, 571, 573]
    assert r["a"]["marcados"] == 0 and r["a"]["supera_el_tope"] is False
    assert r["a"]["eventos_pc"] == 12


def test_control_b_fails_if_mac_ran_at_normal_speed(tmp_path: Path) -> None:
    folder, logs = _scenario(tmp_path, slow_pc=False, slow_mac=False)
    r = ml.measure(ml.read_rows(folder / "metrics.db"), ml.read_calls(logs), since="2026-10-01")
    assert r["b"]["cumple"] is False
    assert r["b"]["faltan"] == [570, 571, 573]


def test_control_a_exceeds_cap_when_pc_is_slow(tmp_path: Path) -> None:
    folder, logs = _scenario(tmp_path, slow_pc=True, slow_mac=True)
    r = ml.measure(ml.read_rows(folder / "metrics.db"), ml.read_calls(logs), since="2026-10-01")
    assert r["a"]["supera_el_tope"] is True
    # 24 eventos de la PC; los 10 primeros no tienen referencia; de los 14 restantes, 12 van lentos.
    assert (r["a"]["con_referencia"], r["a"]["marcados"]) == (14, 12)
    assert r["a"]["pct_sobre_con_referencia"] == 85.71


def test_date_window_counts_only_inner_events(tmp_path: Path) -> None:
    folder, logs = _scenario(tmp_path, slow_pc=True, slow_mac=True)
    # Los lentos de la PC empiezan en T0 + 1200 s (2026-10-01T00:20:00Z): una ventana que termina
    # antes no los cuenta, aunque la ventana de referencia se alimenta con todo el historial.
    r = ml.measure(
        ml.read_rows(folder / "metrics.db"),
        ml.read_calls(logs),
        since="2026-10-01",
        until="2026-10-01T00:15:00",
    )
    assert r["a"]["marcados"] == 0
    assert r["a"]["eventos_pc"] == 10


@pytest.mark.parametrize(
    ("slow_pc", "slow_mac", "code"),
    [(False, True, 0), (True, True, 3), (False, False, 4)],
)
def test_main_returns_stop_code(tmp_path, capsys, slow_pc, slow_mac, code) -> None:
    folder, logs = _scenario(tmp_path, slow_pc=slow_pc, slow_mac=slow_mac)
    rc = ml.main(["--copy", str(folder), "--logs", str(logs), "--since", "2026-10-01"])
    output = json.loads(capsys.readouterr().out)
    assert rc == code
    assert "referencia_elegida" in output


def test_main_copies_from_source_and_leaves_original(tmp_path, capsys) -> None:
    folder, logs = _scenario(tmp_path, slow_pc=False, slow_mac=True)
    before = hashlib.sha256((folder / "metrics.db").read_bytes()).hexdigest()
    rc = ml.main(
        [
            "--source",
            str(folder),
            "--copy",
            str(tmp_path / "otra"),
            "--logs",
            str(logs),
            "--since",
            "2026-10-01",
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert (tmp_path / "otra" / "metrics.db").is_file()
    assert hashlib.sha256((folder / "metrics.db").read_bytes()).hexdigest() == before


def test_main_without_copy_returns_2(tmp_path, capsys) -> None:
    assert ml.main(["--copy", str(tmp_path / "vacia"), "--logs", str(tmp_path)]) == 2
    assert "No hay copia" in capsys.readouterr().err
