"""Coste equivalente a precio de API, por evento y por periodo (coste-api-y-cuota, T6).

Las filas pasan **antes** por la fusión de Python (`cost.merge`), como en producción: el coste
nunca se calcula sobre una fila cruda. Los agregados de `N` se escriben con
`recompute.write_aggregates` (T5), que es también el cruce de formato entre el escritor y el
lector.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from local_delegate import attribution, config, cost, i18n, pricing, recompute, valuation

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
MONTH = f"{NOW:%Y%m}"


@pytest.fixture(autouse=True)
def _without_env_fallback(monkeypatch):
    monkeypatch.setattr(config, "COST_FALLBACK", "")


def _line(n: int = 0, **extra) -> dict:
    """Una delegación de prosa por `path`, buena, de `claude-code`."""
    row = {
        "ts": (NOW - timedelta(hours=1, seconds=n)).isoformat(timespec="seconds"),
        "tool": "local_summarize",
        "source": "path",
        "path": f"C:/docs/notas-{n}.md",
        "chars_in": 1_000_000,
        "chars_out": 0,
        "ok": True,
        "tokens_in": 9000,
        "tokens_out": 100,
        "client": "claude-code",
        "tool_use_id": f"toolu_{n:04d}",
    }
    row.update(extra)
    return row


def _merged(tmp_path, lines: list[dict], backfill: dict | None = None) -> list[dict]:
    if backfill:
        attribution.write_backfill(tmp_path, MONTH, backfill)
    return cost.merge(lines, log_dir=tmp_path)


def _backfill(model="claude-opus-5-5", thread="subagent", n=40, exp=0, **extra) -> dict:
    return {
        "caller_model": model,
        "caller_kind": thread,
        "caller_effort": "high",
        "n": n,
        "expiries": exp,
        "match": "exact",
        **extra,
    }


# --- Por evento (REQ-041) ------------------------------------------------------------------------


def test_a_million_characters(tmp_path):
    """Escenario de la spec: prosa por `path`, Opus 5.5 en subagente, `N` = 40, 0 caducidades.

    T = 1 000 000 × 100 // 200 = 500 000; cota baja = 500 000 × $5/MTok = $2,50; estimación =
    500 000 × ($5 + 40 × $0,20)/MTok = $6,50."""
    rows = _merged(tmp_path, [_line()], {"toolu_0000": _backfill()})
    assert rows[0]["density"]["text"] == [200, "measured"]  # guarda: la celda del escenario
    c = valuation.event_cost(rows[0])
    assert c["low_bound"] == 2.50
    assert c["estimate"] == 6.50
    assert c["T"] == 500_000
    assert (c["N"], c["expiries"], c["n_origin"]) == (40, 0, "backfill")

    b = valuation.cost_block(rows, None, now=NOW)
    assert b["figure"] == {"low_bound": 2.50, "estimate": 6.50}
    # La respuesta trae la cobertura, la densidad con su origen, N con su origen y la tabla.
    assert b["bar"]["backfilled"] == 1
    assert b["density"]["origin"]["measured"] == 1
    assert b["n_origin"] == {"backfill": 1, "aggregate": 0, "declared": 0}
    assert b["table"]["consulted"] == pricing.load_prices()["consulted"]


def test_each_expiry_is_a_rewrite(tmp_path):
    """`exp` = 2: estimación = T × (P_w × 3 + (40 − 2) × P_r) = 500 000 × (15 + 7,6)/MTok."""
    rows = _merged(tmp_path, [_line()], {"toolu_0000": _backfill(exp=2)})
    expected = 500_000 * (5 * (1 + 2) + (40 - 2) * 0.20) / 1e6
    c = valuation.event_cost(rows[0])
    assert c["estimate"] == pytest.approx(expected, abs=1e-9)
    assert c["estimate"] == pytest.approx(11.30, abs=1e-9)
    assert c["low_bound"] == 2.50  # la cota baja no depende de las caducidades


def test_a_negative_T_subtracts(tmp_path):
    """Lo devuelto también entró en caché: devolver más de lo leído da un coste negativo."""
    line = _line(chars_in=100, chars_out=10_000)
    rows = _merged(tmp_path, [line], {"toolu_0000": _backfill()})
    c = valuation.event_cost(rows[0])
    assert c["T"] == 100 * 100 // 200 - 10_000 * 100 // 223
    assert c["low_bound"] < 0
    assert c["estimate"] < 0


def test_a_tiny_negative_is_not_a_signed_zero(tmp_path):
    """Arreglo tras T10: T = 50 − 224 = −174 redondea a céntimos como `-0.0`, y la API lo daba tal
    cual («$0,00» en el panel). La fila y la cifra van con `0.0`, sin signo."""
    line = _line(chars_in=100, chars_out=500)
    rows = _merged(tmp_path, [line], {"toolu_0000": _backfill()})
    c = valuation.event_cost(rows[0])
    assert c["T"] == -174  # guarda: el caso es un negativo que redondea a cero
    assert -0.005 < c["estimate"] < 0
    b = valuation.cost_block(rows, None, now=NOW)
    row = b["breakdown"][0]
    output = json.dumps({"breakdown": [row["low_bound"], row["estimate"]], "figure": b["figure"]})
    assert "-0.0" not in output


# --- De dónde sale N (REQ-042) -------------------------------------------------------------------


def test_origin_of_N(tmp_path):
    """(1) relleno; (2) mediana del grupo con al menos 10 casos; (3) declarado del hilo."""
    recompute.write_aggregates(
        tmp_path,
        {
            "version": 1,
            "n_by_month": {
                "202609": {"claude-opus-5-5|subagent": [10, 20, 30, 40, 50]},
                MONTH: {
                    "claude-opus-5-5|subagent": [60, 70, 80, 90, 100],  # 10 casos en total
                    "claude-opus-5|main": [1, 2, 3, 4, 5, 6, 7, 8, 9],  # 9 casos
                },
            },
        },
    )
    aggregates = recompute.read_aggregates(tmp_path)
    assert aggregates is not None  # guarda: el lector entiende lo que escribió el escritor

    lines = [_line(0), _line(1), _line(2)]
    backfill = {
        "toolu_0000": _backfill(n=7, exp=1),
        # Sin `n`: va a los agregados.
        "toolu_0001": {"caller_model": "claude-opus-5-5", "caller_kind": "subagent"},
        "toolu_0002": {"caller_model": "claude-opus-5", "caller_kind": "main"},
    }
    rows = _merged(tmp_path, lines, backfill)

    assert valuation.n_of(rows[0], aggregates) == (7, 1, "backfill")
    n, exp, origin = valuation.n_of(rows[1], aggregates)
    assert origin == "aggregate"
    assert (n, exp) == (55, 0)  # mediana de 10, 20, …, 100 (par: media de los dos centrales)
    n, exp, origin = valuation.n_of(rows[2], aggregates)
    assert origin == "declared"
    assert (n, exp) == (127, 0)  # principal


# --- Modelo sin precio, sin tabla, sin delegaciones (REQ-016, REQ-046) ---------------------------


def test_a_model_without_a_price_does_not_give_zero(tmp_path):
    """Uno sin precio y uno de Opus 5.5: la cifra suma solo el de Opus 5.5 y cuenta el otro aparte.
    Los dos sin precio: no hay cifra y sí el motivo."""
    lines = [_line(0), _line(1)]
    backfill = {"toolu_0000": _backfill(), "toolu_0001": _backfill(model="claude-nobody-9")}
    rows = _merged(tmp_path, lines, backfill)
    b = valuation.cost_block(rows, None, now=NOW)
    assert b["unpriced"]["n"] == 1
    assert b["unpriced"]["ids"] == ["claude-nobody-9"]
    assert b["figure"] == {"low_bound": 2.50, "estimate": 6.50}

    # Los dos con un modelo sin precio en la propia línea (`at_call`).
    alone = cost.merge(
        [_line(5, caller_model="claude-nobody-9"), _line(6, caller_model="claude-nobody-9")],
        log_dir=tmp_path,
    )
    assert all(f["caller_origin"] == "line" for f in alone)  # guarda: no tomó el respaldo
    b = valuation.cost_block(alone, None, now=NOW)
    assert b["figure"] is None
    assert b["reason"] == i18n.t(valuation.ALL_UNPRICED)
    assert b["unpriced"]["n"] == 2


def test_without_table_and_without_delegations(tmp_path, monkeypatch):
    b = valuation.cost_block([], None, now=NOW)
    assert b["reason"] == "sin delegaciones en el periodo"
    assert b["figure"] is None

    rows = _merged(tmp_path, [_line()], {"toolu_0000": _backfill()})

    def _broken():
        raise ValueError("tabla rota")

    monkeypatch.setattr(pricing, "load_prices", _broken)
    b = valuation.cost_block(rows, None, now=NOW)
    assert b["reason"] == i18n.t(valuation.NO_TABLE)
    assert b["figure"] is None


# --- Desglose y base (REQ-040, REQ-047) ----------------------------------------------------------


def test_breakdown_by_effort(tmp_path):
    lines = [_line(0), _line(1), _line(2)]
    backfill = {
        "toolu_0000": _backfill(caller_effort="low"),
        "toolu_0001": _backfill(caller_effort="high"),
        "toolu_0002": _backfill(caller_effort="high"),
    }
    b = valuation.cost_block(_merged(tmp_path, lines, backfill), None, now=NOW)
    assert len(b["breakdown"]) == 2
    by_effort = {g["effort"]: g for g in b["breakdown"]}
    assert by_effort["high"]["cases"] == 2
    assert by_effort["low"]["cases"] == 1
    assert by_effort["high"]["name"] == "Opus 5.5"


def test_images_and_output_to_file_outside_the_base(tmp_path):
    """La imagen del hermano y una salida a fichero quedan fuera, contadas a la vista; la cifra es
    la de la única delegación de texto."""
    image = {
        "ts": (NOW - timedelta(hours=2)).isoformat(timespec="seconds"),
        "tool": "local_describe_image",
        "source": "path",
        "chars_in": 250000,
        "chars_out": 800,
        "ok": True,
        "tokens_in": 1200,
        "tokens_out": 200,
        "client": "claude-code",
    }
    to_file = {
        "ts": (NOW - timedelta(hours=3)).isoformat(timespec="seconds"),
        "tool": "local_boilerplate",
        "source": "inline",
        "chars_in": 300,
        "chars_out": 600_000,
        "output_to_file": True,
        "ok": True,
        "tokens_in": 100,
        "tokens_out": 5000,
        "client": "claude-code",
    }
    rows = _merged(tmp_path, [_line(), image, to_file], {"toolu_0000": _backfill()})
    b = valuation.cost_block(rows, None, now=NOW)
    assert b["outside_base"]["output_to_file"] == 1
    assert b["outside_base"]["images"] == 1
    assert b["figure"] == {"low_bound": 2.50, "estimate": 6.50}
    assert b["T"] == 500_000

    assert valuation.images_block(rows) == {"n": 1, "bytes": 250000, "chars_returned": 800}


def test_the_excluded_ones_go_to_the_bar_and_do_not_add_up(tmp_path):
    lines = [_line(0), _line(1, client="mcp"), _line(2, client="codex-mcp-client")]
    backfill = {k: _backfill() for k in ("toolu_0000", "toolu_0001", "toolu_0002")}
    b = valuation.cost_block(_merged(tmp_path, lines, backfill), None, now=NOW)
    assert b["bar"]["excluded"] == 2
    assert b["bar"]["excluded_by_reason"] == {"not_claude": 1, "tests": 1}
    assert b["figure"] == {"low_bound": 2.50, "estimate": 6.50}


def test_the_fallback_is_named_in_the_bar(tmp_path):
    """Sin relleno ni línea con modelo, viejo y sin transcript: `supuesto`, con el respaldo."""
    old = _line(ts=(NOW - timedelta(days=45)).isoformat(timespec="seconds"))
    b = valuation.cost_block(cost.merge([old], log_dir=tmp_path), None, now=NOW)
    assert b["bar"]["assumed"] == 1
    assert b["bar"]["with_assumed_model"] == 1
    assert (b["fallback"]["name"], b["fallback"]["thread"]) == ("Opus 5.5", "subagent")
    assert b["n_origin"]["declared"] == 1
    assert json.dumps(b)  # serializable tal cual para `/api/stats`


# --- Ventanas de prueba (test-windows-out-of-metrics, REQ-005 y REQ-014) -------------------------


def _with_window(tmp_path, lines: list[dict]) -> list[dict]:
    """Una ventana que cubre solo la línea 1 (`AHORA - 1 h - 1 s`)."""
    from local_delegate import test_windows

    t = NOW - timedelta(hours=1, seconds=1)
    test_windows.add(tmp_path, t, t + timedelta(milliseconds=500), "prueba")
    return lines


def test_merge_stamps_the_window_and_does_not_touch_the_log(tmp_path):
    import hashlib

    lines = _with_window(tmp_path, [_line(0), _line(1), _line(2)])
    log = tmp_path / f"usage-{MONTH}.jsonl"
    log.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    before = hashlib.sha256(log.read_bytes()).hexdigest()
    raw_lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    rows = cost.merge(raw_lines, log_dir=tmp_path)
    assert [f.get("test_window") for f in rows] == [None, "w-20261006T105959Z", None]
    assert all("test_window" not in c for c in raw_lines), "fundir copia: no muta la entrada"
    assert hashlib.sha256(log.read_bytes()).hexdigest() == before


def test_a_row_in_a_window_goes_to_the_excluded_test_bucket(tmp_path):
    """Control: mutante «`test_reason` ignora `test_window`» → la fila cuenta y suma."""
    lines = _with_window(tmp_path, [_line(0), _line(1)])
    backfill = {k: _backfill() for k in ("toolu_0000", "toolu_0001")}
    rows = _merged(tmp_path, lines, backfill)
    assert cost.segment(rows[1], now=NOW, cleanup_days=30) == "excluded"
    assert cost.segment(rows[0], now=NOW, cleanup_days=30) != "excluded", "guarda"
    b = valuation.cost_block(rows, None, now=NOW)
    assert b["bar"]["excluded_by_reason"] == {"tests": 1}
