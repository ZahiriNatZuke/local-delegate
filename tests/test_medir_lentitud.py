"""El control de lentitud de REQ-025 (`scripts/medir_lentitud.py`), con datos sinteticos.

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

RAIZ = Path(__file__).parents[1]


def _cargar():
    spec = importlib.util.spec_from_file_location(
        "medir_lentitud", RAIZ / "scripts" / "medir_lentitud.py"
    )
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["medir_lentitud"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


ml = _cargar()

MODELO = "modelo-a"


def _ev(i: int, tok_s: float, *, tokens_out: int = 100, tokens_in: int = 500, **extra) -> dict:
    return {
        "id": i,
        "ts": float(i),
        "modelo": MODELO,
        "tok_s": tok_s,
        "tokens_out": tokens_out,
        "tokens_in": tokens_in,
        **extra,
    }


# ---------------------------------------------------------------------------
# La regla: una pieza por test
# ---------------------------------------------------------------------------


def test_ventana_de_50_la_mediana_usa_los_50_ultimos() -> None:
    # 31 eventos viejos a 100 tok/s y 28 nuevos a 40. La ventana de los 50 ultimos del 60.º evento
    # tiene 22 viejos y 28 nuevos (mediana 40); la historia entera tiene 31 viejos de 59 (mediana
    # 100). Con solo 10 viejos la mediana de toda la historia tambien daria 40 y el mutante no
    # mutaria.
    eventos = [_ev(i, 100.0) for i in range(31)] + [_ev(i, 40.0) for i in range(31, 59)]
    eventos.append(_ev(59, 40.0))
    resultado = ml.calcular_lentitud(eventos)
    assert len(resultado) == 60
    ref = resultado[59]["ref"]
    assert ref == 40.0
    assert resultado[59]["ritmo_rel"] == 1.0
    assert resultado[59]["lento"] is False


def test_minimo_de_10_el_evento_10_no_tiene_referencia_y_el_11_si() -> None:
    eventos = ml.calcular_lentitud([_ev(i, 40.0) for i in range(11)])
    assert eventos[9].get("ritmo_rel") is None
    assert "ref" not in eventos[9] and "lento" not in eventos[9]
    assert eventos[10]["ritmo_rel"] == 1.0
    assert eventos[10]["lento"] is False


def test_tokens_out_menor_que_8_no_entra_en_la_ventana() -> None:
    # 12 eventos buenos a 40 tok/s y 15 de 3 tokens a 5 tok/s: sin el filtro, los cortos son mayoria
    # de la ventana y arrastran la mediana a 5.
    eventos = [_ev(i, 40.0) for i in range(12)]
    eventos += [_ev(i, 5.0, tokens_out=3) for i in range(12, 27)]
    eventos.append(_ev(27, 40.0))
    resultado = ml.calcular_lentitud(eventos)
    ref = resultado[27]["ref"]
    assert ref == 40.0
    assert all("ritmo_rel" not in e for e in resultado[12:27])  # los cortos no se evaluan


def test_el_evento_con_exactamente_8_tokens_si_entra() -> None:
    eventos = [_ev(i, 40.0, tokens_out=8) for i in range(10)] + [_ev(10, 40.0)]
    assert ml.calcular_lentitud(eventos)[10]["ref"] == 40.0


def test_la_referencia_no_mira_el_futuro() -> None:
    # Ids en orden temporal; la lista llega desordenada. El 12.º va a 10 tok/s tras 12 a 40.
    ordenados = [_ev(i, 40.0) for i in range(12)] + [_ev(12, 10.0)]
    desordenados = [ordenados[i] for i in (7, 12, 0, 3, 11, 5, 1, 9, 2, 10, 4, 8, 6)]
    resultado = ml.calcular_lentitud(desordenados)
    marcados = [e["id"] for e in resultado if e.get("lento")]
    assert marcados == [12]
    assert [e["id"] for e in resultado] == list(range(13))


def test_un_evento_fallido_no_forma_la_velocidad_normal() -> None:
    eventos = [_ev(i, 40.0) for i in range(10)]
    eventos += [_ev(i, 5.0, ok=False) for i in range(10, 25)]
    eventos.append(_ev(25, 40.0))
    resultado = ml.calcular_lentitud(eventos)
    assert resultado[25]["ref"] == 40.0
    assert "ritmo_rel" not in resultado[12]  # el fallido tampoco se evalua


def test_cada_modelo_tiene_su_ventana() -> None:
    lentos = [{**_ev(i, 100.0), "modelo": "rapido"} for i in range(12)]
    lentos += [_ev(100 + i, 10.0) for i in range(12)]
    resultado = ml.calcular_lentitud(lentos)
    assert not any(e.get("lento") for e in resultado)  # 10 tok/s es normal para modelo-a


def test_el_umbral_es_estricto() -> None:
    base = [_ev(i, 40.0) for i in range(10)]
    justo = ml.calcular_lentitud([*base, _ev(10, 20.0)])[10]  # ritmo 0,50 exacto
    debajo = ml.calcular_lentitud([*base, _ev(10, 19.6)])[10]  # ritmo 0,49
    assert justo["ritmo_rel"] == 0.5 and justo["lento"] is False
    assert debajo["ritmo_rel"] == 0.49 and debajo["lento"] is True


def test_por_tramos_un_evento_de_12k_a_18_tok_s_no_es_lento() -> None:
    # Cortos (< 2k) a 40 tok/s y largos (> 10k) a 26. Con una sola referencia, la mediana la ponen
    # los cortos (mayoria) y el evento largo a 18 sale a 0,45 (lento con el umbral por defecto,
    # 0,5); por tramos se compara con los largos (mediana 26) y sale a 0,69: no es lento.
    eventos = [_ev(i, 40.0, tokens_in=500) for i in range(20)]
    eventos += [_ev(20 + i, 26.0, tokens_in=12_000) for i in range(12)]
    eventos.append(_ev(32, 18.0, tokens_in=12_000))
    lento = ml.calcular_lentitud(eventos, por_tramos=True)[-1]["lento"]
    assert not lento
    una = ml.calcular_lentitud(eventos, por_tramos=False)[-1]
    assert una["lento"] is True


def test_por_tramos_cada_tramo_pide_su_propio_minimo() -> None:
    eventos = [_ev(i, 40.0, tokens_in=500) for i in range(20)]
    eventos += [_ev(20 + i, 26.0, tokens_in=12_000) for i in range(9)]
    eventos.append(_ev(29, 5.0, tokens_in=12_000))  # solo 9 largos antes: sin referencia
    resultado = ml.calcular_lentitud(eventos, por_tramos=True)
    assert "ritmo_rel" not in resultado[-1]


@pytest.mark.parametrize(
    ("tokens", "tramo"),
    [
        (0, "<2k"),
        (1_999, "<2k"),
        (2_000, "2k-10k"),
        (10_000, "2k-10k"),
        (10_001, ">10k"),
        (None, None),
    ],
)
def test_los_limites_de_los_tramos(tokens: int | None, tramo: str | None) -> None:
    assert ml.tramo_de(tokens) == tramo


@pytest.mark.parametrize(
    ("corta", "larga", "esperado"),
    [
        (40.0, 30.0, "una referencia"),  # 0,75 exacto: no es menor
        (40.0, 29.9, "por tramos"),
        (40.0, None, "una referencia"),
        (None, 20.0, "una referencia"),
    ],
)
def test_decision_de_la_referencia(corta, larga, esperado) -> None:
    assert ml.decidir_referencia({"<2k": corta, ">10k": larga}) == esperado


# ---------------------------------------------------------------------------
# Datos: cruce con el log y agrupacion por evento
# ---------------------------------------------------------------------------

T0 = datetime(2026, 10, 1, tzinfo=UTC).timestamp()


def _fila(
    id_: int,
    fin: float,
    *,
    modelo: str = MODELO,
    salida: int = 100,
    tps: float = 40.0,
    entrada: int = 500,
    dur: float = 8.0,
) -> dict:
    return {
        "id": id_,
        "fin": fin,
        "modelo": modelo,
        "entrada": entrada,
        "salida": salida,
        "tps": tps,
        "dur": dur,
    }


def _llamada(fin: float, *, latencia: float = 10.0, modelo: str = MODELO, ok: bool = True) -> dict:
    return {
        "fin": fin,
        "ini": fin - latencia,
        "modelo": modelo,
        "ok": ok,
        "tool": "local_summarize",
    }


def test_las_filas_de_un_mismo_evento_se_agrupan_con_sigma_salida_sobre_sigma_ms() -> None:
    llamadas = [_llamada(T0 + 100)]
    filas = [
        _fila(1, T0 + 96, salida=100, tps=50.0, dur=4.0, entrada=300),  # 2 s de generacion
        _fila(2, T0 + 99, salida=100, tps=25.0, dur=3.0, entrada=900),  # 4 s de generacion
    ]
    eventos = ml.agrupar_por_evento(filas, llamadas)
    assert len(eventos) == 1
    e = eventos[0]
    assert e["origen"] == "PC" and e["filas"] == [1, 2]
    assert e["tokens_out"] == 200
    assert e["tok_s"] == pytest.approx(200 / 6)
    assert e["tokens_in"] == 900  # la mayor entrada de una llamada, no la suma


def test_una_fila_sin_llamada_en_el_log_es_un_evento_no_pc() -> None:
    eventos = ml.agrupar_por_evento([_fila(7, T0 + 500)], [_llamada(T0 + 100)])
    assert [(e["origen"], e["filas"]) for e in eventos] == [("no-PC", [7])]


def test_una_llamada_de_otro_modelo_no_reclama_la_fila() -> None:
    eventos = ml.agrupar_por_evento([_fila(1, T0 + 99)], [_llamada(T0 + 100, modelo="otro")])
    assert eventos[0]["origen"] == "no-PC"


def test_con_dos_llamadas_simultaneas_gana_la_mas_ajustada() -> None:
    larga = _llamada(T0 + 100, latencia=60.0)
    ajustada = _llamada(T0 + 101, latencia=9.0)
    eventos = ml.agrupar_por_evento([_fila(1, T0 + 100, dur=8.0)], [larga, ajustada])
    assert len(eventos) == 1 and eventos[0]["ok"] is True
    assert eventos[0]["ts"] == T0 + 100


def test_una_llamada_con_ok_falso_deja_el_evento_fuera_de_la_ventana() -> None:
    eventos = ml.agrupar_por_evento([_fila(1, T0 + 99)], [_llamada(T0 + 100, ok=False)])
    assert eventos[0]["ok"] is False


# ---------------------------------------------------------------------------
# Copia de solo lectura y controles sobre una base sintetica
# ---------------------------------------------------------------------------

ESQUEMA = """
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


def _crear_db(ruta: Path, filas: list[tuple]) -> None:
    con = sqlite3.connect(ruta)
    con.execute(ESQUEMA)
    con.executemany(
        "insert into activity (id, ts_created, model_id, resp_status_code, cache_tokens,"
        " input_tokens, output_tokens, tokens_per_second, duration_ms) values (?,?,?,?,?,?,?,?,?)",
        filas,
    )
    con.commit()
    con.close()


def _log(carpeta: Path, llamadas: list[dict]) -> None:
    lineas = [
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
        for c in llamadas
    ]
    (carpeta / "usage-202610.jsonl").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def _escenario(tmp_path: Path, *, pc_lento: bool, mac_lenta: bool) -> tuple[Path, Path]:
    """Qwen3.6 de la PC (12 normales y, si se pide, 12 lentos) y 3 filas de la Mac 570, 571, 573."""
    modelo = ml.MODELO_CONTROL
    filas, llamadas = [], []
    id_ = 100
    for i in range(12):
        fin = T0 + 100 * i
        filas.append((id_ + i, int(fin), modelo, 200, 0, 500, 100, 40.0, 8000))
        llamadas.append({"fin": fin + 1, "ini": fin - 9, "modelo": modelo, "ok": True})
    if pc_lento:
        for i in range(12, 24):
            fin = T0 + 100 * i
            filas.append((id_ + i, int(fin), modelo, 200, 0, 500, 100, 10.0, 8000))
            llamadas.append({"fin": fin + 1, "ini": fin - 9, "modelo": modelo, "ok": True})
    for k, fila in enumerate(ml.FILAS_ESPERADAS):
        tps = 8.0 if mac_lenta else 40.0
        filas.append((fila, int(T0 + 5000 + 100 * k), modelo, 200, 0, 500, 100, tps, 8000))
    carpeta = tmp_path / "copia"
    carpeta.mkdir()
    _crear_db(carpeta / "metrics.db", filas)
    logs = tmp_path / "logs"
    logs.mkdir()
    _log(logs, llamadas)
    return carpeta, logs


def test_copiar_metrics_copia_los_tres_ficheros_sin_tocar_el_original(tmp_path: Path) -> None:
    origen = tmp_path / "real"
    origen.mkdir()
    _crear_db(origen / "metrics.db", [(1, int(T0), MODELO, 200, 0, 1, 10, 40.0, 1000)])
    (origen / "metrics.db-wal").write_bytes(b"wal")
    (origen / "metrics.db-shm").write_bytes(b"shm")
    antes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in origen.iterdir()}
    copiados = ml.copiar_metrics(origen, tmp_path / "copia")
    assert sorted(p.name for p in copiados) == ["metrics.db", "metrics.db-shm", "metrics.db-wal"]
    despues = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in origen.iterdir()}
    assert antes == despues
    assert (tmp_path / "copia" / "metrics.db-wal").read_bytes() == b"wal"


def test_leer_filas_abre_en_solo_lectura_y_descarta_lo_que_no_es_generacion(tmp_path: Path) -> None:
    ruta = tmp_path / "metrics.db"
    _crear_db(
        ruta,
        [
            (1, int(T0), MODELO, 200, 5, 100, 10, 40.0, 2000),
            (2, int(T0), MODELO, 500, 0, 100, 10, 40.0, 2000),  # error
            (3, int(T0), MODELO, 200, 0, 100, 0, 0.0, 2000),  # sin generacion
        ],
    )
    filas = ml.leer_filas(ruta)
    assert [f["id"] for f in filas] == [1]
    assert filas[0]["entrada"] == 105  # entrada + cache
    con = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("delete from activity")
    con.close()


def test_control_b_marca_las_tres_filas_de_la_mac(tmp_path: Path) -> None:
    carpeta, logs = _escenario(tmp_path, pc_lento=False, mac_lenta=True)
    r = ml.medir(ml.leer_filas(carpeta / "metrics.db"), ml.leer_llamadas(logs), desde="2026-10-01")
    assert r["b"]["cumple"] is True
    assert r["b"]["marcadas_de_las_esperadas"] == [570, 571, 573]
    assert r["a"]["marcados"] == 0 and r["a"]["supera_el_tope"] is False
    assert r["a"]["eventos_pc"] == 12


def test_control_b_falla_si_la_mac_iba_a_velocidad_normal(tmp_path: Path) -> None:
    carpeta, logs = _escenario(tmp_path, pc_lento=False, mac_lenta=False)
    r = ml.medir(ml.leer_filas(carpeta / "metrics.db"), ml.leer_llamadas(logs), desde="2026-10-01")
    assert r["b"]["cumple"] is False
    assert r["b"]["faltan"] == [570, 571, 573]


def test_control_a_supera_el_tope_cuando_la_pc_va_lenta(tmp_path: Path) -> None:
    carpeta, logs = _escenario(tmp_path, pc_lento=True, mac_lenta=True)
    r = ml.medir(ml.leer_filas(carpeta / "metrics.db"), ml.leer_llamadas(logs), desde="2026-10-01")
    assert r["a"]["supera_el_tope"] is True
    # 24 eventos de la PC; los 10 primeros no tienen referencia; de los 14 restantes, 12 van lentos.
    assert (r["a"]["con_referencia"], r["a"]["marcados"]) == (14, 12)
    assert r["a"]["pct_sobre_con_referencia"] == 85.71


def test_la_ventana_de_fechas_cuenta_solo_los_eventos_de_dentro(tmp_path: Path) -> None:
    carpeta, logs = _escenario(tmp_path, pc_lento=True, mac_lenta=True)
    # Los lentos de la PC empiezan en T0 + 1200 s (2026-10-01T00:20:00Z): una ventana que termina
    # antes no los cuenta, aunque la ventana de referencia se alimenta con todo el historial.
    r = ml.medir(
        ml.leer_filas(carpeta / "metrics.db"),
        ml.leer_llamadas(logs),
        desde="2026-10-01",
        hasta="2026-10-01T00:15:00",
    )
    assert r["a"]["marcados"] == 0
    assert r["a"]["eventos_pc"] == 10


@pytest.mark.parametrize(
    ("pc_lento", "mac_lenta", "codigo"),
    [(False, True, 0), (True, True, 3), (False, False, 4)],
)
def test_main_devuelve_el_codigo_de_parada(tmp_path, capsys, pc_lento, mac_lenta, codigo) -> None:
    carpeta, logs = _escenario(tmp_path, pc_lento=pc_lento, mac_lenta=mac_lenta)
    rc = ml.main(["--copia", str(carpeta), "--logs", str(logs), "--desde", "2026-10-01"])
    salida = json.loads(capsys.readouterr().out)
    assert rc == codigo
    assert "referencia_elegida" in salida


def test_main_copia_desde_el_origen_y_no_toca_el_original(tmp_path, capsys) -> None:
    carpeta, logs = _escenario(tmp_path, pc_lento=False, mac_lenta=True)
    antes = hashlib.sha256((carpeta / "metrics.db").read_bytes()).hexdigest()
    rc = ml.main(
        [
            "--origen",
            str(carpeta),
            "--copia",
            str(tmp_path / "otra"),
            "--logs",
            str(logs),
            "--desde",
            "2026-10-01",
        ]
    )
    capsys.readouterr()
    assert rc == 0
    assert (tmp_path / "otra" / "metrics.db").is_file()
    assert hashlib.sha256((carpeta / "metrics.db").read_bytes()).hexdigest() == antes


def test_main_sin_copia_devuelve_2(tmp_path, capsys) -> None:
    assert ml.main(["--copia", str(tmp_path / "vacia"), "--logs", str(tmp_path)]) == 2
    assert "No hay copia" in capsys.readouterr().err
