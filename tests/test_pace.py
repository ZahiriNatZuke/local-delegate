"""La referencia de velocidad del daemon (`local_delegate.pace`, REQ-025 y REQ-028 en su parte pura).

Los cinco controles de T3 se repiten aqui contra el modulo del paquete (el script de control lo
importa, y `tests/test_measure_slowness.py` sigue siendo la guarda de los dos). Despues, lo que solo
tiene el daemon: la ventana en memoria, la siembra desde el log del mes en curso y del anterior, y
que observar nunca lanza.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from local_delegate import pace

MODEL = "modelo-a"


def _ev(i: int, tok_s: float, *, tokens_out: int = 100, tokens_in: int = 500, **extra) -> dict:
    """Evento de la serie de `compute_slowness` (esquema del script de T3)."""
    return {
        "id": i,
        "ts": float(i),
        "modelo": MODEL,
        "tok_s": tok_s,
        "tokens_out": tokens_out,
        "tokens_in": tokens_in,
        **extra,
    }


def _log(tok_s: float, *, model: str = MODEL, **extra) -> dict:
    """Evento del log de uso (esquema de `usage-*.jsonl`)."""
    return {
        "model": model,
        "ok": True,
        "tokens_out": 100,
        "tokens_in": 500,
        "tok_s": tok_s,
        **extra,
    }


# ---------------------------------------------------------------------------
# Los cinco controles de T3, contra el paquete
# ---------------------------------------------------------------------------


def test_window_of_50_median_uses_last_50() -> None:
    # 31 viejos a 100 y 28 nuevos a 40: la ventana de 50 da 40; la historia entera daria 100.
    events = [_ev(i, 100.0) for i in range(31)] + [_ev(i, 40.0) for i in range(31, 59)]
    events.append(_ev(59, 40.0))
    result = pace.compute_slowness(events)
    ref = result[59]["ref"]
    assert ref == 40.0
    # Y lo mismo en la ventana del daemon, alimentada evento a evento.
    refs = pace.References()
    for e in events[:59]:
        refs.record(_log(e["tok_s"]))
    assert refs.reference(MODEL) == 40.0


def test_minimum_10_event_10_has_no_reference_and_11_does() -> None:
    events = pace.compute_slowness([_ev(i, 40.0) for i in range(11)])
    assert events[9].get("pace_rel") is None
    assert "ref" not in events[9] and "slow" not in events[9]
    assert events[10]["pace_rel"] == 1.0
    assert events[10]["slow"] is False


def test_tokens_out_below_8_not_in_window() -> None:
    events = [_ev(i, 40.0) for i in range(12)]
    events += [_ev(i, 5.0, tokens_out=3) for i in range(12, 27)]
    events.append(_ev(27, 40.0))
    result = pace.compute_slowness(events)
    ref = result[27]["ref"]
    assert ref == 40.0
    assert all("pace_rel" not in e for e in result[12:27])
    # La ventana del daemon aplica el mismo filtro al registrar.
    refs = pace.References()
    for e in events[:27]:
        refs.record(_log(e["tok_s"], tokens_out=e["tokens_out"]))
    assert len(refs.window(MODEL)) == 12


def test_reference_does_not_look_ahead() -> None:
    sorted_ones = [_ev(i, 40.0) for i in range(12)] + [_ev(12, 10.0)]
    unordered = [sorted_ones[i] for i in (7, 12, 0, 3, 11, 5, 1, 9, 2, 10, 4, 8, 6)]
    result = pace.compute_slowness(unordered)
    marked = [e["id"] for e in result if e.get("slow")]
    assert marked == [12]
    assert [e["id"] for e in result] == list(range(13))


def test_by_spans_12k_event_at_18_tok_s_not_slow() -> None:
    # Las cifras de T3 (cortos a 40, largos a 26, evento largo a 18) con el umbral por defecto,
    # 0,5: contra una sola referencia (mediana 40) el ritmo es 0,45 (lento); contra su tramo
    # (mediana 26), 0,69 (no lo es).
    events = [_ev(i, 40.0, tokens_in=500) for i in range(20)]
    events += [_ev(20 + i, 26.0, tokens_in=12_000) for i in range(12)]
    events.append(_ev(32, 18.0, tokens_in=12_000))
    slow = pace.compute_slowness(events, by_spans=True)[-1]["slow"]
    assert not slow
    one_item = pace.compute_slowness(events, by_spans=False)[-1]
    assert one_item["slow"] is True


# ---------------------------------------------------------------------------
# Lo del daemon
# ---------------------------------------------------------------------------


def test_slow_call_distinguished_from_pure_wait() -> None:
    # 20 eventos con mediana de generacion 40,5 y prefill alto (900 tok/s). La respuesta genera
    # a 15 tok/s: 15 / 40,5 = 0,37. Si se comparase el prefill, saldria ~0,02.
    refs = pace.References()
    for k in range(20):
        refs.record(_log(40.0 if k % 2 else 41.0, prefill_tok_s=900.0 + k))
    r = refs.measure(MODEL, 15.0, 500)
    assert r["pace_rel"] == 0.37
    assert r["slow"] is True


def test_with_9_samples_no_reference() -> None:
    refs = pace.References()
    for _ in range(9):
        refs.record(_log(40.0))
    r = refs.measure(MODEL, 5.0, 500)
    assert r == {}
    refs.record(_log(40.0))  # la 10.ª: ya hay referencia
    assert refs.measure(MODEL, 5.0, 500) == {"pace_rel": 0.12, "slow": True}


def test_measure_with_threshold_argument_and_strict() -> None:
    refs = pace.References()
    for _ in range(10):
        refs.record(_log(40.0))
    assert refs.measure(MODEL, 20.0) == {"pace_rel": 0.5, "slow": False}
    assert refs.measure(MODEL, 20.0, threshold=0.6) == {"pace_rel": 0.5, "slow": True}


def test_measure_under_8_output_tokens_not_evaluated() -> None:
    refs = pace.References()
    for _ in range(10):
        refs.record(_log(40.0))
    assert refs.measure(MODEL, 5.0, tokens_out=3) == {}
    assert refs.measure(MODEL, 5.0, tokens_out=8)["slow"] is True


def test_record_ignores_failed_short_and_no_tok_s() -> None:
    refs = pace.References()
    assert refs.record(_log(40.0, ok=False)) is False
    assert refs.record(_log(40.0, tokens_out=7)) is False
    no_tok_s = _log(40.0)
    del no_tok_s["tok_s"]  # backend sin `timings`
    assert refs.record(no_tok_s) is False
    assert refs.record(_log(40.0)) is True
    assert refs.window(MODEL) == [40.0]


def test_each_model_has_its_window_and_summary_shows_it() -> None:
    refs = pace.References()
    for _ in range(12):
        refs.record(_log(100.0, model="rapido"))
    for _ in range(3):
        refs.record(_log(10.0))
    assert refs.measure(MODEL, 10.0) == {}  # 3 muestras propias: sin referencia
    assert refs.summary() == [
        {"model": MODEL, "span": None, "median": None, "samples": 3},
        {"model": "rapido", "span": None, "median": 100.0, "samples": 12},
    ]


@pytest.mark.parametrize(
    ("model", "tok_s", "tokens_in"),
    [
        (None, 15.0, 500),
        (MODEL, None, 500),
        (MODEL, "15", 500),
        (MODEL, float("nan"), 500),
        (MODEL, float("inf"), 500),
        (MODEL, -3.0, 500),
        (MODEL, 0, 500),
        (MODEL, True, 500),
        (MODEL, 15.0, "mucho"),
        (["lista"], 15.0, 500),
        ("otro-modelo", 15.0, 500),
    ],
)
def test_measure_odd_input_returns_empty_without_raising(model, tok_s, tokens_in) -> None:
    refs = pace.References()
    for _ in range(10):
        refs.record(_log(40.0))
    try:
        r = refs.measure(model, tok_s, tokens_in)
    except Exception as e:  # observar no puede romper la tool (REQ-028)
        r = f"excepcion {type(e).__name__}"
    if tokens_in == "mucho":
        # Un `tokens_in` raro no impide medir con una sola referencia: no se usa.
        assert r == {"pace_rel": 0.38, "slow": True}
    else:
        assert r == {}


@pytest.mark.parametrize(
    "event", [None, "texto", 7, [], {"model": MODEL, "ok": True, "tokens_out": "x", "tok_s": 1}]
)
def test_record_odd_input_does_not_raise(event) -> None:
    try:
        entered = pace.References().record(event)
    except Exception as e:
        entered = f"excepcion {type(e).__name__}"
    assert entered is False


# ---------------------------------------------------------------------------
# Siembra
# ---------------------------------------------------------------------------


def _file(folder: Path, year_month: str, n: int, tok_s: float) -> None:
    lines = [json.dumps(_log(tok_s)) for _ in range(n)]
    (folder / f"usage-{year_month}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_seed_reads_current_and_previous_month(tmp_path: Path) -> None:
    # A dia 2 del mes el mes en curso tiene poco: sin el anterior la ventana se queda en 20.
    _file(tmp_path, "202609", 30, 40.0)
    _file(tmp_path, "202610", 20, 40.0)
    refs = pace.References()
    pace.seed_from_log(refs, tmp_path, datetime(2026, 10, 2, tzinfo=UTC))
    window = refs.window(MODEL)
    assert len(window) == 50


def test_seed_does_not_read_other_months(tmp_path: Path) -> None:
    _file(tmp_path, "202608", 15, 100.0)  # dos meses atras: fuera
    _file(tmp_path, "202609", 10, 40.0)
    _file(tmp_path, "202610", 10, 40.0)
    _file(tmp_path, "202611", 15, 100.0)  # futuro (reloj cambiado): fuera
    refs = pace.References()
    n = pace.seed_from_log(refs, tmp_path, datetime(2026, 10, 2, tzinfo=UTC))
    assert n == 20
    assert refs.window(MODEL) == [40.0] * 20


def test_seed_in_january_reads_previous_december(tmp_path: Path) -> None:
    _file(tmp_path, "202512", 10, 40.0)
    _file(tmp_path, "202601", 5, 40.0)
    refs = pace.References()
    assert pace.seed_from_log(refs, tmp_path, datetime(2026, 1, 2, tzinfo=UTC)) == 15


def test_seed_without_files_gives_zero(tmp_path: Path) -> None:
    refs = pace.References()
    now = datetime(2026, 10, 2, tzinfo=UTC)
    assert pace.seed_from_log(refs, tmp_path / "no-existe", now) == 0
    assert refs.summary() == []


def test_corrupt_line_does_not_break_seeding() -> None:
    lines = [json.dumps(_log(40.0)) for _ in range(12)]
    lines.insert(5, '{"model": "modelo-a", "ok": tru')  # linea cortada a medio escribir
    refs = pace.References()
    try:
        n = refs.seed(lines)
    except Exception as e:
        n = f"excepcion {type(e).__name__}"
    assert n == 12, f"la siembra no tolera una linea corrupta: {n}"
