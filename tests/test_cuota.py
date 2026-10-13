"""Puntos de calibración de la cuota y su criterio (REQ-051 a REQ-057, REQ-061; T5).

Registro del statusline y transcripts SINTÉTICOS. Las cifras de `criterio` son las de
`insumos/scripts/criterio.py`, citadas en el escenario de la spec.
"""

from __future__ import annotations

import json
from datetime import timedelta

from test_transcripts import (
    BASE,
    escribir,
    peticion,
    principal,
    sintetica,
    subagente,
    ts,
)

from local_delegate import quota, recompute, transcripts

R1 = "2026-10-01T17:00:00+00:00"  # resets de 5 h (valor opaco: solo agrupa)
R7 = "2026-10-05T00:00:00+00:00"


def fila(s, sesion, cinco, coste, *, reset=R1, siete=1, reset7=R7) -> dict:
    return {
        "ts": ts(s),
        "session_id": sesion,
        "model": "claude-opus-5-5",
        "five_hour": cinco,
        "five_reset": reset,
        "seven_day": siete,
        "seven_reset": reset7,
        "cost_usd": coste,
    }


def _lineas(filas: list) -> list[str]:
    return [x if isinstance(x, str) else json.dumps(x) for x in filas]


def puntos_de(filas: list, peticiones: list | None = None):
    por_tipo, sesiones, d0 = quota.sanitize(_lineas(filas))
    puntos, d1 = quota.statusline_points(por_tipo, sesiones, peticiones or [])
    return puntos, d0, d1


def _punto(fin_dias: float, c: float, ahora, *, tipo="five_hour", fuente="statusline") -> dict:
    fin = ahora - timedelta(days=fin_dias)
    return {
        "source": fuente,
        "type": tipo,
        "start": (fin - timedelta(hours=4)).isoformat(),
        "end": fin.isoformat(),
        "delta_pct": 40,
        "delta_usd": c * 0.4,
        "C": c,
        "marks": [],
        "unpriced_requests": None,
    }


# --- REQ-052: el registro del statusline --------------------------------------------------


def test_cinco_filas_son_un_punto():
    filas = [fila(100 * i, "A", 10 * (i + 1), float(i + 1)) for i in range(5)]
    puntos, _, _ = puntos_de(filas)
    puntos = [p for p in puntos if p["type"] == "five_hour"]
    assert len(puntos) == 1
    p = puntos[0]
    assert p["delta_pct"] == 40
    assert p["delta_usd"] == 4.0
    assert p["C"] == 10.0
    assert p["start"] == (BASE).isoformat()
    assert quota.MARK_OTHER_SURFACES in p["marks"]


def test_sesiones_en_paralelo():
    """B (5 → 45 %) gana a A (10 → 30 %); el Δ$ suma los incrementos de las DOS sesiones."""
    filas = [
        fila(0, "B", 5, 1.0),
        fila(10, "A", 10, 2.0),
        fila(50, "A", 30, 4.0),
        fila(100, "B", 45, 5.0),
    ]
    puntos, _, _ = puntos_de(filas)
    (p,) = [p for p in puntos if p["type"] == "five_hour"]
    SUMA = 4.0 + 2.0
    assert p["delta_usd"] == SUMA
    assert p["delta_pct"] == 40


def test_descartes(tmp_path):
    _, _, d = puntos_de([fila(0, "A", 10, 1.0), fila(100, "A", 15, 2.0)])
    assert d["five_hour"].get("small_delta") == 1

    _, _, d = puntos_de([fila(0, "A", 10, 3.0), fila(100, "A", 40, 3.0)])
    assert d["five_hour"].get("no_local_use") == 1

    # Una sesión que no está en el registro (`claude -p`) pidió dentro del intervalo.
    claude = tmp_path / "claude"
    escribir(principal(claude, sesion="ajena"), [peticion(50, "x1", sesion="ajena")])
    peticiones = list(transcripts.read(claude / "projects").requests.values())
    puntos, _, d = puntos_de([fila(0, "A", 10, 1.0), fila(100, "A", 40, 2.0)], peticiones)
    assert d["five_hour"].get("contaminated") == 1
    assert [p for p in puntos if p["type"] == "five_hour"] == []

    # `/clear`: el coste baja; el incremento es el valor nuevo y el punto lleva la marca.
    puntos, _, _ = puntos_de(
        [fila(0, "A", 10, 5.0), fila(50, "A", 20, 6.0), fila(100, "A", 40, 1.0)]
    )
    (p,) = [p for p in puntos if p["type"] == "five_hour"]
    assert p["delta_usd"] == 2.0
    assert quota.MARK_RESET in p["marks"]

    # Dos ventanas que se solapan: se queda la de mayor Δ%.
    puntos, _, _ = puntos_de(
        [
            fila(0, "A", 10, 1.0, reset="r5"),
            fila(200, "A", 40, 2.0, reset="r5"),
            fila(100, "B", 10, 1.0, reset="r6"),
            fila(300, "B", 30, 2.0, reset="r6"),
        ]
    )
    puntos, d = quota.drop_overlapping([p for p in puntos if p["type"] == "five_hour"])
    assert d["five_hour"].get("overlapping") == 1
    assert [p["delta_pct"] for p in puntos] == [30]


def test_sanear_y_lineas_corruptas(tmp_path):
    filas = [
        fila(0, "A", 120, 1.0),
        fila(50, "A", 10, 1.0, siete="abc"),
        "{esto no es json",
        fila(100, "A", 40, 2.0),
    ]
    escapo = None
    try:
        _, _, d = quota.sanitize(_lineas(filas))
    except Exception as e:  # una línea rota nunca rompe el comando (REQ-061)
        escapo, d = e, {"five_hour": {}, "seven_day": {}}
    assert not escapo
    assert d["five_hour"].get("out_of_range") == 1
    assert d["seven_day"].get("out_of_range") == 1
    assert d["five_hour"].get("corrupt_line") == 1

    # Una línea rota en un transcript: se salta y cuenta, y el comando sigue.
    claude, log = tmp_path / "claude", tmp_path / "log"
    escribir(principal(claude), [peticion(0, "m0"), '{"type": "assistant", roto'])
    escapo = None
    try:
        recompute.run(claude, log, now=BASE + timedelta(days=1))
        agregados = recompute.read_aggregates(log) or {}
    except Exception as e:
        escapo, agregados = e, {}
    assert not escapo
    assert (agregados.get("discards") or {}).get("five_hour", {}).get("corrupt_line") == 1


def test_un_punto_previo_mal_formado_no_rompe_el_comando(tmp_path):
    """REQ-061 en `recalcular-coste`: un punto del JSON anterior sin `delta_pct` (editado a mano)
    se salta y cuenta como `linea_corrupta`, en vez de tumbar `quitar_solapados`."""
    claude, log = tmp_path / "claude", tmp_path / "log"
    escribir(principal(claude), [peticion(0, "m0")])
    roto = {
        "source": "statusline",
        "type": "five_hour",
        "start": (BASE - timedelta(hours=4)).isoformat(),
        "end": BASE.isoformat(),
        "C": 150.0,
    }
    recompute.write_aggregates(log, {"points": [roto]})
    recompute.run(claude, log, now=BASE + timedelta(days=1))
    agregados = recompute.read_aggregates(log) or {}
    assert agregados["points"] == []
    assert agregados["discards"]["five_hour"]["corrupt_line"] == 1
    assert agregados["discards"]["seven_day"].get("corrupt_line", 0) == 0


# --- REQ-051: rechazos --------------------------------------------------------------------


def test_rechazos_duplicados_son_un_punto(tmp_path):
    """11 registros del mismo rechazo de 5 h, en el principal y en dos subagentes: un punto.

    Δ$ = las peticiones de [resetsAt − 5 h, primer rechazo]: 1 M de entrada de Opus 5.5 ($4) y
    1 M escritos a 1 h ($8) = $12. Quedan fuera una de antes del intervalo y una posterior.
    """
    claude = tmp_path / "claude"
    reset = int((BASE + timedelta(hours=3)).timestamp())
    rechazo = {"status": "rejected", "rateLimitType": "five_hour", "resetsAt": reset}

    def rechazos(s0: int, k: int, prefijo: str) -> list:
        return [
            sintetica(s0 + i, f"{prefijo}{i}", quota=[rechazo] if i % 2 else rechazo)
            for i in range(k)
        ]

    escribir(
        principal(claude),
        [
            peticion(-3 * 3600, "antes", usage={"input_tokens": 1_000_000}),
            peticion(0, "p1", usage={"input_tokens": 1_000_000}),
            peticion(10, "p2", usage={"cache_creation": {"ephemeral_1h_input_tokens": 1_000_000}}),
            peticion(2000, "despues", usage={"input_tokens": 1_000_000}),
        ]
        + rechazos(1000, 5, "r"),
    )
    escribir(subagente(claude, "s1"), rechazos(1100, 3, "u"))
    escribir(subagente(claude, "s2"), rechazos(1200, 3, "v"))
    indice = transcripts.read(claude / "projects")
    rechazos_ = quota.rejection_points(indice.rejections, indice.requests.values())
    assert len(rechazos_) == 1
    p = rechazos_[0]
    assert p["delta_usd"] == 12.0
    assert p["end"] == (BASE + timedelta(seconds=1000)).isoformat()
    assert p["marks"] == [quota.MARK_LOW_BOUND, quota.MARK_CHECK_ONLY]
    assert p["unpriced_requests"] == 0
    e = quota.status({"points": rechazos_}, BASE + timedelta(days=1))
    assert e["five_hour"]["status"] == "uncalibrated"
    assert e["five_hour"]["rejection_points"] == 1


# --- REQ-055 y REQ-056: criterio ----------------------------------------------------------


def test_criterio_de_la_spec():
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


def test_un_punto_de_61_dias_no_cuenta():
    ahora = BASE
    fuentes = {"transcripts": True, "statusline": True}
    frescos = [_punto(20, 150, ahora), _punto(10, 160, ahora), _punto(5, 170, ahora)]
    guarda = quota.status({"points": frescos, "sources": fuentes}, ahora)["five_hour"]
    assert guarda["status"] == "calibrated"  # sin el punto viejo, calibra

    con_viejo = [_punto(61, 150, ahora), _punto(10, 160, ahora), _punto(5, 170, ahora)]
    r = quota.status({"points": con_viejo, "sources": fuentes}, ahora)["five_hour"]
    assert r["status"] == "uncalibrated"
    assert r["reason"] == "faltan 1 puntos del statusline"
    assert r["discards"].get("expired") == 1


def test_reinicio_a_mano(tmp_path):
    ahora = BASE
    puntos = [_punto(5, 150, ahora)]
    assert quota.current_points(puntos, ahora) == puntos  # guarda
    vigentes = quota.current_points(puntos, ahora, (ahora - timedelta(days=1)).isoformat())
    assert vigentes == []

    # El comando guarda la fecha del reinicio y conserva la del otro tipo.
    log = tmp_path / "log"
    recompute.run(tmp_path / "claude", log, now=ahora, reset="five_hour")
    recompute.run(tmp_path / "claude", log, now=ahora + timedelta(hours=1))
    reinicios = (recompute.read_aggregates(log) or {}).get("resets")
    assert reinicios == {"five_hour": ahora.isoformat(timespec="seconds"), "seven_day": None}


def test_sin_fuentes_lo_dice():
    """REQ-061: sin registro ni transcripts, «no hay datos de calibración en esta máquina»."""
    ahora = BASE
    sin_nada = {"points": [], "sources": {"transcripts": False, "statusline": False}}
    assert quota.status(sin_nada, ahora)["five_hour"]["reason"] == quota.NO_DATA
    assert quota.status(None, ahora)["seven_day"]["reason"] == quota.NO_DATA
    solo_transcripts = {"points": [], "sources": {"transcripts": True, "statusline": False}}
    assert quota.status(solo_transcripts, ahora)["five_hour"]["reason"] == quota.NO_STATUSLINE
