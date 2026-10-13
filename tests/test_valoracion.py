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

from local_delegate import attribution, config, cost, pricing, recompute, valuation

AHORA = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
MES = f"{AHORA:%Y%m}"


@pytest.fixture(autouse=True)
def _sin_respaldo_del_entorno(monkeypatch):
    monkeypatch.setattr(config, "COST_FALLBACK", "")


def _linea(n: int = 0, **extra) -> dict:
    """Una delegación de prosa por `path`, buena, de `claude-code`."""
    fila = {
        "ts": (AHORA - timedelta(hours=1, seconds=n)).isoformat(timespec="seconds"),
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
    fila.update(extra)
    return fila


def _fundidas(tmp_path, lineas: list[dict], relleno: dict | None = None) -> list[dict]:
    if relleno:
        attribution.write_backfill(tmp_path, MES, relleno)
    return cost.merge(lineas, log_dir=tmp_path)


def _relleno(modelo="claude-opus-5-5", hilo="subagent", n=40, cad=0, **extra) -> dict:
    return {
        "caller_model": modelo,
        "caller_kind": hilo,
        "caller_effort": "high",
        "n": n,
        "expiries": cad,
        "match": "exact",
        **extra,
    }


# --- Por evento (REQ-041) ------------------------------------------------------------------------


def test_un_millon_de_caracteres(tmp_path):
    """Escenario de la spec: prosa por `path`, Opus 5.5 en subagente, `N` = 40, 0 caducidades.

    T = 1 000 000 × 100 // 200 = 500 000; cota baja = 500 000 × $5/MTok = $2,50; estimación =
    500 000 × ($5 + 40 × $0,20)/MTok = $6,50."""
    filas = _fundidas(tmp_path, [_linea()], {"toolu_0000": _relleno()})
    assert filas[0]["density"]["text"] == [200, "measured"]  # guarda: la celda del escenario
    c = valuation.event_cost(filas[0])
    assert c["low_bound"] == 2.50
    assert c["estimate"] == 6.50
    assert c["T"] == 500_000
    assert (c["N"], c["expiries"], c["n_origin"]) == (40, 0, "backfill")

    b = valuation.cost_block(filas, None, now=AHORA)
    assert b["figure"] == {"low_bound": 2.50, "estimate": 6.50}
    # La respuesta trae la cobertura, la densidad con su origen, N con su origen y la tabla.
    assert b["bar"]["backfilled"] == 1
    assert b["density"]["origin"]["measured"] == 1
    assert b["n_origin"] == {"backfill": 1, "aggregate": 0, "declared": 0}
    assert b["table"]["consulted"] == pricing.load_prices()["consulted"]


def test_cada_caducidad_es_una_reescritura(tmp_path):
    """`cad` = 2: estimación = T × (P_w × 3 + (40 − 2) × P_r) = 500 000 × (15 + 7,6)/MTok."""
    filas = _fundidas(tmp_path, [_linea()], {"toolu_0000": _relleno(cad=2)})
    esperada = 500_000 * (5 * (1 + 2) + (40 - 2) * 0.20) / 1e6
    c = valuation.event_cost(filas[0])
    assert c["estimate"] == pytest.approx(esperada, abs=1e-9)
    assert c["estimate"] == pytest.approx(11.30, abs=1e-9)
    assert c["low_bound"] == 2.50  # la cota baja no depende de las caducidades


def test_un_T_negativo_resta(tmp_path):
    """Lo devuelto también entró en caché: devolver más de lo leído da un coste negativo."""
    linea = _linea(chars_in=100, chars_out=10_000)
    filas = _fundidas(tmp_path, [linea], {"toolu_0000": _relleno()})
    c = valuation.event_cost(filas[0])
    assert c["T"] == 100 * 100 // 200 - 10_000 * 100 // 223
    assert c["low_bound"] < 0
    assert c["estimate"] < 0


def test_un_negativo_diminuto_no_es_un_cero_con_signo(tmp_path):
    """Arreglo tras T10: T = 50 − 224 = −174 redondea a céntimos como `-0.0`, y la API lo daba tal
    cual («$0,00» en el panel). La fila y la cifra van con `0.0`, sin signo."""
    linea = _linea(chars_in=100, chars_out=500)
    filas = _fundidas(tmp_path, [linea], {"toolu_0000": _relleno()})
    c = valuation.event_cost(filas[0])
    assert c["T"] == -174  # guarda: el caso es un negativo que redondea a cero
    assert -0.005 < c["estimate"] < 0
    b = valuation.cost_block(filas, None, now=AHORA)
    fila = b["breakdown"][0]
    salida = json.dumps({"breakdown": [fila["low_bound"], fila["estimate"]], "figure": b["figure"]})
    assert "-0.0" not in salida


# --- De dónde sale N (REQ-042) -------------------------------------------------------------------


def test_origen_de_N(tmp_path):
    """(1) relleno; (2) mediana del grupo con al menos 10 casos; (3) declarado del hilo."""
    recompute.write_aggregates(
        tmp_path,
        {
            "version": 1,
            "n_by_month": {
                "202609": {"claude-opus-5-5|subagent": [10, 20, 30, 40, 50]},
                MES: {
                    "claude-opus-5-5|subagent": [60, 70, 80, 90, 100],  # 10 casos en total
                    "claude-opus-5|main": [1, 2, 3, 4, 5, 6, 7, 8, 9],  # 9 casos
                },
            },
        },
    )
    agregados = recompute.read_aggregates(tmp_path)
    assert agregados is not None  # guarda: el lector entiende lo que escribió el escritor

    lineas = [_linea(0), _linea(1), _linea(2)]
    relleno = {
        "toolu_0000": _relleno(n=7, cad=1),
        # Sin `n`: va a los agregados.
        "toolu_0001": {"caller_model": "claude-opus-5-5", "caller_kind": "subagent"},
        "toolu_0002": {"caller_model": "claude-opus-5", "caller_kind": "main"},
    }
    filas = _fundidas(tmp_path, lineas, relleno)

    assert valuation.n_of(filas[0], agregados) == (7, 1, "backfill")
    n, cad, origen = valuation.n_of(filas[1], agregados)
    assert origen == "aggregate"
    assert (n, cad) == (55, 0)  # mediana de 10, 20, …, 100 (par: media de los dos centrales)
    n, cad, origen = valuation.n_of(filas[2], agregados)
    assert origen == "declared"
    assert (n, cad) == (127, 0)  # principal


# --- Modelo sin precio, sin tabla, sin delegaciones (REQ-016, REQ-046) ---------------------------


def test_un_modelo_sin_precio_no_da_cero(tmp_path):
    """Uno sin precio y uno de Opus 5.5: la cifra suma solo el de Opus 5.5 y cuenta el otro aparte.
    Los dos sin precio: no hay cifra y sí el motivo."""
    lineas = [_linea(0), _linea(1)]
    relleno = {"toolu_0000": _relleno(), "toolu_0001": _relleno(modelo="claude-nadie-9")}
    filas = _fundidas(tmp_path, lineas, relleno)
    b = valuation.cost_block(filas, None, now=AHORA)
    assert b["unpriced"]["n"] == 1
    assert b["unpriced"]["ids"] == ["claude-nadie-9"]
    assert b["figure"] == {"low_bound": 2.50, "estimate": 6.50}

    # Los dos con un modelo sin precio en la propia línea (`at_call`).
    solas = cost.merge(
        [_linea(5, caller_model="claude-nadie-9"), _linea(6, caller_model="claude-nadie-9")],
        log_dir=tmp_path,
    )
    assert all(f["caller_origin"] == "line" for f in solas)  # guarda: no tomó el respaldo
    b = valuation.cost_block(solas, None, now=AHORA)
    assert b["figure"] is None
    assert b["reason"] == valuation.ALL_UNPRICED
    assert b["unpriced"]["n"] == 2


def test_sin_tabla_y_sin_delegaciones(tmp_path, monkeypatch):
    b = valuation.cost_block([], None, now=AHORA)
    assert b["reason"] == "sin delegaciones en el periodo"
    assert b["figure"] is None

    filas = _fundidas(tmp_path, [_linea()], {"toolu_0000": _relleno()})

    def _rota():
        raise ValueError("tabla rota")

    monkeypatch.setattr(pricing, "load_prices", _rota)
    b = valuation.cost_block(filas, None, now=AHORA)
    assert b["reason"] == valuation.NO_TABLE
    assert b["figure"] is None


# --- Desglose y base (REQ-040, REQ-047) ----------------------------------------------------------


def test_desglose_por_esfuerzo(tmp_path):
    lineas = [_linea(0), _linea(1), _linea(2)]
    relleno = {
        "toolu_0000": _relleno(caller_effort="low"),
        "toolu_0001": _relleno(caller_effort="high"),
        "toolu_0002": _relleno(caller_effort="high"),
    }
    b = valuation.cost_block(_fundidas(tmp_path, lineas, relleno), None, now=AHORA)
    assert len(b["breakdown"]) == 2
    por_esfuerzo = {g["effort"]: g for g in b["breakdown"]}
    assert por_esfuerzo["high"]["cases"] == 2
    assert por_esfuerzo["low"]["cases"] == 1
    assert por_esfuerzo["high"]["name"] == "Opus 5.5"


def test_imagenes_y_salida_a_fichero_fuera_de_la_base(tmp_path):
    """La imagen del hermano y una salida a fichero quedan fuera, contadas a la vista; la cifra es
    la de la única delegación de texto."""
    imagen = {
        "ts": (AHORA - timedelta(hours=2)).isoformat(timespec="seconds"),
        "tool": "local_describe_image",
        "source": "path",
        "chars_in": 250000,
        "chars_out": 800,
        "ok": True,
        "tokens_in": 1200,
        "tokens_out": 200,
        "client": "claude-code",
    }
    a_fichero = {
        "ts": (AHORA - timedelta(hours=3)).isoformat(timespec="seconds"),
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
    filas = _fundidas(tmp_path, [_linea(), imagen, a_fichero], {"toolu_0000": _relleno()})
    b = valuation.cost_block(filas, None, now=AHORA)
    assert b["outside_base"]["output_to_file"] == 1
    assert b["outside_base"]["images"] == 1
    assert b["figure"] == {"low_bound": 2.50, "estimate": 6.50}
    assert b["T"] == 500_000

    assert valuation.images_block(filas) == {"n": 1, "bytes": 250000, "chars_returned": 800}


def test_los_excluidos_van_a_la_barra_y_no_suman(tmp_path):
    lineas = [_linea(0), _linea(1, client="mcp"), _linea(2, client="codex-mcp-client")]
    relleno = {k: _relleno() for k in ("toolu_0000", "toolu_0001", "toolu_0002")}
    b = valuation.cost_block(_fundidas(tmp_path, lineas, relleno), None, now=AHORA)
    assert b["bar"]["excluded"] == 2
    assert b["bar"]["excluded_by_reason"] == {"no es Claude": 1, "pruebas": 1}
    assert b["figure"] == {"low_bound": 2.50, "estimate": 6.50}


def test_el_respaldo_se_nombra_en_la_barra(tmp_path):
    """Sin relleno ni línea con modelo, viejo y sin transcript: `supuesto`, con el respaldo."""
    vieja = _linea(ts=(AHORA - timedelta(days=45)).isoformat(timespec="seconds"))
    b = valuation.cost_block(cost.merge([vieja], log_dir=tmp_path), None, now=AHORA)
    assert b["bar"]["assumed"] == 1
    assert b["bar"]["with_assumed_model"] == 1
    assert (b["fallback"]["name"], b["fallback"]["thread"]) == ("Opus 5.5", "subagent")
    assert b["n_origin"]["declared"] == 1
    assert json.dumps(b)  # serializable tal cual para `/api/stats`


# --- Ventanas de prueba (test-windows-out-of-metrics, REQ-005 y REQ-014) -------------------------


def _con_ventana(tmp_path, lineas: list[dict]) -> list[dict]:
    """Una ventana que cubre solo la línea 1 (`AHORA - 1 h - 1 s`)."""
    from local_delegate import test_windows

    t = AHORA - timedelta(hours=1, seconds=1)
    test_windows.add(tmp_path, t, t + timedelta(milliseconds=500), "prueba")
    return lineas


def test_fundir_estampa_la_ventana_y_no_toca_el_log(tmp_path):
    import hashlib

    lineas = _con_ventana(tmp_path, [_linea(0), _linea(1), _linea(2)])
    log = tmp_path / f"usage-{MES}.jsonl"
    log.write_text("".join(json.dumps(x) + "\n" for x in lineas), encoding="utf-8")
    antes = hashlib.sha256(log.read_bytes()).hexdigest()
    crudas = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    filas = cost.merge(crudas, log_dir=tmp_path)
    assert [f.get("test_window") for f in filas] == [None, "w-20261006T105959Z", None]
    assert all("test_window" not in c for c in crudas), "fundir copia: no muta la entrada"
    assert hashlib.sha256(log.read_bytes()).hexdigest() == antes


def test_una_fila_en_ventana_va_al_tramo_excluido_como_prueba(tmp_path):
    """Control: mutante «`test_reason` ignora `test_window`» → la fila cuenta y suma."""
    lineas = _con_ventana(tmp_path, [_linea(0), _linea(1)])
    relleno = {k: _relleno() for k in ("toolu_0000", "toolu_0001")}
    filas = _fundidas(tmp_path, lineas, relleno)
    assert cost.segment(filas[1], now=AHORA, cleanup_days=30) == "excluded"
    assert cost.segment(filas[0], now=AHORA, cleanup_days=30) != "excluded", "guarda"
    b = valuation.cost_block(filas, None, now=AHORA)
    assert b["bar"]["excluded_by_reason"] == {"pruebas": 1}
