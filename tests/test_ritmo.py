"""La referencia de velocidad del daemon (`local_delegate.ritmo`, REQ-025 y REQ-028 en su parte pura).

Los cinco controles de T3 se repiten aqui contra el modulo del paquete (el script de control lo
importa, y `tests/test_medir_lentitud.py` sigue siendo la guarda de los dos). Despues, lo que solo
tiene el daemon: la ventana en memoria, la siembra desde el log del mes en curso y del anterior, y
que observar nunca lanza.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from local_delegate import ritmo

MODELO = "modelo-a"


def _ev(i: int, tok_s: float, *, tokens_out: int = 100, tokens_in: int = 500, **extra) -> dict:
    """Evento de la serie de `calcular_lentitud` (esquema del script de T3)."""
    return {
        "id": i,
        "ts": float(i),
        "modelo": MODELO,
        "tok_s": tok_s,
        "tokens_out": tokens_out,
        "tokens_in": tokens_in,
        **extra,
    }


def _log(tok_s: float, *, model: str = MODELO, **extra) -> dict:
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


def test_ventana_de_50_la_mediana_usa_los_50_ultimos() -> None:
    # 31 viejos a 100 y 28 nuevos a 40: la ventana de 50 da 40; la historia entera daria 100.
    eventos = [_ev(i, 100.0) for i in range(31)] + [_ev(i, 40.0) for i in range(31, 59)]
    eventos.append(_ev(59, 40.0))
    resultado = ritmo.calcular_lentitud(eventos)
    ref = resultado[59]["ref"]
    assert ref == 40.0
    # Y lo mismo en la ventana del daemon, alimentada evento a evento.
    refs = ritmo.Referencias()
    for e in eventos[:59]:
        refs.registrar(_log(e["tok_s"]))
    assert refs.referencia(MODELO) == 40.0


def test_minimo_de_10_el_evento_10_no_tiene_referencia_y_el_11_si() -> None:
    eventos = ritmo.calcular_lentitud([_ev(i, 40.0) for i in range(11)])
    assert eventos[9].get("ritmo_rel") is None
    assert "ref" not in eventos[9] and "lento" not in eventos[9]
    assert eventos[10]["ritmo_rel"] == 1.0
    assert eventos[10]["lento"] is False


def test_tokens_out_menor_que_8_no_entra_en_la_ventana() -> None:
    eventos = [_ev(i, 40.0) for i in range(12)]
    eventos += [_ev(i, 5.0, tokens_out=3) for i in range(12, 27)]
    eventos.append(_ev(27, 40.0))
    resultado = ritmo.calcular_lentitud(eventos)
    ref = resultado[27]["ref"]
    assert ref == 40.0
    assert all("ritmo_rel" not in e for e in resultado[12:27])
    # La ventana del daemon aplica el mismo filtro al registrar.
    refs = ritmo.Referencias()
    for e in eventos[:27]:
        refs.registrar(_log(e["tok_s"], tokens_out=e["tokens_out"]))
    assert len(refs.ventana(MODELO)) == 12


def test_la_referencia_no_mira_el_futuro() -> None:
    ordenados = [_ev(i, 40.0) for i in range(12)] + [_ev(12, 10.0)]
    desordenados = [ordenados[i] for i in (7, 12, 0, 3, 11, 5, 1, 9, 2, 10, 4, 8, 6)]
    resultado = ritmo.calcular_lentitud(desordenados)
    marcados = [e["id"] for e in resultado if e.get("lento")]
    assert marcados == [12]
    assert [e["id"] for e in resultado] == list(range(13))


def test_por_tramos_un_evento_de_12k_a_18_tok_s_no_es_lento() -> None:
    # Las cifras de T3 (cortos a 40, largos a 26, evento largo a 18) con el umbral por defecto,
    # 0,5: contra una sola referencia (mediana 40) el ritmo es 0,45 (lento); contra su tramo
    # (mediana 26), 0,69 (no lo es).
    eventos = [_ev(i, 40.0, tokens_in=500) for i in range(20)]
    eventos += [_ev(20 + i, 26.0, tokens_in=12_000) for i in range(12)]
    eventos.append(_ev(32, 18.0, tokens_in=12_000))
    lento = ritmo.calcular_lentitud(eventos, por_tramos=True)[-1]["lento"]
    assert not lento
    una = ritmo.calcular_lentitud(eventos, por_tramos=False)[-1]
    assert una["lento"] is True


# ---------------------------------------------------------------------------
# Lo del daemon
# ---------------------------------------------------------------------------


def test_una_llamada_lenta_se_distingue_de_una_espera_parte_pura() -> None:
    # 20 eventos con mediana de generacion 40,5 y prefill alto (900 tok/s). La respuesta genera
    # a 15 tok/s: 15 / 40,5 = 0,37. Si se comparase el prefill, saldria ~0,02.
    refs = ritmo.Referencias()
    for k in range(20):
        refs.registrar(_log(40.0 if k % 2 else 41.0, prefill_tok_s=900.0 + k))
    r = refs.medir(MODELO, 15.0, 500)
    assert r["ritmo_rel"] == 0.37
    assert r["lento"] is True


def test_con_9_muestras_no_hay_referencia() -> None:
    refs = ritmo.Referencias()
    for _ in range(9):
        refs.registrar(_log(40.0))
    r = refs.medir(MODELO, 5.0, 500)
    assert r == {}
    refs.registrar(_log(40.0))  # la 10.ª: ya hay referencia
    assert refs.medir(MODELO, 5.0, 500) == {"ritmo_rel": 0.12, "lento": True}


def test_medir_con_umbral_como_argumento_y_estricto() -> None:
    refs = ritmo.Referencias()
    for _ in range(10):
        refs.registrar(_log(40.0))
    assert refs.medir(MODELO, 20.0) == {"ritmo_rel": 0.5, "lento": False}
    assert refs.medir(MODELO, 20.0, umbral=0.6) == {"ritmo_rel": 0.5, "lento": True}


def test_medir_con_menos_de_8_tokens_de_salida_no_evalua() -> None:
    refs = ritmo.Referencias()
    for _ in range(10):
        refs.registrar(_log(40.0))
    assert refs.medir(MODELO, 5.0, tokens_out=3) == {}
    assert refs.medir(MODELO, 5.0, tokens_out=8)["lento"] is True


def test_registrar_ignora_fallidos_cortos_y_sin_tok_s() -> None:
    refs = ritmo.Referencias()
    assert refs.registrar(_log(40.0, ok=False)) is False
    assert refs.registrar(_log(40.0, tokens_out=7)) is False
    sin_tok_s = _log(40.0)
    del sin_tok_s["tok_s"]  # backend sin `timings`
    assert refs.registrar(sin_tok_s) is False
    assert refs.registrar(_log(40.0)) is True
    assert refs.ventana(MODELO) == [40.0]


def test_cada_modelo_tiene_su_ventana_y_el_resumen_lo_muestra() -> None:
    refs = ritmo.Referencias()
    for _ in range(12):
        refs.registrar(_log(100.0, model="rapido"))
    for _ in range(3):
        refs.registrar(_log(10.0))
    assert refs.medir(MODELO, 10.0) == {}  # 3 muestras propias: sin referencia
    assert refs.resumen() == [
        {"modelo": MODELO, "tramo": None, "mediana": None, "muestras": 3},
        {"modelo": "rapido", "tramo": None, "mediana": 100.0, "muestras": 12},
    ]


@pytest.mark.parametrize(
    ("modelo", "tok_s", "tokens_in"),
    [
        (None, 15.0, 500),
        (MODELO, None, 500),
        (MODELO, "15", 500),
        (MODELO, float("nan"), 500),
        (MODELO, float("inf"), 500),
        (MODELO, -3.0, 500),
        (MODELO, 0, 500),
        (MODELO, True, 500),
        (MODELO, 15.0, "mucho"),
        (["lista"], 15.0, 500),
        ("otro-modelo", 15.0, 500),
    ],
)
def test_medir_con_entrada_rara_devuelve_vacio_sin_lanzar(modelo, tok_s, tokens_in) -> None:
    refs = ritmo.Referencias()
    for _ in range(10):
        refs.registrar(_log(40.0))
    try:
        r = refs.medir(modelo, tok_s, tokens_in)
    except Exception as e:  # observar no puede romper la tool (REQ-028)
        r = f"excepcion {type(e).__name__}"
    if tokens_in == "mucho":
        # Un `tokens_in` raro no impide medir con una sola referencia: no se usa.
        assert r == {"ritmo_rel": 0.38, "lento": True}
    else:
        assert r == {}


@pytest.mark.parametrize(
    "evento", [None, "texto", 7, [], {"model": MODELO, "ok": True, "tokens_out": "x", "tok_s": 1}]
)
def test_registrar_con_entrada_rara_no_lanza(evento) -> None:
    try:
        entro = ritmo.Referencias().registrar(evento)
    except Exception as e:
        entro = f"excepcion {type(e).__name__}"
    assert entro is False


# ---------------------------------------------------------------------------
# Siembra
# ---------------------------------------------------------------------------


def _fichero(carpeta: Path, anio_mes: str, n: int, tok_s: float) -> None:
    lineas = [json.dumps(_log(tok_s)) for _ in range(n)]
    (carpeta / f"usage-{anio_mes}.jsonl").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def test_sembrar_lee_el_mes_en_curso_y_el_anterior(tmp_path: Path) -> None:
    # A dia 2 del mes el mes en curso tiene poco: sin el anterior la ventana se queda en 20.
    _fichero(tmp_path, "202609", 30, 40.0)
    _fichero(tmp_path, "202610", 20, 40.0)
    refs = ritmo.Referencias()
    ritmo.sembrar_desde_log(refs, tmp_path, datetime(2026, 10, 2, tzinfo=UTC))
    ventana = refs.ventana(MODELO)
    assert len(ventana) == 50


def test_sembrar_no_lee_otros_meses(tmp_path: Path) -> None:
    _fichero(tmp_path, "202608", 15, 100.0)  # dos meses atras: fuera
    _fichero(tmp_path, "202609", 10, 40.0)
    _fichero(tmp_path, "202610", 10, 40.0)
    _fichero(tmp_path, "202611", 15, 100.0)  # futuro (reloj cambiado): fuera
    refs = ritmo.Referencias()
    n = ritmo.sembrar_desde_log(refs, tmp_path, datetime(2026, 10, 2, tzinfo=UTC))
    assert n == 20
    assert refs.ventana(MODELO) == [40.0] * 20


def test_sembrar_en_enero_lee_diciembre_del_anio_anterior(tmp_path: Path) -> None:
    _fichero(tmp_path, "202512", 10, 40.0)
    _fichero(tmp_path, "202601", 5, 40.0)
    refs = ritmo.Referencias()
    assert ritmo.sembrar_desde_log(refs, tmp_path, datetime(2026, 1, 2, tzinfo=UTC)) == 15


def test_sembrar_sin_ficheros_da_cero(tmp_path: Path) -> None:
    refs = ritmo.Referencias()
    ahora = datetime(2026, 10, 2, tzinfo=UTC)
    assert ritmo.sembrar_desde_log(refs, tmp_path / "no-existe", ahora) == 0
    assert refs.resumen() == []


def test_una_linea_corrupta_no_rompe_la_siembra() -> None:
    lineas = [json.dumps(_log(40.0)) for _ in range(12)]
    lineas.insert(5, '{"model": "modelo-a", "ok": tru')  # linea cortada a medio escribir
    refs = ritmo.Referencias()
    try:
        n = refs.sembrar(lineas)
    except Exception as e:
        n = f"excepcion {type(e).__name__}"
    assert n == 12, f"la siembra no tolera una linea corrupta: {n}"
